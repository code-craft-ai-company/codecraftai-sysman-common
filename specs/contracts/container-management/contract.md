# Container-Management Contract

This is the cross-OS abstract contract for the
**container-management** feature. Every `automojo-sysman-*`
package that ships a container manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-container-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-container-management/).
It wraps Podman through an `ICommandRunner` (and MAY use an
`IFileOperator` where available; the established pattern is to
route file I/O through `ICommandRunner` — see the README
"Implementation Conventions"),
with rootful and rootless branches selected at call time. This
contract generalises the verb set for OSes whose container
engines are Podman / Docker on Linux, Docker Desktop / colima /
Podman on macOS, or Docker Desktop / Podman on Windows (with
`containerd` / Windows Containers as an alternative).

---

## Scope

The container-management feature provides idempotent, auditable
control over images and containers local to the host, through a
configurable container engine. It covers:

- Pulling, listing, and removing container images.
- Creating, starting, stopping, restarting, and removing
  containers.
- Listing and inspecting containers.
- Retrieving container logs.
- Executing a command inside a running container.
- Dry-run-aware writes.
- Elevation for writes that target the rootful daemon; reads
  never elevate unless the rootful daemon socket is itself
  access-controlled.

The feature does NOT install the container engine — that is
`package-management`. It does NOT configure container registry
trust / mirrors beyond what the engine exposes via CLI; deeper
registry config is an OS-specific extension.

---

## Verbs

Every OS implementation MUST expose a `ContainerManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `pull_image` | `(reference: str) → ContainerActionResult` | Write |
| `remove_image` | `(reference: str, force: bool) → ContainerActionResult` | Write |
| `list_images` | `() → list[ContainerImage]` | Read |
| `create_container` | `(spec: ContainerSpec) → ContainerActionResult` | Write |
| `start_container` | `(container_id: str) → ContainerActionResult` | Write |
| `stop_container` | `(container_id: str, timeout: int \| None) → ContainerActionResult` | Write |
| `remove_container` | `(container_id: str, force: bool) → ContainerActionResult` | Write |
| `list_containers` | `(include_stopped: bool) → list[ContainerInfo]` | Read |
| `inspect_container` | `(container_id: str) → ContainerInfo \| None` | Read |
| `get_container_logs` | `(container_id: str, lines: int \| None) → ContainerLogs` | Read |
| `exec_in_container` | `(container_id: str, argv: list[str]) → ContainerActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `pull_image` MUST return `SKIPPED`
   when the reference is already present (by digest for
   digest-pinned refs, by tag+digest lookup for floating refs).
   `remove_image` MUST return `SKIPPED` when the reference is
   absent. `create_container` MUST return `SKIPPED` when a
   container with the same `name` and same normalised spec
   already exists. `start_container` MUST return `SKIPPED` when
   the container is already running. `stop_container` MUST return
   `SKIPPED` when the container is already stopped. `exec_in_
   container` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Credential safety.** Registry-login passwords passed to
   `pull_image` (via a companion login verb or via creds embedded
   in the spec) MUST flow on `stdin` and never on argv; the
   recorded `command` MUST be sanitised.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True`, except
   where the OS requires elevation to reach the daemon socket.
2. **Typed errors.** Reads MAY raise `ContainerQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list / synthetic record so callers can proceed without a
   try/except wrapper. `inspect_container` MUST return `None` for
   an unknown container id rather than raise. See the README
   "Implementation Conventions" graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `ContainerActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `ContainerEngine` (enum)

| Value | Meaning |
|-------|---------|
| `PODMAN` | Podman CLI. |
| `DOCKER` | Docker CLI. |
| `CONTAINERD` | `ctr` / `nerdctl` against containerd. |
| `DOCKER_DESKTOP` | Docker Desktop (macOS / Windows). |
| `COLIMA` | colima (macOS). |

### `ContainerSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Container name. |
| `image` | `str` | Image reference. |
| `command` | `list[str] \| None` | Override command. |
| `env` | `dict[str, str]` | Environment variables. |
| `ports` | `list[str]` | Port publications (e.g., `"80:8080/tcp"`). |
| `mounts` | `list[str]` | Volume / bind mounts as native CLI strings. |
| `networks` | `list[str]` | Network names. |
| `restart_policy` | `str \| None` | Restart policy (`"no"`, `"on-failure"`, `"always"`, `"unless-stopped"`). |
| `detach` | `bool` | Whether to run detached. |
| `replace_existing` | `bool` | When `True`, replace a container with the same name instead of skipping. |

### `ContainerImage` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Image id. |
| `references` | `list[str]` | Tag / digest references. |
| `size_bytes` | `int` | On-disk size. |
| `created` | `str \| None` | ISO-8601 creation time. |

### `ContainerInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Container id. |
| `name` | `str` | Container name. |
| `image` | `str` | Image reference. |
| `status` | `str` | Native status string (`"running"`, `"exited"`, `"paused"`, ...). |
| `created` | `str` | ISO-8601 creation time. |
| `started` | `str \| None` | ISO-8601 start time when running. |
| `ports` | `list[str]` | Published port mappings. |
| `mounts` | `list[str]` | Mounts. |

### `ContainerLogs` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `container_id` | `str` | Source container id. |
| `lines` | `list[str]` | Log lines. |
| `truncated` | `bool` | `True` when the query was truncated by a line limit. |

### `ContainerActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ContainerActionStatus` | Outcome category. |
| `target` | `str \| None` | Image reference or container id. |
| `container_id` | `str \| None` | New container id when applicable. |
| `image_id` | `str \| None` | Image id when applicable. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | Sanitised argv. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ContainerQueryError` | A read fails unexpectedly. |
| `ContainerEngineNotFoundError` | The configured engine is not available on the host. |
| `ContainerNotFoundError` | A verb is given an unknown container id and the OS surface requires raising rather than skipping. |

### `ContainerManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, rootful writes pass `elevated=True` to the runner. |
| `container_engine` | `ContainerEngine` | `ContainerEngine.PODMAN` | Selected engine. |
| `rootless_default` | `bool` | `False` | Whether engines that distinguish rootful vs rootless default to rootless. |

---

## Engine Mapping

The abstract `ContainerEngine` maps to each OS's native tooling:

| OS | Default engine | Also supported | Notes |
|----|----------------|----------------|-------|
| Red Hat Enterprise Linux | `PODMAN` | `DOCKER` via `podman-docker` or native Docker | Canonical. Rootful vs rootless via `config.rootless_default`. |
| Ubuntu | `DOCKER` | `PODMAN` | — |
| macOS | `DOCKER_DESKTOP` | `COLIMA`, `PODMAN` | The OS spec MUST document how the selected engine's CLI is located (e.g., `docker` on PATH). |
| Windows | `DOCKER_DESKTOP` | `PODMAN`, `CONTAINERD` (Windows Containers) | — |
| UEFI | N/A | N/A | UEFI has no container runtime. The contract does not apply. |

Each OS spec MUST include an Engine-Mapping section stating its
supported set and how the engine binary is resolved.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, rootful write | Pass `elevated=True` to the runner. |
| Config `elevated=True`, rootless write | Do NOT pass `elevated=True`. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`, except where the OS requires it to access the daemon socket. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                │  selects container engine
                ▼
        <Os>ContainerManager
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

1. Accept an `ICommandRunner` and a `ContainerManagerConfig` in
   their constructor.
2. Never construct their own subprocess.
3. Never restart the container engine daemon on their own
   initiative.
4. Not hold state across calls beyond the config.
5. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `ContainerManager` | `UbuntuContainerManager` | `MacosContainerManager` | `WindowsContainerManager` | `ContainerManager` |
| `ContainerManagerConfig` | `UbuntuContainerManagerConfig` | `MacosContainerManagerConfig` | `WindowsContainerManagerConfig` | `ContainerManagerConfig` |
| `ContainerActionStatus` | `UbuntuContainerActionStatus` | `MacosContainerActionStatus` | `WindowsContainerActionStatus` | `ContainerActionStatus` |
| `ContainerActionResult` | `UbuntuContainerActionResult` | `MacosContainerActionResult` | `WindowsContainerActionResult` | `ContainerActionResult` |
| `ContainerEngine` | `UbuntuContainerEngine` | `MacosContainerEngine` | `WindowsContainerEngine` | `ContainerEngine` |
| `ContainerSpec` | `UbuntuContainerSpec` | `MacosContainerSpec` | `WindowsContainerSpec` | `ContainerSpec` |
| `ContainerImage` | `UbuntuContainerImage` | `MacosContainerImage` | `WindowsContainerImage` | `ContainerImage` |
| `ContainerInfo` | `UbuntuContainerInfo` | `MacosContainerInfo` | `WindowsContainerInfo` | `ContainerInfo` |
| `ContainerLogs` | `UbuntuContainerLogs` | `MacosContainerLogs` | `WindowsContainerLogs` | `ContainerLogs` |
| `ContainerQueryError` | `UbuntuContainerQueryError` | `MacosContainerQueryError` | `WindowsContainerQueryError` | `ContainerQueryError` |
| `ContainerEngineNotFoundError` | `UbuntuContainerEngineNotFoundError` | `MacosContainerEngineNotFoundError` | `WindowsContainerEngineNotFoundError` | `ContainerEngineNotFoundError` |
| `ContainerNotFoundError` | `UbuntuContainerNotFoundError` | `MacosContainerNotFoundError` | `WindowsContainerNotFoundError` | `ContainerNotFoundError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ContainerActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`. Retry aspects MUST NOT double-pull images or
  re-create containers; the manager's idempotency guards cover
  retries.
- Persistence aspects MUST NOT mutate the result and MUST NOT log
  registry credentials.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `pull_image` test with a digest-pinned reference proving
   `SKIPPED` when the digest is already present locally.
5. One `list_containers` parser test covering both running and
   stopped containers.
6. One `get_container_logs` test exercising the line-limit path
   and proving `truncated=True` is set correctly.
7. One `ContainerEngineNotFoundError` test proving the right
   exception fires when the configured engine is absent.
8. One elevation test proving rootful writes pass
   `elevated=True` and reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Image builds (`podman build` / `docker build`).
- Compose / Quadlet / Docker Compose orchestration.
- Container networks and volumes beyond the name references in
  `ContainerSpec`.
- Kubernetes integration (kind, minikube, k3s).
- Container engine daemon configuration (see extensions per
  engine).
- Pod / group constructs (Podman pods).
- Registry mirror configuration and authfile management beyond
  the basic `pull_image` verb.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Per-OS engine enums.** `UbuntuContainerEngine` enumerates
  `DOCKER` / `PODMAN` / `CONTAINERD`; `MacosContainerEngine` adds
  `DOCKER_DESKTOP` / `COLIMA`; `WindowsContainerEngine` adds
  `DOCKER_DESKTOP` / `WINDOWS_CONTAINERS`. The contract's
  abstract `ContainerEngine` is the union; per-OS callers consume
  the prefixed enum.
- **File I/O via `ICommandRunner`.** Compose files, registry
  configs, and credential files route through the runner using
  `cat` / `tee` / `Get-Content` / `Set-Content`.
- **`engine` config field.** Each per-OS `<Os>ContainerManagerConfig`
  carries an `engine: <Os>ContainerEngine` field that the manager
  uses to select between the Podman and Docker CLIs (and the
  Windows-Containers CLI on Windows).
