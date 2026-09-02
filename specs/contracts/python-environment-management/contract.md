# Python-Environment-Management Contract

This is the cross-OS abstract contract for the
**python-environment-management** feature. Every `codecraftai-sysman-*`
package that ships a Python-environment manager MUST honor this
contract.

Unlike most contracts in this folder, the reference implementation is
not a per-OS package — it is the shared base class
[`ccai.sysman.common.pythonenvironmentmanagementbase`](../../../source/packages/ccai/sysman/common/pythonenvironmentmanagementbase.py)
in `codecraftai-sysman-common`, specified at
[`specs/python-environment-management-base/`](../../python-environment-management-base/).
The tools this feature drives — CPython's `venv` module and `pip` — are
identical on every OS, so the verbs are implemented once in the base
and per-OS packages contribute only a *layout* (interpreter location,
launcher, directory probes) and a *prerequisite* step that installs
the interpreter through that OS's package manager.

---

## Scope

The python-environment-management feature provides idempotent,
auditable deployment of Python virtual environments with a declared
set of dependencies. It covers:

- Creating a virtual environment from a chosen base interpreter.
- Removing a virtual environment.
- Installing / upgrading / uninstalling PEP 508 requirement specifiers.
- Installing from requirements files with optional constraints files.
- Upgrading `pip` inside the environment.
- Converging an environment onto a declarative `PythonEnvSpec`
  (`deploy`).
- Querying environment existence, validity, interpreter version,
  installed distributions, and a `pip freeze` snapshot.
- Installing the OS packages that provide the base interpreter
  (`ensure_prerequisites`, per-OS).
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.
Directory probes and removal also go through the runner using
OS-native tools (Convention 1 in the README) — never direct
filesystem I/O.

Out of scope: `conda` / `mamba` environments, `pyenv` interpreter
builds, `poetry` / `pipenv` / `uv` project workflows, wheel building,
and per-project lock-file generation. See §Out of Scope.

---

## Verbs

Every OS implementation MUST expose a `PythonEnvironmentManager`
class (the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs. All but `ensure_prerequisites` are
inherited from the shared base and MUST NOT be overridden to change
their argv shape.

| Verb | Signature | Kind |
|------|-----------|------|
| `create_environment` | `(path: str, *, interpreter: list[str] \| None, system_site_packages: bool \| None, upgrade_pip: bool \| None) → PythonEnvActionResult` | Write |
| `remove_environment` | `(path: str) → PythonEnvActionResult` | Write |
| `install_packages` | `(path: str, packages: list[str], *, upgrade: bool) → PythonEnvActionResult` | Write |
| `install_requirements` | `(path: str, requirements_files: list[str], *, constraints_files: list[str] \| None, upgrade: bool) → PythonEnvActionResult` | Write |
| `uninstall_packages` | `(path: str, names: list[str]) → PythonEnvActionResult` | Write |
| `upgrade_pip` | `(path: str) → PythonEnvActionResult` | Write |
| `deploy` | `(spec: PythonEnvSpec) → PythonEnvDeployResult` | Write (composite) |
| `ensure_prerequisites` | `(packages: list[str] \| None) → list[<Os>PackageActionResult]` | Write (per-OS) |
| `environment_exists` | `(path: str) → bool` | Read |
| `is_valid_environment` | `(path: str) → bool` | Read |
| `get_python_version` | `(path: str) → str \| None` | Read |
| `list_installed` | `(path: str) → list[PythonPackageInfo]` | Read |
| `get_package_info` | `(path: str, name: str) → PythonPackageInfo \| None` | Read |
| `is_package_installed` | `(path: str, name: str) → bool` | Read |
| `freeze` | `(path: str) → list[str]` | Read |
| `get_environment_info` | `(path: str) → PythonEnvInfo \| None` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_environment` MUST return `SKIPPED`
   when `is_valid_environment(path)` is already true.
   `remove_environment` MUST return `SKIPPED` when no directory
   exists at `path`. `install_packages` (with `upgrade=False`) MUST
   return `SKIPPED` when every specifier is already satisfied per
   the conservative probe in §Requirement Probe. `uninstall_packages`
   MUST return `SKIPPED` when none of the names are installed.
2. **Never-skip verbs.** `install_requirements` and `upgrade_pip` are
   operational and MUST NOT skip; pip is itself idempotent for both.
3. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   with `command` populated and MUST NOT invoke the runner — not
   even for the idempotency probe.
4. **Error surface.** Failures MUST return `FAILED` with `exit_code`,
   `stdout`, `stderr`, and `command` populated.
5. **Argument validation.** `install_packages`,
   `install_requirements`, and `uninstall_packages` MUST raise
   `ValueError` for an empty list before touching the runner.
6. **pip invocation form.** Every pip call MUST be
   `<venv python> -m pip --disable-pip-version-check --no-input <sub-command> …`
   so the argv is OS-independent and immune to a missing or stale
   `pip` console-script shim.
7. **Post-create pip upgrade.** When the effective `upgrade_pip` is
   True, `create_environment` upgrades pip after a successful
   creation; a failed upgrade yields `FAILED` with
   `message="environment created but the pip upgrade failed"`.
8. **`deploy` ordering and short-circuit.** `deploy` MUST execute, in
   order: optional `remove_environment` (when `spec.recreate`),
   `create_environment` (with pip upgrade deferred), optional
   `upgrade_pip`, optional `install_requirements`, optional
   `install_packages`; and MUST stop at the first `FAILED` step. The
   aggregate `status` is `FAILED` if any step failed, `DRY_RUN` under
   dry-run, `SUCCESS` if any step succeeded, else `SKIPPED`.
9. **Prerequisite delegation.** `ensure_prerequisites` MUST delegate
   to the OS's existing `package-management` manager (apt, dnf,
   brew, winget) sharing the same runner and the manager's
   `dry_run` / `elevated` flags, and MUST stop at the first `FAILED`
   package.

### Method-level invariants (reads)

1. **No elevation.** Reads and idempotency probes MUST NOT pass
   `elevated=True` to the runner.
2. **Graceful degradation.** `environment_exists`,
   `is_valid_environment`, `get_python_version`, `get_package_info`,
   `is_package_installed`, and `get_environment_info` return
   `False` / `None` for an absent environment. `list_installed` and
   `freeze` MAY raise `PythonEnvQueryError` when pip exits non-zero
   or emits unparsable output.
3. **Pure parsing.** `pip list --format json` is parsed with the
   standard library; no third-party version library is required.

---

## Requirement Probe

The `install_packages` idempotency probe compares each specifier to
`pip list --format json` output. It answers "satisfied" only when it
is certain and otherwise defers to pip:

| Specifier form | Satisfied when |
|----------------|----------------|
| `name`, `name[extras]` | The (PEP 503-normalised) name is installed. |
| `name==X`, `name===X` | Installed version string equals `X`. |
| `name==X.*` | Installed version equals `X` or starts with `X.`. |
| `name!=X` | Installed and version differs from `X`. |
| `name>=X`, `>X`, `<=X`, `<X` | Both versions are purely dotted-numeric and the comparison holds (trailing zeros normalised). |
| `name~=X.Y` | Numeric, same prefix through `X`, and `>= X.Y`. |
| `name; marker` | Marker dropped for the probe; pip still receives it. |
| URL, path, `-e`, `@` forms | Never satisfied (pip decides). |
| Pre-release / local / epoch versions with ordering operators | Never satisfied (pip decides). |

---

## Data Models

Every OS implementation MUST expose these dataclasses and the status
enum, each aliased with the OS prefix (see §Naming). They are defined
once in the shared base.

### `PythonEnvActionStatus` (enum, alias of `ActionStatus`)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and failed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `PythonEnvActionResult` (dataclass, extends `FeatureActionResult`)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `PythonEnvActionStatus` | Outcome category. |
| `detail` | `str \| None` | The environment path, or the stable token `elevation_blocked` (Windows). |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed, with URL credentials redacted. |
| `path` | `str \| None` | The environment root targeted. |
| `packages` | `list[str] \| None` | Specifiers / files / names targeted, when the verb takes any. |
| `message` | `str \| None` | Human-readable detail for `SKIPPED` / `FAILED`. |

### `PythonEnvDeployResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `PythonEnvActionStatus` | Aggregate per invariant 8. |
| `path` | `str` | The environment root. |
| `steps` | `list[PythonEnvActionResult]` | Every step result in execution order. |
| `message` | `str \| None` | One-line summary of the failed step, when any. |

### `PythonEnvSpec` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | — | The environment root. |
| `packages` | `list[str]` | `[]` | PEP 508 specifiers to install. |
| `requirements_files` | `list[str]` | `[]` | `-r` files (paths on the target host). |
| `constraints_files` | `list[str]` | `[]` | `-c` files applied to the requirements install. |
| `interpreter` | `list[str] \| None` | `None` | Per-spec base-interpreter argv override. |
| `system_site_packages` | `bool \| None` | `None` | Per-spec override of the config flag. |
| `upgrade_pip` | `bool \| None` | `None` | Per-spec override of the config flag. |
| `upgrade_packages` | `bool` | `False` | Pass `--upgrade` and bypass the probe. |
| `recreate` | `bool` | `False` | Remove an existing environment first. |

### `PythonPackageInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Distribution name as pip reports it. |
| `version` | `str` | Installed version. |

### `PythonEnvInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Environment root. |
| `python_executable` | `str` | Interpreter path inside the environment. |
| `python_version` | `str \| None` | `platform.python_version()` of that interpreter. |
| `packages` | `list[PythonPackageInfo]` | Installed distributions. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `PythonEnvQueryError` | `list_installed` / `freeze` fail unexpectedly or emit unparsable output. Carries a redacted `command`, `exit_code`, `stderr`. |
| `ValueError` | A list argument to a write verb is empty. |

### `PythonEnvManagerConfig` (dataclass, extends `FeatureConfig`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |
| `base_interpreter` | `list[str] \| None` | `None` | Argv prefix for the creating interpreter; `None` uses the OS default (`python3` / `py -3`). |
| `index_url` | `str \| None` | `None` | `--index-url` for every install. |
| `extra_index_urls` | `list[str] \| None` | `None` | Repeated `--extra-index-url`. |
| `trusted_hosts` | `list[str] \| None` | `None` | Repeated `--trusted-host`. |
| `pip_options` | `list[str] \| None` | `None` | Extra tokens appended to every `pip install`. |
| `upgrade_pip` | `bool` | `True` | Upgrade pip after creation. |
| `system_site_packages` | `bool` | `False` | Create with `--system-site-packages`. |

Per-OS configs add: `prerequisite_packages: list[str] | None` on every
OS; `apt_options` (Ubuntu); `brew_user` (macOS);
`powershell_executable`, `winget_executable` (Windows).

---

## Layout Mapping

The abstract verbs never spell an OS path or shell tool. A
`PythonEnvironmentLayout` strategy supplies them:

| Concern | POSIX (Ubuntu, RHEL, macOS) | Windows |
|---------|-----------------------------|---------|
| Default base interpreter | `python3` | `py -3` (Python launcher) |
| Interpreter inside venv | `<path>/bin/python` | `<path>\Scripts\python.exe` |
| Directory-exists probe | `test -d <path>` | `powershell.exe -NoProfile -NonInteractive -Command "if (Test-Path -LiteralPath '<path>' -PathType Container) { exit 0 } else { exit 1 }"` |
| Recursive removal | `rm -rf <path>` | `powershell.exe … -Command "Remove-Item -LiteralPath '<path>' -Recurse -Force"` |
| Path joining | `posixpath` | `ntpath` |

Prerequisite packages per OS (defaults; all configurable):

| OS | Package manager | Default prerequisites | Why |
|----|-----------------|-----------------------|-----|
| Ubuntu | `UbuntuPackageManager` (apt) | `python3`, `python3-venv`, `python3-pip` | Debian splits `ensurepip` into `python3-venv`; stock images cannot run `python3 -m venv`. |
| RHEL | `PackageManager` (dnf) | `python3`, `python3-pip` | Minimal images omit the interpreter. |
| macOS | `MacosPackageManager` (brew) | `python` | `/usr/bin/python3` is an Xcode CLT stub that prompts when the tools are absent. |
| Windows | `WindowsPackageManager` (winget) | `Python.Python.3.12` | No interpreter ships with Windows; the winget build installs the `py` launcher. |
| UEFI | N/A | — | No interpreter concept; the contract does not apply. |

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. The resulting tree is root- / Administrator-owned. |
| Config `elevated=True`, read method or probe | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| macOS `ensure_prerequisites` | Inherits the Homebrew inversion from `package-management`: brew never elevates; `brew_user` is forwarded for the `sudo -u` wrap. venv / pip calls follow the standard rule. |
| Windows `elevation_blocked` | Surfaced as `detail="elevation_blocked"` on the `FAILED` result (Convention 6). |

---

## Credential Safety

`index_url` / `extra_index_urls` may embed a private-index token in
the URL userinfo (`https://user:token@host/simple`). The runner
receives the real URL; every recorded `command` (on results and on
`PythonEnvQueryError`) passes through `redact_command`, which
replaces the userinfo with `***`. This is the argv-last-resort case
of Convention 12: pip offers no stdin channel for index credentials
short of a `netrc` / keyring file, which is out of scope here.

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>PythonEnvironmentManager
                │            │
                │            └── ensure_prerequisites() ──► <Os>PackageManager (same runner)
                │
                │  .run(argv, elevated=…)
                ▼
          ICommandRunner
                │
        ┌───────┴────────┐
        ▼                ▼
  LocalCommandRunner   SSH / WinRM CommandRunner
        │                │
        └────────┬───────┘
                 │  aspects compose here
                 ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner` and a `PythonEnvManagerConfig` (or
   OS-prefixed subclass) in their constructor.
2. Never construct their own subprocess or touch the filesystem
   directly.
3. Not hold state across calls beyond the config and layout.
4. Be safe under any aspect composition on the runner.

Long-running pip installs SHOULD be paired with a `TimeoutAspect`
sized for the dependency set; the manager itself sets no timeout.

---

## Naming

Concrete types per OS are aliases of the shared base types, prefixed
with the full Pascal-case OS name. The manager and config are real
subclasses.

| Abstract | Ubuntu | RHEL | macOS | Windows |
|----------|--------|------|-------|---------|
| `PythonEnvironmentManager` | `UbuntuPythonEnvironmentManager` | `RedHatPythonEnvironmentManager` | `MacosPythonEnvironmentManager` | `WindowsPythonEnvironmentManager` |
| `PythonEnvManagerConfig` | `UbuntuPythonEnvManagerConfig` | `RedHatPythonEnvManagerConfig` | `MacosPythonEnvManagerConfig` | `WindowsPythonEnvManagerConfig` |
| `PythonEnvActionStatus` | `UbuntuPythonEnvActionStatus` | `RedHatPythonEnvActionStatus` | `MacosPythonEnvActionStatus` | `WindowsPythonEnvActionStatus` |
| `PythonEnvActionResult` | `UbuntuPythonEnvActionResult` | `RedHatPythonEnvActionResult` | `MacosPythonEnvActionResult` | `WindowsPythonEnvActionResult` |
| `PythonEnvDeployResult` | `UbuntuPythonEnvDeployResult` | `RedHatPythonEnvDeployResult` | `MacosPythonEnvDeployResult` | `WindowsPythonEnvDeployResult` |
| `PythonEnvSpec` | `UbuntuPythonEnvSpec` | `RedHatPythonEnvSpec` | `MacosPythonEnvSpec` | `WindowsPythonEnvSpec` |
| `PythonEnvInfo` | `UbuntuPythonEnvInfo` | `RedHatPythonEnvInfo` | `MacosPythonEnvInfo` | `WindowsPythonEnvInfo` |
| `PythonPackageInfo` | `UbuntuPythonPackageInfo` | `RedHatPythonPackageInfo` | `MacosPythonPackageInfo` | `WindowsPythonPackageInfo` |
| `PythonEnvQueryError` | `UbuntuPythonEnvQueryError` | `RedHatPythonEnvQueryError` | `MacosPythonEnvQueryError` | `WindowsPythonEnvQueryError` |

The RHEL package prefixes here (unlike its historical unprefixed
features) because the feature is new and mixed-OS coordinators are
the primary consumer.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same result sequence when driven by a real runner with
  aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

The shared base carries the bulk of the suite (in
`codecraftai-sysman-common`). Each OS implementation MUST additionally
include at minimum:

1. One test proving the expected layout is selected and the venv
   interpreter path / default launcher are correct for the OS.
2. One `ensure_prerequisites` test proving delegation to the OS
   package manager with the default package list and the manager's
   elevation flag.
3. One `ensure_prerequisites` test proving the override / config
   precedence.
4. One `ensure_prerequisites` test proving the sequence stops at the
   first `FAILED`.
5. One dry-run test proving `ensure_prerequisites` dispatches nothing.
6. One end-to-end `deploy` test asserting the OS-specific argv
   sequence (venv, pip upgrade, pip install).
7. Windows only: one test proving PowerShell probes use the configured
   executable and one proving `elevation_blocked` surfaces as the
   detail token.

The shared base suite MUST cover: one command-construction test per
write verb, one idempotency test per guarded write, dry-run for every
write, argument validation, every requirement-probe row in
§Requirement Probe, the deploy ordering and short-circuit, credential
redaction on the recorded command, reads-never-elevate, and both
layouts' argv.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Alternative environment managers (`conda`, `mamba`, `virtualenv`
  package, `uv venv`).
- Interpreter builds (`pyenv`, `python-build`).
- Project workflow tools (`poetry`, `pipenv`, `uv sync`, `pip-tools`).
- Lock-file generation and hash-checking mode (`--require-hashes`).
- Wheel building and caching policy beyond `pip_options`.
- Per-user vs system environment ownership changes (`chown`) after an
  elevated create — see `acl-management` / `user-group-management`.
- Copying environments between hosts or relocating an existing
  environment.
- Registering the environment with a service unit (see
  `service-management`).
- First-boot deployment before any runner can reach the host. That
  path exists — `codecraftai-provisioning/specs/python-env-bootstrap/`
  renders a `PythonEnvironmentSpec` (`ccai.interfaces.pythonenvspec`)
  into cloud-init with the same step order and pip argv as `deploy`,
  so a later run of this contract's manager converges as `SKIPPED` —
  but it is a provisioning feature, not part of this contract.

---

## Implementation Drift

Phase 4 implementation notes (initial landing):

- **Shared implementation, not just shared shapes.** Every verb
  except `ensure_prerequisites` lives in the common base. Per-OS
  packages add ~150 lines each. Contracts that predate this pattern
  put the verbs in each OS package; this one deliberately does not,
  because the underlying tools do not vary by OS.
- **Writes go through the shared `_dispatch`.** The base's
  `_dispatch_write` is a thin wrapper over
  `BaseFeatureManager._dispatch`, which since Phase 4 surfaces the
  Windows `elevation_blocked` extension as `detail="elevation_blocked"`
  itself. `DETAIL_ELEVATION_BLOCKED` is defined in `featurebase` and
  re-exported by the python-environment base.
- **Two-layer idempotency probe for `create_environment`.** A
  directory that exists but whose interpreter fails to run
  (half-created venv, wrong architecture after an OS upgrade) is
  treated as absent and recreated in place; `venv` tolerates an
  existing target directory.
- **`install_requirements` never skips.** The contract could have
  parsed requirements files through the runner (`cat`) and reused
  the probe; it does not, because requirement files support
  includes, options, and hashes that the conservative probe would
  have to refuse anyway.
- **`upgrade_pip` is a separate step in `deploy`.** `deploy` calls
  `create_environment(upgrade_pip=False)` and then `upgrade_pip`
  so an environment that already existed still gets its pip
  upgraded when the config asks for it.
- **RHEL prefixes.** `RedHatPythonEnvironmentManager` breaks the
  RHEL package's unprefixed naming convention on purpose; see
  §Naming.
