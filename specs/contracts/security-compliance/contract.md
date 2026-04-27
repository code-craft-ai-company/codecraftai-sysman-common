# Security-Compliance Contract

This is the cross-OS abstract contract for the **security-compliance**
feature. Every `automojo-sysman-*` package that ships a security-
compliance manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-security-compliance/`](../../../../../automojo-sysman-linux-redhat/specs/3-security-compliance/).
It runs SELinux status checks, file-permission audits, SSH-config
hardening, and world-writable / SUID / SGID discovery through an
`ICommandRunner` and an `IFileOperator`. This contract generalises
that shape for OSes whose compliance surface includes macOS
`profiles`, AppArmor, and Windows security baselines via
`secedit` / DSC.

---

## Scope

The security-compliance feature provides a pluggable check-runner
over a set of compliance profiles, plus read-and-remediate actions
for common hardening categories. It covers:

- Listing available compliance profiles.
- Running a named compliance profile end-to-end and producing a
  structured report.
- Applying a remediation for a specific finding.
- Reading and setting the active compliance baseline.
- Dry-run-aware remediation.
- Elevation for remediation; baseline queries and profile runs
  elevate per-check as needed.

The feature is executed exclusively through an `ICommandRunner` and
an `IFileOperator`.

---

## Verbs

Every OS implementation MUST expose a `SecurityComplianceManager`
class (the OS-prefixed variant — see §Naming) whose public surface
is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_profiles` | `() → list[ComplianceProfile]` | Read |
| `get_profile` | `(profile_name: str) → ComplianceProfile \| None` | Read |
| `run_compliance_profile` | `(profile_name: str) → ComplianceReport` | Read (audit-only) |
| `remediate` | `(finding_id: str) → SecurityComplianceActionResult` | Write |
| `remediate_all` | `(report: ComplianceReport) → list[SecurityComplianceActionResult]` | Write |
| `get_baseline` | `() → BaselineInfo` | Read |
| `set_baseline` | `(baseline_spec: BaselineSpec) → SecurityComplianceActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `remediate` MUST evaluate the finding's
   current compliance state and return `SKIPPED` when the system is
   already compliant. `set_baseline` MUST compare the supplied spec
   to the current baseline; matching state MUST return `SKIPPED`.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or file operator for remediation
   steps.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Remediation guard for irreversible states.** OS specs MUST
   document any baseline value whose `set_baseline` cannot be
   automated (e.g., setting SELinux to `DISABLED` on RHEL) and MUST
   return `FAILED` with an explanatory `message` for such cases
   rather than attempting it.
5. **Batch remediation.** `remediate_all` MUST iterate findings in
   deterministic order and return one result per attempted
   remediation. Compliance-already-met findings MUST be skipped
   (not reported) unless otherwise noted by the OS spec.

### Method-level invariants (reads)

1. **Elevation for audit reads.** Compliance checks may require
   elevation to inspect protected state (e.g., `/etc/shadow`, the
   Windows Security event log). The default policy is
   `elevated=True` for these reads; the OS spec MUST enumerate
   which checks bypass this default.
2. **Typed errors.** `run_compliance_profile` MUST NOT raise for
   individual check failures — those are captured in the report.
   Framework-level failures (unknown profile, unreadable baseline)
   MUST raise `SecurityComplianceError`.
3. **Deterministic ordering.** `run_compliance_profile` MUST
   evaluate checks in a stable, profile-defined order and MUST
   preserve that order in the report.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `SecurityComplianceActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The remediation ran and succeeded. |
| `FAILED` | The remediation ran and failed, or a precondition was not met. |
| `SKIPPED` | The system was already compliant or the finding was not applicable. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ComplianceSeverity` (enum)

| Value | Meaning |
|-------|---------|
| `LOW` | Informational / best-practice guidance. |
| `MEDIUM` | Should-fix; non-urgent. |
| `HIGH` | Should-fix; urgent. |
| `CRITICAL` | Must-fix; security-critical. |

### `ComplianceProfile` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Profile identifier. |
| `description` | `str` | Human-readable description. |
| `checks` | `list[ComplianceCheck]` | Checks this profile runs. |

### `ComplianceCheck` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `check_id` | `str` | Unique check identifier within its profile. |
| `description` | `str` | Human-readable description. |
| `check_type` | `str` | Native type discriminator. |
| `severity` | `ComplianceSeverity` | Severity when non-compliant. |
| `parameters` | `dict[str, Any]` | Type-specific parameters (expected value, file permission spec, etc.). |

### `ComplianceFinding` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `finding_id` | `str` | Stable identifier (profile + check). |
| `check_id` | `str` | The owning check. |
| `description` | `str` | Finding description. |
| `severity` | `ComplianceSeverity` | Severity. |
| `compliant` | `bool` | `True` when the system meets the check. |
| `actual` | `str \| None` | Human-readable actual state. |
| `expected` | `str \| None` | Human-readable expected state. |
| `remediable` | `bool` | Whether `remediate` can address this finding. |
| `error` | `str \| None` | Set when evaluation itself failed. |

### `ComplianceReport` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `profile_name` | `str` | The profile that was run. |
| `started_at` | `datetime` | UTC start. |
| `finished_at` | `datetime` | UTC finish. |
| `findings` | `list[ComplianceFinding]` | Ordered findings. |
| `total` | `int` | Total checks. |
| `compliant` | `int` | Count compliant. |
| `non_compliant` | `int` | Count non-compliant. |
| `errored` | `int` | Count with evaluation errors. |

### `BaselineSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Baseline identifier. |
| `settings` | `dict[str, str]` | Setting-key → expected-value mapping. |

### `BaselineInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Current baseline name. |
| `settings` | `dict[str, str]` | Effective settings. |
| `source` | `str \| None` | Where the baseline is stored. |

### `SecurityComplianceActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `SecurityComplianceActionStatus` | Outcome category. |
| `finding_id` | `str \| None` | Finding addressed, if applicable. |
| `target` | `str \| None` | Path / setting targeted. |
| `message` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `SecurityComplianceError` | Framework-level failures: unknown profile, unreadable baseline, unsupported check type. |

### `SecurityComplianceManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no remediation commands dispatch. |
| `elevated` | `bool` | `False` | When `True`, remediation passes `elevated=True`. |

---

## Profile Mapping

The abstract `profile_name` maps to each OS's native compliance
profile concept.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | Built-in profiles covering SELinux, file-permission sets, SSH hardening, world-writable / SUID discovery; may additionally leverage OpenSCAP datastream IDs. | Canonical. |
| Ubuntu | AppArmor-aware file-permission and SSH-hardening profiles; may leverage OpenSCAP datastream IDs where available. | — |
| macOS | Built-in profiles for `csrutil` / SIP, Gatekeeper, firewall state, and file-permission sets. `profiles` command can list MDM-managed configuration profiles. | The OS spec MUST state whether MDM profiles are included. |
| Windows | Built-in profiles for local security policy (`secedit`), BitLocker, Defender, and registry-based baselines. | Implementations MAY integrate with `Get-CimInstance -Class MSFT_DscConfigurationStatus` for DSC-based baselines. |
| UEFI | N/A | UEFI has its own security concepts (Secure Boot, variable locks) which MAY be surfaced by a separate UEFI-specific contract. The general security-compliance contract does not apply. |

Each OS spec MUST include a Profile-Mapping section enumerating the
profiles it ships and the `check_type` discriminators it supports.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, `remediate` / `set_baseline` | Pass `elevated=True`. |
| Config `elevated=True`, profile-run checks | Per-check elevation; most audit reads pass `elevated=True` because they inspect protected state. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>SecurityComplianceManager
                │
                ├── profile run dispatches per-check to runner / file-op
                └── remediate composes chmod/chown/setenforce/etc.
                     │
                     ▼
          ICommandRunner  /  IFileOperator
                │
        ┌───────┴────────┐
        ▼                ▼
  Local{Command,File}Runner   SSH{Command,File}Runner
                         │
                  aspects compose here
                         │
                         ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner`, an `IFileOperator`, and a
   `SecurityComplianceManagerConfig` in their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `SecurityComplianceManager` | `UbuntuSecurityComplianceManager` | `MacosSecurityComplianceManager` | `WindowsSecurityComplianceManager` | `SecurityComplianceManager` |
| `SecurityComplianceManagerConfig` | `UbuntuSecurityComplianceManagerConfig` | `MacosSecurityComplianceManagerConfig` | `WindowsSecurityComplianceManagerConfig` | `SecurityComplianceConfig` |
| `SecurityComplianceActionStatus` | `UbuntuSecurityComplianceActionStatus` | `MacosSecurityComplianceActionStatus` | `WindowsSecurityComplianceActionStatus` | `ComplianceActionStatus` (implicit) |
| `SecurityComplianceActionResult` | `UbuntuSecurityComplianceActionResult` | `MacosSecurityComplianceActionResult` | `WindowsSecurityComplianceActionResult` | `ComplianceActionResult` |
| `ComplianceSeverity` | `UbuntuComplianceSeverity` | `MacosComplianceSeverity` | `WindowsComplianceSeverity` | `ComplianceSeverity` |
| `ComplianceProfile` | `UbuntuComplianceProfile` | `MacosComplianceProfile` | `WindowsComplianceProfile` | `ComplianceProfile` (implicit via `ComplianceCheck` lists) |
| `ComplianceCheck` | `UbuntuComplianceCheck` | `MacosComplianceCheck` | `WindowsComplianceCheck` | `ComplianceCheck` |
| `ComplianceFinding` | `UbuntuComplianceFinding` | `MacosComplianceFinding` | `WindowsComplianceFinding` | `ComplianceCheckResult` |
| `ComplianceReport` | `UbuntuComplianceReport` | `MacosComplianceReport` | `WindowsComplianceReport` | `ComplianceReport` |
| `BaselineSpec` | `UbuntuBaselineSpec` | `MacosBaselineSpec` | `WindowsBaselineSpec` | — (RHEL uses inline dicts) |
| `BaselineInfo` | `UbuntuBaselineInfo` | `MacosBaselineInfo` | `WindowsBaselineInfo` | — |
| `SecurityComplianceError` | `UbuntuSecurityComplianceError` | `MacosSecurityComplianceError` | `WindowsSecurityComplianceError` | `SecurityQueryError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with mock runner and file operator and no aspects
  MUST produce the same `ComplianceReport` and
  `SecurityComplianceActionResult` outputs when driven by real
  backends with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip individual check results from
  "error" to a compliance determination when the underlying command
  retries to success.
- Persistence aspects MUST NOT mutate results.

---

## Tests

Each OS implementation MUST include at minimum:

1. One `list_profiles` test proving the built-in profiles are
   enumerated.
2. One `run_compliance_profile` test per supported `check_type`
   covering a compliant and a non-compliant case.
3. One `remediate` test per supported remediation proving correct
   command construction.
4. One idempotency test proving `remediate` returns `SKIPPED` when
   the system is already compliant.
5. One baseline round-trip test proving `set_baseline(spec)`
   followed by `get_baseline()` returns `spec.settings`.
6. One dry-run test for `remediate` and `set_baseline` proving no
   runner / file-operator side effects.
7. One `SecurityComplianceError` test for an unknown profile.
8. One framework-level test proving individual check exceptions are
   captured in the report rather than surfaced to the caller.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Full OpenSCAP / DISA STIG datastream evaluation.
- Microsoft DSC resource authoring.
- MDM profile installation (macOS `profiles install`).
- Signed-report / evidence-collection output.
- Attestation via TPM / Secure Enclave.
- Continuous-monitoring / agent-mode operation.
- Remediation rollback.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is structural.** Ubuntu wraps OpenSCAP
  (`oscap info` / `oscap xccdf eval` / `oscap xccdf eval
  --remediate`) against the Ubuntu SCAP Security Guide. macOS
  wraps the `macos_security` baseline shell scripts (per-profile
  `run_compliance.sh`, per-check `checks/<id>.sh`,
  per-remediation `remediate/<id>.sh`). Windows wraps `secedit`
  for Local Security Policy plus PowerShell for Defender /
  BitLocker / registry rules. The verb surface is identical;
  the underlying check-grammar is not.
- **`check_type` is per-OS.** Ubuntu rule findings carry an
  XCCDF rule id; macOS findings carry a `check_type` of
  `"script"` or `"profile_introspection"`; Windows findings
  carry `"secedit_inf"` / `"registry"` / `"defender"` /
  `"bitlocker"`. The contract's `Finding` shape is uniform;
  the discriminator field is OS-specific.
- **File I/O via `ICommandRunner`.** SCAP datastreams,
  `macos_security` baseline trees, results XML / JSON, and
  Windows INF export / import files all route through the
  runner using `cat` / `tee` / `Get-Content` / `Set-Content`
  rather than a separate `IFileOperator`. See the README
  "Implementation Conventions" file-I/O section.
- **Idempotency probes diverge.** Ubuntu re-checks via
  `oscap xccdf eval --rule <id>` before remediating; macOS
  re-checks via `bash <profile>/checks/<id>.sh`; Windows
  re-checks via the per-rule `Get-...` cmdlet matched to the
  `check_type`. Each per-OS spec documents its idempotency
  guard explicitly.
- **Windows `elevation_blocked: bool`.** `secedit /configure`
  / `Set-MpPreference` / `Enable-BitLocker` writes surface the
  structured Windows elevation extension. See the README
  "Implementation Conventions" elevation-blocked entry.
