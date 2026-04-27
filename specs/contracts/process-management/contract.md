# Process-Management Contract

This is the cross-OS abstract contract for the
**process-management** feature. Every `automojo-sysman-*` package
that ships a process manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-process-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-process-management/).
It uses `ps`, `kill`, `pkill`, `nice`, `renice`, and `/proc/<pid>/`
through an `ICommandRunner` and an `IFileOperator`. This contract
generalises the verb set for macOS (BSD `ps`, `kill`, `launchctl
kickstart`) and Windows (`Get-Process`, `Stop-Process`,
`Start-Process`, `Wait-Process`, PowerShell priority control,
`taskkill`/`tasklist`).

---

## Scope

The process-management feature provides idempotent, auditable
control over arbitrary running processes. It covers:

- Enumerating processes by filter.
- Inspecting a single process by PID.
- Terminating a process (with a specified signal or the OS
  equivalent) and optionally its entire process tree.
- Starting a new process.
- Adjusting a process's priority.
- Waiting for a process to exit, with timeout.
- Finding processes by name or pattern.
- Dry-run-aware writes.
- Elevation for cross-user writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and, on OSes that expose a `/proc` filesystem, an `IFileOperator`.

This feature does NOT manage system services; service lifecycle
lives in `service-management`.

---

## Verbs

Every OS implementation MUST expose a `ProcessManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_processes` | `(filter: ProcessFilter \| None) → list[ProcessInfo]` | Read |
| `get_process` | `(pid: int) → ProcessInfo \| None` | Read |
| `kill_process` | `(pid: int, signal: ProcessSignal) → ProcessActionResult` | Write |
| `kill_process_tree` | `(pid: int, signal: ProcessSignal) → ProcessActionResult` | Write |
| `start_process` | `(spec: ProcessStartSpec) → ProcessStartResult` | Write |
| `set_process_priority` | `(pid: int, priority: int) → ProcessActionResult` | Write |
| `wait_for_process` | `(pid: int, timeout_seconds: float \| None) → ProcessWaitResult` | Read |
| `find_processes_by_name` | `(name: str) → list[ProcessInfo]` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `kill_process` / `kill_process_tree`
   against a PID that does not exist MUST return `SKIPPED` with a
   detail indicating the process was already gone.
   `set_process_priority` MUST query the current priority and
   return `SKIPPED` when the requested value matches.
   `start_process` is inherently non-idempotent and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Signal mapping.** `ProcessSignal` values MUST be translated
   to the OS's native signal or terminate mechanism. Signals that
   have no mapping (e.g., `SIGHUP` on Windows) MUST return `FAILED`
   with a descriptive `detail`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner. OS implementations MAY elevate on reads only when the
   target process is owned by another user AND the OS spec
   explicitly documents the policy.
2. **Typed errors.** `list_processes` MUST raise
   `ProcessQueryError` for unexpected failures. `get_process` MUST
   return `None` for an unknown PID and raise only on unexpected
   failures.
3. **`wait_for_process` timeout.** When `timeout_seconds` is
   exceeded, `wait_for_process` MUST return a
   `ProcessWaitResult(timed_out=True, ...)` rather than raise.
4. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `ProcessActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or the signal is not mappable on the OS. |
| `SKIPPED` | The idempotency guard determined no action was needed (e.g., PID already absent). |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ProcessSignal` (enum)

| Value | Meaning |
|-------|---------|
| `TERM` | Graceful terminate (`SIGTERM` on Unix; `Stop-Process` on Windows). |
| `KILL` | Force terminate (`SIGKILL` on Unix; `Stop-Process -Force` on Windows). |
| `HUP` | Hang-up / reload (`SIGHUP` on Unix; `FAILED` on Windows). |
| `INT` | Interrupt (`SIGINT` on Unix; Ctrl-C emulation on Windows). |
| `QUIT` | Quit + core (`SIGQUIT` on Unix; `FAILED` on Windows). |
| `USR1` | User-defined 1 (`SIGUSR1` on Unix; `FAILED` on Windows). |
| `USR2` | User-defined 2 (`SIGUSR2` on Unix; `FAILED` on Windows). |

### `ProcessFilter` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `owner` | `str \| None` | Restrict to processes owned by this user. |
| `name_pattern` | `str \| None` | Regex applied to process name. |
| `min_cpu_percent` | `float \| None` | Floor on CPU usage. |
| `min_memory_bytes` | `int \| None` | Floor on resident memory. |

### `ProcessInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `pid` | `int` | Process ID. |
| `ppid` | `int \| None` | Parent PID. |
| `name` | `str` | Executable name. |
| `command_line` | `str` | Full command line. |
| `owner` | `str \| None` | Username. |
| `cpu_percent` | `float \| None` | Sampled CPU usage. |
| `memory_bytes` | `int \| None` | Resident memory. |
| `start_time` | `datetime \| None` | Process start time, UTC. |
| `state` | `str \| None` | Native state token (`"R"`, `"S"`, `"Z"`, `"Running"`, `"Suspended"`). |

### `ProcessStartSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `command` | `list[str]` | The argv to launch. |
| `cwd` | `str \| None` | Working directory. |
| `env` | `dict[str, str] \| None` | Environment overrides. |
| `detach` | `bool` | When `True`, fully detach from the runner (no captured output). |

### `ProcessStartResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ProcessActionStatus` | Outcome category. |
| `pid` | `int \| None` | PID of the launched process on `SUCCESS`. |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout (empty if `detach=True`). |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `ProcessActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ProcessActionStatus` | Outcome category. |
| `pid` | `int` | Target PID. |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `ProcessWaitResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `pid` | `int` | Target PID. |
| `timed_out` | `bool` | Whether the wait exceeded the timeout. |
| `exit_code` | `int \| None` | Exit code of the process when known. |
| `elapsed_seconds` | `float` | Elapsed wall-clock time. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ProcessQueryError` | A read fails for a reason other than "PID unknown". |

### `ProcessManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

---

## Process-Identity Mapping

The abstract `pid` parameter is the OS-native numeric process
identifier. The abstract name filter maps to the OS's native
matching command.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | POSIX PID; `ps`, `kill`, `pkill`, `/proc/<pid>/` | Canonical. |
| Ubuntu | Same as RHEL | — |
| macOS | BSD PID; `ps`, `kill`, `pkill`; no `/proc` (uses `sysctl kern.proc`) | The macOS spec MUST document its `/proc` substitute. |
| Windows | Windows PID; `Get-Process`, `Stop-Process`, `Start-Process`, `Wait-Process` | Signal concepts do not map cleanly; the Windows spec MUST enumerate the `ProcessSignal` → native action table. |
| UEFI | N/A | UEFI has no multi-process kernel. The process-management contract does not apply. |

Each OS spec MUST include a Process-Identity-Mapping section
stating its command surface and signal translation.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method targeting a foreign-owner PID | Pass `elevated=True` to the runner. |
| Config `elevated=True`, write method targeting the caller's own PID | Implementation-defined — the OS spec MUST state the policy. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True` by default. OS-specific exceptions (e.g., inspecting another user's process listing) MUST be documented. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>ProcessManager
                │
                │  .run(argv, elevated=…, capture_output=True)
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

1. Accept an `ICommandRunner` and a `ProcessManagerConfig` in
   their constructor. Linux-family implementations MAY also accept
   an `IFileOperator` for `/proc` reads.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the injected collaborators
   and the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `ProcessManager` | `UbuntuProcessManager` | `MacosProcessManager` | `WindowsProcessManager` | `ProcessManager` |
| `ProcessManagerConfig` | `UbuntuProcessManagerConfig` | `MacosProcessManagerConfig` | `WindowsProcessManagerConfig` | `ProcessManagerConfig` |
| `ProcessActionStatus` | `UbuntuProcessActionStatus` | `MacosProcessActionStatus` | `WindowsProcessActionStatus` | `ProcessActionStatus` |
| `ProcessSignal` | `UbuntuProcessSignal` | `MacosProcessSignal` | `WindowsProcessSignal` | `ProcessSignal` |
| `ProcessFilter` | `UbuntuProcessFilter` | `MacosProcessFilter` | `WindowsProcessFilter` | `ProcessFilter` |
| `ProcessInfo` | `UbuntuProcessInfo` | `MacosProcessInfo` | `WindowsProcessInfo` | `ProcessInfo` |
| `ProcessStartSpec` | `UbuntuProcessStartSpec` | `MacosProcessStartSpec` | `WindowsProcessStartSpec` | `ProcessStartSpec` |
| `ProcessStartResult` | `UbuntuProcessStartResult` | `MacosProcessStartResult` | `WindowsProcessStartResult` | `ProcessStartResult` |
| `ProcessActionResult` | `UbuntuProcessActionResult` | `MacosProcessActionResult` | `WindowsProcessActionResult` | `ProcessActionResult` |
| `ProcessWaitResult` | `UbuntuProcessWaitResult` | `MacosProcessWaitResult` | `WindowsProcessWaitResult` | `ProcessWaitResult` |
| `ProcessQueryError` | `UbuntuProcessQueryError` | `MacosProcessQueryError` | `WindowsProcessQueryError` | `ProcessQueryError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ProcessActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One `list_processes` parser test covering multiple processes
   and all filter parameters.
2. One `get_process` test for a known and an unknown PID.
3. One command-construction test per write verb.
4. One idempotency test for `kill_process` against a missing PID
   proving `SKIPPED`.
5. One signal-mapping test per `ProcessSignal` value, including
   the `FAILED` cases on Windows.
6. One `start_process` test proving `pid` is populated on
   `SUCCESS`.
7. One `wait_for_process` test proving `timed_out=True` on timeout.
8. One dry-run test per write verb proving the runner is not
   invoked.
9. One elevation test proving cross-user writes pass
   `elevated=True` and reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- `ionice` / IO-priority adjustment — RHEL extension.
- CPU-affinity pinning (`taskset`, `Set-ProcessAffinity`) — RHEL
  extension.
- Process-level capability / seccomp / AppArmor profile
  manipulation.
- Per-process open-file introspection (`lsof`) — RHEL extension.
- Ptrace / debugger attachment.
- Job-object binding on Windows (lives in
  `resource-control-management`).
- launchd / SCM service lifecycle — lives in `service-management`.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu wraps GNU `ps` /
  `kill` / `pkill` / `pgrep`; macOS wraps BSD variants of the
  same tools (different flag spellings, no `/proc` substitute);
  Windows wraps `Get-Process` / `Stop-Process` / `Wait-Process` /
  `taskkill`. The verb surface is identical; argv shapes are
  not.
- **Signal model is POSIX-only.** Windows has no POSIX signal
  facility. `kill_process(pid, signal="TERM" | "KILL")` maps to
  `Stop-Process -Id <pid> -Force`; every other contract signal
  (`HUP` / `INT` / `QUIT` / `USR1` / `USR2`) returns `FAILED`
  with a stable `detail` token of the form
  `signal <NAME> has no Windows mapping`. See the README "FAILED
  with a stable detail token" convention.
- **Process-tree depth differs.** Ubuntu and macOS use
  `pkill -P <pid>` which reaches direct children only — deeper
  descendants are out of scope for the verb. Windows
  `taskkill /F /T /PID <pid>` recurses the full tree natively;
  the asymmetry is intentional and documented in each per-OS
  spec.
- **Windows `elevation_blocked: bool`.** `Stop-Process` /
  `taskkill` against processes owned by other principals require
  elevation; the manager surfaces the structured Windows
  elevation extension. See the README "Implementation
  Conventions" elevation-blocked entry.
- **Reads degrade gracefully.** `get_process(pid)` returns
  `None` rather than raising when the PID is gone; the
  `wait_for_process` poll loop returns a `*ProcessWaitResult`
  with a synthetic outcome rather than raising on timeout. Per
  the README "Reads degrade gracefully" convention.
