# automojo-sysman-common Design

The package collapses two concerns into one place. First, the
cross-OS feature contracts live under `specs/contracts/` — one folder
per feature area (firewall-management, service-management,
package-management, …) plus an index `README.md`. Each contract pins
verb names, dataclass shapes, the canonical status enum, dry-run /
elevation invariants, and any OS-mapping rules. Second, the
`source/packages/automojo/sysman/common/featurebase.py` module
provides the shared Python building blocks: `BaseFeatureManager` with
its `_dispatch` / `_wrap_result` helpers, the `ActionStatus` enum,
the `FeatureConfig` and `FeatureActionResult` dataclasses, and the
UEFI-host-dispatch helpers (`detect_host_os`,
`normalise_override_host_os`, `_build_failed_unsupported`). Per-OS
sysman packages depend on this package and import the shared types
from `automojo.sysman.common.featurebase`; they never re-vendor the
file.
