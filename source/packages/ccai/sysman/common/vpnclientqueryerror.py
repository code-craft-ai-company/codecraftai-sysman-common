"""
    VPNClientQueryError exception for the vpn-client-management contract.

    See :doc:`/specs/contracts/vpn-client-management/contract.md`.
"""

from typing import Optional

from ccai.errors.exceptions import CommandError


class VPNClientQueryError(CommandError):
    """
        Raised by a vpn-client-management ``status`` verb when the
        underlying query command fails for reasons other than
        "daemon not installed" or "daemon not running".

        Derives from :class:`ccai.errors.exceptions.CommandError` so the suite's
        shared command-error vocabulary applies.

        :param message: Human-readable description of the failure.
        :param exit_code: Runner exit code captured at the failure
                          site, or ``None`` when no command ran.
        :param stderr: Captured stderr from the failing command, or
                       ``None``.
    """

    def __init__(
        self,
        *,
        message: str,
        exit_code: Optional[int] = None,
        stderr: Optional[str] = None,
    ) -> None:
        super().__init__(message, exit_code, None, stderr)
        self.message: str = message
        self.exit_code: Optional[int] = exit_code
        self.stderr: Optional[str] = stderr
        return


__all__ = ["VPNClientQueryError"]
