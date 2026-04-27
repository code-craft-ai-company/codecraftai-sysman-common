# Virtualization-Management Contract

This is the cross-OS abstract contract for the
**virtualization-management** feature. Every `automojo-sysman-*`
package that ships a virtualization manager MUST honor this
contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-virtualization-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-virtualization-management/).
It uses KVM / libvirt through `virsh` and `virt-install` against
an `ICommandRunner`. This contract generalises the verb set for
macOS (HyperKit / Apple Virtualization framework, and
QEMU / libvirt via Homebrew) and Windows (Hyper-V PowerShell
module: `New-VM`, `Start-VM`, `Stop-VM`, `Remove-VM`,
`Checkpoint-VM`, `Restore-VMSnapshot`).

---

## Scope

The virtualization-management feature provides idempotent,
auditable control over a host's local hypervisor-managed VMs. It
covers:

- Listing VMs.
- Creating, deleting, starting, stopping, pausing, and resuming
  VMs.
- Querying a VM's information.
- Attaching and detaching disks.
- Creating, restoring, and listing VM snapshots.
- Dry-run-aware writes.
- Elevation for writes (host-level hypervisor operations); reads
  never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `VirtualizationManager`
class (the OS-prefixed variant — see §Naming) whose public
surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_vms` | `() → list[VmInfo]` | Read |
| `create_vm` | `(spec: VmSpec) → VmActionResult` | Write |
| `delete_vm` | `(name: str) → VmActionResult` | Write |
| `start_vm` | `(name: str) → VmActionResult` | Write |
| `stop_vm` | `(name: str, force: bool) → VmActionResult` | Write |
| `pause_vm` | `(name: str) → VmActionResult` | Write |
| `resume_vm` | `(name: str) → VmActionResult` | Write |
| `get_vm_info` | `(name: str) → VmInfo \| None` | Read |
| `attach_disk` | `(vm: str, spec: VmDiskSpec) → VmActionResult` | Write |
| `detach_disk` | `(vm: str, disk_id: str) → VmActionResult` | Write |
| `snapshot_vm` | `(vm: str, snapshot_name: str) → VmActionResult` | Write |
| `restore_snapshot` | `(vm: str, snapshot_name: str) → VmActionResult` | Write |
| `list_snapshots` | `(vm: str) → list[VmSnapshot]` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_vm` MUST return `SKIPPED` when
   a VM with the same `name` and identical rendered spec exists.
   `delete_vm` MUST return `SKIPPED` when no such VM exists.
   `start_vm` / `stop_vm` / `pause_vm` / `resume_vm` MUST return
   `SKIPPED` when the VM is already in the requested power state.
   `attach_disk` MUST return `SKIPPED` when the disk spec is
   already attached; `detach_disk` MUST return `SKIPPED` when the
   disk id is not attached. `snapshot_vm` MUST return `SKIPPED`
   when a snapshot with the same name already exists.
   `restore_snapshot` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Stop vs force-stop.** `stop_vm(force=False)` MUST issue a
   graceful shutdown; `stop_vm(force=True)` MUST issue a hard
   power-off (`virsh destroy`, `Stop-VM -TurnOff`, equivalents).
5. **Data-loss advisory.** `delete_vm`, `detach_disk`, and
   `restore_snapshot` MUST populate `detail` on `SUCCESS` with a
   data-loss advisory so the coordinator can surface it.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_vms` / `list_snapshots` MUST raise
   `VirtualizationQueryError` for unexpected failures.
   `get_vm_info` MUST return `None` for an unknown VM.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `VmActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `VmPowerState` (enum)

| Value | Meaning |
|-------|---------|
| `RUNNING` | VM is powered on and executing. |
| `STOPPED` | VM is powered off. |
| `PAUSED` | VM is paused / suspended-to-memory. |
| `SAVED` | VM is suspended-to-disk (where supported). |
| `UNKNOWN` | Power state could not be determined. |

### `VmSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | VM name. |
| `cpu_count` | `int` | Number of vCPUs. |
| `memory_bytes` | `int` | Allocated memory in bytes. |
| `disks` | `list[VmDiskSpec]` | Disks to attach at creation. |
| `network_interfaces` | `list[str]` | Native network-interface selectors (bridge names, switch names). |
| `os_template` | `str \| None` | Native OS / guest template identifier. |
| `boot_image` | `str \| None` | Path to the installation ISO or boot image. |
| `options` | `dict[str, str]` | OS-specific extra options. |

### `VmDiskSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `disk_id` | `str` | Caller-chosen disk identifier (file path or label). |
| `size_bytes` | `int \| None` | Disk size when creating a new disk. `None` means existing disk. |
| `source_path` | `str \| None` | Path to an existing disk image to attach. |
| `bus` | `str \| None` | Native bus selector (`"virtio"`, `"sata"`, `"scsi"`). |
| `readonly` | `bool` | Whether the attachment is read-only. |

### `VmInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | VM name. |
| `uuid` | `str \| None` | Hypervisor-assigned UUID. |
| `power_state` | `VmPowerState` | Current power state. |
| `cpu_count` | `int` | Configured vCPUs. |
| `memory_bytes` | `int` | Configured memory. |
| `disks` | `list[VmDiskSpec]` | Currently attached disks. |
| `network_interfaces` | `list[str]` | Currently attached NIC selectors. |

### `VmSnapshot` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Snapshot name. |
| `created_at` | `datetime \| None` | Creation time, UTC. |
| `parent` | `str \| None` | Parent snapshot name, if any. |
| `current` | `bool` | Whether this snapshot is the current one. |

### `VmActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `VmActionStatus` | Outcome category. |
| `vm_name` | `str \| None` | The VM targeted. |
| `detail` | `str \| None` | Human-readable explanation or data-loss advisory. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `VirtualizationQueryError` | A read fails for a reason other than "VM unknown". |

### `VirtualizationManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |
| `backend` | `str \| None` | `None` | Optional explicit backend selector (e.g., `"kvm"`, `"hyperkit"`, `"apple-vz"`, `"hyper-v"`). Implementations MAY default based on host detection. |

---

## Hypervisor Mapping

The abstract `(backend, name)` pair maps to each OS's native
hypervisor surface.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | KVM + libvirt (`virsh`, `virt-install`) | Canonical. VM name is the libvirt domain name. |
| Ubuntu | Same as RHEL (KVM + libvirt) | — |
| macOS | Apple Virtualization framework or HyperKit; optionally QEMU / libvirt via Homebrew | The macOS spec MUST document the default backend and any backend-specific verb gaps. Snapshots are supported only on certain backends. |
| Windows | Hyper-V (PowerShell `Hyper-V` module: `New-VM`, `Start-VM`, `Stop-VM`, `Remove-VM`, `Checkpoint-VM`, `Restore-VMSnapshot`) | Requires the Hyper-V role. WSL2 is a separate concern and does NOT satisfy this contract. |
| UEFI | N/A | UEFI has no VM concept. The virtualization-management contract does not apply. |

Each OS spec MUST include a Hypervisor-Mapping section stating
its default backend, backend-selection logic, and any verb gaps
per backend (e.g., snapshot support).

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True` by default. Some hypervisor reads require membership in a privileged group; the OS spec MAY document per-read exceptions. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` + libvirt group membership on RHEL / Ubuntu / macOS; Administrator token / UAC + Hyper-V Administrators on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>VirtualizationManager
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
   `VirtualizationManagerConfig` in their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `VirtualizationManager` | `UbuntuVirtualizationManager` | `MacosVirtualizationManager` | `WindowsVirtualizationManager` | `VirtualizationManager` |
| `VirtualizationManagerConfig` | `UbuntuVirtualizationManagerConfig` | `MacosVirtualizationManagerConfig` | `WindowsVirtualizationManagerConfig` | `VirtualizationManagerConfig` |
| `VmActionStatus` | `UbuntuVmActionStatus` | `MacosVmActionStatus` | `WindowsVmActionStatus` | `VmActionStatus` |
| `VmActionResult` | `UbuntuVmActionResult` | `MacosVmActionResult` | `WindowsVmActionResult` | `VmActionResult` |
| `VmPowerState` | `UbuntuVmPowerState` | `MacosVmPowerState` | `WindowsVmPowerState` | `DomainState` |
| `VmSpec` | `UbuntuVmSpec` | `MacosVmSpec` | `WindowsVmSpec` | `DomainSpec` |
| `VmDiskSpec` | `UbuntuVmDiskSpec` | `MacosVmDiskSpec` | `WindowsVmDiskSpec` | `DiskSpec` |
| `VmInfo` | `UbuntuVmInfo` | `MacosVmInfo` | `WindowsVmInfo` | `DomainInfo` |
| `VmSnapshot` | `UbuntuVmSnapshot` | `MacosVmSnapshot` | `WindowsVmSnapshot` | `DomainSnapshot` |
| `VirtualizationQueryError` | `UbuntuVirtualizationQueryError` | `MacosVirtualizationQueryError` | `WindowsVirtualizationQueryError` | `VirtualizationQueryError` |

The RHEL reference uses libvirt-flavoured names (`Domain*`); new
OS packages use the abstract `Vm*` names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `VmActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state (including per-power-state idempotency for
   `start_vm` / `stop_vm` / `pause_vm` / `resume_vm`).
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_vms` parser test covering multiple VMs in different
   power states.
5. One `get_vm_info` test for a known and an unknown VM.
6. One `attach_disk` / `detach_disk` round-trip construction
   test.
7. One `snapshot_vm` / `restore_snapshot` / `list_snapshots`
   round-trip construction test.
8. One `stop_vm(force=True)` vs `stop_vm(force=False)` command
   distinction test.
9. One data-loss-advisory test proving `detail` is populated on
   `delete_vm`, `detach_disk`, and `restore_snapshot`.
10. One elevation test proving writes pass `elevated=True` and
    reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- VM live migration between hosts.
- Virtual network / virtual switch creation and management.
- Storage-pool creation for VM disks beyond attaching an
  existing path.
- Guest agent installation and RPC.
- Console / VNC / SPICE session management.
- Cloning VMs beyond snapshot-and-restore.
- Template / OVA / OVF import and export.
- WSL2 distribution management (a distinct feature area).
- Container engines (`podman`, `docker`) — live in
  `container-management`.
- Nested virtualization enablement.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is structural.** Ubuntu wraps libvirt
  via `virsh` against KVM/QEMU. macOS wraps libvirt via
  Homebrew-installed `libvirtd` over QEMU on Hypervisor.framework
  (Apple's `Virtualization.framework` is explicitly out of
  scope — Swift-only). Windows wraps the Hyper-V PowerShell
  module (`Get-VM` / `New-VM` / `Start-VM` / `Stop-VM` /
  `Suspend-VM` / `Resume-VM` / `Checkpoint-VM` /
  `Add-VMHardDiskDrive`). Per-OS `<Os>VirtBackend` enums name
  the realisable values; see the README "Per-OS backend enums"
  convention.
- **HyperKit is deprecated and short-circuits.** The macOS
  `MacosVirtBackend.HYPERKIT` selector is recognised for
  cross-OS shape parity but every verb returns `FAILED` with
  the stable `hyperkit_deprecated` token. See the README
  "FAILED with stable detail token" convention and
  stable-detail-token catalog.
- **Hyper-V Generation matters and changes the verb argv.**
  Hyper-V VMs are either Generation 1 (BIOS) or Generation 2
  (UEFI), and the choice ripples through `New-VM -Generation`,
  boot-order semantics, and disk-attach controller types. The
  contract treats Generation as part of the Windows-prefixed
  spec dataclass. The `Set-VMProcessor` follow-up is invoked in
  the same PowerShell scriptblock as `New-VM` so vCPU count
  applies atomically.
- **File I/O via `ICommandRunner`.** libvirt domain XML edits,
  Hyper-V `Export-VM` / `Import-VM` paths, and snapshot metadata
  reads route through the runner using `cat` / `tee` /
  `Get-Content` / `Set-Content` rather than a separate
  `IFileOperator`. See the README "Implementation Conventions"
  file-I/O section.
- **Windows `elevation_blocked: bool`.** Every Hyper-V cmdlet
  requires the Hyper-V Administrators group. Writes surface the
  structured Windows elevation extension when the calling
  process lacks the membership. See the README "Implementation
  Conventions" elevation-blocked entry.
