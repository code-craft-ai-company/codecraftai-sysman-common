# Localization-Management Contract

This is the cross-OS abstract contract for the
**localization-management** feature. Every `automojo-sysman-*`
package that ships a localization manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-localization-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-localization-management/).
It uses `localectl`, `timedatectl`, and `/etc/locale.conf` through
an `ICommandRunner`. This contract generalises the verb set for
OSes whose native locale / keymap / timezone surface is `defaults
write .GlobalPreferences` + `systemsetup` (macOS) or
`Set-Culture` / `Set-WinUserLanguageList` / `Set-TimeZone`
(Windows).

> **Timezone overlap.** The timezone verbs in this contract
> overlap with the `precision-time-management` feature. The two
> contracts are intentionally redundant: `localization-management`
> owns the user-facing locale / keymap / timezone triple that
> presents to end users, while `precision-time-management` owns
> clock-synchronisation sources and drift. Coordinators SHOULD
> pick one owner per field per deployment.

---

## Scope

The localization-management feature provides idempotent, auditable
control over a host's system-wide locale, keyboard layout, and
timezone settings. It covers:

- Querying and setting the active locale (e.g., `en_US.UTF-8`).
- Enumerating supported locales.
- Querying and setting the keyboard layout / keymap.
- Querying and setting the system timezone.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.
File-operator usage is advisory only, for cross-checking
`/etc/locale.conf`, `/etc/vconsole.conf`, or registry-backed
analogs.

---

## Verbs

Every OS implementation MUST expose a `LocalizationManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_locale` | `() → LocaleInfo` | Read |
| `set_locale` | `(locale: str) → LocalizationActionResult` | Write |
| `list_supported_locales` | `() → list[str]` | Read |
| `get_keymap` | `() → KeymapInfo` | Read |
| `set_keymap` | `(keymap: str) → LocalizationActionResult` | Write |
| `get_timezone` | `() → TimezoneInfo` | Read |
| `set_timezone` | `(tz: str) → LocalizationActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** Each write MUST query the corresponding
   read before invoking the underlying mutation and return
   `SKIPPED` when the requested value matches.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Validation.** `set_locale` MUST return `FAILED` with a
   descriptive `detail` when the supplied locale is not in the
   supported list. `set_timezone` MUST return `FAILED` when the
   supplied timezone is not a valid IANA / Windows-registry name on
   the OS.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MAY raise
   `LocalizationQueryError` carrying the exit code and stderr,
   OR (per the per-OS spec) return an empty list / synthetic
   record so callers can proceed without a try/except wrapper.
   See the README "Implementation Conventions" graceful-read
   pattern.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `LocalizationActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or input validation failed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `LocalizationActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `LocalizationActionStatus` | Outcome category. |
| `field` | `str` | Which field was targeted: `"locale"`, `"keymap"`, or `"timezone"`. |
| `requested_value` | `str` | The value the caller asked to set. |
| `previous_value` | `str \| None` | The value read before the mutation, when known. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `LocaleInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `locale` | `str` | Active locale (e.g., `"en_US.UTF-8"`). |
| `language` | `str \| None` | Derived language tag when available. |
| `encoding` | `str \| None` | Derived encoding tag when available. |
| `raw` | `dict[str, str]` | Full native locale-environment dump (`LANG`, `LC_*`). |

### `KeymapInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `keymap` | `str` | Active console keymap (e.g., `"us"`, `"uk"`). |
| `x11_layout` | `str \| None` | Active X11 / graphical-layer layout, when applicable. |
| `x11_variant` | `str \| None` | Active X11 variant. |
| `x11_options` | `str \| None` | Active X11 options. |

### `TimezoneInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `timezone` | `str` | Active timezone (e.g., `"America/Los_Angeles"`). |
| `utc_offset_seconds` | `int` | Current offset from UTC in seconds. |
| `dst_active` | `bool` | Whether DST is currently in effect. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `LocalizationQueryError` | A read fails unexpectedly. |

### `LocalizationManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

---

## Field Mapping

Localization has no natural scope parameter — it is host-wide. The
abstract field names map to each OS's native command surface.

| OS | Locale | Keymap | Timezone |
|----|--------|--------|----------|
| Red Hat Enterprise Linux | `localectl set-locale LANG=<…>` / `/etc/locale.conf` | `localectl set-keymap <…>` / `/etc/vconsole.conf` | `timedatectl set-timezone <…>` |
| Ubuntu | Same as RHEL; `update-locale` acceptable fallback | Same as RHEL | Same as RHEL |
| macOS | `defaults write .GlobalPreferences AppleLocale <…>` (per-user) + `sudo languagesetup` for boot-level | `defaults write com.apple.HIToolbox AppleCurrentKeyboardLayoutInputSourceID <…>` | `sudo systemsetup -settimezone <…>` |
| Windows | `Set-WinUserLanguageList` + `Set-Culture` | `Set-WinUserLanguageList -InputTip <…>` | `Set-TimeZone -Id "<…>"` |
| UEFI | N/A | Firmware-level keymap (rare; not covered) | UEFI variable `Time` (out of scope) |

Each OS spec MUST include a Field-Mapping section that states its
command invocations and input validation rules.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |
| Per-user vs system locale | macOS `defaults write .GlobalPreferences` for the current user does NOT require elevation; system-wide writes DO. The macOS spec MUST document which scope each verb targets. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>LocalizationManager
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

1. Accept an `ICommandRunner` and a `LocalizationManagerConfig` in
   their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `LocalizationManager` | `UbuntuLocalizationManager` | `MacosLocalizationManager` | `WindowsLocalizationManager` | `LocalizationManager` |
| `LocalizationManagerConfig` | `UbuntuLocalizationManagerConfig` | `MacosLocalizationManagerConfig` | `WindowsLocalizationManagerConfig` | `LocalizationManagerConfig` |
| `LocalizationActionStatus` | `UbuntuLocalizationActionStatus` | `MacosLocalizationActionStatus` | `WindowsLocalizationActionStatus` | `LocalizationActionStatus` |
| `LocalizationActionResult` | `UbuntuLocalizationActionResult` | `MacosLocalizationActionResult` | `WindowsLocalizationActionResult` | `LocalizationActionResult` |
| `LocaleInfo` | `UbuntuLocaleInfo` | `MacosLocaleInfo` | `WindowsLocaleInfo` | `LocaleState` |
| `KeymapInfo` | `UbuntuKeymapInfo` | `MacosKeymapInfo` | `WindowsKeymapInfo` | `KeymapState` |
| `TimezoneInfo` | `UbuntuTimezoneInfo` | `MacosTimezoneInfo` | `WindowsTimezoneInfo` | `TimeState` |
| `LocalizationQueryError` | `UbuntuLocalizationQueryError` | `MacosLocalizationQueryError` | `WindowsLocalizationQueryError` | `LocalizationQueryError` |

The RHEL reference uses `LocaleState` / `KeymapState` / `TimeState`
for historical reasons; new OS packages use the abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `LocalizationActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
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
4. One `get_locale` / `get_keymap` / `get_timezone` parser test.
5. One `list_supported_locales` parser test covering a
   representative multi-entry output.
6. One input-validation test per write verb proving `FAILED` with a
   descriptive `detail` when the value is unsupported.
7. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- NTP / PTP source configuration — lives in
  `precision-time-management`.
- Real-time-clock UTC vs local-time selection.
- Per-user locale overrides beyond the current-user default.
- Input-method framework configuration (IBus, SCIM, IME).
- Home-location / country-code settings beyond locale itself
  (Windows `Set-WinHomeLocation`, macOS region codes).
- X11 keyboard model / options exhaustive lists (RHEL reference
  exposes them; they are OS-specific extensions).
- Locale generation (`locale-gen`) — the base contract assumes
  requested locales are already generated.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`detail="unknown_timezone_id"`.** When a write verb is
  passed a timezone identifier that does not resolve, the
  manager returns `FAILED` with this stable detail token. See
  the README stable-token catalog.
- **Backend divergence.** Ubuntu wraps `localectl` /
  `timedatectl`; macOS wraps `defaults write` against
  `.GlobalPreferences` plus `systemsetup` for timezone /
  network-time; Windows wraps `Set-Culture` /
  `Set-WinSystemLocale` / `Set-TimeZone`.
- **File I/O via `ICommandRunner`.** `/etc/locale.conf`,
  `/etc/vconsole.conf`, plist reads, and registry-key reads
  route through the runner.
