# Service-Management Contract

This is the cross-OS abstract contract for the **service-management**
feature. Every `automojo-sysman-*` package that ships a service
manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-service-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-service-management/).
It uses `systemctl` and `journalctl` through an `ICommandRunner`.
This contract generalises the verb set for OSes whose native service
surface is launchd (macOS) or the Service Control Manager / `sc.exe`
/ `Get-Service` (Windows).

---

## Scope

The service-management feature provides idempotent, auditable
control over long-running system and user services. It covers:

- Starting, stopping, restarting, and reloading a service.
- Enabling and disabling a service for automatic start.
- Masking and unmasking a service.
- Reloading the service manager's unit / manifest cache.
- Querying a service's current status.
- Listing all services.
- Dry-run-aware writes.
- Elevation for system-scope writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `ServiceManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `start_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `stop_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `restart_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `reload_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `enable_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `disable_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `mask_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `unmask_service` | `(name: str, scope: ServiceScope) → ServiceActionResult` | Write |
| `get_service_status` | `(name: str, scope: ServiceScope) → ServiceStatus` | Read |
| `list_services` | `(scope: ServiceScope) → list[ServiceInfo]` | Read |
| `reload_daemon` | `(scope: ServiceScope) → ServiceActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** Each write MUST query `get_service_status`
   and compare to the desired state. Matching state MUST return
   `SKIPPED`. `restart_service` and `reload_daemon` are
   unconditional and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Reload precondition.** `reload_service` MUST return `FAILED`
   (with a descriptive `message`) when the service is not
   currently active — the underlying mechanism on most OSes
   requires a running service to accept a reload signal.
5. **Mask semantics.** `mask_service` and `unmask_service` MUST be
   idempotent against the current masked / unmasked state. On OSes
   with no masking equivalent (e.g., Task Scheduler), the OS spec
   MUST document the fallback (typically: disable + refuse-to-run).

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_services` MUST raise
   `ServiceQueryError` for unexpected failures. Informational
   non-zero exits from status queries (e.g., `systemctl is-active`
   returning non-zero because the service is inactive) MUST NOT be
   treated as errors.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `ServiceActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and failed, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ServiceScope` (enum)

| Value | Meaning |
|-------|---------|
| `SYSTEM` | System-wide / machine-scope services. |
| `USER` | Per-user services. |

### `ServiceActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ServiceActionStatus` | Outcome category. |
| `service_name` | `str` | The service name. |
| `scope` | `ServiceScope` | The scope targeted. |
| `message` | `str \| None` | Human-readable detail for `SKIPPED` or `FAILED`. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `ServiceStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `service_name` | `str` | Service name. |
| `scope` | `ServiceScope` | Scope the query targeted. |
| `active_state` | `str` | Native active-state string (`"active"`, `"inactive"`, `"failed"`, `"not-found"`). |
| `enabled_state` | `str` | Native enabled-state string (`"enabled"`, `"disabled"`, `"masked"`, `"static"`, `"not-found"`). |
| `main_pid` | `int \| None` | Main process PID when active. |
| `description` | `str \| None` | Service description when available. |

### `ServiceInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `service_name` | `str` | Service name. |
| `scope` | `ServiceScope` | Scope. |
| `active_state` | `str` | Current active state. |
| `enabled_state` | `str` | Current enabled state. |
| `description` | `str \| None` | Service description. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ServiceQueryError` | A read fails for a reason other than an informational non-zero status-exit. |

### `ServiceManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, system-scope writes pass `elevated=True`. |

---

## Service-Name and Scope Mapping

The abstract `(name, scope)` pair maps to each OS's native service
addressing.

| OS | SYSTEM scope | USER scope | Notes |
|----|--------------|------------|-------|
| Red Hat Enterprise Linux | `systemctl <verb> <name>` | `systemctl --user <verb> <name>` | Canonical. |
| Ubuntu | Same as RHEL | Same as RHEL | — |
| macOS | launchd `/Library/LaunchDaemons/` label; verbs via `launchctl` (bootstrap / bootout / kickstart / enable / disable) | launchd `~/Library/LaunchAgents/` label; verbs via `launchctl` | Masking is emulated via disable + permission-based refuse-to-run. |
| Windows | Service Control Manager via `sc.exe` / PowerShell `Get-Service`, `Start-Service`, `Set-Service` | Per-user services (Windows 10+) via the same tooling with the correct service-name suffix | Masking is emulated via disable + start-type = Disabled. |
| UEFI | N/A | N/A | UEFI has no persistent services. The service-management contract does not apply. |

Each OS spec MUST include a Scope-Mapping section describing how
it resolves `(name, scope)` and how masking is implemented.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, system-scope write | Pass `elevated=True` to the runner. |
| Config `elevated=True`, user-scope write for the current user | Not required on Unix-likes; the OS spec MUST state the policy. |
| Config `elevated=True`, user-scope write for another user | Pass `elevated=True`. |
| Any read | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>ServiceManager
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

1. Accept an `ICommandRunner` and a `ServiceManagerConfig` in their
   constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `ServiceManager` | `UbuntuServiceManager` | `MacosServiceManager` | `WindowsServiceManager` | `ServiceManager` |
| `ServiceManagerConfig` | `UbuntuServiceManagerConfig` | `MacosServiceManagerConfig` | `WindowsServiceManagerConfig` | `ServiceManagerConfig` |
| `ServiceActionStatus` | `UbuntuServiceActionStatus` | `MacosServiceActionStatus` | `WindowsServiceActionStatus` | `ServiceActionStatus` |
| `ServiceActionResult` | `UbuntuServiceActionResult` | `MacosServiceActionResult` | `WindowsServiceActionResult` | `ServiceActionResult` |
| `ServiceScope` | `UbuntuServiceScope` | `MacosServiceScope` | `WindowsServiceScope` | `ServiceScope` |
| `ServiceStatus` | `UbuntuServiceStatus` | `MacosServiceStatus` | `WindowsServiceStatus` | `ServiceInfo` (combined with query) |
| `ServiceInfo` | `UbuntuServiceInfo` | `MacosServiceInfo` | `WindowsServiceInfo` | `ServiceInfo` |
| `ServiceQueryError` | `UbuntuServiceQueryError` | `MacosServiceQueryError` | `WindowsServiceQueryError` | `ServiceQueryError` |

The RHEL reference uses `ServiceInfo` for the single-service query
result. New OS packages MUST separate `ServiceStatus` (per-service
query) from `ServiceInfo` (list-entry) to avoid overloading.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ServiceActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb, per scope.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One `reload_service` precondition test proving `FAILED` when
   the service is not active.
4. One `get_service_status` test per active-state / enabled-state
   combination the OS produces.
5. One `list_services` parser test per scope.
6. One dry-run test per write verb proving the runner is not
   invoked.
7. One elevation test proving system-scope writes pass
   `elevated=True` and reads do not, when configured.
8. One mask / unmask test per OS, documenting the native or
   emulated behavior.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Unit / manifest authoring and installation beyond an existing
  named service.
- Socket-activation, path-activation, or timer-activation wiring
  (covered by `scheduled-tasks` for timers).
- Dependency graph introspection.
- Service sandboxing / capability management.
- Service logs beyond a one-shot `journalctl -u` equivalent (full
  log support lives in `log-management`).
- Service auto-restart policy editing.
- Windows service recovery actions (`sc failure`).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu wraps `systemctl`
  (with `--user` for `USER` scope); macOS wraps `launchctl`
  (`bootstrap` / `bootout` / `kickstart -k` / `print` /
  `disable` / `enable` / `print-disabled`); Windows wraps the
  PowerShell service cmdlets (`Start-Service` / `Stop-Service`
  / `Restart-Service` / `Set-Service`). The verb surface is
  identical but `reload_service` / `mask_service` /
  `unmask_service` have no native analog on Windows (mapped to
  `Set-Service -StartupType Disabled` / `Automatic` aliases).
- **`ServiceScope` mapping is per-OS.** Ubuntu maps `SYSTEM` →
  `systemctl` and `USER` → `systemctl --user`. macOS maps
  `SYSTEM` → `system` domain and `USER` → `gui/<target_uid>`,
  with `target_uid` carried on the manager config. Windows
  rejects `USER` because Windows services are SCM-system-only;
  the per-OS spec returns `FAILED` with a stable detail token
  for `USER`-scope writes. See the README "FAILED with stable
  detail token" convention.
- **`reload_service` semantics diverge.** Ubuntu issues
  `systemctl reload`; macOS sends `SIGHUP` via `launchctl
  kill`; Windows has no reload concept and returns `FAILED`
  with a stable detail token. Each per-OS spec documents the
  fallback explicitly.
- **Read-shape returns sentinels, not raises.** `list_services`
  returns an empty list when no services match;
  `get_service_status` returns a synthetic record (or `None`
  per the per-OS spec) when the service is not registered.
  Per the README "Reads degrade gracefully" convention.
- **Windows `elevation_blocked: bool`.** `Set-Service` /
  `Start-Service` / `Stop-Service` writes surface the
  structured Windows elevation extension when the calling
  process lacks an elevated token. See the README
  "Implementation Conventions" elevation-blocked entry.
