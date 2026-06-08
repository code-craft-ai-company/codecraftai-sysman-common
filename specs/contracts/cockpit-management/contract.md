# Cockpit-Management Contract

This is the cross-OS abstract contract for the
**cockpit-management** feature. Every `codecraftai-sysman-*`
package that ships a Cockpit manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-cockpit-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-cockpit-management/).
It wraps `systemctl` against `cockpit.socket`, reads
`/usr/share/cockpit/*/manifest.json`, writes drop-ins under
`/etc/systemd/system/cockpit.socket.d/` and
`/etc/cockpit/cockpit.conf`, and invokes `cockpit-bridge
--version` through an `ICommandRunner` and `IFileOperator`.

> **RHEL-primary feature.** Cockpit is a Red Hat project. Ubuntu
> ships Cockpit packages as well and implementations there are
> first-class. **Implementations on macOS and Windows are
> OPTIONAL**; these OSes have no native Cockpit equivalent and
> MAY return `CockpitActionResult` with `status=FAILED` and a
> descriptive `detail` for every verb. When an OS opts not to
> implement Cockpit at all, the OS spec MUST state that fact and
> MAY omit the manager class entirely.

---

## Scope

The cockpit-management feature provides idempotent, auditable
control over the Cockpit web-console installation and
configuration on a host. It covers:

- Installing and uninstalling the Cockpit service surface (a
  thin wrapper over package management, not a package manager
  replacement).
- Enabling and disabling individual Cockpit modules.
- Listing installed Cockpit modules and their metadata.
- Querying the Cockpit socket / service status.
- Configuring the TLS certificate / key pair used by the Cockpit
  listener.
- Restarting the Cockpit service surface.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature does NOT install the Cockpit RPM / DEB / whatever
else — that is `package-management`. It assumes the package is
present and raises `CockpitNotInstalledError` when it is not.

---

## Verbs

Every OS implementation that ships a Cockpit manager MUST expose
a `CockpitManager` class (the OS-prefixed variant — see §Naming)
whose public surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `install_cockpit` | `() → CockpitActionResult` | Write |
| `enable_cockpit_module` | `(name: str) → CockpitActionResult` | Write |
| `disable_cockpit_module` | `(name: str) → CockpitActionResult` | Write |
| `list_installed_modules` | `() → list[CockpitModule]` | Read |
| `get_cockpit_status` | `() → CockpitStatus` | Read |
| `configure_cockpit_tls` | `(cert_path: str, key_path: str) → CockpitActionResult` | Write |
| `restart_cockpit` | `() → CockpitActionResult` | Write |
| `get_version` | `() → str` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `install_cockpit` MUST return `SKIPPED`
   when Cockpit is already present and the socket is active.
   `enable_cockpit_module` and `disable_cockpit_module` MUST
   return `SKIPPED` when the module is already in the requested
   state. `configure_cockpit_tls` MUST return `SKIPPED` when the
   same cert/key pair is already in effect (matched by SHA-256
   fingerprint). `restart_cockpit` is operational and MUST NOT
   skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner or file operator.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Platform unsupported.** On OSes that have no Cockpit
   equivalent and opt not to ship a manager, every verb MUST
   return `CockpitActionResult(status=FAILED, detail="Cockpit
   is not supported on this OS")`. The OS spec MUST document
   whether the manager is present at all.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True`.
2. **Typed errors.** Reads MUST raise `CockpitQueryError` for
   unexpected failures.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation that ships a Cockpit manager MUST expose
these dataclasses and enum, each prefixed with the OS name (see
§Naming).

### `CockpitActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or Cockpit is not supported on this OS. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `CockpitActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `CockpitActionStatus` | Outcome category. |
| `target` | `str \| None` | Logical target (module name, `"cockpit.socket"`, TLS path). |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `CockpitModule` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Module identifier. |
| `version` | `str \| None` | Module version from the manifest. |
| `priority` | `int \| None` | Load-order priority when available. |
| `enabled` | `bool` | Whether the module is currently enabled. |
| `path` | `str \| None` | Absolute path to the manifest when applicable. |

### `CockpitStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `present` | `bool` | Whether Cockpit is installed. |
| `active` | `bool` | Whether `cockpit.socket` (or native equivalent) is active. |
| `enabled` | `bool` | Whether Cockpit is configured to start at boot. |
| `listen_entries` | `list[tuple[str, int]]` | Currently effective `(address, port)` pairs. |
| `version` | `str \| None` | Installed Cockpit version. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `CockpitQueryError` | A read fails unexpectedly. |
| `CockpitNotInstalledError` | A verb assumes Cockpit is installed and it is not. |
| `CockpitModuleNotFoundError` | A module-targeting verb is given an unknown module name. |

### `CockpitManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Platform-Support Mapping

| OS | Support level | Notes |
|----|---------------|-------|
| Red Hat Enterprise Linux | Fully supported | Canonical. Runs on `cockpit.socket`. |
| Ubuntu | Fully supported | Ubuntu ships Cockpit via the `cockpit` package; the service surface is identical. |
| macOS | Optional. MAY omit the manager. If provided, all verbs MUST return `FAILED` with `detail="Cockpit is not supported on macOS"`. | — |
| Windows | Optional. MAY omit the manager. If provided, all verbs MUST return `FAILED` with `detail="Cockpit is not supported on Windows"`. | — |
| UEFI | N/A | UEFI has no management-plane web-console concept. The contract does not apply. |

Each OS spec MUST include a Platform-Support section stating its
level.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu; N/A on macOS/Windows when the manager is not shipped. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>CockpitManager
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

All OS implementations that ship a Cockpit manager MUST:

1. Accept an `ICommandRunner` and a `CockpitManagerConfig` in
   their constructor. Implementations that edit drop-in files MAY
   also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Never restart services on their own initiative — the
   coordinator drives restarts via `service-management` or the
   explicit `restart_cockpit` verb.
4. Not hold state across calls beyond the config.
5. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `CockpitManager` | `UbuntuCockpitManager` | `MacosCockpitManager` | `WindowsCockpitManager` | `CockpitManager` |
| `CockpitManagerConfig` | `UbuntuCockpitManagerConfig` | `MacosCockpitManagerConfig` | `WindowsCockpitManagerConfig` | `CockpitManagerConfig` |
| `CockpitActionStatus` | `UbuntuCockpitActionStatus` | `MacosCockpitActionStatus` | `WindowsCockpitActionStatus` | `CockpitActionStatus` |
| `CockpitActionResult` | `UbuntuCockpitActionResult` | `MacosCockpitActionResult` | `WindowsCockpitActionResult` | `CockpitActionResult` |
| `CockpitModule` | `UbuntuCockpitModule` | `MacosCockpitModule` | `WindowsCockpitModule` | `CockpitModule` |
| `CockpitStatus` | `UbuntuCockpitStatus` | `MacosCockpitStatus` | `WindowsCockpitStatus` | `CockpitSocketState` |
| `CockpitQueryError` | `UbuntuCockpitQueryError` | `MacosCockpitQueryError` | `WindowsCockpitQueryError` | `CockpitQueryError` |
| `CockpitNotInstalledError` | `UbuntuCockpitNotInstalledError` | `MacosCockpitNotInstalledError` | `WindowsCockpitNotInstalledError` | `CockpitNotInstalledError` |
| `CockpitModuleNotFoundError` | `UbuntuCockpitModuleNotFoundError` | `MacosCockpitModuleNotFoundError` | `WindowsCockpitModuleNotFoundError` | `CockpitModuleNotFoundError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `CockpitActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation that ships a Cockpit manager MUST include
at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_installed_modules` parser test covering a manifest
   directory with multiple modules.
5. One `get_cockpit_status` test covering both the running and
   stopped paths.
6. One `configure_cockpit_tls` test proving SKIPPED when the
   cert/key pair is already in effect.
7. One `CockpitNotInstalledError` test proving the right
   exception fires when Cockpit is absent.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

OSes that opt not to ship a manager at all are exempt; OSes that
ship a stub manager MUST test that every verb returns `FAILED`
with the `"Cockpit is not supported on this OS"` detail.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Installing the Cockpit package itself (see
  `package-management`).
- Opening firewall ports for the Cockpit listener (see
  `firewall-management`).
- Daemon-reload of systemd after drop-in writes (see
  `service-management`).
- SSO integration (Kerberos / IdP).
- Cockpit plugin development / shipping extra modules beyond
  enable / disable.
- Cockpit session management or user-visible message-of-the-day.

---

## Implementation Drift

No cross-OS implementations exist; Cockpit is an RHEL-primary
feature. macOS and Windows implementations, if shipped, are
expected to return `FAILED` with stable detail tokens such as
`unsupported_on_host_os_darwin` or `unsupported_on_host_os_windows`
per the README "Implementation Conventions" stable-token catalog.
