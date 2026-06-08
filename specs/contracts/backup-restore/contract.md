# Backup-Restore Contract

This is the cross-OS abstract contract for the **backup-restore**
feature. Every `codecraftai-sysman-*` package that ships a backup
manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-backup-restore/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-backup-restore/).
It wraps `tar`, `rsync`, `sha256sum`, and `openssl enc` through
an `ICommandRunner` (and MAY use an `IFileOperator` where
available; the established pattern is to route file I/O through
`ICommandRunner` — see the README "Implementation Conventions"
section), with a repository
layout under `/var/lib/ccai/backups/`. This contract
generalises the verb set for OSes whose backup surface is the
Linux archive family (`tar`, `rsync`, `restic`), macOS Time
Machine (`tmutil`) supplemented by `rsync`, or Windows
`wbadmin` / `Restore-Computer` / PowerShell backup modules.

**Important:** backup-and-restore is the feature area with the
largest semantic divergence across OSes. Time Machine on macOS
and `wbadmin` on Windows impose their own repository layouts,
scheduling assumptions, and restore semantics that do not
round-trip to the Linux tar-plus-manifest model. This contract
therefore locks **verb names and result shapes** but explicitly
acknowledges that individual verbs MAY return `FAILED` with a
descriptive `detail` on OSes whose native tooling does not map
to that verb. OS specs MUST document each deviation.

---

## Scope

The backup-restore feature provides idempotent, auditable
management of file-tree backup jobs and the archives they
produce. It covers:

- Defining named backup jobs from a declarative spec (source,
  destination, schedule, retention, encryption).
- Deleting a previously-defined backup job.
- Running a backup job on demand.
- Listing the archives currently managed by the host.
- Verifying an archive against its recorded checksum / integrity
  metadata.
- Restoring from a previously-taken backup into a target path.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS
  requires elevation to inspect the backup store.

The feature does NOT perform block-level snapshots, LVM snapshot
rotation, or database-consistent dumps. Those are out of scope
for the base contract.

---

## Verbs

Every OS implementation MUST expose a `BackupRestoreManager`
class (the OS-prefixed variant — see §Naming) whose public
surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `create_backup_job` | `(spec: BackupJobSpec) → BackupActionResult` | Write |
| `delete_backup_job` | `(job_id: str) → BackupActionResult` | Write |
| `run_backup_now` | `(job_id: str) → BackupActionResult` | Write |
| `list_backups` | `(job_id: str \| None) → list[BackupEntry]` | Read |
| `restore_from_backup` | `(backup_id: str, target: str, restrict_paths: list[str] \| None) → BackupActionResult` | Write |
| `verify_backup` | `(backup_id: str) → BackupVerifyResult` | Read |
| `get_job_status` | `(job_id: str) → BackupJobStatus` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_backup_job` MUST return
   `SKIPPED` when an equivalent job with the same `job_id` and
   normalised spec already exists. `delete_backup_job` MUST return
   `SKIPPED` when the job does not exist. `run_backup_now` is
   operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or mutating the backup store.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Verify-before-restore.** `restore_from_backup` MUST invoke
   the same verification path as `verify_backup` before any
   extraction-style command is dispatched. If verification fails,
   the restore MUST NOT extract and MUST return `FAILED`.
5. **Credential safety.** Where a backup spec carries encryption
   material, the secret bytes MUST be delivered via runner
   `stdin` and never appear on argv. The `command` field in any
   result MUST be sanitised.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, except where the OS's backup store is access-
   controlled (e.g., `wbadmin` catalog reads on Windows).
2. **Typed errors.** `list_backups`, `get_job_status`, and
   `verify_backup` MAY raise `BackupQueryError` for unexpected
   failures or, per the per-OS spec, return an empty list / synthetic
   `BackupJobStatus` record so callers can proceed without a
   try/except wrapper. An unknown `job_id` or `backup_id` MUST raise
   `BackupNotFoundError`. See the README "Implementation Conventions"
   graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `BackupActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `BackupKind` (enum)

| Value | Meaning |
|-------|---------|
| `ARCHIVE` | A tar-style single-archive backup. |
| `MIRROR` | An rsync-style sibling-of-source mirror. |
| `TIME_MACHINE` | macOS Time Machine snapshot. |
| `SYSTEM_IMAGE` | Windows `wbadmin` / system-image backup. |

### `BackupJobSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `str` | Caller-chosen deterministic identifier. |
| `kind` | `BackupKind` | Backup kind. |
| `sources` | `list[str]` | Paths to back up. |
| `destination` | `str` | Repository root / volume / destination path. |
| `schedule` | `str \| None` | Schedule expression (cron on Linux; `com.apple.backupd` cadence on macOS; Windows Task Scheduler trigger). `None` for on-demand-only jobs. |
| `retention_days` | `int \| None` | Keep archives newer than this many days. |
| `keep_last_n` | `int \| None` | Keep the N most-recent archives. |
| `encryption_enabled` | `bool` | When `True`, archive bytes are encrypted. |
| `excludes` | `list[str]` | Exclude patterns. |

### `BackupEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `backup_id` | `str` | Unique identifier for the individual archive. |
| `job_id` | `str` | Owning job identifier. |
| `created_at` | `str` | ISO-8601 UTC timestamp. |
| `size_bytes` | `int` | Size on disk. |
| `encryption_enabled` | `bool` | Whether the archive is encrypted. |
| `checksum` | `str \| None` | Recorded integrity digest (hex SHA-256 or native equivalent). |
| `path` | `str \| None` | On-disk path when applicable. |

### `BackupJobStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `str` | Job identifier. |
| `kind` | `BackupKind` | Backup kind. |
| `enabled` | `bool` | Whether the job is active. |
| `last_run_at` | `str \| None` | ISO-8601 timestamp of the most recent run. |
| `last_run_status` | `BackupActionStatus \| None` | Outcome of the most recent run. |
| `next_run_at` | `str \| None` | Next scheduled run, when known. |

### `BackupVerifyResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `backup_id` | `str` | Archive identifier. |
| `ok` | `bool` | Whether verification passed. |
| `recorded_checksum` | `str \| None` | Checksum recorded at backup time. |
| `computed_checksum` | `str \| None` | Checksum computed during verification. |
| `detail` | `str \| None` | Human-readable detail on failure. |

### `BackupActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `BackupActionStatus` | Outcome category. |
| `job_id` | `str \| None` | Job identifier. |
| `backup_id` | `str \| None` | Archive identifier when applicable. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | Sanitised argv. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `BackupQueryError` | A read fails unexpectedly. |
| `BackupNotFoundError` | An unknown `job_id` or `backup_id` is supplied. |
| `BackupVerifyError` | Verification logic encounters a structural error (distinct from a mismatched checksum, which returns `ok=False`). |

### `BackupRestoreManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |
| `repository_root` | `str` | `""` | Default repository root; interpretation is OS-specific. |

---

## Backup-Kind Mapping

The abstract `BackupKind` maps to each OS's native tooling:

| OS | Native concepts | Notes |
|----|-----------------|-------|
| Red Hat Enterprise Linux | `ARCHIVE` → `tar` + manifest; `MIRROR` → `rsync --link-dest`; `TIME_MACHINE` / `SYSTEM_IMAGE` → `FAILED` with `detail`. | Canonical. |
| Ubuntu | Same as RHEL. | — |
| macOS | `TIME_MACHINE` → `tmutil startbackup` plus `tmutil listbackups`; `ARCHIVE` → `tar`; `MIRROR` → `rsync`. `SYSTEM_IMAGE` → `FAILED`. | — |
| Windows | `SYSTEM_IMAGE` → `wbadmin start backup`; `ARCHIVE` → `Compress-Archive` plus a manifest or PowerShell `Backup-*` cmdlets; `MIRROR` → `Robocopy /MIR`; `TIME_MACHINE` → `FAILED`. | — |
| UEFI | N/A | UEFI has no persistent filesystem backup concept. The contract does not apply. |

Each OS spec MUST include a Backup-Kind Mapping section
enumerating which kinds it supports, and documenting the
`FAILED` detail string returned for unsupported kinds.

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
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>BackupRestoreManager
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

1. Accept an `ICommandRunner` and a
   `BackupRestoreManagerConfig` in their constructor.
   Implementations whose repository layout requires filesystem
   bookkeeping MAY also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `BackupRestoreManager` | `UbuntuBackupRestoreManager` | `MacosBackupRestoreManager` | `WindowsBackupRestoreManager` | `BackupRestoreManager` |
| `BackupRestoreManagerConfig` | `UbuntuBackupRestoreManagerConfig` | `MacosBackupRestoreManagerConfig` | `WindowsBackupRestoreManagerConfig` | `BackupRestoreManagerConfig` |
| `BackupActionStatus` | `UbuntuBackupActionStatus` | `MacosBackupActionStatus` | `WindowsBackupActionStatus` | `BackupActionStatus` |
| `BackupActionResult` | `UbuntuBackupActionResult` | `MacosBackupActionResult` | `WindowsBackupActionResult` | `BackupActionResult` |
| `BackupKind` | `UbuntuBackupKind` | `MacosBackupKind` | `WindowsBackupKind` | `BackupKind` |
| `BackupJobSpec` | `UbuntuBackupJobSpec` | `MacosBackupJobSpec` | `WindowsBackupJobSpec` | `BackupJobSpec` |
| `BackupEntry` | `UbuntuBackupEntry` | `MacosBackupEntry` | `WindowsBackupEntry` | `BackupEntry` |
| `BackupJobStatus` | `UbuntuBackupJobStatus` | `MacosBackupJobStatus` | `WindowsBackupJobStatus` | `BackupJobStatus` |
| `BackupVerifyResult` | `UbuntuBackupVerifyResult` | `MacosBackupVerifyResult` | `WindowsBackupVerifyResult` | `BackupVerifyResult` |
| `BackupQueryError` | `UbuntuBackupQueryError` | `MacosBackupQueryError` | `WindowsBackupQueryError` | `BackupQueryError` |
| `BackupNotFoundError` | `UbuntuBackupNotFoundError` | `MacosBackupNotFoundError` | `WindowsBackupNotFoundError` | `BackupNotFoundError` |
| `BackupVerifyError` | `UbuntuBackupVerifyError` | `MacosBackupVerifyError` | `WindowsBackupVerifyError` | `BackupVerifyError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `BackupActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result. Persistence
  aspects MUST treat the `stdin` payload (encryption keys,
  passphrases) as sensitive and MUST NOT log it.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state (where applicable).
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_backups` parser test.
5. One `verify_backup` test proving correct checksum
   computation and comparison.
6. One `restore_from_backup` test proving verification occurs
   before extraction and that a verification failure prevents the
   extract command.
7. One credential-safety test proving encryption material does
   not appear on argv.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.
9. One unsupported-kind test proving `FAILED` with a descriptive
   `detail` for any `BackupKind` the OS does not support.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Block-level / LVM / Btrfs / APFS snapshots.
- Database-consistent dumps (PostgreSQL, MSSQL, etc.).
- Cross-host backup replication.
- Cloud-storage destinations beyond a mounted local-looking path.
- Deduplicating archive backends (`restic`, `borg`, `kopia`) as
  first-class `BackupKind` values.
- Bare-metal recovery ISO generation.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Per-OS `BackupKind` enums.** `UbuntuBackupKind`,
  `MacosBackupKind`, and `WindowsBackupKind` enumerate disjoint
  value sets (rsync/restic/duplicity vs Time Machine/rsync vs
  wbadmin/Restore-Computer/PowerShell). The contract's abstract
  `BackupKind` is the union; per-OS callers consume the OS-prefixed
  enum directly.
- **No native daemon on Ubuntu.** Ubuntu has no system-supplied
  backup daemon; the operator picks the tool. The Ubuntu spec
  treats `BackupKind` as a tool selector and defaults to `rsync`.
  macOS and Windows implementations bind to `tmutil` and
  `wbadmin` respectively.
- **File I/O via `ICommandRunner`.** Repository bookkeeping (catalog
  files, lock files, sentinel markers) routes through the runner
  rather than `IFileOperator`.
