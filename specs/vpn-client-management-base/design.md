# Design

## Overview

`VPNClientManagementBase` is the shared abstract feature manager for the
vpn-client-management contract. It lives in
`automojo.sysman.common.vpnclientmanagementbase` and is the only place the
contract's enums, dataclasses, exceptions, and verb signatures are defined.
Per-OS subclasses (`UbuntuVPNClientManager`, `RedHatVPNClientManager`,
`MacosVPNClientManager`, `WindowsVPNClientManager`) inherit from this base,
implement the abstract verbs, and reuse the shared helpers for dry-run
short-circuit, elevation decision-making, and runner-result mapping.

The base never invokes the command runner directly. Every command goes through
the subclass, which forwards `aspects` to the runner. The base owns:

- Type definitions (`VPNProvider`, `VPNActionStatus`, `VPNActionResult`,
  `VPNClientStatus`, `VPNClientManagerConfig`, `VPNClientQueryError`).
- The abstract verb surface (`install_tailscale`, `install_twingate_connector`,
  `configure`, `bring_up`, `bring_down`, `status`, `uninstall`).
- Shared helpers (`_validate_provider`, `_short_circuit_dry_run`,
  `_dispatch_write`, `_should_elevate`).

**See Also:**
- [vpn-client-management contract](../contracts/vpn-client-management/contract.md)
- [BaseFeatureManager](../design.md) in sysman-common
- Per-OS implementations under `automojo-sysman-{ubuntu,redhat,macos,windows}/specs/3-vpn-client-management/`

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                Maintenance coordinator                           │
│  - injects ICommandRunner + VPNClientManagerConfig + Aspects     │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│           <Os>VPNClientManager   (per-OS subclass)               │
│   inherits VPNClientManagementBase                               │
│                                                                  │
│   install_tailscale()       install_twingate_connector()         │
│   configure()               bring_up()                           │
│   bring_down()              status()                             │
│   uninstall()                                                    │
└─────────────────────────┬────────────────────────────────────────┘
                          │ super().<helper>(…)
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│              VPNClientManagementBase   (this spec)               │
│                                                                  │
│   _validate_provider()         _short_circuit_dry_run()          │
│   _dispatch_write()            _should_elevate()                 │
│                                                                  │
│   shared types: VPNProvider, VPNActionStatus, VPNActionResult,   │
│                 VPNClientStatus, VPNClientQueryError,            │
│                 VPNClientManagerConfig                           │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
                  BaseFeatureManager
                          │
                          ▼
                    ICommandRunner
```

---

## Data Model

### Enums

```python
class VPNProvider(Enum):
    TAILSCALE = "tailscale"
    TWINGATE  = "twingate"

class VPNActionStatus(Enum):
    SUCCESS  = "success"
    FAILED   = "failed"
    SKIPPED  = "skipped"
    DRY_RUN  = "dry_run"
```

### Dataclasses

```python
@dataclass
class VPNActionResult:
    status: VPNActionStatus
    provider: VPNProvider
    detail: Optional[str]
    exit_code: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    command: Optional[List[str]]

@dataclass
class VPNClientStatus:
    provider: VPNProvider
    installed: bool
    running: bool
    self_address: Optional[str]
    hostname: Optional[str]
    tailnet: Optional[str]
    peer_addresses: Dict[str, str]
    version: Optional[str]

@dataclass
class VPNClientManagerConfig:
    dry_run: bool = False
    elevated: bool = False

class VPNClientQueryError(Exception):
    """Raised when status() fails for reasons other than 'not installed'."""
```

---

## Abstract Verb Surface

```python
class VPNClientManagementBase(BaseFeatureManager, ABC):

    def __init__(self, *, runner: ICommandRunner,
                 config: Optional[VPNClientManagerConfig] = None) -> None:
        cfg = config if config is not None else VPNClientManagerConfig()
        super().__init__(runner=runner, config=cfg)
        self._config: VPNClientManagerConfig = cfg

    @abstractmethod
    def install_tailscale(self, *, version: Optional[str], channel: str,
                          aspects: Aspects) -> VPNActionResult: ...

    @abstractmethod
    def install_twingate_connector(self, *, version: Optional[str],
                                   aspects: Aspects) -> VPNActionResult: ...

    @abstractmethod
    def configure(self, *, provider: VPNProvider, settings: Dict[str, str],
                  aspects: Aspects) -> VPNActionResult: ...

    @abstractmethod
    def bring_up(self, *, provider: VPNProvider, authkey: str,
                 hostname: Optional[str], advertise_tags: Optional[List[str]],
                 advertise_routes: Optional[List[str]], exit_node: bool,
                 aspects: Aspects) -> VPNActionResult: ...

    @abstractmethod
    def bring_down(self, *, provider: VPNProvider,
                   aspects: Aspects) -> VPNActionResult: ...

    @abstractmethod
    def status(self, *, provider: VPNProvider,
               aspects: Aspects) -> VPNClientStatus: ...

    @abstractmethod
    def uninstall(self, *, provider: VPNProvider, purge: bool,
                  aspects: Aspects) -> VPNActionResult: ...
```

---

## Shared Helpers

| Helper | Purpose |
|--------|---------|
| `_validate_provider(provider, supported)` | Returns `VPNActionResult(FAILED)` with a descriptive `detail` when `provider not in supported`; returns `None` otherwise. |
| `_short_circuit_dry_run(provider, command, detail)` | Returns `VPNActionResult(DRY_RUN, ...)` populated for the caller. |
| `_should_elevate(kind)` | Returns `self._config.elevated and kind == "WRITE"`. |
| `_dispatch_write(provider, command, detail, aspects)` | Calls `self._runner.run(args=command, elevated=self._should_elevate("WRITE"), aspects=aspects)`, maps to `VPNActionResult(SUCCESS or FAILED, ...)`. |

`_dispatch_write` is the single place where exit-code → status mapping lives.
Every per-OS write verb routes through it; subclass code stays linear and
contains only command construction and idempotency-guard logic.

---

## Module Layout

```
source/packages/automojo/sysman/common/
├── featurebase.py                       (existing — BaseFeatureManager)
└── vpnclientmanagementbase.py           (this spec)

source/testroots/testbase/
└── automojo/tests/sysman/common/
    └── test_vpnclientmanagementbase.py
```

---

## See Also

- [vpn-client-management contract](../contracts/vpn-client-management/contract.md)
- [automojo-interfaces IVPNClient](../../../automojo-interfaces/specs/) — peer-facing protocol
- Per-OS implementations under `automojo-sysman-*/specs/3-vpn-client-management/`

---

## Testing Strategy

Tests use a `MockCommandRunner` and a minimal concrete subclass
(`_FakeVPNClientManager`) that implements the abstract verbs with trivial
fixed-command bodies routed through `_dispatch_write`.

- Helper unit tests — `_validate_provider`, `_short_circuit_dry_run`,
  `_should_elevate`, `_dispatch_write` exit-code mapping (0 → SUCCESS,
  non-zero → FAILED).
- Abstract-class instantiation test — proving `TypeError` is raised when a
  subclass omits any abstract verb.
- Dataclass round-trip test — every dataclass survives `dataclasses.asdict`
  / re-construction.
- **Property tests (hypothesis)** required by the contract:
  - Install idempotency: `install ∘ install ≡ install` on the fake subclass
    with simulated state — first call returns `SUCCESS`, every subsequent
    call returns `SKIPPED`.
  - Uninstall idempotency: `uninstall ∘ uninstall ≡ uninstall` — same shape.
  - Bring-up / bring-down idempotency: bringing an already-up tunnel up
    returns `SKIPPED`; bringing an already-down tunnel down returns `SKIPPED`.
  - Dry-run safety: across hypothesis-generated command vectors, when
    `dry_run=True` the mock runner is never invoked and the result status is
    always `DRY_RUN`.
  - Elevation totality: for the cartesian product of
    `{elevated=False, True} × {READ, WRITE}` the result of `_should_elevate`
    matches the truth table in the contract.

All tests live in the same `unittest` harness; hypothesis is imported as a
test-only dependency.
