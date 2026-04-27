# Bootloader-Management Contract

This is the cross-OS abstract contract for the
**bootloader-management** feature. Every `automojo-sysman-*`
package that ships a bootloader manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-boot-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-boot-management/).
It wraps `grubby`, `grub2-mkconfig`, and direct edits to
`/etc/default/grub` through an `ICommandRunner` (and MAY use an
`IFileOperator` where available; the established pattern is to
route file I/O through `ICommandRunner` — see the README
"Implementation Conventions"). This contract generalises the verb set for OSes
whose bootloader surface is GRUB 2 (Linux), systemd-boot
(`bootctl`, on some Ubuntu and other systemd-boot hosts),
macOS `bless` plus the boot plist, or Windows Boot Configuration
Data (`bcdedit`).

**Important:** This contract is distinct from the separate
`boot-management` contract, which addresses UEFI firmware boot
entries (`efibootmgr`, `bcdedit /firmware`). This contract
addresses **the bootloader-config layer that sits between the
firmware entry and the kernel**.

---

## Scope

The bootloader-management feature provides idempotent, auditable
control over the host's bootloader-configuration layer. It
covers:

- Listing the boot entries known to the bootloader.
- Querying and setting the default boot entry.
- Adding a new boot entry from a declarative spec.
- Removing a boot entry by identifier.
- Regenerating the bootloader's on-disk configuration from its
  source templates / drop-ins.
- Reading and writing individual bootloader configuration
  directives.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the bootloader
  config is itself access-controlled.

The feature does NOT touch UEFI firmware boot entries
(that is `boot-management`), and does NOT touch the ESP directly
(that is `esp-management`).

---

## Verbs

Every OS implementation MUST expose a `BootloaderManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_entries` | `() → list[BootloaderEntry]` | Read |
| `get_default_entry` | `() → BootloaderEntry` | Read |
| `set_default_entry` | `(entry_id: str) → BootloaderActionResult` | Write |
| `add_entry` | `(spec: BootloaderEntrySpec) → BootloaderActionResult` | Write |
| `remove_entry` | `(entry_id: str) → BootloaderActionResult` | Write |
| `update_bootloader_config` | `(key: str, value: str \| None) → BootloaderActionResult` | Write |
| `get_bootloader_config` | `(key: str) → str \| None` | Read |
| `regenerate_config` | `() → BootloaderActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `set_default_entry` MUST return
   `SKIPPED` when the supplied entry is already the default.
   `add_entry` MUST return `SKIPPED` when an entry with the same
   identifier and normalised spec already exists.
   `remove_entry` MUST return `SKIPPED` when the entry is absent.
   `update_bootloader_config` MUST return `SKIPPED` when the
   directive is already at the requested value.
   `regenerate_config` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner or file operator.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Running-kernel safety.** `remove_entry` MUST return `FAILED`
   with a descriptive `detail` when the target entry matches the
   currently running boot selection (where the OS exposes that
   information) and MUST NOT invoke the removal command.
5. **Regenerate coupling.** On OSes where directive writes are
   effective only after a regeneration step (GRUB 2), writes to
   `/etc/default/grub` MUST set the result `detail` to indicate
   a follow-up `regenerate_config` is required. Callers are
   responsible for invoking `regenerate_config`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, except where the OS requires elevation to read the
   bootloader store (e.g., BCD on Windows).
2. **Typed errors.** All reads MAY raise `BootloaderQueryError`
   for unexpected failures or, per the per-OS spec, return an
   empty list / synthetic record so callers can proceed without a
   try/except wrapper. An unknown entry or key MUST produce
   a `None` return (`get_bootloader_config`) or a typed
   `BootloaderEntryNotFoundError` (`get_default_entry` when no
   entries exist).
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `BootloaderActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `BootloaderKind` (enum)

| Value | Meaning |
|-------|---------|
| `GRUB2` | GRUB 2. |
| `SYSTEMD_BOOT` | systemd-boot (`bootctl`). |
| `BLESS` | macOS `bless` / boot plist. |
| `BCD` | Windows Boot Configuration Data. |

### `BootloaderEntry` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | `str` | Native identifier (GRUB title / index, BCD GUID, bootctl entry id, macOS blessed path). |
| `title` | `str` | Human-readable entry title. |
| `kernel` | `str \| None` | Kernel image path when applicable. |
| `initrd` | `str \| None` | Initramfs / initrd path when applicable. |
| `cmdline` | `str \| None` | Kernel command line when applicable. |
| `is_default` | `bool` | Whether this entry is currently the default. |
| `source` | `str \| None` | On-disk origin (config file / key) for the entry. |

### `BootloaderEntrySpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | `str` | Caller-chosen identifier. |
| `title` | `str` | Display title. |
| `kernel` | `str \| None` | Kernel image path. |
| `initrd` | `str \| None` | Initramfs path. |
| `cmdline` | `str \| None` | Kernel command line. |
| `options` | `dict[str, str]` | Additional OS-specific options. |

### `BootloaderActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `BootloaderActionStatus` | Outcome category. |
| `entry_id` | `str \| None` | Entry identifier acted upon. |
| `detail` | `str \| None` | Human-readable detail; MAY indicate a follow-up regenerate step is required. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `BootloaderQueryError` | A read fails unexpectedly. |
| `BootloaderEntryNotFoundError` | `get_default_entry` is invoked against a bootloader with no entries, or a verb is given a non-existent `entry_id` and the OS surface requires raising rather than skipping. |

### `BootloaderManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |
| `kind` | `BootloaderKind \| None` | `None` | Override auto-detection of the bootloader. |

---

## Bootloader-Kind Mapping

The abstract `BootloaderKind` maps to each OS's native tooling:

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | GRUB 2 via `grubby` + `grub2-mkconfig` + `/etc/default/grub` + `/etc/grub.d/` | Canonical. `regenerate_config` runs `grub2-mkconfig` against the firmware-appropriate path (BIOS vs UEFI). |
| Ubuntu | GRUB 2 via `update-grub` + `/etc/default/grub`; optionally systemd-boot on UEFI hosts via `bootctl`. | The OS spec MUST state whether it supports both and how it auto-detects. |
| macOS | `bless` on the signed system volume and `/Library/Preferences/SystemConfiguration/com.apple.Boot.plist`. `add_entry` / `remove_entry` MAY return `FAILED` when the host is sealed; the OS spec MUST document this. | — |
| Windows | BCD via `bcdedit /store`. `entry_id` is the BCD GUID. `cmdline` is not applicable; Windows entries expose a different option set encoded into `options`. | — |
| UEFI | N/A | UEFI firmware boot entries are `boot-management`, not this feature. |

Each OS spec MUST include a Bootloader-Kind Mapping section
listing which kinds it supports and how it auto-detects when
`config.kind is None`.

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
        <Os>BootloaderManager
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

1. Accept an `ICommandRunner` and a
   `BootloaderManagerConfig` in their constructor.
   Implementations whose directive store is a plain file MAY also
   accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `BootloaderManager` | `UbuntuBootloaderManager` | `MacosBootloaderManager` | `WindowsBootloaderManager` | `BootloaderManager` |
| `BootloaderManagerConfig` | `UbuntuBootloaderManagerConfig` | `MacosBootloaderManagerConfig` | `WindowsBootloaderManagerConfig` | `BootloaderManagerConfig` |
| `BootloaderActionStatus` | `UbuntuBootloaderActionStatus` | `MacosBootloaderActionStatus` | `WindowsBootloaderActionStatus` | `BootloaderActionStatus` |
| `BootloaderActionResult` | `UbuntuBootloaderActionResult` | `MacosBootloaderActionResult` | `WindowsBootloaderActionResult` | `BootloaderActionResult` |
| `BootloaderKind` | `UbuntuBootloaderKind` | `MacosBootloaderKind` | `WindowsBootloaderKind` | `BootloaderKind` |
| `BootloaderEntry` | `UbuntuBootloaderEntry` | `MacosBootloaderEntry` | `WindowsBootloaderEntry` | `BootloaderEntry` |
| `BootloaderEntrySpec` | `UbuntuBootloaderEntrySpec` | `MacosBootloaderEntrySpec` | `WindowsBootloaderEntrySpec` | `BootloaderEntrySpec` |
| `BootloaderQueryError` | `UbuntuBootloaderQueryError` | `MacosBootloaderQueryError` | `WindowsBootloaderQueryError` | `BootloaderQueryError` |
| `BootloaderEntryNotFoundError` | `UbuntuBootloaderEntryNotFoundError` | `MacosBootloaderEntryNotFoundError` | `WindowsBootloaderEntryNotFoundError` | `BootloaderEntryNotFoundError` |

The RHEL reference uses the historical unprefixed names
(`BootManager` / `BootActionResult`) in the existing module; this
contract adopts the `Bootloader*` names for new packages to avoid
collision with the `boot-management` contract (UEFI firmware
entries).

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `BootloaderActionResult` sequence when driven
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
4. One `list_entries` parser test covering representative
   output.
5. One `get_default_entry` test covering both the happy path and
   the empty-bootloader case.
6. One `remove_entry` test proving `FAILED` when the target
   matches the running kernel / active boot selection.
7. One `regenerate_config` test proving the correct native
   command is dispatched for the detected firmware kind.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- UEFI firmware boot entries (`efibootmgr`, `bcdedit /firmware`)
  — covered by `boot-management`.
- Kernel installation / cleanup — covered by a kernel-lifecycle
  feature.
- Kernel parameter tuning — covered by `kernel-parameters`.
- ESP filesystem layout — covered by `esp-management`.
- Secure Boot signature verification / shim configuration —
  covered by `secure-boot`.
- Systemd unit ordering during boot.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu uses
  `grubby` / `grub-mkconfig` / `update-grub`; macOS uses
  `bless` plus the boot plist (no GRUB analog); Windows uses
  `bcdedit` over BCD. The per-OS dataclass shapes carry
  backend-specific fields the contract does not enumerate
  (e.g., `bcd_store_path` on Windows, `boot_volume` on macOS).
- **`requires_reboot: bool`.** Windows BCD edits and macOS bless
  changes require a reboot to take effect. The Windows / macOS
  `*BootloaderActionResult` carries `requires_reboot: bool = False`
  so coordinators can sequence reboots correctly. See the README
  "Implementation Conventions" reboot-signaling pattern.
- **File I/O via `ICommandRunner`.** Direct file edits to
  `/etc/default/grub`, `40_custom`, and BCD-store exports route
  through `cat` / `tee` / `Get-Content` / `Set-Content` rather than
  `IFileOperator`.
