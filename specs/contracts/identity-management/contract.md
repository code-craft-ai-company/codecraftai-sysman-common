# Identity-Management Contract

This is the cross-OS abstract contract for the
**identity-management** feature. Every `automojo-sysman-*`
package that ships an identity manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-identity-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-identity-management/).
It wraps `realm`, `adcli`, `sssctl`, `kinit`, and direct edits to
`/etc/sssd/` and `/etc/krb5.conf` through an `ICommandRunner`.
This contract generalises the verb set for OSes whose identity
surface is FreeIPA / SSSD / realmd (Linux), macOS Directory
Services (`dsconfigad` for AD, `dscl` for Open Directory), or
Windows Active Directory join (`Add-Computer`, RSAT
`ActiveDirectory` module).

Credential material (passwords, one-time passwords, keytabs)
MUST flow through runner `stdin` and never on argv. The
`command` field in any result MUST be sanitised.

---

## Scope

The identity-management feature provides idempotent, auditable
control over a host's enrollment in an identity realm / directory
service. It covers:

- Joining a realm / domain with supplied credentials.
- Leaving a realm.
- Querying the current realm-join status.
- Listing the realms the host is currently joined to.
- Synchronising users / groups from the directory into the local
  name resolver.
- Resolving a user or group name against the joined directory.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature does NOT manage local user accounts — that is
`user-group-management`. It does NOT configure PAM — that is
`authentication-management`. It does NOT manage CA trust
anchors — that is `certificate-trust-management`.

---

## Verbs

Every OS implementation MUST expose an `IdentityManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `join_realm` | `(spec: RealmJoinSpec, credential: Credential) → IdentityActionResult` | Write |
| `leave_realm` | `(realm: str) → IdentityActionResult` | Write |
| `get_realm_status` | `(realm: str) → RealmStatus \| None` | Read |
| `list_joined_realms` | `() → list[RealmMembership]` | Read |
| `sync_users` | `(realm: str \| None) → IdentityActionResult` | Write |
| `resolve_user` | `(username: str) → IdentityPrincipal \| None` | Read |
| `resolve_group` | `(groupname: str) → IdentityPrincipal \| None` | Read |
| `discover_realm` | `(domain: str) → RealmDiscovery` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `join_realm` MUST return `SKIPPED`
   when the host is already joined to the requested realm with
   matching spec parameters. `leave_realm` MUST return `SKIPPED`
   when the host is not joined to the realm. `sync_users` is
   operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner. Dry-run mode MUST
   block all calls that would contact a remote KDC or domain
   controller.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Credential safety.** Every password / OTP byte MUST flow
   on `stdin`. The `command` field MUST be sanitised.
5. **Credential required.** `join_realm` MUST raise
   `IdentityCredentialError` when no credential is supplied.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` unless
   the OS requires it to read the directory configuration.
2. **Typed errors.** `list_joined_realms` and `discover_realm`
   MAY raise `IdentityQueryError` for unexpected failures or,
   per the per-OS spec, return an empty list / synthetic
   `RealmStatus(joined=False, ...)` record so callers can
   proceed without a try/except wrapper. (`get_realm_status`
   returning `RealmStatus(joined=False, ...)` is the canonical
   reference example; see the README "Implementation
   Conventions" graceful-read pattern.) `get_realm_status`,
   `resolve_user`, and `resolve_group` MUST return `None` for
   unknown inputs rather than raise.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `IdentityActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `RealmKind` (enum)

| Value | Meaning |
|-------|---------|
| `ACTIVE_DIRECTORY` | Microsoft Active Directory. |
| `FREEIPA` | FreeIPA / Red Hat Identity Management. |
| `OPEN_DIRECTORY` | macOS Open Directory. |
| `KERBEROS_ONLY` | Plain Kerberos realm without directory integration. |

### `RealmJoinSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `realm` | `str` | Realm / domain name. |
| `kind` | `RealmKind` | Realm kind. |
| `ou` | `str \| None` | Organizational unit for computer-account placement (AD only). |
| `computer_name` | `str \| None` | Override computer name used during join. |
| `one_time_password` | `bool` | When `True`, the credential carries a one-time password rather than user credentials. |
| `extra_options` | `dict[str, str]` | Native extras (e.g., `--user-principal`, `--os-name`). |

### `RealmDiscovery` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `domain` | `str` | Queried domain. |
| `realm` | `str \| None` | Canonical realm name. |
| `kind` | `RealmKind \| None` | Detected realm kind. |
| `servers` | `list[str]` | Discovered domain controllers / servers. |
| `raw` | `str` | Verbatim discovery output. |

### `RealmStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `realm` | `str` | Realm name. |
| `joined` | `bool` | Whether the host is currently joined. |
| `computer_account` | `str \| None` | Computer account / machine account name, when joined. |
| `detail` | `str \| None` | Human-readable status detail. |

### `RealmMembership` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `realm` | `str` | Realm name. |
| `kind` | `RealmKind` | Realm kind. |
| `configured` | `bool` | Whether the host is configured for the realm. |
| `domain_controllers` | `list[str]` | Known domain controllers / servers. |

### `IdentityPrincipal` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Principal name as supplied. |
| `resolved_name` | `str \| None` | Canonical resolved name (e.g., `user@REALM`). |
| `principal_kind` | `str` | `"user"` or `"group"`. |
| `uid` | `int \| None` | Numeric uid / gid when applicable. |
| `gid` | `int \| None` | Primary group id for users. |
| `source` | `str \| None` | Native source (`"sss"`, `"ad"`, `"opendirectory"`, ...). |

### `IdentityActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `IdentityActionStatus` | Outcome category. |
| `realm` | `str \| None` | Realm acted upon. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | Sanitised argv. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `IdentityQueryError` | A read fails unexpectedly. |
| `IdentityCredentialError` | A verb requires a credential and none was supplied. |
| `IdentityRealmNotFoundError` | A realm-addressing verb is given an unknown realm. |

### `IdentityManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Realm-Kind Mapping

The abstract `RealmKind` maps to each OS's native tooling:

| OS | Supported kinds | Native tooling |
|----|-----------------|----------------|
| Red Hat Enterprise Linux | `FREEIPA`, `ACTIVE_DIRECTORY`, `KERBEROS_ONLY` | `realm discover`, `realm join`, `realm leave`, `adcli`, `sssctl`, `kinit` |
| Ubuntu | Same as RHEL. | — |
| macOS | `ACTIVE_DIRECTORY`, `OPEN_DIRECTORY` | `dsconfigad` for AD bind; `dscl` for Open Directory. `FREEIPA` and `KERBEROS_ONLY` MUST return `FAILED` with a descriptive `detail`. |
| Windows | `ACTIVE_DIRECTORY` | `Add-Computer`, `Remove-Computer`, RSAT `ActiveDirectory`. `FREEIPA`, `OPEN_DIRECTORY`, and `KERBEROS_ONLY` MUST return `FAILED`. |
| UEFI | N/A | UEFI has no identity surface. The contract does not apply. |

Each OS spec MUST include a Realm-Kind Mapping section.

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
                │  supplies credential objects for passwords / OTPs
                ▼
        <Os>IdentityManager
                │
                │  .run(argv, elevated=…, stdin=<secret>, capture_output=True)
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

1. Accept an `ICommandRunner` and an `IdentityManagerConfig` in
   their constructor.
2. Never construct their own subprocess.
3. Never place credential bytes on argv.
4. Not hold state across calls beyond the config.
5. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `IdentityManager` | `UbuntuIdentityManager` | `MacosIdentityManager` | `WindowsIdentityManager` | `IdentityManager` |
| `IdentityManagerConfig` | `UbuntuIdentityManagerConfig` | `MacosIdentityManagerConfig` | `WindowsIdentityManagerConfig` | `IdentityManagerConfig` |
| `IdentityActionStatus` | `UbuntuIdentityActionStatus` | `MacosIdentityActionStatus` | `WindowsIdentityActionStatus` | `IdentityActionStatus` |
| `IdentityActionResult` | `UbuntuIdentityActionResult` | `MacosIdentityActionResult` | `WindowsIdentityActionResult` | `IdentityActionResult` |
| `RealmKind` | `UbuntuRealmKind` | `MacosRealmKind` | `WindowsRealmKind` | `RealmKind` |
| `RealmJoinSpec` | `UbuntuRealmJoinSpec` | `MacosRealmJoinSpec` | `WindowsRealmJoinSpec` | `RealmJoinSpec` |
| `RealmDiscovery` | `UbuntuRealmDiscovery` | `MacosRealmDiscovery` | `WindowsRealmDiscovery` | `RealmDiscovery` |
| `RealmStatus` | `UbuntuRealmStatus` | `MacosRealmStatus` | `WindowsRealmStatus` | `RealmStatus` |
| `RealmMembership` | `UbuntuRealmMembership` | `MacosRealmMembership` | `WindowsRealmMembership` | `RealmMembership` |
| `IdentityPrincipal` | `UbuntuIdentityPrincipal` | `MacosIdentityPrincipal` | `WindowsIdentityPrincipal` | `IdentityPrincipal` |
| `IdentityQueryError` | `UbuntuIdentityQueryError` | `MacosIdentityQueryError` | `WindowsIdentityQueryError` | `IdentityQueryError` |
| `IdentityCredentialError` | `UbuntuIdentityCredentialError` | `MacosIdentityCredentialError` | `WindowsIdentityCredentialError` | `IdentityCredentialError` |
| `IdentityRealmNotFoundError` | `UbuntuIdentityRealmNotFoundError` | `MacosIdentityRealmNotFoundError` | `WindowsIdentityRealmNotFoundError` | `IdentityRealmNotFoundError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `IdentityActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`. Retry aspects MUST NOT re-send credential bytes
  beyond the runner's documented retry-redelivery contract.
- Persistence aspects MUST NOT mutate the result. Persistence
  aspects MUST NOT log `stdin` bytes.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` when
   the host is already in the requested membership state.
3. One dry-run test per write verb proving no remote contact is
   made (no `realm` / `Add-Computer` / `dsconfigad` command is
   dispatched).
4. One `list_joined_realms` parser test covering representative
   output.
5. One `resolve_user` / `resolve_group` test covering a known
   principal and an unknown principal (returns `None`).
6. One `discover_realm` parser test.
7. One credential-safety test proving passwords never appear in
   the recorded argv.
8. One `IdentityCredentialError` test proving the right
   exception fires when a credential is required but absent.
9. One unsupported-kind test proving `FAILED` with a
   descriptive `detail` for any `RealmKind` the OS does not
   support.
10. One elevation test proving writes pass `elevated=True` and
    reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- PAM configuration (see `authentication-management`).
- Local account creation (see `user-group-management`).
- SSHD Kerberos / GSSAPI configuration (see
  `ssh-server-configuration`).
- Certificate-based machine enrollment beyond the basic
  password-driven `join_realm`.
- Group Policy / MDM policy synchronisation.
- Cross-forest / trust topology management.
- Per-user Kerberos ticket lifecycle (`kinit` / `klist` /
  `kdestroy`) — may be added as an extension.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu wraps `realmd` /
  `sssd` / `adcli`; macOS wraps `dsconfigad` /
  `dsconfigldap` / `kinit`; Windows wraps `Add-Computer` /
  `Test-ComputerSecureChannel` and the Active Directory
  PowerShell module. Field shapes diverge.
- **`requires_reboot: bool` on Windows realm-join.** Windows
  domain-join requires a reboot to take effect; the
  `WindowsIdentityActionResult` carries
  `requires_reboot: bool = False`. See the README reboot-
  signaling convention.
- **`get_realm_status` returns a synthetic record.** When the
  host is not joined or the realm-discovery tool fails, the
  manager returns `RealmStatus(joined=False, ...)` rather than
  raising. This is the canonical reference for the README
  graceful-read pattern.
