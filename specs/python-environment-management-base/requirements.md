# Requirements

## Introduction

The `python-environment-management-base` feature provides `codecraftai-sysman-common`
with the OS-neutral, *concrete* feature manager that per-OS subclasses extend to
implement the
[python-environment-management contract](../contracts/python-environment-management/contract.md).

It exposes `PythonEnvironmentManagementBase`, a subclass of `BaseFeatureManager` that:

- Implements every contract verb — `create_environment`, `remove_environment`,
  `install_packages`, `install_requirements`, `uninstall_packages`, `upgrade_pip`,
  `deploy`, and the read surface — once, because CPython's `venv` module and `pip`
  behave identically on every OS.
- Defines the shared `PythonEnvManagerConfig`, `PythonEnvActionResult`,
  `PythonEnvSpec`, `PythonEnvDeployResult`, `PythonEnvInfo`, `PythonPackageInfo`
  dataclasses and the `PythonEnvQueryError` exception.
- Delegates the only OS-varying concerns — interpreter path inside the environment,
  default base-interpreter launcher, directory probe, recursive removal, path joining
  — to a `PythonEnvironmentLayout` strategy supplied by the subclass through the single
  abstract hook `_build_layout()`.

The companion module `pythonenvironmentlayout` ships `PosixPythonEnvironmentLayout`
(Ubuntu, RHEL, macOS) and `WindowsPythonEnvironmentLayout` (Windows).

All commands — including probes — route through the injected `ICommandRunner`; the
base never touches `subprocess` or the filesystem.

---

## Requirements

### Requirement 1: Provide Shared Dataclasses and Exception

**User Story:** As a per-OS implementer, I want one canonical definition of the
config, result, spec, info, and error types, so that OS-prefixed names are plain
aliases and the contract is enforced by import.

#### Acceptance Criteria

1. THE SYSTEM SHALL expose `PythonEnvActionStatus` (alias of `ActionStatus`),
   `PythonEnvManagerConfig`, `PythonEnvActionResult`, `PythonEnvSpec`,
   `PythonEnvDeployResult`, `PythonEnvInfo`, `PythonPackageInfo`, and
   `PythonEnvQueryError` from `ccai.sysman.common.pythonenvironmentmanagementbase`.
2. THE SYSTEM SHALL match the field names, types, and defaults declared in the
   contract exactly.
3. `PythonEnvSpec` list fields SHALL default per-instance (no shared mutable default).
4. `PythonEnvQueryError` SHALL store a redacted copy of the failing argv plus
   `exit_code` and `stderr`, and SHALL render them in its message.

---

### Requirement 2: Provide the Layout Strategy Seam

**User Story:** As a per-OS implementer, I want to contribute only the OS-specific
paths and probe commands, so that no venv / pip logic is duplicated.

#### Acceptance Criteria

1. THE SYSTEM SHALL declare `_build_layout() -> PythonEnvironmentLayout` as the only
   abstract method on `PythonEnvironmentManagementBase`.
2. WHEN a subclass omits `_build_layout` THE SYSTEM SHALL prevent instantiation via
   `abc`.
3. `PythonEnvironmentLayout` SHALL declare `default_interpreter_argv`, `join_path`,
   `venv_python_path`, `build_directory_exists_argv`, and `build_remove_tree_argv`.
4. `PosixPythonEnvironmentLayout` SHALL return `["python3"]`, `<path>/bin/python`,
   `["test", "-d", <path>]`, and `["rm", "-rf", <path>]`.
5. `WindowsPythonEnvironmentLayout` SHALL return `["py", "-3"]`,
   `<path>\Scripts\python.exe`, and PowerShell `-NoProfile -NonInteractive -Command`
   scriptblocks for `Test-Path -LiteralPath … -PathType Container` (exit 0 / 1) and
   `Remove-Item -LiteralPath … -Recurse -Force`, doubling single quotes in the path
   and honouring a configurable `powershell_executable`.

---

### Requirement 3: Create an Environment

**User Story:** As a maintenance coordinator, I want to create a virtual environment
from a chosen interpreter, idempotently and with dry-run support.

#### Acceptance Criteria

1. WHEN the coordinator calls `create_environment(path)` THE SYSTEM SHALL dispatch
   `<interpreter> -m venv [--system-site-packages] <path>` where `<interpreter>` is
   the per-call `interpreter` argument, else `config.base_interpreter`, else the
   layout default.
2. WHEN `is_valid_environment(path)` is already true THE SYSTEM SHALL return
   `SKIPPED` with `message="environment already exists"` and dispatch nothing.
3. WHEN the directory exists but its interpreter does not run THE SYSTEM SHALL treat
   the environment as absent and dispatch the create command.
4. WHEN creation succeeds AND the effective `upgrade_pip` is True THE SYSTEM SHALL
   then dispatch `pip install --upgrade [index options] pip`; a failed upgrade SHALL
   yield `FAILED` with `message="environment created but the pip upgrade failed"`.
5. WHEN creation fails THE SYSTEM SHALL return `FAILED` and SHALL NOT attempt the
   pip upgrade.
6. WHEN dry-run is active THE SYSTEM SHALL return `DRY_RUN` with `command` populated
   and SHALL NOT invoke the runner, not even for the probe.

---

### Requirement 4: Remove an Environment

#### Acceptance Criteria

1. WHEN the coordinator calls `remove_environment(path)` THE SYSTEM SHALL dispatch
   the layout's remove-tree argv with `elevated=config.elevated`.
2. WHEN no directory exists at `path` THE SYSTEM SHALL return `SKIPPED` with
   `message="environment does not exist"`.
3. WHEN dry-run is active THE SYSTEM SHALL return `DRY_RUN` without invoking the
   runner.

---

### Requirement 5: Install Packages

#### Acceptance Criteria

1. WHEN the coordinator calls `install_packages(path, packages)` THE SYSTEM SHALL
   dispatch `<venv python> -m pip --disable-pip-version-check --no-input install
   [--upgrade] [--index-url U] [--extra-index-url E]… [--trusted-host H]…
   [pip_options…] <packages…>`.
2. WHEN `upgrade=False` AND every specifier is satisfied per the contract's
   requirement-probe table THE SYSTEM SHALL return `SKIPPED` with
   `message="every requested package is already installed"`.
3. WHEN `upgrade=True` THE SYSTEM SHALL bypass the probe and pass `--upgrade`.
4. WHEN `packages` is empty THE SYSTEM SHALL raise `ValueError` before any runner
   call.
5. THE SYSTEM SHALL echo `packages` onto the result and SHALL redact URL userinfo in
   the recorded `command` while passing the unredacted argv to the runner.
6. WHEN dry-run is active THE SYSTEM SHALL return `DRY_RUN` without invoking the
   runner.

---

### Requirement 6: Install Requirements Files

#### Acceptance Criteria

1. WHEN the coordinator calls `install_requirements(path, files, constraints_files)`
   THE SYSTEM SHALL dispatch the pip install argv with `-r <file>` per requirements
   file followed by `-c <file>` per constraints file.
2. THE SYSTEM SHALL NOT consult `pip list` and SHALL NOT return `SKIPPED`.
3. WHEN `requirements_files` is empty THE SYSTEM SHALL raise `ValueError`.
4. WHEN dry-run is active THE SYSTEM SHALL return `DRY_RUN` without invoking the
   runner.

---

### Requirement 7: Uninstall Packages

#### Acceptance Criteria

1. WHEN the coordinator calls `uninstall_packages(path, names)` THE SYSTEM SHALL
   dispatch `… pip … uninstall -y <names…>`.
2. WHEN none of the (PEP 503-normalised) names are installed THE SYSTEM SHALL return
   `SKIPPED` with `message="none of the requested packages are installed"`.
3. WHEN `names` is empty THE SYSTEM SHALL raise `ValueError`.

---

### Requirement 8: Upgrade pip

#### Acceptance Criteria

1. WHEN the coordinator calls `upgrade_pip(path)` THE SYSTEM SHALL dispatch
   `… pip … install --upgrade [index options] pip` and SHALL NOT skip.

---

### Requirement 9: Deploy From a Spec

#### Acceptance Criteria

1. WHEN the coordinator calls `deploy(spec)` THE SYSTEM SHALL run, in order:
   `remove_environment` (only when `spec.recreate`), `create_environment` with
   `upgrade_pip=False`, `upgrade_pip` (when the effective flag is True),
   `install_requirements` (when files are listed), `install_packages` (when packages
   are listed).
2. THE SYSTEM SHALL stop at the first `FAILED` step and SHALL populate `message`
   with a one-line description of that step.
3. THE SYSTEM SHALL aggregate `status` as `FAILED` > `DRY_RUN` > `SUCCESS` >
   `SKIPPED`.
4. Per-spec `interpreter`, `system_site_packages`, `upgrade_pip`, and
   `upgrade_packages` SHALL override the config.

---

### Requirement 10: Read Surface

#### Acceptance Criteria

1. `environment_exists` SHALL return True iff the layout's directory probe exits 0.
2. `is_valid_environment` SHALL return True iff the directory exists AND
   `get_python_version` is not `None`.
3. `get_python_version` SHALL run `<venv python> -c "import platform;
   print(platform.python_version())"` and return the stripped stdout, or `None` on
   non-zero exit or empty output.
4. `list_installed` SHALL parse `pip list --format json` into `PythonPackageInfo`
   rows, return `[]` for empty output, and raise `PythonEnvQueryError` on non-zero
   exit or unparsable JSON.
5. `get_package_info` / `is_package_installed` SHALL compare names PEP 503-normalised.
6. `freeze` SHALL return non-blank `pip freeze` lines and raise on non-zero exit.
7. `get_environment_info` SHALL return `None` when the directory is absent, else a
   populated `PythonEnvInfo`.
8. No read or probe SHALL pass `elevated=True`.

---

### Requirement 11: Elevation and Elevation-Blocked Pass-Through

#### Acceptance Criteria

1. Writes SHALL pass `elevated=config.elevated`; reads and probes SHALL pass
   `elevated=False`.
2. WHEN a runner's `RunResult` carries a truthy `elevation_blocked` attribute THE
   SYSTEM SHALL set `detail="elevation_blocked"` on the `FAILED` result.

---

### Requirement 12: Credential Redaction

#### Acceptance Criteria

1. `redact_command` SHALL replace the userinfo of any `scheme://user:pass@host` token
   (bare or `--flag=` form) with `***`.
2. Every recorded `command` on results and on `PythonEnvQueryError` SHALL pass
   through `redact_command`.
