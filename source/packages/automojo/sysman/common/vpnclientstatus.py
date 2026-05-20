"""
    VPNClientStatus dataclass for the vpn-client-management contract.

    See :doc:`/specs/contracts/vpn-client-management/contract.md`.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from automojo.sysman.common.vpnprovider import VPNProvider


def _empty_peer_addresses() -> Dict[str, str]:
    """
        Build a fresh empty mapping for the ``peer_addresses`` field.

        Using a factory satisfies the project's no-mutable-default rule
        while still allowing the field to default to an empty dict.

        :returns: A new empty ``Dict[str, str]``.
    """
    rtnval: Dict[str, str] = {}
    return rtnval


@dataclass
class VPNClientStatus:
    """
        Typed status snapshot returned by ``status()`` on a
        vpn-client-management feature manager.

        :param provider: Provider being reported.
        :param installed: True when the daemon package is present.
        :param running: True when the daemon is active and the tunnel
                        is up.
        :param self_address: Overlay IP for providers that assign one
                             per client (Tailscale); ``None`` otherwise.
        :param hostname: Hostname registered with the control plane.
        :param tailnet: Tailnet / network slug if known.
        :param peer_addresses: Mapping of peer hostname to overlay IP.
                               Empty for providers without per-client
                               overlay addressing.
        :param version: Installed client version string.
    """
    provider: VPNProvider
    installed: bool = False
    running: bool = False
    self_address: Optional[str] = None
    hostname: Optional[str] = None
    tailnet: Optional[str] = None
    peer_addresses: Dict[str, str] = field(default_factory=_empty_peer_addresses)
    version: Optional[str] = None


__all__ = ["VPNClientStatus"]
