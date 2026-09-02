# codecraftai-sysman-common Tasks

The initial migration task migrated the cross-OS contracts out of
`codecraftai-interfaces/specs/sysman-contracts/` into
`codecraftai-sysman-common/specs/contracts/`, upstreamed the previously
vendored `featurebase.py` (which had been duplicated across the
Ubuntu, macOS, Windows, and UEFI sysman packages) into the canonical
location at `source/packages/ccai/sysman/common/featurebase.py`,
and re-pointed every per-OS sysman package's pyproject.toml and
Python imports at the new module. Ongoing tasks track changes to the
shared base classes (e.g., new status values, new helpers) and
contract updates that emerge as new per-OS implementations land.

## Phase 4 — python-environment-management base (landed 2026-09-01)

- [x] Author `specs/contracts/python-environment-management/contract.md`
  and register it in the contracts README (Layer 3 table, count,
  per-OS inventory, Convention 12 URL-userinfo channel).
- [x] Add `ccai.sysman.common.pythonenvironmentlayout` with
  `PythonEnvironmentLayout`, `PosixPythonEnvironmentLayout`,
  `WindowsPythonEnvironmentLayout`.
- [x] Add `ccai.sysman.common.pythonenvironmentmanagementbase` with
  the concrete shared verbs, `PythonEnvManagerConfig`,
  `PythonEnvActionResult`, `PythonEnvSpec`, `PythonEnvDeployResult`,
  `PythonEnvInfo`, `PythonPackageInfo`, `PythonEnvQueryError`.
- [x] Extend `commandredaction.redact_command` / `redact_text` with
  URL-userinfo redaction (`redact_url_userinfo`).
- [x] Author `specs/python-environment-management-base/` spec trio.
- [x] testbase suite `test_pythonenvironmentmanagementbase.py` (54
  tests) plus the legacy `unittest` mirror; URL-redaction tests in
  both redaction suites.
- [ ] Follow-up: once `BaseFeatureManager._dispatch` learns to
  surface `elevation_blocked`, drop the local `_dispatch_write` in
  the python-environment base in favour of the shared helper.
- [x] Update `codecraftai-books` volume 04 (README, chapters 1–4,
  `research/code-anchors.md`) and the series index for the new
  contract and the concrete-base pattern; reconciled the stale
  contract total (52, not 50 — `vpn-client-management` had never
  been counted) and the per-package file counts (2026-09-02).
