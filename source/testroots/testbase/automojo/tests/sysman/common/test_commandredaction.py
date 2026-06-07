"""
    Tests for the vpn-client-management secret redaction helpers and the
    automatic redaction performed by :class:`VPNActionResult`.
"""

from automojo.sysman.common.commandredaction import (
    REDACTED_PLACEHOLDER,
    redact_command,
    redact_secret_argument,
    redact_text,
)
from automojo.sysman.common.vpnactionresult import VPNActionResult
from automojo.sysman.common.vpnactionstatus import VPNActionStatus
from automojo.sysman.common.vpnprovider import VPNProvider


def test_redacts_authkey_flag() -> None:
    result = redact_secret_argument(argument="--authkey=tskey-secret")
    assert result == "--authkey=***"
    return


def test_redacts_twingate_access_token() -> None:
    result = redact_secret_argument(
        argument="--access-token=abc.def.ghi",
    )
    assert result == "--access-token=***"
    return


def test_leaves_non_secret_flag_untouched() -> None:
    result = redact_secret_argument(argument="--hostname=winbox")
    assert result == "--hostname=winbox"
    return


def test_leaves_plain_token_untouched() -> None:
    result = redact_secret_argument(argument="install")
    assert result == "install"
    return


def test_none_passes_through() -> None:
    result = redact_command(command=None)
    assert result is None
    return


def test_redacts_equals_form() -> None:
    command = ["tailscale", "up", "--authkey=tskey-SECRET"]
    result = redact_command(command=command)
    assert result == ["tailscale", "up", "--authkey=***"]
    return


def test_redacts_spaced_form() -> None:
    command = ["twingate", "setup", "--access-token", "SECRET-TOKEN"]
    result = redact_command(command=command)
    assert result == ["twingate", "setup", "--access-token", REDACTED_PLACEHOLDER]
    return


def test_preserves_non_secret_arguments() -> None:
    command = [
        "tailscale", "up", "--authkey=tskey-SECRET",
        "--hostname=winbox", "--advertise-exit-node",
    ]
    result = redact_command(command=command)
    assert result == [
        "tailscale", "up", "--authkey=***",
        "--hostname=winbox", "--advertise-exit-node",
    ]
    return


def test_redacts_embedded_secret() -> None:
    text = "failed running tailscale up --authkey=tskey-SECRET now"
    result = redact_text(text=text)
    assert result is not None
    assert "tskey-SECRET" not in result
    assert "--authkey=***" in result
    return


def test_authkey_redacted_on_construction() -> None:
    secret = "tskey-auth-SUPERSECRET"
    result = VPNActionResult(
        status=VPNActionStatus.SUCCESS,
        provider=VPNProvider.TAILSCALE,
        detail="bring_up",
        exit_code=0,
        stdout=None,
        stderr=None,
        command=["tailscale", "up", "--authkey={}".format(secret)],
    )
    assert result.command is not None
    joined = " ".join(result.command)
    assert secret not in joined
    assert "--authkey=***" in joined
    return


def test_none_command_stays_none() -> None:
    result = VPNActionResult(
        status=VPNActionStatus.SKIPPED,
        provider=VPNProvider.TAILSCALE,
        detail="noop",
        exit_code=None,
        stdout=None,
        stderr=None,
        command=None,
    )
    assert result.command is None
    return
