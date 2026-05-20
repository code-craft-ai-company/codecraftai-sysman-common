# Implementation Plan — VPN Client Management Base

## Module and Types

- [x] 1. Create the `automojo.sysman.common.vpnclientmanagementbase` module.

- [x] 2. Define the `VPNProvider` enum (`TAILSCALE`, `TWINGATE`).

- [x] 3. Define the `VPNActionStatus` enum (`SUCCESS` / `FAILED` / `SKIPPED` / `DRY_RUN`).

- [x] 4. Define the `VPNActionResult` dataclass with all contract fields.

- [x] 5. Define the `VPNClientStatus` dataclass with all contract fields, including
  `peer_addresses: Dict[str, str]` defaulted via the no-mutable-default rule
  (use `None` + per-instance dict in `__post_init__`).

- [x] 6. Define the `VPNClientManagerConfig` dataclass (`dry_run`, `elevated`).

- [x] 7. Define the `VPNClientQueryError` exception class.

## Base Class

- [x] 8. Implement `VPNClientManagementBase(BaseFeatureManager, ABC)` with the
  constructor signature `(*, runner: ICommandRunner, config: Optional[VPNClientManagerConfig] = None)`.

- [x] 9. Declare the abstract verbs with full named-only signatures and return-type
  hints — `install_tailscale`, `install_twingate_connector`, `configure`,
  `bring_up`, `bring_down`, `status`, `uninstall`.

- [x] 10. Implement `_validate_provider(provider, supported)` returning either
  a `VPNActionResult(FAILED, ...)` or `None`.

- [x] 11. Implement `_short_circuit_dry_run(provider, command, detail)` returning
  a `VPNActionResult(DRY_RUN, ...)`.

- [x] 12. Implement `_should_elevate(kind)` returning the boolean per the contract
  truth table.

- [x] 13. Implement `_dispatch_write(provider, command, detail, aspects)` calling
  the runner and mapping the `RunResult` to `VPNActionResult`.

## Tests — Examples

- [x] 14. `test_validate_provider_passes_supported_returns_none`.

- [x] 15. `test_validate_provider_rejects_unsupported_returns_failed`.

- [x] 16. `test_short_circuit_dry_run_returns_dry_run_with_populated_fields`.

- [x] 17. `test_should_elevate_truth_table` (covers all four combinations).

- [x] 18. `test_dispatch_write_zero_exit_returns_success`.

- [x] 19. `test_dispatch_write_nonzero_exit_returns_failed`.

- [x] 20. `test_abstract_class_cannot_instantiate_without_overrides`.

- [x] 21. `test_dataclasses_roundtrip_asdict`.

## Tests — Property (hypothesis)

- [x] 22. `test_property_install_is_idempotent` — install twice; second call
  is `SKIPPED`. Generated input: any version string, any channel.

- [x] 23. `test_property_uninstall_is_idempotent` — same shape for uninstall.

- [x] 24. `test_property_bring_up_idempotent_on_matching_state` — when status
  already shows the desired hostname / tags, `bring_up` returns `SKIPPED`.

- [x] 25. `test_property_bring_down_idempotent_on_matching_state`.

- [x] 26. `test_property_dry_run_never_invokes_runner` — across generated
  command vectors, `dry_run=True` never invokes the mock runner.

- [x] 27. `test_property_elevation_truth_table` — for generated `(elevated, kind)`
  pairs the helper output matches the contract.

## Documentation

- [x] 28. Add Sphinx-style docstrings (`:param:`, `:returns:`, `:raises:`) on every
  abstract method and every helper.

- [x] 29. Cross-link the contract document from the module-level docstring.

## Follow-ups

- [x] 30. Update the sysman-common `README.md` to list `vpn-client-management-base`
  alongside the existing feature-base modules.
  Done: added a "VPN client management base" highlight to `README.rst` listing
  `VPNClientManagementBase` and its shared types alongside the other feature bases.

- [x] 31. Confirm per-OS implementations import `VPNClientManagementBase` and the
  shared types from this module (no re-vendoring).
  Confirmed: macOS, Windows, RHEL, and Ubuntu `vpnclientmanagement.py` all
  `from automojo.sysman.common.vpnclientmanagementbase import VPNClientManagementBase`
  and subclass it, and import the shared types (`VPNClientManagerConfig`,
  `VPNClientStatus`, `VPNClientQueryError`) from `automojo.sysman.common.*` — no
  re-vendoring.
