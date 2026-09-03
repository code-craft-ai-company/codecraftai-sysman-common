# Implementation Plan — python-environment-management base

Checked items (`[x]`) are implemented and covered by tests.  Unchecked
items (`[ ]`) identify remaining work.

## Module and Models

- [x] 1. Create `ccai.sysman.common.pythonenvironmentlayout` with
  `PythonEnvironmentLayout` (abstract), `PosixPythonEnvironmentLayout`,
  `WindowsPythonEnvironmentLayout`, and `escape_powershell_single_quoted`
- [x] 2. Create `ccai.sysman.common.pythonenvironmentmanagementbase`
- [x] 3. Define `PythonEnvActionStatus` (alias of `ActionStatus`)
- [x] 4. Define `PythonEnvManagerConfig` (dry_run, elevated, base_interpreter,
  index_url, extra_index_urls, trusted_hosts, pip_options, upgrade_pip,
  system_site_packages)
- [x] 5. Define `PythonEnvActionResult`, `PythonPackageInfo`, `PythonEnvInfo`,
  `PythonEnvSpec`, `PythonEnvDeployResult`
- [x] 6. Define `PythonEnvQueryError` with redacted `command`
- [x] 7. Extend `commandredaction` with `redact_url_userinfo` and wire it into
  `redact_command` and `redact_text`

## PythonEnvironmentManagementBase — Implemented

- [x] 8. `__init__` accepting runner + optional config; calls the abstract
  `_build_layout()`
- [x] 9. `create_environment` — two-layer validity probe, venv argv with
  interpreter precedence, optional post-create pip upgrade with failure message
- [x] 10. `remove_environment` — existence probe, layout remove argv
- [x] 11. `install_packages` — index/option argv, conservative satisfied probe,
  `--upgrade` bypass, empty-list guard
- [x] 12. `install_requirements` — `-r` / `-c` argv, never skips
- [x] 13. `uninstall_packages` — `pip uninstall -y`, none-present skip
- [x] 14. `upgrade_pip` — never skips
- [x] 15. `deploy` — ordered steps, short-circuit, aggregate status, spec overrides
- [x] 16. Read surface — `environment_exists`, `is_valid_environment`,
  `get_python_version`, `list_installed`, `get_package_info`,
  `is_package_installed`, `freeze`, `get_environment_info`
- [x] 17. `_dispatch_write` — thin wrapper over the shared `_dispatch` (elevation,
  redaction, `elevation_blocked` token all inherited)
- [x] 18. Requirement probe — `_parse_requirement`, `_clause_satisfied`,
  `_version_tuple`, `_normalise_name`

## Tests — Implemented (testbase, mirrored to unittest)

- [x] 19. Layout tests (POSIX, Windows, Windows quoting / executable)
- [x] 20. Data-model tests (config defaults, per-instance spec defaults, query
  error, abstract instantiation)
- [x] 21. `create_environment` × 8 (argv, no-upgrade, skipped, broken-recreate,
  dry-run, interpreter precedence, system-site flag, failure paths)
- [x] 22. `remove_environment` × 3
- [x] 23. `install_packages` × 7 (argv order, skipped, pin mismatch, upgrade
  bypass, empty guard, dry-run, redaction, failure mapping)
- [x] 24. `install_requirements` × 3, `uninstall_packages` × 3, `upgrade_pip` × 1
- [x] 25. `deploy` × 5 (ordering, short-circuit, all-skipped, overrides, dry-run)
- [x] 26. Read surface × 7
- [x] 27. Requirement probe × 5 (bare/extras, pins, ordering/compatible,
  defer-to-pip, markers)
- [x] 28. Elevation × 2 (reads never elevate, `elevation_blocked` token)
- [x] 29. URL-userinfo redaction × 5 in both redaction suites

## Gaps and Follow-ups

- [ ] 30. Property-based tests (hypothesis via `ccai.testbase.properties`) for the
  requirement probe and the deploy aggregate, once the property-test harness is
  green-verified in a rehomed environment
- [x] 31. Route `_dispatch_write` through `BaseFeatureManager._dispatch`; the
  shared helper now surfaces `elevation_blocked` (2026-09-02)
- [x] 32. Ownership hand-over after an elevated create (2026-09-02): `set_owner` /
  `get_owner` verbs, `PythonEnvSpec.owner`, applied as the final `deploy` step;
  layout gains `build_query_owner_argv` / `build_set_owner_argv` /
  `normalise_owner` / `supports_owner_group`, with `BsdPythonEnvironmentLayout`
  for macOS because BSD `stat` differs from GNU.  Kept in this feature rather
  than delegated to `acl-management`: it is one recursive chown on a path this
  feature already owns, and delegating would thread a second manager and its
  config through every per-OS subclass for a single argv.
- [ ] 33. Hash-checking mode (`--require-hashes`) and lock-file support as an
  extension
- [x] 34. Update `codecraftai-books` volume 04 for the new contract and the
  concrete-base pattern (2026-09-02)
