"""
    VPNActionResult dataclass for the vpn-client-management contract.

    See :doc:`/specs/contracts/vpn-client-management/contract.md`.
"""

from dataclasses import dataclass
from typing import List, Optional

from automojo.sysman.common.vpnactionstatus import VPNActionStatus
from automojo.sysman.common.vpnprovider import VPNProvider


@dataclass
class VPNActionResult:
    """
        Canonical per-operation result returned by every write verb on
        the vpn-client-management contract.

        :param status: Outcome category of the operation.
        :param provider: Provider the operation targeted.
        :param detail: Free-form description of the operation.
        :param exit_code: Exit code from the command runner for
                          ``SUCCESS`` / ``FAILED`` outcomes.
        :param stdout: Captured stdout from the runner.
        :param stderr: Captured stderr from the runner.
        :param command: The argv that was (or would have been) executed.
    """
    status: VPNActionStatus
    provider: VPNProvider
    detail: Optional[str] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    command: Optional[List[str]] = None


__all__ = ["VPNActionResult"]
