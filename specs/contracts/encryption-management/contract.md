# Encryption-Management Contract

This is the cross-OS abstract contract for the
**encryption-management** feature. Every `automojo-sysman-*`
package that ships an encryption manager MUST honor this
contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-encryption-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-encryption-management/).
It wraps `cryptsetup`, `systemd-cryptenroll`, `clevis`, and
direct edits to `/etc/crypttab` through an `ICommandRunner`.
This contract generalises the verb set for OSes whose
full-volume encryption surface is Linux LUKS (`cryptsetup`),
macOS FileVault (`fdesetup`, `diskutil apfs
encryptVolume`), or Windows BitLocker (PowerShell `BitLocker`
module: `Enable-BitLocker`, `Disable-BitLocker`,
`Get-BitLockerVolume`).

Passphrase and recovery-key bytes MUST flow through runner
`stdin`; they MUST NOT appear on argv. The `command` field in any
result MUST be sanitised.

---

## Scope

The encryption-management feature provides idempotent, auditable
control over full-volume encryption of local storage devices. It
covers:

- Enabling and disabling encryption on a volume.
- Querying encryption state for a volume.
- Listing encrypted volumes on the host.
- Rotating keys / passphrases.
- Backing up a recovery key to a filesystem path.
- Unlocking (attaching / mounting) an encrypted volume.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS
  requires elevation to inspect the encryption subsystem.

The feature does NOT partition, format, or mount filesystems —
those are `storage-management` and `filesystem-management`.

---

## Verbs

Every OS implementation MUST expose an `EncryptionManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `enable_encryption` | `(volume: str, spec: EncryptionSpec, credential: Credential) → EncryptionActionResult` | Write |
| `disable_encryption` | `(volume: str, credential: Credential) → EncryptionActionResult` | Write |
| `get_encryption_status` | `(volume: str) → EncryptionStatus` | Read |
| `list_encrypted_volumes` | `() → list[EncryptionStatus]` | Read |
| `rotate_key` | `(volume: str, old_credential: Credential, new_credential: Credential) → EncryptionActionResult` | Write |
| `backup_recovery_key` | `(volume: str, destination_path: str) → EncryptionActionResult` | Write |
| `unlock_volume` | `(volume: str, credential: Credential) → EncryptionActionResult` | Write |
| `lock_volume` | `(volume: str) → EncryptionActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `enable_encryption` MUST return
   `SKIPPED` when the volume is already encrypted with a
   compatible spec. `disable_encryption` MUST return `SKIPPED`
   when the volume is already plaintext. `unlock_volume` MUST
   return `SKIPPED` when the volume is already unlocked.
   `lock_volume` MUST return `SKIPPED` when the volume is
   already locked / not attached.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Credential safety.** Every passphrase / recovery-key byte
   MUST flow on `stdin`. The `command` field MUST be sanitised.
5. **Last-key safety rail.** On OSes where key slots are
   enumerable, writes that would remove the last enabled key
   slot (leaving the volume unrecoverable) MUST return `FAILED`
   with a descriptive `detail` and MUST NOT invoke the
   destructive command.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` unless
   the OS requires it to inspect the encryption subsystem.
2. **Typed errors.** Reads MAY raise `EncryptionQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list / synthetic record so callers can proceed without a
   try/except wrapper. An unknown volume MUST raise
   `EncryptionVolumeNotFoundError`. See the README "Implementation
   Conventions" graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `EncryptionActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a safety rail blocked the action. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `EncryptionBackend` (enum)

| Value | Meaning |
|-------|---------|
| `LUKS` | Linux LUKS via `cryptsetup`. |
| `FILEVAULT` | macOS FileVault. |
| `BITLOCKER` | Windows BitLocker. |

### `EncryptionKeySlotState` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `slot` | `int` | Slot index. |
| `enabled` | `bool` | Whether the slot is in use. |
| `kind` | `str` | Slot kind (`"passphrase"`, `"recovery"`, `"tpm"`, `"escrow"`, `"keyfile"`). |

### `EncryptionSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `backend` | `EncryptionBackend` | Backend to use. |
| `cipher` | `str \| None` | Native cipher spec (LUKS `aes-xts-plain64`, BitLocker `AES256`, ...). |
| `key_size_bits` | `int \| None` | Key size in bits. |
| `use_tpm` | `bool` | When `True`, bind to TPM where supported. |
| `extra_options` | `dict[str, str]` | Backend-specific extras. |

### `EncryptionStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `volume` | `str` | Volume identifier (device path, GPT UUID, drive letter). |
| `backend` | `EncryptionBackend` | Backend on the volume. |
| `encrypted` | `bool` | Whether the volume is currently encrypted. |
| `unlocked` | `bool` | Whether the volume is currently unlocked / attached. |
| `cipher` | `str \| None` | Current cipher. |
| `key_size_bits` | `int \| None` | Current key size. |
| `key_slots` | `list[EncryptionKeySlotState]` | Slot states where enumerable (empty list when not). |
| `tpm_bound` | `bool` | Whether a TPM binding is active. |

### `EncryptionActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `EncryptionActionStatus` | Outcome category. |
| `volume` | `str \| None` | Volume acted upon. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | Sanitised argv. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `EncryptionQueryError` | A read fails unexpectedly. |
| `EncryptionVolumeNotFoundError` | A volume-addressing verb is given an unknown volume. |
| `EncryptionCredentialError` | A verb requires a credential and none was supplied. |

### `EncryptionManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Backend Mapping

The abstract `EncryptionBackend` maps to each OS's native
tooling:

| OS | Native backend | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `LUKS` via `cryptsetup` + `systemd-cryptenroll` + optional `clevis` | Canonical. |
| Ubuntu | `LUKS` | — |
| macOS | `FILEVAULT` via `fdesetup` for the boot volume; `diskutil apfs encryptVolume` for data volumes. | Per-volume key-slot enumeration is coarse; `key_slots` MAY be empty. |
| Windows | `BITLOCKER` via `Enable-BitLocker`, `Disable-BitLocker`, `Get-BitLockerVolume`. | Volume identifiers are drive letters (`"C:"`) or GPT volume paths. |
| UEFI | N/A | UEFI has no encryption surface at this layer. The contract does not apply. |

Each OS spec MUST include a Backend-Mapping section.

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
                │  instantiates + injects runner, config
                │  supplies credential objects for passphrases
                ▼
        <Os>EncryptionManager
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

1. Accept an `ICommandRunner` and an `EncryptionManagerConfig`
   in their constructor.
2. Never construct their own subprocess.
3. Never place secret bytes on argv.
4. Not hold state across calls beyond the config.
5. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `EncryptionManager` | `UbuntuEncryptionManager` | `MacosEncryptionManager` | `WindowsEncryptionManager` | `EncryptionManager` |
| `EncryptionManagerConfig` | `UbuntuEncryptionManagerConfig` | `MacosEncryptionManagerConfig` | `WindowsEncryptionManagerConfig` | `EncryptionManagerConfig` |
| `EncryptionActionStatus` | `UbuntuEncryptionActionStatus` | `MacosEncryptionActionStatus` | `WindowsEncryptionActionStatus` | `EncryptionActionStatus` |
| `EncryptionActionResult` | `UbuntuEncryptionActionResult` | `MacosEncryptionActionResult` | `WindowsEncryptionActionResult` | `EncryptionActionResult` |
| `EncryptionBackend` | `UbuntuEncryptionBackend` | `MacosEncryptionBackend` | `WindowsEncryptionBackend` | `EncryptionBackend` |
| `EncryptionSpec` | `UbuntuEncryptionSpec` | `MacosEncryptionSpec` | `WindowsEncryptionSpec` | `CryptFormatSpec` |
| `EncryptionStatus` | `UbuntuEncryptionStatus` | `MacosEncryptionStatus` | `WindowsEncryptionStatus` | `LuksHeader` |
| `EncryptionKeySlotState` | `UbuntuEncryptionKeySlotState` | `MacosEncryptionKeySlotState` | `WindowsEncryptionKeySlotState` | `KeySlotInfo` |
| `EncryptionQueryError` | `UbuntuEncryptionQueryError` | `MacosEncryptionQueryError` | `WindowsEncryptionQueryError` | `EncryptionQueryError` |
| `EncryptionVolumeNotFoundError` | `UbuntuEncryptionVolumeNotFoundError` | `MacosEncryptionVolumeNotFoundError` | `WindowsEncryptionVolumeNotFoundError` | `EncryptionVolumeNotFoundError` |
| `EncryptionCredentialError` | `UbuntuEncryptionCredentialError` | `MacosEncryptionCredentialError` | `WindowsEncryptionCredentialError` | `EncryptionCredentialError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `EncryptionActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`. Retry aspects MUST NOT re-send secret bytes beyond
  the runner's documented retry-redelivery contract.
- Persistence aspects MUST NOT mutate the result. Persistence
  aspects MUST NOT log `stdin` bytes.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_encryption_status` parser test covering both the
   encrypted and plaintext paths.
5. One `list_encrypted_volumes` parser test covering
   representative output.
6. One last-key safety-rail test proving that a write which
   would remove the last enabled key slot returns `FAILED`
   without dispatching the destructive command (where the OS
   exposes slots).
7. One credential-safety test proving passphrases never appear
   in the recorded argv.
8. One `EncryptionCredentialError` test proving the right
   exception fires when a credential is required but absent.
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Partitioning, LVM, RAID, and block-device provisioning (see
  `storage-management`).
- `/etc/crypttab` / initramfs boot-time unlock wiring beyond
  persisting entries alongside encryption.
- Per-file encryption (eCryptfs, EFS).
- Network-bound disk encryption advanced policies (Clevis PIN
  selection beyond TPM, Tang).
- Key-escrow to external services (MBAM, MDM vendors).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu wraps LUKS via
  `cryptsetup`; macOS wraps FileVault via `fdesetup` /
  `diskutil apfs`; Windows wraps BitLocker via
  `manage-bde` / `Get-BitLockerVolume` / `Enable-BitLocker`.
  Field shapes diverge accordingly.
- **`requires_reboot: bool`.** Windows BitLocker enablement
  often requires a reboot to take effect; the
  `WindowsEncryptionActionResult` carries
  `requires_reboot: bool = False` so the coordinator can sequence
  reboots. See the README reboot-signaling convention.
- **Credential-safety convention.** All implementations route
  passphrases via `--key-file`-style argv arguments pointing to
  ephemeral files written by the runner; passphrases never appear
  in the recorded `command` argv.
- **`detail="elevation_blocked"` on Windows.** When the manager
  is invoked without elevation but the verb requires admin
  privileges, the Windows runner returns the structured
  elevation-blocked result.
- Encryption hardware offload tuning (AES-NI / crypto engine
  selection).
