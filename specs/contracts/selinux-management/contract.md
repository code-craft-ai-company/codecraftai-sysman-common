# SELinux-Management Contract

This is the cross-OS abstract contract for the
**selinux-management** feature. Every `automojo-sysman-*` package
that ships an SELinux manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-selinux-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-selinux-management/).
It uses `getenforce`, `setenforce`, `semanage`, `getsebool`,
`setsebool`, `restorecon`, and `/etc/selinux/config` through an
`ICommandRunner` and an `IFileOperator`.

> **Linux-only feature.**
> - macOS has SIP + XProtect + Gatekeeper + AMFI — distinct
>   mandatory-access-control enforcement systems with their own
>   contracts. **The macOS implementation of this contract is OPTIONAL
>   and MAY raise `NotImplementedError` or return `FAILED` with
>   `detail="selinux not available on macOS"` for every verb.**
> - Windows has AppLocker / WDAC — distinct contracts. **The Windows
>   implementation of this contract is OPTIONAL and MAY raise
>   `NotImplementedError` or return `FAILED` with
>   `detail="selinux not available on Windows"` for every verb.**
> - Ubuntu MAY implement this contract if the `selinux-policy`
>   package is installed; otherwise the Ubuntu implementation raises
>   `NotImplementedError` or returns `FAILED` for every verb.
> - UEFI has no MAC concept — the contract does not apply.

---

## Scope

The selinux-management feature provides idempotent, auditable
control over a host's SELinux state. It covers:

- Querying and setting the global enforcement mode.
- Reading, setting, and listing SELinux booleans.
- Adding and removing named file-context entries.
- Relabelling paths (`restorecon`).
- Listing active SELinux policies.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and an `IFileOperator` (for `/etc/selinux/config`).

---

## Verbs

Every OS implementation MUST expose an `SelinuxManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_mode` | `() → SelinuxMode` | Read |
| `set_mode` | `(mode: SelinuxMode, persistent: bool) → SelinuxActionResult` | Write |
| `get_boolean` | `(name: str) → SelinuxBoolean \| None` | Read |
| `set_boolean` | `(name: str, value: bool, persistent: bool) → SelinuxActionResult` | Write |
| `list_booleans` | `() → list[SelinuxBoolean]` | Read |
| `add_file_context` | `(path: str, label: str) → SelinuxActionResult` | Write |
| `remove_file_context` | `(path: str) → SelinuxActionResult` | Write |
| `restorecon` | `(path: str, recursive: bool) → SelinuxActionResult` | Write |
| `list_policies` | `() → list[SelinuxPolicy]` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `set_mode` MUST return `SKIPPED` when
   the current mode already matches. `set_boolean` MUST return
   `SKIPPED` when the boolean is already at the requested value
   (respecting `persistent`). `add_file_context` MUST return
   `SKIPPED` when the path already has the requested label.
   `remove_file_context` MUST return `SKIPPED` when the path has
   no custom label. `restorecon` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Platform-unsupported writes.** On OSes where this feature is
   OPTIONAL (macOS / Windows / Ubuntu without policy), writes MUST
   either raise `NotImplementedError` or return `FAILED` with a
   descriptive `detail`. The OS spec MUST pick one strategy and
   document it.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MUST raise `SelinuxQueryError`
   for unexpected failures. An unknown boolean MUST cause
   `get_boolean` to return `None` rather than raise.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `SelinuxActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or SELinux is unavailable. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `SelinuxMode` (enum)

| Value | Meaning |
|-------|---------|
| `ENFORCING` | Policy is enforced. |
| `PERMISSIVE` | Policy decisions are logged but not enforced. |
| `DISABLED` | SELinux is turned off (requires reboot to change into/out of). |

### `SelinuxBoolean` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Boolean name. |
| `current` | `bool` | Current runtime value. |
| `persistent` | `bool` | Persistent (on-reboot) value. |
| `description` | `str \| None` | Human-readable description. |

### `SelinuxFileContext` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `path_pattern` | `str` | Filesystem path or regex pattern. |
| `label` | `str` | SELinux context label. |

### `SelinuxPolicy` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Policy module name. |
| `version` | `str \| None` | Policy module version. |
| `enabled` | `bool` | Whether the policy is currently loaded. |

### `SelinuxActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `SelinuxActionStatus` | Outcome category. |
| `action` | `str` | Short identifier (e.g., `"set_mode:enforcing"`). |
| `detail` | `str \| None` | Human-readable explanation (reboot advisory for disable transitions). |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `SelinuxQueryError` | A read fails for a reason other than "name unknown". |
| `SelinuxUnavailableError` | An optional-OS implementation chooses the raising strategy and SELinux is unavailable. |

### `SelinuxManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |

---

## Scope Mapping

SELinux has two natural scope concepts: the boolean name and the
file-context path pattern. The abstract verbs use both.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | SELinux (canonical) | Full support. |
| Ubuntu | SELinux via `selinux-policy` (when installed) | Extension-only; without the package every verb returns `FAILED` or raises. |
| macOS | SIP / XProtect / Gatekeeper / AMFI | Not a backing for this contract. Implementation is OPTIONAL and returns `FAILED`. |
| Windows | AppLocker / WDAC | Not a backing for this contract. Implementation is OPTIONAL and returns `FAILED`. |
| UEFI | N/A | Does not apply. |

Each OS spec that is not the RHEL reference MUST include a
Scope-Mapping section stating its availability policy and the
detection procedure for "SELinux not available".

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu. N/A on macOS / Windows for this contract. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>SelinuxManager
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

1. Accept an `ICommandRunner`, an `IFileOperator`, and a
   `SelinuxManagerConfig` in their constructor.
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
| `SelinuxManager` | `UbuntuSelinuxManager` | `MacosSelinuxManager` | `WindowsSelinuxManager` | `SelinuxManager` |
| `SelinuxManagerConfig` | `UbuntuSelinuxManagerConfig` | `MacosSelinuxManagerConfig` | `WindowsSelinuxManagerConfig` | `SelinuxManagerConfig` |
| `SelinuxActionStatus` | `UbuntuSelinuxActionStatus` | `MacosSelinuxActionStatus` | `WindowsSelinuxActionStatus` | `SelinuxActionStatus` |
| `SelinuxActionResult` | `UbuntuSelinuxActionResult` | `MacosSelinuxActionResult` | `WindowsSelinuxActionResult` | `SelinuxActionResult` |
| `SelinuxMode` | `UbuntuSelinuxMode` | `MacosSelinuxMode` | `WindowsSelinuxMode` | `SelinuxMode` |
| `SelinuxBoolean` | `UbuntuSelinuxBoolean` | `MacosSelinuxBoolean` | `WindowsSelinuxBoolean` | `SelinuxBoolean` |
| `SelinuxFileContext` | `UbuntuSelinuxFileContext` | `MacosSelinuxFileContext` | `WindowsSelinuxFileContext` | `FileContextEntry` |
| `SelinuxPolicy` | `UbuntuSelinuxPolicy` | `MacosSelinuxPolicy` | `WindowsSelinuxPolicy` | `PolicyModule` |
| `SelinuxQueryError` | `UbuntuSelinuxQueryError` | `MacosSelinuxQueryError` | `WindowsSelinuxQueryError` | `SelinuxQueryError` |
| `SelinuxUnavailableError` | `UbuntuSelinuxUnavailableError` | `MacosSelinuxUnavailableError` | `WindowsSelinuxUnavailableError` | `SelinuxUnavailableError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `SelinuxActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per applicable write verb proving
   `SKIPPED` on matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_mode` parser test for each `SelinuxMode` value.
5. One `list_booleans` parser test covering at least three
   booleans.
6. One `add_file_context` / `remove_file_context` pair.
7. One `restorecon` command-construction test with
   `recursive=True` and `recursive=False`.
8. For OPTIONAL-OS implementations: one test per verb proving the
   documented "SELinux not available" strategy (raise vs `FAILED`).
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Policy module authoring (`audit2allow`, `.te` compilation).
- User / role mapping (`semanage login`, `semanage user`).
- Port-label management (`semanage port`).
- Audit log mining for AVC denials (belongs in
  `audit-management`).
- `chcon` (transient labels) — the contract covers persistent
  `semanage fcontext` + `restorecon` flow.
- MLS / MCS category management.
- `setroubleshoot` integration.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **No cross-OS implementations exist.** This contract is
  RHEL-only by design; SELinux's policy framework (kernel LSM,
  `policycoreutils`, `semanage`, `setsebool`, `restorecon`,
  `seinfo`, `sestatus`) has no analog on macOS or Windows, and
  Ubuntu hosts only ship the policy when the operator opts into
  `selinux-policy`. Per-OS implementations on Ubuntu / macOS /
  Windows would return `FAILED` with stable detail tokens of the
  form `unsupported_on_host_os_<host>` documented in the
  contract — see the README "FAILED with stable detail token"
  convention and stable-detail-token catalog.
- **File I/O via `ICommandRunner`.** Any future Ubuntu
  implementation building on `selinux-policy` would route
  `/etc/selinux/config` and the policy file customisations
  through the runner using `cat` / `tee` rather than a separate
  `IFileOperator`, per the README "Implementation Conventions"
  file-I/O section.
