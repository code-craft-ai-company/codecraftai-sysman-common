# Design

## Overview

`ccai.sysman.common.pythonenvironmentmanagementbase` implements the
python-environment-management contract once for every OS.  The design inverts the
usual sysman split: the contract's *behaviour* lives in `codecraftai-sysman-common`
and per-OS packages contribute a strategy object plus one OS-specific verb.

The reason is that the underlying tools do not vary.  `python -m venv` and
`python -m pip` are part of CPython; their flags, exit codes, and `pip list
--format json` output are identical on Ubuntu, RHEL, macOS, and Windows.  Only
three things differ, and they are all filesystem / shell concerns:

| Concern | POSIX | Windows |
|---|---|---|
| Interpreter inside the venv | `bin/python` | `Scripts\python.exe` |
| Default launcher for the creating interpreter | `python3` | `py -3` |
| Directory probe / removal | `test -d`, `rm -rf` | PowerShell `Test-Path`, `Remove-Item` |

Those are isolated in `ccai.sysman.common.pythonenvironmentlayout`.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Maintenance Coordinator                          │
│   builds runner + <Os>PythonEnvManagerConfig, calls deploy(spec)     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  <Os>PythonEnvironmentManager        (per-OS package, ~150 lines)    │
│    _build_layout() → Posix | Windows layout                          │
│    ensure_prerequisites() → <Os>PackageManager (same runner)         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ inherits
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PythonEnvironmentManagementBase     (codecraftai-sysman-common)     │
│    create_environment  remove_environment  install_packages          │
│    install_requirements  uninstall_packages  upgrade_pip  deploy     │
│    environment_exists  is_valid_environment  get_python_version      │
│    list_installed  get_package_info  freeze  get_environment_info    │
│                                                                      │
│    argv builders ── _build_venv_create_argv / _build_pip_argv        │
│    probe ────────── _requirement_satisfied (conservative)            │
│    dispatch ─────── _dispatch_write (elevation, redaction, token)    │
└──────────────┬─────────────────────────────────────┬─────────────────┘
               │ uses                                │ uses
               ▼                                     ▼
┌────────────────────────────┐        ┌────────────────────────────────┐
│  PythonEnvironmentLayout   │        │  ICommandRunner                │
│  Posix / Windows           │        │  (local, SSH, WinRM + aspects) │
└────────────────────────────┘        └────────────────────────────────┘
```

---

## Components

### `PythonEnvironmentManagementBase`

**Location:** `source/packages/ccai/sysman/common/pythonenvironmentmanagementbase.py`

| Method | Kind | Command |
|---|---|---|
| `create_environment(path, *, interpreter, system_site_packages, upgrade_pip)` | Write | `<interp> -m venv [--system-site-packages] <path>` then optional pip upgrade |
| `remove_environment(path)` | Write | layout remove-tree argv |
| `install_packages(path, packages, *, upgrade)` | Write | `<py> -m pip <general> install [--upgrade] <index opts> <pip_options> <pkgs>` |
| `install_requirements(path, files, *, constraints_files, upgrade)` | Write | `… install [--upgrade] <index opts> <pip_options> -r f… -c c…` |
| `uninstall_packages(path, names)` | Write | `… uninstall -y <names>` |
| `upgrade_pip(path)` | Write | `… install --upgrade <index opts> pip` |
| `deploy(spec)` | Write | composite of the above |
| `environment_exists(path)` | Read | layout exists argv |
| `is_valid_environment(path)` | Read | exists + `get_python_version` |
| `get_python_version(path)` | Read | `<py> -c "import platform; print(platform.python_version())"` |
| `list_installed(path)` | Read | `… list --format json` |
| `get_package_info(path, name)` / `is_package_installed` | Read | via `list_installed` |
| `freeze(path)` | Read | `… freeze` |
| `get_environment_info(path)` | Read | exists + version + list |

`<general>` is always `--disable-pip-version-check --no-input`.  Both are general
pip options placed before the sub-command; the first suppresses the upgrade banner
on stderr, the second makes pip fail rather than block when it would prompt.

### `PythonEnvironmentLayout` and implementations

**Location:** `source/packages/ccai/sysman/common/pythonenvironmentlayout.py`

Abstract strategy with five methods (`default_interpreter_argv`, `join_path`,
`venv_python_path`, `build_directory_exists_argv`, `build_remove_tree_argv`).
`PosixPythonEnvironmentLayout` is stateless.  `WindowsPythonEnvironmentLayout`
carries the PowerShell executable and exposes `build_powershell_argv(script)` so
subclasses can reuse the canonical `-NoProfile -NonInteractive -Command` form.

### `PythonEnvManagerConfig`

See the contract's config table.  `base_interpreter` is an argv *prefix*
(`list[str]`), not a path, so `["py", "-3.12"]` and `["/usr/bin/python3.12"]` are
both expressible.

---

## Data Models

```python
PythonEnvActionStatus = ActionStatus          # SUCCESS / FAILED / SKIPPED / DRY_RUN

@dataclass
class PythonEnvActionResult(FeatureActionResult):
    path: str | None = None
    packages: list[str] | None = None
    message: str | None = None

@dataclass
class PythonPackageInfo:
    name: str
    version: str

@dataclass
class PythonEnvInfo:
    path: str
    python_executable: str
    python_version: str | None = None
    packages: list[PythonPackageInfo] = field(default_factory=list)

@dataclass
class PythonEnvSpec:
    path: str
    packages: list[str] = field(default_factory=list)
    requirements_files: list[str] = field(default_factory=list)
    constraints_files: list[str] = field(default_factory=list)
    interpreter: list[str] | None = None
    system_site_packages: bool | None = None
    upgrade_pip: bool | None = None
    upgrade_packages: bool = False
    recreate: bool = False

@dataclass
class PythonEnvDeployResult:
    status: PythonEnvActionStatus
    path: str
    steps: list[PythonEnvActionResult] = field(default_factory=list)
    message: str | None = None
```

---

## Idempotency Guards

| Verb | Probe | Skip condition |
|---|---|---|
| `create_environment` | `test -d` (or `Test-Path`) then `<py> -c …` | both succeed |
| `remove_environment` | `test -d` / `Test-Path` | probe fails |
| `install_packages` (`upgrade=False`) | `pip list --format json` | every specifier satisfied per the probe table |
| `uninstall_packages` | `pip list --format json` | no name present |
| `install_requirements`, `upgrade_pip` | none | never skip |

The requirement probe (`_parse_requirement`, `_clause_satisfied`, `_version_tuple`)
is deliberately conservative.  It uses only the standard library, so it refuses to
reason about pre-release, local, or epoch versions under ordering operators and
about URL / path / editable requirements; in every refused case it answers "not
satisfied" and pip — which is itself idempotent — makes the real decision.  The
cost of a false "not satisfied" is one redundant pip call; the cost of a false
"satisfied" would be a missing dependency, so the asymmetry is intentional.

---

## Dispatch and Redaction

`_dispatch_write` is a thin wrapper over `BaseFeatureManager._dispatch` that
passes `detail=path` and echoes `path` / `packages` as extra result fields.  The
shared helper maps exit 0 → `SUCCESS`, else `FAILED`; redacts the recorded
`command`; and (since Phase 4) replaces `detail` with the stable token
`DETAIL_ELEVATION_BLOCKED` when the runner's `RunResult` carries a truthy
`elevation_blocked` attribute (Convention 6).  The base originally called the
runner itself to read that attribute; the pass-through was upstreamed into
`_dispatch` so every manager benefits.

`redact_command` gained URL-userinfo scrubbing for this feature.  The runner
receives the real `--index-url https://user:token@host/simple`; the result, any
`PythonEnvQueryError`, and any log built from either see `https://***@host/simple`.

---

## Deploy Algorithm

```
steps = []
if spec.recreate:
    steps += remove_environment(path);  stop if FAILED
steps += create_environment(path, interpreter, system_site_packages, upgrade_pip=False);  stop if FAILED
if effective_upgrade_pip:
    steps += upgrade_pip(path);  stop if FAILED
if spec.requirements_files:
    steps += install_requirements(path, files, constraints, upgrade=spec.upgrade_packages);  stop if FAILED
if spec.packages:
    steps += install_packages(path, packages, upgrade=spec.upgrade_packages)
status = FAILED if any failed else DRY_RUN if config.dry_run else SUCCESS if any succeeded else SKIPPED
```

`create_environment` is called with `upgrade_pip=False` and the upgrade is a
separate step so that an environment which already existed (create → `SKIPPED`)
still gets pip upgraded when the config asks for it.

---

## Correctness Properties

1. **Venv argv.** `create_environment` dispatches exactly
   `<interp> -m venv [--system-site-packages] <path>` with interpreter precedence
   argument > config > layout.
2. **Create idempotency.** A valid environment yields `SKIPPED` and no write.
3. **Broken environment recreated.** Directory present + interpreter failing yields
   a create dispatch.
4. **Post-create pip upgrade.** Exactly one `pip install --upgrade pip` follows a
   successful create when `upgrade_pip` is True; none when False; none when create
   failed.
5. **Remove idempotency.** Absent directory yields `SKIPPED`.
6. **Pip argv.** Every pip call starts with
   `<venv python> -m pip --disable-pip-version-check --no-input`.
7. **Index option order.** `--index-url`, then each `--extra-index-url`, then each
   `--trusted-host`, then `pip_options`, then targets.
8. **Install idempotency.** All-satisfied specifiers yield `SKIPPED`; a single
   unsatisfied specifier dispatches.
9. **Upgrade bypass.** `upgrade=True` never calls `pip list`.
10. **Empty-list guard.** Empty `packages` / `requirements_files` / `names` raise
    `ValueError` with zero runner calls.
11. **Requirements never skip.** `install_requirements` never calls `pip list`.
12. **Uninstall guard.** No names installed yields `SKIPPED`; any present dispatches
    the full list.
13. **Deploy ordering.** Writes appear in the order remove, venv, pip upgrade,
    requirements, packages.
14. **Deploy short-circuit.** The first `FAILED` step is the last step.
15. **Deploy aggregate.** FAILED > DRY_RUN > SUCCESS > SKIPPED.
16. **Dry-run safety.** Every write verb under `dry_run=True` returns `DRY_RUN`
    with `command` set and zero runner calls.
17. **Reads never elevate.** Every probe and read passes `elevated=False`.
18. **Writes elevate when configured.** Every write passes `elevated=config.elevated`.
19. **Elevation-blocked token.** A truthy `elevation_blocked` on the `RunResult`
    sets `detail="elevation_blocked"` (delivered by the shared `_dispatch`).
20. **Redaction.** URL userinfo never appears on a recorded `command`; the runner
    still receives it.
21. **Probe table.** Each row of the contract's requirement-probe table holds.
22. **Layouts.** POSIX and Windows layouts produce the documented argv and paths,
    with single-quote doubling on Windows.

---

## Module Layout

```
source/packages/ccai/sysman/common/
├── commandredaction.py                    ← + redact_url_userinfo
├── pythonenvironmentlayout.py             ← PythonEnvironmentLayout, Posix…, Windows…
└── pythonenvironmentmanagementbase.py     ← PythonEnvironmentManagementBase + models

source/testroots/testbase/ccai/tests/sysman/common/
├── test_commandredaction.py               ← + URL userinfo tests
└── test_pythonenvironmentmanagementbase.py

source/tests/ccai_tests/sysman/common/
├── test_commandredaction.py               ← + URL userinfo tests
└── test_pythonenvironmentmanagementbase.py   ← unittest mirror of the testbase module
```

---

## Usage Example (from a per-OS package)

```python
from ccai.sysman.linux.ubuntu.runners import UbuntuLocalCommandRunner, UbuntuLocalRunnerConfig
from ccai.sysman.linux.ubuntu.pythonenvironmentmanagement import (
    UbuntuPythonEnvironmentManager, UbuntuPythonEnvManagerConfig, UbuntuPythonEnvSpec,
)

runner = UbuntuLocalCommandRunner(UbuntuLocalRunnerConfig())
config = UbuntuPythonEnvManagerConfig(
    elevated=True,
    index_url="https://svc:token@pypi.internal/simple",
    trusted_hosts=["pypi.internal"],
)
manager = UbuntuPythonEnvironmentManager(runner=runner, config=config)

manager.ensure_prerequisites()                       # apt: python3, python3-venv, python3-pip
result = manager.deploy(spec=UbuntuPythonEnvSpec(
    path="/opt/venvs/agent",
    requirements_files=["/opt/agent/requirements.txt"],
    packages=["codecraftai-agent-kit==1.0.0"],
))
for step in result.steps:
    print(step.status.value, " ".join(step.command or []))   # token already redacted
```

---

## Testing Strategy

1. A `_MockCommandRunner` keyed by argv tuple seeds `test -d`, `<py> -c …`,
   `pip list --format json`, and each write separately; helper functions seed a
   "valid", "missing", and "broken" environment in one call.
2. A `_PosixPythonEnvManager` test subclass supplies the POSIX layout; layout
   classes are unit-tested directly, including the Windows quoting.
3. One command-construction test per write verb; one idempotency test per guarded
   verb; one dry-run test per write verb; argument-validation tests.
4. The requirement probe is tested row-by-row against the contract table through a
   thin `_satisfied(spec, installed)` helper.
5. `deploy` is tested for ordering, short-circuit, aggregate status, per-spec
   overrides, and dry-run.
6. A `RunResult` subclass with `elevation_blocked=True` proves the token pass-through
   without importing the Windows package.
7. The legacy `unittest` mirror binds every testbase function onto a `TestCase` so
   both suites run identical assertions.
