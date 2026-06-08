# Kdump-Management Contract

This is the cross-OS abstract contract for the **kdump-management**
feature. Every `codecraftai-sysman-*` package that ships a kdump manager
MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-kdump-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-kdump-management/).
It uses `kdumpctl`, `kdump.service`, `/etc/kdump.conf`, and the
`crashkernel=` kernel command-line reservation. Kdump is a
**Linux-primary feature**; macOS and Windows implementations MUST
map the verbs onto their native kernel-crash-dump facilities (macOS
kernel-panic logs in `/Library/Logs/DiagnosticReports/`; Windows
Memory.dmp / minidumps via `WER`). Those facilities do not share
kdump's pre-reserved-memory semantics, so the OS spec MUST document
precisely which verbs reduce to `FAILED` or `SKIPPED` in the native
model.

---

## Scope

The kdump-management feature provides idempotent, auditable
control over the host's kernel-crash-dump capture subsystem. It
covers:

- Enabling and disabling the kdump capture service (or its OS
  equivalent).
- Configuring the dump target (local path, NFS endpoint, SSH
  endpoint, raw device, or remote collector URI).
- Querying overall kdump status (service active, armed, reserved
  memory, dump target in effect).
- Listing recent crash-dump artifacts.
- Purging old crash-dump artifacts by age.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` if available; the
established cross-OS pattern is to route file I/O through
`ICommandRunner` using OS-native file utilities. See the README
"Implementation Conventions".

---

## Verbs

Every OS implementation MUST expose a `KdumpManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `enable_kdump` | `() → KdumpActionResult` | Write |
| `disable_kdump` | `() → KdumpActionResult` | Write |
| `configure_kdump_target` | `(spec: KdumpTargetSpec) → KdumpActionResult` | Write |
| `clear_old_dumps` | `(age_days: int) → KdumpActionResult` | Write |
| `get_kdump_status` | `() → KdumpStatus` | Read |
| `list_recent_dumps` | `() → list[KdumpArtifact]` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `enable_kdump` MUST return `SKIPPED` when
   the capture service is already active/enabled; `disable_kdump`
   MUST return `SKIPPED` when already disabled;
   `configure_kdump_target` MUST read the current target and return
   `SKIPPED` when the requested spec matches.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner. The `command` field MAY be populated
   with the argv that would have been executed.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Reboot advisory.** Writes that alter pre-reserved memory (the
   RHEL `crashkernel=` equivalent) MUST populate `detail` with a
   reboot-required advisory on `SUCCESS`. macOS / Windows
   implementations whose native dump engines do not require a reboot
   MAY omit the advisory.
5. **Platform-unsupported writes.** Any verb whose semantics do not
   map to the native OS facility MUST return `FAILED` with
   `detail="not supported on <os>: <reason>"` rather than raise.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `get_kdump_status` and `list_recent_dumps`
   MAY raise `KdumpQueryError` for unexpected failures or, per the
   per-OS spec, return an empty list / synthetic record so callers
   can proceed without a try/except wrapper. A system with no
   configured kdump MUST cause `get_kdump_status` to return
   `KdumpStatus(enabled=False, armed=False, reserved_bytes=0, ...)`
   rather than raise. See the README "Implementation Conventions"
   graceful-read pattern.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `KdumpActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or the verb is not supported on the OS. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `KdumpActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `KdumpActionStatus` | Outcome category. |
| `action` | `str` | Short identifier of the action (e.g., `"enable"`, `"configure_target"`, `"clear_old_dumps"`). |
| `detail` | `str \| None` | Human-readable explanation, reboot advisory, or `"not supported"` rationale. |
| `exit_code` | `int \| None` | Runner exit code for `SUCCESS` / `FAILED`. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `KdumpTargetKind` (enum)

| Value | Meaning |
|-------|---------|
| `LOCAL_PATH` | A filesystem path on the host. |
| `NFS` | An NFS URI (`host:/path`). |
| `SSH` | An SSH endpoint (`user@host:/path`). |
| `RAW_DEVICE` | A raw block device (`/dev/sdb`). |
| `REMOTE_COLLECTOR` | A vendor-specific collector (e.g., Windows remote dump share, macOS diagnostic-report export). |

### `KdumpTargetSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `KdumpTargetKind` | The target kind. |
| `location` | `str` | The target locator (path, URI, device). |
| `options` | `dict[str, str]` | Optional key/value options (compression, ssh key path, credentials reference, etc.). |

### `KdumpStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | `bool` | Whether capture is enabled at boot / service level. |
| `armed` | `bool` | Whether the kernel is currently armed to capture (kexec loaded on Linux, equivalent on other OSes — `False` if N/A). |
| `reserved_bytes` | `int` | Memory currently reserved for capture (`0` when N/A). |
| `target` | `KdumpTargetSpec \| None` | The current dump target, if any. |
| `service_active` | `bool` | Whether the capture service / background facility is active. |

### `KdumpArtifact` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Path to the artifact file or directory. |
| `created_at` | `datetime \| None` | Creation time, UTC, if available. |
| `size_bytes` | `int` | Size on disk. |
| `kind` | `str` | Native type (e.g., `"vmcore"`, `"minidump"`, `"panic.ips"`). |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `KdumpQueryError` | A read fails for a reason other than "kdump not configured". |

### `KdumpManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Target Mapping

The abstract `KdumpTargetSpec` maps to each OS's native crash-dump
target concept.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `/etc/kdump.conf` `path` / `nfs` / `ssh` / `raw` directives | Canonical. Reboot required for `crashkernel=` changes. |
| Ubuntu | `kdump-tools` with `/etc/default/kdump-tools` and `/etc/kdump-tools.d/` | Same semantics as RHEL; rebuild via `kdump-config`. |
| macOS | `/Library/Logs/DiagnosticReports/` plus `sudo sysctl kern.panic_minidump` | No pre-reserved memory. Target is essentially fixed; `configure_kdump_target` with anything but `LOCAL_PATH` MUST return `FAILED`. |
| Windows | `HKLM\SYSTEM\CurrentControlSet\Control\CrashControl` (`DumpFile`, `MinidumpDir`, `CrashDumpEnabled`) | No pre-reserved memory beyond pagefile sizing. `SSH` / `NFS` targets MUST return `FAILED`. |
| UEFI | N/A | UEFI has no kernel-crash-dump concept. The kdump-management contract does not apply. |

Each OS spec MUST include a Target-Mapping section describing its
native directives and the `FAILED` cases for unsupported target
kinds.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner (and to the file operator for `/etc/kdump.conf` writes, registry writes on Windows, etc.). |
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
        <Os>KdumpManager
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

1. Accept an `ICommandRunner` and a `KdumpManagerConfig` in their
   constructor. Implementations that touch `/etc/kdump.conf` or
   registry-backed configuration MAY also accept an `IFileOperator`.
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
| `KdumpManager` | `UbuntuKdumpManager` | `MacosKdumpManager` | `WindowsKdumpManager` | `KdumpManager` |
| `KdumpManagerConfig` | `UbuntuKdumpManagerConfig` | `MacosKdumpManagerConfig` | `WindowsKdumpManagerConfig` | `KdumpManagerConfig` |
| `KdumpActionStatus` | `UbuntuKdumpActionStatus` | `MacosKdumpActionStatus` | `WindowsKdumpActionStatus` | `KdumpActionStatus` |
| `KdumpActionResult` | `UbuntuKdumpActionResult` | `MacosKdumpActionResult` | `WindowsKdumpActionResult` | `KdumpActionResult` |
| `KdumpTargetKind` | `UbuntuKdumpTargetKind` | `MacosKdumpTargetKind` | `WindowsKdumpTargetKind` | `KdumpTargetKind` |
| `KdumpTargetSpec` | `UbuntuKdumpTargetSpec` | `MacosKdumpTargetSpec` | `WindowsKdumpTargetSpec` | `KdumpTargetSpec` |
| `KdumpStatus` | `UbuntuKdumpStatus` | `MacosKdumpStatus` | `WindowsKdumpStatus` | `KdumpServiceState` (combined) |
| `KdumpArtifact` | `UbuntuKdumpArtifact` | `MacosKdumpArtifact` | `WindowsKdumpArtifact` | `KdumpArtifact` |
| `KdumpQueryError` | `UbuntuKdumpQueryError` | `MacosKdumpQueryError` | `WindowsKdumpQueryError` | `KdumpQueryError` |

The RHEL reference keeps legacy names for the service-state
aggregate; new OS packages MUST use the abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `KdumpActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
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
4. One `get_kdump_status` test for an enabled + armed host and a
   disabled host.
5. One `list_recent_dumps` parser test covering a representative
   sample with at least two artifacts.
6. One `clear_old_dumps` test proving that only artifacts older
   than `age_days` are removed.
7. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.
8. One "not supported" test per verb that the OS reduces to
   `FAILED` by design, proving the failure path is wired correctly.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- kdump initramfs rebuild and module selection (RHEL `kdumpctl
  rebuild`).
- Core-dump handler configuration (`systemd-coredump`, macOS
  `CrashReporter`).
- Compression algorithm selection.
- Remote-collector authentication material (delegated to the
  credentials layer).
- Post-capture actions / triggers.
- Full parsing of vmcore / minidump contents.
- Capture-time encryption.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence.** Ubuntu wraps `kexec-tools` /
  `/etc/default/kdump-tools`; macOS maps to the
  `CrashReporter` / `panic.log` framework; Windows maps to the
  Memory.DMP / minidump policy via registry keys.
- **`detail="windows_no_kdump_concept"`.** The Windows manager
  returns `FAILED` with this stable detail token for verbs
  whose semantics do not map to the Windows crash-dump model
  (e.g., per-target reservation tuning). See the README
  stable-token catalog.
- **File I/O via `ICommandRunner`.** `/etc/kdump.conf`,
  `kdump-tools` config, and registry-key reads route through
  the runner.
