# Storage-Management Contract

This is the cross-OS abstract contract for the
**storage-management** feature. Every `codecraftai-sysman-*` package
that ships a storage manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-storage-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-storage-management/).
It uses LVM (`pvcreate`, `vgcreate`, `lvcreate`, `lvextend`,
`lvremove`, `vgs`, `lvs`, `pvs`) and optionally `mdadm` through
an `ICommandRunner`. This contract generalises the verb set for
macOS (`diskutil` + APFS containers / volumes) and Windows
(`Get-Disk`, `New-Partition`, `New-VirtualDisk` / Storage Spaces,
and `diskpart`).

---

## Scope

The storage-management feature provides idempotent, auditable
control over a host's block storage above the partition layer. It
covers:

- Enumerating disks and volumes.
- Creating, deleting, and resizing volumes.
- Creating and deleting storage pools (volume groups / APFS
  containers / Storage Spaces storage pools).
- Adding and removing physical devices from a pool.
- Querying detailed disk and volume information.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

Filesystem formatting and mounting are NOT part of this contract
— those live in `filesystem-management`. This contract stops at
the volume boundary.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `StorageManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_disks` | `() → list[DiskInfo]` | Read |
| `list_volumes` | `() → list[VolumeInfo]` | Read |
| `create_volume` | `(spec: VolumeSpec) → StorageActionResult` | Write |
| `delete_volume` | `(id: str) → StorageActionResult` | Write |
| `resize_volume` | `(id: str, size_bytes: int) → StorageActionResult` | Write |
| `create_pool` | `(spec: PoolSpec) → StorageActionResult` | Write |
| `delete_pool` | `(name: str) → StorageActionResult` | Write |
| `add_to_pool` | `(name: str, disk_id: str) → StorageActionResult` | Write |
| `remove_from_pool` | `(name: str, disk_id: str) → StorageActionResult` | Write |
| `get_volume_info` | `(id: str) → VolumeInfo \| None` | Read |
| `get_disk_info` | `(id: str) → DiskInfo \| None` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_volume` MUST return `SKIPPED`
   when a volume with the same identity and spec already exists.
   `delete_volume` MUST return `SKIPPED` when no such volume
   exists. `resize_volume` MUST return `SKIPPED` when the volume
   is already at the requested size (within the OS's granularity).
   `create_pool` / `delete_pool` follow the same pattern on pool
   identity. `add_to_pool` MUST return `SKIPPED` when the disk is
   already a member; `remove_from_pool` MUST return `SKIPPED`
   when the disk is not a member.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Data-loss advisory.** `delete_volume`, `delete_pool`, and
   `remove_from_pool` MUST populate `detail` on `SUCCESS` with a
   data-loss advisory so the coordinator can surface it.
5. **Growth vs. shrink.** `resize_volume` MUST NOT shrink a
   volume whose current filesystem the implementation cannot
   safely shrink. The OS spec MUST enumerate the shrink-support
   matrix; unsupported shrinks MUST return `FAILED`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MUST raise
   `StorageQueryError`. An unknown id MUST cause `get_volume_info`
   / `get_disk_info` to return `None`.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `StorageActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a shrink was refused. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `DiskInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Stable disk identifier (`/dev/sda` on Linux, `disk0` on macOS, disk number on Windows). |
| `size_bytes` | `int` | Total disk size. |
| `vendor` | `str \| None` | Vendor string when available. |
| `model` | `str \| None` | Model string when available. |
| `serial` | `str \| None` | Serial number when available. |
| `rotational` | `bool \| None` | Rotational-vs-SSD hint when available. |
| `member_of_pool` | `str \| None` | Pool / volume-group this disk belongs to, if any. |

### `VolumeInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Stable volume identifier. |
| `name` | `str` | Human-facing name. |
| `pool` | `str \| None` | Parent pool / VG / container, if any. |
| `size_bytes` | `int` | Current size. |
| `kind` | `str` | Native kind (`"lvm-linear"`, `"apfs"`, `"storage-spaces"`). |

### `VolumeSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Volume name. |
| `pool` | `str \| None` | Parent pool name, or `None` for whole-disk volumes. |
| `size_bytes` | `int` | Requested size. |
| `options` | `dict[str, str]` | OS-specific extra options (mirror count, RAID level, provisioning). |

### `PoolSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Pool name. |
| `disks` | `list[str]` | Disk ids to include at creation. |
| `redundancy` | `str \| None` | Native redundancy selection (`"mirror"`, `"raid5"`, `"simple"`). |
| `options` | `dict[str, str]` | OS-specific extra options. |

### `StorageActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `StorageActionStatus` | Outcome category. |
| `action` | `str` | Short identifier (e.g., `"create_volume:data"`). |
| `detail` | `str \| None` | Human-readable explanation or data-loss advisory. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `StorageQueryError` | A read fails for a reason other than "id unknown". |

### `StorageManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |

---

## Pool / Volume Mapping

The abstract pool + volume concept maps to each OS's native
storage-abstraction layer.

| OS | Pool | Volume | Notes |
|----|------|--------|-------|
| Red Hat Enterprise Linux | LVM Volume Group | LVM Logical Volume | Canonical. Commands: `vgcreate`, `vgextend`, `vgreduce`, `vgremove`, `lvcreate`, `lvextend`, `lvremove`. `mdadm`-backed RAID is an extension. |
| Ubuntu | Same as RHEL (LVM) | Same as RHEL | — |
| macOS | APFS Container | APFS Volume | Commands: `diskutil apfs createContainer`, `diskutil apfs addVolume`, `diskutil apfs deleteVolume`. |
| Windows | Storage Pool | Virtual Disk (Storage Spaces) or Volume | Commands: `New-StoragePool`, `New-VirtualDisk`, `New-Volume`, `Remove-*`. `diskpart` is an extension. |
| UEFI | N/A | N/A | UEFI ESP partitioning lives in `esp-management`; generic storage does not apply. |

Each OS spec MUST include a Pool-Volume-Mapping section stating
its command surface, identifier syntax, and the shrink-support
matrix.

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
        <Os>StorageManager
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

1. Accept an `ICommandRunner` and a `StorageManagerConfig` in
   their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `StorageManager` | `UbuntuStorageManager` | `MacosStorageManager` | `WindowsStorageManager` | `StorageManager` |
| `StorageManagerConfig` | `UbuntuStorageManagerConfig` | `MacosStorageManagerConfig` | `WindowsStorageManagerConfig` | `StorageManagerConfig` |
| `StorageActionStatus` | `UbuntuStorageActionStatus` | `MacosStorageActionStatus` | `WindowsStorageActionStatus` | `StorageActionStatus` |
| `StorageActionResult` | `UbuntuStorageActionResult` | `MacosStorageActionResult` | `WindowsStorageActionResult` | `StorageActionResult` |
| `DiskInfo` | `UbuntuDiskInfo` | `MacosDiskInfo` | `WindowsDiskInfo` | `PhysicalVolumeInfo` |
| `VolumeInfo` | `UbuntuVolumeInfo` | `MacosVolumeInfo` | `WindowsVolumeInfo` | `LogicalVolumeInfo` |
| `VolumeSpec` | `UbuntuVolumeSpec` | `MacosVolumeSpec` | `WindowsVolumeSpec` | `LogicalVolumeSpec` |
| `PoolSpec` | `UbuntuPoolSpec` | `MacosPoolSpec` | `WindowsPoolSpec` | `VolumeGroupSpec` |
| `StorageQueryError` | `UbuntuStorageQueryError` | `MacosStorageQueryError` | `WindowsStorageQueryError` | `StorageQueryError` |

The RHEL reference uses LVM-flavoured names; new OS packages use
the abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `StorageActionResult` sequence when driven by a
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
4. One `list_disks` parser test covering multiple disks.
5. One `list_volumes` parser test covering multiple volumes
   across at least two pools.
6. One `create_pool` + `create_volume` round-trip construction
   test.
7. One `resize_volume` shrink-refused test per OS that the spec
   marks as shrink-unsupported.
8. One data-loss-advisory test proving `detail` is populated on
   `delete_volume` / `delete_pool` / `remove_from_pool`.
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Filesystem creation / formatting — lives in
  `filesystem-management`.
- Mount-point management — lives in `filesystem-management`.
- Partition-table editing — lives in `filesystem-management` or
  `boot-management` depending on scope.
- Encryption at the volume layer (LUKS / FileVault / BitLocker)
  — lives in `encryption-management`.
- RAID rebuild operations.
- Snapshot creation / revert at the storage layer (may be added
  as an extension; snapshots at VM layer live in
  `virtualization-management`).
- Multipath / FC HBA configuration.
- NVMe-oF / iSCSI target configuration.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Substrate divergence is structural.** Ubuntu wraps LVM
  (`pvcreate` / `vgcreate` / `vgextend` / `lvcreate` /
  `lvremove` / `lvresize`); macOS wraps APFS via
  `diskutil apfs createContainer / addVolume / resizeContainer`
  on the BSD device tree; Windows wraps Storage Spaces
  (`New-StoragePool` / `New-Volume` / `Add-PhysicalDisk` /
  `Remove-PhysicalDisk`) plus the raw-partition flow
  (`New-Partition` + `Format-Volume`) for non-pooled disks.
  Volume identifiers diverge accordingly: `<vg>/<lv>` (Ubuntu),
  BSD device id `disk1s2` (macOS), drive letter or volume id
  (Windows).
- **APFS shared-sizing inverts the resize verb.** APFS volumes
  share their container's free space and have no fixed size of
  their own. `resize_volume` on macOS dispatches
  `diskutil apfs resizeContainer` rather than a per-volume
  resize, and the per-OS spec documents the shared-sizing model
  in detail.
- **Resiliency model is per-OS.** Ubuntu has none natively
  (operators layer `mdadm` underneath); macOS is Apple-managed
  and not exposed; Windows surfaces
  `ResiliencySettingName` (`Mirror` / `Parity` / `Simple`) on
  the pool plus per-`New-Volume` overrides. The contract treats
  resiliency as an optional pool field; the per-OS specs
  enforce when it is meaningful.
- **File I/O via `ICommandRunner`.** macOS plist parsing routes
  through `diskutil ... -plist | plutil -convert json` on the
  runner; Windows JSON conversion uses
  `ConvertTo-Json`; Ubuntu LVM tools emit text directly. No
  separate `IFileOperator` is involved. See the README
  "Implementation Conventions" file-I/O section.
- **Windows `elevation_blocked: bool`.** `New-StoragePool` /
  `Remove-StoragePool` / `New-Volume` / `Add-PhysicalDisk`
  writes surface the structured Windows elevation extension.
  See the README "Implementation Conventions"
  elevation-blocked entry.
