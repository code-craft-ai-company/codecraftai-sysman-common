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

    Two concrete layouts ship with the package:

        * :class:`PosixPythonEnvironmentLayout` — ``<venv>/bin/python``,
          ``python3`` launcher, ``test -d`` / ``rm -rf`` probes.  Used by
          the Ubuntu, RHEL, and macOS sysman packages.
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
        ...

    @abstractmethod
    def join_path(self, base: str, *parts: str) -> str:
        """
            Join path components using the OS-native separator.

            :param base: The leading path component.
            :param parts: Trailing path components.

            :returns: The joined path.
        """
        ...

    @abstractmethod
    def venv_python_path(self, path: str) -> str:
        """
            The absolute path of the interpreter inside a virtual
            environment.

            :param path: The virtual-environment root.

            :returns: The interpreter path.
        """
        ...

    @abstractmethod
    def build_directory_exists_argv(self, path: str) -> List[str]:
        """
            Build an argv that exits ``0`` when ``path`` is an existing
            directory and non-zero otherwise.

            :param path: The directory to probe.

            :returns: The argv list.
        """
        ...

    @abstractmethod
    def build_remove_tree_argv(self, path: str) -> List[str]:
        """
            Build an argv that recursively removes ``path``.

            :param path: The directory to remove.

            :returns: The argv list.
        """
        ...


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
    "PosixPythonEnvironmentLayout",
    "PythonEnvironmentLayout",
    "WindowsPythonEnvironmentLayout",
    "escape_powershell_single_quoted",
]
