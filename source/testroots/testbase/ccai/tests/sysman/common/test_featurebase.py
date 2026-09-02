"""
    Tests for :class:`BaseFeatureManager` and its ``_dispatch`` helper.

    All tests use a ``_MockCommandRunner`` that records every ``run`` call
    and returns a pre-seeded :class:`RunResult`.  No live command runs.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from ccai import testbase

from ccai.interfaces.icommandrunner import RunResult

from ccai.sysman.common.featurebase import (
    DETAIL_ELEVATION_BLOCKED,
    ActionStatus,
    BaseFeatureManager,
    FeatureActionResult,
    FeatureConfig,
)


@dataclass
class _MockCommandRunner:
    """
        Minimal ``ICommandRunner`` stand-in returning one fixed result.
    """

    result: RunResult = field(default_factory=lambda: RunResult(exit_code=0, stdout="", stderr=""))
    calls: list = field(default_factory=list)

    def run(
        self,
        args: list,
        *,
        elevated: bool = False,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        on_output: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        capture_output: bool = True,
    ) -> RunResult:
        self.calls.append({"args": list(args), "elevated": elevated, "stdin": stdin})
        return self.result


@dataclass
class _ElevationAwareRunResult(RunResult):
    """
        Stand-in for the Windows ``WindowsRunResult`` extension.
    """
    elevation_blocked: bool = False


@dataclass
class _Result(FeatureActionResult):
    name: Optional[str] = None


class _Manager(BaseFeatureManager):
    result_class = _Result

    def do(self, name: str, *, elevated_override: Optional[bool] = None) -> _Result:
        rtnval = self._dispatch(
            command=["tool", "--do", name],
            detail=name,
            name=name,
            elevated_override=elevated_override,
        )
        return rtnval


def _manager(runner: _MockCommandRunner, **config) -> _Manager:
    rtnval = _Manager(runner=runner, config=FeatureConfig(**config))
    return rtnval


def test_dispatch_maps_zero_exit_to_success_and_echoes_extra():
    """
        Exit 0 becomes SUCCESS; detail, command and extra fields land on
        the result.
    """
    runner = _MockCommandRunner(result=RunResult(exit_code=0, stdout="out", stderr=""))
    result = _manager(runner).do("x")

    testbase.assert_equal(result.status, ActionStatus.SUCCESS)
    testbase.assert_equal(result.detail, "x")
    testbase.assert_equal(result.name, "x")
    testbase.assert_equal(result.command, ["tool", "--do", "x"])
    testbase.assert_equal(result.stdout, "out")
    return


def test_dispatch_maps_non_zero_exit_to_failed():
    """
        A non-zero exit becomes FAILED with the streams captured.
    """
    runner = _MockCommandRunner(result=RunResult(exit_code=3, stdout="", stderr="bad"))
    result = _manager(runner).do("x")

    testbase.assert_equal(result.status, ActionStatus.FAILED)
    testbase.assert_equal(result.exit_code, 3)
    testbase.assert_equal(result.stderr, "bad")
    testbase.assert_equal(result.detail, "x")
    return


def test_dispatch_dry_run_records_command_without_running():
    """
        Dry-run yields DRY_RUN with the argv and no runner call.
    """
    runner = _MockCommandRunner()
    result = _manager(runner, dry_run=True).do("x")

    testbase.assert_equal(result.status, ActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, ["tool", "--do", "x"])
    testbase.assert_equal(runner.calls, [])
    return


def test_dispatch_elevation_follows_config_and_override():
    """
        elevated comes from the config unless elevated_override is given.
    """
    runner = _MockCommandRunner()
    manager = _manager(runner, elevated=True)
    manager.do("a")
    manager.do("b", elevated_override=False)
    _manager(runner).do("c", elevated_override=True)

    testbase.assert_equal([c["elevated"] for c in runner.calls], [True, False, True])
    return


def test_dispatch_redacts_recorded_command_but_not_runner_argv():
    """
        Secret-bearing tokens are scrubbed on the result only.
    """
    runner = _MockCommandRunner()
    manager = _manager(runner)
    result = manager._dispatch(command=["tool", "--token", "s3cret", "https://u:p@h/x"])

    testbase.assert_equal(result.command, ["tool", "--token", "***", "https://***@h/x"])
    testbase.assert_equal(runner.calls[0]["args"], ["tool", "--token", "s3cret", "https://u:p@h/x"])
    return


def test_dispatch_surfaces_elevation_blocked_as_detail_token():
    """
        A runner result flagged elevation_blocked yields FAILED with the
        stable token in place of the caller's detail.
    """
    runner = _MockCommandRunner(
        result=_ElevationAwareRunResult(exit_code=-1, stdout="", stderr="not elevated", elevation_blocked=True),
    )
    result = _manager(runner, elevated=True).do("x")

    testbase.assert_equal(result.status, ActionStatus.FAILED)
    testbase.assert_equal(result.detail, DETAIL_ELEVATION_BLOCKED)
    testbase.assert_equal(result.stderr, "not elevated")
    testbase.assert_equal(result.name, "x")
    return


def test_dispatch_ignores_false_elevation_blocked_flag():
    """
        A Windows-shaped result with elevation_blocked=False keeps the
        caller's detail.
    """
    runner = _MockCommandRunner(
        result=_ElevationAwareRunResult(exit_code=1, stdout="", stderr="", elevation_blocked=False),
    )
    result = _manager(runner).do("x")

    testbase.assert_equal(result.status, ActionStatus.FAILED)
    testbase.assert_equal(result.detail, "x")
    return


def test_build_failed_unsupported_token_forms():
    """
        The unsupported-host token is emitted alone or with a message.
    """
    manager = _manager(_MockCommandRunner())
    bare = manager._build_failed_unsupported(verb="v", host_os="darwin")
    with_msg = manager._build_failed_unsupported(verb="v", host_os="darwin", message="no tool")

    testbase.assert_equal(bare.status, ActionStatus.FAILED)
    testbase.assert_equal(bare.detail, "unsupported_on_host_os_darwin")
    testbase.assert_equal(bare.stderr, "unsupported_on_host_os_darwin")
    testbase.assert_equal(with_msg.detail, "unsupported_on_host_os_darwin: no tool")
    return
