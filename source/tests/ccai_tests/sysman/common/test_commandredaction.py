"""
    Tests for the vpn-client-management secret redaction helpers and the
    automatic redaction performed by :class:`VPNActionResult`.
"""

import base64
import unittest

from ccai.sysman.common.commandredaction import (
    REDACTED_PLACEHOLDER,
    redact_command,
    redact_secret_argument,
    redact_text,
)
from ccai.sysman.common.vpnactionresult import VPNActionResult
from ccai.sysman.common.vpnactionstatus import VPNActionStatus
from ccai.sysman.common.vpnprovider import VPNProvider


class TestRedactSecretArgument(unittest.TestCase):
    """
        Coverage for :func:`redact_secret_argument`.
    """

    def test_redacts_authkey_flag(self) -> None:
        result = redact_secret_argument(argument="--authkey=tskey-secret")
        self.assertEqual(result, "--authkey=***")
        return

    def test_redacts_twingate_access_token(self) -> None:
        result = redact_secret_argument(
            argument="--access-token=abc.def.ghi",
        )
        self.assertEqual(result, "--access-token=***")
        return

    def test_leaves_non_secret_flag_untouched(self) -> None:
        result = redact_secret_argument(argument="--hostname=winbox")
        self.assertEqual(result, "--hostname=winbox")
        return

    def test_leaves_plain_token_untouched(self) -> None:
        result = redact_secret_argument(argument="install")
        self.assertEqual(result, "install")
        return


class TestRedactCommand(unittest.TestCase):
    """
        Coverage for :func:`redact_command`.
    """

    def test_none_passes_through(self) -> None:
        result = redact_command(command=None)
        self.assertIsNone(result)
        return

    def test_redacts_equals_form(self) -> None:
        command = ["tailscale", "up", "--authkey=tskey-SECRET"]
        result = redact_command(command=command)
        self.assertEqual(result, ["tailscale", "up", "--authkey=***"])
        return

    def test_redacts_spaced_form(self) -> None:
        command = ["twingate", "setup", "--access-token", "SECRET-TOKEN"]
        result = redact_command(command=command)
        self.assertEqual(
            result,
            ["twingate", "setup", "--access-token", REDACTED_PLACEHOLDER],
        )
        return

    def test_preserves_non_secret_arguments(self) -> None:
        command = [
            "tailscale", "up", "--authkey=tskey-SECRET",
            "--hostname=winbox", "--advertise-exit-node",
        ]
        result = redact_command(command=command)
        self.assertEqual(
            result,
            [
                "tailscale", "up", "--authkey=***",
                "--hostname=winbox", "--advertise-exit-node",
            ],
        )
        return


class TestRedactText(unittest.TestCase):
    """
        Coverage for :func:`redact_text`.
    """

    def test_redacts_embedded_secret(self) -> None:
        text = "failed running tailscale up --authkey=tskey-SECRET now"
        result = redact_text(text=text)
        self.assertIsNotNone(result)
        self.assertNotIn("tskey-SECRET", result)
        self.assertIn("--authkey=***", result)
        return


class TestVPNActionResultRedaction(unittest.TestCase):
    """
        C3 regression: a :class:`VPNActionResult` must never store an
        auth key or token verbatim in its ``command`` field.
    """

    def test_authkey_redacted_on_construction(self) -> None:
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
        self.assertIsNotNone(result.command)
        joined = " ".join(result.command)
        self.assertNotIn(secret, joined)
        self.assertIn("--authkey=***", joined)
        return

    def test_none_command_stays_none(self) -> None:
        result = VPNActionResult(
            status=VPNActionStatus.SKIPPED,
            provider=VPNProvider.TAILSCALE,
            detail="noop",
            exit_code=None,
            stdout=None,
            stderr=None,
            command=None,
        )
        self.assertIsNone(result.command)
        return


class TestRedactBase64StagedContent(unittest.TestCase):
    """
        Coverage for redaction of the Windows ``FromBase64String``
        secret-staging form (Tailscale auth key, Twingate config).
    """

    def _staged_command(self, secret: str) -> list:
        encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        script = (
            "$content = [System.Text.Encoding]::UTF8.GetString("
            "[System.Convert]::FromBase64String('{}')); "
            "[System.IO.File]::WriteAllText('C:\\Temp\\authkey', $content, "
            "(New-Object System.Text.UTF8Encoding $false))"
        ).format(encoded)
        rtnval = ["powershell.exe", "-NoProfile", "-Command", script]
        return rtnval

    def test_redact_command_scrubs_base64_staged_secret(self) -> None:
        secret = "tskey-auth-SUPERSECRET123456"
        encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        command = self._staged_command(secret=secret)

        redacted = redact_command(command=command)
        joined = " ".join(redacted)

        self.assertNotIn(secret, joined)
        self.assertNotIn(encoded, joined)
        self.assertIn("FromBase64String('***')", joined)
        return

    def test_vpnactionresult_scrubs_base64_staged_secret(self) -> None:
        secret = "twingate-setup-token-ABCDEF"
        encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        command = self._staged_command(secret=secret)

        result = VPNActionResult(
            status=VPNActionStatus.SUCCESS,
            provider=VPNProvider.TWINGATE,
            detail="stage_config",
            exit_code=0,
            stdout=None,
            stderr=None,
            command=command,
        )
        joined = " ".join(result.command)

        self.assertNotIn(secret, joined)
        self.assertNotIn(encoded, joined)
        self.assertIn("FromBase64String('***')", joined)
        return

    def test_non_base64_command_untouched(self) -> None:
        command = ["powershell.exe", "-Command", "Get-Service -Name tailscale"]
        redacted = redact_command(command=command)
        self.assertEqual(redacted, command)
        return



class TestRedactUrlUserinfo(unittest.TestCase):
    """
        URL userinfo redaction for python-environment-management index
        URLs.
    """

    def test_redact_url_userinfo_scrubs_bare_url(self) -> None:
        from ccai.sysman.common.commandredaction import redact_url_userinfo
        result = redact_url_userinfo(argument="https://svc:s3cret@pypi.example/simple")
        self.assertEqual(result, "https://***@pypi.example/simple")
        return

    def test_redact_url_userinfo_scrubs_equals_form(self) -> None:
        from ccai.sysman.common.commandredaction import redact_url_userinfo
        result = redact_url_userinfo(argument="--index-url=https://svc:s3cret@pypi.example/simple")
        self.assertEqual(result, "--index-url=https://***@pypi.example/simple")
        return

    def test_redact_url_userinfo_leaves_credential_free_url(self) -> None:
        from ccai.sysman.common.commandredaction import redact_url_userinfo
        result = redact_url_userinfo(argument="https://pypi.org/simple")
        self.assertEqual(result, "https://pypi.org/simple")
        return

    def test_redact_command_scrubs_index_url_credentials(self) -> None:
        from ccai.sysman.common.commandredaction import redact_command
        command = [
            "python", "-m", "pip", "install",
            "--index-url", "https://svc:s3cret@pypi.example/simple",
            "--extra-index-url=https://a:b@extra.example/simple",
            "rich",
        ]
        result = redact_command(command=command)
        self.assertEqual(result, [
            "python", "-m", "pip", "install",
            "--index-url", "https://***@pypi.example/simple",
            "--extra-index-url=https://***@extra.example/simple",
            "rich",
        ])
        return

    def test_redact_text_scrubs_index_url_credentials(self) -> None:
        from ccai.sysman.common.commandredaction import redact_text
        result = redact_text(text="pip failed for https://svc:s3cret@pypi.example/simple today")
        self.assertEqual(result, "pip failed for https://***@pypi.example/simple today")
        return

if __name__ == "__main__":
    unittest.main()
