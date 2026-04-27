# User-Group-Management Contract

This is the cross-OS abstract contract for the **user-group-management**
feature. Every `automojo-sysman-*` package that ships a user and
group manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-user-group-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-user-group-management/).
It uses `useradd`, `userdel`, `usermod`, `groupadd`, `groupdel`,
`gpasswd`, `passwd`, `chage`, and `getent` through an
`ICommandRunner`. This contract generalises the verb set for OSes
whose native user surface is `dscl` / `sysadminctl` (macOS) or
`net user` / `New-LocalUser` (Windows).

---

## Scope

The user-group-management feature provides idempotent, auditable
control over local users, local groups, and their relationship. It
covers:

- Creating, deleting, and modifying a user.
- Querying a user's record.
- Listing all local users.
- Setting a user's password.
- Locking and unlocking a user account.
- Creating, deleting, and querying a group.
- Listing all local groups.
- Adding and removing a user's group membership.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `UserGroupManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs. Implementations MAY split the surface into
two cooperating classes (`<Os>UserManager` and `<Os>GroupManager`)
as the RHEL reference does.

### User verbs

| Verb | Signature | Kind |
|------|-----------|------|
| `create_user` | `(spec: UserSpec) → UserGroupActionResult` | Write |
| `delete_user` | `(name: str, remove_home: bool) → UserGroupActionResult` | Write |
| `modify_user` | `(name: str, changes: UserModSpec) → UserGroupActionResult` | Write |
| `get_user` | `(name: str) → UserInfo \| None` | Read |
| `list_users` | `() → list[UserInfo]` | Read |
| `set_password` | `(name: str, password: str) → UserGroupActionResult` | Write |
| `lock_account` | `(name: str) → UserGroupActionResult` | Write |
| `unlock_account` | `(name: str) → UserGroupActionResult` | Write |

### Group verbs

| Verb | Signature | Kind |
|------|-----------|------|
| `create_group` | `(spec: GroupSpec) → UserGroupActionResult` | Write |
| `delete_group` | `(name: str) → UserGroupActionResult` | Write |
| `get_group` | `(name: str) → GroupInfo \| None` | Read |
| `list_groups` | `() → list[GroupInfo]` | Read |
| `add_to_group` | `(user: str, group: str) → UserGroupActionResult` | Write |
| `remove_from_group` | `(user: str, group: str) → UserGroupActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_user` / `create_group` MUST
   return `SKIPPED` when the user / group already exists (regardless
   of whether other spec fields match — `modify_user` is the
   mutation verb). `delete_user` / `delete_group` MUST return
   `SKIPPED` when the user / group does not exist. `add_to_group`
   / `remove_from_group` MUST return `SKIPPED` when the membership
   is already in the requested state. `lock_account` /
   `unlock_account` MUST return `SKIPPED` when the account is
   already in the requested state.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Typed preconditions.** `modify_user`, `add_to_group`,
   `remove_from_group`, `set_password`, `lock_account`, and
   `unlock_account` MUST raise `UserNotFoundError` when the user
   does not exist. `add_to_group` and `remove_from_group` MUST
   raise `GroupNotFoundError` when the group does not exist.
5. **Password handling.** `set_password` MUST accept the password
   as a parameter and forward it to the runner via `stdin` (or the
   OS's secure equivalent). The password MUST NOT appear in the
   result's `command` field; only the invocation argv is stored.
6. **Password validation.** Implementations MUST accept passwords
   as opaque strings; the contract does not define complexity
   policy, which is an OS / PAM / LSA concern.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_users`, `list_groups`, and unexpected
   `get_user` / `get_group` failures MUST raise `UserGroupQueryError`.
   A missing user / group MUST cause `get_user` / `get_group` to
   return `None`.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `UserGroupActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and failed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `UserSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Username. |
| `uid` | `int \| None` | Numeric UID or equivalent (RID / DS GeneratedUID). |
| `home` | `str \| None` | Home directory path. |
| `shell` | `str \| None` | Login shell. |
| `primary_group` | `str \| None` | Primary group name. |
| `comment` | `str \| None` | GECOS / description. |
| `system_account` | `bool` | `True` for a system-allocated UID. |

### `UserModSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `shell` | `str \| None` | New shell. |
| `home` | `str \| None` | New home directory. |
| `move_home` | `bool` | `True` to move existing home contents. |
| `primary_group` | `str \| None` | New primary group. |
| `comment` | `str \| None` | New GECOS / description. |
| `uid` | `int \| None` | New UID. |

### `UserInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Username. |
| `uid` | `int` | UID / RID. |
| `gid` | `int` | Primary GID where applicable. |
| `comment` | `str` | GECOS / description. |
| `home` | `str` | Home directory. |
| `shell` | `str` | Login shell. |
| `locked` | `bool` | Whether the account is currently locked. |

### `GroupSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Group name. |
| `gid` | `int \| None` | Numeric GID or equivalent. |
| `system_group` | `bool` | `True` for a system-allocated GID. |

### `GroupInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Group name. |
| `gid` | `int` | GID. |
| `members` | `list[str]` | Usernames that are members of the group. |

### `UserGroupActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `UserGroupActionStatus` | Outcome category. |
| `target` | `str` | The user or group targeted. |
| `kind` | `str` | Either `"user"` or `"group"`. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed (never contains a plaintext password). |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `UserNotFoundError` | `modify_user`, `add_to_group`, `remove_from_group`, `set_password`, `lock_account`, or `unlock_account` targets a non-existent user. |
| `GroupNotFoundError` | `add_to_group` or `remove_from_group` targets a non-existent group. |
| `UserGroupQueryError` | `list_users`, `list_groups`, or an unexpected `get_*` failure. |

### `UserGroupManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

---

## User-vs-Group Mapping

The abstract verbs operate on each OS's local user / group
directories.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `/etc/passwd`, `/etc/group`, `/etc/shadow` — tools: `useradd`, `usermod`, `userdel`, `groupadd`, `groupdel`, `gpasswd`, `passwd`, `chage`, `getent` | Canonical. |
| Ubuntu | Same as RHEL | — |
| macOS | Directory Services — tools: `dscl .`, `sysadminctl`, `dseditgroup` | UIDs / GIDs are Directory Services integers; `dscl` reads/writes the local node. |
| Windows | Local SAM database — tools: `net user`, `net localgroup`, PowerShell `New-LocalUser`, `Add-LocalGroupMember`, `Get-LocalUser` | `uid` maps to the RID component of the user SID. |
| UEFI | N/A | UEFI has no user concept. The user-group-management contract does not apply. |

Each OS spec MUST include a User-vs-Group-Mapping section stating
how it resolves names to native identifiers and how `uid` / `gid`
are represented for OSes that do not use POSIX integers.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>UserGroupManager
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

1. Accept an `ICommandRunner` and a `UserGroupManagerConfig` in
   their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.
5. Never log the plaintext password supplied to `set_password`,
   regardless of aspect configuration. Implementations MUST
   document how they prevent the persistence aspect from capturing
   the password (typically: pass via `stdin`, not argv).

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `UserGroupManager` | `UbuntuUserGroupManager` | `MacosUserGroupManager` | `WindowsUserGroupManager` | `UserManager` + `GroupManager` (split) |
| `UserGroupManagerConfig` | `UbuntuUserGroupManagerConfig` | `MacosUserGroupManagerConfig` | `WindowsUserGroupManagerConfig` | `UserGroupManagerConfig` |
| `UserGroupActionStatus` | `UbuntuUserGroupActionStatus` | `MacosUserGroupActionStatus` | `WindowsUserGroupActionStatus` | `ActionStatus` |
| `UserGroupActionResult` | `UbuntuUserGroupActionResult` | `MacosUserGroupActionResult` | `WindowsUserGroupActionResult` | `UserActionResult` + `GroupActionResult` (split) |
| `UserSpec` | `UbuntuUserSpec` | `MacosUserSpec` | `WindowsUserSpec` | `UserSpec` |
| `UserModSpec` | `UbuntuUserModSpec` | `MacosUserModSpec` | `WindowsUserModSpec` | `UserModSpec` |
| `UserInfo` | `UbuntuUserInfo` | `MacosUserInfo` | `WindowsUserInfo` | `UserInfo` |
| `GroupSpec` | `UbuntuGroupSpec` | `MacosGroupSpec` | `WindowsGroupSpec` | `GroupSpec` |
| `GroupInfo` | `UbuntuGroupInfo` | `MacosGroupInfo` | `WindowsGroupInfo` | `GroupInfo` |
| `UserNotFoundError` | `UbuntuUserNotFoundError` | `MacosUserNotFoundError` | `WindowsUserNotFoundError` | `UserNotFoundError` |
| `GroupNotFoundError` | `UbuntuGroupNotFoundError` | `MacosGroupNotFoundError` | `WindowsGroupNotFoundError` | `GroupNotFoundError` |
| `UserGroupQueryError` | `UbuntuUserGroupQueryError` | `MacosUserGroupQueryError` | `WindowsUserGroupQueryError` | `UserQueryError` |

Implementations MAY split the single `UserGroupManager` into two
cooperating classes as the RHEL reference does; the verb names and
return types MUST match this contract regardless of which class
they live on.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `UserGroupActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result and MUST NOT log
  passwords (see §Execution Model).

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One `UserNotFoundError` test per user-write that requires
   existence.
4. One `GroupNotFoundError` test per group-targeting verb.
5. One `get_user` / `get_group` test for known and unknown targets.
6. One `list_users` / `list_groups` parser test covering
   representative output.
7. One `set_password` test proving the password is passed via
   `stdin` and does NOT appear in `UserGroupActionResult.command`.
8. One lock / unlock round-trip test per OS demonstrating the
   native lock-state detection.
9. One dry-run test per write verb proving the runner is not
   invoked.
10. One elevation test proving writes pass `elevated=True` and
    reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Directory-service users / groups (LDAP, Active Directory, Open
  Directory beyond the local node).
- SSH authorized_keys management (the RHEL reference exposes
  `add_ssh_key` / `remove_ssh_key` as an OS-specific extension).
- Password expiry / aging policy (RHEL exposes `set_password_age`
  and `expire_password` as OS-specific extensions).
- Sudoers / privilege configuration.
- Home-directory skeleton customisation beyond what `create_user`
  naturally provides.
- Full keychain / credential-store integration.
- Admin / Standard user role assignment (macOS / Windows).
- User-profile migration between devices.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is structural.** Ubuntu wraps the
  shadow-utils suite (`useradd` / `userdel` / `usermod` /
  `groupadd` / `groupdel` / `gpasswd` / `passwd` / `chpasswd`)
  plus `getent` for reads. macOS wraps Directory Services —
  `sysadminctl` for user lifecycle / password reset, `dscl`
  for property updates and enumeration, `dseditgroup` for group
  membership. Windows wraps the PowerShell `*-LocalUser` /
  `*-LocalGroup` cmdlets against the local SAM, not Active
  Directory.
- **Password handling diverges.** Ubuntu pipes plaintext to
  `chpasswd` via stdin (no plaintext in argv). macOS includes
  the password as a `sysadminctl` argv argument because the
  tool requires it that way; the per-OS spec documents the
  argv-leak risk and recommends `noecho` runners. Windows pipes
  plaintext into a PowerShell here-string that converts to a
  `SecureString` in-process and feeds `New-LocalUser -Password`.
- **`create_user` does not create the home profile on Windows.**
  `New-LocalUser` registers the SAM principal but Windows lazily
  materialises the profile on first interactive logon. The
  per-OS read-shape carries `home: str | None` as informational
  and resolves the actual profile path through a registry
  lookup at `HKLM:\SOFTWARE\Microsoft\Windows
  NT\CurrentVersion\ProfileList\<SID>`.
- **Read-shape returns `None`, not raises.** `get_user(name)`
  returns `None` when the principal is absent; `list_users`
  returns an empty list. Per the README "Reads degrade
  gracefully" convention.
- **Windows `elevation_blocked: bool`.** `New-LocalUser` /
  `Set-LocalUser` / `Remove-LocalUser` / `Add-LocalGroupMember`
  writes surface the structured Windows elevation extension when
  the calling process lacks an elevated token. See the README
  "Implementation Conventions" elevation-blocked entry.
