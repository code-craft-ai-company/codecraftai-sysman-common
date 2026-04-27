# Filesystem-Quotas Contract

This is the cross-OS abstract contract for the
**filesystem-quotas** feature. Every `automojo-sysman-*` package
that ships a filesystem-quotas manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-filesystem-quotas/`](../../../../../automojo-sysman-linux-redhat/specs/3-filesystem-quotas/).
It wraps `quotaon`, `quotaoff`, `quotacheck`, `setquota`,
`repquota`, `edquota`, and `xfs_quota` through an
`ICommandRunner`, auto-dispatching between XFS and ext-family
tooling. This contract generalises the verb set for OSes whose
quota surface is the POSIX-style `quota` family (Linux, macOS
BSD quota), or the Windows quota families (`fsutil quota` for
per-volume quotas; `dirquota` / FSRM for per-directory quotas).

---

## Scope

The filesystem-quotas feature provides idempotent, auditable
control over per-user, per-group, and (where supported)
per-project space / inode quotas on a filesystem mountpoint. It
covers:

- Enabling and disabling quota enforcement on a mountpoint.
- Setting soft and hard space / inode limits for users and
  groups.
- Querying current usage and limits for a user or group.
- Listing all quota entries on a mountpoint.
- Querying the overall quota-enforcement status for a mountpoint.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS
  requires elevation to read quota metadata.

The feature does NOT set mount options (`usrquota`, `grpquota`)
— that is `filesystem-management`. It assumes quotas are
available on the filesystem and surfaces a clean failure when
they are not.

---

## Verbs

Every OS implementation MUST expose a `FilesystemQuotasManager`
class (the OS-prefixed variant — see §Naming) whose public
surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `enable_quotas` | `(mountpoint: str, targets: list[QuotaTarget]) → QuotaActionResult` | Write |
| `disable_quotas` | `(mountpoint: str, targets: list[QuotaTarget]) → QuotaActionResult` | Write |
| `set_user_quota` | `(mountpoint: str, user: str, limits: QuotaLimits) → QuotaActionResult` | Write |
| `set_group_quota` | `(mountpoint: str, group: str, limits: QuotaLimits) → QuotaActionResult` | Write |
| `get_user_quota` | `(mountpoint: str, user: str) → QuotaEntry \| None` | Read |
| `get_group_quota` | `(mountpoint: str, group: str) → QuotaEntry \| None` | Read |
| `list_quotas` | `(mountpoint: str, target: QuotaTarget) → list[QuotaEntry]` | Read |
| `get_quota_status` | `(mountpoint: str) → QuotaEnforcement` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `enable_quotas` MUST return `SKIPPED`
   when enforcement is already active for every requested
   target. `disable_quotas` MUST return `SKIPPED` when
   enforcement is already inactive. `set_user_quota` and
   `set_group_quota` MUST return `SKIPPED` when the current
   limits already match the requested values.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Mount validation.** Writes MUST raise
   `QuotaFilesystemNotMountedError` when the supplied
   `mountpoint` is not currently mounted before invoking the
   quota-mutation command.
5. **Unsupported target.** Verbs that address a target kind the
   filesystem does not support (e.g., project quotas on ext4
   without `prjquota`, user quotas on a filesystem mounted
   without `usrquota`) MUST return `FAILED` with a descriptive
   `detail` rather than invoking the command.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` unless
   the OS requires it to access quota metadata.
2. **Typed errors.** Reads MAY raise `QuotaQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list / synthetic record so callers can proceed without a
   try/except wrapper. `get_user_quota` and `get_group_quota`
   MUST return `None` for an unknown principal on that
   mountpoint rather than raise. See the README "Implementation
   Conventions" graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `QuotaActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `QuotaTarget` (enum)

| Value | Meaning |
|-------|---------|
| `USER` | Per-user quotas. |
| `GROUP` | Per-group quotas. |
| `PROJECT` | Per-project quotas (XFS / Windows FSRM). |

### `QuotaLimits` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `block_soft` | `int` | Soft block limit (bytes or native block unit per OS spec). |
| `block_hard` | `int` | Hard block limit. |
| `inode_soft` | `int` | Soft inode / file-count limit. `0` when the OS does not enforce inode quotas. |
| `inode_hard` | `int` | Hard inode / file-count limit. |

### `QuotaEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `mountpoint` | `str` | Filesystem mountpoint. |
| `target` | `QuotaTarget` | Target kind. |
| `name` | `str` | Username, group name, or project name. |
| `block_used` | `int` | Current block usage. |
| `block_soft` | `int` | Soft block limit. |
| `block_hard` | `int` | Hard block limit. |
| `inode_used` | `int` | Current inode usage. |
| `inode_soft` | `int` | Soft inode limit. |
| `inode_hard` | `int` | Hard inode limit. |
| `grace_blocks` | `str \| None` | Native grace-period string for block overage. |
| `grace_inodes` | `str \| None` | Native grace-period string for inode overage. |

### `QuotaEnforcement` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `mountpoint` | `str` | Filesystem mountpoint. |
| `fstype` | `str` | Detected filesystem type (`"ext4"`, `"xfs"`, `"apfs"`, `"ntfs"`, ...). |
| `user_enforced` | `bool` | Whether user-quota enforcement is active. |
| `group_enforced` | `bool` | Whether group-quota enforcement is active. |
| `project_enforced` | `bool` | Whether project-quota enforcement is active. `False` on OSes / filesystems that do not support it. |

### `QuotaActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `QuotaActionStatus` | Outcome category. |
| `mountpoint` | `str \| None` | Mountpoint acted upon. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `QuotaQueryError` | A read fails unexpectedly. |
| `QuotaFilesystemNotMountedError` | A write is invoked against a path that is not a mountpoint. |
| `QuotaUnsupportedOperationError` | A verb is unsupported by the target filesystem (e.g., `quotacheck` on XFS). |

### `FilesystemQuotasManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Filesystem Mapping

The abstract verbs map to each OS's native quota tooling:

| OS | Native tooling | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `quota` family (`quotaon`, `setquota`, `repquota`) for ext*; `xfs_quota` for XFS | Canonical. Dispatch is auto-detected per mountpoint fstype. |
| Ubuntu | Same as RHEL. | — |
| macOS | BSD `quota` family (`quotaon`, `edquota`, `repquota`) on HFS+. APFS quota surface is more limited; the OS spec MUST document which verbs return `FAILED` on APFS. | — |
| Windows | `fsutil quota` for per-volume user quotas on NTFS; `dirquota` for per-directory quotas via FSRM. `QuotaTarget.GROUP` is unsupported by NTFS per-volume quotas and MUST return `FAILED`. | — |
| UEFI | N/A | UEFI has no quota subsystem. The contract does not apply. |

Each OS spec MUST include a Filesystem-Mapping section
enumerating which `(fstype, QuotaTarget)` combinations are
supported.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`, except where the OS requires it. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>FilesystemQuotasManager
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

1. Accept an `ICommandRunner` and a
   `FilesystemQuotasManagerConfig` in their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `FilesystemQuotasManager` | `UbuntuFilesystemQuotasManager` | `MacosFilesystemQuotasManager` | `WindowsFilesystemQuotasManager` | `FilesystemQuotasManager` |
| `FilesystemQuotasManagerConfig` | `UbuntuFilesystemQuotasManagerConfig` | `MacosFilesystemQuotasManagerConfig` | `WindowsFilesystemQuotasManagerConfig` | `FilesystemQuotasConfig` |
| `QuotaActionStatus` | `UbuntuQuotaActionStatus` | `MacosQuotaActionStatus` | `WindowsQuotaActionStatus` | `QuotaActionStatus` |
| `QuotaActionResult` | `UbuntuQuotaActionResult` | `MacosQuotaActionResult` | `WindowsQuotaActionResult` | `QuotaActionResult` |
| `QuotaTarget` | `UbuntuQuotaTarget` | `MacosQuotaTarget` | `WindowsQuotaTarget` | `QuotaTarget` |
| `QuotaLimits` | `UbuntuQuotaLimits` | `MacosQuotaLimits` | `WindowsQuotaLimits` | `QuotaLimits` |
| `QuotaEntry` | `UbuntuQuotaEntry` | `MacosQuotaEntry` | `WindowsQuotaEntry` | `QuotaEntry` |
| `QuotaEnforcement` | `UbuntuQuotaEnforcement` | `MacosQuotaEnforcement` | `WindowsQuotaEnforcement` | `QuotaEnforcement` |
| `QuotaQueryError` | `UbuntuQuotaQueryError` | `MacosQuotaQueryError` | `WindowsQuotaQueryError` | `QuotaQueryError` |
| `QuotaFilesystemNotMountedError` | `UbuntuQuotaFilesystemNotMountedError` | `MacosQuotaFilesystemNotMountedError` | `WindowsQuotaFilesystemNotMountedError` | `QuotaFilesystemNotMountedError` |
| `QuotaUnsupportedOperationError` | `UbuntuQuotaUnsupportedOperationError` | `MacosQuotaUnsupportedOperationError` | `WindowsQuotaUnsupportedOperationError` | `QuotaUnsupportedOperationError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `QuotaActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb, per supported
   filesystem family.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_user_quota` / `get_group_quota` test covering a
   known principal and an unknown principal (returns `None`).
5. One `list_quotas` parser test covering representative output.
6. One `get_quota_status` test covering both enforced and
   unenforced mountpoints.
7. One `QuotaFilesystemNotMountedError` test proving the error
   is raised before the runner is invoked.
8. One `QuotaUnsupportedOperationError` test proving the error
   is raised for an unsupported combination (e.g., project
   quotas on a non-supporting filesystem).
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Mount-option management (`usrquota` / `grpquota` / `prjquota`)
  — covered by `filesystem-management`.
- XFS project definition (`/etc/projects`, `/etc/projid`) beyond
  setting quotas on a pre-declared project.
- Windows FSRM policy templates and quota thresholds with
  notification actions.
- Quota reporting exports / consolidated dashboards.
- `quotacheck` on filesystems that support it (treated as a
  maintenance extension, not a base verb).
- Grace-period configuration (only surfaced read-only in
  `QuotaEntry`).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **macOS APFS returns `apfs_no_quota_support`.** Apple's APFS
  exposes no native user/group quota infrastructure; the macOS
  manager returns `FAILED` with the stable detail token for every
  write verb. See the README stable-token catalog.
- **Backend divergence.** Ubuntu wraps `quotaon` /
  `setquota` / `repquota` against `usrquota` / `grpquota` /
  `prjquota` mount options; macOS is a no-op layer; Windows
  wraps FSRM (`Set-FsrmQuota` / `Get-FsrmQuota`).
- **File I/O via `ICommandRunner`.** `quotatab` / `aquota.user`
  / `aquota.group` reads route through the runner.
