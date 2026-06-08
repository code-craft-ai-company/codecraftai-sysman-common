# Filesystem-Management Contract

This is the cross-OS abstract contract for the **filesystem-management**
feature. Every `codecraftai-sysman-*` package that ships a filesystem
manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-filesystem-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-filesystem-management/).
It uses `mount`, `umount`, `findmnt`, `stat`, `df`, `mkdir`, `rm`,
`chmod`, `chown`, and `/etc/fstab` rewrites through an
`ICommandRunner`. This contract generalises that shape for OSes
whose filesystem surface includes `diskutil`, `mount.exe`,
`Get-PSDrive`, and the UEFI boot-partition tooling.

---

## Scope

The filesystem-management feature provides idempotent, auditable
control over mounts, persistent mount tables, directory/file
creation, ownership, permissions, and disk-usage inspection. It
covers:

- Mounting and unmounting devices at mount points.
- Adding and removing persistent mount-table entries.
- Listing current mounts.
- Creating and removing directories (including recursive removal).
- Creating and removing symbolic links.
- Querying a path's stat-like metadata.
- Querying disk usage for a path.
- Changing file/directory ownership and permissions.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `FilesystemManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `mount` | `(device: str, mountpoint: str, fstype: str \| None, options: str \| None) → FilesystemActionResult` | Write |
| `unmount` | `(mountpoint: str, lazy: bool) → FilesystemActionResult` | Write |
| `add_fstab_entry` | `(entry: FstabEntry) → FilesystemActionResult` | Write |
| `remove_fstab_entry` | `(device_or_mountpoint: str) → FilesystemActionResult` | Write |
| `get_mounts` | `() → list[MountInfo]` | Read |
| `create_directory` | `(path: str, mode: int \| None, owner: str \| None, group: str \| None) → FilesystemActionResult` | Write |
| `remove_directory` | `(path: str, recursive: bool) → FilesystemActionResult` | Write |
| `create_symlink` | `(link: str, target: str) → FilesystemActionResult` | Write |
| `remove_symlink` | `(link: str) → FilesystemActionResult` | Write |
| `chown` | `(path: str, user: str \| None, group: str \| None) → FilesystemActionResult` | Write |
| `chmod` | `(path: str, mode: int) → FilesystemActionResult` | Write |
| `stat` | `(path: str) → FileInfo \| None` | Read |
| `query_disk_usage` | `(path: str) → DiskUsageInfo` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** Before any write, the manager MUST check
   the current state (via `stat`, `get_mounts`, or a read of the
   persistent mount table) and compare to the desired state.
   Matching state MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` with `exit_code`, `stdout`, `stderr`, and `command`
   populated. Writes do NOT raise for routine I/O.
4. **Type conflict detection.** `create_symlink` MUST return
   `FAILED` (not `SUCCESS` or `SKIPPED`) when the link path exists
   as a non-symlink. `remove_symlink` MUST return `FAILED` when the
   path exists but is not a symlink.
5. **Persistent-table updates.** `add_fstab_entry` /
   `remove_fstab_entry` MUST preserve unrelated entries in the
   persistent mount table across a read-modify-write cycle.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `stat` MUST return `None` for a non-existent
   path; other read failures MAY raise `FilesystemQueryError` or,
   per the per-OS spec, return an empty list / synthetic record so
   callers can proceed without a try/except wrapper. See the README
   "Implementation Conventions" graceful-read pattern. (`get_mounts`
   on every OS returns an empty list when the mount tool is absent;
   this is the canonical reference example.)
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `FilesystemActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `FilesystemActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `FilesystemActionStatus` | Outcome category. |
| `path` | `str` | The target path or mount point. |
| `detail` | `str \| None` | Human-readable detail for `SKIPPED` or `FAILED`. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `MountInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `device` | `str` | The backing device identifier. |
| `mountpoint` | `str` | The mount point path. |
| `fstype` | `str` | The filesystem type. |
| `options` | `str` | The comma-separated options string. |

### `FstabEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `device` | `str` | Device or UUID specifier. |
| `mountpoint` | `str` | Mount point path. |
| `fstype` | `str` | Filesystem type. |
| `options` | `str` | Mount options (default `"defaults"`). |
| `dump` | `int` | Dump field (default `0`). |
| `passno` | `int` | fsck pass number (default `0`). |

### `FileInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Absolute path. |
| `path_type` | `str` | Native type label (e.g., `"regular file"`, `"directory"`, `"symbolic link"`). |
| `mode` | `str` | Octal mode string (e.g., `"755"`). |
| `owner` | `str` | Owner name. |
| `group` | `str` | Group name. |
| `size_bytes` | `int` | Size in bytes. |

### `DiskUsageInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | The path whose usage was queried. |
| `total_bytes` | `int` | Total capacity. |
| `used_bytes` | `int` | Bytes used. |
| `available_bytes` | `int` | Bytes available. |
| `use_percent` | `int` | Integer use percentage 0..100. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `FilesystemQueryError` | `get_mounts` or `query_disk_usage` fails for reasons other than a missing path. |

### `FilesystemManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |
| `fstab_path` | `str \| None` | OS-default | Path to the persistent mount table; overridable for testing. |

---

## Persistent-Mount-Table Mapping

The abstract `add_fstab_entry` / `remove_fstab_entry` verbs operate
on each OS's persistent mount table.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `/etc/fstab` | Canonical. Six-field entries. |
| Ubuntu | `/etc/fstab` | Same as RHEL. |
| macOS | `/etc/fstab` (advisory only; diskutil / auto-mount override it) and `/Library/LaunchDaemons/<label>.plist` for launchd-triggered mounts | macOS spec MUST state which surface it writes to. |
| Windows | `mountvol` / `assign` persistence through drive-letter and mount-point registry entries | Implementations SHOULD use PowerShell `Set-Partition -DriveLetter` / `Add-PartitionAccessPath` equivalents. UUID identification uses disk-signature / GPT-GUID. |
| UEFI | ESP boot entries and FAT boot partition mounts | **In scope** for UEFI: boot-partition mount operations. The `FstabEntry` fields map to ESP GUID / LoadOption variables. |

Each OS spec MUST include a Mount-Table-Mapping section describing
which surface it writes and how it represents a mount-table entry.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows; EFI privilege mode under UEFI. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>FilesystemManager
                │
                │  .run(argv, elevated=…, stdin=…, capture_output=True)
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

1. Accept an `ICommandRunner` and a `FilesystemManagerConfig` in
   their constructor.
2. Never construct their own runner or subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `FilesystemManager` | `UbuntuFilesystemManager` | `MacosFilesystemManager` | `WindowsFilesystemManager` | `FilesystemManager` |
| `FilesystemManagerConfig` | `UbuntuFilesystemManagerConfig` | `MacosFilesystemManagerConfig` | `WindowsFilesystemManagerConfig` | `FilesystemManagerConfig` |
| `FilesystemActionStatus` | `UbuntuFilesystemActionStatus` | `MacosFilesystemActionStatus` | `WindowsFilesystemActionStatus` | `FilesystemActionStatus` |
| `FilesystemActionResult` | `UbuntuFilesystemActionResult` | `MacosFilesystemActionResult` | `WindowsFilesystemActionResult` | `FilesystemActionResult` |
| `MountInfo` | `UbuntuMountInfo` | `MacosMountInfo` | `WindowsMountInfo` | `MountInfo` |
| `FstabEntry` | `UbuntuFstabEntry` | `MacosFstabEntry` | `WindowsFstabEntry` | `FstabEntry` |
| `FileInfo` | `UbuntuFileInfo` | `MacosFileInfo` | `WindowsFileInfo` | `FileInfo` |
| `DiskUsageInfo` | `UbuntuDiskUsageInfo` | `MacosDiskUsageInfo` | `WindowsDiskUsageInfo` | `DiskUsageInfo` |
| `FilesystemQueryError` | `UbuntuFilesystemQueryError` | `MacosFilesystemQueryError` | `WindowsFilesystemQueryError` | `FilesystemQueryError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `FilesystemActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One conflict test for `create_symlink` (non-symlink at path)
   proving `FAILED`.
4. One conflict test for `remove_symlink` (non-symlink at path)
   proving `FAILED`.
5. One parser test per read verb covering realistic output.
6. One `stat` test for a missing path proving `None` is returned.
7. One dry-run test per write verb proving the runner is not
   invoked.
8. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Filesystem creation (`mkfs`), resize, or fsck.
- Filesystem quotas (covered by a separate contract if defined).
- ACL / extended-attribute / SELinux-label manipulation.
- Encryption-at-rest configuration (LUKS, FileVault, BitLocker).
- Snapshots (LVM, APFS, VSS).
- Named-pipe / device-node creation.
- Hard-link management.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`detail="attribute_preservation_read_failed"`.** Some
  attribute-preserving writes (xattr / extended ACL / Windows
  Alternate Data Streams) read the existing attributes before
  writing; if that pre-read fails, the manager returns `FAILED`
  with this stable detail token. See the README stable-token
  catalog.
- **`detail="destructive_operation_requires_explicit_confirm"`.**
  Verbs such as `delete` / `delete_directory` / `truncate`
  refuse to act unless the destructive-confirm flag is set.
  Refusal returns `FAILED` with this stable detail token.
- **File I/O via `ICommandRunner`.** All managers route file
  operations through the runner using `cat`, `tee`, `mv`, `cp`,
  `rm`, `chmod`, `chown` on POSIX and `Get-Content`,
  `Set-Content`, `Move-Item`, `Copy-Item`, `Remove-Item`,
  `Get-Acl`, `Set-Acl` on Windows.
