"""
    Tests for the vpn-client-management secret redaction helpers and the
    automatic redaction performed by :class:`VPNActionResult`.
"""

from ccai.sysman.common.commandredaction import (
    REDACTED_PLACEHOLDER,
    redact_command,
    redact_secret_argument,
    redact_text,
)
from ccai.sysman.common.vpnactionresult import VPNActionResult
from ccai.sysman.common.vpnactionstatus import VPNActionStatus
from ccai.sysman.common.vpnprovider import VPNProvider


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


# ----------------------------------------------------------------------
# URL userinfo redaction (python-environment-management index URLs)
# ----------------------------------------------------------------------


def test_redact_url_userinfo_scrubs_bare_url() -> None:
    from ccai.sysman.common.commandredaction import redact_url_userinfo
    result = redact_url_userinfo(argument="https://svc:s3cret@pypi.example/simple")
    assert result == "https://***@pypi.example/simple"
    return


def test_redact_url_userinfo_scrubs_equals_form() -> None:
    from ccai.sysman.common.commandredaction import redact_url_userinfo
    result = redact_url_userinfo(argument="--index-url=https://svc:s3cret@pypi.example/simple")
    assert result == "--index-url=https://***@pypi.example/simple"
    return


def test_redact_url_userinfo_leaves_credential_free_url() -> None:
    from ccai.sysman.common.commandredaction import redact_url_userinfo
    result = redact_url_userinfo(argument="https://pypi.org/simple")
    assert result == "https://pypi.org/simple"
    return


def test_redact_command_scrubs_index_url_credentials() -> None:
    command = [
        "python", "-m", "pip", "install",
        "--index-url", "https://svc:s3cret@pypi.example/simple",
        "--extra-index-url=https://a:b@extra.example/simple",
        "rich",
    ]
    result = redact_command(command=command)
    assert result == [
        "python", "-m", "pip", "install",
        "--index-url", "https://***@pypi.example/simple",
        "--extra-index-url=https://***@extra.example/simple",
        "rich",
    ]
    return


def test_redact_text_scrubs_index_url_credentials() -> None:
    result = redact_text(text="pip failed for https://svc:s3cret@pypi.example/simple today")
    assert result == "pip failed for https://***@pypi.example/simple today"
    return
