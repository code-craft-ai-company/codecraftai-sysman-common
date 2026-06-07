# Kernel-Parameters Contract

This is the cross-OS abstract contract for the **kernel-parameters**
feature. Every `codecraftai-sysman-*` package that ships a kernel-
parameter manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-kernel-parameters/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-kernel-parameters/).
It uses `sysctl` at runtime and drop-in files under `/etc/sysctl.d/`
for persistence. This contract generalises the verb set across OSes
with very different kernel-tuning surfaces.

---

## Scope

The kernel-parameters feature provides idempotent, auditable read
and write of named kernel tunables, both at runtime (if supported
by the OS) and persistently. It covers:

- Reading a single parameter's current value.
- Writing a parameter value at runtime, persistently, or both.
- Listing all parameters and their values.
- Reloading persisted parameters into the running kernel.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `KernelParameterManager` class
(the OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_parameter` | `(name: str) → ParameterValue \| None` | Read |
| `set_parameter` | `(name: str, value: str, persistent: bool) → KernelParameterActionResult` | Write |
| `list_parameters` | `() → dict[str, str]` | Read |
| `reload_parameters` | `() → KernelParameterActionResult` | Write |
| `remove_persisted_parameter` | `(name: str) → KernelParameterActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** Before any `set_parameter`, the manager
   MUST read the current runtime value (when `persistent=False` or
   both) and the persisted value (when `persistent=True` or both)
   and compare. Matching state MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner. For file-backed persistence, a
   `diff` field MAY be populated with the unified diff that would
   have been applied.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Persistence + runtime composition.** When `persistent=True` on
   an OS that supports both surfaces, the manager MUST update the
   persistent source and MUST apply the runtime change (via a
   separate runner invocation when needed). When one step fails,
   the result MUST report `FAILED` with a `message` identifying the
   failing step.
5. **Unsupported parameters.** Implementations MAY reject parameters
   that are out of scope for that OS (see §Parameter-Namespace
   Mapping) by returning `FAILED` with a descriptive `message`
   before invoking the runner. Such rejection MUST NOT be silent.
6. **Reboot-required flag.** Where a write persists but does not
   apply until reboot (e.g., Windows registry entries), the result
   MUST set `requires_reboot=True`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner. Some OSes require elevation to read certain parameters;
   those implementations MUST document the exception.
2. **Typed errors.** `list_parameters` failures MAY raise
   `KernelParameterQueryError` or, per the per-OS spec, return an
   empty list with the failure surfaced via logging. `get_parameter`
   MUST return `None` for an unknown name and MAY raise
   `KernelParameterQueryError` for unexpected failures (or return
   `None` per the per-OS spec). See the README "Implementation
   Conventions" graceful-read pattern.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `KernelParameterActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and failed, or the parameter is out of scope. |
| `SKIPPED` | The idempotency guard short-circuited the write. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ParameterValue` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | The dotted parameter name. |
| `value` | `str` | The current string value. |
| `source` | `str \| None` | Where the value was read from (runtime vs a specific drop-in file). |

### `KernelParameterActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `KernelParameterActionStatus` | Outcome category. |
| `name` | `str` | The parameter name. |
| `current_value` | `str \| None` | Value before the action. |
| `applied_value` | `str \| None` | Value after the action (or would-be in `DRY_RUN`). |
| `persistent` | `bool` | Whether the write targeted persistent storage. |
| `requires_reboot` | `bool` | Whether a reboot is required for the change to take effect. |
| `source` | `str \| None` | The drop-in file or registry key modified. |
| `diff` | `str \| None` | Unified diff for `DRY_RUN` file writes. |
| `message` | `str \| None` | Human-readable detail for `SKIPPED`, `FAILED`, or unsupported-parameter cases. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `KernelParameterQueryError` | `list_parameters` or an unexpected `get_parameter` failure. |

### `KernelParameterManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |
| `persist_dir` | `str \| None` | OS-default | Drop-in directory (or registry key root) for persistence. |

---

## Parameter-Namespace Mapping

The abstract parameter name maps to each OS's native tunable
namespace.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `sysctl` key (e.g., `vm.swappiness`) with drop-ins under `/etc/sysctl.d/` | Canonical. |
| Ubuntu | `sysctl` key with drop-ins under `/etc/sysctl.d/` | Same shape as RHEL. |
| macOS | `sysctl` key (BSD-style; e.g., `net.inet.ip.forwarding`) with persistence in `/etc/sysctl.conf` or launchd plist | The spec MUST state the persistence target. |
| Windows | Registry values under `HKLM\SYSTEM\CurrentControlSet\Services\<Service>\Parameters` and `HKLM\SYSTEM\CurrentControlSet\Control\...`. Windows has no `sysctl` equivalent — `set_parameter` maps to registry writes. | Many writes set `requires_reboot=True`. Implementations MAY reject parameters outside a documented allowlist as out-of-scope, returning `FAILED` with a descriptive `message`. |
| UEFI | N/A | UEFI has no runtime kernel-parameter concept. The kernel-parameters contract does not apply. |

Each OS spec MUST include a Parameter-Namespace section defining
the allowlist of parameters it accepts and explicitly documenting
unsupported parameter prefixes.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True` (see note below). |
| Config `elevated=False` | Never pass `elevated=True`. |
| Read-elevation exceptions | Some parameters (e.g., hardened `sysctl` keys, Windows protected registry hives) may require elevation to read. OS specs MUST document any such read that must bypass the "reads never elevate" rule, and SHOULD offer an explicit `elevated_reads=True` extension rather than silently elevating. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>KernelParameterManager
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

1. Accept an `ICommandRunner` and a `KernelParameterManagerConfig`
   in their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `KernelParameterManager` | `UbuntuKernelParameterManager` | `MacosKernelParameterManager` | `WindowsKernelParameterManager` | `KernelParamManager` |
| `KernelParameterManagerConfig` | `UbuntuKernelParameterManagerConfig` | `MacosKernelParameterManagerConfig` | `WindowsKernelParameterManagerConfig` | `KernelManagerConfig` |
| `KernelParameterActionStatus` | `UbuntuKernelParameterActionStatus` | `MacosKernelParameterActionStatus` | `WindowsKernelParameterActionStatus` | `KernelParamActionStatus` |
| `KernelParameterActionResult` | `UbuntuKernelParameterActionResult` | `MacosKernelParameterActionResult` | `WindowsKernelParameterActionResult` | `KernelParamActionResult` |
| `ParameterValue` | `UbuntuParameterValue` | `MacosParameterValue` | `WindowsParameterValue` | `KernelParamInfo` |
| `KernelParameterQueryError` | `UbuntuKernelParameterQueryError` | `MacosKernelParameterQueryError` | `WindowsKernelParameterQueryError` | `KernelParamQueryError` |

The RHEL package keeps its historical short names (`KernelParamManager`,
`KernelParamInfo`) for backwards compatibility; new OS packages use
the fully qualified names above.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `KernelParameterActionResult` sequence when
  driven by a real runner with aspects attached, modulo
  retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb, covering runtime,
   persistent, and combined modes.
2. One idempotency test per mode proving `SKIPPED` when current
   value matches desired.
3. One rejection test proving an out-of-scope parameter returns
   `FAILED` without invoking the runner.
4. One `get_parameter` test for a known parameter and a missing
   parameter.
5. One `list_parameters` parser test covering representative output.
6. One `reload_parameters` test proving correct command
   construction.
7. One dry-run test per write verb proving the runner is not
   invoked.
8. One `requires_reboot` test (if the OS has that concept) proving
   the flag is set for the correct subset of parameters.
9. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Kernel module load/unload (managed separately; the RHEL reference
  hosts a `KernelModuleManager` alongside `KernelParamManager`).
- Boot-time parameter editing (grub, `bcdedit`, EFI boot-loader
  variables).
- Per-cgroup or per-namespace tunables.
- Runtime-only writes with no persistence path.
- Parameter discovery / introspection metadata (type, range, default).
- Mass-apply from a structured policy document (YAML / TOML).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`requires_reboot: bool`.** Windows kernel-parameter writes
  via `bcdedit /set` require a reboot to take effect; the
  `WindowsKernelParameterActionResult` carries
  `requires_reboot: bool = False`. Ubuntu's `sysctl -w` is
  immediate; persistent writes via `/etc/sysctl.d/*` are
  applied on next boot or via `sysctl --system`. See the
  README reboot-signaling convention.
- **`detail="parameter_not_supported"`.** When a verb names a
  parameter that exists on Linux but has no analog on macOS
  / Windows, the manager returns `FAILED` with this stable
  detail token. See the README stable-token catalog.
- **File I/O via `ICommandRunner`.** `/etc/sysctl.d/*.conf` and
  registry / BCD writes route through the runner.
