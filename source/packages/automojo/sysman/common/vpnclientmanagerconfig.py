"""
    VPNClientManagerConfig dataclass for the vpn-client-management contract.

    See :doc:`/specs/contracts/vpn-client-management/contract.md`.
"""

from dataclasses import dataclass


@dataclass
class VPNClientManagerConfig:
    """
        Configuration for a VPN-client manager.

        Per-OS subclasses MAY extend this dataclass with OS-specific
        fields but MUST preserve ``dry_run`` and ``elevated`` with the
        contract-mandated defaults.

        :param dry_run: When True, no mutating command dispatches; the
                        would-have-been command is recorded on the
                        returned :class:`VPNActionResult`.
        :param elevated: When True, mutating commands dispatch with
                         ``elevated=True`` to the runner.
    """
    dry_run: bool = False
    elevated: bool = False


__all__ = ["VPNClientManagerConfig"]
