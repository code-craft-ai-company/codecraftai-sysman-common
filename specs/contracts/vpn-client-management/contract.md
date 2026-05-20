# VPN-Client-Management Contract

This is the cross-OS abstract contract for the **vpn-client-management**
feature. Every `automojo-sysman-*` package that ships a VPN-client
manager MUST honor this contract.

The contract covers installation and lifecycle of mesh-VPN client
daemons on a host — primarily **Tailscale** (`tailscaled`) and
**Twingate Connector** (`twingate-connector`). It does NOT cover the
control-plane API surface (auth-key minting, ACL push, device
deletion). Those live in `automojo-interop` (`IVPNControlPlane`).

The host-side feature is small but uniform: install the daemon,
configure it, start it, bring the tunnel up against a tailnet / network,
report status, bring it down, uninstall.

---

## Scope

The vpn-client-management feature provides idempotent, auditable
control over the locally-installed mesh-VPN client. It covers:

- Installing the Tailscale client (`tailscaled`).
- Installing the Twingate Connector.
- Writing provider-specific configuration files where required.
- Bringing the tunnel up with an auth key, hostname, and tag set.
- Bringing the tunnel down.
- Reporting tunnel status (running, self overlay address, peers).
- Uninstalling the daemon and removing residual state.

The feature is executed exclusively through an `ICommandRunner` from
`automojo-interfaces`. Configuration writes route through the runner
using `tee` / `Set-Content` / equivalent — never direct filesystem I/O.

---

## Verbs

Every OS implementation MUST expose a `VPNClientManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs. Signatures below are abstract; concrete
signatures substitute the OS-prefixed result-type names.

| Verb | Signature | Kind |
|------|-----------|------|
| `install_tailscale` | `(version: str \| None, channel: str, aspects: Aspects) → VPNActionResult` | Write |
| `install_twingate_connector` | `(version: str \| None, aspects: Aspects) → VPNActionResult` | Write |
| `configure` | `(provider: VPNProvider, settings: dict, aspects: Aspects) → VPNActionResult` | Write |
| `bring_up` | `(provider: VPNProvider, authkey: str, hostname: str \| None, advertise_tags: list[str] \| None, advertise_routes: list[str] \| None, exit_node: bool, aspects: Aspects) → VPNActionResult` | Write |
| `bring_down` | `(provider: VPNProvider, aspects: Aspects) → VPNActionResult` | Write |
| `status` | `(provider: VPNProvider, aspects: Aspects) → VPNClientStatus` | Read |
| `uninstall` | `(provider: VPNProvider, purge: bool, aspects: Aspects) → VPNActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** Each write MUST query the relevant local
   state (package presence for installs, daemon state for bring-up /
   bring-down) and return `SKIPPED` when the desired state is already
   in effect. The runner MUST NOT be invoked for the mutating command.
2. **Dry-run short-circuit.** `dry_run=True` on the manager config
   MUST return `DRY_RUN` without invoking the runner. The `command`
   field on the result MAY be populated with what would have run.
3. **Error surface.** Non-zero exit codes from the runner return
   `FAILED` with `exit_code`, `stdout`, `stderr`, and `command`
   populated. Writes do NOT raise.
4. **Aspects on every call.** Every behaviour-bearing op accepts an
   `aspects` parameter. Timeouts, retries, elevation, and persistence
   are controlled through it — never baked in.
5. **Elevation.** WHERE the runner is configured for elevation THE
   SYSTEM SHALL pass `elevated=True` for installs, configure, bring-up,
   bring-down, and uninstall. Status reads never elevate.

### Method-level invariants (reads)

1. **No elevation.** `status` MUST NOT pass `elevated=True`.
2. **Typed errors.** `status` MUST raise `VPNClientQueryError` for
   unexpected failures. An "installed but not running" daemon is NOT
   an error — it returns `VPNClientStatus(running=False, ...)`.
3. **Pure parsing.** Provider CLI output (`tailscale status --json`,
   `twingate status`) is parsed in pure Python.

---

## Data Models

### `VPNProvider` (enum)

| Value | Meaning |
|-------|---------|
| `TAILSCALE` | The Tailscale mesh-VPN client. |
| `TWINGATE` | The Twingate Connector. |

### `VPNActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `VPNActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `VPNActionStatus` | Outcome category. |
| `provider` | `VPNProvider` | The provider the action targeted. |
| `detail` | `str \| None` | Free-form identifier (package, action descriptor). |
| `exit_code` | `int \| None` | Runner exit code for `SUCCESS` / `FAILED`. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `VPNClientStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `provider` | `VPNProvider` | Provider being reported. |
| `installed` | `bool` | True when the daemon package is present. |
| `running` | `bool` | True when the daemon is active and the tunnel is up. |
| `self_address` | `str \| None` | Overlay IP (Tailscale `100.x.x.x`) or `None` for Twingate. |
| `hostname` | `str \| None` | The hostname registered with the control plane. |
| `tailnet` | `str \| None` | Tailnet / network slug, if known. |
| `peer_addresses` | `dict[str, str]` | Peer hostname → overlay IP. Empty for Twingate. |
| `version` | `str \| None` | Installed client version. |

### `VPNClientQueryError` (exception)

Raised from `status` when the underlying query command fails for
reasons other than "daemon not installed" or "daemon not running".
Carries the exit code and captured stderr.

### `VPNClientManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True`. |

Implementations MAY extend with OS-specific fields (e.g., an MSI
download cache path on Windows, a Homebrew tap override on macOS)
but MUST preserve these two fields with these names and defaults.

---

## Provider Asymmetry

The contract acknowledges that Tailscale and Twingate are not
interchangeable:

| Aspect | Tailscale | Twingate |
|--------|-----------|----------|
| Topology | Flat mesh | Hub-and-spoke (clients reach resources via connector) |
| Self address | Each host gets a `100.x.x.x` overlay IP | Connector host has no overlay IP |
| `VPNClientStatus.self_address` | populated | `None` |
| `VPNClientStatus.peer_addresses` | populated for tailnet peers | always empty |
| `bring_up` advertise_routes | optional subnet router | maps to advertised resources |

Per-OS implementations MUST honour these asymmetries and document
them in their own `design.md`.

---

## Provider × OS Backend Matrix

| OS | Tailscale install path | Twingate install path | Service mechanism |
|----|------------------------|------------------------|-------------------|
| Ubuntu | apt repo `pkgs.tailscale.com` + `tailscale` package | apt repo `packages.twingate.com` + `twingate-connector` deb | `systemctl` on `tailscaled` / `twingate-connector` |
| RHEL / Fedora | dnf/yum repo `pkgs.tailscale.com` + `tailscale` package | rpm repo + `twingate-connector` rpm | `systemctl` |
| macOS | Homebrew formula `tailscale` (CLI/daemon) or signed `.pkg` from Tailscale | signed `.pkg` from Twingate | `launchctl` on `com.tailscale.tailscaled` |
| Windows | MSI from `pkgs.tailscale.com/.../tailscale-setup-*.msi` via `msiexec /quiet` | MSI from Twingate via `msiexec /quiet` | Windows Service via `Set-Service` / `sc.exe` |

Each per-OS spec MUST include a Provider-Backend section that pins
the exact package names, repos / URLs, and service identifiers it
uses.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, `status` (read) | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`, regardless of verb. |

OS elevation mechanism: `sudo` on RHEL/Ubuntu/macOS; Administrator
token / UAC on Windows. The command runner handles the mechanism.

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>VPNClientManager  (inherits BaseFeatureManager)
                │
                │  .run(argv, elevated=…, capture_output=True)
                ▼
          ICommandRunner
                │
        ┌───────┴────────┐
        ▼                ▼
  LocalCommandRunner   SSHCommandRunner
                 │
                 ▼  aspects compose here
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner` and a `VPNClientManagerConfig` in their
   constructor.
2. Never construct their own subprocess; never write files directly.
3. Hold no state across method calls beyond runner and config.
4. Compose cleanly under any aspect configuration on the runner.

---

## Naming

Concrete types per OS are prefixed with the OS name in Pascal case.

| Abstract | Ubuntu | RHEL | macOS | Windows |
|----------|--------|------|-------|---------|
| `VPNClientManager` | `UbuntuVPNClientManager` | `RedHatVPNClientManager` | `MacosVPNClientManager` | `WindowsVPNClientManager` |
| `VPNClientManagerConfig` | `UbuntuVPNClientManagerConfig` | `RedHatVPNClientManagerConfig` | `MacosVPNClientManagerConfig` | `WindowsVPNClientManagerConfig` |
| `VPNActionStatus` | `UbuntuVPNActionStatus` | `RedHatVPNActionStatus` | `MacosVPNActionStatus` | `WindowsVPNActionStatus` |
| `VPNActionResult` | `UbuntuVPNActionResult` | `RedHatVPNActionResult` | `MacosVPNActionResult` | `WindowsVPNActionResult` |
| `VPNClientStatus` | `UbuntuVPNClientStatus` | `RedHatVPNClientStatus` | `MacosVPNClientStatus` | `WindowsVPNClientStatus` |
| `VPNClientQueryError` | `UbuntuVPNClientQueryError` | `RedHatVPNClientQueryError` | `MacosVPNClientQueryError` | `WindowsVPNClientQueryError` |

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb, per provider.
2. One idempotency test per write verb (install, bring_up, bring_down,
   uninstall) proving `SKIPPED` is returned when the state already
   matches.
3. One dry-run test per write verb proving the runner is not invoked.
4. One parser test per provider for `status`.
5. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.
6. **Property tests** (hypothesis) covering install and uninstall
   idempotency — `install ∘ install = install`,
   `uninstall ∘ uninstall = uninstall`.

---

## Out of Scope for the Base Contract

The following are explicitly NOT in the contract:

- Auth-key minting (lives in `IVPNControlPlane`).
- ACL push (lives in `IVPNControlPlane`).
- Cross-host peer enumeration beyond what the local daemon reports.
- Funnel / Serve features.
- Multi-tenant tailnet switching on a single host.
- Operating-system kernel-module installation when the distro lacks
  WireGuard in-kernel (documented per-OS as a precondition error).

Any extension MUST be documented in the per-OS `design.md` under
"Extensions beyond the contract".
