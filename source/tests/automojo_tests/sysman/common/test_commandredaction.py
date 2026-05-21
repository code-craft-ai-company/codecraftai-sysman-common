"""
    Tests for the vpn-client-management secret redaction helpers and the
    automatic redaction performed by :class:`VPNActionResult`.
"""

import unittest

from automojo.sysman.common.commandredaction import (
    REDACTED_PLACEHOLDER,
    redact_command,
    redact_secret_argument,
    redact_text,
)
from automojo.sysman.common.vpnactionresult import VPNActionResult
from automojo.sysman.common.vpnactionstatus import VPNActionStatus
from automojo.sysman.common.vpnprovider import VPNProvider


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


if __name__ == "__main__":
    unittest.main()
