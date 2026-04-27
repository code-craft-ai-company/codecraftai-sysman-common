# Maintenance-Reporting Contract

This is the cross-OS abstract contract for the **maintenance-reporting**
feature. Every `automojo-sysman-*` package that ships a maintenance
reporter MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/2-maintenance-reporting/`](../../../../../automojo-sysman-linux-redhat/specs/2-maintenance-reporting/).
Maintenance-reporting is a Layer-2 feature: it is platform-agnostic
by nature. The original RHEL design used `IFileOperator` to persist
its serialised output; the established cross-OS pattern is to route
file I/O through `ICommandRunner` using OS-native file utilities.
See the README "Implementation Conventions". Every OS
implementation exposes the same verbs and result shapes — the only
per-OS variation is the file-write seam used.

---

## Scope

The maintenance-reporting feature provides a structured,
serialisable record of a maintenance session. It covers:

- Starting a session with an identifier, host, and description.
- Recording individual action and query outcomes from Layer-3
  managers.
- Filtering recorded actions by status and by feature name.
- Finalising the session and computing overall status.
- Producing summary counts of action outcomes.
- Emitting the report in JSON and plain-text formats.
- Writing the report to a file through `ICommandRunner` (or,
  optionally, `IFileOperator`).
- Dry-run-aware persistence: `write_report` short-circuits without
  touching the OS when `dry_run=True`.

The feature is executed exclusively through an `ICommandRunner`
(or, optionally, an `IFileOperator`) from `automojo-interfaces`.
No direct filesystem writes occur inside the module.

---

## Verbs

Every OS implementation MUST expose a `MaintenanceReport` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `begin_session` | `(run_id: str, host: str, description: str \| None) → None` | Write |
| `add_action` | `(record: ActionRecord) → None` | Write |
| `record_query` | `(record: ActionRecord) → None` | Write |
| `record_error` | `(feature: str, operation: str, error: str) → None` | Write |
| `end_session` | `() → None` | Write |
| `summary_counts` | `() → ReportSummary` | Read |
| `actions_by_status` | `(*statuses: ActionStatus) → list[ActionRecord]` | Read |
| `actions_by_feature` | `(feature: str) → list[ActionRecord]` | Read |
| `to_json` | `(indent: int \| None) → str` | Read |
| `to_text` | `() → str` | Read |
| `emit_report` | `(path: str, format: ReportFormat) → ReportWriteResult` | Write |

Both `add_action` and `record_query` append to the same action list;
`record_query` is provided as a discoverable alias for read-operation
outcomes. Implementations MAY implement them as the same method.

### Method-level invariants (writes)

1. **In-memory accumulation.** `begin_session`, `add_action`,
   `record_query`, and `record_error` MUST NOT perform I/O. They
   mutate only in-memory state.
2. **Insertion order preserved.** Actions MUST appear in the order
   they were added.
3. **Automatic timestamps.** An `ActionRecord` without an explicit
   `timestamp` MUST be stamped with the current UTC time at add
   time. A `_clock` injection point MUST exist for tests.
4. **Finalisation idempotency.** `end_session` MAY be called
   multiple times; each call re-evaluates `overall_status` based on
   the current action list.
5. **Dry-run short-circuit for `emit_report`.** When `dry_run=True`,
   the file operator MUST NOT be invoked and `ReportWriteResult`
   MUST be returned with `success=True` and `dry_run=True`.
6. **Write-error surface.** File-write failures MUST be returned as
   `ReportWriteResult` with `success=False` and `error` populated.
   `emit_report` MUST NOT raise for routine I/O failures.

### Method-level invariants (reads)

1. **No I/O.** `summary_counts`, `actions_by_status`,
   `actions_by_feature`, `to_json`, and `to_text` MUST NOT touch the
   file operator or the runner.
2. **Stable ordering.** Filter methods MUST preserve insertion order.
3. **Deterministic serialisation.** `to_json` with the same indent
   and the same state MUST produce the same string on successive
   calls.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `ActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The action completed successfully. |
| `FAILED` | The action ran and failed. |
| `SKIPPED` | An idempotency guard short-circuited the action. |
| `DRY_RUN` | A dry-run short-circuited the action. |

No OS-specific additions are allowed in this enum — the reporter is
platform-agnostic.

### `ReportFormat` (enum)

| Value | Meaning |
|-------|---------|
| `JSON` | JSON serialisation (UTF-8, indentable). |
| `TEXT` | Plain-text serialisation (line-oriented, human-readable). |
| `YAML` | Optional; implementations MAY implement it but are not required to. |
| `MARKDOWN` | Optional; implementations MAY implement it but are not required to. |

Implementations that do not support `YAML` or `MARKDOWN` MUST return
`ReportWriteResult(success=False, error=...)` when asked to emit
them rather than raise.

### `ActionRecord` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `feature` | `str` | Layer-3 feature name, e.g. `"package-management"`. |
| `operation` | `str` | Verb name, e.g. `"install_package"`. |
| `status` | `ActionStatus` | Outcome category. |
| `detail` | `str \| None` | Human-readable description of what happened. |
| `error` | `str \| None` | Error text / captured stderr when status is `FAILED`. |
| `duration_seconds` | `float \| None` | Wall-clock duration. |
| `timestamp` | `datetime \| None` | UTC timestamp; auto-set at construction when `None`. |

### `ReportSummary` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `total` | `int` | Total actions recorded. |
| `succeeded` | `int` | Count of `SUCCESS` records. |
| `failed` | `int` | Count of `FAILED` records. |
| `skipped` | `int` | Count of `SKIPPED` records. |
| `dry_run` | `int` | Count of `DRY_RUN` records. |

### `ReportWriteResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Whether the write (or dry-run short-circuit) succeeded. |
| `path` | `str` | The target path. |
| `dry_run` | `bool` | Whether the write was dry-run-synthetic. |
| `error` | `str \| None` | Populated when `success=False`. |

### `MaintenanceSession` (dataclass)

Top-level report state, exposed by the reporter.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Caller-supplied run identifier. |
| `host` | `str` | Hostname or system identifier. |
| `description` | `str \| None` | Caller-supplied description. |
| `started_at` | `datetime` | UTC start time. |
| `finished_at` | `datetime \| None` | UTC end time set by `end_session`. |
| `overall_status` | `ActionStatus \| None` | Computed by `end_session`. |
| `actions` | `list[ActionRecord]` | Ordered action list. |

### `MaintenanceReportConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, `emit_report` never writes. |

### Exceptions

Maintenance-reporting does not define typed query exceptions.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| In-memory operations (begin, add, end, queries, serialisers) | MUST NOT request elevation. |
| `emit_report` | Delegates to `IFileOperator`; the file operator's caller-supplied `elevated` decision is passed through. The reporter MUST NOT embed elevation policy. |
| OS mechanism | Whatever the file operator uses (`sudo tee` on Unix-likes, Administrator ACL on Windows, EFI System Partition access under UEFI). |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects file operator, config
                ▼
        <Os>MaintenanceReport
                │
                │  begin/add/end in memory
                │  emit_report(path, format) → file_operator.write_text(...)
                ▼
          IFileOperator
                │
        ┌───────┴────────┐
        ▼                ▼
  LocalFileOperator    SSHFileOperator
        │                │
        └────────┬───────┘
                 │  aspects compose here
                 ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `IFileOperator` and a `MaintenanceReportConfig` in
   their constructor.
2. Never construct their own file handle or temp file outside the
   operator.
3. Allow a `_clock` callable to be injected for deterministic tests.
4. Be safe under any aspect composition attached to the file
   operator.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `MaintenanceReport` | `UbuntuMaintenanceReport` | `MacosMaintenanceReport` | `WindowsMaintenanceReport` | `MaintenanceReport` |
| `MaintenanceReportConfig` | `UbuntuMaintenanceReportConfig` | `MacosMaintenanceReportConfig` | `WindowsMaintenanceReportConfig` | `MaintenanceReportConfig` |
| `ActionStatus` | `UbuntuActionStatus` | `MacosActionStatus` | `WindowsActionStatus` | `ActionStatus` |
| `ActionRecord` | `UbuntuActionRecord` | `MacosActionRecord` | `WindowsActionRecord` | `ActionRecord` |
| `ReportSummary` | `UbuntuReportSummary` | `MacosReportSummary` | `WindowsReportSummary` | `ReportSummary` |
| `ReportWriteResult` | `UbuntuReportWriteResult` | `MacosReportWriteResult` | `WindowsReportWriteResult` | `ReportWriteResult` |
| `ReportFormat` | `UbuntuReportFormat` | `MacosReportFormat` | `WindowsReportFormat` | `ReportFormat` |
| `MaintenanceSession` | `UbuntuMaintenanceSession` | `MacosMaintenanceSession` | `WindowsMaintenanceSession` | `MaintenanceSession` |

Because the reporter is platform-agnostic, some consumers MAY choose
to use a single shared type; such reuse is permitted but any exposed
names MUST match the rows above.

---

## Aspect Composition

Aspect behavior MUST be transparent to the reporter:

- A reporter tested with a `MockFileOperator` and no aspects MUST
  produce the same `ReportWriteResult` sequence when driven by a real
  file operator with `PersistenceAspect`, `RetryAspect`, and
  `TimeoutAspect` attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `success` from `False` to
  `True`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. A begin/add/end test proving insertion order, timestamp default,
   and `overall_status` computation.
2. A summary-counts test per status value.
3. A filter test for `actions_by_status` and `actions_by_feature`.
4. A JSON-serialisation test that round-trips timestamps through
   `json.loads`.
5. A text-serialisation test asserting key substrings (run id, host,
   status labels).
6. An `emit_report` success test that asserts `IFileOperator.write_text`
   was called with the right path and content.
7. An `emit_report` dry-run test proving the file operator is not
   invoked.
8. An `emit_report` failure test verifying `success=False` and
   `error` are populated on write exception.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Streaming / chunked report emission for very large sessions.
- HTML or PDF output formats.
- Report templating / customisable section ordering.
- Correlation with external ticketing or incident systems.
- Multi-host aggregation of reports (that is a coordinator concern).
- Structured-log emission in parallel with the report (implementations
  MAY pipe to syslog, ETW, or the macOS unified log but are not
  required to).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`ICommandRunner` instead of `IFileOperator`.** Per-OS
  implementations route the report write through
  `ICommandRunner` using `tee` / `Set-Content` rather than a
  separate `IFileOperator`. See the README "Implementation
  Conventions" file-I/O convention.
