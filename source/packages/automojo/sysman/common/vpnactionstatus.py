"""
    VPNActionStatus enum for the vpn-client-management contract.

    See :doc:`/specs/contracts/vpn-client-management/contract.md`.
"""

from enum import Enum


class VPNActionStatus(Enum):
    """
        Outcome status returned from every write verb declared by the
        vpn-client-management contract.
    """
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"


__all__ = ["VPNActionStatus"]
