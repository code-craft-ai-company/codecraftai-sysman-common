# Configuration-Management Contract

This is the cross-OS abstract contract for the **configuration-management**
feature. Every `automojo-sysman-*` package that ships a configuration
manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-configuration-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-configuration-management/).
It treats configuration files as the unit of management, using `cat`,
`tee`, `cp`, `chmod`, and `chown` through an `ICommandRunner`. This
contract generalises that shape for OSes whose configuration surface
includes plist files, the Windows registry, NVRAM variables, and
ordinary text files.

---

## Scope

The configuration-management feature provides idempotent, auditable
mutation and inspection of system configuration artifacts. It covers:

- Reading, writing, and removing named settings within a configuration
  source.
- Listing settings within a source.
- Computing a diff between the current and a desired content.
- Validating a configuration source using a registered validator.
- Backing up a configuration source and restoring from a backup.
- Setting permissions and ownership on configuration sources.
- Triggering a service reload when a backing service is known.
- Applying elevation for writes; reads never elevate.
- Supporting dry-run mode that short-circuits all mutations.

The feature is executed exclusively through an `ICommandRunner`. No
direct `subprocess`, no direct filesystem writes.

---

## Verbs

Every OS implementation MUST expose a `ConfigurationManager` class
(the OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `read_setting` | `(source: str, key: str) → SettingValue` | Read |
| `write_setting` | `(source: str, key: str, value: str) → ConfigActionResult` | Write |
| `remove_setting` | `(source: str, key: str) → ConfigActionResult` | Write |
| `list_settings` | `(source: str) → list[SettingValue]` | Read |
| `write` | `(source: str, content: str, mode: int \| None, owner: str \| None, group: str \| None) → ConfigActionResult` | Write |
| `diff` | `(source: str, desired_content: str) → ConfigDiffResult` | Read |
| `validate` | `(source: str, validator_id: str) → ConfigValidationResult` | Read |
| `backup_configuration` | `(source: str) → ConfigActionResult` | Write |
| `restore_configuration` | `(backup_path: str) → ConfigActionResult` | Write |
| `set_permissions` | `(source: str, mode: int) → ConfigActionResult` | Write |
| `set_ownership` | `(source: str, user: str \| None, group: str \| None) → ConfigActionResult` | Write |
| `reload_configuration` | `(service: str) → ConfigActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** Before any write, the manager MUST read
   the current value (via `read_setting`, `list_settings`, or a raw
   read of the source) and compare to the desired state. Matching
   state MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner. The `diff` field MAY be populated
   with the unified diff that would have been applied.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` with `exit_code`, `stdout`, and `stderr` populated.
   Writes do NOT raise for routine failures.
4. **Persistence.** Writes MUST update the persistent configuration
   source. Runtime-only overrides are out of scope.
5. **Typed preconditions.** `backup_configuration`, `set_permissions`,
   and `set_ownership` MUST raise `ConfigFileNotFoundError` when the
   source does not exist. `validate` MUST raise
   `ConfigValidatorNotFoundError` for unregistered validators.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, regardless of config.
2. **Typed errors.** `read_setting` and `list_settings` MAY raise
   `ConfigQueryError` when the source cannot be read for reasons
   other than "source does not exist", OR (per the per-OS spec)
   return an empty list / synthetic record. A missing source MUST
   yield an empty `list_settings` result; `read_setting` MUST raise
   `ConfigSettingNotFoundError` when the setting is missing but
   the source is readable. See the README "Implementation
   Conventions" graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python / library code and
   does not require the OS's native configuration tool.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `ConfigActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and returned non-zero. |
| `SKIPPED` | The idempotency guard short-circuited the write. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

Implementations MAY append OS-specific statuses at the tail and MUST
document any additions.

### `ConfigActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ConfigActionStatus` | Outcome category. |
| `source` | `str` | The configuration source (path, plist key, registry key). |
| `key` | `str \| None` | The setting name, or `None` for whole-source operations. |
| `backup_path` | `str \| None` | Populated by `backup_configuration` and `restore_configuration`. |
| `diff` | `str \| None` | Unified diff for `DRY_RUN` results with content changes. |
| `exit_code` | `int \| None` | Runner exit code when a command ran. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `SettingValue` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | The source (path, plist, registry key). |
| `key` | `str` | The setting name. |
| `value` | `str` | The raw value string. |
| `value_type` | `str \| None` | Native value type (e.g., plist `string`, registry `REG_DWORD`). |

### `ConfigDiffResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | The source being compared. |
| `has_diff` | `bool` | `True` when contents differ. |
| `diff` | `str` | Unified diff; empty string when `has_diff=False`. |

### `ConfigValidationResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | The source validated. |
| `validator_id` | `str` | The registered validator used. |
| `valid` | `bool` | Whether the validator succeeded. |
| `exit_code` | `int` | The validator exit code. |
| `stdout` | `str` | Captured stdout. |
| `stderr` | `str` | Captured stderr. |

### `ConfigFileInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | The source identifier. |
| `exists` | `bool` | Whether the source exists. |
| `mode` | `str \| None` | Octal mode string where applicable. |
| `owner` | `str \| None` | Owner where applicable. |
| `group` | `str \| None` | Group where applicable. |
| `size_bytes` | `int \| None` | File size where applicable. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ConfigFileNotFoundError` | `backup_configuration`, `restore_configuration`, `set_permissions`, or `set_ownership` targets a non-existent source. |
| `ConfigTemplateError` | A template-render helper is invoked with a missing variable. |
| `ConfigValidatorNotFoundError` | `validate` is called with an unregistered validator. |
| `ConfigSettingNotFoundError` | `read_setting` targets a missing key in an existing source. |
| `ConfigQueryError` | A read fails for a reason other than "source missing". |

### `ConfigurationManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations are dispatched. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Configuration-Source Mapping

The abstract `source` parameter maps to the native configuration
surface of each OS.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | Text files under `/etc/` | Canonical. INI / plain-text / shell-snippet formats. |
| Ubuntu | Text files under `/etc/` plus `/etc/default/<name>` fragments | Same shape as RHEL; validators use Debian-specific tools (`apachectl -t`, `ufw status` etc.). |
| macOS | `/etc/<file>` for BSD-inherited services; `/Library/Preferences/` and `~/Library/Preferences/` plist files for services and apps | Plist sources use `defaults read/write` / `plutil`; file sources use the same `cat`/`tee` pattern. |
| Windows | Registry paths (`HKLM\Software\...`, `HKCU\...`) and `%ProgramData%\...` text files | Registry sources use `reg.exe` or PowerShell `Set-ItemProperty`; text sources use `Get-Content`/`Set-Content`. |
| UEFI | NVRAM variables (GUID + name) and ESP configuration files | NVRAM sources use `efibootmgr`-equivalent / `SetVariable`; ESP sources use EFI shell file I/O. UEFI applicability **is in scope** for this contract. |

Each OS spec MUST include a Source-Mapping section that states its
choice of source identifier format and the subset of formats it
supports.

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
        <Os>ConfigurationManager
                │
                │  .run(argv, elevated=…, stdin=content, capture_output=True)
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

1. Accept an `ICommandRunner` and a `ConfigurationManagerConfig` in
   their constructor.
2. Never construct their own runner or subprocess.
3. Maintain a `ValidatorRegistry` (a mapping from validator id to
   argv-builder callable) that is populated at import time with
   OS-appropriate defaults and is runtime-extensible.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `ConfigurationManager` | `UbuntuConfigurationManager` | `MacosConfigurationManager` | `WindowsConfigurationManager` | `ConfigurationManager` |
| `ConfigurationManagerConfig` | `UbuntuConfigurationManagerConfig` | `MacosConfigurationManagerConfig` | `WindowsConfigurationManagerConfig` | `ConfigurationManagerConfig` |
| `ConfigActionStatus` | `UbuntuConfigActionStatus` | `MacosConfigActionStatus` | `WindowsConfigActionStatus` | `ConfigActionStatus` |
| `ConfigActionResult` | `UbuntuConfigActionResult` | `MacosConfigActionResult` | `WindowsConfigActionResult` | `ConfigActionResult` |
| `SettingValue` | `UbuntuSettingValue` | `MacosSettingValue` | `WindowsSettingValue` | `SettingValue` |
| `ConfigDiffResult` | `UbuntuConfigDiffResult` | `MacosConfigDiffResult` | `WindowsConfigDiffResult` | `ConfigDiffResult` |
| `ConfigValidationResult` | `UbuntuConfigValidationResult` | `MacosConfigValidationResult` | `WindowsConfigValidationResult` | `ConfigValidationResult` |
| `ConfigFileInfo` | `UbuntuConfigFileInfo` | `MacosConfigFileInfo` | `WindowsConfigFileInfo` | `ConfigFileInfo` |

Exception classes follow the same rule:
`UbuntuConfigFileNotFoundError`, `MacosConfigValidatorNotFoundError`,
etc.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ConfigActionResult` sequence when driven by a
  real runner with `PersistenceAspect`, `RetryAspect`, and
  `TimeoutAspect` attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One write test per verb proving command construction.
2. One idempotency test per write proving `SKIPPED` is returned
   when the desired state is already in effect.
3. One dry-run test per write proving the runner is not invoked.
4. One parser test per read verb covering realistic multi-setting
   output.
5. One `validate` test per registered validator covering a
   compliant and a non-compliant input.
6. One `diff` test covering non-existent-source → full-addition diff.
7. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.
8. One template error test (if the implementation exposes a template
   helper) proving `ConfigTemplateError` is raised before any
   runner invocation.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Cross-source transactions (atomic multi-source writes).
- Schema-aware editors beyond simple INI / plist / registry key
  manipulation.
- GUI-based configuration surfaces (System Preferences / Settings).
- Secrets management / encrypted-at-rest configuration.
- Distributed configuration sources (LDAP, Active Directory,
  Puppet/Chef catalogs).
- Watching a source for external changes.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Per-OS source kinds.** Ubuntu's `UbuntuConfigSource` enumerates
  `INI`, `KEY_VALUE`, `JSON`, `YAML`; macOS's `MacosConfigSource`
  adds `PLIST_BINARY` / `PLIST_XML` / `NVRAM`; Windows's
  `WindowsConfigSource` adds `REGISTRY` and `XML`. The contract's
  abstract source kind is the union; per-OS callers consume the
  prefixed enum.
- **File I/O via `ICommandRunner`.** All source reads/writes route
  through the runner using `cat`, `tee`, `mv`, `chmod`, `chown`
  on POSIX and `Get-Content`, `Set-Content`, `Move-Item`,
  `Get-Acl`, `Set-Acl` on Windows. No `IFileOperator` is used.
- **`detail="not_set"` on successful reads with no value.** When
  a setting key resolves but carries no value, implementations
  return `read_setting` result with `detail="not_set"` rather
  than raising `ConfigSettingNotFoundError`. See the README
  stable-token catalog.
