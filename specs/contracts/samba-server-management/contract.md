# Samba-Server-Management Contract

This is the cross-OS abstract contract for the
**samba-server-management** feature. Every `automojo-sysman-*`
package that ships a Samba / SMB-server manager MUST honor this
contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-samba-server-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-samba-server-management/).
It manages `/etc/samba/smb.conf`, validates via `testparm`, and
drives `smbpasswd` / `pdbedit` / `net ads` / `wbinfo` through an
`ICommandRunner`. This contract generalises the verb set for
macOS (Samba `smbd` built-in, plus Sharing preferences) and
Windows (native SMB via `New-SmbShare` / `Remove-SmbShare` /
`Get-SmbShare`).

---

## Scope

The samba-server-management feature provides idempotent,
auditable control over a host's SMB-share configuration. It
covers:

- Adding, removing, and listing shares.
- Querying a single share.
- Setting share-level permissions.
- Reloading the SMB configuration.
- Creating and removing SMB users (where applicable).
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and an `IFileOperator` (for `smb.conf` on Samba-backed OSes).

> **Credential handling.** SMB user passphrases MUST be passed via
> the runner's stdin channel, never via argv. The
> `ShareActionResult.command` field MUST be sanitised to redact
> any credential material that the underlying tool accepts on the
> command line.

---

## Verbs

Every OS implementation MUST expose a `SambaServerManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_share` | `(spec: ShareSpec) → ShareActionResult` | Write |
| `remove_share` | `(name: str) → ShareActionResult` | Write |
| `list_shares` | `() → list[ShareInfo]` | Read |
| `get_share` | `(name: str) → ShareInfo \| None` | Read |
| `set_share_permissions` | `(name: str, acl: list[ShareAclEntry]) → ShareActionResult` | Write |
| `reload_config` | `() → ShareActionResult` | Write |
| `add_samba_user` | `(name: str, password: str) → ShareActionResult` | Write |
| `remove_samba_user` | `(name: str) → ShareActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_share` MUST return `SKIPPED` when a
   share with the same `name` and identical rendered spec exists.
   `remove_share` MUST return `SKIPPED` when no such share exists.
   `set_share_permissions` MUST return `SKIPPED` when the existing
   ACL already matches (order-insensitive).
   `add_samba_user` / `remove_samba_user` MUST return `SKIPPED`
   when the user is already in the requested state.
   `reload_config` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Config validation.** Samba-backed OSes MUST validate
   `smb.conf` (e.g., `testparm -s`) before reloading and MUST
   return `FAILED` with the validator's stderr on error.
5. **Credential sanitisation.** `command` MUST NOT contain the
   password on `add_samba_user`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_shares` MUST raise `ShareQueryError`
   for unexpected failures. `get_share` MUST return `None` for an
   unknown name and raise only on unexpected failures.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `ShareActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ShareSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | The share name as clients see it. |
| `path` | `str` | Filesystem path exposed by the share. |
| `read_only` | `bool` | Whether the share is read-only. |
| `guest_ok` | `bool` | Whether guest access is permitted. |
| `valid_users` | `list[str]` | Users allowed access (empty means all). |
| `comment` | `str \| None` | Free-form description. |
| `extra_options` | `dict[str, str]` | OS-specific extra key/value options. |

### `ShareInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Share name. |
| `path` | `str` | Filesystem path. |
| `read_only` | `bool` | Read-only flag. |
| `guest_ok` | `bool` | Guest-access flag. |
| `valid_users` | `list[str]` | Configured valid users. |
| `comment` | `str \| None` | Description. |

### `ShareAclEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `principal` | `str` | User or group name. |
| `permission` | `str` | Native permission token (`"full"`, `"change"`, `"read"`). |
| `deny` | `bool` | Whether this is an explicit-deny entry. |

### `ShareActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ShareActionStatus` | Outcome category. |
| `share_name` | `str \| None` | The share targeted, or `None` for `reload_config`. |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed, sanitised. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ShareQueryError` | A read fails for a reason other than "share unknown". |

### `SambaServerManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |
| `smb_conf_path` | `str` | `"/etc/samba/smb.conf"` | Path to the primary Samba configuration file on Samba-backed OSes. Ignored on Windows. |

---

## Share-Name Mapping

The abstract `name` parameter is the SMB share name as clients
see it.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `[<name>]` section in `/etc/samba/smb.conf` | Canonical. |
| Ubuntu | Same as RHEL (Samba package) | — |
| macOS | `smbd` built-in + `sharing -a` / `dscl` | macOS shares are managed via `sharing`; the macOS spec MUST document the name → underlying registration. |
| Windows | `New-SmbShare -Name <name>` | Native SMB share namespace. |
| UEFI | N/A | UEFI has no SMB concept. The samba-server-management contract does not apply. |

Each OS spec MUST include a Share-Name-Mapping section stating
its configuration location, validation command, and any naming
restrictions.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |
| Credential transport | All SMB passwords MUST flow on stdin, never on argv. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>SambaServerManager
                │
                │  .run(argv, elevated=…, stdin=password, capture_output=True)
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
   `SambaServerManagerConfig` in their constructor.
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
| `SambaServerManager` | `UbuntuSambaServerManager` | `MacosSambaServerManager` | `WindowsSambaServerManager` | `SambaServerManager` |
| `SambaServerManagerConfig` | `UbuntuSambaServerManagerConfig` | `MacosSambaServerManagerConfig` | `WindowsSambaServerManagerConfig` | `SambaServerManagerConfig` |
| `ShareActionStatus` | `UbuntuShareActionStatus` | `MacosShareActionStatus` | `WindowsShareActionStatus` | `SambaActionStatus` |
| `ShareActionResult` | `UbuntuShareActionResult` | `MacosShareActionResult` | `WindowsShareActionResult` | `SambaActionResult` |
| `ShareSpec` | `UbuntuShareSpec` | `MacosShareSpec` | `WindowsShareSpec` | `ShareDefinition` |
| `ShareInfo` | `UbuntuShareInfo` | `MacosShareInfo` | `WindowsShareInfo` | `ShareEntry` |
| `ShareAclEntry` | `UbuntuShareAclEntry` | `MacosShareAclEntry` | `WindowsShareAclEntry` | `ShareAclEntry` |
| `ShareQueryError` | `UbuntuShareQueryError` | `MacosShareQueryError` | `WindowsShareQueryError` | `SambaQueryError` |

The RHEL reference uses Samba-flavoured names; new OS packages
use the abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ShareActionResult` sequence when driven by a
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
4. One `list_shares` parser test covering multiple shares.
5. One `get_share` test for a known and an unknown share.
6. One `set_share_permissions` test proving order-insensitive
   idempotency on the ACL.
7. One config-validation failure test proving `reload_config`
   returns `FAILED` when the validator fails.
8. One credential-sanitisation test proving `command` does not
   contain the password for `add_samba_user`.
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- AD-domain join (`net ads join`) — RHEL extension.
- Winbind / nsswitch integration.
- Printer sharing and `smb.conf [printers]`.
- Server-role switching (standalone / member / AD DC).
- VFS module wiring.
- NTLMv1 / signing / encryption fine-grained tuning (treated as
  `extra_options`).
- Cluster / CTDB configuration.
- Windows Distributed File System (DFS) namespaces.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is structural.** Ubuntu wraps the full
  Samba toolchain (`smbcontrol`, `smbpasswd`, `pdbedit`,
  `/etc/samba/smb.conf`); macOS wraps the `sharing` CLI plus
  `launchctl kickstart` of `com.apple.smbd` and the `dscl .
  /SharePoints/...` namespace; Windows wraps the
  `New-SmbShare` / `Get-SmbShare` / `Grant-SmbShareAccess`
  PowerShell module against the SMB server stack natively built
  into Windows. The verb surface is identical; the underlying
  data models are not.
- **No `smb.conf` on macOS or Windows.** The Ubuntu manager
  parses and writes `smb.conf` sections; macOS persists shares
  via `sharing` and shares' state is in
  `dscl . /SharePoints/`; Windows persists in the registry via
  the SMB cmdlets. Configuration-file reads only exist on Ubuntu.
- **User database is Ubuntu-only.** `add_samba_user` /
  `remove_samba_user` route to `smbpasswd` / `pdbedit` on Ubuntu;
  macOS and Windows defer to the OS-native principal stores
  (Open Directory and Active Directory respectively) and the
  per-OS specs document the analog as a `FAILED` /
  `parameter_not_supported` token where appropriate.
- **File I/O via `ICommandRunner`.** `/etc/samba/smb.conf` reads
  and writes route through the runner using `cat` / `tee` rather
  than a separate `IFileOperator`. See the README "Implementation
  Conventions" file-I/O section.
- **Windows `elevation_blocked: bool`.** `New-SmbShare` /
  `Remove-SmbShare` / `Grant-SmbShareAccess` writes surface the
  structured Windows elevation extension when the calling
  process lacks an elevated token. See the README "Implementation
  Conventions" elevation-blocked entry.
