# Log-Management Contract

This is the cross-OS abstract contract for the **log-management**
feature. Every `automojo-sysman-*` package that ships a log manager
MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-log-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-log-management/).
It uses `journalctl` for the systemd journal, `tail`/`grep` for
plain log files, and `logrotate` with drop-ins under
`/etc/logrotate.d/`. This contract generalises the verb set for
OSes whose log surface includes macOS's unified log, BSD syslog,
and the Windows Event Log / `Get-WinEvent`.

---

## Scope

The log-management feature provides idempotent, auditable
inspection and lifecycle control of system logs. It covers:

- Retrieving recent entries from a named log source with optional
  filters (unit/subsystem, time window, severity, pattern, line
  count).
- Tailing a log source as a stream of entries.
- Listing available log sources.
- Rotating a log source on demand.
- Truncating a log source.
- Configuring rotation policy for a log source.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` for rotation drop-in
files; the established cross-OS pattern is to route file I/O
through `ICommandRunner` using OS-native file utilities. See the
README "Implementation Conventions".

---

## Verbs

Every OS implementation MUST expose a `LogManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_log` | `(source: str, lines: int \| None, since: str \| None, until: str \| None, severity: str \| None, pattern: str \| None) → LogEntries` | Read |
| `tail_log` | `(source: str, follow: bool) → Iterator[LogEntry]` | Read |
| `list_logs` | `() → list[LogInfo]` | Read |
| `rotate_log` | `(source: str) → LogActionResult` | Write |
| `truncate_log` | `(source: str) → LogActionResult` | Write |
| `configure_rotation` | `(source: str, policy: RotationPolicy) → LogActionResult` | Write |
| `remove_rotation_config` | `(source: str) → LogActionResult` | Write |
| `get_rotation_config` | `(source: str) → RotationPolicy \| None` | Read |
| `query_disk_usage` | `(source: str) → LogDiskUsage` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `configure_rotation` MUST read the current
   policy (from the rotation drop-in file or OS-native policy store)
   and compare; matching policy MUST return `SKIPPED`.
   `remove_rotation_config` MUST return `SKIPPED` when no policy is
   configured. `rotate_log` and `truncate_log` are operational
   actions and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner — with one exception: `rotate_log`
   MAY execute a native dry-run (e.g., `logrotate --debug`) in
   dry-run mode to surface useful simulation output. That behavior
   MUST be documented in the OS spec.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Policy-file idempotency.** `configure_rotation` MUST write
   only when rendered content differs from existing content.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner unless the OS's log source is protected (e.g., Windows
   Security event log); in that case the OS spec MUST document the
   exception.
2. **Typed errors.** `get_log`, `list_logs`, and `query_disk_usage`
   MAY raise `LogQueryError` for unexpected failures or, per the
   per-OS spec, return an empty list / synthetic record so callers
   can proceed without a try/except wrapper. An unknown
   source MUST return an empty `LogEntries` / no `LogInfo` entry
   rather than raise. See the README "Implementation Conventions"
   graceful-read pattern.
3. **Pure parsing.** All parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `LogActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard short-circuited the write. |
| `DRY_RUN` | Dry-run mode short-circuited the command (or emitted a simulation). |

### `LogInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Native source identifier (file path, unit name, subsystem, event-log name). |
| `path` | `str \| None` | Filesystem path when applicable. |
| `size_bytes` | `int \| None` | Current size when applicable. |
| `rotating` | `bool` | Whether a rotation policy is configured. |

### `LogEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | `datetime \| None` | Entry timestamp (UTC). |
| `severity` | `str \| None` | Parsed severity / priority. |
| `source` | `str \| None` | Unit, subsystem, or provider. |
| `message` | `str` | The log line text. |

### `LogEntries` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | The source queried. |
| `entries` | `list[LogEntry]` | Parsed entries in chronological order. |
| `raw` | `list[str]` | Raw lines. |
| `truncated` | `bool` | `True` when the query was truncated by a line limit. |

### `LogActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `LogActionStatus` | Outcome category. |
| `source` | `str` | The source targeted. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `RotationPolicy` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Source the policy applies to. |
| `keep_count` | `int` | Number of rotated files to retain. |
| `frequency` | `str` | Rotation cadence, e.g., `"daily"`, `"weekly"`, `"size:100M"`. |
| `compress` | `bool` | Whether rotated files are compressed. |
| `max_size_bytes` | `int \| None` | Optional size threshold. |
| `post_rotate` | `str \| None` | Optional post-rotate hook command. |

### `LogDiskUsage` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | The source queried. |
| `size_human` | `str` | Human-readable size. |
| `size_bytes` | `int` | Size in bytes. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `LogQueryError` | A read fails for a reason other than "source unknown". |

### `LogManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutating writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

---

## Log-Source Mapping

The abstract `source` parameter maps to each OS's native log-source
identifier.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | systemd unit name for journal (`nginx.service`) or file path for plain logs (`/var/log/messages`) | Canonical. |
| Ubuntu | Same as RHEL; implementations SHOULD also accept syslog facility names for rsyslog-only hosts. | — |
| macOS | Unified-log subsystem / predicate expression for `log show` (`com.apple.network`) or file path for BSD syslog (`/var/log/system.log`) | `log show --predicate 'subsystem == "..."'` is the canonical read path. |
| Windows | Event-log channel name (`System`, `Application`, `Security`) for `Get-WinEvent` or file path for text logs | `Get-WinEvent -LogName <name>` is the canonical read path. |
| UEFI | N/A | UEFI has no persistent logging beyond firmware-specific buffers that are not consumer-grade. The log-management contract does not apply. |

Each OS spec MUST include a Source-Mapping section describing its
identifier syntax.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True` — except where the OS requires it (e.g., Windows Security log). |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>LogManager
                │
                │  .run(argv, elevated=…, stdin=content, capture_output=True)
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

1. Accept an `ICommandRunner` and a `LogManagerConfig` in their
   constructor. Implementations whose rotation store is a plain
   file MAY also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `LogManager` | `UbuntuLogManager` | `MacosLogManager` | `WindowsLogManager` | `LogManager` |
| `LogManagerConfig` | `UbuntuLogManagerConfig` | `MacosLogManagerConfig` | `WindowsLogManagerConfig` | `LogManagerConfig` |
| `LogActionStatus` | `UbuntuLogActionStatus` | `MacosLogActionStatus` | `WindowsLogActionStatus` | `LogActionStatus` |
| `LogActionResult` | `UbuntuLogActionResult` | `MacosLogActionResult` | `WindowsLogActionResult` | `LogActionResult` |
| `LogInfo` | `UbuntuLogInfo` | `MacosLogInfo` | `WindowsLogInfo` | `LogInfo` |
| `LogEntry` | `UbuntuLogEntry` | `MacosLogEntry` | `WindowsLogEntry` | `LogEntry` |
| `LogEntries` | `UbuntuLogEntries` | `MacosLogEntries` | `WindowsLogEntries` | `LogEntries` |
| `RotationPolicy` | `UbuntuRotationPolicy` | `MacosRotationPolicy` | `WindowsRotationPolicy` | `LogrotateConfig` |
| `LogDiskUsage` | `UbuntuLogDiskUsage` | `MacosLogDiskUsage` | `WindowsLogDiskUsage` | `JournalDiskUsage` |
| `LogQueryError` | `UbuntuLogQueryError` | `MacosLogQueryError` | `WindowsLogQueryError` | `LogManagementError` |

The RHEL package keeps its historical names; new OS packages use
the abstract names above.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `LogActionResult` sequence when driven by a real
  runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One `get_log` test per filter parameter (lines, since, severity,
   pattern) proving correct command construction.
2. One `list_logs` parser test covering representative output.
3. One `rotate_log` test proving correct command construction, plus
   a dry-run variant proving either a no-op or a debug-mode call
   per OS-spec policy.
4. One `truncate_log` test proving correct command construction.
5. One `configure_rotation` idempotency test proving `SKIPPED` when
   the rendered policy matches the existing source.
6. One `get_rotation_config` test for a configured and an
   unconfigured source.
7. One `query_disk_usage` parser test.
8. One dry-run test per write verb proving no runner calls occur
   (except the documented `rotate_log` debug path).
9. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Centralised log shipping (rsyslog forwarding, Fluentd, Windows
  Event Forwarding) — see the `remote-log-forwarding` feature.
- Log content parsing into structured records beyond basic
  `LogEntry` fields.
- Log-based alerting.
- Audit-log-specific features (`auditd`, `auditpol`).
- Binary-format log viewers (`btmp`, `wtmp`).
- Unified-log signposts / activities (macOS).
- ETW provider registration (Windows).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence.** Ubuntu wraps `journalctl` /
  `logrotate`; macOS wraps the unified-log via `log show` /
  `log stream` / `log collect`; Windows wraps `Get-WinEvent` /
  `wevtutil`. The `LogEntry` / `LogInfo` shapes are identical;
  the realisable filters and rotation config differ.
- **File I/O via `ICommandRunner`.** `/etc/logrotate.d/*` and
  per-source rotation configs route through the runner.
- **No `IFileOperator`.** All three implementations use
  `ICommandRunner` for both command dispatch and file I/O.
