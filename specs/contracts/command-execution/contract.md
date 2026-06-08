# Command-Execution Contract

This is the cross-OS abstract contract for the **command-execution**
feature. Every `codecraftai-sysman-*` package that ships a command
executor MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/1-command-execution/`](../../../../../codecraftai-sysman-linux-redhat/specs/1-command-execution/).
It is the foundational Layer-1 feature that every Layer-3 manager
depends on through the `ICommandRunner` interface, and this abstract
contract defines the shape every OS must honor for local and remote
process execution.

---

## Scope

The command-execution feature provides auditable, dry-run-aware
dispatch of OS-level commands through an `ICommandRunner`. It covers:

- Running a single command with argv, working directory, environment
  overrides, elevation, and an optional timeout.
- Running an ordered sequence of commands with an optional
  stop-on-failure policy.
- Running a short inline script fragment via the OS's default
  shell or scripting host.
- Mapping exit codes to a uniform success/fail result shape.
- Merging caller-supplied environment with the process environment.
- Surfacing timeouts as a typed result field rather than an exception.
- Applying elevation uniformly for writes; reads never elevate (the
  executor does not distinguish reads from writes — the caller does).

The feature is executed exclusively through an `ICommandRunner` from
`codecraftai-interfaces`. No direct `subprocess`, no direct daemon-socket
calls, and no direct filesystem writes except for the one short-lived
temp-file used by `run_script`.

---

## Verbs

Every OS implementation MUST expose a `CommandExecutor` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `run` | `(args: list[str], *, elevated: bool, working_dir: str \| None, env: dict \| None, timeout_seconds: float \| None) → CommandResult` | Write |
| `run_sequence` | `(commands: list[CommandSpec], *, stop_on_failure: bool) → SequenceResult` | Write |
| `run_script` | `(script: str, *, elevated: bool, working_dir: str \| None, env: dict \| None, timeout_seconds: float \| None) → CommandResult` | Write |

The executor treats every invocation as a potential write: elevation
is dispatched to the runner as requested. The contract does not
itself define read vs write verbs — that is a caller concern.

### Method-level invariants (all verbs)

1. **Dry-run short-circuit.** When `dry_run=True` on the config, no
   `ICommandRunner.run` call MUST occur. A synthetic `CommandResult`
   with `success=True`, `dry_run=True`, and `exit_code=0` MUST be
   returned. For `run_sequence`, one synthetic result per spec MUST
   be returned. For `run_script`, no temp file MUST be created.
2. **Working-dir precondition.** When `working_dir` is supplied and
   the directory does not exist, the executor MUST return a
   `CommandResult` with `success=False` and a descriptive `stderr`
   without invoking the runner.
3. **Environment merging.** When `env` is supplied, the runner MUST
   be invoked with a merged env equal to the process environment
   overlaid with `env` (caller wins on conflicts). When `env` is
   `None`, the runner MUST receive `env=None` and use its own
   default.
4. **Timeout propagation.** `timeout_seconds` MUST be forwarded to
   the runner. When the runner returns `timed_out=True`, the
   resulting `CommandResult.timed_out` MUST be `True` and
   `success=False`. If the runner populates no `stderr` for the
   timeout, the executor MUST inject a standardised timeout message.
5. **Exit-code → success.** `success = (exit_code == 0)` for all
   non-dry-run results.
6. **Elevation propagation.** The runner MUST be invoked with the
   `elevated` value supplied by the caller. The executor does not
   consult the config for elevation — it forwards what the caller
   said.
7. **Stop-on-failure.** In `run_sequence`, when `stop_on_failure=True`
   and a command returns `success=False`, no subsequent commands MUST
   be run, and `failed_at` MUST equal the index of the first failed
   command. When `stop_on_failure=False`, all commands MUST be run
   and `failed_at` MUST equal the index of the first failed command
   or `None` when all succeeded.
8. **Script temp-file cleanup.** In `run_script`, the temp file MUST
   be deleted regardless of the outcome of the underlying `run`
   call, via a `finally` block equivalent.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum, each
prefixed with the OS name (see §Naming).

### `CommandExecutionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded (`exit_code == 0`). |
| `FAILED` | The command ran and returned non-zero, or timed out. |
| `SKIPPED` | Reserved for coordinator-level skip decisions; the executor itself never returns this. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

The executor primarily populates `success` / `exit_code` /
`dry_run` / `timed_out` directly, and implementations MAY omit this
enum in favor of the boolean fields described below, but MUST accept
and document the canonical status vocabulary that the reporter
consumes.

### `CommandSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `args` | `list[str]` | The argv list to execute. |
| `elevated` | `bool` | Whether to request elevation. Default `False`. |
| `working_dir` | `str \| None` | Directory to execute in. |
| `env` | `dict[str, str] \| None` | Environment overrides. |
| `timeout_seconds` | `float \| None` | Per-command timeout. |
| `label` | `str \| None` | Human-readable identifier for reporting. |

### `CommandResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | `True` when `exit_code == 0` and `timed_out=False`. |
| `exit_code` | `int \| None` | The runner exit code; `0` in `DRY_RUN`. |
| `stdout` | `str` | Captured stdout. |
| `stderr` | `str` | Captured stderr. |
| `args` | `list[str]` | The argv that was (or would have been) executed. |
| `timed_out` | `bool` | `True` when the runner surfaced a timeout. |
| `dry_run` | `bool` | `True` when the result was dry-run-synthetic. |
| `started_at` | `datetime \| None` | UTC start time, or `None` in dry-run. |
| `finished_at` | `datetime \| None` | UTC finish time, or `None` in dry-run. |
| `duration_ms` | `float \| None` | Elapsed milliseconds, or `None` in dry-run. |
| `elevated` | `bool` | The `elevated` value that was forwarded. |

### `SequenceResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `all_succeeded` | `bool` | `True` when every `CommandResult.success` is `True`. |
| `results` | `list[CommandResult]` | One per executed or dry-run spec. |
| `failed_at` | `int \| None` | Index of the first failing spec, or `None`. |
| `dry_run` | `bool` | `True` when the whole sequence was dry-run-synthetic. |

### `CommandExecutorConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no commands are executed. |
| `default_timeout_seconds` | `float \| None` | `None` | Fallback timeout when none is supplied per-call. |

Implementations MAY extend with OS-specific fields (e.g., shell path
on Unix-likes, PowerShell invocation policy on Windows) but MUST
preserve these two fields with these names and defaults.

### Exceptions

Command-execution does not define typed query exceptions — all
failures are surfaced on `CommandResult`. Callers wanting typed
failures re-raise from the result.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Caller passes `elevated=True` | The executor MUST call the runner with `elevated=True`. |
| Caller passes `elevated=False` | The executor MUST call the runner with `elevated=False`. |
| `dry_run=True` | No runner call occurs; the returned `CommandResult.elevated` MUST reflect the requested value. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows; N/A under UEFI shell. The runner owns the mechanism. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>CommandExecutor
                │
                │  .run(argv, elevated=…, cwd=…, env=…, timeout=…)
                ▼
          ICommandRunner
                │
        ┌───────┴────────┐
        ▼                ▼
  LocalCommandRunner   SSHCommandRunner
        │                │
        └────────┬───────┘
                 │  aspects compose here
                 ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner` and a `CommandExecutorConfig` in their
   constructor.
2. Never construct their own runner or subprocess.
3. Not hold process state across calls (temp files created by
   `run_script` are deleted before return).
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `CommandExecutor` | `UbuntuCommandExecutor` | `MacosCommandExecutor` | `WindowsCommandExecutor` | `CommandExecutor` |
| `CommandExecutorConfig` | `UbuntuCommandExecutorConfig` | `MacosCommandExecutorConfig` | `WindowsCommandExecutorConfig` | `CommandExecutorConfig` |
| `CommandSpec` | `UbuntuCommandSpec` | `MacosCommandSpec` | `WindowsCommandSpec` | `CommandSpec` |
| `CommandResult` | `UbuntuCommandResult` | `MacosCommandResult` | `WindowsCommandResult` | `CommandResult` |
| `SequenceResult` | `UbuntuSequenceResult` | `MacosSequenceResult` | `WindowsSequenceResult` | `SequenceResult` |
| `CommandExecutionStatus` | `UbuntuCommandExecutionStatus` | `MacosCommandExecutionStatus` | `WindowsCommandExecutionStatus` | `CommandExecutionStatus` |

Local-runner types also follow this rule:
`UbuntuLocalCommandRunner`, `MacosLocalCommandRunner`,
`WindowsLocalCommandRunner`. Under UEFI the canonical implementation
is `UefiCommandExecutor` wrapping a `UefiShellCommandRunner`.

---

## Aspect Composition

Aspect behavior MUST be transparent to the executor:

- An executor tested with a `MockCommandRunner` and no aspects MUST
  produce the same `CommandResult` sequence when driven by a real
  runner with `PersistenceAspect`, `RetryAspect`, and `TimeoutAspect`
  attached, modulo timing fields and retries.
- Retry aspects that translate transient non-zero exits into
  zero-exit results are permitted to flip `success` from `False` to
  `True`; `args`, `elevated`, and `dry_run` MUST remain unchanged.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. A success-path test for `run` verifying `args`, `elevated`, `cwd`,
   and `env` propagation to the runner.
2. A non-existent-`working_dir` test proving the runner is not
   invoked.
3. A timeout-propagation test proving `timed_out=True` and
   `success=False` when the runner reports a timeout.
4. Environment-merge tests proving `{**os.environ, **caller_env}`
   semantics.
5. `run_sequence` tests covering empty input, all-success,
   stop-on-failure, and continue-on-failure.
6. `run_script` tests proving the temp file is created, executed,
   and deleted.
7. A dry-run test per verb proving the runner is never invoked.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Streaming stdout/stderr to callbacks with back-pressure.
- PTY allocation / interactive prompt handling.
- Signal injection beyond timeout-triggered termination.
- Background / detached process spawning beyond the temp-file-backed
  `run_script` pattern.
- Per-command resource limits (nice, ionice, ulimit).
- Shell-string parsing: all inputs are argv lists; shell semantics
  require `run_script`.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Windows-specific `elevation_blocked: bool` on `RunResult`.**
  The Windows `LocalCommandRunner` pre-detects elevation status
  via `IsUserAnAdmin()`. When `elevated=True` is requested but
  the process is not elevated, the runner returns `FAILED` with
  `elevation_blocked=True` rather than spawning the underlying
  command. POSIX runners do not carry this field. See the README
  "Implementation Conventions" elevation-blocked extension.
- **`command: list[str] | None` field on dispatched results.**
  The `featurebase._dispatch` helper that downstream feature
  managers use records the argv on every action-result type;
  this is a manager-level field, not a `RunResult` field. See
  the README "Implementation Conventions" `command` field
  convention.
- Output redirection to files on the target host.
