# Subscription-Management Contract

This is the cross-OS abstract contract for the
**subscription-management** feature. Every `automojo-sysman-*`
package that ships a subscription manager MUST honor this
contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-subscription-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-subscription-management/).
It wraps Red Hat Subscription Manager (`subscription-manager`)
through an `ICommandRunner`.

> **Red Hat Enterprise Linux only.** Red Hat Subscription Manager is
> a RHEL-only service. **The Ubuntu, macOS, Windows, and UEFI
> implementations of this contract are OPTIONAL and MAY raise
> `NotImplementedError` or return `FAILED` with
> `detail="Red Hat Subscription Manager is a RHEL-only service."`
> for every verb.** The OS spec MUST pick one strategy (raise vs
> `FAILED`) and document it.
>
> A future "entitlement-management" contract MAY generalise this
> surface for Ubuntu Pro (`ua`), macOS volume licences, and Windows
> licensing (`slmgr`), but the base `subscription-management`
> contract is scoped to RHSM verb semantics.

---

## Scope

The subscription-management feature provides idempotent,
auditable control over a host's Red Hat subscription state. It
covers:

- Registering and unregistering the host.
- Attaching and removing subscription pools.
- Listing available and attached pools.
- Refreshing entitlement certificates.
- Querying overall registration status.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

> **Credential handling.** Registration credentials (username,
> password, activation key, organisation id) MUST be passed via
> the runner's stdin or environment channel, never via argv. The
> `SubscriptionActionResult.command` field MUST be sanitised to
> redact any credential material.

---

## Verbs

Every OS implementation MUST expose a `SubscriptionManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `register` | `(credentials: RegistrationCredentials) → SubscriptionActionResult` | Write |
| `unregister` | `() → SubscriptionActionResult` | Write |
| `attach_pool` | `(pool_id: str) → SubscriptionActionResult` | Write |
| `remove_pool` | `(pool_id: str) → SubscriptionActionResult` | Write |
| `list_pools` | `(available: bool) → list[SubscriptionPool]` | Read |
| `list_attached_subscriptions` | `() → list[AttachedSubscription]` | Read |
| `refresh_entitlements` | `() → SubscriptionActionResult` | Write |
| `get_registration_status` | `() → RegistrationStatus` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `register` MUST return `SKIPPED` when
   the host is already registered to the same organisation.
   `unregister` MUST return `SKIPPED` when the host is already
   unregistered. `attach_pool` MUST return `SKIPPED` when the
   pool is already attached. `remove_pool` MUST return `SKIPPED`
   when the pool is not currently attached. `refresh_entitlements`
   is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Credential sanitisation.** `command` MUST NOT contain the
   password or activation key for `register`.
5. **Platform-unsupported writes.** On non-RHEL OSes, writes MUST
   either raise `NotImplementedError` or return `FAILED` with
   `detail="Red Hat Subscription Manager is a RHEL-only service."`
   The OS spec MUST pick one strategy and document it.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MUST raise
   `SubscriptionQueryError` for unexpected failures. An
   unregistered host MUST cause `get_registration_status` to
   return `RegistrationStatus(registered=False, ...)` rather than
   raise.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `SubscriptionActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or the verb is unsupported on the OS. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `RegistrationCredentials` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `username` | `str \| None` | Red Hat account username, if using username / password flow. |
| `password` | `str \| None` | Red Hat account password, if using username / password flow. |
| `activation_key` | `str \| None` | Activation key, if using key-based flow. |
| `organization_id` | `str \| None` | Organisation identifier when required by the flow. |
| `server_url` | `str \| None` | Override for the subscription server URL. |
| `auto_attach` | `bool` | Whether to auto-attach on register. |

### `SubscriptionPool` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `pool_id` | `str` | Pool identifier. |
| `name` | `str` | Product / pool name. |
| `sku` | `str \| None` | SKU identifier. |
| `quantity` | `int \| None` | Pool quantity. |
| `available` | `int \| None` | Currently available entitlements in the pool. |
| `ends_at` | `datetime \| None` | Pool expiration, UTC. |

### `AttachedSubscription` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `pool_id` | `str` | Pool identifier. |
| `name` | `str` | Product / pool name. |
| `serial` | `str` | Entitlement serial. |
| `starts_at` | `datetime \| None` | Entitlement start, UTC. |
| `ends_at` | `datetime \| None` | Entitlement end, UTC. |

### `RegistrationStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `registered` | `bool` | Whether the host is registered. |
| `identity` | `str \| None` | Consumer identity (UUID), when registered. |
| `organization_id` | `str \| None` | Organisation id, when registered. |
| `overall_status` | `str` | Native overall status token (`"Current"`, `"Insufficient"`, `"Invalid"`, `"Unknown"`). |

### `SubscriptionActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `SubscriptionActionStatus` | Outcome category. |
| `action` | `str` | Short identifier (e.g., `"register"`, `"attach:<pool>"`). |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed, sanitised. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `SubscriptionQueryError` | A read fails unexpectedly on a supported OS. |
| `SubscriptionUnavailableError` | The OS implementation chooses the raising strategy for unsupported OSes. |

### `SubscriptionManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |

---

## Scope Mapping

Subscription management has no natural scope parameter — it is
host-wide. The abstract verbs map to each OS's native
entitlement facility.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `subscription-manager` | Canonical. |
| Ubuntu | N/A (Ubuntu Pro is a different surface) | OPTIONAL; returns `FAILED` or raises. |
| macOS | N/A | OPTIONAL; returns `FAILED` or raises. |
| Windows | N/A | OPTIONAL; returns `FAILED` or raises. |
| UEFI | N/A | Does not apply. |

Each non-RHEL OS spec MUST include a Scope-Mapping section
stating its chosen strategy (raise vs `FAILED`).

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL; N/A elsewhere for this contract. |
| Credential transport | Credentials MUST flow on stdin / env, never on argv. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>SubscriptionManager
                │
                │  .run(argv, elevated=…, stdin=credentials, capture_output=True)
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

1. Accept an `ICommandRunner` and a `SubscriptionManagerConfig`
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
| `SubscriptionManager` | `UbuntuSubscriptionManager` | `MacosSubscriptionManager` | `WindowsSubscriptionManager` | `SubscriptionManager` |
| `SubscriptionManagerConfig` | `UbuntuSubscriptionManagerConfig` | `MacosSubscriptionManagerConfig` | `WindowsSubscriptionManagerConfig` | `SubscriptionManagerConfig` |
| `SubscriptionActionStatus` | `UbuntuSubscriptionActionStatus` | `MacosSubscriptionActionStatus` | `WindowsSubscriptionActionStatus` | `SubscriptionActionStatus` |
| `SubscriptionActionResult` | `UbuntuSubscriptionActionResult` | `MacosSubscriptionActionResult` | `WindowsSubscriptionActionResult` | `SubscriptionActionResult` |
| `RegistrationCredentials` | `UbuntuRegistrationCredentials` | `MacosRegistrationCredentials` | `WindowsRegistrationCredentials` | `RegistrationCredentials` |
| `SubscriptionPool` | `UbuntuSubscriptionPool` | `MacosSubscriptionPool` | `WindowsSubscriptionPool` | `SubscriptionPool` |
| `AttachedSubscription` | `UbuntuAttachedSubscription` | `MacosAttachedSubscription` | `WindowsAttachedSubscription` | `AttachedSubscription` |
| `RegistrationStatus` | `UbuntuRegistrationStatus` | `MacosRegistrationStatus` | `WindowsRegistrationStatus` | `RegistrationStatus` |
| `SubscriptionQueryError` | `UbuntuSubscriptionQueryError` | `MacosSubscriptionQueryError` | `WindowsSubscriptionQueryError` | `SubscriptionQueryError` |
| `SubscriptionUnavailableError` | `UbuntuSubscriptionUnavailableError` | `MacosSubscriptionUnavailableError` | `WindowsSubscriptionUnavailableError` | `SubscriptionUnavailableError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `SubscriptionActionResult` sequence when
  driven by a real runner with aspects attached, modulo
  retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb (RHEL only).
2. One idempotency test per applicable write verb proving
   `SKIPPED` on matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_pools(available=True)` parser test covering multiple
   pools.
5. One `list_attached_subscriptions` parser test.
6. One `get_registration_status` parser test for a registered and
   an unregistered host.
7. One credential-sanitisation test proving `command` does not
   contain the password on `register`.
8. For OPTIONAL-OS implementations: one test per verb proving the
   documented "unsupported" strategy (raise vs `FAILED`).
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Insights-client / remediation playbooks (lives in
  `insights-management`).
- Satellite-specific registration flows beyond
  `RegistrationCredentials.server_url`.
- Red Hat repository enablement post-attach (lives in
  `repository-management`).
- Ubuntu Pro (`ua`) entitlement flows.
- Windows volume activation (`slmgr`) / KMS / MAK.
- macOS licence management.
- Custom facts / profile uploads.
- Consumer-type selection beyond the default host consumer.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **No cross-OS implementations exist.** This contract is
  RHEL-only by design; `subscription-manager`, the RHSM
  client, and the Red Hat content delivery network have no
  analog on Ubuntu (the closest is Ubuntu Pro / `ua`, which is
  out of scope for this contract), macOS, or Windows. Per-OS
  implementations on Ubuntu / macOS / Windows would return
  `FAILED` with stable detail tokens of the form
  `unsupported_on_host_os_<host>` documented in the contract —
  see the README "FAILED with stable detail token" convention
  and stable-detail-token catalog.
- **File I/O via `ICommandRunner`.** Any future implementation
  that touches `/etc/rhsm/rhsm.conf` or the Satellite-CA file
  drop on a non-RHEL host would route through the runner using
  `cat` / `tee` rather than a separate `IFileOperator`, per the
  README "Implementation Conventions" file-I/O section.
