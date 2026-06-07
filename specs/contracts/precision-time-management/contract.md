# Precision-Time-Management Contract

This is the cross-OS abstract contract for the
**precision-time-management** feature. Every `codecraftai-sysman-*`
package that ships a precision-time manager MUST honor this
contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-precision-time-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-precision-time-management/).
The RHEL reference focuses on IEEE 1588 / PTP through `ptp4l`,
`phc2sys`, and `pmc`; this cross-OS contract generalises the
surface to cover chrony / `systemd-timesyncd` / `ntpd` on Linux,
`sntp` / `systemsetup -setnetworktimeserver` on macOS, and the
Windows Time Service (`w32tm`, `W32Time`). Implementations MAY
favor NTP, PTP, or a combination, but MUST present the abstract
verb set uniformly.

> **Timezone overlap.** Timezone-related verbs live in the
> `localization-management` contract. This contract owns
> clock-synchronisation sources, drift, and sync lifecycle.

---

## Scope

The precision-time-management feature provides idempotent,
auditable control over a host's time-synchronisation sources and
sync lifecycle. It covers:

- Querying overall time status (synchronized, stratum, selected
  source, drift).
- Listing active time sources.
- Adding and removing time sources.
- Replacing the entire set of time sources.
- Forcing an immediate synchronisation.
- Enabling and disabling the sync service.
- Reporting measured drift.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and, when writing configuration files, an `IFileOperator`.

---

## Verbs

Every OS implementation MUST expose a `PrecisionTimeManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_time_status` | `() → TimeStatus` | Read |
| `get_time_sources` | `() → list[TimeSource]` | Read |
| `add_time_source` | `(server: str) → TimeActionResult` | Write |
| `remove_time_source` | `(server: str) → TimeActionResult` | Write |
| `set_time_servers` | `(servers: list[str]) → TimeActionResult` | Write |
| `force_sync_now` | `() → TimeActionResult` | Write |
| `get_drift` | `() → TimeDrift` | Read |
| `enable_sync` | `() → TimeActionResult` | Write |
| `disable_sync` | `() → TimeActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_time_source` MUST return `SKIPPED`
   when the server is already configured. `remove_time_source`
   MUST return `SKIPPED` when the server is not present.
   `set_time_servers` MUST return `SKIPPED` when the existing list
   already equals the requested list (order-insensitive).
   `enable_sync` / `disable_sync` MUST return `SKIPPED` when the
   sync service is already in the requested state.
   `force_sync_now` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Persistent reload.** When the OS uses a config file
   (`/etc/chrony.conf`, `W32Time` registry keys), mutations MUST
   reload the sync service on `SUCCESS`. A reload failure MUST
   surface as `FAILED` on the mutating verb.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MUST raise `TimeQueryError`
   carrying exit code and stderr. A host with no sync service
   running MUST cause `get_time_status` to return
   `TimeStatus(synchronized=False, ...)` rather than raise.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `TimeActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `TimeActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `TimeActionStatus` | Outcome category. |
| `action` | `str` | Short identifier (e.g., `"add_source:pool.ntp.org"`). |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `TimeStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `synchronized` | `bool` | Whether the host's clock is considered synchronised. |
| `sync_service_active` | `bool` | Whether the sync service / daemon is running. |
| `selected_source` | `str \| None` | The currently selected upstream source. |
| `stratum` | `int \| None` | Stratum of the selected source (NTP) or PTP class. |
| `last_sync_time` | `datetime \| None` | Timestamp of the last successful sync, UTC. |

### `TimeSource` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `server` | `str` | Server hostname or address. |
| `state` | `str` | Native state token (`"selected"`, `"candidate"`, `"rejected"`). |
| `offset_seconds` | `float \| None` | Offset from local clock in seconds. |
| `jitter_seconds` | `float \| None` | Source jitter estimate, if reported. |

### `TimeDrift` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `drift_ppm` | `float` | Measured drift in parts per million. |
| `frequency_ppm` | `float \| None` | Native frequency adjustment in PPM, if reported. |
| `rms_offset_seconds` | `float \| None` | Smoothed RMS offset estimate. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `TimeQueryError` | A read fails for a reason other than "sync service not running". |

### `PrecisionTimeManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |

---

## Sync-Backend Mapping

Precision-time has no natural scope parameter — a host runs one
primary sync backend. The abstract verbs map to each OS's default
backend.

| OS | Default backend | Notes |
|----|-----------------|-------|
| Red Hat Enterprise Linux | chrony (`chronyd`, `chronyc`) | Canonical for NTP. RHEL also ships `linuxptp` (`ptp4l`, `phc2sys`) for PTP; the RHEL spec documents both. |
| Ubuntu | `systemd-timesyncd` by default, chrony optional | The Ubuntu spec MUST document the selection. |
| macOS | `sntp` via `systemsetup -setnetworktimeserver`; Big Sur+ uses `timed` | No direct PTP support in stock macOS. |
| Windows | Windows Time Service (`w32tm`) | Registry under `HKLM\SYSTEM\CurrentControlSet\Services\W32Time`. |
| UEFI | N/A | UEFI has no time-sync daemon. The precision-time-management contract does not apply. |

Each OS spec MUST include a Sync-Backend-Mapping section stating
its default, how multiple backends are selected, and which
command surface is used.

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
        <Os>PrecisionTimeManager
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

1. Accept an `ICommandRunner` and a `PrecisionTimeManagerConfig`
   in their constructor. Implementations that write configuration
   files MAY also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the injected collaborators
   and the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `PrecisionTimeManager` | `UbuntuPrecisionTimeManager` | `MacosPrecisionTimeManager` | `WindowsPrecisionTimeManager` | `PrecisionTimeManager` |
| `PrecisionTimeManagerConfig` | `UbuntuPrecisionTimeManagerConfig` | `MacosPrecisionTimeManagerConfig` | `WindowsPrecisionTimeManagerConfig` | `PrecisionTimeManagerConfig` |
| `TimeActionStatus` | `UbuntuTimeActionStatus` | `MacosTimeActionStatus` | `WindowsTimeActionStatus` | `PtpActionStatus` |
| `TimeActionResult` | `UbuntuTimeActionResult` | `MacosTimeActionResult` | `WindowsTimeActionResult` | `PtpActionResult` |
| `TimeStatus` | `UbuntuTimeStatus` | `MacosTimeStatus` | `WindowsTimeStatus` | `PtpCurrentDataSet` |
| `TimeSource` | `UbuntuTimeSource` | `MacosTimeSource` | `WindowsTimeSource` | `PtpParentDataSet` |
| `TimeDrift` | `UbuntuTimeDrift` | `MacosTimeDrift` | `WindowsTimeDrift` | `PtpPortDataSet` |
| `TimeQueryError` | `UbuntuTimeQueryError` | `MacosTimeQueryError` | `WindowsTimeQueryError` | `PtpQueryError` |

The RHEL reference uses PTP-specific names; new OS packages use
the NTP-flavoured abstract names to cover the broader backend
space.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `TimeActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per applicable write verb proving `SKIPPED`
   on matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_time_status` parser test for a synchronised host.
5. One `get_time_sources` parser test covering multiple sources.
6. One `get_drift` parser test.
7. One `force_sync_now` command-construction test.
8. One "sync service not running" test proving
   `get_time_status(synchronized=False)` without raising.
9. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- PTP-specific tuning (grand-master selection, domain numbers,
  transport protocol) — RHEL extension.
- Hardware clock (`hwclock`) synchronisation details.
- Leap-second handling policy.
- PPS (pulse-per-second) input device configuration.
- NTP authentication keys.
- Per-interface PTP-over-specific-NIC selection.
- Windows Time provider configuration beyond NTP.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend selection on Ubuntu.** Ubuntu carries a
  `UbuntuTimeBackend` enum (`CHRONY` / `TIMESYNCD`, with `NTPD`
  reserved) on the manager config. macOS binds unconditionally to
  `systemsetup` / `sntp` / `defaults`; Windows binds
  unconditionally to `w32tm.exe` plus `net.exe` / `sc.exe`. Per
  the README "Per-OS backend enums" convention, the prefixed enum
  lives on the OS spec, not the contract.
- **macOS field-shape drift on `TimeStatus` and `TimeDrift`.** The
  contract's `sync_service_active` collapses to `enabled` on
  `MacosTimeStatus`; `last_sync_time: datetime` becomes
  `last_sync: Optional[str]` and is always `None` because Apple's
  user-space tools do not surface a last-sync timestamp. The
  contract's `drift_ppm` / `rms_offset_seconds` are renamed to
  `frequency_ppm` / `jitter_seconds` on `MacosTimeDrift`, with
  `frequency_ppm` always `None`.
- **Single-server backends on macOS and Windows.** macOS's
  `systemsetup` is single-server-oriented; the contract's
  multi-server-natural verb surface is honoured but renderered
  through whichever single-server slot the OS exposes. Windows
  consolidates the multi-peer list into the
  `w32tm /config /manualpeerlist:"<list>"` argument.
- **File I/O via `ICommandRunner`.** chrony.conf, timesyncd.conf,
  and legacy ntp.conf reads/writes route through the runner using
  `cat` / `tee` rather than a separate `IFileOperator`. See the
  README "Implementation Conventions" file-I/O section.
- **Windows `elevation_blocked: bool`.** `w32tm /config /update`,
  `w32tm /resync /force`, and the `net stop` / `net start` service
  bounce surface the structured Windows elevation extension. See
  the README "Implementation Conventions" elevation-blocked entry.
