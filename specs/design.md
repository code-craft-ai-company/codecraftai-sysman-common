# codecraftai-sysman-common Design

The package collapses two concerns into one place. First, the
cross-OS feature contracts live under `specs/contracts/` — one folder
per feature area (firewall-management, service-management,
package-management, …) plus an index `README.md`. Each contract pins
verb names, dataclass shapes, the canonical status enum, dry-run /
elevation invariants, and any OS-mapping rules. Second, the
`source/packages/ccai/sysman/common/featurebase.py` module
provides the shared Python building blocks: `BaseFeatureManager` with
its `_dispatch` / `_wrap_result` helpers, the `ActionStatus` enum,
the `FeatureConfig` and `FeatureActionResult` dataclasses, and the
UEFI-host-dispatch helpers (`detect_host_os`,
`normalise_override_host_os`, `_build_failed_unsupported`). Per-OS
sysman packages depend on this package and import the shared types
from `ccai.sysman.common.featurebase`; they never re-vendor the
file.

Two feature bases also live here, one per pattern. The
vpn-client-management base (`vpnclientmanagementbase.py`) is
*abstract*: it fixes the verb signatures and shared helpers, and every
per-OS package implements the verbs because the tools (apt vs brew vs
MSI, systemctl vs launchctl vs Service Control Manager) differ. The
python-environment-management base
(`pythonenvironmentmanagementbase.py`) is *concrete*: CPython's `venv`
module and `pip` behave identically on every OS, so every verb is
implemented once, and the only OS-varying concerns — interpreter
location inside the environment, default launcher, directory probe and
removal commands — are isolated behind a `PythonEnvironmentLayout`
strategy (`pythonenvironmentlayout.py`, with POSIX and Windows
implementations). Per-OS packages subclass the base, pick a layout, and
add an `ensure_prerequisites` verb that delegates to that OS's existing
package-management manager. See
`specs/python-environment-management-base/` for the base spec and
`specs/contracts/python-environment-management/contract.md` for the
contract.
