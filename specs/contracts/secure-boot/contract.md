# Secure-Boot Contract

This is the cross-OS abstract contract for the **secure-boot**
feature. Every `codecraftai-sysman-*` package that ships a Secure Boot
manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-uefi/specs/3-secure-boot/`](../../../../../codecraftai-sysman-uefi/specs/3-secure-boot/).
It reads Secure Boot state from firmware, enumerates key slots
(`PK`, `KEK`, `db`, `dbx`, and the MOK list on Linux hosts),
dispatches MOK enrollment through `mokutil` on Linux hosts, and
reports the Apple Silicon Secure Boot policy through `bputil` on
macOS hosts and `Confirm-SecureBootUEFI` / `Get-SecureBootPolicy`
on Windows hosts, all through an `ICommandRunner`.

---

## Scope

The secure-boot feature provides auditable inspection of Secure
Boot state and policy, plus the narrow subset of write operations
that the host OS exposes to user-space (MOK enrollment on Linux
only). It covers:

- Reading the current Secure Boot enabled / disabled state.
- Reading the current Secure Boot policy (the key hashes enrolled in
  the `PK`, `KEK`, `db`, and `dbx` slots, and the MOK list where
  applicable).
- Enrolling a Machine-Owner Key (MOK) from a certificate file
  (Linux only; `FAILED` on macOS / Windows).
- Deleting a MOK key by fingerprint (Linux only; `FAILED` elsewhere).
- Listing enrolled keys across all slots.
- Requesting a Secure Boot mode change (always `FAILED` with a
  firmware-setup-only message — the base contract documents this as
  a non-scriptable operation on every OS).
- Applying elevation for writes, not for reads.
- Supporting dry-run mode.

The feature is executed exclusively through an `ICommandRunner`.
No direct `subprocess`, no direct firmware-variable writes.

---

## Verbs

Every OS implementation MUST expose a `SecureBootManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_secure_boot_state` | `() → SecureBootState` | Read |
| `get_secure_boot_policy` | `() → SecureBootPolicy` | Read |
| `list_enrolled_keys` | `(slot: str \| None) → list[SecureBootKey]` | Read |
| `enroll_mok_key` | `(certificate_path: str) → SecureBootActionResult` | Write |
| `reset_mok` | `(key_fingerprint: str) → SecureBootActionResult` | Write |
| `set_secure_boot_mode` | `(mode: str) → SecureBootActionResult` | Write |

**Writes** apply elevation per §Elevation and return
`SecureBootActionResult`. **Reads** never elevate and return the
specified query dataclass, or raise `SecureBootQueryError`.

### Method-level invariants (writes)

1. **Idempotency guard.** Before enrolling a MOK, the implementation
   MUST call `list_enrolled_keys` and compare the certificate's
   fingerprint to the already-enrolled MOK fingerprints. A matching
   fingerprint MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` with `exit_code`, `stdout`, `stderr`, and `command`
   populated. Writes do NOT raise for routine failures.
4. **Unsupported host OS.** `enroll_mok_key` and `reset_mok` MUST
   return `FAILED` (never `SUCCESS` or silent no-op) on host OSes
   that do not expose a MOK-equivalent userspace surface (macOS,
   Windows). The `detail` MUST cite the specific surface that IS
   exposed (Apple's Boot Policy, OEM `PK`/`KEK`/`db` tooling).
5. **Firmware-setup-only operations.** `set_secure_boot_mode` MUST
   always return `FAILED` on every host OS with a `detail` that
   explicitly instructs the operator to toggle Secure Boot via
   firmware-setup UI on reboot. It MUST NOT invoke any command.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, regardless of config.
2. **Typed errors.** Query failures MUST raise
   `SecureBootQueryError` carrying the exit code and stderr, except
   that a "Secure Boot not supported by firmware" signal MUST be
   surfaced as `SecureBootState(enabled=False, supported=False, ...)`
   rather than raising.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses, enums, and
exception, each prefixed with the OS name (see §Naming).

### `SecureBootActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or the host OS does not implement the verb. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `SecureBootActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `SecureBootActionStatus` | Outcome category. |
| `slot` | `str \| None` | Key slot affected (`"PK"`, `"KEK"`, `"db"`, `"dbx"`, `"MOK"`), or `None`. |
| `detail` | `str \| None` | Free-form detail: certificate path, fingerprint, or firmware-setup-only message. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `SecureBootState` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | `bool` | Whether Secure Boot is currently enforcing. |
| `supported` | `bool` | Whether the firmware exposes Secure Boot at all. |
| `setup_mode` | `bool` | Whether the firmware is in Secure-Boot-setup mode (no PK enrolled). |
| `audit_mode` | `bool` | Whether the firmware is in audit mode (where supported). |
| `deployed_mode` | `bool` | Whether the firmware is in deployed mode (where supported). |
| `vendor_keys` | `bool` | Whether vendor-provided keys are enrolled. |
| `policy_description` | `str` | OS-specific single-line description of the policy (e.g., Apple's `"Permissive Security"`). |

### `SecureBootPolicy` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `pk_hash` | `str \| None` | Hash of the Platform Key certificate, where available. |
| `kek_hashes` | `list[str]` | Hashes of the Key-Exchange Key certificates. |
| `db_hashes` | `list[str]` | Hashes / SHA256 digests in the allow-list. |
| `dbx_hashes` | `list[str]` | Hashes / SHA256 digests in the deny-list. |
| `mok_hashes` | `list[str]` | MOK list (Linux only; empty elsewhere). |
| `apple_policy_raw` | `str \| None` | Raw `bputil --display` text on macOS; `None` elsewhere. |

### `SecureBootKey` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `slot` | `str` | One of `"PK"`, `"KEK"`, `"db"`, `"dbx"`, `"MOK"`. |
| `fingerprint` | `str` | Key fingerprint / SHA256 digest. |
| `subject` | `str \| None` | Subject DN, where available. |
| `issuer` | `str \| None` | Issuer DN, where available. |

### `SecureBootQueryError` (exception)

Raised from read methods when the underlying query command fails for
a reason other than "Secure Boot not supported".

### `SecureBootManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations are dispatched. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

Implementations MAY extend with OS-specific fields (e.g., the UEFI
package's `override_host_os` for test-time host-OS dispatch).

---

## Key-Slot Mapping

The abstract `slot` parameter maps to the native Secure Boot key
slot concept of each firmware / OS surface:

| OS / Firmware | Native slot surface | Notes |
|---------------|---------------------|-------|
| UEFI on Linux | `PK`, `KEK`, `db`, `dbx` EFI variables + MOK list via `mokutil` | Canonical UEFI slots; MOK is shim's second-stage allow-list. |
| UEFI on macOS | Apple Boot Policy (`bputil`) on Apple Silicon; `csrutil` SIP on Intel | Apple does not expose the UEFI slot model; the contract surfaces state / policy but rejects slot-specific writes. |
| UEFI on Windows | `PK`, `KEK`, `db`, `dbx` via `Get-SecureBootPolicy` | Windows exposes read-only inspection; writes require OEM tooling and MUST return `FAILED`. |

Each OS spec MUST include a Key-Slot-Mapping section stating which
slot surface it reads from and rejecting writes to slots it cannot
manage.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on Linux/macOS hosts; Administrator token on Windows hosts. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>SecureBootManager
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

1. Accept an `ICommandRunner` in their constructor.
2. Never construct their own runner or subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition.

---

## Naming

Concrete types per firmware are prefixed with the Pascal-case name.
No abbreviations.

| Abstract | UEFI | Future Firmware Variants |
|----------|------|--------------------------|
| `SecureBootManager` | `UefiSecureBootManager` | `<Firmware>SecureBootManager` |
| `SecureBootManagerConfig` | `UefiSecureBootManagerConfig` | `<Firmware>SecureBootManagerConfig` |
| `SecureBootActionStatus` | `UefiSecureBootActionStatus` | `<Firmware>SecureBootActionStatus` |
| `SecureBootActionResult` | `UefiSecureBootActionResult` | `<Firmware>SecureBootActionResult` |
| `SecureBootState` | `UefiSecureBootState` | `<Firmware>SecureBootState` |
| `SecureBootPolicy` | `UefiSecureBootPolicy` | `<Firmware>SecureBootPolicy` |
| `SecureBootKey` | `UefiSecureBootKey` | `<Firmware>SecureBootKey` |
| `SecureBootQueryError` | `UefiSecureBootQueryError` | `<Firmware>SecureBootQueryError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `SecureBootActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One test proving `get_secure_boot_state` parses an
   enabled-and-supported output.
2. One test proving `get_secure_boot_state` surfaces
   `supported=False` when the firmware does not expose Secure Boot.
3. One test proving `get_secure_boot_policy` parses the full set of
   slots for the host OS it targets.
4. One idempotency test proving `enroll_mok_key` returns `SKIPPED`
   when the certificate is already enrolled.
5. One test proving `set_secure_boot_mode` ALWAYS returns `FAILED`
   with a firmware-setup-only `detail`, on every host OS.
6. One test proving `enroll_mok_key` and `reset_mok` return `FAILED`
   on unsupported host OSes with a descriptive `detail` (UEFI only).
7. One dry-run test proving the runner is not invoked.
8. One elevation test proving writes pass `elevated=True` and reads
   do not.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Generating MOK / PK / KEK keypairs.
- Signing loaders or shim binaries.
- Measured boot / TPM PCR attestation (separate contract).
- Apple Boot Policy modification via `bputil --mode` (restricted;
  requires Apple Configurator or Recovery).
- Windows OEM PK / KEK / db enrollment workflows.
- Firmware-setup unlock automation.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is host-OS-keyed.** The single
  `UefiSecureBootManager` dispatches via `override_host_os` to
  `mokutil` + `efivar` on Linux (full coverage including MOK
  enrollment), `csrutil` + `bputil` on macOS (Apple Boot Policy
  model — does NOT use the UEFI slot surface), and
  `Confirm-SecureBootUEFI` + `Get-SecureBootPolicy` on Windows
  (read-only). See the README "UEFI managers carry an
  `override_host_os` config field" convention.
- **`set_secure_boot_mode` is always `FAILED`.** Switching to /
  from Setup Mode is firmware-setup-UI-only on every host. The
  verb returns `FAILED` with the stable
  `firmware_setup_ui_only` token (or `DRY_RUN` when
  short-circuited). See the README "FAILED with stable detail
  token" convention and stable-detail-token catalog.
- **macOS and Windows return `FAILED` for MOK writes.**
  `enroll_mok_key` and `reset_mok` return `FAILED` with stable
  tokens of the form `unsupported_on_host_os_<host>` because
  Apple's Boot Policy model and Windows OEM enrollment do not
  expose the MOK slot. `list_enrolled_keys(slot="MOK")` returns
  `[]` on these hosts.
- **File I/O via `ICommandRunner`.** Certificate-path reads for
  `enroll_mok_key`, `efivar` raw variable bytes, and any
  per-host parser inputs route through the runner using `cat`
  and the OS-native equivalents — not a separate
  `IFileOperator`. See the README "Implementation Conventions"
  file-I/O section.
