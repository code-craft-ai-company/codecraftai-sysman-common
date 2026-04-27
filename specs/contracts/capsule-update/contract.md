# Capsule-Update Contract

This is the cross-OS abstract contract for the **capsule-update**
feature. Every `automojo-sysman-*` package that ships a capsule-
update manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-uefi/specs/3-capsule-update/`](../../../../../automojo-sysman-uefi/specs/3-capsule-update/).
It wraps `fwupdmgr` on Linux hosts (the canonical UEFI capsule-
update surface), reports via `softwareupdate` on macOS hosts (which
do not expose capsule updates directly — the manager reports macOS-
native firmware updates as a delegation), and wraps the
`PSWindowsUpdate` module filtered to firmware on Windows hosts. All
dispatch is through an `ICommandRunner`.

---

## Scope

The capsule-update feature provides auditable, idempotent control
over firmware capsule updates (the standardised UEFI firmware-update
mechanism). It covers:

- Listing available firmware updates on the host.
- Applying an update by identifier.
- Installing a pre-downloaded capsule file.
- Listing devices whose firmware can be updated.
- Reading the firmware-update history.
- Applying elevation for writes, not for reads.
- Supporting dry-run mode.

The feature is executed exclusively through an `ICommandRunner`.
No direct `subprocess`, no direct capsule staging.

---

## Verbs

Every OS implementation MUST expose a `CapsuleUpdateManager` class
(the OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_available_updates` | `(device_id: str \| None) → list[CapsuleUpdateInfo]` | Read |
| `apply_update` | `(update_id: str) → CapsuleUpdateActionResult` | Write |
| `apply_capsule_file` | `(capsule_path: str) → CapsuleUpdateActionResult` | Write |
| `list_devices` | `() → list[DeviceInfo]` | Read |
| `get_update_status` | `(limit: int \| None) → list[CapsuleUpdateHistoryEntry]` | Read |

**Writes** apply elevation per §Elevation and return
`CapsuleUpdateActionResult`. **Reads** never elevate and return the
specified query dataclass, or raise `CapsuleUpdateQueryError`.

### Method-level invariants (writes)

1. **Idempotency guard.** Before calling `apply_update`, the
   implementation MUST call `list_available_updates` and verify that
   the `update_id` is in the pending list. An `update_id` that is
   not in the pending list (because it has already been applied or
   because it was never offered) MUST return `SKIPPED` with a
   descriptive `detail`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` with `exit_code`, `stdout`, `stderr`, and `command`
   populated. Writes do NOT raise.
4. **Unsupported host OS.** `apply_update` and `apply_capsule_file`
   MUST return `FAILED` with a delegation `detail` on host OSes that
   do not expose user-space capsule application (macOS on both
   Intel and Apple Silicon; Windows for `apply_capsule_file` where
   raw capsule files are not scriptable). The `detail` MUST name the
   alternative surface the operator should use
   (`softwareupdate` on macOS, `Install-WindowsUpdate` filtered to
   firmware on Windows).
5. **Post-apply reboot hint.** A `CapsuleUpdateActionResult` with
   status `SUCCESS` MUST set `requires_reboot=True` on its
   `CapsuleUpdateInfo` in the `applied` field — firmware capsules
   take effect on next boot.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, regardless of config.
2. **Typed errors.** Query failures MAY raise
   `CapsuleUpdateQueryError` carrying the exit code and stderr, OR
   (per the per-OS spec) return an empty list / synthetic record
   so callers can proceed without a try/except wrapper. See the
   README "Implementation Conventions" graceful-read pattern.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses, enum, and
exception, each prefixed with the OS name (see §Naming).

### `CapsuleUpdateActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The capsule was staged / applied. |
| `FAILED` | The command returned non-zero, or the host OS does not implement the verb. |
| `SKIPPED` | The update was already applied or is not in the pending list. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `CapsuleUpdateActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `CapsuleUpdateActionStatus` | Outcome category. |
| `update_id` | `str \| None` | The update ID the action targeted, or `None` for capsule-file installs. |
| `capsule_path` | `str \| None` | Capsule file path, when applicable. |
| `applied` | `CapsuleUpdateInfo \| None` | The update record that was applied. |
| `detail` | `str \| None` | Free-form detail: delegation message or progress summary. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `CapsuleUpdateInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `update_id` | `str` | Identifier of the update (GUID assigned by the update backend). |
| `device_id` | `str` | Target device identifier. |
| `current_version` | `str` | Current firmware version on the device. |
| `available_version` | `str` | Version offered by the update. |
| `summary` | `str` | Short human-readable summary. |
| `requires_reboot` | `bool` | Whether activation requires a reboot. |
| `severity` | `str` | Severity label (`"low"`, `"medium"`, `"high"`, `"critical"`, or backend-specific). |

### `DeviceInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | `str` | Firmware-updatable device identifier (GUID). |
| `vendor` | `str` | Vendor name. |
| `product` | `str` | Product name. |
| `current_version` | `str` | Current firmware version. |
| `supported` | `bool` | Whether the backend can update the device. |

### `CapsuleUpdateHistoryEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `update_id` | `str` | Identifier of the applied update. |
| `device_id` | `str` | Target device. |
| `applied_version` | `str` | Version that was applied. |
| `applied_at` | `str` | ISO-8601 timestamp string. |
| `result` | `str` | Backend-reported result label. |

### `CapsuleUpdateQueryError` (exception)

Raised from read methods when the underlying query command fails.

### `CapsuleUpdateManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |
| `allow_downgrade` | `bool` | `False` | When `True`, writes may apply updates whose `available_version` is older than `current_version`. |

Implementations MAY extend with OS-specific fields (e.g., the UEFI
package's `override_host_os`).

---

## Device-ID Mapping

The abstract `device_id` parameter maps to the native firmware-
updatable-device identifier concept of each host OS:

| OS | Native concept | Notes |
|----|----------------|-------|
| UEFI on Linux | fwupd GUID (e.g., `b8fe6b66-c42a-5c69-a2c9-10d1f1e7e4b1`) | Canonical form. |
| UEFI on macOS | Apple `PlatformIdentifier` from `system_profiler` | macOS does not expose capsule-level IDs; `DeviceInfo.device_id` is the Apple hardware identifier. |
| UEFI on Windows | `PSWindowsUpdate` update-UUID | Scoped to firmware updates only. |

Each OS spec MUST include a Device-ID-Mapping section stating its
chosen identifier form.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on Linux/macOS hosts; Administrator token on Windows hosts. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>CapsuleUpdateManager
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

1. Accept an `ICommandRunner` in their constructor.
2. Never construct their own runner or subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition.

---

## Naming

Concrete types per firmware are prefixed with the Pascal-case name.
No abbreviations.

| Abstract | UEFI | Future Firmware Variants |
|----------|------|--------------------------|
| `CapsuleUpdateManager` | `UefiCapsuleUpdateManager` | `<Firmware>CapsuleUpdateManager` |
| `CapsuleUpdateManagerConfig` | `UefiCapsuleUpdateManagerConfig` | `<Firmware>CapsuleUpdateManagerConfig` |
| `CapsuleUpdateActionStatus` | `UefiCapsuleUpdateActionStatus` | `<Firmware>CapsuleUpdateActionStatus` |
| `CapsuleUpdateActionResult` | `UefiCapsuleUpdateActionResult` | `<Firmware>CapsuleUpdateActionResult` |
| `CapsuleUpdateInfo` | `UefiCapsuleUpdateInfo` | `<Firmware>CapsuleUpdateInfo` |
| `DeviceInfo` | `UefiDeviceInfo` | `<Firmware>DeviceInfo` |
| `CapsuleUpdateHistoryEntry` | `UefiCapsuleUpdateHistoryEntry` | `<Firmware>CapsuleUpdateHistoryEntry` |
| `CapsuleUpdateQueryError` | `UefiCapsuleUpdateQueryError` | `<Firmware>CapsuleUpdateQueryError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `CapsuleUpdateActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test for `apply_update` proving `SKIPPED` when
   the `update_id` is not in the pending list.
3. One dry-run test per write verb.
4. One parser test for `list_available_updates` covering multiple
   pending updates.
5. One parser test for `list_devices`.
6. One parser test for `get_update_status` covering a historical
   success and failure.
7. One test per write verb proving delegation `FAILED` with a
   descriptive `detail` on unsupported host OSes (UEFI only).
8. One elevation test proving writes pass `elevated=True` and reads
   do not.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Vendor-specific firmware signing or verification beyond what the
  update backend already performs.
- Rolling back firmware to a prior version (fwupd supports this in
  limited cases; the base contract does not mandate a verb).
- Scheduling an update to run at a future boot (the `BootNext` +
  capsule-staging pattern). Implementations MAY surface this via
  the boot-management verb `set_boot_next` in tandem.
- UEFI ESRT decoding / parsing. Implementations MAY surface ESRT
  contents through `DeviceInfo` but are not required to.
- Vendor telemetry submission (e.g., fwupd's `report` upload).

---

## Implementation Drift

The UEFI implementation surfaced these intentional deviations from
the contract.

- **`override_host_os` config field.** `UefiCapsuleUpdateManagerConfig`
  carries `override_host_os: str | None = None` so the manager can
  drive `fwupd` (Linux), `bless`/firmware-update (macOS), and
  Windows Update / DISM-staged capsules from a single host. See
  the README UEFI conventions.
- **Stable detail tokens for unsupported combos.** The manager
  returns `FAILED` with `detail="firmware_setup_ui_only"` when the
  host requires a firmware-setup UI step, and
  `detail="firmware_downgrade_blocked"` when capsule version-lock
  policy refuses a downgrade. See the README stable-token catalog.
- **`requires_reboot: bool` on apply results.** Firmware capsules
  always take effect on next boot; the action-result carries
  `requires_reboot=True` so the coordinator can sequence reboots.
- **OS-prefixed naming.** All concrete types use the `Uefi` prefix.
