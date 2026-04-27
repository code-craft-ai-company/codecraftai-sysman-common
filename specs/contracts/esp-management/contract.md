# ESP-Management Contract

This is the cross-OS abstract contract for the **esp-management**
feature. Every `automojo-sysman-*` package that ships an EFI System
Partition manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-uefi/specs/3-esp-management/`](../../../../../automojo-sysman-uefi/specs/3-esp-management/).
It locates the ESP, mounts and unmounts it, enumerates its contents,
and reads / writes / deletes files on it, using `findmnt`, `lsblk`,
and `mount` on Linux hosts, `diskutil` on macOS hosts, and
`Get-Partition`, `Get-Volume`, and `mountvol` on Windows hosts.
All command dispatch is through an `ICommandRunner`. The original
contract delegated file I/O on the mounted ESP to an
`IFileOperator`; the established cross-OS pattern is to route
file I/O through `ICommandRunner` using OS-native file utilities
(`cat`, `tee`, `cp`, `rm`, `Get-Content`, `Set-Content`,
`Remove-Item`). See the README "Implementation Conventions"
file-I/O convention.

This contract partially overlaps with the
[filesystem-management contract](../filesystem-management/contract.md):
mounting and unmounting are conceptually the same verbs. The
esp-management contract is distinct in that (a) there is exactly
one ESP per host, (b) the mount-point and device discovery is
firmware-metadata-driven rather than fstab-driven, and (c) file I/O
on the ESP happens through `ICommandRunner` (or, optionally,
`IFileOperator`) because the FAT filesystem's case-insensitive
path rules require care.

---

## Scope

The esp-management feature provides auditable access to the EFI
System Partition on a host. It covers:

- Locating the ESP (device, UUID, filesystem type).
- Mounting and unmounting the ESP at a coordinator-chosen mount
  point.
- Listing the ESP's contents at a subpath.
- Reading, writing, and deleting files on the mounted ESP.
- Reporting whether the ESP is currently mounted.
- Applying elevation for writes, not for reads.
- Supporting dry-run mode.

The feature is executed through an `ICommandRunner` for mount
operations and for file I/O on the mounted ESP (via OS-native
file utilities). Implementations MAY use an `IFileOperator` if
available. No direct `subprocess`, no direct filesystem I/O
outside the runner / file-operator seam.

---

## Verbs

Every OS implementation MUST expose an `EspManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_esp_info` | `() → EspInfo` | Read |
| `mount_esp` | `(mountpoint: str) → EspActionResult` | Write |
| `unmount_esp` | `(mountpoint: str) → EspActionResult` | Write |
| `is_esp_mounted` | `() → bool` | Read |
| `list_esp_contents` | `(path: str) → list[str]` | Read |
| `read_esp_file` | `(path: str) → bytes` | Read |
| `write_esp_file` | `(path: str, content: bytes) → EspActionResult` | Write |
| `delete_esp_file` | `(path: str) → EspActionResult` | Write |

**Writes** apply elevation per §Elevation and return
`EspActionResult`. **Reads** never elevate and return the specified
query value, or raise `EspQueryError`.

### Method-level invariants (writes)

1. **Idempotency guard.** Before calling `mount_esp`, the
   implementation MUST call `is_esp_mounted` and return `SKIPPED`
   when the ESP is already mounted at the requested mountpoint.
   Before calling `unmount_esp`, the implementation MUST return
   `SKIPPED` when the mountpoint is not currently an ESP mount.
   Before calling `write_esp_file`, the implementation MUST read
   the existing file's bytes (if any) and return `SKIPPED` when
   they byte-match the desired content.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or file operator.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` with `exit_code`, `stdout`, `stderr`, and `command`
   populated. `IFileOperator` failures MUST be caught and surfaced
   through `EspActionResult` with `status=FAILED` and a `detail`
   carrying the file-operator error message. Writes do NOT raise
   for routine failures.
4. **Mount precondition for file I/O.** `list_esp_contents`,
   `read_esp_file`, `write_esp_file`, and `delete_esp_file` MUST
   first call `is_esp_mounted`; when not mounted, these methods
   return `FAILED` (for writes) or raise `EspNotMountedError` (for
   reads). The manager MUST NOT auto-mount.
5. **Unsupported host OS.** On host OSes where a verb has no real
   implementation (macOS does not expose user-space ESP management
   cleanly because Apple owns the ESP), the method MUST return
   `FAILED` (for writes) or raise `EspQueryError` (for reads) with
   a descriptive `detail` pointing at the Apple-managed alternative.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner or file operator.
2. **Typed errors.** Query failures MAY raise `EspQueryError`
   or, per the per-OS spec, return an empty list / synthetic
   record so callers can proceed without a try/except wrapper.
   See the README "Implementation Conventions" graceful-read
   pattern. The legacy MUST-raise contract language continues:
   `EspQueryError`
   carrying the exit code and stderr. A "no ESP detected" signal
   MUST be surfaced as `EspInfo(device="", mountpoint=None, ...)`
   with `detected=False` rather than raising.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses, enum, and
exceptions, each prefixed with the OS name (see §Naming).

### `EspActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command / file operation succeeded. |
| `FAILED` | The command returned non-zero, a precondition failed, or the host OS does not implement the verb. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `EspActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `EspActionStatus` | Outcome category. |
| `path` | `str \| None` | The ESP-relative path (for file ops) or mountpoint (for mount ops). |
| `detail` | `str \| None` | Free-form detail. |
| `exit_code` | `int \| None` | Runner exit code (for mount ops). |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `EspInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `detected` | `bool` | Whether an ESP was located. |
| `device` | `str` | Device identifier (e.g., `/dev/sda1`, `disk0s1`, `PhysicalDrive0Partition1`). |
| `mountpoint` | `str \| None` | Current mountpoint when mounted; `None` when not mounted. |
| `fstype` | `str` | Filesystem type (`"vfat"`, `"msdos"`, `"FAT32"`). |
| `size_bytes` | `int` | Partition size. |
| `uuid` | `str \| None` | Filesystem UUID, where available. |
| `partition_guid` | `str \| None` | GPT partition GUID (the well-known ESP GUID `C12A7328-F81F-11D2-BA4B-00A0C93EC93B` is the expected value). |

### `EspQueryError` (exception)

Raised from read methods when the underlying query command fails.

### `EspNotMountedError` (exception)

Raised from read methods that require the ESP to be mounted
(`list_esp_contents`, `read_esp_file`) when `is_esp_mounted` is
`False`.

### `EspManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

Implementations MAY extend with OS-specific fields (e.g., the UEFI
package's `override_host_os`).

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner / file operator. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on Linux/macOS hosts; Administrator token on Windows hosts. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>EspManager
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
 ICommandRunner     IFileOperator
 (mount / query)    (file I/O on mounted ESP)
       │                 │
       └────────┬────────┘
                │
       ┌────────┴────────┐
       ▼                 ▼
 LocalCommandRunner  SSHCommandRunner
       │                 │
       └────────┬────────┘
                │  aspects compose here
                ▼
       PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner` and an `IFileOperator` in their
   constructor.
2. Never construct their own runner, file operator, or subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition.

---

## Naming

Concrete types per firmware are prefixed with the Pascal-case name.
No abbreviations.

| Abstract | UEFI | Future Firmware Variants |
|----------|------|--------------------------|
| `EspManager` | `UefiEspManager` | `<Firmware>EspManager` |
| `EspManagerConfig` | `UefiEspManagerConfig` | `<Firmware>EspManagerConfig` |
| `EspActionStatus` | `UefiEspActionStatus` | `<Firmware>EspActionStatus` |
| `EspActionResult` | `UefiEspActionResult` | `<Firmware>EspActionResult` |
| `EspInfo` | `UefiEspInfo` | `<Firmware>EspInfo` |
| `EspQueryError` | `UefiEspQueryError` | `<Firmware>EspQueryError` |
| `EspNotMountedError` | `UefiEspNotMountedError` | `<Firmware>EspNotMountedError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `EspActionResult` sequence when driven by a real
  runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One parser test for `get_esp_info` covering a realistic output.
2. One command-construction test per mount-related write verb.
3. One idempotency test for `mount_esp` (already mounted →
   `SKIPPED`) and `unmount_esp` (not mounted → `SKIPPED`).
4. One idempotency test for `write_esp_file` (byte-match → `SKIPPED`).
5. One precondition test proving `list_esp_contents` raises
   `EspNotMountedError` when the ESP is not mounted.
6. One precondition test proving `write_esp_file` returns `FAILED`
   when the ESP is not mounted.
7. One dry-run test per write verb.
8. One test per write verb proving `FAILED` with a descriptive
   `detail` on unsupported host OSes (UEFI only).
9. One elevation test proving writes pass `elevated=True` and reads
   do not.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Creating or deleting the ESP itself (partition creation / GPT
  authoring — covered by a separate storage contract if defined).
- Resizing the ESP.
- Running `fsck.vfat` / `chkdsk` on the ESP.
- Signing / verifying loaders placed on the ESP.
- Mounting additional (non-ESP) EFI-related partitions (the NVMe
  FFS partition, Apple's preboot volume) — those are vendor-
  specific and handled by the host OS.
- Encryption-at-rest on the ESP (unsupported by UEFI FAT).

---

## Implementation Drift

The UEFI implementation surfaced these intentional deviations from
the contract.

- **`override_host_os` config field.** `UefiEspManagerConfig`
  carries `override_host_os: str | None = None` so the manager
  can drive `findmnt` / `lsblk` (Linux), `diskutil` (macOS), and
  `Get-Partition` / `mountvol` (Windows) backends from a single
  host. See the README UEFI conventions.
- **macOS returns `unsupported_on_host_os_darwin` for many writes.**
  Apple owns the ESP on Apple Silicon and Apple-Silicon-class
  hosts; user-space ESP file writes are not realisable. The
  manager returns `FAILED` with the stable detail token. See
  the README stable-token catalog.
- **`ICommandRunner` for file I/O.** ESP file reads/writes route
  through the runner via `cat` / `tee` / `cp` / `rm` /
  `Get-Content` / `Set-Content` / `Remove-Item` rather than a
  separate `IFileOperator`.
