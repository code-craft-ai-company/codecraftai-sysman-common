# Resource-Control-Management Contract

This is the cross-OS abstract contract for the
**resource-control-management** feature. Every `codecraftai-sysman-*`
package that ships a resource-control manager MUST honor this
contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-resource-control-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-resource-control-management/).
It uses `systemctl set-property`, systemd drop-in files under
`/etc/systemd/system/<unit>.d/`, `systemd-run`, and the
`/sys/fs/cgroup/**` pseudo-filesystem. This contract generalises
the verb set for macOS (launchd `ResourceLimits` per-daemon +
`ulimit`) and Windows (Job Objects via PowerShell +
`Set-ProcessMitigation`; Windows System Resource Manager where
available).

---

## Scope

The resource-control-management feature provides idempotent,
auditable control over a host's process-group / slice /
job-object resource ceilings. It covers:

- Creating and deleting named resource-control groups.
- Setting per-group CPU, memory, and IO limits.
- Attaching and detaching processes to / from a group.
- Listing all groups.
- Querying a group's current usage.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and, for cgroup / registry reads, an `IFileOperator`.

---

## Verbs

Every OS implementation MUST expose a `ResourceControlManager`
class (the OS-prefixed variant — see §Naming) whose public
surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `create_group` | `(spec: ResourceGroupSpec) → ResourceActionResult` | Write |
| `delete_group` | `(name: str) → ResourceActionResult` | Write |
| `set_cpu_limit` | `(name: str, percent: float) → ResourceActionResult` | Write |
| `set_memory_limit` | `(name: str, bytes_: int) → ResourceActionResult` | Write |
| `set_io_limits` | `(name: str, spec: IoLimitSpec) → ResourceActionResult` | Write |
| `attach_process` | `(name: str, pid: int) → ResourceActionResult` | Write |
| `detach_process` | `(name: str, pid: int) → ResourceActionResult` | Write |
| `list_groups` | `() → list[ResourceGroupInfo]` | Read |
| `get_group_usage` | `(name: str) → ResourceGroupUsage` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_group` MUST return `SKIPPED`
   when a group with the same `name` already exists with matching
   ceilings. `delete_group` MUST return `SKIPPED` when no such
   group exists. `set_cpu_limit` / `set_memory_limit` /
   `set_io_limits` MUST query the current value and return
   `SKIPPED` when matching. `attach_process` MUST return
   `SKIPPED` when the PID is already in the group; `detach_process`
   MUST return `SKIPPED` when the PID is not in the group.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Persistent reload.** Where the OS writes drop-in files
   (RHEL / Ubuntu systemd), writes MUST trigger `systemctl
   daemon-reload` on `SUCCESS`. macOS / Windows implementations
   have no equivalent and MUST state that no reload is required.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_groups` and `get_group_usage` MUST
   raise `ResourceQueryError` for unexpected failures. An unknown
   group MUST cause `get_group_usage` to raise with a descriptive
   `detail`.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `ResourceActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ResourceGroupSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Group identifier (slice / job-object / launchd label). |
| `cpu_percent` | `float \| None` | Initial CPU ceiling (0-100). |
| `memory_bytes` | `int \| None` | Initial memory ceiling in bytes. |
| `io_limits` | `IoLimitSpec \| None` | Initial IO limits. |

### `IoLimitSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `read_bytes_per_second` | `int \| None` | Per-second read ceiling. |
| `write_bytes_per_second` | `int \| None` | Per-second write ceiling. |
| `read_iops` | `int \| None` | Per-second read-operation ceiling. |
| `write_iops` | `int \| None` | Per-second write-operation ceiling. |

### `ResourceGroupInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Group identifier. |
| `cpu_percent` | `float \| None` | Current CPU ceiling, or `None` if unlimited. |
| `memory_bytes` | `int \| None` | Current memory ceiling, or `None` if unlimited. |
| `io_limits` | `IoLimitSpec \| None` | Current IO limits. |
| `attached_pids` | `list[int]` | PIDs currently in the group. |

### `ResourceGroupUsage` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Group identifier. |
| `cpu_usage_percent` | `float` | Current CPU usage. |
| `memory_usage_bytes` | `int` | Current resident memory usage. |
| `io_read_bytes` | `int` | Cumulative read bytes. |
| `io_write_bytes` | `int` | Cumulative write bytes. |

### `ResourceActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ResourceActionStatus` | Outcome category. |
| `group_name` | `str` | The group targeted. |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ResourceQueryError` | A read fails for a reason other than "group unknown". |

### `ResourceControlManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |

---

## Group-Identity Mapping

The abstract `name` parameter maps to each OS's native
process-group / job-object / slice identifier.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | systemd slice (`<name>.slice`) and `/sys/fs/cgroup/<name>.slice` | Canonical. |
| Ubuntu | Same as RHEL (systemd cgroups v2) | — |
| macOS | launchd label + `ResourceLimits` in plist; `ulimit` for per-shell | macOS has no per-group cgroup equivalent. The macOS spec MUST document that groups are synthesised from launchd labels. IO limits are not supported natively and MUST return `FAILED`. |
| Windows | Job Object created via PowerShell; `Set-ProcessMitigation`; Windows System Resource Manager where available | Group identity is the Job-Object name. Not all CPU / memory / IO knobs are supported on all SKUs — the Windows spec MUST enumerate the gaps. |
| UEFI | N/A | UEFI has no process-group concept. The resource-control-management contract does not apply. |

Each OS spec MUST include a Group-Identity-Mapping section
stating its identifier conventions and the unsupported-limit
cases.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>ResourceControlManager
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

1. Accept an `ICommandRunner`, an `IFileOperator`, and a
   `ResourceControlManagerConfig` in their constructor.
2. Never construct their own subprocess or file access.
3. Not hold state across calls beyond the injected collaborators
   and the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `ResourceControlManager` | `UbuntuResourceControlManager` | `MacosResourceControlManager` | `WindowsResourceControlManager` | `ResourceControlManager` |
| `ResourceControlManagerConfig` | `UbuntuResourceControlManagerConfig` | `MacosResourceControlManagerConfig` | `WindowsResourceControlManagerConfig` | `ResourceControlManagerConfig` |
| `ResourceActionStatus` | `UbuntuResourceActionStatus` | `MacosResourceActionStatus` | `WindowsResourceActionStatus` | `ResourceActionStatus` |
| `ResourceActionResult` | `UbuntuResourceActionResult` | `MacosResourceActionResult` | `WindowsResourceActionResult` | `ResourceActionResult` |
| `ResourceGroupSpec` | `UbuntuResourceGroupSpec` | `MacosResourceGroupSpec` | `WindowsResourceGroupSpec` | `SliceSpec` |
| `ResourceGroupInfo` | `UbuntuResourceGroupInfo` | `MacosResourceGroupInfo` | `WindowsResourceGroupInfo` | `SliceInfo` |
| `ResourceGroupUsage` | `UbuntuResourceGroupUsage` | `MacosResourceGroupUsage` | `WindowsResourceGroupUsage` | `SliceUsage` |
| `IoLimitSpec` | `UbuntuIoLimitSpec` | `MacosIoLimitSpec` | `WindowsIoLimitSpec` | `IoLimitSpec` |
| `ResourceQueryError` | `UbuntuResourceQueryError` | `MacosResourceQueryError` | `WindowsResourceQueryError` | `ResourceQueryError` |

The RHEL reference uses slice-specific names; new OS packages
use the abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ResourceActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_groups` parser test covering multiple groups.
5. One `get_group_usage` parser test covering a representative
   snapshot.
6. One `attach_process` / `detach_process` pair proving correct
   PID movement.
7. One unsupported-limit test per OS that the spec marks as
   unsupported (e.g., IO limits on macOS) proving `FAILED` is
   returned.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Transient scope creation (`systemd-run --scope`) — RHEL
  extension.
- Nested slice hierarchies beyond a single-level parent.
- cgroup v1 compatibility shims.
- Per-device IO weighting beyond the abstract `IoLimitSpec`.
- CPU affinity / pinning (lives in `process-management`).
- PSI / pressure-stall-information reporting.
- Windows System Resource Manager policy authoring in full
  generality.
- launchd `HardResourceLimits` / `SoftResourceLimits` granularity
  beyond CPU / memory.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Substrate divergence is structural.** Ubuntu uses systemd
  slice units (cgroups v2, `/etc/systemd/system/<name>.slice` +
  `/sys/fs/cgroup/<name>.slice/`); macOS uses launchd plists at
  `/Library/LaunchDaemons/codecraftai-rc-<name>.plist` with
  `taskpolicy` for per-process attachment; Windows holds a
  logical record at `%ProgramData%\CodeCraftAI\rcgroups\<name>.json`
  applied via `Get-Process` because PowerShell exposes no clean
  Job Object cmdlets. The contract's group-container abstraction
  hides the substrate; the realisable feature surface does not.
- **macOS lacks per-group CPU and IO caps.** `set_cpu_quota` and
  `set_io_limits` return `FAILED` with the stable
  `macos_no_per_group_cpu_limit` and `macos_no_per_group_io_limit`
  tokens because launchd has no per-domain CPU quota or
  block-IO cap. See the README "FAILED with stable detail token"
  convention and stable-detail-token catalog.
- **Windows lacks PowerShell Job Object memory and IO caps.**
  `set_memory_limit` returns `FAILED` with
  `windows_no_powershell_job_object_memory_limit`;
  `set_io_limits` returns `FAILED` with
  `windows_no_powershell_io_limit`. Native P/Invoke would
  unlock these but is out of scope for the PowerShell-only pilot.
- **File I/O via `ICommandRunner`.** Slice-unit reads and writes,
  launchd plist edits, and the Windows logical-record JSON file
  all route through the runner using `cat` / `tee` /
  `Get-Content` / `Set-Content` rather than a separate
  `IFileOperator`. See the README "Implementation Conventions"
  file-I/O section.
- **Windows `elevation_blocked: bool`.** Job Object-adjacent
  writes and `Get-Process | Set-...` adjustments surface the
  structured Windows elevation extension. See the README
  "Implementation Conventions" elevation-blocked entry.
