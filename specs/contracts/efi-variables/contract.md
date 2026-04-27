# EFI-Variables Contract

This is the cross-OS abstract contract for the **efi-variables**
feature. Every `automojo-sysman-*` package that ships an EFI
variable manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-uefi/specs/3-efi-variables/`](../../../../../automojo-sysman-uefi/specs/3-efi-variables/).
It reads, writes, deletes, and enumerates EFI NVRAM variables
through `efivar` and the `/sys/firmware/efi/efivars` filesystem on
Linux hosts, through `nvram` on macOS hosts, and through the
PowerShell `Uefi` module / `[UEFI]::GetVariable(...)` API on Windows
hosts — all dispatched through an `ICommandRunner`. This contract
generalises that shape so that any firmware-variable surface (not
only UEFI NVRAM) could implement it.

This contract borrows its scope-concept framing from the
[configuration-management contract](../configuration-management/contract.md):
an EFI variable is a discrete setting within a namespace (the
variable-owning GUID), not a free-form file. Consumers that want to
manage whole ESP files should instead use the
[filesystem-management contract](../filesystem-management/contract.md)
or the esp-management contract.

---

## Scope

The efi-variables feature provides idempotent, auditable access to
raw firmware NVRAM variables. It covers:

- Reading a variable by `(namespace, name)`.
- Writing a variable, including its value bytes and attribute flags.
- Deleting a variable.
- Listing variables in a namespace, or across all namespaces.
- Applying elevation for writes, not for reads.
- Supporting dry-run mode.

The feature is executed exclusively through an `ICommandRunner`.
No direct `subprocess`, no direct NVRAM I/O.

---

## Verbs

Every OS implementation MUST expose a `VariableManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_variable` | `(name: str, namespace: str) → Variable` | Read |
| `set_variable` | `(name: str, value: bytes, namespace: str, attributes: int) → VariableActionResult` | Write |
| `delete_variable` | `(name: str, namespace: str) → VariableActionResult` | Write |
| `list_variables` | `(namespace: str \| None) → list[Variable]` | Read |

**Writes** apply elevation per §Elevation and return
`VariableActionResult`. **Reads** never elevate and return a
`Variable` / `list[Variable]`, or raise `VariableQueryError`.

### Method-level invariants (writes)

1. **Idempotency guard.** Before calling `set_variable`, the
   implementation MUST first call `get_variable` and compare the
   current value bytes and attributes to the desired value and
   attributes. A matching state MUST return `SKIPPED`. Before
   calling `delete_variable`, the implementation MUST first call
   `get_variable`; when the variable does not exist, the method MUST
   return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` with `exit_code`, `stdout`, `stderr`, and `command`
   populated. Writes do NOT raise for routine failures.
4. **Attribute preservation.** When `set_variable` is called to
   change only the value bytes, the implementation MUST preserve the
   current variable's attributes unless the caller explicitly passes
   a new attribute bitmap.
5. **Immutability flag.** On Linux hosts where the efivars
   filesystem exposes an immutable attribute, `delete_variable` and
   `set_variable` on pre-existing variables MUST clear the immutable
   flag (`chattr -i`) before writing, then (for `set_variable` only)
   restore it afterwards.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, regardless of config.
2. **Typed errors.** `get_variable` MUST raise
   `VariableNotFoundError` when the variable does not exist in the
   namespace. Other query failures MAY raise `VariableQueryError`
   or, per the per-OS spec, return an empty list / synthetic
   record. See the README "Implementation Conventions" graceful-
   read pattern.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses, enum, and
exception hierarchy, each prefixed with the OS name (see §Naming).

### `VariableActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or the host OS does not implement the verb. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `VariableActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `VariableActionStatus` | Outcome category. |
| `namespace` | `str` | The variable namespace (GUID or friendly alias). |
| `name` | `str` | The variable name. |
| `detail` | `str \| None` | Free-form detail (e.g., `"attributes=0x07"`, `"immutable flag cleared"`). |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `Variable` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `namespace` | `str` | Variable namespace GUID (or host-OS alias). |
| `name` | `str` | Variable name. |
| `value` | `bytes` | Raw value bytes. |
| `attributes` | `int` | Variable attribute bitmap (e.g., `0x07` for NV + BS + RT). |
| `size_bytes` | `int` | Size of the value in bytes. |

### Well-Known Attribute Bits

| Bit | Name | Meaning |
|-----|------|---------|
| `0x01` | `NON_VOLATILE` | Persists across reboots. |
| `0x02` | `BOOTSERVICE_ACCESS` | Accessible to boot-service code. |
| `0x04` | `RUNTIME_ACCESS` | Accessible to runtime-service code. |
| `0x08` | `HARDWARE_ERROR_RECORD` | Reserved for hardware error records. |
| `0x10` | `AUTHENTICATED_WRITE_ACCESS` | Legacy authenticated write. |
| `0x20` | `TIME_BASED_AUTHENTICATED_WRITE_ACCESS` | Signed time-based authenticated write. |
| `0x40` | `APPEND_WRITE` | Append-on-write. |

Implementations MAY expose these as an IntEnum or constants module;
the contract mandates only that they honor these bit values when
round-tripping attributes through `Variable.attributes`.

### `VariableManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations are dispatched. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

Implementations MAY extend with OS-specific fields (e.g., the UEFI
package's `override_host_os` for host-OS dispatch testability).

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `VariableNotFoundError` | `get_variable` targets a variable that does not exist. |
| `VariableQueryError` | Any other read failure. |
| `VariableNamespaceError` | A write or read targets a namespace the host OS cannot access (e.g., Apple-reserved namespaces from Linux). |

---

## Namespace Mapping

The abstract `namespace` parameter maps to the native variable-
owning-GUID concept of each firmware / OS surface. This is the
"scope concept" for this contract, analogous to the configuration
source in the configuration-management contract.

| OS / Firmware | Native concept | Common well-known values |
|---------------|----------------|--------------------------|
| UEFI on Linux | `GUID` (e.g., `8be4df61-93ca-11d2-aa0d-00e098032b8c`) | `EFI_GLOBAL_VARIABLE` = `8be4df61-93ca-11d2-aa0d-00e098032b8c` |
| UEFI on macOS | Friendly alias (e.g., `Apple`, `Common`) or full GUID | macOS `nvram` allows both `<alias>:<name>` and raw GUID forms. |
| UEFI on Windows | GUID string (same canonical form as Linux) | Same set of EFI globals as Linux; Microsoft-specific GUIDs exist for BCD variables. |

Each OS spec MUST include a Namespace-Mapping section stating:

- The canonical string form the spec accepts in the `namespace`
  parameter.
- Any friendly aliases the spec accepts (e.g., `EFI_GLOBAL_VARIABLE`
  for `8be4df61-93ca-11d2-aa0d-00e098032b8c`).
- Which namespaces raise `VariableNamespaceError` on the given host
  OS (Apple-reserved namespaces on Linux, for example).

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on Linux/macOS hosts; Administrator token / UAC on Windows hosts. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>VariableManager
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
| `VariableManager` | `UefiVariableManager` | `<Firmware>VariableManager` |
| `VariableManagerConfig` | `UefiVariableManagerConfig` | `<Firmware>VariableManagerConfig` |
| `VariableActionStatus` | `UefiVariableActionStatus` | `<Firmware>VariableActionStatus` |
| `VariableActionResult` | `UefiVariableActionResult` | `<Firmware>VariableActionResult` |
| `Variable` | `UefiVariable` | `<Firmware>Variable` |
| `VariableQueryError` | `UefiVariableQueryError` | `<Firmware>VariableQueryError` |
| `VariableNotFoundError` | `UefiVariableNotFoundError` | `<Firmware>VariableNotFoundError` |
| `VariableNamespaceError` | `UefiVariableNamespaceError` | `<Firmware>VariableNamespaceError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `VariableActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test for `set_variable` covering a
   multi-byte value and a non-default attribute bitmap.
2. One command-construction test for `delete_variable`.
3. One command-construction test for `get_variable`.
4. One idempotency test for `set_variable` proving `SKIPPED` when
   the current value and attributes already match.
5. One idempotency test for `delete_variable` proving `SKIPPED`
   when the variable does not exist.
6. One dry-run test for each write verb.
7. One parser test for `list_variables` covering a realistic
   multi-variable output block.
8. One `VariableNotFoundError` test for `get_variable` on a missing
   variable.
9. One elevation test proving writes pass `elevated=True` and reads
   do not.
10. One `VariableNamespaceError` test proving unsupported
    namespaces raise without invoking the runner (UEFI only).

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Signed variable authoring (`TIME_BASED_AUTHENTICATED_WRITE_ACCESS`
  signing workflows). Implementations MAY surface this by accepting
  pre-signed blobs but are not required to produce them.
- Audit-log generation of variable changes beyond what
  `PersistenceAspect` already records.
- GUID-alias registry authoring (adding a new friendly alias at
  runtime).
- Variable-capsule-based updates (covered by capsule-update).
- Legacy BIOS CMOS settings — this contract is firmware-variable-
  oriented only.

---

## Implementation Drift

The UEFI implementation surfaced these intentional deviations from
the contract.

- **`override_host_os` config field.** `UefiEfiVariableManagerConfig`
  carries `override_host_os: str | None = None` so the manager
  can drive `efivar` (Linux), `nvram` (macOS), and `bcdedit /enum`
  / Windows-Runtime-Services backends from a single host. See the
  README UEFI conventions.
- **Stable detail token `firmware_setup_ui_only`.** Some variables
  (vendor-specific BIOS settings) are read-only from the OS and
  require firmware-setup UI to mutate; the manager returns
  `FAILED` with a stable detail token rather than attempting the
  write. See the README stable-token catalog.
- **OS-prefixed naming.** All concrete types use the `Uefi`
  prefix.
