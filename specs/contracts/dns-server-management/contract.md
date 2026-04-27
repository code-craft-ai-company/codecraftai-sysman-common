# Dns-Server-Management Contract

This is the cross-OS abstract contract for the
**dns-server-management** feature. Every `automojo-sysman-*`
package that ships a DNS-server manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-dns-server-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-dns-server-management/).
It wraps BIND (`named-checkconf`, `named-checkzone`, `rndc`),
Unbound (`unbound-checkconf`, `unbound-control`), and dnsmasq
(`dnsmasq --test`) through an `ICommandRunner`. This contract
generalises the verb set for OSes whose DNS-server surface is the
BIND / Unbound / dnsmasq family (Linux / macOS — BIND ships with
macOS), PowerDNS (Linux), or the Windows DNS Server role
(PowerShell `DnsServer` module).

The feature manages the **authoritative or recursive server**
configuration — not the DNS client stub resolver. Client-side
resolution is covered by `network-configuration`.

---

## Scope

The dns-server-management feature provides idempotent, auditable
control over a host's DNS-server configuration. It covers:

- Defining and removing named zones.
- Listing configured zones and their state.
- Adding and removing individual resource records inside a zone.
- Listing records inside a zone.
- Reloading a single zone on demand.
- Querying the DNS-server daemon status.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature executes exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` for text-backed config
stores; the established pattern is to route file I/O through
`ICommandRunner` using OS-native file utilities. See the README
"Implementation Conventions".

---

## Verbs

Every OS implementation MUST expose a `DnsServerManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_zone` | `(name: str, spec: DnsZoneSpec) → DnsActionResult` | Write |
| `remove_zone` | `(name: str) → DnsActionResult` | Write |
| `list_zones` | `() → list[DnsZoneInfo]` | Read |
| `add_record` | `(zone: str, record: DnsRecord) → DnsActionResult` | Write |
| `remove_record` | `(zone: str, record: DnsRecord) → DnsActionResult` | Write |
| `list_records` | `(zone: str) → list[DnsRecord]` | Read |
| `reload_zone` | `(name: str) → DnsActionResult` | Write |
| `get_zone_status` | `(name: str) → DnsZoneStatus` | Read |
| `get_server_status` | `() → DnsServerStatus` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_zone` MUST return `SKIPPED` when
   a zone with the same name and normalised spec already exists.
   `remove_zone` MUST return `SKIPPED` when the zone is absent.
   `add_record` MUST return `SKIPPED` when an identical record
   already exists. `remove_record` MUST return `SKIPPED` when
   the record is absent. `reload_zone` is operational and MUST
   NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner or file operator.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Validate before apply.** On OSes where configuration
   validation is separate from application (BIND
   `named-checkconf`, Unbound `unbound-checkconf`), writes MUST
   validate the rendered configuration before dispatching the
   reload / apply command. Validation failure MUST return
   `FAILED` without applying.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` unless
   the OS requires it to read the zone store.
2. **Typed errors.** Reads MAY raise `DnsQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list / synthetic record so callers can proceed without a
   try/except wrapper. An unknown zone MUST raise
   `DnsZoneNotFoundError` from verbs that address a specific
   zone. See the README "Implementation Conventions" graceful-read
   pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `DnsActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `DnsServerBackend` (enum)

| Value | Meaning |
|-------|---------|
| `BIND` | BIND 9 / `named`. |
| `UNBOUND` | Unbound. |
| `DNSMASQ` | dnsmasq. |
| `POWERDNS` | PowerDNS Authoritative. |
| `WINDOWS_DNS` | Windows DNS Server role. |

### `DnsZoneKind` (enum)

| Value | Meaning |
|-------|---------|
| `PRIMARY` | Master / primary authoritative zone. |
| `SECONDARY` | Slave / secondary zone. |
| `FORWARD` | Forward-only zone. |
| `STUB` | Stub zone. |

### `DnsZoneSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `DnsZoneKind` | Zone kind. |
| `file_path` | `str \| None` | Path to the zone-data file for primary zones. |
| `primaries` | `list[str]` | Master server addresses for secondary / stub zones. |
| `forwarders` | `list[str]` | Forwarder addresses for forward zones. |
| `allow_transfer` | `list[str]` | Allowed AXFR peers. |
| `dnssec_enabled` | `bool` | Whether DNSSEC signing is enabled. |

### `DnsZoneInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Zone name. |
| `kind` | `DnsZoneKind` | Zone kind. |
| `serial` | `int \| None` | SOA serial when available. |
| `record_count` | `int \| None` | Number of records, when cheap to compute. |
| `loaded` | `bool` | Whether the zone is currently loaded in the server. |

### `DnsZoneStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Zone name. |
| `loaded` | `bool` | Whether loaded by the server. |
| `serial` | `int \| None` | Current SOA serial. |
| `last_refresh` | `str \| None` | ISO-8601 timestamp of last refresh (secondary zones). |
| `error` | `str \| None` | Last zone-load error when present. |

### `DnsRecord` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Owner name (FQDN or relative to the zone). |
| `rtype` | `str` | Record type (`"A"`, `"AAAA"`, `"CNAME"`, `"MX"`, `"TXT"`, `"SRV"`, ...). |
| `ttl` | `int \| None` | TTL in seconds. |
| `data` | `str` | Record data (rdata) in the native text form. |

### `DnsServerStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `backend` | `DnsServerBackend` | Active backend. |
| `running` | `bool` | Whether the daemon is active. |
| `version` | `str \| None` | Version string when known. |
| `zone_count` | `int \| None` | Number of configured zones. |

### `DnsActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `DnsActionStatus` | Outcome category. |
| `zone` | `str \| None` | Zone acted upon. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `DnsQueryError` | A read fails unexpectedly. |
| `DnsZoneNotFoundError` | A zone-addressing verb is given an unknown zone. |
| `DnsBackendNotAvailableError` | No supported backend is installed or the configured backend is not reachable. |
| `DnsBackendMismatchError` | A backend-specific verb is called against the wrong backend. |

### `DnsServerManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |
| `backend` | `DnsServerBackend \| None` | `None` | Override auto-detection of the backend. |

---

## Backend Mapping

The abstract `DnsServerBackend` maps to each OS's native
tooling:

| OS | Default backend | Also supported | Notes |
|----|-----------------|----------------|-------|
| Red Hat Enterprise Linux | `BIND` | `UNBOUND`, `DNSMASQ` | Canonical. |
| Ubuntu | `BIND` | `UNBOUND`, `DNSMASQ` | — |
| macOS | `BIND` | `DNSMASQ` via Homebrew | macOS ships BIND. |
| Windows | `WINDOWS_DNS` | — | `Get-DnsServerZone`, `Add-DnsServerPrimaryZone`, `Add-DnsServerResourceRecord`. BIND-only verbs MUST return `FAILED`. |
| UEFI | N/A | N/A | UEFI has no DNS server surface. The contract does not apply. |

Each OS spec MUST include a Backend-Mapping section enumerating
supported backends, auto-detection, and how
`DnsBackendMismatchError` is surfaced.

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
        <Os>DnsServerManager
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

1. Accept an `ICommandRunner` and a `DnsServerManagerConfig` in
   their constructor. Implementations whose zone store is a
   filesystem layout MAY also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Never restart the DNS daemon on their own initiative —
   `reload_zone` is the only runtime-affecting verb; full
   restarts are delegated to `service-management`.
4. Not hold state across calls beyond the config.
5. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `DnsServerManager` | `UbuntuDnsServerManager` | `MacosDnsServerManager` | `WindowsDnsServerManager` | `DnsServerManager` |
| `DnsServerManagerConfig` | `UbuntuDnsServerManagerConfig` | `MacosDnsServerManagerConfig` | `WindowsDnsServerManagerConfig` | `DnsServerManagerConfig` |
| `DnsActionStatus` | `UbuntuDnsActionStatus` | `MacosDnsActionStatus` | `WindowsDnsActionStatus` | `DnsActionStatus` |
| `DnsActionResult` | `UbuntuDnsActionResult` | `MacosDnsActionResult` | `WindowsDnsActionResult` | `DnsActionResult` |
| `DnsServerBackend` | `UbuntuDnsServerBackend` | `MacosDnsServerBackend` | `WindowsDnsServerBackend` | `DnsServerBackend` |
| `DnsZoneKind` | `UbuntuDnsZoneKind` | `MacosDnsZoneKind` | `WindowsDnsZoneKind` | `DnsZoneKind` |
| `DnsZoneSpec` | `UbuntuDnsZoneSpec` | `MacosDnsZoneSpec` | `WindowsDnsZoneSpec` | `DnsZoneSpec` |
| `DnsZoneInfo` | `UbuntuDnsZoneInfo` | `MacosDnsZoneInfo` | `WindowsDnsZoneInfo` | `DnsZoneInfo` |
| `DnsZoneStatus` | `UbuntuDnsZoneStatus` | `MacosDnsZoneStatus` | `WindowsDnsZoneStatus` | `DnsZoneStatus` |
| `DnsRecord` | `UbuntuDnsRecord` | `MacosDnsRecord` | `WindowsDnsRecord` | `DnsRecord` |
| `DnsServerStatus` | `UbuntuDnsServerStatus` | `MacosDnsServerStatus` | `WindowsDnsServerStatus` | `DnsServerStatus` |
| `DnsQueryError` | `UbuntuDnsQueryError` | `MacosDnsQueryError` | `WindowsDnsQueryError` | `DnsQueryError` |
| `DnsZoneNotFoundError` | `UbuntuDnsZoneNotFoundError` | `MacosDnsZoneNotFoundError` | `WindowsDnsZoneNotFoundError` | `DnsZoneNotFoundError` |
| `DnsBackendNotAvailableError` | `UbuntuDnsBackendNotAvailableError` | `MacosDnsBackendNotAvailableError` | `WindowsDnsBackendNotAvailableError` | `DnsBackendNotAvailableError` |
| `DnsBackendMismatchError` | `UbuntuDnsBackendMismatchError` | `MacosDnsBackendMismatchError` | `WindowsDnsBackendMismatchError` | `DnsBackendMismatchError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `DnsActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb, per supported
   backend.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_zones` parser test covering representative output
   with multiple zone kinds.
5. One `list_records` parser test covering at least A, AAAA,
   CNAME, and TXT records.
6. One `get_zone_status` test covering both the loaded and
   unloaded paths.
7. One validate-before-apply test proving the reload / apply
   command is not dispatched when validation fails.
8. One `DnsBackendMismatchError` test proving the correct error
   is raised for a backend-specific verb invoked under the wrong
   backend.
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Zone signing and DNSSEC key management (KSK / ZSK rollover).
- TSIG / transfer-key management.
- Global server tuning (cache size, EDNS options).
- Views / split-horizon configuration beyond a single default
  view.
- Response-policy zones (RPZ).
- Dynamic update (RFC 2136) authentication and ACL management.
- DNS over TLS / HTTPS listener configuration.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence.** Ubuntu wraps BIND 9 (`named-checkconf`,
  `rndc`); macOS wraps `dnsmasq` (no native enterprise DNS daemon);
  Windows wraps the DNS Server role via PowerShell
  (`Add-DnsServerPrimaryZone`, `Add-DnsServerResourceRecordA`).
  The per-OS specs document fields specific to each backend
  (e.g., `bind_view` on Ubuntu, `windows_directory_integrated`
  on Windows).
- **macOS often returns `unsupported_on_host_os_darwin`.** Several
  zone-record-types BIND supports are not realisable on
  `dnsmasq`; the macOS manager returns `FAILED` with a stable
  detail token. See the README stable-token catalog.
- **File I/O via `ICommandRunner`.** Zone files, `named.conf`
  fragments, and PowerShell DNS-zone exports route through the
  runner.
