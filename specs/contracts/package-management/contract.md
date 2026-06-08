# Package-Management Contract

This is the cross-OS abstract contract for the **package-management**
feature. Every `codecraftai-sysman-*` package that ships a package
manager MUST honor this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-package-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-package-management/).
It uses `dnf` and `rpm` through an `ICommandRunner`. This contract
generalises the verb set for OSes whose native package manager is
`apt`, `brew`, `pkg`, `winget`, `Chocolatey`, or the Microsoft
Store.

---

## Scope

The package-management feature provides idempotent, auditable
control over installed software packages. It covers:

- Installing a package at the latest version or at a pinned
  version.
- Removing an installed package.
- Upgrading a package to its latest version.
- Upgrading all installed packages.
- Querying a package's installed state.
- Listing all installed packages.
- Listing packages with available upgrades.
- Refreshing package-manager metadata.
- Installing a package from a local file.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `PackageManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `install_package` | `(name: str, version: str \| None) → PackageActionResult` | Write |
| `remove_package` | `(name: str) → PackageActionResult` | Write |
| `upgrade_package` | `(name: str, version: str \| None) → PackageActionResult` | Write |
| `upgrade_all` | `() → PackageActionResult` | Write |
| `is_installed` | `(name: str) → bool` | Read |
| `get_package_info` | `(name: str) → PackageInfo \| None` | Read |
| `list_installed` | `() → list[PackageInfo]` | Read |
| `list_upgradable` | `() → list[PackageUpdateInfo]` | Read |
| `install_local` | `(filepath: str) → PackageActionResult` | Write |
| `refresh_metadata` | `() → PackageActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `install_package` MUST return `SKIPPED`
   when the package is already installed at the requested version
   (or any version if `version=None`). `remove_package` MUST return
   `SKIPPED` when the package is not installed. `upgrade_package`
   MUST return `SKIPPED` when the installed version already matches
   (or exceeds) the requested version.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Local-install preconditions.** `install_local` MUST raise
   `PackageFileNotFoundError` when the supplied path does not exist
   before invoking the runner.
5. **Refresh semantics.** `refresh_metadata` is operational; it
   MUST NOT skip based on a freshness heuristic. It is the caller's
   responsibility to schedule it.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_installed`, `list_upgradable`, and
   `get_package_info` MUST raise `PackageQueryError` for unexpected
   failures. An unknown package MUST cause `get_package_info` to
   return `None` and `is_installed` to return `False`.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `PackageActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and failed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `PackageActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `PackageActionStatus` | Outcome category. |
| `package_name` | `str` | The package name. |
| `version` | `str \| None` | Resolved version after the action, if known. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `PackageInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Package name. |
| `version` | `str` | Installed version. |
| `release` | `str` | Release / revision where applicable. |
| `arch` | `str` | Architecture (`x86_64`, `arm64`, `noarch`, etc.). |
| `origin` | `str \| None` | Source channel (repo / tap / source). |

### `PackageUpdateInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Package name. |
| `installed_version` | `str` | Currently installed version. |
| `available_version` | `str` | Latest available version. |
| `arch` | `str` | Architecture. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `PackageQueryError` | `list_installed`, `list_upgradable`, or `get_package_info` fails unexpectedly. |
| `PackageFileNotFoundError` | `install_local` is called with a path that does not exist on disk. |

### `PackageManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |
| `assume_yes` | `bool` | `True` | When `True`, the manager passes the OS's non-interactive flag (e.g., `-y`) to writes. |

---

## Channel / Source Mapping

The abstract verbs implicitly operate against the union of enabled
channels (repositories, taps, buckets). Repository lifecycle is
managed by the separate `repository-management` contract. The
package-management contract takes "which channels are enabled" as
an input state.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `dnf` / `rpm` | Canonical. Commands use `dnf install -y`, `rpm -q`, `dnf check-update`. |
| Ubuntu | `apt` / `dpkg` | `apt-get install -y`, `dpkg-query -W`, `apt list --upgradable`. |
| macOS | `brew` (primary) with optional support for the Mac App Store / `mas` | The OS spec MUST state whether it supports taps beyond `homebrew-core` and whether casks are included. |
| Windows | `winget` (primary) or `choco` / `Chocolatey` | Implementations MAY expose both under one manager but MUST document which is the default. MSI-based installs from local files map to `install_local`. |
| UEFI | N/A | UEFI has no package concept. The package-management contract does not apply. |

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |
| Per-user package managers | Some OSes (Homebrew without `sudo`, `winget` for the current user) do NOT require elevation. The OS spec MUST document which verbs bypass elevation regardless of `elevated=True`. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>PackageManager
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

1. Accept an `ICommandRunner` and a `PackageManagerConfig` in their
   constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `PackageManager` | `UbuntuPackageManager` | `MacosPackageManager` | `WindowsPackageManager` | `PackageManager` |
| `PackageManagerConfig` | `UbuntuPackageManagerConfig` | `MacosPackageManagerConfig` | `WindowsPackageManagerConfig` | `PackageManagerConfig` |
| `PackageActionStatus` | `UbuntuPackageActionStatus` | `MacosPackageActionStatus` | `WindowsPackageActionStatus` | `PackageActionStatus` |
| `PackageActionResult` | `UbuntuPackageActionResult` | `MacosPackageActionResult` | `WindowsPackageActionResult` | `PackageActionResult` |
| `PackageInfo` | `UbuntuPackageInfo` | `MacosPackageInfo` | `WindowsPackageInfo` | `PackageInfo` |
| `PackageUpdateInfo` | `UbuntuPackageUpdateInfo` | `MacosPackageUpdateInfo` | `WindowsPackageUpdateInfo` | `PackageUpdateInfo` |
| `PackageQueryError` | `UbuntuPackageQueryError` | `MacosPackageQueryError` | `WindowsPackageQueryError` | `PackageQueryError` |
| `PackageFileNotFoundError` | `UbuntuPackageFileNotFoundError` | `MacosPackageFileNotFoundError` | `WindowsPackageFileNotFoundError` | `PackageFileNotFoundError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `PackageActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One `is_installed` / `get_package_info` test for an installed
   and a missing package.
4. One `list_installed` parser test covering representative output.
5. One `list_upgradable` parser test covering representative output,
   including the OS's "updates available" exit-code idioms (e.g.,
   `dnf check-update` returning 100).
6. One `install_local` test proving `PackageFileNotFoundError` is
   raised for a missing path and the runner is not invoked.
7. One dry-run test per write verb proving the runner is not
   invoked.
8. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Version holds / pinning (the RHEL reference exposes `hold` /
  `release_hold`; the Ubuntu reference MAY use `apt-mark hold`).
- Package groups (`dnf groupinstall`, `brew bundle`, Windows
  "features").
- Dependency resolution reporting.
- Signature / GPG key import (see `repository-management`).
- Snap / Flatpak / AppX packages beyond the primary manager.
- Offline / cached installs with explicit cache management.
- History / rollback.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu wraps `apt-get` /
  `dpkg-query` / `apt list`; macOS wraps Homebrew (`brew`); Windows
  wraps `winget`. The verb surface is identical but the underlying
  semantic models differ — Ubuntu and Windows treat repositories
  as system-wide, macOS treats taps as Homebrew-prefix-scoped, and
  the dataclass field meanings shift accordingly (e.g.,
  `release` is empty on Ubuntu because apt has no release/revision
  split).
- **macOS inverts the elevation model.** Homebrew refuses to run
  as root. The macOS manager always passes `elevated=False` and
  routes through a `sudo -u <brew_user>` wrapper when the calling
  process is already root, contradicting the contract's
  "write-elevate" rule. The deviation is enforced by manager-level
  property tests rather than relaxed in the contract.
- **`install_local` semantics diverge per backend.** Ubuntu treats
  the path as a `.deb` for `apt-get install -y <filepath>`; macOS
  routes to `brew install --cask`; Windows uses
  `winget install [--manifest] <filepath>` and may need an MSI
  fallback for `.msi` files in a future extension.
- **Windows `elevation_blocked: bool`.** Writes that require
  elevation surface the structured Windows extension when the
  manager runs without an elevated token. See the README
  "Implementation Conventions" elevation-blocked entry.
- **OS-prefixed types throughout.** `UbuntuPackageManager`,
  `MacosPackageManager`, and `WindowsPackageManager` carry
  prefixed dataclasses (`*PackageInfo`, `*PackageUpdateInfo`,
  `*PackageActionResult`) per the README naming convention.
