"""
    Canonical shared featurebase for codecraftai-sysman-* packages.

    Hosts the cross-OS base classes and helpers that every per-OS sysman
    package extends:

        * ``ActionStatus`` — the canonical outcome-status enum
          (``SUCCESS``, ``FAILED``, ``SKIPPED``, ``DRY_RUN``).
        * ``FeatureConfig`` — the base config dataclass with ``dry_run``
          and ``elevated`` flags.
        * ``FeatureActionResult`` — the base per-operation result shape
          (``status``, ``detail``, ``exit_code``, ``stdout``, ``stderr``,
          ``command``).
        * ``BaseFeatureManager`` — the shared manager class with the
          ``_dispatch`` / ``_wrap_result`` helpers that every feature
          manager uses to route mutating commands through the injected
          ``ICommandRunner``.

    UEFI-host-dispatch additions used by the ``codecraftai-sysman-uefi``
    package (and ignored by the per-OS packages that do not need
    cross-host dispatch):

        * ``detect_host_os`` / ``normalise_override_host_os`` helpers.
        * ``BaseFeatureManager`` stores ``self._host_os`` at
          construction so per-feature dispatch tables can route on it
          without re-querying ``platform.system()`` at call time.
        * The ``override_host_os`` config field is honoured for test
          coverage of all three host OS branches from any developer
          workstation.
        * ``_build_failed_unsupported`` constructs a stable
          ``FAILED`` result for verbs with no scriptable
          implementation on the given host OS.

    Windows elevation-blocked pass-through (Convention 6):

        * When the runner's ``RunResult`` carries a truthy
          ``elevation_blocked`` attribute (the Windows runners set it
          when ``elevated=True`` was requested but the process holds no
          Administrator token), ``_dispatch`` replaces ``detail`` with
          the stable token :data:`DETAIL_ELEVATION_BLOCKED` so
          coordinators can distinguish a refused elevation from a real
          command failure without parsing stderr.  POSIX runners never
          set the attribute, so the branch is inert there.
"""

import os
import platform

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ccai.interfaces.icommandrunner import ICommandRunner, RunResult

from ccai.sysman.common.commandredaction import redact_command


HOST_OS_LINUX = "linux"
HOST_OS_DARWIN = "darwin"
HOST_OS_WINDOWS = "windows"

_SUPPORTED_HOST_OS = frozenset({HOST_OS_LINUX, HOST_OS_DARWIN, HOST_OS_WINDOWS})

_PLATFORM_TO_HOST_OS = {
    "Linux":   HOST_OS_LINUX,
    "Darwin":  HOST_OS_DARWIN,
    "Windows": HOST_OS_WINDOWS,
}

# Stable detail token recorded on a FAILED result when the runner refused
# the call because the process is not elevated (Windows runners only).
DETAIL_ELEVATION_BLOCKED = "elevation_blocked"


def detect_host_os() -> str:
    """
        Detect the running host OS using :func:`platform.system` and map it
        to one of the lower-cased UEFI-package host-OS keys.

        :returns: One of ``"linux"``, ``"darwin"``, ``"windows"``.
        :raises RuntimeError: When the running platform is not one of the
                              three supported host OSes.
    """
    raw = platform.system()
    if raw not in _PLATFORM_TO_HOST_OS:
        err_msg = "unsupported_host_os: {}".format(raw)
        raise RuntimeError(err_msg)

    rtnval = _PLATFORM_TO_HOST_OS[raw]
    return rtnval


def normalise_override_host_os(override: Optional[str]) -> Optional[str]:
    """
        Normalise a config-supplied ``override_host_os`` value.

        Accepts either the lower-cased canonical form (``"linux"``,
        ``"darwin"``, ``"windows"``) or the title-cased
        :func:`platform.system` form (``"Linux"``, ``"Darwin"``,
        ``"Windows"``).

        :param override: The raw config value or ``None``.

        :returns: The normalised lower-cased form, or ``None`` when the
                  caller passed ``None``.
        :raises ValueError: When the override is not one of the accepted
                            values.
    """
    if override is None:
        rtnval = None
        return rtnval

    if override in _PLATFORM_TO_HOST_OS:
        rtnval = _PLATFORM_TO_HOST_OS[override]
        return rtnval

    lowered = override.lower()
    if lowered in _SUPPORTED_HOST_OS:
        rtnval = lowered
        return rtnval

    accepted = sorted(_SUPPORTED_HOST_OS) + sorted(_PLATFORM_TO_HOST_OS.keys())
    err_msg_lines = ["override_host_os value is not one of the supported platforms."]
    err_msg_lines.append("    PROVIDED: {!r}".format(override))
    err_msg_lines.append("    ACCEPTED: {}".format(accepted))
    err_msg = os.linesep.join(err_msg_lines)
    raise ValueError(err_msg)


class ActionStatus(Enum):
    """
        Canonical outcome-status enum for every feature manager in
        this package.
    """
    SUCCESS = "success"
    FAILED  = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"


@dataclass
class FeatureConfig:
    """
        Canonical configuration base for every feature manager.

        :param dry_run: When True, no mutating command is dispatched;
                        the would-have-been command is still recorded
                        on the returned :class:`FeatureActionResult`.
        :param elevated: When True, mutating commands are dispatched
                         with ``elevated=True`` to the runner.
    """
    dry_run: bool = False
    elevated: bool = False


@dataclass
class FeatureActionResult:
    """
        Canonical per-operation result shape.  Every feature's own
        ``*ActionResult`` dataclass subclasses this and adds
        feature-specific fields (path, name, archive_path, ...).
    """
    status: ActionStatus
    detail: Optional[str] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    command: Optional[list[str]] = None


class BaseFeatureManager:
    """
        Shared base for every feature manager.

        Subclasses override the class variables ``result_class`` and (rarely)
        ``status_class`` to plug in feature-specific result and status types.
        Methods that need to populate extra result fields either pass them
        through as ``**extra`` to :meth:`_dispatch` / :meth:`_wrap_result`, or
        override :meth:`_wrap_result` to inject them explicitly.
    """

    # TODO: Once a MaintenanceReport equivalent exists in this package,
    #       reinstate the auto-wired reporting hook that lives in the RHEL
    #       featurebase.

    # Feature-specific result dataclass.  MUST subclass
    # :class:`FeatureActionResult` so the standard fields are accepted as
    # keyword arguments.
    result_class: type = FeatureActionResult

    # Feature-specific status enum.  Defaults to :class:`ActionStatus`;
    # subclasses override only if they extend the base enum.
    status_class: type = ActionStatus

    # Feature name used for future auto-reporting.  Subclasses set this to
    # the canonical spec-folder name.
    feature_name: Optional[str] = None

    def __init__(
        self,
        runner: ICommandRunner,
        config: Optional[FeatureConfig] = None,
    ) -> None:
        """
            :param runner: The command runner used by every mutating
                           operation.
            :param config: Manager configuration.  Defaults to the base
                           :class:`FeatureConfig` when omitted.
        """
        if config is None:
            config = FeatureConfig()

        self._runner: ICommandRunner = runner
        self._config: FeatureConfig = config

        override_attr = getattr(config, "override_host_os", None)
        normalised_override = normalise_override_host_os(override=override_attr)
        if normalised_override is not None:
            self._host_os: str = normalised_override
        else:
            self._host_os = detect_host_os()
        return

    @property
    def config(self) -> FeatureConfig:
        """
            The active configuration.
        """
        return self._config

    @property
    def runner(self) -> ICommandRunner:
        """
            The injected command runner.
        """
        return self._runner

    @property
    def host_os(self) -> str:
        """
            The detected (or overridden) host OS, lower-cased.  One of
            ``"linux"``, ``"darwin"``, ``"windows"``.
        """
        return self._host_os

    def _dispatch(
        self,
        *,
        command: list[str],
        detail: Optional[str] = None,
        stdin: Optional[str] = None,
        operation: Optional[str] = None,
        elevated_override: Optional[bool] = None,
        **extra,
    ) -> FeatureActionResult:
        """
            Dispatch a mutating command through the runner, honouring
            dry-run, and map the result to the feature's result type.

            :param command: Argument vector for the runner.
            :param detail: Optional human-readable description.
            :param stdin: Optional stdin payload forwarded to the runner.
            :param operation: Operation name (reserved for future
                              auto-reporting).
            :param elevated_override: When not None, overrides the config's
                                      ``elevated`` flag for this single
                                      dispatch.
            :param extra: Extra keyword arguments forwarded to
                          :meth:`_wrap_result`.

            :returns: The wrapped :class:`FeatureActionResult`.  When the
                      runner reports ``elevation_blocked``, ``detail`` is
                      the stable token :data:`DETAIL_ELEVATION_BLOCKED`.
        """
        command_copy = list(command)

        if self._config.dry_run:
            dry_result = self._wrap_result(
                status=self.status_class.DRY_RUN,
                detail=detail,
                command=command_copy,
                **extra,
            )
            return dry_result

        if elevated_override is None:
            run_elevated = self._config.elevated
        else:
            run_elevated = elevated_override

        run_result: RunResult = self._runner.run(
            command_copy,
            elevated=run_elevated,
            stdin=stdin,
        )

        if run_result.exit_code == 0:
            mapped_status = self.status_class.SUCCESS
        else:
            mapped_status = self.status_class.FAILED

        # Convention 6: a Windows runner that refused the call for lack of
        # an Administrator token reports ``elevation_blocked=True``.  The
        # stable token replaces the caller's detail so the condition is
        # machine-detectable on the result; the runner's stderr still
        # carries the human-readable explanation.
        elevation_blocked = getattr(run_result, "elevation_blocked", False)
        if elevation_blocked:
            final_detail: Optional[str] = DETAIL_ELEVATION_BLOCKED
        else:
            final_detail = detail

        # The upstream ``ccai.interfaces.icommandrunner.RunResult`` does
        # not carry a ``command`` field, so we record the argv the caller
        # supplied.  The shared dispatch is credential-safe by design —
        # secret bytes are routed via ``stdin`` and never placed on argv —
        # but we additionally run the recorded argv through ``redact_command``
        # as defense-in-depth, so a per-OS manager that mistakenly puts a
        # secret on the command line still cannot leak it into a logged or
        # persisted result (matching the VPNActionResult redaction path).
        final_result = self._wrap_result(
            status=mapped_status,
            detail=final_detail,
            exit_code=run_result.exit_code,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            command=redact_command(command=command_copy),
            **extra,
        )
        return final_result

    def _wrap_result(
        self,
        *,
        status: ActionStatus,
        detail: Optional[str] = None,
        exit_code: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        command: Optional[list[str]] = None,
        **extra,
    ) -> FeatureActionResult:
        """
            Construct the feature-specific result.  The default instantiates
            ``self.result_class`` with every passed field; subclasses whose
            result dataclass does not accept a given key override this
            method to filter or transform.
        """
        kwargs = {
            "status": status,
            "detail": detail,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "command": command,
        }
        kwargs.update(extra)
        rtnval = self.result_class(**kwargs)
        return rtnval

    def _build_failed_unsupported(
        self,
        *,
        verb: str,
        host_os: str,
        message: Optional[str] = None,
        **extra,
    ) -> FeatureActionResult:
        """
            Build a stable ``FAILED`` result for a verb that has no
            scriptable implementation on the given host OS.  No runner call
            is issued.

            :param verb: The verb name (used in the detail token).
            :param host_os: The detected host OS, lower-cased.
            :param message: Optional human-readable supplement appended to
                            the stable token in the ``detail`` field.
            :param extra: Extra keyword arguments forwarded to
                          :meth:`_wrap_result`.

            :returns: The wrapped :class:`FeatureActionResult`.
        """
        token = "unsupported_on_host_os_{}".format(host_os)
        if message is not None and len(message) > 0:
            detail = "{}: {}".format(token, message)
        else:
            detail = token

        rtnval = self._wrap_result(
            status=self.status_class.FAILED,
            detail=detail,
            command=None,
            stderr=token,
            **extra,
        )
        return rtnval
