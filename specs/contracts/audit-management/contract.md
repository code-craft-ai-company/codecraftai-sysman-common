# Audit-Management Contract

This is the cross-OS abstract contract for the **audit-management**
feature. Every `automojo-sysman-*` package that ships an audit
manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-audit-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-audit-management/).
It wraps `auditctl`, `augenrules`, `ausearch`, `aureport`, and
direct edits to `/etc/audit/auditd.conf` and
`/etc/audit/rules.d/` through an `ICommandRunner` and
`IFileOperator`. This contract generalises the verb set for OSes
whose audit surface is the Linux Audit subsystem, the BSD audit
subsystem on macOS (`audit`, `praudit`, `auditreduce`), or the
Windows auditing subsystem (`auditpol`, `Get-WinEvent -LogName
Security`).

---

## Scope

The audit-management feature provides idempotent, auditable
control over a host's security-auditing subsystem. It covers:

- Enabling and disabling auditing globally.
- Adding and removing individual audit rules keyed by a
  deterministic rule identifier.
- Listing the currently active rule set.
- Querying the audit-subsystem status (running state, kernel
  flags, rate limits where applicable).
- Searching audit events with structured filters (time, event
  type, principal, key).
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS's audit
  records are themselves access-controlled (e.g., Windows
  Security channel).

The feature is executed exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` for file-backed rule
stores; the established pattern is to route file I/O through
`ICommandRunner` using OS-native file utilities. See the README
"Implementation Conventions" section.

---

## Verbs

Every OS implementation MUST expose an `AuditManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_rule` | `(spec: AuditRuleSpec) → AuditActionResult` | Write |
| `remove_rule` | `(rule_id: str) → AuditActionResult` | Write |
| `list_rules` | `() → list[AuditRule]` | Read |
| `enable_auditing` | `() → AuditActionResult` | Write |
| `disable_auditing` | `() → AuditActionResult` | Write |
| `get_audit_status` | `() → AuditStatus` | Read |
| `search_events` | `(query: AuditEventQuery) → list[AuditEvent]` | Read |
| `reload_rules` | `() → AuditActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_rule` MUST return `SKIPPED` when a
   rule with the same `rule_id` and the same normalised body is
   already present. `remove_rule` MUST return `SKIPPED` when the
   rule_id is not present. `enable_auditing` and
   `disable_auditing` MUST return `SKIPPED` when the subsystem is
   already in the requested state. `reload_rules` is operational
   and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or file operator.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Persistence.** Where the underlying subsystem distinguishes
   runtime rules from persistent rules (Linux `auditctl` vs
   `rules.d/`), writes MUST persist the rule to the on-disk store
   and ALSO best-effort apply the rule to the running subsystem.
   OS specs MUST document any deviation.
5. **Immutable mode.** On OSes where the audit subsystem supports
   a "locked" / immutable mode that forbids further rule changes,
   writes MUST return `FAILED` with a descriptive `detail` rather
   than invoking the command that would fail opaquely.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner unless the OS's audit store requires elevation (e.g.,
   Windows Security event log). OS specs MUST document the
   exception.
2. **Typed errors.** `list_rules`, `get_audit_status`, and
   `search_events` MUST raise `AuditQueryError` for unexpected
   failures.
3. **Pure parsing.** All parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `AuditActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `AuditRuleSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `rule_id` | `str` | Deterministic identifier. On Linux this is the `-k` key; on macOS this is the event source name; on Windows this is the `auditpol` subcategory name. |
| `subsystem` | `str` | Native rule-subsystem / class (e.g., `"syscall"`, `"path"`, `"file"`, `"Success,Failure"`). |
| `expression` | `str` | Tool-native rule body as a single normalised string. |
| `enabled` | `bool` | When `False`, the rule is recorded but not applied. |

### `AuditRule` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `rule_id` | `str` | Rule identifier. |
| `subsystem` | `str` | Native rule-subsystem. |
| `expression` | `str` | Tool-native rule body. |
| `enabled` | `bool` | Current enabled / applied state. |
| `source` | `str \| None` | On-disk origin of the rule (file path on Linux; OS-specific elsewhere). |

### `AuditActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `AuditActionStatus` | Outcome category. |
| `rule_id` | `str \| None` | Rule identifier, when applicable. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `AuditStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `running` | `bool` | Whether the audit subsystem is active. |
| `enabled` | `bool` | Whether auditing is globally enabled. |
| `locked` | `bool` | Whether the subsystem is in immutable / locked mode. |
| `rule_count` | `int` | Number of currently active rules. |
| `backlog` | `int \| None` | Current event backlog (Linux only; `None` when N/A). |
| `lost_events` | `int \| None` | Count of dropped events since boot (when known). |

### `AuditEventQuery` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `since` | `str \| None` | Lower time bound (ISO-8601 or native relative token). |
| `until` | `str \| None` | Upper time bound. |
| `event_type` | `str \| None` | Event-type filter (e.g., `"SYSCALL"`, `"Logon"`). |
| `principal` | `str \| None` | User or SID filter. |
| `rule_id` | `str \| None` | Filter by rule identifier. |
| `limit` | `int \| None` | Maximum events to return. |

### `AuditEvent` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | `str` | Native event identifier. |
| `timestamp` | `str` | ISO-8601 UTC timestamp. |
| `event_type` | `str` | Event type / category. |
| `principal` | `str \| None` | Associated user / SID when known. |
| `rule_id` | `str \| None` | Rule key that matched, when known. |
| `raw` | `str` | Full raw event body. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `AuditQueryError` | A read fails unexpectedly. |
| `AuditImmutableError` | A write is attempted while the subsystem is in locked / immutable mode. |

### `AuditManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Rule-Identifier Mapping

The abstract `rule_id` MUST map deterministically to each OS's
native addressing scheme:

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `-k <key>` on an audit rule under `/etc/audit/rules.d/` | Canonical. The `rule_id` MUST be unique across the union of rule files. |
| Ubuntu | Same as RHEL | — |
| macOS | `audit_control` / `audit_event` flag tuple; `rule_id` is the logical event-class name (e.g., `"fr"`, `"lo"`, `"ad"`) | The OS spec MUST state how multiple events collapse into a single `rule_id`. |
| Windows | `auditpol` subcategory name (e.g., `"Logon"`, `"File System"`) paired with a Success/Failure flag set | The `rule_id` MUST equal the subcategory; `expression` MUST encode the Success/Failure flags. |
| UEFI | N/A | UEFI has no audit subsystem. The audit-management contract does not apply. |

Each OS spec MUST include a Rule-Identifier Mapping section.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`, except where the OS requires it to read audit records. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>AuditManager
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

1. Accept an `ICommandRunner` and an `AuditManagerConfig` in
   their constructor. Implementations whose rule store is a
   plain file MAY also accept an `IFileOperator`, though the
   established pattern is to route file I/O through the runner.
2. Never construct their own subprocess.
3. Not hold state across method calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `AuditManager` | `UbuntuAuditManager` | `MacosAuditManager` | `WindowsAuditManager` | `AuditManager` |
| `AuditManagerConfig` | `UbuntuAuditManagerConfig` | `MacosAuditManagerConfig` | `WindowsAuditManagerConfig` | `AuditManagerConfig` |
| `AuditActionStatus` | `UbuntuAuditActionStatus` | `MacosAuditActionStatus` | `WindowsAuditActionStatus` | `AuditActionStatus` |
| `AuditActionResult` | `UbuntuAuditActionResult` | `MacosAuditActionResult` | `WindowsAuditActionResult` | `AuditActionResult` |
| `AuditRuleSpec` | `UbuntuAuditRuleSpec` | `MacosAuditRuleSpec` | `WindowsAuditRuleSpec` | `AuditRuleSpec` |
| `AuditRule` | `UbuntuAuditRule` | `MacosAuditRule` | `WindowsAuditRule` | `AuditRule` |
| `AuditStatus` | `UbuntuAuditStatus` | `MacosAuditStatus` | `WindowsAuditStatus` | `AuditKernelState` |
| `AuditEventQuery` | `UbuntuAuditEventQuery` | `MacosAuditEventQuery` | `WindowsAuditEventQuery` | `AuditEventQuery` |
| `AuditEvent` | `UbuntuAuditEvent` | `MacosAuditEvent` | `WindowsAuditEvent` | `AuditEvent` |
| `AuditQueryError` | `UbuntuAuditQueryError` | `MacosAuditQueryError` | `WindowsAuditQueryError` | `AuditQueryError` |
| `AuditImmutableError` | `UbuntuAuditImmutableError` | `MacosAuditImmutableError` | `WindowsAuditImmutableError` | `AuditImmutableError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `AuditActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` when the
   desired state is already in effect.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_audit_status` parser test covering representative
   output.
5. One `list_rules` parser test covering a representative rule
   set.
6. One `search_events` parser test covering multiple event types
   and a bounded result limit.
7. One immutable-mode test proving `AuditImmutableError` is
   raised (or `FAILED` with a descriptive detail per OS spec)
   when the subsystem is locked.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Audit-log rotation / retention (see `log-management`).
- Remote audit-event shipping (see `remote-log-forwarding`).
- Audit-record signing / HMAC verification.
- Windows SACL management at the object level (see
  `acl-management` extensions).
- Audit-dispatcher plugin configuration (Linux `audispd`).
- Forensic tooling that reconstructs process trees from audit
  records.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Concept divergence is sharper than other features.** Linux
  `auditd` rules, macOS BSM `audit_control`, and Windows
  `auditpol` policy categories do not share a common rule shape.
  Each OS spec documents its own `<Os>AuditRuleSpec` /
  `<Os>AuditRule` field set; cross-OS callers do not expect
  field-level portability beyond the contract minimum.
- **`reload_rules` is a no-op on Windows.** `auditpol /set` is
  itself the persistent write — there is no reload step to surface.
  The Windows manager returns `SKIPPED` with a stable detail
  token explaining the no-op rather than `FAILED`.
- **File I/O via `ICommandRunner`.** Rule-file reads/writes route
  through the runner via `cat` / `tee` / `Get-Content` / `Set-Content`
  rather than a separate `IFileOperator`.
