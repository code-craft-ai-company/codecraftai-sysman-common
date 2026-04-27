# Repository-Management Contract

This is the cross-OS abstract contract for the **repository-management**
feature. Every `automojo-sysman-*` package that ships a repository
manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-repository-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-repository-management/).
It manages `/etc/yum.repos.d/*.repo` files and the `dnf
config-manager` tool through an `ICommandRunner`. This contract
generalises the verb set for OSes whose native repository concept
is `apt` sources, Homebrew taps, `winget` sources, and Chocolatey
sources.

---

## Scope

The repository-management feature provides idempotent, auditable
control over the set of software-source channels the OS's package
manager consults. It covers:

- Adding a new repository from a specification.
- Removing a repository.
- Enabling or disabling an existing repository.
- Listing all configured repositories.
- Refreshing metadata for all or a single repository.
- Importing a GPG / signing key.
- Setting repository priority where supported.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.

---

## Verbs

Every OS implementation MUST expose a `RepositoryManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_repository` | `(spec: RepositorySpec) → RepositoryActionResult` | Write |
| `remove_repository` | `(name: str) → RepositoryActionResult` | Write |
| `enable_repository` | `(name: str) → RepositoryActionResult` | Write |
| `disable_repository` | `(name: str) → RepositoryActionResult` | Write |
| `list_repositories` | `() → list[RepositoryInfo]` | Read |
| `get_repository` | `(name: str) → RepositoryInfo \| None` | Read |
| `refresh_repositories` | `(name: str \| None) → RepositoryActionResult` | Write |
| `set_priority` | `(name: str, priority: int) → RepositoryActionResult` | Write |
| `import_gpg_key` | `(key_source: str) → RepositoryActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_repository` MUST compute the
   rendered native form of the spec and compare it to the current
   configuration; matching state MUST return `SKIPPED`.
   `remove_repository` MUST return `SKIPPED` when the repository is
   not configured. `enable_repository` / `disable_repository` /
   `set_priority` MUST return `SKIPPED` when the requested state
   is already in effect.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Precondition exceptions.** `set_priority` MUST raise
   `RepositoryNotFoundError` when the repository does not exist.
   `import_gpg_key` with a local-file argument MUST raise
   `RepositoryKeyFileNotFoundError` when the file does not exist.
5. **Refresh semantics.** `refresh_repositories` is operational;
   it MUST NOT skip. When `name` is `None`, it refreshes all
   enabled repositories; when supplied, it refreshes only the
   named one.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** `list_repositories` MUST raise
   `RepositoryQueryError` for unexpected failures. `get_repository`
   MUST return `None` for an unknown name.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `RepositoryActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and failed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `RepositorySpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique repository identifier. |
| `display_name` | `str` | Human-readable name. |
| `base_url` | `str \| None` | Package download base URL. |
| `mirror_list_url` | `str \| None` | URL to a mirror list. |
| `enabled` | `bool` | Initial enabled state. |
| `gpg_check` | `bool` | Whether signature checking is required. |
| `gpg_key` | `str \| None` | URL or path to the signing key. |
| `priority` | `int \| None` | Priority where supported. |
| `channel` | `str \| None` | Native sub-concept (component / suite / arch / tap). |

### `RepositoryInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Repository identifier. |
| `display_name` | `str` | Human-readable name. |
| `enabled` | `bool` | Current enabled state. |
| `url` | `str \| None` | Base URL or mirror-list URL in effect. |
| `priority` | `int \| None` | Current priority where supported. |

### `RepositoryActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `RepositoryActionStatus` | Outcome category. |
| `name` | `str` | The repository targeted. |
| `file_path` | `str \| None` | The source file affected where applicable. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `RepositoryQueryError` | `list_repositories` fails for an unexpected reason. |
| `RepositoryNotFoundError` | `set_priority` targets a repository that does not exist. |
| `RepositoryKeyFileNotFoundError` | `import_gpg_key` is called with a local file path that does not exist. |

### `RepositoryManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |
| `repos_dir` | `str \| None` | OS-default | Override for the directory hosting repository definitions. |

---

## Repository-Name Mapping

The abstract `name` parameter maps to each OS's native repository
concept.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `.repo` file stem under `/etc/yum.repos.d/` | Canonical. Definitions are INI files consumed by `dnf`. |
| Ubuntu | apt sources entry under `/etc/apt/sources.list.d/<name>.list` (or `.sources` for deb822) | `name` is the filename stem. Definitions include component and suite fields that map to `RepositorySpec.channel`. |
| macOS | Homebrew tap (`owner/name`) | Many `RepositorySpec` fields (GPG, priority) are N/A for taps; implementations MUST accept but ignore them with a documented warning. |
| Windows | `winget source` entry name or `choco source` entry | `winget source add --name <name> --arg <url>`; the `type` field of `winget` sources maps to a subset of `RepositorySpec.channel`. |
| UEFI | N/A | UEFI has no package repository concept. The repository-management contract does not apply. |

Each OS spec MUST include a Repository-Name-Mapping section
describing which fields of `RepositorySpec` are honored, which are
N/A, and how it renders the spec to native form.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |
| Per-user package managers | Homebrew taps, `winget` user sources, and Chocolatey user sources do NOT require elevation. The OS spec MUST document which verbs bypass elevation. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>RepositoryManager
                │
                │  .run(argv, elevated=…, stdin=content, capture_output=True)
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

1. Accept an `ICommandRunner` and a `RepositoryManagerConfig` in
   their constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `RepositoryManager` | `UbuntuRepositoryManager` | `MacosRepositoryManager` | `WindowsRepositoryManager` | `RepositoryManager` |
| `RepositoryManagerConfig` | `UbuntuRepositoryManagerConfig` | `MacosRepositoryManagerConfig` | `WindowsRepositoryManagerConfig` | `RepositoryManagerConfig` |
| `RepositoryActionStatus` | `UbuntuRepositoryActionStatus` | `MacosRepositoryActionStatus` | `WindowsRepositoryActionStatus` | `RepoActionStatus` |
| `RepositoryActionResult` | `UbuntuRepositoryActionResult` | `MacosRepositoryActionResult` | `WindowsRepositoryActionResult` | `RepoActionResult` |
| `RepositorySpec` | `UbuntuRepositorySpec` | `MacosRepositorySpec` | `WindowsRepositorySpec` | `RepoDefinition` |
| `RepositoryInfo` | `UbuntuRepositoryInfo` | `MacosRepositoryInfo` | `WindowsRepositoryInfo` | `RepoInfo` |
| `RepositoryQueryError` | `UbuntuRepositoryQueryError` | `MacosRepositoryQueryError` | `WindowsRepositoryQueryError` | `RepoQueryError` |
| `RepositoryNotFoundError` | `UbuntuRepositoryNotFoundError` | `MacosRepositoryNotFoundError` | `WindowsRepositoryNotFoundError` | `RepoNotFoundError` |
| `RepositoryKeyFileNotFoundError` | `UbuntuRepositoryKeyFileNotFoundError` | `MacosRepositoryKeyFileNotFoundError` | `WindowsRepositoryKeyFileNotFoundError` | `RepoKeyFileNotFoundError` |

The RHEL package keeps its historical short names (`RepoActionResult`,
`RepoDefinition`, `RepoInfo`); new OS packages use the fully
qualified names above.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `RepositoryActionResult` sequence when driven by
  a real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One `list_repositories` parser test covering representative
   output including enabled and disabled repos.
4. One `add_repository` rendering-consistency test proving that
   identical specs render identically on successive calls.
5. One `import_gpg_key` test proving
   `RepositoryKeyFileNotFoundError` is raised for a missing local
   file.
6. One `set_priority` test proving `RepositoryNotFoundError` is
   raised for an unknown repository.
7. One dry-run test per write verb proving the runner is not
   invoked.
8. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Repository mirroring / local mirror hosting.
- Client-certificate authentication for private repositories.
- Subscription-manager / entitlement integration (RHEL-specific).
- deb822 advanced fields (Architectures, Signed-By beyond a single
  key).
- Homebrew bundle files as multi-tap specifications.
- `winget` manifest authoring.
- Package-index search that transcends a single repository.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is sharp.** Ubuntu manages
  `/etc/apt/sources.list.d/` `.list` / deb822 files plus
  `/etc/apt/keyrings/`; macOS wraps Homebrew taps
  (`brew tap` / `brew untap` / `brew tap-info`); Windows wraps
  `winget source`. Many contract fields (GPG key, mirror list,
  priority) have no Homebrew analog and are surfaced as `None`
  in the macOS read-shape.
- **Homebrew has no soft-disable.** macOS `enable_repository`
  short-circuits to `SKIPPED` for present taps;
  `disable_repository` returns `FAILED` with the stable
  `homebrew_no_disable_untap_required` token because the only
  near-equivalent is `brew untap` (which `remove_repository`
  performs explicitly). See the README "FAILED with stable
  detail token" convention and stable-detail-token catalog.
- **macOS Homebrew elevation inversion.** Homebrew refuses to
  run as root. The macOS manager accepts `elevated` on its
  config but always passes `elevated=False` to the runner; this
  matches the elevation-inversion already present in
  `package-management` for the same reason.
- **File I/O via `ICommandRunner`.** Ubuntu drop-in files,
  pinning files, and keyring writes route through the runner
  using `cat` / `tee`; Windows surfaces no file edits because
  `winget source` is a CLI-only registry. See the README
  "Implementation Conventions" file-I/O section.
- **Windows `elevation_blocked: bool`.** `winget source add` /
  `remove` / `update` writes surface the structured Windows
  elevation extension when the calling process lacks an elevated
  token. See the README "Implementation Conventions"
  elevation-blocked entry.
