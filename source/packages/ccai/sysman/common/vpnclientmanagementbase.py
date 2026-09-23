"""
    Abstract feature-manager base for the vpn-client-management contract.

    ``VPNClientManagementBase`` is the only place the contract's enums,
    dataclasses, exceptions, and verb signatures are defined. Per-OS
    subclasses (``UbuntuVPNClientManager``, ``RedHatVPNClientManager``,
    ``MacosVPNClientManager``, ``WindowsVPNClientManager``) inherit from
    this base, implement the abstract verbs, and reuse the shared
    helpers below.

    The base never invokes the command runner directly except through
    :meth:`VPNClientManagementBase._dispatch_write`, which subclasses
    delegate to.

    See :doc:`/specs/contracts/vpn-client-management/contract.md` for the
    cross-OS contract.
"""

import os

from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Optional

from ccai.aspects.aspects import Aspects
from ccai.interfaces.icommandrunner import ICommandRunner, RunResult

from ccai.sysman.common.featurebase import BaseFeatureManager
from ccai.sysman.common.vpnactionresult import VPNActionResult
from ccai.sysman.common.vpnactionstatus import VPNActionStatus
from ccai.sysman.common.vpnclientmanagerconfig import VPNClientManagerConfig
from ccai.sysman.common.vpnclientqueryerror import VPNClientQueryError
from ccai.sysman.common.vpnclientstatus import VPNClientStatus
from ccai.sysman.common.vpnprovider import VPNProvider


VERB_KIND_READ = "READ"
VERB_KIND_WRITE = "WRITE"


class VPNClientManagementBase(BaseFeatureManager, ABC):
    """
        Abstract feature manager for the vpn-client-management contract.

        Per-OS subclasses override every abstract verb and use the shared
        helpers (``_validate_provider``, ``_short_circuit_dry_run``,
        ``_should_elevate``, ``_dispatch_write``) to keep behaviour
        uniform across OSes and providers.
    """

    feature_name: Optional[str] = "vpn-client-management"

    def __init__(
        self,
        *,
        runner: ICommandRunner,
        config: Optional[VPNClientManagerConfig] = None,
    ) -> None:
        """
            :param runner: Command runner injected by the maintenance
                           coordinator. Every write goes through it.
            :param config: Manager configuration. Defaults to the base
                           :class:`VPNClientManagerConfig` when omitted.
        """
        if config is None:
            cfg = VPNClientManagerConfig()
        else:
            cfg = config

        super().__init__(runner=runner, config=cfg)
        self._config: VPNClientManagerConfig = cfg
        return

    # --------------------------------------------------------------
    # Abstract verb surface
    # --------------------------------------------------------------

    @abstractmethod
    def install_tailscale(
        self,
        *,
        version: Optional[str],
        channel: str,
        aspects: Aspects,
    ) -> VPNActionResult:
        """
            Install the Tailscale client (``tailscaled``).

            :param version: Specific package version to install, or
                            ``None`` to use the channel default.
            :param channel: Release channel identifier
                            (``"stable"``, ``"unstable"``, etc.).
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """

    @abstractmethod
    def install_twingate_connector(
        self,
        *,
        version: Optional[str],
        aspects: Aspects,
    ) -> VPNActionResult:
        """
            Install the Twingate Connector daemon.

            :param version: Specific package version to install, or
                            ``None`` to use the repository default.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """

    @abstractmethod
    def configure(
        self,
        *,
        provider: VPNProvider,
        settings: Dict[str, str],
        aspects: Aspects,
    ) -> VPNActionResult:
        """
            Write provider-specific configuration.

            :param provider: Target provider.
            :param settings: Provider-specific key/value settings.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """

    @abstractmethod
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
        """
            Bring the mesh-VPN tunnel up.

            :param provider: Target provider.
            :param authkey: Vendor-issued authentication key.
            :param hostname: Hostname to register, or ``None`` to defer
                             to the daemon default.
            :param advertise_tags: Tags to advertise, or ``None``.
            :param advertise_routes: Subnet routes to advertise, or
                                     ``None``.
            :param exit_node: When True, advertise this host as an exit
                              node.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """

    @abstractmethod
    def bring_down(
        self,
        *,
        provider: VPNProvider,
        aspects: Aspects,
    ) -> VPNActionResult:
        """
            Bring the mesh-VPN tunnel down without uninstalling.

            :param provider: Target provider.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """

    @abstractmethod
    def status(
        self,
        *,
        provider: VPNProvider,
        aspects: Aspects,
    ) -> VPNClientStatus:
        """
            Report the local daemon state.

            :param provider: Target provider.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNClientStatus` snapshot.
            :raises VPNClientQueryError: When the underlying query
                command fails for reasons other than "daemon not
                installed" or "daemon not running".
        """

    @abstractmethod
    def uninstall(
        self,
        *,
        provider: VPNProvider,
        purge: bool,
        aspects: Aspects,
    ) -> VPNActionResult:
        """
            Uninstall the provider daemon.

            :param provider: Target provider.
            :param purge: When True, remove residual configuration
                          files in addition to the package.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """

    # --------------------------------------------------------------
    # Shared helpers
    # --------------------------------------------------------------

    def _validate_provider(
        self,
        *,
        provider: VPNProvider,
        supported: Iterable[VPNProvider],
    ) -> Optional[VPNActionResult]:
        """
            Validate that ``provider`` is in the per-OS supported set.

            :param provider: The provider passed by the caller.
            :param supported: The set of providers the subclass supports.

            :returns: ``None`` when the provider is supported; otherwise
                      a :class:`VPNActionResult` with
                      ``status=FAILED`` and a descriptive ``detail``.
        """
        supported_list = list(supported)
        is_member = provider in supported_list
        if is_member is True:
            rtnval: Optional[VPNActionResult] = None
            return rtnval

        supported_names = sorted([item.value for item in supported_list])
        detail_lines = ["Unsupported VPN provider for this manager."]
        detail_lines.append("    PROVIDED: {!r}".format(provider.value))
        detail_lines.append("    SUPPORTED: {}".format(supported_names))
        detail = os.linesep.join(detail_lines)

        rtnval = VPNActionResult(
            status=VPNActionStatus.FAILED,
            provider=provider,
            detail=detail,
            exit_code=None,
            stdout=None,
            stderr=None,
            command=None,
        )
        return rtnval

    def _short_circuit_dry_run(
        self,
        *,
        provider: VPNProvider,
        command: List[str],
        detail: Optional[str] = None,
    ) -> Optional[VPNActionResult]:
        """
            Return a populated ``DRY_RUN`` result when the manager
            config has ``dry_run=True``; otherwise return ``None``.

            :param provider: Provider the would-have-been command
                             targets.
            :param command: The argv that would have been executed.
            :param detail: Optional human-readable description.

            :returns: A :class:`VPNActionResult` with
                      ``status=DRY_RUN`` when dry-run is active, or
                      ``None`` otherwise.
        """
        if self._config.dry_run is False:
            rtnval: Optional[VPNActionResult] = None
            return rtnval

        command_copy = list(command)
        rtnval = VPNActionResult(
            status=VPNActionStatus.DRY_RUN,
            provider=provider,
            detail=detail,
            exit_code=None,
            stdout=None,
            stderr=None,
            command=command_copy,
        )
        return rtnval

    def _should_elevate(self, *, kind: str) -> bool:
        """
            Decide whether ``elevated=True`` should be passed to the
            runner for an operation of the given verb kind.

            :param kind: Either ``"READ"`` or ``"WRITE"``.

            :returns: True only when ``kind == "WRITE"`` and the
                      manager config has ``elevated=True``.
            :raises ValueError: When ``kind`` is neither ``"READ"`` nor
                                ``"WRITE"``.
        """
        if kind == VERB_KIND_READ:
            rtnval = False
            return rtnval

        if kind == VERB_KIND_WRITE:
            rtnval = bool(self._config.elevated)
            return rtnval

        err_msg_lines = ["Unknown verb kind passed to _should_elevate."]
        err_msg_lines.append("    PROVIDED: {!r}".format(kind))
        err_msg_lines.append(
            "    ACCEPTED: [{!r}, {!r}]".format(VERB_KIND_READ, VERB_KIND_WRITE)
        )
        err_msg = os.linesep.join(err_msg_lines)
        raise ValueError(err_msg)

    def _dispatch_write(
        self,
        *,
        provider: VPNProvider,
        command: List[str],
        detail: Optional[str],
        aspects: Aspects,
    ) -> VPNActionResult:
        """
            Run a write command through the injected runner and map the
            :class:`RunResult` to a :class:`VPNActionResult`.

            This helper never raises for non-zero exit codes; it maps
            them to ``status=FAILED``. Callers are responsible for
            performing dry-run and idempotency checks before invoking
            this helper.

            :param provider: Provider the command targets.
            :param command: The argv to execute.
            :param detail: Optional human-readable description.
            :param aspects: Behaviour controls forwarded to the runner.

            :returns: A :class:`VPNActionResult` describing the outcome.
        """
        command_copy = list(command)
        run_elevated = self._should_elevate(kind=VERB_KIND_WRITE)

        run_result: RunResult = self._runner.run(
            command_copy,
            elevated=run_elevated,
            timeout=aspects.connection_timeout,
        )

        if run_result.exit_code == 0:
            mapped_status = VPNActionStatus.SUCCESS
        else:
            mapped_status = VPNActionStatus.FAILED

        rtnval = VPNActionResult(
            status=mapped_status,
            provider=provider,
            detail=detail,
            exit_code=run_result.exit_code,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            command=command_copy,
        )
        return rtnval


__all__ = [
    "VPNClientManagementBase",
    "VPNProvider",
    "VPNActionStatus",
    "VPNActionResult",
    "VPNClientStatus",
    "VPNClientManagerConfig",
    "VPNClientQueryError",
    "VERB_KIND_READ",
    "VERB_KIND_WRITE",
]
