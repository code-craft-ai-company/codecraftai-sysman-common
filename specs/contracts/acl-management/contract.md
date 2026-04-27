# Acl-Management Contract

This is the cross-OS abstract contract for the **acl-management**
feature. Every `automojo-sysman-*` package that ships an ACL
manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-acl-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-acl-management/).
It wraps POSIX ACL tooling (`setfacl`, `getfacl`), extended
attribute tooling (`chattr`, `lsattr`), and file capabilities
(`setcap`, `getcap`) through an `ICommandRunner`. This contract
generalises the verb set for OSes whose ACL surface is the POSIX
ACL family (Linux), macOS extended ACLs (`chmod +a` / native
ACEs), or the Windows NTFS ACL model (`icacls`, PowerShell
`Get-Acl` / `Set-Acl`).

---

## Scope

The acl-management feature provides idempotent, auditable
control over per-path access-control metadata beyond the classic
owner / group / other permission bits. It covers:

- Reading the full ACL attached to a filesystem path.
- Replacing the full ACL at a path from a declarative
  specification.
- Adding a single ACE (access-control entry) for a named
  principal with a named set of rights.
- Removing all ACEs belonging to a named principal.
- Clearing the entire non-default ACL on a path.
- Copying an ACL from one path to another.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS requires
  elevation to read protected directories.

The feature is executed exclusively through an `ICommandRunner`.
No direct `subprocess`, no direct filesystem writes, no direct
library calls into OS ACL APIs.

---

## Verbs

Every OS implementation MUST expose an `AclManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_acl` | `(path: str) → AclSet` | Read |
| `set_acl` | `(path: str, acl_spec: AclSet, recursive: bool) → AclActionResult` | Write |
| `add_ace` | `(path: str, principal: AclPrincipal, rights: list[str], recursive: bool) → AclActionResult` | Write |
| `remove_ace` | `(path: str, principal: AclPrincipal, recursive: bool) → AclActionResult` | Write |
| `clear_acl` | `(path: str, recursive: bool) → AclActionResult` | Write |
| `copy_acl` | `(src: str, dst: str, recursive: bool) → AclActionResult` | Write |
| `list_acls` | `(root: str, recursive: bool) → list[AclSet]` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** Every write MUST call `get_acl` against
   the target path and compare the current ACL to the requested
   end state. If the current state already matches, the method
   MUST return `AclActionResult` with status `SKIPPED` and MUST
   NOT invoke the underlying ACL-mutation command.
2. **Dry-run short-circuit.** If the manager is configured with
   `dry_run=True`, writes MUST NOT invoke the runner and MUST
   return `AclActionResult` with status `DRY_RUN`. The `command`
   field MAY carry the argv that would have been executed.
3. **Error surface.** Non-zero exit codes from the runner MUST
   return `AclActionResult` with status `FAILED` populated with
   `exit_code`, `stdout`, `stderr`, and `command`. Writes do NOT
   raise for failed commands.
4. **Recursive semantics.** When `recursive=True`, the
   implementation MUST use the tool's native recursion flag where
   available (`setfacl -R`, PowerShell `Set-Acl` with an enumerated
   child set). Implementations MUST NOT emulate recursion by
   shelling a per-child command unless the underlying tool
   provides no recursion option and the OS spec documents the
   emulation.
5. **Path existence.** Writes MUST raise `AclPathNotFoundError`
   when the target path does not exist before invoking the
   runner.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner unless the OS specifically requires it (e.g., Windows
   reading ACLs of system-owned directories). The OS spec MUST
   document any elevated-read exceptions.
2. **Typed errors.** `get_acl` and `list_acls` MAY raise
   `AclQueryError` for unexpected failures or, per the per-OS spec,
   return a synthetic empty `AclSet` and surface the error through
   logging. A missing path MUST raise `AclPathNotFoundError`. See
   the README "Implementation Conventions" section on graceful
   read-failure for the established cross-OS pattern.
3. **Pure parsing.** All parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `AclActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `AclPrincipalKind` (enum)

| Value | Meaning |
|-------|---------|
| `USER` | A named user principal. |
| `GROUP` | A named group principal. |
| `MASK` | The POSIX effective-rights mask (Linux/macOS only). |
| `OTHER` | The POSIX "other" class. |
| `EVERYONE` | Windows `Everyone` / macOS `everyone`. |
| `SYSTEM` | Windows `NT AUTHORITY\SYSTEM`. |

### `AclPrincipal` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `AclPrincipalKind` | Principal category. |
| `name` | `str \| None` | Principal name (user / group). `None` for `MASK`, `OTHER`, `EVERYONE`, `SYSTEM`. |
| `sid` | `str \| None` | Native security identifier (SID on Windows) when available. |

### `AclEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `principal` | `AclPrincipal` | Who the ACE applies to. |
| `rights` | `list[str]` | Normalised rights tokens (e.g., `"read"`, `"write"`, `"execute"`, `"full_control"`, `"delete_child"`). |
| `allow` | `bool` | `True` for allow-ACE; `False` for deny-ACE. |
| `inherited` | `bool` | `True` when the ACE is inherited from a parent. |
| `is_default` | `bool` | `True` for POSIX default ACEs (directory-only inheritance). |

### `AclSet` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Path the ACL applies to. |
| `owner` | `str \| None` | Owner principal name. |
| `group` | `str \| None` | Primary group principal name. |
| `entries` | `list[AclEntry]` | Non-default entries. |
| `default_entries` | `list[AclEntry]` | POSIX default entries; empty list on OSes without default ACLs. |
| `inheritance_enabled` | `bool` | Whether inheritance is enabled from the parent. |

### `AclActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `AclActionStatus` | Outcome category. |
| `path` | `str` | Target path. |
| `detail` | `str \| None` | Free-form detail. Typically the principal name or rights spec acted upon. |
| `exit_code` | `int \| None` | Runner exit code for `SUCCESS` and `FAILED`. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `AclQueryError` | A read fails for a reason other than "path not found". |
| `AclPathNotFoundError` | A write or read is invoked against a path that does not exist. |

### `AclManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Principal Mapping

The abstract `AclPrincipal` maps to each OS's native principal
model:

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | POSIX user / group name resolved via NSS | Canonical. `MASK`, `OTHER` use native POSIX semantics. `EVERYONE` / `SYSTEM` MUST return `FAILED` with a descriptive `detail`. |
| Ubuntu | Same as RHEL | — |
| macOS | Native user / group (Directory Services), extended ACLs via `chmod +a` | `EVERYONE` maps to `everyone`. `SYSTEM` is unsupported; MUST return `FAILED`. Default-ACE equivalents are not first-class on HFS+/APFS and MUST be returned as `default_entries=[]`. |
| Windows | SID resolved via LSA, with `DOMAIN\name` and well-known SIDs | `MASK` and `OTHER` are unsupported; MUST return `FAILED`. `EVERYONE` maps to `S-1-1-0`; `SYSTEM` maps to `S-1-5-18`. |
| UEFI | N/A | UEFI has no POSIX / NT ACL model. The acl-management contract does not apply. |

Each OS spec MUST include a Principal-Mapping section stating
which `AclPrincipalKind` values are supported and how unsupported
principals surface failures.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`, except where the OS explicitly requires elevation to read protected paths. |
| Config `elevated=False` | Never pass `elevated=True`, regardless of verb. |
| OS elevation mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. The command runner handles the mechanism. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>AclManager
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

1. Accept an `ICommandRunner` and an `AclManagerConfig` in their
   constructor.
2. Never construct their own runner or subprocess.
3. Never hold state across method calls beyond the runner and the
   config. ACL state is re-queried per write.
4. Be safe to invoke under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `AclManager` | `UbuntuAclManager` | `MacosAclManager` | `WindowsAclManager` | `AclManager` |
| `AclManagerConfig` | `UbuntuAclManagerConfig` | `MacosAclManagerConfig` | `WindowsAclManagerConfig` | `AclManagerConfig` |
| `AclActionStatus` | `UbuntuAclActionStatus` | `MacosAclActionStatus` | `WindowsAclActionStatus` | `AclActionStatus` |
| `AclActionResult` | `UbuntuAclActionResult` | `MacosAclActionResult` | `WindowsAclActionResult` | `AclActionResult` |
| `AclPrincipal` | `UbuntuAclPrincipal` | `MacosAclPrincipal` | `WindowsAclPrincipal` | `AclPrincipal` |
| `AclPrincipalKind` | `UbuntuAclPrincipalKind` | `MacosAclPrincipalKind` | `WindowsAclPrincipalKind` | `AclPrincipalKind` |
| `AclEntry` | `UbuntuAclEntry` | `MacosAclEntry` | `WindowsAclEntry` | `AclEntry` |
| `AclSet` | `UbuntuAclSet` | `MacosAclSet` | `WindowsAclSet` | `AclSet` |
| `AclQueryError` | `UbuntuAclQueryError` | `MacosAclQueryError` | `WindowsAclQueryError` | `AclQueryError` |
| `AclPathNotFoundError` | `UbuntuAclPathNotFoundError` | `MacosAclPathNotFoundError` | `WindowsAclPathNotFoundError` | `AclPathNotFoundError` |

The RHEL package retains unprefixed names for historical reasons;
new packages use the OS-prefixed form.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `AclActionResult` sequence when driven by a
  real runner with `PersistenceAspect`, `RetryAspect`, and
  `TimeoutAspect` attached, modulo runner-level timing and
  retries.
- Retry aspects that translate transient non-zero exits into
  successes are permitted to change `status` from `FAILED` to
  `SUCCESS`; all other field semantics are unchanged.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb proving correct
   argv assembly for the native tool.
2. One idempotency test per write verb proving `SKIPPED` is
   returned when the desired ACL is already in effect.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_acl` parser test covering an ACL with multiple
   principals, allow and (where supported) deny ACEs, inherited
   entries, and (where supported) default entries.
5. One `list_acls` test covering a recursive enumeration against
   a small directory tree output.
6. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.
7. One path-not-found test proving `AclPathNotFoundError` is
   raised before the runner is invoked.
8. One principal-mapping test proving unsupported
   `AclPrincipalKind` values surface a clean `FAILED` result on
   that OS.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Classic POSIX mode bits (`chmod`, `chown`) — covered by
  `filesystem-management`.
- Extended filesystem attributes / flags (`chattr`, `lsattr`,
  macOS `chflags`, Windows file attributes like `Archive` /
  `Hidden`).
- File capabilities (`setcap`, `getcap`) — may be exposed by an
  OS-specific extension.
- NTFS auditing ACEs (SACL) — writes to the audit ACL are
  distinct from the DACL covered here.
- Bulk import / export of ACL specifications across hosts.
- SELinux labels and contexts — covered by a separate MAC
  feature.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract; they are documented here so contract
readers know what to expect when reading per-OS code.

- **Read-shape vs write-shape split.** Ubuntu and macOS implementations
  expose `<Os>AclInfo` (the per-path snapshot) and a separate
  `<Os>AceInfo` / `<Os>AceSpec` pair instead of a single `AclEntry`.
  The split distinguishes parsed read shapes from caller-supplied
  write shapes; the contract's combined `AclEntry` is treated as the
  abstract union.
- **`AclPrincipal` collapsed.** macOS has no SID concept; Ubuntu's
  POSIX backend likewise carries the principal name directly. Both
  implementations carry the principal name on `<Os>AceInfo` /
  `<Os>AceSpec` rather than wrapping it in a separate
  `AclPrincipal` dataclass. Windows retains a SID-aware shape.
- **`recursive: bool` parameter dropped on per-OS verbs.** The
  contract carries `recursive: bool` on every write verb; per-OS
  implementations drop it pending a future
  `acl-management-recursive` follow-up that ships recursive walks
  with their own progress / partial-failure shape.
- **File I/O via `ICommandRunner`.** All implementations route
  `getfacl`/`setfacl`/`icacls`/`chmod +a` through the runner; no
  `IFileOperator` is involved.
