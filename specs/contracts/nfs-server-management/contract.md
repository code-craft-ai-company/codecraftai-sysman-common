# NFS-Server-Management Contract

This is the cross-OS abstract contract for the
**nfs-server-management** feature. Every `automojo-sysman-*`
package that ships an NFS server manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-nfs-server-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-nfs-server-management/).
It uses `exportfs`, `showmount`, and the content of `/etc/exports`
and `/etc/exports.d/`. This contract generalises the verb set for
macOS (`nfsd`, `/etc/exports`) and Windows (Server for NFS role
and the PowerShell `NFS` module with `New-NfsShare` /
`Remove-NfsShare`).

---

## Scope

The nfs-server-management feature provides idempotent, auditable
control over a host's NFS server exports. It covers:

- Adding and removing named exports.
- Listing active and configured exports.
- Reloading the export table after configuration changes.
- Querying the status of a single export.
- Updating per-export options.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` for `/etc/exports`
drop-in files; the established cross-OS pattern is to route file
I/O through `ICommandRunner` using OS-native file utilities. See
the README "Implementation Conventions".

---

## Verbs

Every OS implementation MUST expose an `NfsServerManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_export` | `(spec: NfsExportSpec) → NfsActionResult` | Write |
| `remove_export` | `(path: str) → NfsActionResult` | Write |
| `list_exports` | `() → list[NfsExport]` | Read |
| `reload_exports` | `() → NfsActionResult` | Write |
| `get_export_status` | `(path: str) → NfsExport \| None` | Read |
| `set_export_options` | `(path: str, options: list[str]) → NfsActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_export` MUST read current exports
   and return `SKIPPED` when the requested spec matches an
   existing export. `remove_export` MUST return `SKIPPED` when no
   export exists at `path`. `set_export_options` MUST return
   `SKIPPED` when the existing options already match. `reload_exports`
   is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Post-write reload.** `add_export`, `remove_export`, and
   `set_export_options` MUST invoke a native reload (e.g.,
   `exportfs -r` on Linux, `nfsd update` on macOS, restart of
   the `NfsService` on Windows) on `SUCCESS`. If the reload fails,
   the write MUST return `FAILED` even when the text mutation
   succeeded.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_exports` MAY raise `NfsQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list so callers can proceed without a try/except wrapper.
   `get_export_status` MUST return `None` for an unknown path
   and MAY raise on unexpected failures (or return `None` per
   the per-OS spec). See the README "Implementation Conventions"
   graceful-read pattern.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `NfsActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `NfsActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `NfsActionStatus` | Outcome category. |
| `path` | `str \| None` | The export path targeted, or `None` for `reload_exports`. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `NfsExportSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | The filesystem path to export. |
| `clients` | `list[str]` | Client address matchers (hostnames, CIDRs, wildcards, or `"*"`). |
| `options` | `list[str]` | Native export options (e.g., `"rw"`, `"sync"`, `"no_root_squash"`). |

### `NfsExport` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Exported path. |
| `clients` | `list[str]` | Clients permitted. |
| `options` | `list[str]` | Options currently in effect. |
| `active` | `bool` | Whether the export is currently advertised by the NFS daemon. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `NfsQueryError` | A read fails for a reason other than "path unknown". |

### `NfsServerManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. Default is `True` because NFS server configuration nearly always requires root. |

---

## Export-Path Mapping

The abstract `path` parameter maps to each OS's native NFS export
surface.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `/etc/exports` + `/etc/exports.d/<drop-in>.exports` | Canonical. Reload via `exportfs -r`. |
| Ubuntu | Same as RHEL (`nfs-kernel-server` package) | — |
| macOS | `/etc/exports` with Darwin-specific syntax | Reload via `nfsd update`. The macOS spec MUST document that Darwin's `/etc/exports` is not wire-compatible with Linux. |
| Windows | Server-for-NFS role via `New-NfsShare` / `Set-NfsShare` / `Remove-NfsShare` | Shares are identified by a share name, not a filesystem path. The Windows spec MUST describe the `path`→`share-name` normalisation. |
| UEFI | N/A | UEFI has no NFS server. The nfs-server-management contract does not apply. |

Each OS spec MUST include an Export-Path-Mapping section stating
its configuration location, reload mechanism, and any path-to-name
normalisation.

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
        <Os>NfsServerManager
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

1. Accept an `ICommandRunner` (and MAY accept an `IFileOperator`
   for `/etc/exports` drop-in files; the established pattern is
   to route file I/O through the runner) and an
   `NfsServerManagerConfig` in their constructor.
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
| `NfsServerManager` | `UbuntuNfsServerManager` | `MacosNfsServerManager` | `WindowsNfsServerManager` | `NfsServerManager` |
| `NfsServerManagerConfig` | `UbuntuNfsServerManagerConfig` | `MacosNfsServerManagerConfig` | `WindowsNfsServerManagerConfig` | `NfsServerManagerConfig` |
| `NfsActionStatus` | `UbuntuNfsActionStatus` | `MacosNfsActionStatus` | `WindowsNfsActionStatus` | `NfsActionStatus` |
| `NfsActionResult` | `UbuntuNfsActionResult` | `MacosNfsActionResult` | `WindowsNfsActionResult` | `NfsActionResult` |
| `NfsExportSpec` | `UbuntuNfsExportSpec` | `MacosNfsExportSpec` | `WindowsNfsExportSpec` | `ExportSpec` |
| `NfsExport` | `UbuntuNfsExport` | `MacosNfsExport` | `WindowsNfsExport` | `Export` |
| `NfsQueryError` | `UbuntuNfsQueryError` | `MacosNfsQueryError` | `WindowsNfsQueryError` | `NfsQueryError` |

The RHEL reference uses shorter names (`Export`, `ExportSpec`) for
historical reasons; new OS packages use the abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `NfsActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per applicable write verb proving `SKIPPED`
   on matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_exports` parser test covering active + configured
   mismatches.
5. One `get_export_status` test for a known and an unknown path.
6. One `reload_exports` failure-propagation test proving `FAILED`
   when the reload step fails after a successful text mutation.
7. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- NFS daemon tuning (thread counts, RPC bind ports) — RHEL
  extension covers `/etc/nfs.conf`.
- ID mapping configuration (`idmapd.conf`) — RHEL extension.
- Kerberos integration (NFSv4 sec=krb5).
- NFSv4 pseudo-root manipulation.
- Client-side mounting — lives in `filesystem-management`.
- NFS server statistics (`nfsstat`) beyond basic active/inactive
  reporting.
- Quota enforcement — lives in `filesystem-quotas`.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Per-client option scoping.** The contract carries `clients`
  and `options` as parallel lists on `NfsExportSpec`, applied
  uniformly. Ubuntu and macOS nest options inside each client via
  `<Os>NfsClientSpec(host, options)` because Linux exports natively
  scope options per client (`*(rw,sync) 10.0.0.0/24(ro,sync)`).
  macOS cannot honour per-client scoping at the line level — the
  Darwin grammar shares options across the whole line — so the
  renderer collapses to first-client options.
- **`share_name` is mandatory on Windows.** `New-NfsShare` /
  `Remove-NfsShare` address exports by share name, not by path.
  The Windows `WindowsNfsExportSpec` adds a required
  `share_name` field; per-client option fidelity falls back to
  whole-share defaults because `Grant-NfsSharePermission` per-client
  ACLs are out of scope for the pilot.
- **OS-prefixed read-shape rename.** Ubuntu uses
  `UbuntuNfsExportInfo` instead of the contract's `NfsExport` to
  match the Ubuntu manager's broader `*Info` naming convention.
  See the README "Concrete-implementation naming overrides"
  convention.
- **File I/O via `ICommandRunner`.** `/etc/exports` reads, writes,
  and drop-in directory edits route through the runner using
  `cat` / `tee` on Ubuntu and macOS rather than a separate
  `IFileOperator`. macOS does not consult `/etc/exports.d/` —
  the manager edits `/etc/exports` exclusively. See the README
  "Implementation Conventions" file-I/O section.
- **Reload semantics diverge.** Ubuntu and macOS issue
  `exportfs -ra` for full server-wide re-export. Windows has no
  per-share reload cmdlet — `reload_exports` invokes
  `Restart-Service NfsService` for contract parity, even though
  `New-NfsShare` and `Remove-NfsShare` apply synchronously.
