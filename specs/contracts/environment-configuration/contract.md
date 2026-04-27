# Environment-Configuration Contract

This is the cross-OS abstract contract for the **environment-configuration**
feature. Every `automojo-sysman-*` package that ships an environment
configurator MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-environment-configuration/`](../../../../../automojo-sysman-linux-redhat/specs/3-environment-configuration/).
It writes `/etc/profile.d/*.sh`, `/etc/environment`, and per-user rc
files. The original RHEL design used an `IFileOperator`; cross-OS
implementations route file I/O through `ICommandRunner` using
`cat` / `tee` on POSIX and `Get-Content` / `Set-Content` /
`[Environment]::SetEnvironmentVariable` on Windows. See the README
"Implementation Conventions" file-I/O convention. This contract
generalises that shape for OSes whose environment surface includes
launchd plists, the Windows registry, and the user-session profile
files.

---

## Scope

The environment-configuration feature provides idempotent, auditable
management of named environment variables at two scopes: **system**
(applies to every login) and **user** (applies to a specific user's
sessions). It covers:

- Setting, unsetting, and querying a system environment variable.
- Setting, unsetting, and querying a user environment variable.
- Listing all variables at a given scope.
- Dry-run-aware writes.
- Elevation for system-scope writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
(and MAY use an `IFileOperator` where available; the established
pattern is to route file I/O through `ICommandRunner`). No direct
filesystem writes occur inside the module.

---

## Verbs

Every OS implementation MUST expose an `EnvironmentConfigurator`
class (the OS-prefixed variant — see §Naming) whose public surface
is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `set_system_env` | `(name: str, value: str) → EnvActionResult` | Write |
| `unset_system_env` | `(name: str) → EnvActionResult` | Write |
| `get_system_env` | `(name: str) → EnvValue \| None` | Read |
| `list_system_env` | `() → dict[str, str]` | Read |
| `set_user_env` | `(user: str, name: str, value: str) → EnvActionResult` | Write |
| `unset_user_env` | `(user: str, name: str) → EnvActionResult` | Write |
| `get_user_env` | `(user: str, name: str) → EnvValue \| None` | Read |
| `list_user_env` | `(user: str) → dict[str, str]` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** Before any set or unset, the configurator
   MUST read the current persisted value and compare to the desired
   state. Matching state MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the file operator for writes.
3. **Error surface.** Failures MUST return `FAILED` with `message`
   populated. Writes do NOT raise for routine I/O.
4. **User validation.** User-scope writes MUST return `FAILED` with
   an explanatory `message` when the named user does not exist.
   User-scope reads MUST raise `EnvConfigError` for a non-existent
   user.
5. **Line-preserving rewrites.** Where the OS persists environment
   as text files, writes MUST preserve non-managed lines (comments,
   unrelated variables) across a read-modify-write cycle.
6. **Empty-file cleanup.** Where the OS uses drop-in files (e.g.,
   `/etc/profile.d/*.sh`), unsetting the last managed variable in a
   drop-in MAY delete the drop-in; this is OS-spec-documented
   behavior.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   file operator.
2. **Missing-source handling.** `list_system_env` and `list_user_env`
   MUST return an empty dict when the source is absent. `get_*` MUST
   return `None` for an absent variable within an existing source.
3. **Pure parsing.** All parsing runs in pure Python / library code.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `EnvActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The write ran and succeeded. |
| `FAILED` | The write ran and failed, or a precondition was not met. |
| `SKIPPED` | The idempotency guard short-circuited the write. |
| `DRY_RUN` | Dry-run mode short-circuited the write. |

### `EnvScope` (enum)

| Value | Meaning |
|-------|---------|
| `SYSTEM` | Applies to all users (or all services, depending on OS). |
| `USER` | Applies to a specific user's sessions. |

### `EnvValue` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | The variable name. |
| `value` | `str` | The variable value. |
| `scope` | `EnvScope` | Whether the value comes from system or user scope. |
| `source` | `str \| None` | The backing source (path or registry key) the value came from. |

### `EnvActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `EnvActionStatus` | Outcome category. |
| `scope` | `EnvScope` | The scope the action targeted. |
| `name` | `str` | The variable name. |
| `value` | `str \| None` | New value for set; `None` for unset. |
| `path` | `str \| None` | The source that was (or would have been) modified. |
| `user` | `str \| None` | The target user for user-scope actions. |
| `message` | `str \| None` | Human-readable detail for `FAILED` or `SKIPPED`. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. Optional / additive — see the README "Implementation Conventions" `command` field. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `EnvConfigError` | A read operation cannot complete (e.g., unknown user, unreadable source). |

### `EnvironmentConfiguratorConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no file operations with side effects occur. |
| `elevated` | `bool` | `False` | When `True`, system-scope writes pass `elevated=True`. |

---

## Scope Mapping

The abstract `EnvScope` maps to the native scope concept of each OS:

| OS | SYSTEM | USER | Notes |
|----|--------|------|-------|
| Red Hat Enterprise Linux | `/etc/environment` and `/etc/profile.d/*.sh` | `~user/.bashrc` / `~user/.profile` | Canonical. |
| Ubuntu | `/etc/environment` and `/etc/profile.d/*.sh` | `~user/.bashrc` / `~user/.profile` | Same as RHEL, but implementations MAY additionally support `pam_env.d` drop-ins. |
| macOS | `/etc/launchd.conf` (deprecated on recent versions) plus a managed `/Library/LaunchDaemons/<label>.plist` that sets `EnvironmentVariables`; implementations SHOULD prefer the plist path. | `~user/Library/LaunchAgents/<label>.plist` that sets `EnvironmentVariables`, or the user's shell rc file. | Interactive-shell variables and launchd environment are two distinct surfaces; the OS spec MUST state which is primary. |
| Windows | `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment` | `HKCU\Environment` (default) or the per-user SID hive under `HKU\<SID>\Environment` when setting for another user | `setx` / `Set-ItemProperty` is the canonical write path. A broadcast of `WM_SETTINGCHANGE` MAY be emitted after writes but is not required. |
| UEFI | N/A | N/A | UEFI has no per-login environment concept. The environment-configuration contract does not apply. |

Each OS spec MUST include a Scope-Mapping section stating which
source file(s) or registry key(s) it uses and how it resolves a
username to that user's backing source.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, system-scope write | Pass `elevated=True` to the file operator. |
| Config `elevated=True`, user-scope write for the current user | Elevation is OS-dependent; on Unix-likes, not required; on Windows, writes to `HKCU` do not require elevation. The OS spec MUST state the policy. |
| Config `elevated=True`, user-scope write for another user | Pass `elevated=True` to the file operator. |
| Any read | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects file operator, config
                ▼
        <Os>EnvironmentConfigurator
                │
                │  read_text / write_text / delete via IFileOperator
                ▼
          IFileOperator
                │
        ┌───────┴────────┐
        ▼                ▼
  LocalFileOperator    SSHFileOperator
        │                │
        └────────┬───────┘
                 │  aspects compose here
                 ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `IFileOperator` and an `EnvironmentConfiguratorConfig`
   in their constructor. Implementations whose native surface
   requires a CLI (`setx`, `defaults`) MAY also accept an
   `ICommandRunner`.
2. Never construct their own subprocess or file handle outside the
   injected abstractions.
3. Not hold state across calls.
4. Be safe under any aspect composition on the file operator.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `EnvironmentConfigurator` | `UbuntuEnvironmentConfigurator` | `MacosEnvironmentConfigurator` | `WindowsEnvironmentConfigurator` | `EnvironmentConfigurator` |
| `EnvironmentConfiguratorConfig` | `UbuntuEnvironmentConfiguratorConfig` | `MacosEnvironmentConfiguratorConfig` | `WindowsEnvironmentConfiguratorConfig` | `EnvironmentConfiguratorConfig` |
| `EnvActionStatus` | `UbuntuEnvActionStatus` | `MacosEnvActionStatus` | `WindowsEnvActionStatus` | `EnvActionStatus` |
| `EnvScope` | `UbuntuEnvScope` | `MacosEnvScope` | `WindowsEnvScope` | `EnvScope` |
| `EnvValue` | `UbuntuEnvValue` | `MacosEnvValue` | `WindowsEnvValue` | `EnvValue` |
| `EnvActionResult` | `UbuntuEnvActionResult` | `MacosEnvActionResult` | `WindowsEnvActionResult` | `EnvActionResult` |
| `EnvConfigError` | `UbuntuEnvConfigError` | `MacosEnvConfigError` | `WindowsEnvConfigError` | `EnvConfigError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the configurator:

- A configurator tested with a `MockFileOperator` and no aspects MUST
  produce the same `EnvActionResult` sequence when driven by a real
  operator with `PersistenceAspect`, `RetryAspect`, and
  `TimeoutAspect` attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One set test per scope proving the correct source is modified.
2. One idempotency test per scope proving `SKIPPED` when the value
   is already set.
3. One unset test per scope proving the variable is removed.
4. One unset-idempotency test per scope proving `SKIPPED` when the
   variable is not present.
5. One unknown-user test for user-scope writes proving `FAILED` with
   a descriptive `message` and no file-operator calls.
6. One unknown-user test for user-scope reads proving
   `EnvConfigError` is raised.
7. One `list_*` test per scope covering a populated source.
8. One `list_*` test per scope proving an empty dict is returned for
   a missing source.
9. One dry-run test per write verb proving no file operations occur.
10. One elevation test proving system-scope writes pass
    `elevated=True` and reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Per-shell environment configuration (bash, zsh, fish, PowerShell
  profile scripts beyond the OS's default).
- GUI-session-only variables (GNOME / macOS WindowServer / Explorer
  shell-init).
- Variable expansion / interpolation inside values.
- Transactional multi-variable writes.
- `PATH`-aware prepend/append semantics — values are treated as
  opaque strings.
- Broadcasting environment-change notifications (e.g., Windows
  `WM_SETTINGCHANGE`, macOS `launchctl setenv`).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`ICommandRunner` instead of `IFileOperator`.** All three
  per-OS implementations route file I/O through `ICommandRunner`
  (no concrete `IFileOperator` exists in the ecosystem). See the
  README "Implementation Conventions" file-I/O convention.
- **Backend divergence.** Ubuntu writes `/etc/profile.d/*.sh`
  drop-ins; macOS writes launchd plists and per-user
  `.zprofile` / `.zshenv` files; Windows writes the
  `HKCU\Environment` and `HKLM\System\CurrentControlSet\Control\
  Session Manager\Environment` registry keys via PowerShell.
  Per-OS specs document the exact source paths.
- **`requires_reboot: bool` on Windows system-scope writes.**
  Some Windows system-scope env writes require a reboot (or at
  least an explorer.exe restart) to take effect; the
  `WindowsEnvActionResult` carries `requires_reboot: bool = False`.
