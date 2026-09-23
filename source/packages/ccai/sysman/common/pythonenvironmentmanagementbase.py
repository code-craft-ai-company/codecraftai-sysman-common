"""
    Abstract feature-manager base for the python-environment-management
    contract.

    ``PythonEnvironmentManagementBase`` is the only place the contract's
    dataclasses, exceptions, verb signatures, and verb *behaviour* are
    defined.  Unlike most sysman features, the tools involved — the
    ``venv`` module and ``pip`` — are part of CPython itself and behave
    identically on every OS.  Only three things differ per OS:

        * where the interpreter lives inside the environment
          (``bin/python`` vs ``Scripts\\python.exe``),
        * how the base interpreter is launched (``python3`` vs ``py -3``),
        * which shell tools probe for / remove a directory.

    Those three concerns are delegated to a
    :class:`PythonEnvironmentLayout`; the per-OS subclasses
    (``UbuntuPythonEnvironmentManager``, ``RedHatPythonEnvironmentManager``,
    ``MacosPythonEnvironmentManager``, ``WindowsPythonEnvironmentManager``)
    only have to pick a layout and, optionally, add an OS-specific
    ``ensure_prerequisites`` verb that installs the interpreter through
    that OS's package manager.

    Every command — including the directory probes — is dispatched
    through the injected :class:`ICommandRunner`, so a manager works
    identically under local and SSH / WinRM execution and no direct
    ``subprocess`` or filesystem call lives in this module.

    Elevation policy:
        Write verbs honour ``config.elevated``.  Read verbs and the
        idempotency probes never elevate.  Note that creating an
        environment with ``elevated=True`` produces a root- /
        Administrator-owned tree; callers that want a user-owned
        environment should run an unelevated runner as that user.

    Credential safety:
        ``index_url`` / ``extra_index_urls`` may carry a private-index
        token in the URL userinfo.  Every recorded ``command`` passes
        through :func:`redact_command`, which scrubs URL userinfo, so a
        result object never carries the token into a log.

    See :doc:`/specs/contracts/python-environment-management/contract.md`
    for the cross-OS contract.
"""

import json
import os
import re

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ccai.interfaces.icommandrunner import ICommandRunner

from ccai.sysman.common.commandredaction import redact_command
from ccai.sysman.common.featurebase import (
    DETAIL_ELEVATION_BLOCKED,
    ActionStatus,
    BaseFeatureManager,
    FeatureActionResult,
    FeatureConfig,
)
from ccai.sysman.common.pythonenvironmentlayout import PythonEnvironmentLayout


# ----------------------------------------------------------------------
# Module-level constants
# ----------------------------------------------------------------------

_PIP_MODULE = "pip"
_VENV_MODULE = "venv"

# General ``pip`` options placed before the sub-command on every pip
# argv.  Both are real, long-standing pip flags: the first silences the
# "new version available" banner that would otherwise pollute stderr;
# the second makes pip fail instead of prompting when it needs input
# (for example a credential for a private index).
_PIP_GENERAL_OPTIONS = ["--disable-pip-version-check", "--no-input"]

_PIP_LIST_FORMAT_JSON = ["list", "--format", "json"]

_PYTHON_VERSION_SNIPPET = "import platform; print(platform.python_version())"

# PEP 508 requirement head: ``name[extras] <version clauses> ; markers``.
# Only the name and the version-clause list are used for the
# idempotency probe; extras and markers are carried through to pip
# untouched.
_REQUIREMENT_HEAD_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[^\]]*\])?"
    r"\s*(?P<rest>.*)$"
)
_VERSION_CLAUSE_PATTERN = re.compile(
    r"^\s*(?P<op>===|==|~=|!=|<=|>=|<|>)\s*(?P<version>[^\s,;]+)\s*$"
)
_NUMERIC_VERSION_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+)*$")

# Tokens that mark a requirement string as something the probe cannot
# reason about (URLs, editable installs, local paths).  Any such
# requirement is treated as "not satisfied" so pip makes the call.
_UNPROBEABLE_MARKERS = ("@", "://", "/", "\\")

_MESSAGE_ENV_ALREADY_EXISTS = "environment already exists"
_MESSAGE_ENV_NOT_FOUND = "environment does not exist"
_MESSAGE_PACKAGES_SATISFIED = "every requested package is already installed"
_MESSAGE_PACKAGES_NOT_INSTALLED = "none of the requested packages are installed"
_MESSAGE_OWNER_ALREADY_SET = "environment is already owned by the requested owner"

# ``user`` or ``user:group``.  The value reaches the runner as its own argv
# token, never a shell word, so this is a fail-fast readability guard rather
# than an injection defence.
_OWNER_PATTERN = re.compile(
    r"\A[A-Za-z_][A-Za-z0-9_.\\-]*\$?(:[A-Za-z_][A-Za-z0-9_.\\-]*\$?)?\Z"
)
_MESSAGE_PIP_UPGRADE_FAILED = "environment created but the pip upgrade failed"


PythonEnvActionStatus = ActionStatus


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------


@dataclass
class PythonEnvManagerConfig(FeatureConfig):
    """
        Configuration for a python-environment manager.  Inherits
        ``dry_run`` and ``elevated`` from :class:`FeatureConfig`.

        Per-OS subclasses MAY extend this dataclass with OS-specific
        fields but MUST preserve every field below with the
        contract-mandated defaults.

        :param base_interpreter: Argv prefix for the interpreter used to
                                 create new environments, e.g.
                                 ``["/usr/bin/python3.12"]`` or
                                 ``["py", "-3.12"]``.  ``None`` (the
                                 default) uses the layout's OS default.
        :param index_url: Value forwarded as ``--index-url`` on every
                          ``pip install``; ``None`` leaves pip's default.
        :param extra_index_urls: Values forwarded as repeated
                                 ``--extra-index-url`` options.
        :param trusted_hosts: Values forwarded as repeated
                              ``--trusted-host`` options.
        :param pip_options: Additional tokens appended to every ``pip
                            install`` argv (for example
                            ``["--no-cache-dir"]``).
        :param upgrade_pip: When True (the default), ``create_environment``
                            upgrades ``pip`` inside the new environment
                            immediately after creation.
        :param system_site_packages: When True, new environments are
                                     created with
                                     ``--system-site-packages``.
    """
    base_interpreter: Optional[List[str]] = None
    index_url: Optional[str] = None
    extra_index_urls: Optional[List[str]] = None
    trusted_hosts: Optional[List[str]] = None
    pip_options: Optional[List[str]] = None
    upgrade_pip: bool = True
    system_site_packages: bool = False


# ----------------------------------------------------------------------
# Results and models
# ----------------------------------------------------------------------


@dataclass
class PythonEnvActionResult(FeatureActionResult):
    """
        Result of a python-environment write operation.

        :param path: The environment root targeted.
        :param packages: The requirement specifiers targeted, when the
                         verb takes any.
        :param message: Optional human-readable detail for ``SKIPPED`` or
                        ``FAILED`` outcomes.
    """
    path: Optional[str] = None
    packages: Optional[List[str]] = None
    message: Optional[str] = None


@dataclass
class PythonPackageInfo:
    """
        One installed distribution inside an environment, as reported by
        ``pip list --format json``.

        :param name: Distribution name exactly as pip reports it.
        :param version: Installed version string.
    """
    name: str
    version: str


@dataclass
class PythonEnvInfo:
    """
        Snapshot of an existing environment.

        :param path: The environment root.
        :param python_executable: The interpreter path inside the
                                  environment.
        :param python_version: ``platform.python_version()`` of the
                               environment interpreter, or ``None`` when
                               the probe failed.
        :param packages: Every installed distribution.
    """
    path: str
    python_executable: str
    python_version: Optional[str] = None
    packages: List[PythonPackageInfo] = field(default_factory=list)


@dataclass
class PythonEnvSpec:
    """
        Declarative description of an environment to deploy.  Consumed
        by :meth:`PythonEnvironmentManagementBase.deploy`.

        :param path: The environment root.
        :param packages: PEP 508 requirement specifiers to install.
        :param requirements_files: ``-r`` files to install from (paths on
                                   the target host).
        :param constraints_files: ``-c`` files applied to the
                                  requirements-file install.
        :param interpreter: Per-spec override of the base interpreter
                            argv; ``None`` defers to the config.
        :param system_site_packages: Per-spec override; ``None`` defers
                                     to the config.
        :param upgrade_pip: Per-spec override; ``None`` defers to the
                            config.
        :param upgrade_packages: When True, ``packages`` are installed
                                 with ``--upgrade`` and the
                                 already-installed probe is skipped.
        :param recreate: When True, an existing environment at ``path``
                         is removed before creation.
        :param owner: When set, the finished tree is handed to this owner
                      (``user`` or ``user:group`` on POSIX; a bare account
                      name on Windows).  Applied last, after every install,
                      so files pip created are re-owned too.
    """
    path: str
    packages: List[str] = field(default_factory=list)
    requirements_files: List[str] = field(default_factory=list)
    constraints_files: List[str] = field(default_factory=list)
    interpreter: Optional[List[str]] = None
    system_site_packages: Optional[bool] = None
    upgrade_pip: Optional[bool] = None
    upgrade_packages: bool = False
    recreate: bool = False
    owner: Optional[str] = None


@dataclass
class PythonEnvDeployResult:
    """
        Aggregate result of :meth:`PythonEnvironmentManagementBase.deploy`.

        :param status: ``FAILED`` when any step failed (later steps are
                       not attempted); ``DRY_RUN`` when the manager is in
                       dry-run mode; ``SKIPPED`` when every step was
                       skipped; ``SUCCESS`` otherwise.
        :param path: The environment root.
        :param steps: Every step result in execution order.
        :param message: Human-readable summary, populated on ``FAILED``.
    """
    status: PythonEnvActionStatus
    path: str
    steps: List[PythonEnvActionResult] = field(default_factory=list)
    message: Optional[str] = None


class PythonEnvQueryError(Exception):
    """
        Raised when a read verb fails for a reason other than the
        environment being absent.
    """

    def __init__(
        self,
        *,
        command: List[str],
        exit_code: Optional[int],
        stderr: str,
    ) -> None:
        """
            :param command: The argv that failed.
            :param exit_code: The runner's exit code.
            :param stderr: The runner's captured stderr.
        """
        self.command = redact_command(command=list(command))
        self.exit_code = exit_code
        self.stderr = stderr

        err_msg_lines = ["Python environment query command failed."]
        err_msg_lines.append("    COMMAND: {}".format(" ".join(self.command)))
        err_msg_lines.append("    EXIT_CODE: {}".format(exit_code))
        err_msg_lines.append("    STDERR: {}".format(stderr))
        err_msg = os.linesep.join(err_msg_lines)
        super().__init__(err_msg)
        return


# ----------------------------------------------------------------------
# Base manager
# ----------------------------------------------------------------------


class PythonEnvironmentManagementBase(BaseFeatureManager, ABC):
    """
        Abstract feature manager for the python-environment-management
        contract.

        Subclasses implement :meth:`_build_layout` to select the
        on-disk layout and default interpreter launcher for their OS.
        Every verb below is concrete and shared.
    """

    result_class = PythonEnvActionResult
    status_class = PythonEnvActionStatus
    feature_name: Optional[str] = "python-environment-management"

    def __init__(
        self,
        runner: ICommandRunner,
        config: Optional[PythonEnvManagerConfig] = None,
    ) -> None:
        """
            :param runner: Command runner injected by the maintenance
                           coordinator.  Every command goes through it.
            :param config: Manager configuration.  Defaults to the base
                           :class:`PythonEnvManagerConfig` when omitted.
        """
        if config is None:
            cfg = PythonEnvManagerConfig()
        else:
            cfg = config

        super().__init__(runner=runner, config=cfg)
        self._config: PythonEnvManagerConfig = cfg
        self._layout: PythonEnvironmentLayout = self._build_layout()
        return

    @abstractmethod
    def _build_layout(self) -> PythonEnvironmentLayout:
        """
            Construct the :class:`PythonEnvironmentLayout` for this OS.

            :returns: The layout strategy.
        """

    @property
    def layout(self) -> PythonEnvironmentLayout:
        """
            The active layout strategy.
        """
        return self._layout

    # ------------------------------------------------------------------
    # Write verbs
    # ------------------------------------------------------------------

    def create_environment(
        self,
        path: str,
        *,
        interpreter: Optional[List[str]] = None,
        system_site_packages: Optional[bool] = None,
        upgrade_pip: Optional[bool] = None,
    ) -> PythonEnvActionResult:
        """
            Create a virtual environment at ``path`` with
            ``<interpreter> -m venv``.

            Skipped when a valid environment already exists at ``path``.
            When ``upgrade_pip`` resolves to True and creation succeeds,
            ``pip`` inside the new environment is upgraded immediately;
            a failed upgrade is reported as ``FAILED`` with
            ``message`` set even though the directory now exists.

            :param path: The environment root.
            :param interpreter: Argv prefix override for the base
                                interpreter; ``None`` uses the config,
                                then the layout default.
            :param system_site_packages: Override for the config flag.
            :param upgrade_pip: Override for the config flag.

            :returns: The :class:`PythonEnvActionResult`.
        """
        command = self._build_venv_create_argv(
            path=path,
            interpreter=interpreter,
            system_site_packages=system_site_packages,
        )

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                command=command,
            )
            return dry_result

        if self.is_valid_environment(path=path):
            skipped = self._build_result(
                status=PythonEnvActionStatus.SKIPPED,
                path=path,
                command=command,
                message=_MESSAGE_ENV_ALREADY_EXISTS,
            )
            return skipped

        create_result = self._dispatch_write(command=command, path=path)
        if create_result.status != PythonEnvActionStatus.SUCCESS:
            return create_result

        if upgrade_pip is None:
            do_upgrade = self._config.upgrade_pip
        else:
            do_upgrade = upgrade_pip

        if not do_upgrade:
            return create_result

        upgrade_result = self.upgrade_pip(path=path)
        if upgrade_result.status == PythonEnvActionStatus.SUCCESS:
            return create_result

        upgrade_result.message = _MESSAGE_PIP_UPGRADE_FAILED
        return upgrade_result

    def remove_environment(self, path: str) -> PythonEnvActionResult:
        """
            Recursively remove the environment directory at ``path``.
            Skipped when no directory exists there.

            :param path: The environment root.

            :returns: The :class:`PythonEnvActionResult`.
        """
        command = self._layout.build_remove_tree_argv(path=path)

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                command=command,
            )
            return dry_result

        if not self.environment_exists(path=path):
            skipped = self._build_result(
                status=PythonEnvActionStatus.SKIPPED,
                path=path,
                command=command,
                message=_MESSAGE_ENV_NOT_FOUND,
            )
            return skipped

        rtnval = self._dispatch_write(command=command, path=path)
        return rtnval

    def install_packages(
        self,
        path: str,
        packages: List[str],
        *,
        upgrade: bool = False,
    ) -> PythonEnvActionResult:
        """
            Install PEP 508 requirement specifiers into the environment
            with ``<venv python> -m pip install``.

            Skipped when every specifier is already satisfied by the
            installed set (see :meth:`_requirement_satisfied` for what
            the probe can and cannot decide).  When ``upgrade`` is True
            the probe is bypassed and ``--upgrade`` is passed so pip
            resolves the newest permitted versions.

            :param path: The environment root.
            :param packages: Requirement specifiers, e.g.
                             ``["requests==2.32.3", "rich>=13"]``.
            :param upgrade: When True, pass ``--upgrade`` and never skip.

            :returns: The :class:`PythonEnvActionResult`.
            :raises ValueError: When ``packages`` is empty.
        """
        self._require_non_empty(items=packages, name="packages")

        install_args: List[str] = ["install"]
        if upgrade:
            install_args.append("--upgrade")
        install_args.extend(self._build_index_options())
        install_args.extend(self._build_pip_options())
        install_args.extend(packages)
        command = self._build_pip_argv(path=path, pip_args=install_args)

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                packages=packages,
                command=command,
            )
            return dry_result

        if not upgrade:
            installed = self.list_installed(path=path)
            all_satisfied = True
            for specifier in packages:
                if not self._requirement_satisfied(specifier=specifier, installed=installed):
                    all_satisfied = False
                    break
            if all_satisfied:
                skipped = self._build_result(
                    status=PythonEnvActionStatus.SKIPPED,
                    path=path,
                    packages=packages,
                    command=command,
                    message=_MESSAGE_PACKAGES_SATISFIED,
                )
                return skipped

        rtnval = self._dispatch_write(command=command, path=path, packages=packages)
        return rtnval

    def install_requirements(
        self,
        path: str,
        requirements_files: List[str],
        *,
        constraints_files: Optional[List[str]] = None,
        upgrade: bool = False,
    ) -> PythonEnvActionResult:
        """
            Install from one or more requirements files with
            ``pip install -r <file> [-c <constraints>]``.

            Never skips: pip already treats an already-satisfied
            requirements file as a no-op, and reproducing pip's
            resolver for arbitrary requirement files is out of scope.

            :param path: The environment root.
            :param requirements_files: Paths (on the target host) of the
                                       requirements files.
            :param constraints_files: Optional constraints-file paths.
            :param upgrade: When True, pass ``--upgrade``.

            :returns: The :class:`PythonEnvActionResult`.
            :raises ValueError: When ``requirements_files`` is empty.
        """
        self._require_non_empty(items=requirements_files, name="requirements_files")

        install_args: List[str] = ["install"]
        if upgrade:
            install_args.append("--upgrade")
        install_args.extend(self._build_index_options())
        install_args.extend(self._build_pip_options())
        for requirements_file in requirements_files:
            install_args.extend(["-r", requirements_file])
        if constraints_files is not None:
            for constraints_file in constraints_files:
                install_args.extend(["-c", constraints_file])
        command = self._build_pip_argv(path=path, pip_args=install_args)

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                packages=list(requirements_files),
                command=command,
            )
            return dry_result

        rtnval = self._dispatch_write(
            command=command,
            path=path,
            packages=list(requirements_files),
        )
        return rtnval

    def uninstall_packages(
        self,
        path: str,
        names: List[str],
    ) -> PythonEnvActionResult:
        """
            Remove distributions with ``pip uninstall -y``.

            Skipped when none of the named distributions are installed.
            When only some are installed the full list is still passed;
            pip reports the missing ones as skipped and exits ``0``.

            :param path: The environment root.
            :param names: Distribution names (specifier operators are
                          ignored by pip on uninstall).

            :returns: The :class:`PythonEnvActionResult`.
            :raises ValueError: When ``names`` is empty.
        """
        self._require_non_empty(items=names, name="names")

        uninstall_args: List[str] = ["uninstall", "-y"]
        uninstall_args.extend(names)
        command = self._build_pip_argv(path=path, pip_args=uninstall_args)

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                packages=names,
                command=command,
            )
            return dry_result

        installed = self.list_installed(path=path)
        installed_names = set()
        for info in installed:
            installed_names.add(self._normalise_name(name=info.name))

        any_present = False
        for name in names:
            if self._normalise_name(name=name) in installed_names:
                any_present = True
                break

        if not any_present:
            skipped = self._build_result(
                status=PythonEnvActionStatus.SKIPPED,
                path=path,
                packages=names,
                command=command,
                message=_MESSAGE_PACKAGES_NOT_INSTALLED,
            )
            return skipped

        rtnval = self._dispatch_write(command=command, path=path, packages=names)
        return rtnval

    def upgrade_pip(self, path: str) -> PythonEnvActionResult:
        """
            Upgrade ``pip`` inside the environment with
            ``pip install --upgrade pip``.  Never skips.

            :param path: The environment root.

            :returns: The :class:`PythonEnvActionResult`.
        """
        install_args: List[str] = ["install", "--upgrade"]
        install_args.extend(self._build_index_options())
        install_args.append(_PIP_MODULE)
        command = self._build_pip_argv(path=path, pip_args=install_args)

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                packages=[_PIP_MODULE],
                command=command,
            )
            return dry_result

        rtnval = self._dispatch_write(command=command, path=path, packages=[_PIP_MODULE])
        return rtnval

    def set_owner(self, path: str, owner: str) -> PythonEnvActionResult:
        """
            Hand the environment tree to ``owner``.

            Creating an environment with ``config.elevated`` produces a
            root- or Administrator-owned tree, which the service account that
            runs the application usually cannot write to.  This verb re-owns
            it recursively, and is the last step of :meth:`deploy` so that
            files pip created are covered too.

            Skipped when the environment root already reports ``owner``.  The
            probe reads only the root, not the whole tree: a partially-owned
            tree is the outcome of an interrupted ``chown``, and re-running
            the command is the cheapest way to converge it.

            :param path: The environment root.
            :param owner: ``user`` or ``user:group`` on POSIX; a bare account
                          name on Windows, where there is no group half.

            :returns: The :class:`PythonEnvActionResult`.

            :raises ValueError: When ``owner`` is empty or not of the form
                                ``user[:group]``.
        """
        self._require_owner(owner=owner)
        command = self._layout.build_set_owner_argv(path=path, owner=owner)

        if self._config.dry_run:
            dry_result = self._build_result(
                status=PythonEnvActionStatus.DRY_RUN,
                path=path,
                command=command,
            )
            return dry_result

        current = self.get_owner(path=path)
        if current is not None:
            wanted = self._layout.normalise_owner(owner)
            if current == wanted:
                skipped = self._build_result(
                    status=PythonEnvActionStatus.SKIPPED,
                    path=path,
                    command=command,
                    message=_MESSAGE_OWNER_ALREADY_SET,
                )
                return skipped

        rtnval = self._dispatch_write(command=command, path=path)
        return rtnval

    def get_owner(self, path: str) -> Optional[str]:
        """
            Read the current owner of the environment root, normalised for
            comparison by the layout.

            :param path: The environment root.

            :returns: The normalised owner, or ``None`` when the probe fails
                      (the path is absent, or the platform tool is missing).
        """
        command = self._layout.build_query_owner_argv(path=path)
        run_result = self._runner.run(list(command), elevated=False)

        if run_result.exit_code != 0:
            rtnval: Optional[str] = None
            return rtnval

        stripped = run_result.stdout.strip()
        if len(stripped) == 0:
            rtnval = None
            return rtnval

        rtnval = self._layout.normalise_owner(stripped)
        return rtnval

    def deploy(self, spec: PythonEnvSpec) -> PythonEnvDeployResult:
        """
            Converge an environment onto a :class:`PythonEnvSpec`.

            Steps, in order, stopping at the first ``FAILED``:

                1. ``remove_environment`` when ``spec.recreate`` and the
                   directory exists.
                2. ``create_environment`` (pip upgrade deferred to step 3
                   so an already-existing environment is upgraded too).
                3. ``upgrade_pip`` when the effective ``upgrade_pip`` is
                   True.
                4. ``install_requirements`` when the spec lists any
                   requirements files.
                5. ``install_packages`` when the spec lists any packages.
                6. ``set_owner`` when the spec names an owner.  Last, so
                   that everything pip wrote is re-owned as well.

            :param spec: The environment declaration.

            :returns: A :class:`PythonEnvDeployResult` carrying every
                      step result in order.
        """
        steps: List[PythonEnvActionResult] = []

        if spec.recreate:
            remove_result = self.remove_environment(path=spec.path)
            steps.append(remove_result)
            if remove_result.status == PythonEnvActionStatus.FAILED:
                rtnval = self._build_deploy_result(spec=spec, steps=steps)
                return rtnval

        create_result = self.create_environment(
            path=spec.path,
            interpreter=spec.interpreter,
            system_site_packages=spec.system_site_packages,
            upgrade_pip=False,
        )
        steps.append(create_result)
        if create_result.status == PythonEnvActionStatus.FAILED:
            rtnval = self._build_deploy_result(spec=spec, steps=steps)
            return rtnval

        if spec.upgrade_pip is None:
            do_upgrade_pip = self._config.upgrade_pip
        else:
            do_upgrade_pip = spec.upgrade_pip

        if do_upgrade_pip:
            pip_result = self.upgrade_pip(path=spec.path)
            steps.append(pip_result)
            if pip_result.status == PythonEnvActionStatus.FAILED:
                rtnval = self._build_deploy_result(spec=spec, steps=steps)
                return rtnval

        if len(spec.requirements_files) > 0:
            if len(spec.constraints_files) > 0:
                constraints: Optional[List[str]] = list(spec.constraints_files)
            else:
                constraints = None
            requirements_result = self.install_requirements(
                path=spec.path,
                requirements_files=list(spec.requirements_files),
                constraints_files=constraints,
                upgrade=spec.upgrade_packages,
            )
            steps.append(requirements_result)
            if requirements_result.status == PythonEnvActionStatus.FAILED:
                rtnval = self._build_deploy_result(spec=spec, steps=steps)
                return rtnval

        if len(spec.packages) > 0:
            packages_result = self.install_packages(
                path=spec.path,
                packages=list(spec.packages),
                upgrade=spec.upgrade_packages,
            )
            steps.append(packages_result)
            if packages_result.status == PythonEnvActionStatus.FAILED:
                rtnval = self._build_deploy_result(spec=spec, steps=steps)
                return rtnval

        if spec.owner is not None:
            owner_result = self.set_owner(path=spec.path, owner=spec.owner)
            steps.append(owner_result)

        rtnval = self._build_deploy_result(spec=spec, steps=steps)
        return rtnval

    # ------------------------------------------------------------------
    # Read verbs
    # ------------------------------------------------------------------

    def environment_exists(self, path: str) -> bool:
        """
            Return whether a directory exists at ``path``.  Does not
            verify it is a working environment; see
            :meth:`is_valid_environment`.

            :param path: The environment root.

            :returns: True when the layout's directory probe exits ``0``.
        """
        command = self._layout.build_directory_exists_argv(path=path)
        run_result = self._runner.run(list(command), elevated=False)
        rtnval = run_result.exit_code == 0
        return rtnval

    def is_valid_environment(self, path: str) -> bool:
        """
            Return whether ``path`` holds a working environment: the
            directory exists and its interpreter runs.

            :param path: The environment root.

            :returns: True when both probes succeed.
        """
        if not self.environment_exists(path=path):
            rtnval = False
            return rtnval

        version = self.get_python_version(path=path)
        rtnval = version is not None
        return rtnval

    def get_python_version(self, path: str) -> Optional[str]:
        """
            Run the environment interpreter and report its
            ``platform.python_version()``.

            :param path: The environment root.

            :returns: The version string, or ``None`` when the
                      interpreter could not be run.
        """
        command = [self._layout.venv_python_path(path=path), "-c", _PYTHON_VERSION_SNIPPET]
        run_result = self._runner.run(list(command), elevated=False)

        if run_result.exit_code != 0:
            rtnval: Optional[str] = None
            return rtnval

        stripped = run_result.stdout.strip()
        if len(stripped) == 0:
            rtnval = None
            return rtnval

        rtnval = stripped
        return rtnval

    def list_installed(self, path: str) -> List[PythonPackageInfo]:
        """
            List every installed distribution via
            ``pip list --format json``.

            :param path: The environment root.

            :returns: One :class:`PythonPackageInfo` per distribution.
            :raises PythonEnvQueryError: When pip exits non-zero or emits
                                         unparsable JSON.
        """
        command = self._build_pip_argv(path=path, pip_args=list(_PIP_LIST_FORMAT_JSON))
        run_result = self._runner.run(list(command), elevated=False)

        if run_result.exit_code != 0:
            raise PythonEnvQueryError(
                command=command,
                exit_code=run_result.exit_code,
                stderr=run_result.stderr,
            )

        rtnval = self._parse_pip_list_json(stdout=run_result.stdout, command=command)
        return rtnval

    def get_package_info(self, path: str, name: str) -> Optional[PythonPackageInfo]:
        """
            Look one distribution up by name (PEP 503 normalised
            comparison).

            :param path: The environment root.
            :param name: The distribution name.

            :returns: The :class:`PythonPackageInfo`, or ``None`` when
                      not installed.
            :raises PythonEnvQueryError: Propagated from
                                         :meth:`list_installed`.
        """
        wanted = self._normalise_name(name=name)
        for info in self.list_installed(path=path):
            if self._normalise_name(name=info.name) == wanted:
                rtnval: Optional[PythonPackageInfo] = info
                return rtnval

        rtnval = None
        return rtnval

    def is_package_installed(self, path: str, name: str) -> bool:
        """
            Return whether a distribution is installed.

            :param path: The environment root.
            :param name: The distribution name.

            :returns: True when :meth:`get_package_info` finds it.
        """
        info = self.get_package_info(path=path, name=name)
        rtnval = info is not None
        return rtnval

    def freeze(self, path: str) -> List[str]:
        """
            Return ``pip freeze`` output as a list of pinned requirement
            lines, suitable for writing to a requirements file.

            :param path: The environment root.

            :returns: One line per distribution.
            :raises PythonEnvQueryError: When pip exits non-zero.
        """
        command = self._build_pip_argv(path=path, pip_args=["freeze"])
        run_result = self._runner.run(list(command), elevated=False)

        if run_result.exit_code != 0:
            raise PythonEnvQueryError(
                command=command,
                exit_code=run_result.exit_code,
                stderr=run_result.stderr,
            )

        rtnval: List[str] = []
        for raw_line in run_result.stdout.splitlines():
            stripped = raw_line.strip()
            if len(stripped) == 0:
                continue
            rtnval.append(stripped)
        return rtnval

    def get_environment_info(self, path: str) -> Optional[PythonEnvInfo]:
        """
            Snapshot an environment: interpreter path, interpreter
            version, and installed distributions.

            :param path: The environment root.

            :returns: A :class:`PythonEnvInfo`, or ``None`` when no
                      directory exists at ``path``.
            :raises PythonEnvQueryError: Propagated from
                                         :meth:`list_installed`.
        """
        if not self.environment_exists(path=path):
            rtnval: Optional[PythonEnvInfo] = None
            return rtnval

        python_executable = self._layout.venv_python_path(path=path)
        python_version = self.get_python_version(path=path)
        packages = self.list_installed(path=path)

        rtnval = PythonEnvInfo(
            path=path,
            python_executable=python_executable,
            python_version=python_version,
            packages=packages,
        )
        return rtnval

    # ------------------------------------------------------------------
    # Argv construction helpers
    # ------------------------------------------------------------------

    def _resolve_base_interpreter(
        self,
        *,
        interpreter: Optional[List[str]],
    ) -> List[str]:
        """
            Pick the base-interpreter argv prefix: explicit argument,
            then config, then the layout default.

            :param interpreter: Caller-supplied override or ``None``.

            :returns: A copy of the chosen argv prefix.
        """
        if interpreter is not None and len(interpreter) > 0:
            rtnval = list(interpreter)
            return rtnval

        configured = self._config.base_interpreter
        if configured is not None and len(configured) > 0:
            rtnval = list(configured)
            return rtnval

        rtnval = self._layout.default_interpreter_argv()
        return rtnval

    def _build_venv_create_argv(
        self,
        *,
        path: str,
        interpreter: Optional[List[str]],
        system_site_packages: Optional[bool],
    ) -> List[str]:
        """
            Build ``<interpreter> -m venv [--system-site-packages] <path>``.

            :param path: The environment root.
            :param interpreter: Base-interpreter override or ``None``.
            :param system_site_packages: Flag override or ``None``.

            :returns: The argv list.
        """
        rtnval = self._resolve_base_interpreter(interpreter=interpreter)
        rtnval.extend(["-m", _VENV_MODULE])

        if system_site_packages is None:
            use_system_site = self._config.system_site_packages
        else:
            use_system_site = system_site_packages
        if use_system_site:
            rtnval.append("--system-site-packages")

        rtnval.append(path)
        return rtnval

    def _build_pip_argv(self, *, path: str, pip_args: List[str]) -> List[str]:
        """
            Build ``<venv python> -m pip <general options> <pip_args>``.

            ``python -m pip`` is used rather than the ``pip`` script so
            the invocation is identical on every OS and immune to a
            stale or missing console-script shim.

            :param path: The environment root.
            :param pip_args: The sub-command and its arguments.

            :returns: The argv list.
        """
        rtnval: List[str] = [self._layout.venv_python_path(path=path), "-m", _PIP_MODULE]
        rtnval.extend(_PIP_GENERAL_OPTIONS)
        rtnval.extend(pip_args)
        return rtnval

    def _build_index_options(self) -> List[str]:
        """
            Build the ``--index-url`` / ``--extra-index-url`` /
            ``--trusted-host`` tokens from the config.

            :returns: The option tokens (possibly empty).
        """
        rtnval: List[str] = []

        if self._config.index_url is not None:
            rtnval.extend(["--index-url", self._config.index_url])

        if self._config.extra_index_urls is not None:
            for extra_url in self._config.extra_index_urls:
                rtnval.extend(["--extra-index-url", extra_url])

        if self._config.trusted_hosts is not None:
            for trusted_host in self._config.trusted_hosts:
                rtnval.extend(["--trusted-host", trusted_host])

        return rtnval

    def _build_pip_options(self) -> List[str]:
        """
            Return a copy of the config's ``pip_options`` tail.

            :returns: The tokens (possibly empty).
        """
        if self._config.pip_options is None:
            rtnval: List[str] = []
            return rtnval

        rtnval = list(self._config.pip_options)
        return rtnval

    # ------------------------------------------------------------------
    # Dispatch and result helpers
    # ------------------------------------------------------------------

    def _dispatch_write(
        self,
        *,
        command: List[str],
        path: str,
        packages: Optional[List[str]] = None,
    ) -> PythonEnvActionResult:
        """
            Run a write command through the shared
            :meth:`BaseFeatureManager._dispatch` helper, echoing ``path``
            and ``packages`` onto the result.

            Callers perform dry-run and idempotency checks before
            invoking this helper (``_dispatch`` would honour dry-run too,
            but the callers short-circuit earlier so the probe is never
            issued).  Elevation follows ``config.elevated``; the recorded
            ``command`` is redacted; a Windows runner's
            ``elevation_blocked`` extension is surfaced by ``_dispatch``
            as the stable ``detail`` token
            :data:`DETAIL_ELEVATION_BLOCKED`.

            :param command: The argv to execute.
            :param path: The environment root echoed onto the result.
            :param packages: Specifiers echoed onto the result.

            :returns: The :class:`PythonEnvActionResult`.
        """
        rtnval = self._dispatch(
            command=command,
            detail=path,
            path=path,
            packages=packages,
        )
        return rtnval

    def _build_result(
        self,
        *,
        status: PythonEnvActionStatus,
        path: str,
        command: List[str],
        packages: Optional[List[str]] = None,
        message: Optional[str] = None,
    ) -> PythonEnvActionResult:
        """
            Construct a :class:`PythonEnvActionResult` without invoking
            the runner (``DRY_RUN`` / ``SKIPPED`` outcomes).

            :param status: The outcome status.
            :param path: The environment root.
            :param command: The would-have-been argv.
            :param packages: Specifiers echoed onto the result.
            :param message: Human-readable detail.

            :returns: The :class:`PythonEnvActionResult`.
        """
        rtnval = PythonEnvActionResult(
            status=status,
            detail=path,
            command=redact_command(command=list(command)),
            path=path,
            packages=packages,
            message=message,
        )
        return rtnval

    def _build_deploy_result(
        self,
        *,
        spec: PythonEnvSpec,
        steps: List[PythonEnvActionResult],
    ) -> PythonEnvDeployResult:
        """
            Fold step results into an aggregate
            :class:`PythonEnvDeployResult`.

            :param spec: The spec that was deployed.
            :param steps: Step results in execution order.

            :returns: The aggregate result.
        """
        message: Optional[str] = None
        any_failed = False
        any_success = False
        for step in steps:
            if step.status == PythonEnvActionStatus.FAILED:
                any_failed = True
                message = self._describe_failed_step(step=step)
                break
            if step.status == PythonEnvActionStatus.SUCCESS:
                any_success = True

        if any_failed:
            status = PythonEnvActionStatus.FAILED
        elif self._config.dry_run:
            status = PythonEnvActionStatus.DRY_RUN
        elif any_success:
            status = PythonEnvActionStatus.SUCCESS
        else:
            status = PythonEnvActionStatus.SKIPPED

        rtnval = PythonEnvDeployResult(
            status=status,
            path=spec.path,
            steps=steps,
            message=message,
        )
        return rtnval

    def _describe_failed_step(self, *, step: PythonEnvActionResult) -> str:
        """
            Render a one-line summary of a failed step for the deploy
            result's ``message``.

            :param step: The failed step.

            :returns: The summary text.
        """
        if step.command is None:
            command_text = "<no command>"
        else:
            command_text = " ".join(step.command)

        if step.message is not None:
            rtnval = "{} (exit={}): {}".format(command_text, step.exit_code, step.message)
        else:
            rtnval = "{} (exit={})".format(command_text, step.exit_code)
        return rtnval

    # ------------------------------------------------------------------
    # Parsing and requirement helpers
    # ------------------------------------------------------------------

    def _parse_pip_list_json(
        self,
        *,
        stdout: str,
        command: List[str],
    ) -> List[PythonPackageInfo]:
        """
            Parse ``pip list --format json`` output.

            :param stdout: Raw stdout.
            :param command: The argv, echoed into any raised error.

            :returns: One :class:`PythonPackageInfo` per entry.
            :raises PythonEnvQueryError: When the payload is not a JSON
                                         list of ``{name, version}``
                                         objects.
        """
        stripped = stdout.strip()
        if len(stripped) == 0:
            rtnval: List[PythonPackageInfo] = []
            return rtnval

        try:
            payload = json.loads(stripped)
        except ValueError as verr:
            raise PythonEnvQueryError(
                command=command,
                exit_code=0,
                stderr="pip list emitted unparsable JSON: {}".format(verr),
            )

        if not isinstance(payload, list):
            raise PythonEnvQueryError(
                command=command,
                exit_code=0,
                stderr="pip list JSON payload is not a list",
            )

        rtnval = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            version = entry.get("version")
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            rtnval.append(PythonPackageInfo(name=name, version=version))

        return rtnval

    def _requirement_satisfied(
        self,
        *,
        specifier: str,
        installed: List[PythonPackageInfo],
    ) -> bool:
        """
            Decide whether one requirement specifier is already satisfied
            by the installed set.

            The probe is deliberately conservative — it answers True only
            when it is certain, and defers to pip otherwise:

                * URL / path / editable requirements are never satisfied.
                * A bare name is satisfied when the name is installed.
                * ``==`` / ``===`` clauses need an exact string match.
                * ``!=`` needs a string mismatch.
                * Ordering clauses (``<``, ``<=``, ``>``, ``>=``, ``~=``)
                  are compared numerically and only when both versions
                  are purely dotted-numeric; anything else (pre-releases,
                  local labels, epochs) is treated as not satisfied.

            :param specifier: A PEP 508 requirement string.
            :param installed: The installed distributions.

            :returns: True when certainly satisfied.
        """
        parsed = self._parse_requirement(specifier=specifier)
        if parsed is None:
            rtnval = False
            return rtnval

        name, clauses = parsed
        wanted = self._normalise_name(name=name)

        installed_version: Optional[str] = None
        for info in installed:
            if self._normalise_name(name=info.name) == wanted:
                installed_version = info.version
                break

        if installed_version is None:
            rtnval = False
            return rtnval

        for operator, version in clauses:
            if not self._clause_satisfied(
                operator=operator,
                wanted=version,
                installed=installed_version,
            ):
                rtnval = False
                return rtnval

        rtnval = True
        return rtnval

    def _parse_requirement(
        self,
        *,
        specifier: str,
    ) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
        """
            Split a requirement into ``(name, [(operator, version), ...])``.

            :param specifier: A PEP 508 requirement string.

            :returns: The parsed tuple, or ``None`` when the requirement
                      is a URL / path / editable form or otherwise not
                      parsable.
        """
        stripped = specifier.strip()
        if len(stripped) == 0:
            rtnval: Optional[Tuple[str, List[Tuple[str, str]]]] = None
            return rtnval

        if stripped.startswith("-"):
            rtnval = None
            return rtnval

        for marker in _UNPROBEABLE_MARKERS:
            if marker in stripped:
                rtnval = None
                return rtnval

        # Environment markers are dropped for the probe; pip still sees
        # them on argv.
        head, _, _ = stripped.partition(";")

        match = _REQUIREMENT_HEAD_PATTERN.match(head)
        if match is None:
            rtnval = None
            return rtnval

        name = match.group("name")
        rest = match.group("rest").strip()

        clauses: List[Tuple[str, str]] = []
        if len(rest) > 0:
            if rest.startswith("(") and rest.endswith(")"):
                rest = rest[1:-1]
            for raw_clause in rest.split(","):
                clause_match = _VERSION_CLAUSE_PATTERN.match(raw_clause)
                if clause_match is None:
                    rtnval = None
                    return rtnval
                clauses.append((clause_match.group("op"), clause_match.group("version")))

        rtnval = (name, clauses)
        return rtnval

    def _clause_satisfied(
        self,
        *,
        operator: str,
        wanted: str,
        installed: str,
    ) -> bool:
        """
            Evaluate one version clause against an installed version.

            :param operator: One of ``===``, ``==``, ``!=``, ``~=``,
                             ``<=``, ``>=``, ``<``, ``>``.
            :param wanted: The clause version.
            :param installed: The installed version.

            :returns: True when certainly satisfied.
        """
        if operator in ("==", "==="):
            if wanted.endswith(".*"):
                prefix = wanted[:-2]
                rtnval = installed == prefix or installed.startswith(prefix + ".")
                return rtnval
            rtnval = installed == wanted
            return rtnval

        if operator == "!=":
            rtnval = installed != wanted
            return rtnval

        wanted_tuple = self._version_tuple(version=wanted)
        installed_tuple = self._version_tuple(version=installed)
        if wanted_tuple is None or installed_tuple is None:
            rtnval = False
            return rtnval

        if operator == ">=":
            rtnval = installed_tuple >= wanted_tuple
            return rtnval
        if operator == ">":
            rtnval = installed_tuple > wanted_tuple
            return rtnval
        if operator == "<=":
            rtnval = installed_tuple <= wanted_tuple
            return rtnval
        if operator == "<":
            rtnval = installed_tuple < wanted_tuple
            return rtnval
        if operator == "~=":
            # ``~= X.Y.Z`` means ``>= X.Y.Z, == X.Y.*``.
            if len(wanted_tuple) < 2:
                rtnval = False
                return rtnval
            prefix_len = len(wanted_tuple) - 1
            same_prefix = installed_tuple[:prefix_len] == wanted_tuple[:prefix_len]
            rtnval = same_prefix and installed_tuple >= wanted_tuple
            return rtnval

        rtnval = False
        return rtnval

    def _version_tuple(self, *, version: str) -> Optional[Tuple[int, ...]]:
        """
            Convert a purely dotted-numeric version to a comparable
            tuple, padding nothing (``1.2`` < ``1.2.0`` is avoided by
            trailing-zero normalisation).

            :param version: The version string.

            :returns: The tuple, or ``None`` when the version is not
                      purely dotted-numeric.
        """
        if _NUMERIC_VERSION_PATTERN.match(version) is None:
            rtnval: Optional[Tuple[int, ...]] = None
            return rtnval

        parts = [int(piece) for piece in version.split(".")]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()

        rtnval = tuple(parts)
        return rtnval

    def _normalise_name(self, *, name: str) -> str:
        """
            PEP 503 name normalisation: lower-case, runs of ``-``, ``_``,
            ``.`` collapsed to a single ``-``.

            :param name: A distribution name.

            :returns: The normalised name.
        """
        rtnval = re.sub(r"[-_.]+", "-", name).lower()
        return rtnval

    def _require_owner(self, *, owner: str) -> None:
        """
            Reject an owner that is empty or not of the form ``user[:group]``.

            :param owner: The caller-supplied owner.

            :raises ValueError: When the value is unusable.
        """
        if owner is None or not isinstance(owner, str) or len(owner) == 0:
            raise ValueError("'owner' must be a non-empty string.")

        if _OWNER_PATTERN.match(owner) is None:
            err_msg = (
                "'owner' must be 'user' or 'user:group', got {!r}.".format(owner)
            )
            raise ValueError(err_msg)

        if ":" in owner and not self._layout.supports_owner_group:
            err_msg = (
                "This platform has no paired owner group; supply a bare "
                "account name instead of {!r}.".format(owner)
            )
            raise ValueError(err_msg)
        return

    def _require_non_empty(self, *, items: List[str], name: str) -> None:
        """
            Raise when a required list argument is empty.

            :param items: The argument value.
            :param name: The argument name for the error message.

            :raises ValueError: When ``items`` is empty.
        """
        if items is None or len(items) == 0:
            err_msg = "'{}' must contain at least one entry.".format(name)
            raise ValueError(err_msg)
        return


__all__ = [
    "DETAIL_ELEVATION_BLOCKED",
    "PythonEnvActionResult",
    "PythonEnvActionStatus",
    "PythonEnvDeployResult",
    "PythonEnvInfo",
    "PythonEnvManagerConfig",
    "PythonEnvQueryError",
    "PythonEnvSpec",
    "PythonEnvironmentManagementBase",
    "PythonPackageInfo",
]
