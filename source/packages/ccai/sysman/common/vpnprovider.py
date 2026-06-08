"""
    VPNProvider enum for the vpn-client-management contract.

    See :doc:`/specs/contracts/vpn-client-management/contract.md` for the
    cross-OS contract this enum participates in.
"""

from enum import Enum


class VPNProvider(Enum):
    """
        Identifies a mesh-VPN provider supported by the
        vpn-client-management contract.
    """
    TAILSCALE = "tailscale"
    TWINGATE = "twingate"


__all__ = ["VPNProvider"]
