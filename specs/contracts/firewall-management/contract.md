# Firewall-Management Contract

This is the cross-OS abstract contract for the **firewall-management**
feature. Every `codecraftai-sysman-*` package that ships a firewall
manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-firewall-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-firewall-management/).
It uses `firewalld` via `firewall-cmd` and is the basis for the
abstract shape defined here.

---

## Scope

The firewall-management feature provides idempotent, auditable
control over a host's local packet-filter / application-firewall
configuration. It covers:

- Adding and removing named services, raw port/protocol allows, and
  OS-native "rich" / "custom" rules within a zone.
- Setting the default zone.
- Reloading permanent changes into the runtime configuration.
- Querying zone state, listing all zones, and reporting the overall
  firewall daemon / service state.
- Applying elevation for write operations, not for reads.
- Supporting dry-run mode that short-circuits all mutations without
  contacting the OS.

The feature is executed exclusively through an `ICommandRunner` from
`codecraftai-interfaces`. No direct `subprocess`, no direct filesystem
writes, no direct daemon-socket calls.

---

## Verbs

Every OS implementation MUST expose a `FirewallManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs. Signatures below are abstract; concrete
signatures substitute the OS-prefixed result-type names.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_service` | `(service: str, zone: str) → FirewallActionResult` | Write |
| `remove_service` | `(service: str, zone: str) → FirewallActionResult` | Write |
| `add_port` | `(port: int, protocol: str, zone: str) → FirewallActionResult` | Write |
| `remove_port` | `(port: int, protocol: str, zone: str) → FirewallActionResult` | Write |
| `add_rich_rule` | `(rule: str, zone: str) → FirewallActionResult` | Write |
| `remove_rich_rule` | `(rule: str, zone: str) → FirewallActionResult` | Write |
| `set_default_zone` | `(zone: str) → FirewallActionResult` | Write |
| `reload` | `() → FirewallActionResult` | Write |
| `query_zone` | `(zone: str) → ZoneInfo` | Read |
| `query_all_zones` | `() → list[ZoneInfo]` | Read |
| `query_state` | `() → FirewallState` | Read |

**Writes** apply elevation per §Elevation and return
`FirewallActionResult`. **Reads** never elevate and return the
specified query dataclass, or raise `FirewallQueryError`.

### Method-level invariants (all writes)

1. **Idempotency guard.** Before invoking any mutating command, the
   implementation calls its internal zone-state query and compares the
   desired state against the current state. If the desired state is
   already in effect, the method MUST return a result with status
   `SKIPPED` and MUST NOT invoke the write command.
2. **Dry-run short-circuit.** If the manager is configured with
   `dry_run=True`, writes MUST NOT invoke the command runner and MUST
   return a result with status `DRY_RUN`. The `command` field MAY be
   populated with the command that would have been executed.
3. **Error surface.** Non-zero exit codes from the runner return a
   result with status `FAILED` populated with `exit_code`, `stdout`,
   and `stderr`. Writes do NOT raise.
4. **Permanence.** Where the underlying tool has a "permanent" /
   "persistent" concept, writes MUST apply it. Runtime-only variants
   are out of scope for the base contract.

### Method-level invariants (all reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   command runner, regardless of manager config.
2. **Typed errors.** Query failures MUST raise `FirewallQueryError`
   carrying the exit code and stderr. The one documented exception is
   `query_state()`: a non-zero exit from the firewall-state query MUST
   be interpreted as "firewall not running" and return a
   `FirewallState(running=False, default_zone="")` rather than raise.
3. **Pure parsing.** All output parsing is Python-only and does not
   require the tool to be installed on the host running the parser's
   unit tests.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum, each
prefixed with the OS name (see §Naming).

### `FirewallActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

Implementations MAY add OS-specific statuses only at the tail of the
enum (never repurposing the above values) and MUST document any
additions in the per-OS spec.

### `FirewallActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `FirewallActionStatus` | Outcome category. |
| `zone` | `str \| None` | The zone the action targeted, or `None` for zone-less verbs (e.g., `reload`). |
| `detail` | `str \| None` | Free-form identifier of the action target: service name, `port/proto`, rule string, or zone name. |
| `exit_code` | `int \| None` | Runner exit code for `SUCCESS` and `FAILED`; `None` otherwise. |
| `stdout` | `str \| None` | Captured stdout for `SUCCESS` and `FAILED`. |
| `stderr` | `str \| None` | Captured stderr for `SUCCESS` and `FAILED`. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `ZoneInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `zone` | `str` | The zone name. |
| `services` | `list[str]` | Named services permitted in the zone. |
| `ports` | `list[str]` | Open `port/protocol` strings. |
| `rich_rules` | `list[str]` | OS-native rich / custom rules. |
| `interfaces` | `list[str]` | Interfaces assigned to the zone (empty if N/A on the OS). |
| `sources` | `list[str]` | Source address matchers assigned to the zone (empty if N/A). |
| `is_default` | `bool` | Whether this zone is currently the default. |

Fields that have no OS-native analog (e.g., `interfaces` on Ubuntu/ufw
or Windows Firewall) MUST be populated as empty lists rather than
omitted.

### `FirewallState` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `running` | `bool` | Whether the firewall daemon / service is active. |
| `default_zone` | `str` | The current default zone name, or `""` when not running / not applicable. |

### `FirewallQueryError` (exception)

Raised from read methods when the underlying query command fails for
reasons other than "firewall not running". Carries the exit code and
captured stderr.

### `FirewallManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations are dispatched. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

Implementations MAY extend with OS-specific fields (e.g., a pf anchor
name on macOS, a PowerShell execution policy on Windows) but MUST
preserve these two fields with these names and defaults.

---

## Zone Mapping

The abstract `zone` parameter maps to the native scoping concept of
each OS's firewall:

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux (firewalld) | Zone | Canonical. |
| Ubuntu (ufw) | Single global policy — `zone` is validated to be `"default"`. | ufw has no zones. Passing any other value MUST return `FirewallActionResult` with `status=FAILED` and a `detail` explaining that ufw supports only the `"default"` zone. |
| macOS (pf) | Anchor | The anchor named by `zone` is the pf sub-ruleset that receives the rule. Convention: `/etc/pf.anchors/ccai.<zone>`. |
| Windows (NetSecurity) | Profile | Maps to Windows Firewall profile: `Domain`, `Private`, `Public`, or `Any`. Any other value MUST return `FAILED`. |
| UEFI | N/A | UEFI has no firewall concept. The firewall-management contract does not apply. |

Each OS spec MUST include a Zone-Mapping section that states its
choice and validation behavior.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the command runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`, regardless of verb. |
| OS elevation mechanism | OS-specific: `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. The command runner handles the mechanism. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>FirewallManager
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
   config. Zone state is re-queried per write.
4. Be safe to invoke under any aspect composition configured on the
   runner.

---

## Naming

Concrete types per OS are prefixed with the OS name in a Pascal-case
form. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `FirewallManager` | `UbuntuFirewallManager` | `MacosFirewallManager` | `WindowsFirewallManager` | `FirewallManager` |
| `FirewallManagerConfig` | `UbuntuFirewallManagerConfig` | `MacosFirewallManagerConfig` | `WindowsFirewallManagerConfig` | `FirewallManagerConfig` |
| `FirewallActionStatus` | `UbuntuFirewallActionStatus` | `MacosFirewallActionStatus` | `WindowsFirewallActionStatus` | `FirewallActionStatus` |
| `FirewallActionResult` | `UbuntuFirewallActionResult` | `MacosFirewallActionResult` | `WindowsFirewallActionResult` | `FirewallActionResult` |
| `ZoneInfo` | `UbuntuZoneInfo` | `MacosZoneInfo` | `WindowsZoneInfo` | `ZoneInfo` |
| `FirewallState` | `UbuntuFirewallState` | `MacosFirewallState` | `WindowsFirewallState` | `FirewallState` |
| `FirewallQueryError` | `UbuntuFirewallQueryError` | `MacosFirewallQueryError` | `WindowsFirewallQueryError` | `FirewallQueryError` |

The RHEL package retains unprefixed names for historical reasons; new
packages use the OS-prefixed form so that code importing from
multiple OS packages does not alias-collide. A coordinator that
handles mixed-OS fleets imports the prefixed types directly.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager that was tested with a `MockCommandRunner` with no aspects
  MUST produce the same `FirewallActionResult` sequence when driven by
  a `SSHCommandRunner` with `PersistenceAspect`, `RetryAspect`, and
  `TimeoutAspect` attached, modulo runner-level timing and retries.
- Retry aspects that translate transient non-zero exits into successes
  are permitted to change `status` from `FAILED` to `SUCCESS`; all
  other field semantics are unchanged.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One test per write verb proving command construction is correct.
2. One idempotency test per write verb proving `SKIPPED` is returned
   when the desired state is already in effect.
3. One dry-run test per write verb proving the runner is not invoked.
4. One parser test per read verb covering a realistic multi-item
   output block.
5. One test proving `query_state()` surfaces `running=False` when the
   firewall is off.
6. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

Beyond these, each OS MAY add tool-specific tests (e.g., rich-rule
normalisation on RHEL, pf anchor loading on macOS, profile parameter
validation on Windows).

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required for
contract conformance:

- Runtime-only (non-permanent) rule variants.
- Forward ports / port forwarding.
- Zone / anchor / profile creation and removal.
- Source address / ipset / NLA-based zone assignment beyond reading
  `ZoneInfo.sources`.
- NAT, masquerading, and policy routing.
- Rule metrics / hit counters.
- IPv6 vs IPv4 selection (the base contract treats rules as family-
  agnostic strings; OS specs may elaborate).

Any extension MUST be documented in the per-OS `design.md` under an
"Extensions beyond the contract" heading.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu wraps `ufw` (single
  global policy, `zone == "default"`); macOS wraps `pf` with
  anchor files; Windows wraps the NetSecurity PowerShell module
  (Domain / Private / Public profiles). The `ZoneInfo` shape is
  identical; the realisable values are not. The `interfaces` /
  `sources` lists are empty on Ubuntu and Windows.
- **File I/O via `ICommandRunner`.** macOS pf-anchor file reads
  and writes route through the runner using `cat` and `tee`
  rather than a separate `IFileOperator`. Windows PowerShell
  rule exports and imports likewise.
- **Windows `elevation_blocked: bool`.** Writes that require
  elevation fail with the structured Windows
  `elevation_blocked=True` extension when the manager is not
  running with an elevated token. See the README
  "Implementation Conventions" elevation-blocked extension.
