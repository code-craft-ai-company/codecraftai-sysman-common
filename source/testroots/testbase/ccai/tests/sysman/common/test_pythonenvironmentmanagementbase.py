"""
    Tests for :class:`PythonEnvironmentManagementBase` and the shared
    python-environment-management data model.

    All tests use a ``_MockCommandRunner`` that records every ``run`` call
    and returns pre-seeded :class:`RunResult` values keyed by argv tuple.
    No live interpreter, ``venv`` module, or ``pip`` is invoked.  The
    concrete manager under test is a minimal subclass that selects the
    POSIX layout; per-OS packages test their own layout selection.
"""

import json

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ccai import testbase

from ccai.interfaces.icommandrunner import RunResult

from ccai.sysman.common.pythonenvironmentlayout import (
    BsdPythonEnvironmentLayout,
    PosixPythonEnvironmentLayout,
    PythonEnvironmentLayout,
    WindowsPythonEnvironmentLayout,
)
from ccai.sysman.common.pythonenvironmentmanagementbase import (
    DETAIL_ELEVATION_BLOCKED,
    PythonEnvActionResult,
    PythonEnvActionStatus,
    PythonEnvDeployResult,
    PythonEnvInfo,
    PythonEnvManagerConfig,
    PythonEnvQueryError,
    PythonEnvSpec,
    PythonEnvironmentManagementBase,
    PythonPackageInfo,
)


_VENV = "/opt/venvs/app"
_VENV_PYTHON = "/opt/venvs/app/bin/python"
_PIP_PREFIX = [_VENV_PYTHON, "-m", "pip", "--disable-pip-version-check", "--no-input"]
_VERSION_SNIPPET = "import platform; print(platform.python_version())"


# ----------------------------------------------------------------------
# Test scaffolding
# ----------------------------------------------------------------------


@dataclass
class _MockCommandRunner:
    """
        Minimal ``ICommandRunner`` stand-in that records every call and
        returns pre-seeded :class:`RunResult` values keyed by argv tuple.
    """

    results: dict = field(default_factory=dict)
    default_result: Optional[RunResult] = None
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
        call_record = {
            "args": list(args),
            "elevated": elevated,
            "stdin": stdin,
            "env": env,
        }
        self.calls.append(call_record)

        key = tuple(args)
        if key in self.results:
            rtnval = self.results[key]
            return rtnval

        if self.default_result is not None:
            rtnval = self.default_result
            return rtnval

        rtnval = RunResult(exit_code=0, stdout="", stderr="")
        return rtnval


@dataclass
class _ElevationBlockedRunResult(RunResult):
    """
        Stand-in for the Windows ``WindowsRunResult`` extension.
    """
    elevation_blocked: bool = False


class _PosixPythonEnvManager(PythonEnvironmentManagementBase):
    """
        Concrete manager selecting the POSIX layout.
    """

    def _build_layout(self) -> PythonEnvironmentLayout:
        rtnval = PosixPythonEnvironmentLayout()
        return rtnval


def _ok(stdout: str = "") -> RunResult:
    rtnval = RunResult(exit_code=0, stdout=stdout, stderr="")
    return rtnval


def _fail(stderr: str = "boom", exit_code: int = 1) -> RunResult:
    rtnval = RunResult(exit_code=exit_code, stdout="", stderr=stderr)
    return rtnval


def _pip_argv(*pip_args: str) -> list:
    rtnval = list(_PIP_PREFIX)
    rtnval.extend(pip_args)
    return rtnval


def _pip_list_result(entries: list) -> RunResult:
    payload = [{"name": name, "version": version} for name, version in entries]
    rtnval = _ok(stdout=json.dumps(payload))
    return rtnval


def _seed_env_valid(runner: _MockCommandRunner, *, version: str = "3.12.3") -> None:
    runner.results[("test", "-d", _VENV)] = _ok()
    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _ok(stdout=version + "\n")
    return


def _seed_env_missing(runner: _MockCommandRunner) -> None:
    runner.results[("test", "-d", _VENV)] = _fail(stderr="", exit_code=1)
    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _fail(exit_code=127)
    return


def _seed_installed(runner: _MockCommandRunner, entries: list) -> None:
    runner.results[tuple(_pip_argv("list", "--format", "json"))] = _pip_list_result(entries)
    return


def _make_manager(
    runner: _MockCommandRunner,
    config: Optional[PythonEnvManagerConfig] = None,
) -> _PosixPythonEnvManager:
    rtnval = _PosixPythonEnvManager(runner=runner, config=config)
    return rtnval


def _write_calls(runner: _MockCommandRunner) -> list:
    """
        Every call that is not a read probe (``test -d``, ``python -c``,
        ``pip list``, ``pip freeze``, ``stat`` for the owner).
    """
    rtnval = []
    for call in runner.calls:
        args = call["args"]
        if args[:1] == ["test"]:
            continue
        if args[:1] == ["stat"]:
            continue
        if args[:2] == [_VENV_PYTHON, "-c"]:
            continue
        if args[:6] == _pip_argv("list"):
            continue
        if args[:6] == _pip_argv("freeze"):
            continue
        rtnval.append(call)
    return rtnval


# ----------------------------------------------------------------------
# Layouts
# ----------------------------------------------------------------------


def test_posix_layout_paths_and_probes():
    """
        The POSIX layout uses bin/python, test -d and rm -rf.
    """
    layout = PosixPythonEnvironmentLayout()
    testbase.assert_equal(layout.default_interpreter_argv(), ["python3"])
    testbase.assert_equal(layout.venv_python_path(path=_VENV), _VENV_PYTHON)
    testbase.assert_equal(layout.join_path("/a", "b", "c"), "/a/b/c")
    testbase.assert_equal(layout.build_directory_exists_argv(path=_VENV), ["test", "-d", _VENV])
    testbase.assert_equal(layout.build_remove_tree_argv(path=_VENV), ["rm", "-rf", _VENV])
    return


def test_windows_layout_paths_and_probes():
    """
        The Windows layout uses Scripts\\python.exe, the py launcher, and
        PowerShell Test-Path / Remove-Item scriptblocks.
    """
    layout = WindowsPythonEnvironmentLayout()
    path = r"C:\venvs\app"
    testbase.assert_equal(layout.default_interpreter_argv(), ["py", "-3"])
    testbase.assert_equal(layout.venv_python_path(path=path), r"C:\venvs\app\Scripts\python.exe")
    testbase.assert_equal(layout.join_path(r"C:\a", "b"), r"C:\a\b")

    exists_argv = layout.build_directory_exists_argv(path=path)
    testbase.assert_equal(
        exists_argv[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"],
    )
    testbase.assert_equal(
        exists_argv[4],
        "if (Test-Path -LiteralPath 'C:\\venvs\\app' -PathType Container) "
        "{ exit 0 } else { exit 1 }",
    )

    remove_argv = layout.build_remove_tree_argv(path=path)
    testbase.assert_equal(
        remove_argv[4], "Remove-Item -LiteralPath 'C:\\venvs\\app' -Recurse -Force",
    )
    return


def test_windows_layout_escapes_single_quotes_and_honours_executable():
    """
        Single quotes in the path are doubled and the configured
        PowerShell executable is used.
    """
    layout = WindowsPythonEnvironmentLayout(powershell_executable=r"C:\ps\pwsh.exe")
    argv = layout.build_remove_tree_argv(path=r"C:\it's\venv")
    testbase.assert_equal(argv[0], r"C:\ps\pwsh.exe")
    testbase.assert_equal(argv[4], "Remove-Item -LiteralPath 'C:\\it''s\\venv' -Recurse -Force")
    return


# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------


def test_config_defaults():
    """
        The config carries the contract-mandated defaults.
    """
    config = PythonEnvManagerConfig()
    testbase.assert_equal(config.dry_run, False)
    testbase.assert_equal(config.elevated, False)
    testbase.assert_equal(config.base_interpreter, None)
    testbase.assert_equal(config.index_url, None)
    testbase.assert_equal(config.extra_index_urls, None)
    testbase.assert_equal(config.trusted_hosts, None)
    testbase.assert_equal(config.pip_options, None)
    testbase.assert_equal(config.upgrade_pip, True)
    testbase.assert_equal(config.system_site_packages, False)
    return


def test_spec_defaults_are_per_instance():
    """
        List defaults on PythonEnvSpec are not shared between instances.
    """
    first = PythonEnvSpec(path="/a")
    second = PythonEnvSpec(path="/b")
    first.packages.append("x")
    testbase.assert_equal(second.packages, [])
    testbase.assert_equal(first.recreate, False)
    testbase.assert_equal(first.upgrade_packages, False)
    return


def test_query_error_redacts_command_and_carries_fields():
    """
        PythonEnvQueryError stores the redacted argv, exit code and stderr.
    """
    error = PythonEnvQueryError(
        command=["pip", "--index-url", "https://u:p@h/simple", "list"],
        exit_code=2,
        stderr="bad",
    )
    testbase.assert_equal(error.command, ["pip", "--index-url", "https://***@h/simple", "list"])
    testbase.assert_equal(error.exit_code, 2)
    testbase.assert_equal(error.stderr, "bad")
    testbase.assert_true("EXIT_CODE: 2" in str(error))
    return


def test_abstract_base_cannot_be_instantiated():
    """
        The base requires _build_layout.
    """
    raised = False
    try:
        PythonEnvironmentManagementBase(runner=_MockCommandRunner())
    except TypeError:
        raised = True
    testbase.assert_true(raised)
    return


# ----------------------------------------------------------------------
# create_environment
# ----------------------------------------------------------------------


def test_create_environment_dispatches_venv_then_pip_upgrade():
    """
        A missing environment is created with python3 -m venv and pip is
        upgraded afterwards by default.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(result.path, _VENV)
    writes = _write_calls(runner)
    testbase.assert_equal(len(writes), 2)
    testbase.assert_equal(writes[0]["args"], ["python3", "-m", "venv", _VENV])
    testbase.assert_equal(writes[0]["elevated"], True)
    testbase.assert_equal(writes[1]["args"], _pip_argv("install", "--upgrade", "pip"))
    testbase.assert_equal(writes[1]["elevated"], True)
    return


def test_create_environment_without_pip_upgrade():
    """
        upgrade_pip=False on the config suppresses the pip upgrade.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    manager = _make_manager(runner, PythonEnvManagerConfig(upgrade_pip=False))

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    writes = _write_calls(runner)
    testbase.assert_equal(len(writes), 1)
    testbase.assert_equal(writes[0]["args"], ["python3", "-m", "venv", _VENV])
    return


def test_create_environment_skipped_when_valid_environment_exists():
    """
        An existing, working environment is not recreated.
    """
    runner = _MockCommandRunner()
    _seed_env_valid(runner)
    manager = _make_manager(runner)

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SKIPPED)
    testbase.assert_equal(result.message, "environment already exists")
    testbase.assert_equal(_write_calls(runner), [])
    return


def test_create_environment_recreates_when_directory_exists_but_python_broken():
    """
        A directory whose interpreter does not run is treated as absent.
    """
    runner = _MockCommandRunner()
    runner.results[("test", "-d", _VENV)] = _ok()
    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _fail(exit_code=127)
    manager = _make_manager(runner, PythonEnvManagerConfig(upgrade_pip=False))

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(_write_calls(runner)[0]["args"], ["python3", "-m", "venv", _VENV])
    return


def test_create_environment_dry_run_records_command_without_probing():
    """
        Dry-run returns DRY_RUN with the argv and never calls the runner.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, ["python3", "-m", "venv", _VENV])
    testbase.assert_equal(runner.calls, [])
    return


def test_create_environment_honours_interpreter_precedence():
    """
        Explicit argument beats config which beats layout default.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    config = PythonEnvManagerConfig(base_interpreter=["/usr/bin/python3.11"], upgrade_pip=False)
    manager = _make_manager(runner, config)

    manager.create_environment(path=_VENV)
    manager.create_environment(path=_VENV, interpreter=["/opt/py/bin/python3.12"])

    writes = _write_calls(runner)
    testbase.assert_equal(writes[0]["args"][0], "/usr/bin/python3.11")
    testbase.assert_equal(writes[1]["args"][0], "/opt/py/bin/python3.12")
    return


def test_create_environment_system_site_packages_flag():
    """
        --system-site-packages is emitted from config or per-call override.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    manager = _make_manager(runner, PythonEnvManagerConfig(system_site_packages=True, upgrade_pip=False))

    manager.create_environment(path=_VENV)
    manager.create_environment(path=_VENV, system_site_packages=False)

    writes = _write_calls(runner)
    testbase.assert_equal(writes[0]["args"], ["python3", "-m", "venv", "--system-site-packages", _VENV])
    testbase.assert_equal(writes[1]["args"], ["python3", "-m", "venv", _VENV])
    return


def test_create_environment_failed_venv_returns_failed_without_pip_upgrade():
    """
        A failing venv command surfaces as FAILED and pip is not touched.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    runner.results[("python3", "-m", "venv", _VENV)] = _fail(stderr="ensurepip missing")
    manager = _make_manager(runner)

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.FAILED)
    testbase.assert_equal(result.stderr, "ensurepip missing")
    testbase.assert_equal(len(_write_calls(runner)), 1)
    return


def test_create_environment_failed_pip_upgrade_reports_message():
    """
        When creation succeeds but the pip upgrade fails the result is
        FAILED with an explanatory message.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    runner.results[tuple(_pip_argv("install", "--upgrade", "pip"))] = _fail(stderr="no network")
    manager = _make_manager(runner)

    result = manager.create_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.FAILED)
    testbase.assert_equal(result.message, "environment created but the pip upgrade failed")
    testbase.assert_equal(result.command, _pip_argv("install", "--upgrade", "pip"))
    return


# ----------------------------------------------------------------------
# remove_environment
# ----------------------------------------------------------------------


def test_remove_environment_dispatches_rm_when_present():
    """
        rm -rf is dispatched with elevation when the directory exists.
    """
    runner = _MockCommandRunner()
    _seed_env_valid(runner)
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    result = manager.remove_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    writes = _write_calls(runner)
    testbase.assert_equal(writes, [{"args": ["rm", "-rf", _VENV], "elevated": True, "stdin": None, "env": None}])
    return


def test_remove_environment_skipped_when_absent():
    """
        Nothing is removed when the directory does not exist.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    manager = _make_manager(runner)

    result = manager.remove_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SKIPPED)
    testbase.assert_equal(result.message, "environment does not exist")
    testbase.assert_equal(_write_calls(runner), [])
    return


def test_remove_environment_dry_run():
    """
        Dry-run short-circuits before the existence probe.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.remove_environment(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, ["rm", "-rf", _VENV])
    testbase.assert_equal(runner.calls, [])
    return


# ----------------------------------------------------------------------
# install_packages
# ----------------------------------------------------------------------


def test_install_packages_builds_pip_install_argv_with_index_and_options():
    """
        Index URLs, trusted hosts and pip_options land on the argv in
        the documented order.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [])
    config = PythonEnvManagerConfig(
        index_url="https://pypi.example/simple",
        extra_index_urls=["https://extra.example/simple"],
        trusted_hosts=["extra.example"],
        pip_options=["--no-cache-dir"],
        elevated=True,
    )
    manager = _make_manager(runner, config)

    result = manager.install_packages(path=_VENV, packages=["requests==2.32.3", "rich"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(result.packages, ["requests==2.32.3", "rich"])
    writes = _write_calls(runner)
    testbase.assert_equal(len(writes), 1)
    testbase.assert_equal(
        writes[0]["args"],
        _pip_argv(
            "install",
            "--index-url", "https://pypi.example/simple",
            "--extra-index-url", "https://extra.example/simple",
            "--trusted-host", "extra.example",
            "--no-cache-dir",
            "requests==2.32.3", "rich",
        ),
    )
    testbase.assert_equal(writes[0]["elevated"], True)
    return


def test_install_packages_skipped_when_all_satisfied():
    """
        Exact pins that match and bare names that are present skip.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [("requests", "2.32.3"), ("Rich", "13.7.1")])
    manager = _make_manager(runner)

    result = manager.install_packages(path=_VENV, packages=["requests==2.32.3", "rich"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.SKIPPED)
    testbase.assert_equal(result.message, "every requested package is already installed")
    testbase.assert_equal(_write_calls(runner), [])
    return


def test_install_packages_dispatches_when_pin_differs():
    """
        A pin that does not match the installed version dispatches.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [("requests", "2.31.0")])
    manager = _make_manager(runner)

    result = manager.install_packages(path=_VENV, packages=["requests==2.32.3"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(len(_write_calls(runner)), 1)
    return


def test_install_packages_upgrade_bypasses_probe_and_adds_flag():
    """
        upgrade=True never probes pip list and passes --upgrade.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner)

    result = manager.install_packages(path=_VENV, packages=["rich"], upgrade=True)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(len(runner.calls), 1)
    testbase.assert_equal(runner.calls[0]["args"], _pip_argv("install", "--upgrade", "rich"))
    return


def test_install_packages_rejects_empty_list():
    """
        An empty package list raises ValueError before any runner call.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner)

    raised = False
    try:
        manager.install_packages(path=_VENV, packages=[])
    except ValueError:
        raised = True

    testbase.assert_true(raised)
    testbase.assert_equal(runner.calls, [])
    return


def test_install_packages_dry_run():
    """
        Dry-run returns DRY_RUN with the argv and no runner calls.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.install_packages(path=_VENV, packages=["rich"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, _pip_argv("install", "rich"))
    testbase.assert_equal(runner.calls, [])
    return


def test_install_packages_redacts_index_credentials_on_result():
    """
        Credentials in an index URL never reach the recorded command,
        while the runner receives the real URL.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [])
    config = PythonEnvManagerConfig(index_url="https://svc:s3cret@pypi.example/simple")
    manager = _make_manager(runner, config)

    result = manager.install_packages(path=_VENV, packages=["rich"])

    testbase.assert_equal(
        result.command,
        _pip_argv("install", "--index-url", "https://***@pypi.example/simple", "rich"),
    )
    testbase.assert_equal(
        _write_calls(runner)[0]["args"],
        _pip_argv("install", "--index-url", "https://svc:s3cret@pypi.example/simple", "rich"),
    )
    return


def test_install_packages_failed_maps_exit_code():
    """
        A non-zero pip exit maps to FAILED with the captured streams.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [])
    runner.results[tuple(_pip_argv("install", "nope"))] = _fail(stderr="No matching distribution")
    manager = _make_manager(runner)

    result = manager.install_packages(path=_VENV, packages=["nope"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.FAILED)
    testbase.assert_equal(result.exit_code, 1)
    testbase.assert_equal(result.stderr, "No matching distribution")
    return


# ----------------------------------------------------------------------
# install_requirements
# ----------------------------------------------------------------------


def test_install_requirements_builds_argv_and_never_probes():
    """
        -r / -c options are emitted and pip list is not consulted.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner)

    result = manager.install_requirements(
        path=_VENV,
        requirements_files=["/srv/app/requirements.txt", "/srv/app/dev.txt"],
        constraints_files=["/srv/app/constraints.txt"],
    )

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(result.packages, ["/srv/app/requirements.txt", "/srv/app/dev.txt"])
    testbase.assert_equal(len(runner.calls), 1)
    testbase.assert_equal(
        runner.calls[0]["args"],
        _pip_argv(
            "install",
            "-r", "/srv/app/requirements.txt",
            "-r", "/srv/app/dev.txt",
            "-c", "/srv/app/constraints.txt",
        ),
    )
    return


def test_install_requirements_upgrade_flag_and_dry_run():
    """
        --upgrade is emitted and dry-run short-circuits.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.install_requirements(
        path=_VENV, requirements_files=["/r.txt"], upgrade=True,
    )

    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, _pip_argv("install", "--upgrade", "-r", "/r.txt"))
    testbase.assert_equal(runner.calls, [])
    return


def test_install_requirements_rejects_empty_list():
    """
        An empty requirements list raises ValueError.
    """
    manager = _make_manager(_MockCommandRunner())
    raised = False
    try:
        manager.install_requirements(path=_VENV, requirements_files=[])
    except ValueError:
        raised = True
    testbase.assert_true(raised)
    return


# ----------------------------------------------------------------------
# uninstall_packages
# ----------------------------------------------------------------------


def test_uninstall_packages_dispatches_when_any_present():
    """
        pip uninstall -y runs with the full name list when at least one
        name is installed.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [("requests", "2.32.3")])
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    result = manager.uninstall_packages(path=_VENV, names=["requests", "rich"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    writes = _write_calls(runner)
    testbase.assert_equal(writes[0]["args"], _pip_argv("uninstall", "-y", "requests", "rich"))
    testbase.assert_equal(writes[0]["elevated"], True)
    return


def test_uninstall_packages_skipped_when_none_present():
    """
        No uninstall runs when none of the names are installed.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [("other", "1.0")])
    manager = _make_manager(runner)

    result = manager.uninstall_packages(path=_VENV, names=["requests"])

    testbase.assert_equal(result.status, PythonEnvActionStatus.SKIPPED)
    testbase.assert_equal(result.message, "none of the requested packages are installed")
    testbase.assert_equal(_write_calls(runner), [])
    return


def test_uninstall_packages_dry_run_and_empty_guard():
    """
        Dry-run records the argv; an empty list raises ValueError.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.uninstall_packages(path=_VENV, names=["rich"])
    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, _pip_argv("uninstall", "-y", "rich"))

    raised = False
    try:
        manager.uninstall_packages(path=_VENV, names=[])
    except ValueError:
        raised = True
    testbase.assert_true(raised)
    return


# ----------------------------------------------------------------------
# upgrade_pip
# ----------------------------------------------------------------------


def test_upgrade_pip_argv_includes_index_options_and_never_skips():
    """
        pip install --upgrade pip is dispatched every time.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(index_url="https://i/simple"))

    manager.upgrade_pip(path=_VENV)
    result = manager.upgrade_pip(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(result.packages, ["pip"])
    testbase.assert_equal(len(runner.calls), 2)
    testbase.assert_equal(
        runner.calls[1]["args"],
        _pip_argv("install", "--upgrade", "--index-url", "https://i/simple", "pip"),
    )
    return


# ----------------------------------------------------------------------
# deploy
# ----------------------------------------------------------------------


def test_deploy_runs_steps_in_order_for_fresh_environment():
    """
        recreate → create → upgrade pip → requirements → packages.
    """
    runner = _MockCommandRunner()
    # Directory exists (so recreate removes it) but python is missing
    # afterwards; the mock is static, so seed "exists" for the remove
    # probe and a broken interpreter so create proceeds.
    runner.results[("test", "-d", _VENV)] = _ok()
    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _fail(exit_code=127)
    _seed_installed(runner, [])
    manager = _make_manager(runner)

    spec = PythonEnvSpec(
        path=_VENV,
        packages=["rich>=13"],
        requirements_files=["/r.txt"],
        constraints_files=["/c.txt"],
        recreate=True,
    )
    result = manager.deploy(spec=spec)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(result.path, _VENV)
    testbase.assert_equal(len(result.steps), 5)
    writes = [c["args"] for c in _write_calls(runner)]
    testbase.assert_equal(
        writes,
        [
            ["rm", "-rf", _VENV],
            ["python3", "-m", "venv", _VENV],
            _pip_argv("install", "--upgrade", "pip"),
            _pip_argv("install", "-r", "/r.txt", "-c", "/c.txt"),
            _pip_argv("install", "rich>=13"),
        ],
    )
    return


def test_deploy_stops_at_first_failure():
    """
        A failed create step aborts the remaining steps and the aggregate
        is FAILED with a message.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    runner.results[("python3", "-m", "venv", _VENV)] = _fail(stderr="ensurepip missing")
    manager = _make_manager(runner)

    result = manager.deploy(spec=PythonEnvSpec(path=_VENV, packages=["rich"]))

    testbase.assert_equal(result.status, PythonEnvActionStatus.FAILED)
    testbase.assert_equal(len(result.steps), 1)
    testbase.assert_true(result.message.startswith("python3 -m venv"))
    testbase.assert_equal(len(_write_calls(runner)), 1)
    return


def test_deploy_all_skipped_yields_skipped():
    """
        An already-converged environment with upgrade_pip off yields
        SKIPPED overall.
    """
    runner = _MockCommandRunner()
    _seed_env_valid(runner)
    _seed_installed(runner, [("rich", "13.7.1")])
    manager = _make_manager(runner, PythonEnvManagerConfig(upgrade_pip=False))

    result = manager.deploy(spec=PythonEnvSpec(path=_VENV, packages=["rich"]))

    testbase.assert_equal(result.status, PythonEnvActionStatus.SKIPPED)
    testbase.assert_equal([s.status for s in result.steps], [PythonEnvActionStatus.SKIPPED] * 2)
    testbase.assert_equal(_write_calls(runner), [])
    return


def test_deploy_spec_overrides_win_over_config():
    """
        Per-spec interpreter, system_site_packages and upgrade_pip
        override the config.
    """
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    config = PythonEnvManagerConfig(base_interpreter=["python3.11"], upgrade_pip=True)
    manager = _make_manager(runner, config)

    spec = PythonEnvSpec(
        path=_VENV, interpreter=["python3.12"], system_site_packages=True, upgrade_pip=False,
    )
    result = manager.deploy(spec=spec)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    writes = [c["args"] for c in _write_calls(runner)]
    testbase.assert_equal(writes, [["python3.12", "-m", "venv", "--system-site-packages", _VENV]])
    return


def test_deploy_dry_run_aggregates_to_dry_run():
    """
        In dry-run every step is DRY_RUN and so is the aggregate.
    """
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.deploy(spec=PythonEnvSpec(path=_VENV, packages=["rich"]))

    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal([s.status for s in result.steps], [PythonEnvActionStatus.DRY_RUN] * 3)
    testbase.assert_equal(runner.calls, [])
    return


# ----------------------------------------------------------------------
# Read verbs
# ----------------------------------------------------------------------


def test_environment_exists_reflects_probe_exit_code():
    """
        environment_exists is True on exit 0 and False otherwise, never
        elevating.
    """
    runner = _MockCommandRunner()
    runner.results[("test", "-d", _VENV)] = _ok()
    runner.results[("test", "-d", "/nope")] = _fail(exit_code=1)
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    testbase.assert_equal(manager.environment_exists(path=_VENV), True)
    testbase.assert_equal(manager.environment_exists(path="/nope"), False)
    testbase.assert_equal([c["elevated"] for c in runner.calls], [False, False])
    return


def test_get_python_version_parses_and_returns_none_on_failure():
    """
        The interpreter version is stripped; failures yield None.
    """
    runner = _MockCommandRunner()
    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _ok(stdout="3.12.3\n")
    manager = _make_manager(runner)
    testbase.assert_equal(manager.get_python_version(path=_VENV), "3.12.3")

    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _fail(exit_code=127)
    testbase.assert_equal(manager.get_python_version(path=_VENV), None)

    runner.results[(_VENV_PYTHON, "-c", _VERSION_SNIPPET)] = _ok(stdout="   \n")
    testbase.assert_equal(manager.get_python_version(path=_VENV), None)
    return


def test_list_installed_parses_pip_list_json():
    """
        pip list JSON becomes PythonPackageInfo rows in order.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [("pip", "24.0"), ("Requests", "2.32.3")])
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    rows = manager.list_installed(path=_VENV)

    testbase.assert_equal(rows, [PythonPackageInfo("pip", "24.0"), PythonPackageInfo("Requests", "2.32.3")])
    testbase.assert_equal(runner.calls[0]["elevated"], False)
    return


def test_list_installed_raises_on_non_zero_exit():
    """
        A failing pip list raises PythonEnvQueryError.
    """
    runner = _MockCommandRunner()
    runner.results[tuple(_pip_argv("list", "--format", "json"))] = _fail(stderr="No module named pip")
    manager = _make_manager(runner)

    raised: Optional[PythonEnvQueryError] = None
    try:
        manager.list_installed(path=_VENV)
    except PythonEnvQueryError as err:
        raised = err

    testbase.assert_true(raised is not None)
    testbase.assert_equal(raised.stderr, "No module named pip")
    return


def test_list_installed_raises_on_unparsable_json_and_tolerates_empty():
    """
        Garbage output raises; empty output is an empty list.
    """
    runner = _MockCommandRunner()
    key = tuple(_pip_argv("list", "--format", "json"))
    manager = _make_manager(runner)

    runner.results[key] = _ok(stdout="not json")
    raised = False
    try:
        manager.list_installed(path=_VENV)
    except PythonEnvQueryError:
        raised = True
    testbase.assert_true(raised)

    runner.results[key] = _ok(stdout="")
    testbase.assert_equal(manager.list_installed(path=_VENV), [])
    return


def test_get_package_info_normalises_names():
    """
        Lookup is PEP 503 normalised in both directions.
    """
    runner = _MockCommandRunner()
    _seed_installed(runner, [("typing_extensions", "4.12.2")])
    manager = _make_manager(runner)

    info = manager.get_package_info(path=_VENV, name="Typing-Extensions")
    testbase.assert_equal(info, PythonPackageInfo("typing_extensions", "4.12.2"))
    testbase.assert_equal(manager.get_package_info(path=_VENV, name="missing"), None)
    testbase.assert_equal(manager.is_package_installed(path=_VENV, name="typing.extensions"), True)
    return


def test_freeze_returns_stripped_lines_and_raises_on_failure():
    """
        pip freeze lines are returned without blanks; failure raises.
    """
    runner = _MockCommandRunner()
    key = tuple(_pip_argv("freeze"))
    runner.results[key] = _ok(stdout="requests==2.32.3\n\nrich==13.7.1\n")
    manager = _make_manager(runner)

    testbase.assert_equal(manager.freeze(path=_VENV), ["requests==2.32.3", "rich==13.7.1"])

    runner.results[key] = _fail()
    raised = False
    try:
        manager.freeze(path=_VENV)
    except PythonEnvQueryError:
        raised = True
    testbase.assert_true(raised)
    return


def test_get_environment_info_snapshot_and_none_when_missing():
    """
        A snapshot carries path, interpreter, version and packages; a
        missing directory yields None.
    """
    runner = _MockCommandRunner()
    _seed_env_valid(runner, version="3.11.9")
    _seed_installed(runner, [("pip", "24.0")])
    manager = _make_manager(runner)

    info = manager.get_environment_info(path=_VENV)
    testbase.assert_equal(
        info,
        PythonEnvInfo(
            path=_VENV,
            python_executable=_VENV_PYTHON,
            python_version="3.11.9",
            packages=[PythonPackageInfo("pip", "24.0")],
        ),
    )

    runner.results[("test", "-d", _VENV)] = _fail(exit_code=1)
    testbase.assert_equal(manager.get_environment_info(path=_VENV), None)
    return


# ----------------------------------------------------------------------
# Requirement probe
# ----------------------------------------------------------------------


def _satisfied(specifier: str, installed: list) -> bool:
    manager = _make_manager(_MockCommandRunner())
    rows = [PythonPackageInfo(name, version) for name, version in installed]
    rtnval = manager._requirement_satisfied(specifier=specifier, installed=rows)
    return rtnval


def test_requirement_probe_bare_name_and_extras():
    """
        A bare name (with or without extras) is satisfied by presence.
    """
    testbase.assert_equal(_satisfied("requests", [("requests", "2.32.3")]), True)
    testbase.assert_equal(_satisfied("requests[socks]", [("requests", "2.32.3")]), True)
    testbase.assert_equal(_satisfied("requests", []), False)
    return


def test_requirement_probe_exact_and_wildcard_pins():
    """
        == needs an exact match; ==X.Y.* needs a prefix match.
    """
    testbase.assert_equal(_satisfied("requests==2.32.3", [("requests", "2.32.3")]), True)
    testbase.assert_equal(_satisfied("requests==2.32.3", [("requests", "2.32.4")]), False)
    testbase.assert_equal(_satisfied("requests==2.32.*", [("requests", "2.32.9")]), True)
    testbase.assert_equal(_satisfied("requests==2.32.*", [("requests", "2.33.0")]), False)
    testbase.assert_equal(_satisfied("requests!=2.32.3", [("requests", "2.32.4")]), True)
    return


def test_requirement_probe_ordering_and_compatible_release():
    """
        Ordering operators compare numerically; ~= honours the prefix.
    """
    testbase.assert_equal(_satisfied("rich>=13", [("rich", "13.7.1")]), True)
    testbase.assert_equal(_satisfied("rich>=14", [("rich", "13.7.1")]), False)
    testbase.assert_equal(_satisfied("rich>=13,<14", [("rich", "13.7.1")]), True)
    testbase.assert_equal(_satisfied("rich<13.7", [("rich", "13.7.1")]), False)
    testbase.assert_equal(_satisfied("rich~=13.6", [("rich", "13.7.1")]), True)
    testbase.assert_equal(_satisfied("rich~=13.7.2", [("rich", "13.7.1")]), False)
    testbase.assert_equal(_satisfied("rich>=1.2", [("rich", "1.2.0")]), True)
    return


def test_requirement_probe_defers_to_pip_when_uncertain():
    """
        Pre-release versions, URLs, editable and path requirements are
        never reported as satisfied.
    """
    testbase.assert_equal(_satisfied("rich>=13", [("rich", "13.7.1rc1")]), False)
    testbase.assert_equal(_satisfied("pkg @ https://x/pkg.whl", [("pkg", "1.0")]), False)
    testbase.assert_equal(_satisfied("-e ./local", []), False)
    testbase.assert_equal(_satisfied("./dist/pkg.whl", [("pkg", "1.0")]), False)
    testbase.assert_equal(_satisfied("", []), False)
    return


def test_requirement_probe_ignores_environment_markers():
    """
        Markers are dropped for the probe.
    """
    testbase.assert_equal(
        _satisfied('tomli>=2; python_version < "3.11"', [("tomli", "2.0.1")]), True,
    )
    return


# ----------------------------------------------------------------------
# Elevation and Windows extension
# ----------------------------------------------------------------------


def test_reads_never_elevate_even_when_configured():
    """
        Probes and read verbs pass elevated=False.
    """
    runner = _MockCommandRunner()
    _seed_env_valid(runner)
    _seed_installed(runner, [])
    runner.results[tuple(_pip_argv("freeze"))] = _ok()
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    manager.environment_exists(path=_VENV)
    manager.is_valid_environment(path=_VENV)
    manager.list_installed(path=_VENV)
    manager.freeze(path=_VENV)
    manager.get_environment_info(path=_VENV)

    testbase.assert_true(len(runner.calls) > 0)
    testbase.assert_equal(all(c["elevated"] is False for c in runner.calls), True)
    return


def test_elevation_blocked_extension_surfaces_as_detail_token():
    """
        A runner that returns elevation_blocked=True yields FAILED with
        the stable detail token.
    """
    runner = _MockCommandRunner()
    runner.default_result = _ElevationBlockedRunResult(
        exit_code=-1, stdout="", stderr="not elevated", elevation_blocked=True,
    )
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    result = manager.upgrade_pip(path=_VENV)

    testbase.assert_equal(result.status, PythonEnvActionStatus.FAILED)
    testbase.assert_equal(result.detail, DETAIL_ELEVATION_BLOCKED)
    return


# ----------------------------------------------------------------------
# Ownership
#
# Creating an environment with elevated=True yields a root-owned tree the
# service account cannot write to, so deploy hands it over as its last step.
# ----------------------------------------------------------------------


_STAT_ARGV = ("stat", "-c", "%U:%G", _VENV)
_CHOWN_ARGV = ["chown", "-R", "agent", _VENV]


def _seed_owner(runner: _MockCommandRunner, owner: str) -> None:
    runner.results[_STAT_ARGV] = _ok(stdout=owner + "\n")
    return


def test_posix_layout_owner_argv():
    layout = PosixPythonEnvironmentLayout()
    testbase.assert_equal(layout.build_query_owner_argv(path=_VENV), list(_STAT_ARGV))
    testbase.assert_equal(layout.build_set_owner_argv(path=_VENV, owner="agent"), _CHOWN_ARGV)
    testbase.assert_equal(layout.supports_owner_group, True)
    return


def test_bsd_layout_only_differs_in_the_owner_probe():
    # macOS ships BSD stat; everything else matches the POSIX layout.
    posix = PosixPythonEnvironmentLayout()
    bsd = BsdPythonEnvironmentLayout()
    testbase.assert_equal(bsd.build_query_owner_argv(path=_VENV),
                          ["stat", "-f", "%Su:%Sg", _VENV])
    testbase.assert_equal(bsd.build_set_owner_argv(path=_VENV, owner="agent"),
                          posix.build_set_owner_argv(path=_VENV, owner="agent"))
    testbase.assert_equal(bsd.venv_python_path(path=_VENV), posix.venv_python_path(path=_VENV))
    testbase.assert_equal(bsd.build_remove_tree_argv(path=_VENV),
                          posix.build_remove_tree_argv(path=_VENV))
    return


def test_windows_layout_owner_argv_and_no_group():
    layout = WindowsPythonEnvironmentLayout()
    path = r"C:\venvs\app"
    testbase.assert_equal(layout.supports_owner_group, False)
    testbase.assert_equal(
        layout.build_set_owner_argv(path=path, owner="svc"),
        ["icacls", path, "/setowner", "svc", "/T", "/C"],
    )
    query = layout.build_query_owner_argv(path=path)
    testbase.assert_equal(query[4], "(Get-Acl -LiteralPath 'C:\\venvs\\app').Owner")
    # Get-Acl reports DOMAIN\user; a caller may supply either form.
    testbase.assert_equal(layout.normalise_owner("CORP\\Svc-Agent"), "svc-agent")
    testbase.assert_equal(layout.normalise_owner("svc-agent"), "svc-agent")
    return


def test_posix_normalise_owner_drops_the_group_half():
    # `chown -R agent` leaves the group alone, so a probe reporting
    # agent:staff must still compare equal to the requested "agent".
    layout = PosixPythonEnvironmentLayout()
    testbase.assert_equal(layout.normalise_owner("agent:staff"), "agent")
    testbase.assert_equal(layout.normalise_owner(" agent \n"), "agent")
    return


def test_get_owner_reads_and_normalises():
    runner = _MockCommandRunner()
    _seed_owner(runner, "agent:staff")
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))
    testbase.assert_equal(manager.get_owner(path=_VENV), "agent")
    testbase.assert_equal(runner.calls[0]["elevated"], False)
    return


def test_get_owner_returns_none_when_the_probe_fails():
    runner = _MockCommandRunner()
    runner.results[_STAT_ARGV] = _fail(exit_code=1)
    manager = _make_manager(runner)
    testbase.assert_equal(manager.get_owner(path=_VENV), None)

    runner.results[_STAT_ARGV] = _ok(stdout="   \n")
    testbase.assert_equal(manager.get_owner(path=_VENV), None)
    return


def test_set_owner_dispatches_chown_when_owner_differs():
    runner = _MockCommandRunner()
    _seed_owner(runner, "root:root")
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    result = manager.set_owner(path=_VENV, owner="agent")

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    writes = _write_calls(runner)
    testbase.assert_equal([c["args"] for c in writes], [_CHOWN_ARGV])
    testbase.assert_equal(writes[0]["elevated"], True)
    return


def test_set_owner_skipped_when_already_owned():
    runner = _MockCommandRunner()
    _seed_owner(runner, "agent:staff")
    manager = _make_manager(runner)

    result = manager.set_owner(path=_VENV, owner="agent")

    testbase.assert_equal(result.status, PythonEnvActionStatus.SKIPPED)
    testbase.assert_equal(result.message, "environment is already owned by the requested owner")
    testbase.assert_equal(_write_calls(runner), [])
    return


def test_set_owner_dispatches_when_the_probe_cannot_answer():
    # An unreadable owner must not be treated as "already correct".
    runner = _MockCommandRunner()
    runner.results[_STAT_ARGV] = _fail(exit_code=1)
    manager = _make_manager(runner)

    result = manager.set_owner(path=_VENV, owner="agent")

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    testbase.assert_equal(len(_write_calls(runner)), 1)
    return


def test_set_owner_dry_run_records_the_command():
    runner = _MockCommandRunner()
    manager = _make_manager(runner, PythonEnvManagerConfig(dry_run=True))

    result = manager.set_owner(path=_VENV, owner="agent")

    testbase.assert_equal(result.status, PythonEnvActionStatus.DRY_RUN)
    testbase.assert_equal(result.command, _CHOWN_ARGV)
    testbase.assert_equal(runner.calls, [])
    return


def test_set_owner_rejects_a_malformed_owner():
    runner = _MockCommandRunner()
    manager = _make_manager(runner)
    for bad in ("", "agent; rm -rf /", "-agent", "agent:staff:extra"):
        raised = False
        try:
            manager.set_owner(path=_VENV, owner=bad)
        except ValueError:
            raised = True
        testbase.assert_true(raised, bad)
    testbase.assert_equal(runner.calls, [])
    return


def test_set_owner_rejects_a_group_half_on_windows():
    class _WindowsManager(PythonEnvironmentManagementBase):
        def _build_layout(self) -> PythonEnvironmentLayout:
            return WindowsPythonEnvironmentLayout()

    manager = _WindowsManager(runner=_MockCommandRunner())
    raised = False
    try:
        manager.set_owner(path=r"C:\venvs\app", owner="svc:admins")
    except ValueError:
        raised = True
    testbase.assert_true(raised)
    # The bare account name is accepted.
    manager._require_owner(owner="svc")
    return


def test_deploy_hands_ownership_over_last():
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    _seed_installed(runner, [])
    _seed_owner(runner, "root:root")
    manager = _make_manager(runner, PythonEnvManagerConfig(elevated=True))

    spec = PythonEnvSpec(path=_VENV, packages=["rich"], owner="agent")
    result = manager.deploy(spec=spec)

    testbase.assert_equal(result.status, PythonEnvActionStatus.SUCCESS)
    writes = [c["args"] for c in _write_calls(runner)]
    testbase.assert_equal(writes[-1], _CHOWN_ARGV)
    testbase.assert_equal(
        writes,
        [
            ["python3", "-m", "venv", _VENV],
            _pip_argv("install", "--upgrade", "pip"),
            _pip_argv("install", "rich"),
            _CHOWN_ARGV,
        ],
    )
    return


def test_deploy_without_an_owner_never_chowns():
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    _seed_installed(runner, [])
    manager = _make_manager(runner)

    manager.deploy(spec=PythonEnvSpec(path=_VENV, packages=["rich"]))

    for call in runner.calls:
        testbase.assert_true(call["args"][:1] != ["chown"])
    return


def test_deploy_stops_before_chown_when_an_install_fails():
    runner = _MockCommandRunner()
    _seed_env_missing(runner)
    _seed_installed(runner, [])
    _seed_owner(runner, "root:root")
    runner.results[tuple(_pip_argv("install", "rich"))] = _fail(stderr="no network")
    manager = _make_manager(runner)

    result = manager.deploy(spec=PythonEnvSpec(path=_VENV, packages=["rich"], owner="agent"))

    testbase.assert_equal(result.status, PythonEnvActionStatus.FAILED)
    for call in runner.calls:
        testbase.assert_true(call["args"][:1] != ["chown"])
    return
