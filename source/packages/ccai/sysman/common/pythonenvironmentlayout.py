"""
    Filesystem-layout strategies for the python-environment-management
    contract.

    A Python virtual environment has the same logical shape on every OS
    (an interpreter, a ``site-packages`` tree, a ``pip`` module) but the
    on-disk layout, the default interpreter launcher, and the
    shell-level tools used to probe or remove a directory differ between
    POSIX hosts and Windows.  The layout classes here isolate exactly
    those differences so :class:`PythonEnvironmentManagementBase` can
    stay OS-neutral.

    Ownership is the one concern where "POSIX" is not a single answer:
    ``chown`` is common to Linux and macOS, but the ``stat`` used to read an
    owner back takes GNU flags on Linux and BSD flags on macOS.  That is why
    a BSD variant of the POSIX layout exists.

    Three concrete layouts ship with the package:

        * :class:`PosixPythonEnvironmentLayout` — ``<venv>/bin/python``,
          ``python3`` launcher, ``test -d`` / ``rm -rf`` probes.  Used by
          the Ubuntu, RHEL, and macOS sysman packages.
        * :class:`BsdPythonEnvironmentLayout` — the POSIX layout with the
          BSD ``stat -f`` owner probe.  Used by the macOS sysman package.
        * :class:`WindowsPythonEnvironmentLayout` —
          ``<venv>\\Scripts\\python.exe``, ``py -3`` launcher, PowerShell
          ``Test-Path`` / ``Remove-Item`` probes.  Used by the Windows
          sysman package.

    Every argv the layouts build is dispatched by the manager through the
    injected :class:`ICommandRunner`; the layouts themselves never touch
    the filesystem.
"""

import ntpath
import posixpath

from abc import ABC, abstractmethod
from typing import List


_DEFAULT_POWERSHELL = "powershell.exe"
_PS_NOPROFILE = "-NoProfile"
_PS_NONINTERACTIVE = "-NonInteractive"
_PS_COMMAND = "-Command"

_POSIX_BIN_DIRNAME = "bin"
_POSIX_PYTHON_EXECUTABLE = "python"

_WINDOWS_BIN_DIRNAME = "Scripts"
_WINDOWS_PYTHON_EXECUTABLE = "python.exe"


class PythonEnvironmentLayout(ABC):
    """
        Strategy describing how a virtual environment is laid out on
        disk and which OS-native commands probe or remove it.
    """

    @abstractmethod
    def default_interpreter_argv(self) -> List[str]:
        """
            The argv prefix used to invoke the base interpreter that
            creates new environments when the manager config does not
            supply one.

            :returns: An argv prefix such as ``["python3"]`` or
                      ``["py", "-3"]``.
        """

    @abstractmethod
    def join_path(self, base: str, *parts: str) -> str:
        """
            Join path components using the OS-native separator.

            :param base: The leading path component.
            :param parts: Trailing path components.

            :returns: The joined path.
        """

    @abstractmethod
    def venv_python_path(self, path: str) -> str:
        """
            The absolute path of the interpreter inside a virtual
            environment.

            :param path: The virtual-environment root.

            :returns: The interpreter path.
        """

    @abstractmethod
    def build_directory_exists_argv(self, path: str) -> List[str]:
        """
            Build an argv that exits ``0`` when ``path`` is an existing
            directory and non-zero otherwise.

            :param path: The directory to probe.

            :returns: The argv list.
        """

    @abstractmethod
    def build_remove_tree_argv(self, path: str) -> List[str]:
        """
            Build an argv that recursively removes ``path``.

            :param path: The directory to remove.

            :returns: The argv list.
        """

    @abstractmethod
    def build_query_owner_argv(self, path: str) -> List[str]:
        """
            Build an argv that prints the current owner of ``path`` on
            stdout, in the same form :meth:`normalise_owner` accepts.

            :param path: The directory to probe.

            :returns: The argv list.
        """

    @abstractmethod
    def build_set_owner_argv(self, path: str, owner: str) -> List[str]:
        """
            Build an argv that recursively assigns ``owner`` to ``path``.

            :param path: The directory to re-own.
            :param owner: The owner in this layout's notation.

            :returns: The argv list.
        """

    def normalise_owner(self, raw: str) -> str:
        """
            Normalise an owner string for comparison, so a probe result and
            a caller-supplied value can be matched.

            :param raw: A queried or caller-supplied owner.

            :returns: The normalised form.
        """
        rtnval = raw.strip()
        return rtnval

    @property
    def supports_owner_group(self) -> bool:
        """
            Whether this platform has a ``user:group`` ownership pair.

            :returns: True on POSIX; False on Windows, whose ACL model has
                      an owner but no paired group.
        """
        return True


class PosixPythonEnvironmentLayout(PythonEnvironmentLayout):
    """
        Layout for Linux and macOS hosts.
    """

    def default_interpreter_argv(self) -> List[str]:
        """
            :returns: ``["python3"]``.
        """
        rtnval = ["python3"]
        return rtnval

    def join_path(self, base: str, *parts: str) -> str:
        """
            Join with :mod:`posixpath`.
        """
        rtnval = posixpath.join(base, *parts)
        return rtnval

    def venv_python_path(self, path: str) -> str:
        """
            :returns: ``<path>/bin/python``.
        """
        rtnval = posixpath.join(path, _POSIX_BIN_DIRNAME, _POSIX_PYTHON_EXECUTABLE)
        return rtnval

    def build_directory_exists_argv(self, path: str) -> List[str]:
        """
            :returns: ``["test", "-d", <path>]``.
        """
        rtnval = ["test", "-d", path]
        return rtnval

    def build_remove_tree_argv(self, path: str) -> List[str]:
        """
            :returns: ``["rm", "-rf", <path>]``.
        """
        rtnval = ["rm", "-rf", path]
        return rtnval

    def build_query_owner_argv(self, path: str) -> List[str]:
        """
            :returns: ``["stat", "-c", "%U:%G", <path>]`` — the GNU
                      coreutils form used on Linux.  macOS ships BSD
                      ``stat``; see :class:`BsdPythonEnvironmentLayout`.
        """
        rtnval = ["stat", "-c", "%U:%G", path]
        return rtnval

    def build_set_owner_argv(self, path: str, owner: str) -> List[str]:
        """
            :returns: ``["chown", "-R", <owner>, <path>]``.
        """
        rtnval = ["chown", "-R", owner, path]
        return rtnval

    def normalise_owner(self, raw: str) -> str:
        """
            Normalise a POSIX owner.  A bare ``user`` and ``user:group`` are
            both accepted; the group half is dropped so that ``chown -R
            agent`` (which leaves the group alone) still compares equal to a
            probe that reports ``agent:staff``.

            :param raw: A queried or caller-supplied owner.

            :returns: The user portion, stripped.
        """
        stripped = raw.strip()
        user, _, _group = stripped.partition(":")
        rtnval = user
        return rtnval


class BsdPythonEnvironmentLayout(PosixPythonEnvironmentLayout):
    """
        The POSIX layout with the BSD ``stat`` owner probe, for macOS.

        Everything else — ``bin/python``, the ``python3`` launcher,
        ``test -d`` and ``rm -rf`` — is identical to
        :class:`PosixPythonEnvironmentLayout`.  Only the owner probe differs:
        GNU ``stat -c`` is not available on macOS, whose ``stat`` spells the
        same query ``-f "%Su:%Sg"``.
    """

    def build_query_owner_argv(self, path: str) -> List[str]:
        """
            :returns: ``["stat", "-f", "%Su:%Sg", <path>]``.
        """
        rtnval = ["stat", "-f", "%Su:%Sg", path]
        return rtnval


class WindowsPythonEnvironmentLayout(PythonEnvironmentLayout):
    """
        Layout for Windows hosts.  Directory probes and removal go
        through a PowerShell ``-Command`` scriptblock because Windows
        ships no ``test`` / ``rm`` equivalents that are reliably on the
        ``PATH`` of a WinRM or SSH session.
    """

    def __init__(self, *, powershell_executable: str = _DEFAULT_POWERSHELL) -> None:
        """
            :param powershell_executable: The PowerShell binary used for
                                          directory probes and removal.
                                          Defaults to ``powershell.exe``
                                          (PATH-resolved).
        """
        self._powershell_executable: str = powershell_executable
        return

    @property
    def powershell_executable(self) -> str:
        """
            The PowerShell binary used for directory probes and removal.
        """
        return self._powershell_executable

    def default_interpreter_argv(self) -> List[str]:
        """
            :returns: ``["py", "-3"]`` — the Python launcher for Windows,
                      which resolves the newest installed CPython 3.
        """
        rtnval = ["py", "-3"]
        return rtnval

    def join_path(self, base: str, *parts: str) -> str:
        """
            Join with :mod:`ntpath`.
        """
        rtnval = ntpath.join(base, *parts)
        return rtnval

    def venv_python_path(self, path: str) -> str:
        """
            :returns: ``<path>\\Scripts\\python.exe``.
        """
        rtnval = ntpath.join(path, _WINDOWS_BIN_DIRNAME, _WINDOWS_PYTHON_EXECUTABLE)
        return rtnval

    def build_directory_exists_argv(self, path: str) -> List[str]:
        """
            :returns: A PowerShell argv that exits ``0`` when ``path`` is
                      an existing container and ``1`` otherwise.
        """
        script = (
            "if (Test-Path -LiteralPath '{}' -PathType Container) "
            "{{ exit 0 }} else {{ exit 1 }}"
        ).format(escape_powershell_single_quoted(value=path))
        rtnval = self.build_powershell_argv(script=script)
        return rtnval

    def build_remove_tree_argv(self, path: str) -> List[str]:
        """
            :returns: A PowerShell argv running
                      ``Remove-Item -LiteralPath <path> -Recurse -Force``.
        """
        script = "Remove-Item -LiteralPath '{}' -Recurse -Force".format(
            escape_powershell_single_quoted(value=path),
        )
        rtnval = self.build_powershell_argv(script=script)
        return rtnval

    @property
    def supports_owner_group(self) -> bool:
        """
            :returns: False — the Windows ACL model has an owner but no
                      paired group, so a ``user:group`` owner is rejected.
        """
        return False

    def build_query_owner_argv(self, path: str) -> List[str]:
        """
            :returns: A PowerShell argv printing the ACL owner of ``path``
                      (for example ``BUILTIN\\Administrators`` or
                      ``CORP\\svc-agent``).
        """
        script = "(Get-Acl -LiteralPath '{}').Owner".format(
            escape_powershell_single_quoted(value=path),
        )
        rtnval = self.build_powershell_argv(script=script)
        return rtnval

    def build_set_owner_argv(self, path: str, owner: str) -> List[str]:
        """
            :returns: An ``icacls`` argv assigning the ACL owner recursively.

            Windows has no ``user:group`` ownership pair, so only the user
            portion of an owner is meaningful here; a ``group`` half is
            rejected by the manager before this is reached.  Setting an owner
            requires the SeRestorePrivilege, i.e. an elevated token.
        """
        rtnval = ["icacls", path, "/setowner", owner, "/T", "/C"]
        return rtnval

    def normalise_owner(self, raw: str) -> str:
        """
            Normalise a Windows ACL owner for comparison.  ``Get-Acl``
            reports a qualified ``DOMAIN\\user``; a caller may supply either
            that or the bare user name, so the comparison uses the portion
            after the last backslash, case-insensitively.

            :param raw: A queried or caller-supplied owner.

            :returns: The lower-cased account name.
        """
        stripped = raw.strip()
        _prefix, _, account = stripped.rpartition("\\")
        rtnval = account.lower()
        return rtnval

    def build_powershell_argv(self, *, script: str) -> List[str]:
        """
            Build the canonical ``["powershell.exe", "-NoProfile",
            "-NonInteractive", "-Command", <script>]`` argv.

            :param script: PowerShell scriptblock text.

            :returns: The argv list.
        """
        rtnval = [
            self._powershell_executable,
            _PS_NOPROFILE,
            _PS_NONINTERACTIVE,
            _PS_COMMAND,
            script,
        ]
        return rtnval


def escape_powershell_single_quoted(*, value: str) -> str:
    """
        Escape a string for inclusion inside PowerShell single quotes.

        :param value: Raw text.

        :returns: The text with every ``'`` doubled.
    """
    rtnval = value.replace("'", "''")
    return rtnval


__all__ = [
    "BsdPythonEnvironmentLayout",
    "PosixPythonEnvironmentLayout",
    "PythonEnvironmentLayout",
    "WindowsPythonEnvironmentLayout",
    "escape_powershell_single_quoted",
]
