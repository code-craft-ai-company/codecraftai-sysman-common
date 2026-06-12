"""
    Unit and property tests for ``VPNClientManagementBase`` and the
    shared vpn-client-management data model.

    Converted from the legacy ``unittest.TestCase`` module to the testbase
    module-level ``def test_*() -> None`` form (Phase 7 unittest->testbase
    shift). Each former test method becomes a module-level function with an
    identical body. The ``setUp`` from ``ValidateProviderHelperTests`` is
    replicated per-test through the ``_make_validate_provider_fixture`` helper.
"""

import dataclasses

from typing import Callable, Dict, List, Optional, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st

from ccai.aspects.aspects import Aspects
from ccai.interfaces.icommandrunner import RunResult

from ccai.sysman.common.vpnclientmanagementbase import (
    VERB_KIND_READ,
    VERB_KIND_WRITE,
    VPNActionResult,
    VPNActionStatus,
    VPNClientManagementBase,
    VPNClientManagerConfig,
    VPNClientQueryError,
    VPNClientStatus,
    VPNProvider,
)


class _MockRunner:
    """
        Minimal ``ICommandRunner`` for unit tests. Records every call,
        returns a configurable :class:`RunResult` per call.
    """

    def __init__(self, *, queued: Optional[List[RunResult]] = None) -> None:
        if queued is None:
            self.queued: List[RunResult] = []
        else:
            self.queued = list(queued)
        self.calls: List[Dict[str, object]] = []
        return

    def run(
        self,
        args: List[str],
        *,
        elevated: bool = False,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        capture_output: bool = True,
    ) -> RunResult:
        call_record = {
            "args": list(args),
            "elevated": elevated,
            "stdin": stdin,
        }
        self.calls.append(call_record)

        if len(self.queued) > 0:
            rtnval = self.queued.pop(0)
        else:
            rtnval = RunResult(exit_code=0, stdout="", stderr="")
        return rtnval


class _FakeVPNClientManager(VPNClientManagementBase):
    """
        Minimal concrete subclass used to exercise the abstract verb
        surface and the shared helpers.

        Idempotency-guard state is held on the instance so the property
        tests can verify ``install ∘ install ≡ install`` and
        ``uninstall ∘ uninstall ≡ uninstall`` semantics.
    """

    def __init__(
        self,
        *,
        runner,
        config: Optional[VPNClientManagerConfig] = None,
    ) -> None:
        super().__init__(runner=runner, config=config)
        self._installed: Dict[VPNProvider, bool] = {}
        self._up: Dict[VPNProvider, Dict[str, object]] = {}
        return

    def install_tailscale(
        self,
        *,
        version: Optional[str],
        channel: str,
        aspects: Aspects,
    ) -> VPNActionResult:
        provider = VPNProvider.TAILSCALE
        command = ["apt-get", "install", "-y", "tailscale"]

        if self._installed.get(provider, False) is True:
            rtnval = VPNActionResult(
                status=VPNActionStatus.SKIPPED,
                provider=provider,
                detail="already_installed",
                command=command,
            )
            return rtnval

        dry = self._short_circuit_dry_run(
            provider=provider, command=command, detail="install_tailscale"
        )
        if dry is not None:
            return dry

        result = self._dispatch_write(
            provider=provider,
            command=command,
            detail="install_tailscale",
            aspects=aspects,
        )
        if result.status == VPNActionStatus.SUCCESS:
            self._installed[provider] = True
        return result

    def install_twingate_connector(
        self,
        *,
        version: Optional[str],
        aspects: Aspects,
    ) -> VPNActionResult:
        provider = VPNProvider.TWINGATE
        command = ["apt-get", "install", "-y", "twingate-connector"]

        if self._installed.get(provider, False) is True:
            rtnval = VPNActionResult(
                status=VPNActionStatus.SKIPPED,
                provider=provider,
                detail="already_installed",
                command=command,
            )
            return rtnval

        dry = self._short_circuit_dry_run(
            provider=provider, command=command, detail="install_twingate"
        )
        if dry is not None:
            return dry

        result = self._dispatch_write(
            provider=provider,
            command=command,
            detail="install_twingate",
            aspects=aspects,
        )
        if result.status == VPNActionStatus.SUCCESS:
            self._installed[provider] = True
        return result

    def configure(
        self,
        *,
        provider: VPNProvider,
        settings: Dict[str, str],
        aspects: Aspects,
    ) -> VPNActionResult:
        command = ["true"]
        dry = self._short_circuit_dry_run(
            provider=provider, command=command, detail="configure"
        )
        if dry is not None:
            return dry
        rtnval = self._dispatch_write(
            provider=provider,
            command=command,
            detail="configure",
            aspects=aspects,
        )
        return rtnval

    def bring_up(
        self,
        *,
        provider: VPNProvider,
        authkey: str,
        hostname: Optional[str],
        advertise_tags: Optional[List[str]],
        advertise_routes: Optional[List[str]],
        exit_node: bool,
        aspects: Aspects,
    ) -> VPNActionResult:
        command = ["tailscale", "up", "--authkey", authkey]
        desired = {
            "authkey": authkey,
            "hostname": hostname,
            "tags": tuple(advertise_tags) if advertise_tags is not None else None,
        }

        existing = self._up.get(provider)
        if existing is not None and existing == desired:
            rtnval = VPNActionResult(
                status=VPNActionStatus.SKIPPED,
                provider=provider,
                detail="already_up",
                command=command,
            )
            return rtnval

        dry = self._short_circuit_dry_run(
            provider=provider, command=command, detail="bring_up"
        )
        if dry is not None:
            return dry

        result = self._dispatch_write(
            provider=provider,
            command=command,
            detail="bring_up",
            aspects=aspects,
        )
        if result.status == VPNActionStatus.SUCCESS:
            self._up[provider] = desired
        return result

    def bring_down(
        self,
        *,
        provider: VPNProvider,
        aspects: Aspects,
    ) -> VPNActionResult:
        command = ["tailscale", "down"]
        if provider not in self._up:
            rtnval = VPNActionResult(
                status=VPNActionStatus.SKIPPED,
                provider=provider,
                detail="already_down",
                command=command,
            )
            return rtnval

        dry = self._short_circuit_dry_run(
            provider=provider, command=command, detail="bring_down"
        )
        if dry is not None:
            return dry

        result = self._dispatch_write(
            provider=provider,
            command=command,
            detail="bring_down",
            aspects=aspects,
        )
        if result.status == VPNActionStatus.SUCCESS:
            del self._up[provider]
        return result

    def status(
        self,
        *,
        provider: VPNProvider,
        aspects: Aspects,
    ) -> VPNClientStatus:
        installed = self._installed.get(provider, False)
        running = provider in self._up
        rtnval = VPNClientStatus(
            provider=provider,
            installed=installed,
            running=running,
        )
        return rtnval

    def uninstall(
        self,
        *,
        provider: VPNProvider,
        purge: bool,
        aspects: Aspects,
    ) -> VPNActionResult:
        command = ["apt-get", "remove", "-y", provider.value]

        if self._installed.get(provider, False) is False:
            rtnval = VPNActionResult(
                status=VPNActionStatus.SKIPPED,
                provider=provider,
                detail="not_installed",
                command=command,
            )
            return rtnval

        dry = self._short_circuit_dry_run(
            provider=provider, command=command, detail="uninstall"
        )
        if dry is not None:
            return dry

        result = self._dispatch_write(
            provider=provider,
            command=command,
            detail="uninstall",
            aspects=aspects,
        )
        if result.status == VPNActionStatus.SUCCESS:
            self._installed[provider] = False
        return result


_DEFAULT_ASPECTS = Aspects()


def _make_validate_provider_fixture() -> Tuple[_MockRunner, _FakeVPNClientManager]:
    """
        Replicates the ``setUp`` from the former ``ValidateProviderHelperTests``
        ``unittest.TestCase`` by building a fresh ``_MockRunner`` and a
        ``_FakeVPNClientManager`` bound to it.

        :returns: A tuple of the runner and the manager under test.
    """
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    rtnval = (runner, manager)
    return rtnval


def test_provider_enum_members() -> None:
    actual_values = sorted([member.value for member in VPNProvider])
    expected_values = ["tailscale", "twingate"]
    assert actual_values == expected_values
    return


def test_status_enum_members() -> None:
    actual_values = sorted([member.value for member in VPNActionStatus])
    expected_values = ["dry_run", "failed", "skipped", "success"]
    assert actual_values == expected_values
    return


def test_action_result_construction() -> None:
    result = VPNActionResult(
        status=VPNActionStatus.SUCCESS,
        provider=VPNProvider.TAILSCALE,
        detail="installed",
        exit_code=0,
        stdout="ok",
        stderr="",
        command=["apt-get", "install", "-y", "tailscale"],
    )
    assert result.status == VPNActionStatus.SUCCESS
    assert result.provider == VPNProvider.TAILSCALE
    assert result.exit_code == 0
    return


def test_dataclasses_roundtrip_asdict() -> None:
    result = VPNActionResult(
        status=VPNActionStatus.SUCCESS,
        provider=VPNProvider.TAILSCALE,
        detail="installed",
        exit_code=0,
        stdout="ok",
        stderr="",
        command=["x"],
    )
    as_dict = dataclasses.asdict(result)
    assert as_dict["exit_code"] == 0
    assert as_dict["command"] == ["x"]

    status_obj = VPNClientStatus(provider=VPNProvider.TAILSCALE)
    status_dict = dataclasses.asdict(status_obj)
    assert status_dict["peer_addresses"] == {}

    cfg = VPNClientManagerConfig(dry_run=True, elevated=True)
    cfg_dict = dataclasses.asdict(cfg)
    assert cfg_dict == {"dry_run": True, "elevated": True}
    return


def test_peer_addresses_is_per_instance() -> None:
    first = VPNClientStatus(provider=VPNProvider.TAILSCALE)
    second = VPNClientStatus(provider=VPNProvider.TAILSCALE)
    first.peer_addresses["host-a"] = "100.1.1.1"
    assert second.peer_addresses == {}
    return


def test_defaults() -> None:
    cfg = VPNClientManagerConfig()
    assert cfg.dry_run == False
    assert cfg.elevated == False
    return


def test_query_error_carries_fields() -> None:
    err = VPNClientQueryError(message="oops", exit_code=2, stderr="bad")
    assert err.message == "oops"
    assert err.exit_code == 2
    assert err.stderr == "bad"
    return


def test_validate_provider_passes_supported_returns_none() -> None:
    runner, manager = _make_validate_provider_fixture()
    result = manager._validate_provider(
        provider=VPNProvider.TAILSCALE,
        supported=[VPNProvider.TAILSCALE, VPNProvider.TWINGATE],
    )
    assert result is None
    return


def test_validate_provider_rejects_unsupported_returns_failed() -> None:
    runner, manager = _make_validate_provider_fixture()
    result = manager._validate_provider(
        provider=VPNProvider.TWINGATE,
        supported=[VPNProvider.TAILSCALE],
    )
    assert result is not None
    assert result is not None
    assert result.status == VPNActionStatus.FAILED
    assert result.provider == VPNProvider.TWINGATE
    assert "twingate" in result.detail
    assert "tailscale" in result.detail
    return


def test_short_circuit_dry_run_returns_dry_run_with_populated_fields() -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(
        runner=runner, config=VPNClientManagerConfig(dry_run=True)
    )
    result = manager._short_circuit_dry_run(
        provider=VPNProvider.TAILSCALE,
        command=["tailscale", "up"],
        detail="bring_up",
    )
    assert result is not None
    assert result is not None
    assert result.status == VPNActionStatus.DRY_RUN
    assert result.provider == VPNProvider.TAILSCALE
    assert result.command == ["tailscale", "up"]
    assert result.detail == "bring_up"
    assert runner.calls == []
    return


def test_short_circuit_dry_run_returns_none_when_not_dry() -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    result = manager._short_circuit_dry_run(
        provider=VPNProvider.TAILSCALE,
        command=["x"],
        detail=None,
    )
    assert result is None
    return


def test_should_elevate_truth_table() -> None:
    runner = _MockRunner()
    cases = [
        (VPNClientManagerConfig(elevated=False), VERB_KIND_READ, False),
        (VPNClientManagerConfig(elevated=False), VERB_KIND_WRITE, False),
        (VPNClientManagerConfig(elevated=True), VERB_KIND_READ, False),
        (VPNClientManagerConfig(elevated=True), VERB_KIND_WRITE, True),
    ]
    for cfg, kind, expected in cases:
        manager = _FakeVPNClientManager(runner=runner, config=cfg)
        actual = manager._should_elevate(kind=kind)
        assert actual == expected, "cfg.elevated={} kind={!r}".format(
            cfg.elevated, kind
        )
    return


def test_should_elevate_rejects_unknown_kind() -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    raised = False
    try:
        manager._should_elevate(kind="BOGUS")
    except ValueError:
        raised = True
    assert raised
    return


def test_dispatch_write_zero_exit_returns_success() -> None:
    queued = [RunResult(exit_code=0, stdout="ok", stderr="")]
    runner = _MockRunner(queued=queued)
    manager = _FakeVPNClientManager(runner=runner)
    result = manager._dispatch_write(
        provider=VPNProvider.TAILSCALE,
        command=["true"],
        detail="probe",
        aspects=_DEFAULT_ASPECTS,
    )
    assert result.status == VPNActionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.command == ["true"]
    assert len(runner.calls) == 1
    assert runner.calls[0]["elevated"] == False
    return


def test_dispatch_write_nonzero_exit_returns_failed() -> None:
    queued = [RunResult(exit_code=2, stdout="", stderr="bad")]
    runner = _MockRunner(queued=queued)
    manager = _FakeVPNClientManager(runner=runner)
    result = manager._dispatch_write(
        provider=VPNProvider.TAILSCALE,
        command=["false"],
        detail="probe",
        aspects=_DEFAULT_ASPECTS,
    )
    assert result.status == VPNActionStatus.FAILED
    assert result.exit_code == 2
    assert result.stderr == "bad"
    return


def test_dispatch_write_honors_elevation_flag() -> None:
    queued = [RunResult(exit_code=0, stdout="", stderr="")]
    runner = _MockRunner(queued=queued)
    manager = _FakeVPNClientManager(
        runner=runner, config=VPNClientManagerConfig(elevated=True)
    )
    manager._dispatch_write(
        provider=VPNProvider.TAILSCALE,
        command=["apt-get", "install"],
        detail="install",
        aspects=_DEFAULT_ASPECTS,
    )
    assert runner.calls[0]["elevated"] == True
    return


def test_abstract_class_cannot_instantiate_without_overrides() -> None:
    runner = _MockRunner()
    raised = False
    try:
        VPNClientManagementBase(runner=runner)
    except TypeError:
        raised = True
    assert raised
    return


@given(
    version=st.one_of(st.none(), st.text(min_size=1, max_size=8)),
    channel=st.sampled_from(["stable", "unstable", "beta"]),
)
@settings(max_examples=25, deadline=None)
def test_property_install_is_idempotent(
    version: Optional[str], channel: str
) -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    first = manager.install_tailscale(
        version=version, channel=channel, aspects=_DEFAULT_ASPECTS
    )
    second = manager.install_tailscale(
        version=version, channel=channel, aspects=_DEFAULT_ASPECTS
    )
    assert first.status == VPNActionStatus.SUCCESS
    assert second.status == VPNActionStatus.SKIPPED
    return


@given(purge=st.booleans())
@settings(max_examples=10, deadline=None)
def test_property_uninstall_is_idempotent(purge: bool) -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    manager.install_tailscale(
        version=None, channel="stable", aspects=_DEFAULT_ASPECTS
    )
    first = manager.uninstall(
        provider=VPNProvider.TAILSCALE, purge=purge, aspects=_DEFAULT_ASPECTS
    )
    second = manager.uninstall(
        provider=VPNProvider.TAILSCALE, purge=purge, aspects=_DEFAULT_ASPECTS
    )
    assert first.status == VPNActionStatus.SUCCESS
    assert second.status == VPNActionStatus.SKIPPED
    return


@given(
    authkey=st.text(min_size=1, max_size=16),
    hostname=st.one_of(st.none(), st.text(min_size=1, max_size=8)),
)
@settings(max_examples=20, deadline=None)
def test_property_bring_up_idempotent_on_matching_state(
    authkey: str, hostname: Optional[str]
) -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    manager.install_tailscale(
        version=None, channel="stable", aspects=_DEFAULT_ASPECTS
    )
    first = manager.bring_up(
        provider=VPNProvider.TAILSCALE,
        authkey=authkey,
        hostname=hostname,
        advertise_tags=None,
        advertise_routes=None,
        exit_node=False,
        aspects=_DEFAULT_ASPECTS,
    )
    second = manager.bring_up(
        provider=VPNProvider.TAILSCALE,
        authkey=authkey,
        hostname=hostname,
        advertise_tags=None,
        advertise_routes=None,
        exit_node=False,
        aspects=_DEFAULT_ASPECTS,
    )
    assert first.status == VPNActionStatus.SUCCESS
    assert second.status == VPNActionStatus.SKIPPED
    return


def test_property_bring_down_idempotent_on_matching_state() -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(runner=runner)
    first = manager.bring_down(
        provider=VPNProvider.TAILSCALE, aspects=_DEFAULT_ASPECTS
    )
    assert first.status == VPNActionStatus.SKIPPED
    assert runner.calls == []
    return


@given(
    version=st.one_of(st.none(), st.text(min_size=1, max_size=8)),
    channel=st.sampled_from(["stable", "unstable"]),
)
@settings(max_examples=25, deadline=None)
def test_property_dry_run_never_invokes_runner(
    version: Optional[str], channel: str
) -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(
        runner=runner, config=VPNClientManagerConfig(dry_run=True)
    )
    result = manager.install_tailscale(
        version=version, channel=channel, aspects=_DEFAULT_ASPECTS
    )
    assert result.status == VPNActionStatus.DRY_RUN
    assert runner.calls == []
    return


@given(
    elevated=st.booleans(),
    kind=st.sampled_from([VERB_KIND_READ, VERB_KIND_WRITE]),
)
@settings(max_examples=20, deadline=None)
def test_property_elevation_truth_table(elevated: bool, kind: str) -> None:
    runner = _MockRunner()
    manager = _FakeVPNClientManager(
        runner=runner, config=VPNClientManagerConfig(elevated=elevated)
    )
    expected = (kind == VERB_KIND_WRITE) and (elevated is True)
    actual = manager._should_elevate(kind=kind)
    assert actual == expected
    return
