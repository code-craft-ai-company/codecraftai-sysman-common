# Requirements

## Introduction

The `vpn-client-management-base` feature provides `codecraftai-sysman-common` with the
OS-neutral abstract feature manager that per-OS subclasses extend to implement the
[vpn-client-management contract](../contracts/vpn-client-management/contract.md).

It exposes `VPNClientManagementBase`, a subclass of `BaseFeatureManager` that:

- Defines the abstract verbs `install_tailscale`, `install_twingate_connector`,
  `configure`, `bring_up`, `bring_down`, `status`, `uninstall`.
- Defines the shared `VPNProvider` enum, the `VPNActionStatus` enum, the
  `VPNActionResult` / `VPNClientStatus` dataclasses, the
  `VPNClientManagerConfig` dataclass, and the `VPNClientQueryError` exception.
- Provides shared helpers — `_validate_provider`, `_short_circuit_dry_run`,
  `_dispatch_write`, `_should_elevate` — used by every per-OS implementation.

The base class never invokes a command runner directly. Per-OS subclasses override
the abstract verbs and route all subprocess work through the injected
`ICommandRunner`. All behaviour-bearing operations accept an `aspects` parameter
that subclasses must forward to the runner.

---

## Requirements

### Requirement 1: Provide Shared Enums and Dataclasses

**User Story:** As a per-OS implementer, I want one canonical definition of
`VPNProvider`, `VPNActionStatus`, `VPNActionResult`, `VPNClientStatus`,
`VPNClientManagerConfig`, and `VPNClientQueryError`, so that OS-prefixed
types simply alias these shared shapes and the contract is enforced by
import rather than by review.

#### Acceptance Criteria

1. THE SYSTEM SHALL expose `VPNProvider`, `VPNActionStatus`, `VPNActionResult`,
   `VPNClientStatus`, `VPNClientManagerConfig`, and `VPNClientQueryError` from
   `ccai.sysman.common.vpnclientmanagementbase`.
2. THE SYSTEM SHALL match the field names and types declared in the contract
   exactly.
3. WHEN a per-OS subclass adds OS-specific fields to its config THE SYSTEM SHALL
   preserve `dry_run` and `elevated` with their contract-mandated defaults.

---

### Requirement 2: Define Abstract Verb Surface

**User Story:** As a per-OS implementer, I want a single base class to inherit
from that declares every contract verb as an abstract method, so that any
missing implementation surfaces as a `TypeError` at instantiation time rather
than as a runtime `AttributeError`.

#### Acceptance Criteria

1. THE SYSTEM SHALL declare `install_tailscale`, `install_twingate_connector`,
   `configure`, `bring_up`, `bring_down`, `status`, and `uninstall` as abstract
   methods on `VPNClientManagementBase`.
2. WHEN a subclass omits an abstract verb THE SYSTEM SHALL prevent instantiation
   via the standard `abc` machinery.
3. THE SYSTEM SHALL declare every abstract verb's signature with named-only
   parameters, full type hints, and an explicit return type per the contract.

---

### Requirement 3: Provide Provider Validation Helper

**User Story:** As a per-OS implementer, I want a single helper to reject
unsupported providers, so that every subclass gives the same `FAILED` shape
when asked to manage a provider it does not implement.

#### Acceptance Criteria

1. WHEN a subclass calls `_validate_provider(provider, supported)` with a
   provider not in `supported` THE SYSTEM SHALL return a `VPNActionResult` with
   `status=FAILED` and a `detail` describing which providers ARE supported.
2. WHEN the provider IS in `supported` THE SYSTEM SHALL return `None`,
   signalling the caller to proceed.

---

### Requirement 4: Provide Dry-Run Short-Circuit Helper

**User Story:** As a per-OS implementer, I want one helper that returns the
correct `DRY_RUN` result without touching the runner, so that every write verb
has identical dry-run semantics.

#### Acceptance Criteria

1. WHEN the manager config has `dry_run=True` THE SYSTEM SHALL return a
   `VPNActionResult` with `status=DRY_RUN`, the supplied `provider`, the
   supplied `detail`, and the supplied `command` populated.
2. WHEN dry-run is active THE SYSTEM SHALL NOT invoke the command runner.

---

### Requirement 5: Provide Elevation Helper

**User Story:** As a per-OS implementer, I want a single source of truth for
"should this command pass `elevated=True`", so that the contract's elevation
rule is honoured uniformly.

#### Acceptance Criteria

1. WHEN the verb kind is `WRITE` and the config has `elevated=True` THE SYSTEM
   SHALL return `True` from `_should_elevate(kind=WRITE)`.
2. WHEN the verb kind is `READ` THE SYSTEM SHALL return `False`, regardless of
   the config.
3. WHERE the runner is configured for elevation THE SYSTEM SHALL pass
   `elevated=True` for write operations.

---

### Requirement 6: Provide Shared Write Dispatch Helper

**User Story:** As a per-OS implementer, I want one helper that runs a write
command and maps the `RunResult` to a `VPNActionResult`, so that error
surfacing is uniform across providers and OSes.

#### Acceptance Criteria

1. WHEN the runner exits with code 0 THE SYSTEM SHALL return a
   `VPNActionResult` with `status=SUCCESS`, the exit code, stdout, stderr,
   and the executed `command`.
2. WHEN the runner exits non-zero THE SYSTEM SHALL return a `VPNActionResult`
   with `status=FAILED`, the exit code, stdout, stderr, and the executed
   `command`.
3. THE SYSTEM SHALL never raise from `_dispatch_write` for non-zero exits.

---

### Requirement 7: Idempotency Property — Install / Uninstall

**User Story:** As a per-OS implementer, I want the contract's idempotency
property formalised in the base layer, so that the property tests can be
shared across OS subclasses.

#### Acceptance Criteria

1. WHEN `install_tailscale(...)` is invoked twice in succession against the
   same host state THE SYSTEM SHALL return `SUCCESS` on the first call and
   `SKIPPED` on the second.
2. WHEN `uninstall(provider=...)` is invoked twice in succession against the
   same host state THE SYSTEM SHALL return `SUCCESS` on the first call and
   `SKIPPED` on the second.
3. WHEN `bring_up(...)` is invoked against an already-up tunnel with the same
   authkey/hostname/tags THE SYSTEM SHALL return `SKIPPED` without invoking
   the runner.

---

### Requirement 8: Aspects on Every Behaviour-Bearing Op

**User Story:** As a maintenance coordinator, I want every behaviour-bearing
verb to take an `aspects` parameter, so that timeouts, retries, and
persistence are controlled from the call site without modifying the manager.

#### Acceptance Criteria

1. THE SYSTEM SHALL accept an `aspects: Aspects` parameter on every abstract
   verb defined by the contract.
2. THE SYSTEM SHALL NOT apply any `@retry` or behaviour-modifying decorator
   to any verb on the base class or any subclass.
3. WHEN `aspects` is passed THE SYSTEM SHALL forward it to the runner verbatim.
