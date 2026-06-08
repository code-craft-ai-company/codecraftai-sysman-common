# Remote-Log-Forwarding Contract

This is the cross-OS abstract contract for the
**remote-log-forwarding** feature. Every `codecraftai-sysman-*`
package that ships a remote-log-forwarding manager MUST honor
this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-remote-log-forwarding/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-remote-log-forwarding/).
It manages rsyslog forward drop-ins under `/etc/rsyslog.d/`,
`/etc/systemd/journal-upload.conf`, and journald-forward
directives. This contract generalises the verb set for macOS
(limited native syslog forwarding via `/etc/syslog.conf`) and
Windows (Windows Event Forwarding via `wecutil` + subscriptions;
third-party shippers like Winlogbeat / NXLog for syslog-protocol
forwarding).

---

## Scope

The remote-log-forwarding feature provides idempotent, auditable
control over outbound log forwarding to a remote collector. It
covers:

- Adding, removing, and listing forwarders.
- Enabling and disabling a configured forwarder.
- Probing whether a forwarder can reach its collector.
- Querying a forwarder's current status.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and an `IFileOperator` (for drop-in configuration files).

---

## Verbs

Every OS implementation MUST expose a `RemoteLogForwardingManager`
class (the OS-prefixed variant — see §Naming) whose public
surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_forwarder` | `(spec: ForwarderSpec) → ForwarderActionResult` | Write |
| `remove_forwarder` | `(id: str) → ForwarderActionResult` | Write |
| `list_forwarders` | `() → list[ForwarderInfo]` | Read |
| `enable_forwarder` | `(id: str) → ForwarderActionResult` | Write |
| `disable_forwarder` | `(id: str) → ForwarderActionResult` | Write |
| `test_forwarder` | `(id: str) → ForwarderProbeResult` | Read |
| `get_forwarder_status` | `(id: str) → ForwarderInfo \| None` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_forwarder` MUST return `SKIPPED`
   when a forwarder with the same `id` and identical rendered
   content already exists. `remove_forwarder` MUST return
   `SKIPPED` when no forwarder exists for `id`. `enable_forwarder`
   / `disable_forwarder` MUST return `SKIPPED` when the forwarder
   is already in the requested state.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or writing the drop-in.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Post-write reload.** Writes MUST reload the underlying
   forwarding service (rsyslog reload, journal-upload restart,
   `wecutil` subscription reload) on `SUCCESS`. A reload failure
   MUST surface as `FAILED` on the mutating verb.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_forwarders` MUST raise
   `ForwarderQueryError` for unexpected failures.
   `get_forwarder_status` MUST return `None` for an unknown id and
   raise only on unexpected failures.
3. **`test_forwarder` non-raising.** The probe MUST return a
   `ForwarderProbeResult` indicating reachability and MUST NOT
   raise on network failure.
4. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `ForwarderActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ForwarderTransport` (enum)

| Value | Meaning |
|-------|---------|
| `UDP` | UDP syslog transport (insecure). |
| `TCP` | TCP syslog transport. |
| `TLS` | TLS-wrapped TCP syslog. |
| `HTTPS` | HTTPS / RELP / journal-upload transport. |
| `WEF` | Windows Event Forwarding (WS-Management). |

### `ForwarderSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Caller-chosen identifier (file-name friendly). |
| `destination_host` | `str` | Collector hostname or IP. |
| `destination_port` | `int` | Collector port. |
| `transport` | `ForwarderTransport` | Transport selection. |
| `facility_filter` | `str \| None` | Native facility / channel filter. |
| `severity_filter` | `str \| None` | Native severity / level filter. |
| `tls_bundle_path` | `str \| None` | Path to TLS trust material, if `transport` is `TLS` or `HTTPS`. |

### `ForwarderInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Identifier. |
| `destination_host` | `str` | Collector hostname or IP. |
| `destination_port` | `int` | Collector port. |
| `transport` | `ForwarderTransport` | Transport. |
| `enabled` | `bool` | Whether the forwarder is currently enabled. |
| `last_sent_at` | `datetime \| None` | Timestamp of the last successful send, UTC. |
| `queue_depth` | `int \| None` | Native queue depth when available. |

### `ForwarderActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ForwarderActionStatus` | Outcome category. |
| `forwarder_id` | `str` | The identifier targeted. |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `ForwarderProbeResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `forwarder_id` | `str` | The identifier probed. |
| `reachable` | `bool` | Whether the collector accepted the probe. |
| `latency_ms` | `float \| None` | Round-trip time in milliseconds, if measured. |
| `tls_verified` | `bool \| None` | TLS verification outcome, when applicable. |
| `detail` | `str \| None` | Human-readable explanation. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ForwarderQueryError` | A read fails for a reason other than "id unknown". |

### `RemoteLogForwardingConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. Default is `True` because forwarding configuration lives in system directories. |

---

## Destination Mapping

The abstract `(destination_host, destination_port, transport)`
tuple maps to each OS's native forwarder syntax.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | rsyslog drop-ins under `/etc/rsyslog.d/` + `systemd-journal-upload` | Canonical. |
| Ubuntu | Same as RHEL (rsyslog) or `syslog-ng` where installed | Ubuntu spec MUST document which is default. |
| macOS | `/etc/syslog.conf` + `/etc/asl.conf`; optional third-party shipper | Native facility is limited; TLS is not supported natively — MUST return `FAILED` when `transport=TLS` is requested. |
| Windows | Windows Event Forwarding (`wecutil`) for WEF transport; Winlogbeat / NXLog for syslog-protocol transports | The Windows spec MUST document which transport the default implementation supports. |
| UEFI | N/A | UEFI has no log-forwarding concept. The remote-log-forwarding contract does not apply. |

Each OS spec MUST include a Destination-Mapping section
describing the drop-in location, filter syntax, and unsupported
transport values.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>RemoteLogForwardingManager
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

1. Accept an `ICommandRunner`, an `IFileOperator`, and a
   `RemoteLogForwardingConfig` in their constructor.
2. Never construct their own subprocess or file access.
3. Not hold state across calls beyond the injected collaborators
   and the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `RemoteLogForwardingManager` | `UbuntuRemoteLogForwardingManager` | `MacosRemoteLogForwardingManager` | `WindowsRemoteLogForwardingManager` | `RemoteLogForwardingManager` |
| `RemoteLogForwardingConfig` | `UbuntuRemoteLogForwardingConfig` | `MacosRemoteLogForwardingConfig` | `WindowsRemoteLogForwardingConfig` | `RemoteLogForwardingConfig` |
| `ForwarderActionStatus` | `UbuntuForwarderActionStatus` | `MacosForwarderActionStatus` | `WindowsForwarderActionStatus` | `LogForwardingActionStatus` |
| `ForwarderActionResult` | `UbuntuForwarderActionResult` | `MacosForwarderActionResult` | `WindowsForwarderActionResult` | `LogForwardingActionResult` |
| `ForwarderTransport` | `UbuntuForwarderTransport` | `MacosForwarderTransport` | `WindowsForwarderTransport` | `ForwarderTransport` |
| `ForwarderSpec` | `UbuntuForwarderSpec` | `MacosForwarderSpec` | `WindowsForwarderSpec` | `ForwarderSpec` |
| `ForwarderInfo` | `UbuntuForwarderInfo` | `MacosForwarderInfo` | `WindowsForwarderInfo` | `ForwarderInfo` |
| `ForwarderProbeResult` | `UbuntuForwarderProbeResult` | `MacosForwarderProbeResult` | `WindowsForwarderProbeResult` | `ProbeResult` |
| `ForwarderQueryError` | `UbuntuForwarderQueryError` | `MacosForwarderQueryError` | `WindowsForwarderQueryError` | `ForwarderQueryError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ForwarderActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_forwarders` parser test covering multiple forwarders.
5. One `test_forwarder` test proving `reachable=False` with
   populated `detail` on a network failure (no raise).
6. One transport-unsupported test proving `FAILED` is returned for
   the documented transport gaps (e.g., TLS on macOS).
7. One reload-failure test proving the mutating verb returns
   `FAILED` when the post-write reload fails.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Local log inspection — lives in `log-management`.
- Disk-spool / queue size tuning.
- Structured (JSON / CEE / GELF) output formatting beyond the
  native default.
- Collector-side setup and authentication.
- Client certificate generation (delegated to
  `certificate-issuance`).
- WEF subscription authoring in full generality — the base
  contract treats a WEF subscription as a single forwarder entry.
- Forwarder-to-forwarder fan-out / relay chains.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is structural.** Ubuntu wraps rsyslog
  drop-ins under `/etc/rsyslog.d/` (full TCP / UDP / TLS via
  `omfwd` and the `gtls` driver). macOS wraps the legacy
  `/etc/syslog.conf` plus `syslogd(8)` — UDP-only and limited to
  the BSD-syslog facility subset. Windows wraps Windows Event
  Forwarding (WEF) on top of WinRM via `wecutil gs`. The verbs
  align; the backends do not.
- **macOS cannot honour `TLS` transport natively.** Specs that
  request `transport=TCP` or `transport=TLS` are accepted, then
  silently downgraded to UDP with a documented warning advising
  Filebeat / a third-party shipper for production TLS coverage.
- **Windows field-shape drift.** The contract's
  `ForwarderProbeResult` is replaced with
  `WindowsForwarderTestResult` because `Write-EventLog` does not
  round-trip and there is no probe to time. The contract's
  `selector` field becomes `query` (XPath); `last_sent_at` /
  `queue_depth` move onto `WindowsForwarderStatus` parsed
  best-effort from `wecutil gs`. The contract's `transport` enum
  collapses to a `protocol: str` (`"http"` / `"https"`).
- **File I/O via `ICommandRunner`.** Drop-in rsyslog files,
  `/etc/syslog.conf`, and WEF subscription XML reads/writes route
  through the runner using `cat` / `tee` / `Get-Content` /
  `Set-Content` rather than a separate `IFileOperator`. See the
  README "Implementation Conventions" file-I/O section.
- **Windows `elevation_blocked: bool`.** `wecutil` writes and the
  service-bounce surface the structured Windows elevation
  extension. See the README "Implementation Conventions"
  elevation-blocked entry.
