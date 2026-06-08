# Boot-Management Contract

This is the cross-OS abstract contract for the **boot-management**
feature. Every `codecraftai-sysman-*` package that ships a boot manager
MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-uefi/specs/3-boot-management/`](../../../../../codecraftai-sysman-uefi/specs/3-boot-management/).
It manages UEFI boot entries and boot order using `efibootmgr` on
Linux hosts, `bless` and `nvram` on macOS hosts, and `bcdedit` on
Windows hosts, all through an `ICommandRunner`. This contract
generalises that shape so that a non-UEFI package (e.g., a future
SBC / coreboot package) could also implement it without retooling
the caller.

---

## Scope

The boot-management feature provides idempotent, auditable control
over a host's firmware boot entries and boot order. It covers:

- Listing all firmware boot entries.
- Retrieving a single boot entry by its identifier.
- Creating a new boot entry that points at a loader on a named
  device and partition.
- Deleting a boot entry by identifier.
- Reading the current persistent boot order.
- Writing a new persistent boot order.
- Reading and writing the one-shot `BootNext` value.
- Reading the `BootCurrent` value (the entry used for the current
  boot).
- Applying elevation for writes, not for reads.
- Supporting dry-run mode that short-circuits all mutations without
  contacting the firmware.

The feature is executed exclusively through an `ICommandRunner` from
`codecraftai-interfaces`. No direct `subprocess`, no direct NVRAM
writes, no direct firmware-variable access.

---

## Verbs

Every OS implementation MUST expose a `BootManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_boot_entries` | `() → list[BootEntryInfo]` | Read |
| `get_boot_entry` | `(entry_id: str) → BootEntryInfo` | Read |
| `create_boot_entry` | `(spec: BootEntrySpec) → BootActionResult` | Write |
| `delete_boot_entry` | `(entry_id: str) → BootActionResult` | Write |
| `get_boot_order` | `() → list[str]` | Read |
| `set_boot_order` | `(order: list[str]) → BootActionResult` | Write |
| `get_boot_next` | `() → str \| None` | Read |
| `set_boot_next` | `(entry_id: str) → BootActionResult` | Write |
| `get_boot_current` | `() → str` | Read |

**Writes** apply elevation per §Elevation and return
`BootActionResult`. **Reads** never elevate and return the specified
query dataclass / value, or raise `BootQueryError`.

### Method-level invariants (writes)

1. **Idempotency guard.** Before invoking any mutating command, the
   implementation calls its internal state-query method and compares
   the desired state to the current state. If the desired state is
   already in effect, the method MUST return a result with status
   `SKIPPED` and MUST NOT invoke the write command. For
   `create_boot_entry`, "already in effect" means an entry with the
   same label and loader path already exists. For `set_boot_order`,
   it means the current boot order equals the requested order.
2. **Dry-run short-circuit.** If the manager is configured with
   `dry_run=True`, writes MUST NOT invoke the command runner and MUST
   return a result with status `DRY_RUN`. The `command` field MAY be
   populated.
3. **Error surface.** Non-zero runner exit codes MUST return
   `FAILED` populated with `exit_code`, `stdout`, and `stderr`.
   Writes do NOT raise for routine failures.
4. **Unsupported host OS.** When the host OS has no real
   implementation for a verb (e.g., `set_boot_order` on macOS), the
   method MUST return `FAILED` with a descriptive `detail` rather
   than silently no-oping or raising.
5. **Persistence.** Writes operate on the persistent firmware
   variables (`BootOrder`, `Boot<XXXX>`). Runtime-only overrides are
   out of scope for the base contract.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner, regardless of config.
2. **Typed errors.** `get_boot_entry(entry_id)` MUST raise
   `BootQueryError` when the entry does not exist. Other read
   failures MAY raise `BootQueryError` carrying the exit code and
   stderr, OR (per the per-OS spec) return an empty list / synthetic
   `BootEntryInfo(...)` record so callers can proceed without a
   try/except wrapper. See the README "Implementation Conventions"
   graceful-read pattern.
3. **Pure parsing.** All output parsing is Python-only and does not
   require the underlying tool to be installed on the host running
   the parser's unit tests.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum, each
prefixed with the OS name (see §Naming).

### `BootActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or the host OS does not implement the verb. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `BootActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `BootActionStatus` | Outcome category. |
| `entry_id` | `str \| None` | The boot entry identifier the action targeted (4-hex on UEFI spec Linux; GUID on Windows; opaque string on macOS). |
| `detail` | `str \| None` | Free-form identifier: label, loader path, or ordered-id list summary. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `BootEntryInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | `str` | Firmware boot-entry identifier. |
| `label` | `str` | Human-readable entry label (`"ubuntu"`, `"Windows Boot Manager"`). |
| `loader_path` | `str` | Path to the loader on the ESP (e.g., `\EFI\ubuntu\shimx64.efi`). |
| `device` | `str \| None` | Backing device identifier, where available. |
| `partition` | `int \| None` | Partition number, where available. |
| `is_active` | `bool` | Whether the entry is marked active. |
| `is_current` | `bool` | Whether this entry matches `BootCurrent`. |

### `BootEntrySpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `label` | `str` | Label to assign to the new entry. |
| `device` | `str` | Device containing the ESP. |
| `partition` | `int` | Partition number of the ESP. |
| `loader_path` | `str` | Loader path on the ESP. |
| `description` | `str \| None` | Optional human-readable description. |

### `BootQueryError` (exception)

Raised from read methods when the underlying query command fails, or
when `get_boot_entry` targets a non-existent entry.

### `BootManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations are dispatched. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

Implementations MAY extend with OS-specific fields (e.g., an
`override_host_os` field for the UEFI package's host-OS dispatch
testability) but MUST preserve these two fields with these names and
defaults.

---

## Boot-Entry-ID Mapping

The abstract `entry_id` parameter maps to the native boot-entry
identifier of each firmware / OS surface:

| OS / Firmware | Native concept | Notes |
|---------------|----------------|-------|
| UEFI on Linux | 4-hex-digit `Boot<XXXX>` variable suffix (e.g., `"0001"`) | Canonical UEFI form. |
| UEFI on macOS | Opaque label string from `bless --info` | macOS does not expose the raw 4-hex ID through user-space tooling. |
| UEFI on Windows | GUID string (`{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}`) | `bcdedit` uses GUIDs as handles. |
| Non-UEFI firmware (future) | Firmware-specific | Each per-firmware spec MUST state its ID format. |

Each OS spec MUST include an Entry-ID-Mapping section that states
its chosen format and any canonicalisation applied when comparing
identifiers.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the command runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`, regardless of verb. |
| OS elevation mechanism | `sudo` on Linux/macOS hosts; Administrator token / UAC on Windows hosts. The command runner handles the mechanism. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>BootManager
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
3. Never hold state across method calls beyond the runner and the
   config. Boot state is re-queried per write.
4. Be safe to invoke under any aspect composition configured on the
   runner.

---

## Naming

Concrete types per OS / firmware are prefixed with the Pascal-case
name. No abbreviations.

| Abstract | UEFI | Future OS-Specific Variants |
|----------|------|-----------------------------|
| `BootManager` | `UefiBootManager` | `<Firmware>BootManager` |
| `BootManagerConfig` | `UefiBootManagerConfig` | `<Firmware>BootManagerConfig` |
| `BootActionStatus` | `UefiBootActionStatus` | `<Firmware>BootActionStatus` |
| `BootActionResult` | `UefiBootActionResult` | `<Firmware>BootActionResult` |
| `BootEntryInfo` | `UefiBootEntryInfo` | `<Firmware>BootEntryInfo` |
| `BootEntrySpec` | `UefiBootEntrySpec` | `<Firmware>BootEntrySpec` |
| `BootQueryError` | `UefiBootQueryError` | `<Firmware>BootQueryError` |

The UEFI package is the reference implementation and uses the
`Uefi` prefix. When future firmware packages adopt this contract
they use their own firmware-family prefix to avoid alias collisions
in a multi-firmware coordinator.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager that was tested with a `MockCommandRunner` with no
  aspects MUST produce the same `BootActionResult` sequence when
  driven by a runner with `PersistenceAspect`, `RetryAspect`, and
  `TimeoutAspect` attached, modulo runner-level timing and retries.
- Retry aspects that translate transient non-zero exits into
  successes are permitted to change `status` from `FAILED` to
  `SUCCESS`; all other field semantics are unchanged.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One test per write verb proving command construction is correct.
2. One idempotency test per write verb proving `SKIPPED` is returned
   when the desired state is already in effect.
3. One dry-run test per write verb proving the runner is not invoked.
4. One parser test per read verb covering a realistic multi-entry
   output block.
5. One test per write verb proving that on unsupported host OSes the
   method returns `FAILED` with a descriptive `detail` (UEFI only).
6. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Signing, measuring, or attesting loaders before registering them.
- Editing individual load-option attributes other than label, device,
  partition, and loader path.
- Legacy-BIOS boot entries (CSM).
- Recovery-partition-specific boot flow (e.g., macOS Recovery, WinRE).
- PXE / HTTP boot option authoring.
- `Timeout` / `BootOptionSupport` variable authoring.

---

## Implementation Drift

The UEFI implementation surfaced these intentional deviations from
the contract.

- **`override_host_os` config field.** `UefiBootManagerConfig` carries
  `override_host_os: str | None = None` so the manager can be driven
  through the `efibootmgr` (Linux) / `bcdedit` (Windows) backends
  on a single host without spinning up a VM per backend. See the
  README "Implementation Conventions" UEFI conventions.
- **OS-prefixed naming.** All concrete types use the `Uefi` prefix
  (`UefiBootManager`, `UefiBootEntryInfo`, `UefiBootActionResult`).
- **`BootEntryInfo` vs `BootEntrySpec` split.** Implementation distinguishes
  parsed read shapes (`UefiBootEntryInfo` with parsed
  `device_path` / `loader_path`) from caller-supplied write shapes
  (`UefiBootEntrySpec` with raw input device / loader strings).
- **File I/O via `ICommandRunner`.** All EFI variable reads/writes
  route through the runner; no `IFileOperator` is used.
