# Insights-Management Contract

This is the cross-OS abstract contract for the
**insights-management** feature. Every `codecraftai-sysman-*`
package that ships an Insights manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-insights-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-insights-management/).
It wraps the `insights-client` CLI and direct edits to
`/etc/insights-client/insights-client.conf` and
`/etc/insights-client/tags.yaml` through an `ICommandRunner` and
`IFileOperator`.

> **Red Hat Insights is a RHEL-only cloud service.** The
> `insights-client` tool and the corresponding cloud backend are
> provided by Red Hat and intended for Red Hat Enterprise Linux
> hosts.
>
> **Other OS implementations are NOT required.** Ubuntu, macOS,
> and Windows MAY raise `NotImplementedError` from the manager
> constructor, or MAY ship a stub manager whose verbs return
> `InsightsActionResult(status=FAILED, detail="Red Hat Insights
> is a RHEL-only cloud service.")`. The OS spec MUST state
> explicitly which approach is taken; either is conformant.
> Shipping an actual working implementation on non-RHEL is NOT
> required for contract conformance on this feature.

---

## Scope

The insights-management feature provides idempotent, auditable
control over a host's registration with Red Hat Insights (or,
on other OSes, a clean "unsupported" surface). It covers:

- Registering the host with Insights.
- Unregistering the host.
- Triggering an on-demand upload of the Insights payload.
- Querying the current registration status.
- Listing recent findings from the Insights service, where the
  client surfaces them locally.
- Retrieving the details of a single finding.
- Applying / remediating a finding via an Insights playbook,
  where supported.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

---

## Verbs

Every OS implementation that ships an Insights manager MUST
expose an `InsightsManager` class (the OS-prefixed variant — see
§Naming) whose public surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `register_host` | `(spec: InsightsRegistrationSpec) → InsightsActionResult` | Write |
| `unregister_host` | `() → InsightsActionResult` | Write |
| `upload_report` | `() → InsightsActionResult` | Write |
| `get_registration_status` | `() → InsightsRegistrationStatus` | Read |
| `list_findings` | `() → list[InsightsFinding]` | Read |
| `get_finding_details` | `(finding_id: str) → InsightsFindingDetails \| None` | Read |
| `remediate_finding` | `(finding_id: str) → InsightsActionResult` | Write |
| `get_version` | `() → str` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `register_host` MUST return `SKIPPED`
   when the host is already registered AND the supplied spec
   does not carry `force=True`. `unregister_host` MUST return
   `SKIPPED` when the host is not registered. `upload_report`
   and `remediate_finding` are operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner or file operator.
   Dry-run MUST block all cloud-contacting calls.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Precondition.** `upload_report` MUST return `FAILED` with
   a descriptive `detail` when the host is not registered, and
   MUST NOT dispatch the upload command.
5. **Platform unsupported.** On OSes that ship a stub manager,
   every verb MUST return `InsightsActionResult(status=FAILED,
   detail="Red Hat Insights is a RHEL-only cloud service.")`.
   Implementations MAY alternatively raise `NotImplementedError`
   from the constructor.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True`.
2. **Typed errors.** Reads MUST raise `InsightsQueryError` for
   unexpected failures. `get_finding_details` MUST return
   `None` for an unknown finding id rather than raise.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation that ships an Insights manager MUST
expose these dataclasses and enum, each prefixed with the OS name
(see §Naming).

### `InsightsActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, a precondition was not met, or the OS does not support Insights. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `InsightsRegistrationSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `display_name` | `str \| None` | Override display name reported to Insights. |
| `group` | `str \| None` | Inventory group assignment. |
| `tags` | `dict[str, str]` | Key / value tags to attach to the host. |
| `force` | `bool` | When `True`, re-register even if already registered. |

### `InsightsRegistrationStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `registered` | `bool` | Whether the host is currently registered. |
| `machine_id` | `str \| None` | Machine id reported to Insights. |
| `last_upload_at` | `str \| None` | ISO-8601 timestamp of last successful upload. |

### `InsightsFinding` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `finding_id` | `str` | Finding identifier as reported by the Insights service. |
| `title` | `str` | Short title. |
| `severity` | `str` | Native severity string (`"low"`, `"moderate"`, `"important"`, `"critical"`). |
| `category` | `str \| None` | Category (`"security"`, `"availability"`, `"performance"`, `"stability"`). |
| `created_at` | `str \| None` | ISO-8601 timestamp. |

### `InsightsFindingDetails` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `finding` | `InsightsFinding` | Summary fields. |
| `description` | `str` | Long description. |
| `remediation_available` | `bool` | Whether an Insights-shipped playbook exists. |
| `raw` | `str` | Verbatim detail text. |

### `InsightsActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `InsightsActionStatus` | Outcome category. |
| `finding_id` | `str \| None` | Finding acted upon, when applicable. |
| `machine_id` | `str \| None` | Machine id reported by the registration command. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `InsightsQueryError` | A read fails unexpectedly. |
| `InsightsNotInstalledError` | A verb assumes the Insights client is installed and it is not (RHEL / Ubuntu with the client). |
| `InsightsNotRegisteredError` | `upload_report` or `remediate_finding` is called when the host is not registered. |

### `InsightsManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Platform-Support Mapping

| OS | Support level | Notes |
|----|---------------|-------|
| Red Hat Enterprise Linux | Fully supported | Canonical. Wraps `insights-client`. |
| Ubuntu | Optional. Ubuntu is not an Insights target in the general case. If shipped, the implementation MAY wrap the Red Hat-provided `insights-client` package where available, otherwise MUST return `FAILED` with `detail="Red Hat Insights is a RHEL-only cloud service."`. | — |
| macOS | Not supported. MAY raise `NotImplementedError` from the constructor, or MAY ship a stub whose verbs return `FAILED` with the documented detail. | — |
| Windows | Not supported. MAY raise `NotImplementedError` from the constructor, or MAY ship a stub whose verbs return `FAILED` with the documented detail. | — |
| UEFI | N/A | UEFI has no cloud-reporting surface. The contract does not apply. |

Each OS spec MUST include a Platform-Support section stating its
level (fully supported / stub / `NotImplementedError`).

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL; not applicable on OSes that ship stubs. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>InsightsManager
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

All OS implementations that ship an Insights manager MUST:

1. Accept an `ICommandRunner` and an `InsightsManagerConfig` in
   their constructor. Implementations that edit the client's
   config or tags files MAY also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

Stub implementations MAY omit the runner / file-operator
injection as long as they still conform to the verb signatures
and return the documented stub result.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `InsightsManager` | `UbuntuInsightsManager` | `MacosInsightsManager` | `WindowsInsightsManager` | `InsightsManager` |
| `InsightsManagerConfig` | `UbuntuInsightsManagerConfig` | `MacosInsightsManagerConfig` | `WindowsInsightsManagerConfig` | `InsightsManagerConfig` |
| `InsightsActionStatus` | `UbuntuInsightsActionStatus` | `MacosInsightsActionStatus` | `WindowsInsightsActionStatus` | `InsightsActionStatus` |
| `InsightsActionResult` | `UbuntuInsightsActionResult` | `MacosInsightsActionResult` | `WindowsInsightsActionResult` | `InsightsActionResult` |
| `InsightsRegistrationSpec` | `UbuntuInsightsRegistrationSpec` | `MacosInsightsRegistrationSpec` | `WindowsInsightsRegistrationSpec` | `InsightsRegistrationSpec` |
| `InsightsRegistrationStatus` | `UbuntuInsightsRegistrationStatus` | `MacosInsightsRegistrationStatus` | `WindowsInsightsRegistrationStatus` | `InsightsState` |
| `InsightsFinding` | `UbuntuInsightsFinding` | `MacosInsightsFinding` | `WindowsInsightsFinding` | `InsightsFinding` |
| `InsightsFindingDetails` | `UbuntuInsightsFindingDetails` | `MacosInsightsFindingDetails` | `WindowsInsightsFindingDetails` | `InsightsFindingDetails` |
| `InsightsQueryError` | `UbuntuInsightsQueryError` | `MacosInsightsQueryError` | `WindowsInsightsQueryError` | `InsightsQueryError` |
| `InsightsNotInstalledError` | `UbuntuInsightsNotInstalledError` | `MacosInsightsNotInstalledError` | `WindowsInsightsNotInstalledError` | `InsightsNotInstalledError` |
| `InsightsNotRegisteredError` | `UbuntuInsightsNotRegisteredError` | `MacosInsightsNotRegisteredError` | `WindowsInsightsNotRegisteredError` | `InsightsNotRegisteredError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `InsightsActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

OS implementations that ship a working Insights manager MUST
include at minimum:

1. One command-construction test per write verb.
2. One idempotency test for `register_host` proving `SKIPPED`
   when already registered and `force=False`.
3. One `unregister_host` idempotency test proving `SKIPPED` when
   not registered.
4. One dry-run test per write verb proving no remote contact is
   made.
5. One `get_registration_status` parser test covering both
   registered and unregistered hosts.
6. One `list_findings` parser test covering multiple severities
   and categories.
7. One `InsightsNotRegisteredError` (or equivalent `FAILED`
   result per OS spec) test proving `upload_report` does not
   dispatch the upload command when unregistered.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

OS implementations that ship a stub MUST include:

1. One test per verb proving the documented stub result
   (`FAILED` with the "RHEL-only cloud service" detail, or
   constructor raising `NotImplementedError`).

OS implementations that omit the manager entirely are exempt.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- RHSM subscription management (see `subscription-management`).
- Satellite / capsule integration.
- Insights Advisor rule customisation.
- Compliance policy authoring (see `security-compliance`).
- Ansible Tower / AAP integration for remediation playbooks
  beyond the single-verb surface.
- Insights Drift baseline management.
- Web-console Insights views (see `cockpit-management`).

---

## Implementation Drift

No cross-OS implementations exist; Insights is an RHEL-only
cloud service. Stub implementations on Ubuntu, macOS, and Windows
(if shipped) return `FAILED` with stable detail tokens such as
`unsupported_on_host_os_<host>` per the README "Implementation
Conventions" stable-token catalog.
