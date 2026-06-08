# Network-Configuration Contract

This is the cross-OS abstract contract for the **network-configuration**
feature. Every `codecraftai-sysman-*` package that ships a network
manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-network-configuration/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-network-configuration/).
It uses `hostnamectl`, `nmcli`, `chronyc`, and direct edits of
`/etc/hosts` / `/etc/resolv.conf` / `/etc/chrony.conf` through an
`ICommandRunner`. This contract generalises the verb set for OSes
whose native surface includes `netplan`, `networksetup`, and
`New-NetIPAddress` / `Set-DnsClientServerAddress`.

---

## Scope

The network-configuration feature provides idempotent, auditable
control over per-interface addressing, routing, DNS, and hostname
configuration. It covers:

- Listing interfaces and querying interface detail.
- Assigning address / netmask / gateway to an interface.
- Enabling or disabling an interface.
- Adding and removing routes.
- Reading and setting DNS servers and search domains.
- Reading and setting the system hostname.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `NetworkConfigurationManager`
class (the OS-prefixed variant — see §Naming) whose public surface
is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_interfaces` | `() → list[InterfaceInfo]` | Read |
| `get_interface` | `(name: str) → InterfaceInfo \| None` | Read |
| `configure_interface` | `(name: str, address: str, netmask: str, gateway: str \| None) → NetworkActionResult` | Write |
| `enable_interface` | `(name: str) → NetworkActionResult` | Write |
| `disable_interface` | `(name: str) → NetworkActionResult` | Write |
| `add_route` | `(dest: str, gateway: str, interface: str \| None) → NetworkActionResult` | Write |
| `remove_route` | `(dest: str) → NetworkActionResult` | Write |
| `get_routes` | `() → list[RouteInfo]` | Read |
| `set_dns_servers` | `(servers: list[str]) → NetworkActionResult` | Write |
| `get_dns_servers` | `() → list[str]` | Read |
| `set_search_domains` | `(domains: list[str]) → NetworkActionResult` | Write |
| `get_hostname` | `() → str` | Read |
| `set_hostname` | `(name: str) → NetworkActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** Each write MUST read current state (via
   the corresponding read verb) and compare to the desired state.
   Matching state MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Apply-then-persist.** Where the OS distinguishes runtime and
   persistent configuration, writes MUST update both surfaces. When
   only one surface succeeds, the result MUST report `FAILED` with
   a `message` identifying the failing step.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Reads MAY raise `NetworkQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list / synthetic record so callers can proceed without a
   try/except wrapper. A missing interface MUST cause
   `get_interface` to return `None`. See the README "Implementation
   Conventions" graceful-read pattern.
3. **Pure parsing.** All parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `NetworkActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and failed, or a step in a multi-step write failed. |
| `SKIPPED` | The idempotency guard short-circuited the write. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `NetworkActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `NetworkActionStatus` | Outcome category. |
| `interface` | `str \| None` | The interface name when applicable. |
| `detail` | `str \| None` | Human-readable context (hostname, IP, route). |
| `diff` | `str \| None` | Unified diff for file-backed writes in `DRY_RUN`. |
| `message` | `str \| None` | Human-readable explanation for `SKIPPED` or `FAILED`. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `InterfaceInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Interface name. |
| `mac_address` | `str \| None` | Hardware address. |
| `addresses` | `list[str]` | IPv4/IPv6 CIDR strings. |
| `gateway` | `str \| None` | Default gateway for the interface. |
| `state` | `str` | Native state string (`"up"`, `"down"`, `"unknown"`, etc.). |
| `mtu` | `int \| None` | MTU when known. |

### `RouteInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `destination` | `str` | Destination prefix (CIDR). |
| `gateway` | `str \| None` | Gateway IP when applicable. |
| `interface` | `str \| None` | Outgoing interface when known. |
| `metric` | `int \| None` | Route metric. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `NetworkQueryError` | A read fails for an unexpected reason. |

### `NetworkConfigurationManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

---

## Interface-Name Mapping

The abstract `name` parameter maps to each OS's native interface
identifier.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | NetworkManager connection name or kernel ifname (`eth0`, `enp0s3`, `bond0`) | Canonical. Writes use `nmcli`; reads can use either `nmcli` or `/proc/net`. |
| Ubuntu | kernel ifname with `netplan` on modern releases; `nmcli` on desktop installs; `ifupdown` on older images | The OS spec MUST state the primary surface. |
| macOS | Network service name (`Wi-Fi`, `Ethernet`) for `networksetup`; BSD ifname (`en0`) for `ifconfig` | Many operations require both: `networksetup` for persistence, `ifconfig` for runtime state. |
| Windows | Adapter alias (`Ethernet`, `Wi-Fi`) or index from `Get-NetAdapter` | Writes use `New-NetIPAddress` / `Set-DnsClientServerAddress`; reads use `Get-NetIPAddress` / `Get-DnsClientServerAddress`. |
| UEFI | N/A | UEFI networking is present (iSCSI, PXE) but the interface-configuration contract does not apply outside the boot-time networking namespace. |

Each OS spec MUST include an Interface-Name-Mapping section
describing how it resolves an abstract interface name to the
native identifier and how writes reach both runtime and persistent
state.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>NetworkConfigurationManager
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

1. Accept an `ICommandRunner` and a `NetworkConfigurationManagerConfig`
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
| `NetworkConfigurationManager` | `UbuntuNetworkConfigurationManager` | `MacosNetworkConfigurationManager` | `WindowsNetworkConfigurationManager` | `NetworkManager` |
| `NetworkConfigurationManagerConfig` | `UbuntuNetworkConfigurationManagerConfig` | `MacosNetworkConfigurationManagerConfig` | `WindowsNetworkConfigurationManagerConfig` | `NetworkManagerConfig` |
| `NetworkActionStatus` | `UbuntuNetworkActionStatus` | `MacosNetworkActionStatus` | `WindowsNetworkActionStatus` | `NetworkActionStatus` |
| `NetworkActionResult` | `UbuntuNetworkActionResult` | `MacosNetworkActionResult` | `WindowsNetworkActionResult` | `NetworkActionResult` |
| `InterfaceInfo` | `UbuntuInterfaceInfo` | `MacosInterfaceInfo` | `WindowsInterfaceInfo` | `InterfaceInfo` |
| `RouteInfo` | `UbuntuRouteInfo` | `MacosRouteInfo` | `WindowsRouteInfo` | `RouteInfo` |
| `NetworkQueryError` | `UbuntuNetworkQueryError` | `MacosNetworkQueryError` | `WindowsNetworkQueryError` | `NetworkQueryError` |

The RHEL package keeps the short name `NetworkManager` historically.
New OS packages use the fully qualified
`<Os>NetworkConfigurationManager` to avoid colliding with the
Linux `NetworkManager` daemon name.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `NetworkActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One `get_interfaces` parser test covering multiple interfaces
   including loopback.
4. One `get_routes` parser test.
5. One `set_hostname` test proving the write reaches the canonical
   hostname source for that OS.
6. One `set_dns_servers` / `get_dns_servers` round-trip test.
7. One dry-run test per write verb proving the runner is not
   invoked.
8. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- VLAN / bridge / bond configuration beyond documenting the
  interface name.
- Wi-Fi SSID / profile management.
- VPN client configuration (OpenVPN, WireGuard, IPsec).
- 802.1x / EAP settings.
- NetworkManager-specific connection profiles beyond `add_connection`
  / `remove_connection` equivalents (see the RHEL reference for an
  OS-specific extension).
- IPv6 privacy extensions / SLAAC tuning.
- Policy routing (`ip rule`).
- NTP server management (covered by the `time-management` feature
  when defined).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence.** Ubuntu wraps Netplan / NetworkManager
  / `systemd-networkd`; macOS wraps `networksetup` / `ifconfig`
  / `route`; Windows wraps `Get-NetAdapter` /
  `New-NetIPAddress` / `Set-DnsClientServerAddress` and the
  registry. The `InterfaceInfo` shape is identical;
  realisable fields differ.
- **`requires_reboot: bool` on Windows hostname rename.**
  Hostname rename via `Rename-Computer` requires a reboot to
  take effect; the `WindowsNetworkActionResult` carries
  `requires_reboot: bool = False`. See the README reboot-
  signaling convention.
- **File I/O via `ICommandRunner`.** Netplan YAML, resolv.conf,
  and registry / `setupapi.dev.log` reads route through the
  runner.
