# Hardware-Inventory Contract

This is the cross-OS abstract contract for the
**hardware-inventory** feature. Every `codecraftai-sysman-*`
package that ships a hardware-inventory manager MUST honor this
contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-hardware-inventory/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-hardware-inventory/).
It wraps `dmidecode`, `lscpu`, `lsmem`, `lsblk`, `lspci`,
`lsusb`, and sysfs reads through an `ICommandRunner` (and MAY
use an `IFileOperator` where available; the established pattern
is to route file I/O through `ICommandRunner` — see the README
"Implementation Conventions"). This contract generalises the verb set for OSes
whose inventory surface is `lshw` / `lspci` / `lsusb` / sysfs
(Linux), `system_profiler` / `sysctl hw.*` / `ioreg` (macOS), or
WMI / `Get-ComputerInfo` / `Get-CimInstance` (Windows).

**This feature is strictly read-only.** Every verb is inherently
idempotent and safe to repeat. There is **no `DRY_RUN` status**
and **no `dry_run` field** on the manager config. A read-only
feature needs no short-circuit.

---

## Scope

The hardware-inventory feature provides cheap, auditable
snapshots of a host's hardware and platform identity. It covers:

- System identity (vendor, product, serial, UUID).
- CPU topology and features.
- Memory (aggregate sizes, optionally per-DIMM detail).
- Block-storage devices.
- Network link-layer hardware.
- PCI device enumeration.
- USB device enumeration.
- Firmware (BIOS / UEFI) identity.
- Combined snapshot of all of the above.

The feature is executed exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` for sysfs / `/proc` /
registry-backed information; the established pattern is to route
file I/O through `ICommandRunner` using OS-native file utilities.
It does not manage state; it never mutates the host.

---

## Verbs

Every OS implementation MUST expose a `HardwareInventoryManager`
class (the OS-prefixed variant — see §Naming) whose public
surface is the following set of verbs. Every verb is a Read.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_system_info` | `() → SystemIdentity` | Read |
| `get_cpu_info` | `() → CpuInfo` | Read |
| `get_memory_info` | `() → MemoryInfo` | Read |
| `list_storage_devices` | `() → list[StorageDevice]` | Read |
| `list_network_devices` | `() → list[NetworkDevice]` | Read |
| `list_pci_devices` | `() → list[PciDevice]` | Read |
| `list_usb_devices` | `() → list[UsbDevice]` | Read |
| `get_firmware_info` | `() → FirmwareInfo` | Read |
| `collect_snapshot` | `() → HardwareSnapshot` | Read |

### Method-level invariants (reads)

1. **No writes.** No verb MUST invoke any command that mutates
   host state.
2. **Selective elevation.** Reads MUST NOT pass `elevated=True`
   by default. Implementations MAY pass `elevated=True` for
   specific sub-queries that the OS requires elevation to read
   (e.g., `dmidecode` for DMI / DIMM data on Linux). Selective
   elevation MUST be controlled by `config.elevated=True`. When
   `config.elevated=False`, no sub-query passes `elevated=True`.
3. **Partial-snapshot tolerance.** `collect_snapshot` MUST NOT
   raise when a single sub-query fails. The corresponding
   `HardwareSnapshot` field MUST be set to `None` and a
   `PartialInventoryWarning` MUST be appended to
   `HardwareSnapshot.warnings`.
4. **Typed errors.** Individual verbs MAY raise
   `HardwareQueryError` for unexpected failures or, per the
   per-OS spec, return `None` / an empty list / synthetic
   record so callers can proceed without a try/except wrapper.
   `HardwareInventoryPermissionError` MUST be raised when a
   sub-query fails due to insufficient permissions and the
   caller requested a direct verb (not `collect_snapshot`). See
   the README "Implementation Conventions" graceful-read pattern.
5. **Pure parsing.** All parsing runs in pure Python.
6. **Fallbacks.** Each verb SHOULD implement at least one
   fallback where the primary tool is absent (e.g., sysfs read
   when `dmidecode` is unavailable). The `source` field on the
   result MUST indicate which collector produced the data.

---

## Data Models

Every OS implementation MUST expose these dataclasses, each
prefixed with the OS name (see §Naming).

### `SystemIdentity` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `manufacturer` | `str \| None` | System manufacturer / vendor. |
| `product` | `str \| None` | Product / model name. |
| `version` | `str \| None` | Product version. |
| `serial` | `str \| None` | Serial number. |
| `uuid` | `str \| None` | System UUID. |
| `machine_id` | `str \| None` | Host machine identifier (`/etc/machine-id`, macOS IOPlatformUUID, Windows `MachineGuid`). |
| `hostname` | `str \| None` | Resolved hostname. |
| `source` | `str` | Collector identifier (`"dmidecode"`, `"sysfs"`, `"system_profiler"`, `"wmi"`, ...). |

### `CpuInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `arch` | `str \| None` | CPU architecture. |
| `vendor` | `str \| None` | CPU vendor. |
| `model_name` | `str \| None` | Model name / brand string. |
| `sockets` | `int \| None` | Socket count. |
| `cores` | `int \| None` | Physical core count. |
| `threads` | `int \| None` | Logical thread count. |
| `mhz` | `float \| None` | Nominal MHz. |
| `flags` | `list[str]` | CPU feature flags. |
| `virtualization` | `str \| None` | Virtualization extension / flag. |
| `source` | `str` | Collector identifier. |

### `MemoryInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `total_bytes` | `int \| None` | Total installed memory. |
| `available_bytes` | `int \| None` | Available memory (native definition). |
| `swap_total_bytes` | `int \| None` | Total swap / pagefile. |
| `dimm_count` | `int \| None` | Installed DIMM count. |
| `source` | `str` | Collector identifier. |

### `StorageDevice` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Native device name (`/dev/sda`, `disk0`, `PhysicalDrive0`). |
| `type` | `str \| None` | Device type (`"disk"`, `"ssd"`, `"nvme"`, `"usb"`). |
| `size_bytes` | `int \| None` | Total capacity. |
| `model` | `str \| None` | Device model string. |
| `serial` | `str \| None` | Serial number. |
| `vendor` | `str \| None` | Vendor string. |
| `rotational` | `bool \| None` | `True` for spinning disks; `False` for solid-state; `None` when unknown. |
| `interface` | `str \| None` | Transport (`"sata"`, `"nvme"`, `"usb"`, `"scsi"`). |

### `NetworkDevice` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Native interface name. |
| `mac` | `str \| None` | MAC address. |
| `driver` | `str \| None` | Driver / kext / miniport name. |
| `link_state` | `str \| None` | Native link state. |
| `speed_mbps` | `int \| None` | Reported link speed. |
| `duplex` | `str \| None` | `"full"` / `"half"` where known. |

### `PciDevice` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `slot` | `str` | Bus address (`"0000:00:1f.3"` on Linux; vendor-specific on others). |
| `vendor` | `str \| None` | Vendor text. |
| `device` | `str \| None` | Device text. |
| `vendor_id` | `str \| None` | Vendor id hex. |
| `device_id` | `str \| None` | Device id hex. |
| `driver` | `str \| None` | Kernel / kext / driver name. |

### `UsbDevice` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `bus` | `str` | Bus / hub identifier. |
| `device` | `str` | Device address. |
| `vendor_id` | `str \| None` | Vendor id hex. |
| `product_id` | `str \| None` | Product id hex. |
| `description` | `str \| None` | Human-readable description. |

### `FirmwareInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `vendor` | `str \| None` | Firmware vendor. |
| `version` | `str \| None` | Firmware version string. |
| `release_date` | `str \| None` | Release date string. |
| `mode` | `str \| None` | `"BIOS"` or `"UEFI"`. |
| `available` | `bool` | Whether firmware data could be retrieved. |

### `HardwareSnapshot` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `collected_at` | `str` | ISO-8601 UTC timestamp. |
| `system` | `SystemIdentity \| None` | System identity; `None` on sub-query failure. |
| `cpu` | `CpuInfo \| None` | CPU info. |
| `memory` | `MemoryInfo \| None` | Memory info. |
| `storage_devices` | `list[StorageDevice] \| None` | Storage devices. |
| `network_devices` | `list[NetworkDevice] \| None` | Network devices. |
| `pci_devices` | `list[PciDevice] \| None` | PCI devices. |
| `usb_devices` | `list[UsbDevice] \| None` | USB devices. |
| `firmware` | `FirmwareInfo \| None` | Firmware info. |
| `warnings` | `list[PartialInventoryWarning]` | Recorded partial-snapshot warnings. |

### `PartialInventoryWarning` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `field` | `str` | Name of the missing field (`"cpu"`, `"memory"`). |
| `reason` | `str` | Category (`"permission_denied"`, `"tool_unavailable"`). |
| `detail` | `str \| None` | Optional human-readable detail. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `HardwareQueryError` | A direct verb fails unexpectedly. |
| `HardwareInventoryPermissionError` | A direct verb fails due to insufficient permissions. |

### `HardwareInventoryManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `elevated` | `bool` | `False` | When `True`, sub-queries that require elevation (e.g., DMI) are invoked elevated. All other sub-queries run unelevated regardless. |

There is intentionally **no** `dry_run` field. This feature is
read-only.

---

## Collector Mapping

The abstract verbs map to each OS's native tooling:

| OS | Primary collectors | Fallback collectors |
|----|--------------------|---------------------|
| Red Hat Enterprise Linux | `dmidecode`, `lscpu`, `lsmem`, `lsblk`, `lspci`, `lsusb`, `ip -j link`, `/sys/class/dmi/id/` | `/proc/cpuinfo`, `/proc/meminfo`, sysfs |
| Ubuntu | Same as RHEL. | — |
| macOS | `system_profiler -json SPHardwareDataType`, `sysctl hw.*`, `ioreg`, `diskutil list`, `ifconfig`, `networksetup` | — |
| Windows | `Get-ComputerInfo`, `Get-CimInstance Win32_*`, `Get-PhysicalDisk`, `Get-NetAdapter`, WMI | `wmic` (deprecated) |
| UEFI | N/A | N/A |

Each OS spec MUST include a Collector-Mapping section stating
its primary tools and fallbacks, and which fields populate the
`source` property for each.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, DMI / DIMM sub-query (Linux) | Pass `elevated=True` to the runner. |
| Config `elevated=True`, any other sub-query | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>HardwareInventoryManager
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
   `HardwareInventoryManagerConfig` in their constructor. An
   `IFileOperator` MAY be injected for sysfs / procfs / registry
   reads.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `HardwareInventoryManager` | `UbuntuHardwareInventoryManager` | `MacosHardwareInventoryManager` | `WindowsHardwareInventoryManager` | `HardwareInventoryManager` |
| `HardwareInventoryManagerConfig` | `UbuntuHardwareInventoryManagerConfig` | `MacosHardwareInventoryManagerConfig` | `WindowsHardwareInventoryManagerConfig` | `HardwareInventoryConfig` |
| `SystemIdentity` | `UbuntuSystemIdentity` | `MacosSystemIdentity` | `WindowsSystemIdentity` | `DmiIdentity` |
| `CpuInfo` | `UbuntuCpuInfo` | `MacosCpuInfo` | `WindowsCpuInfo` | `CpuInfo` |
| `MemoryInfo` | `UbuntuMemoryInfo` | `MacosMemoryInfo` | `WindowsMemoryInfo` | `MemoryInfo` |
| `StorageDevice` | `UbuntuStorageDevice` | `MacosStorageDevice` | `WindowsStorageDevice` | `BlockDeviceInventory` |
| `NetworkDevice` | `UbuntuNetworkDevice` | `MacosNetworkDevice` | `WindowsNetworkDevice` | `NetInterfaceHardware` |
| `PciDevice` | `UbuntuPciDevice` | `MacosPciDevice` | `WindowsPciDevice` | `PciDevice` |
| `UsbDevice` | `UbuntuUsbDevice` | `MacosUsbDevice` | `WindowsUsbDevice` | `UsbDevice` |
| `FirmwareInfo` | `UbuntuFirmwareInfo` | `MacosFirmwareInfo` | `WindowsFirmwareInfo` | `FirmwareInfo` |
| `HardwareSnapshot` | `UbuntuHardwareSnapshot` | `MacosHardwareSnapshot` | `WindowsHardwareSnapshot` | `HardwareSnapshot` |
| `PartialInventoryWarning` | `UbuntuPartialInventoryWarning` | `MacosPartialInventoryWarning` | `WindowsPartialInventoryWarning` | `PartialInventoryWarning` |
| `HardwareQueryError` | `UbuntuHardwareQueryError` | `MacosHardwareQueryError` | `WindowsHardwareQueryError` | `HardwareQueryError` |
| `HardwareInventoryPermissionError` | `UbuntuHardwareInventoryPermissionError` | `MacosHardwareInventoryPermissionError` | `WindowsHardwareInventoryPermissionError` | `HardwareInventoryPermissionError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `HardwareSnapshot` structure when driven by a
  real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects MAY flip a transient failing sub-query into a
  successful one; the resulting snapshot MUST reflect the retry
  outcome.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One parser test per verb, covering representative primary-
   collector output.
2. One fallback test per verb where a fallback is defined,
   proving the correct fallback runs when the primary tool is
   absent and that `source` reflects the fallback.
3. One `collect_snapshot` test proving every sub-query is
   invoked exactly once and that all fields populate on a fully
   privileged host.
4. One `collect_snapshot` partial-tolerance test proving that a
   sub-query failure leaves the corresponding field `None`,
   appends a `PartialInventoryWarning`, and does not prevent the
   remaining sub-queries.
5. One permission-failure test proving
   `HardwareInventoryPermissionError` is raised from a direct
   verb when the sub-query fails for permission reasons and the
   caller did not call `collect_snapshot`.
6. One elevation test proving that DMI / DIMM-equivalent
   sub-queries receive `elevated=True` only when
   `config.elevated=True`.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- SMART / NVMe health queries on storage devices.
- IPMI / BMC queries.
- GPU topology and feature queries.
- Per-port network interface statistics (covered by
  `network-configuration`).
- Hardware change detection / diffs against a prior snapshot.
- Thermal / power / fan sensor queries.
- Chassis intrusion status.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`SystemIdentity` rename.** The contract uses `SystemIdentity`;
  per-OS specs use `<Os>SystemIdentity` /
  `<Os>HostIdentity` interchangeably with field shapes that differ
  slightly (macOS adds `hardware_uuid`; Windows adds
  `pc_system_type`). See the README "Implementation Conventions"
  concrete-implementation naming-overrides convention.
- **No `IFileOperator`.** sysfs / `/proc` reads on Linux route
  through the runner via `cat` / `head` / `tr`; macOS uses
  `system_profiler` / `sysctl` / `ioreg`; Windows uses
  WMI / CIM PowerShell cmdlets. None of the implementations
  inject a separate `IFileOperator`.
- **`PartialInventoryWarning`-tolerance is universal.** Every
  per-OS `collect_snapshot` aggregates partial failures into the
  warnings list rather than raising.
