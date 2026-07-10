"""
    Secret redaction helpers for the vpn-client-management contract.

    VPN write verbs build argv lists that may embed vendor secrets
    (Tailscale auth keys, Twingate access / refresh / setup tokens).
    Those argv lists are stored on :class:`VPNActionResult.command` and
    routinely logged or persisted.  The helpers here replace the secret
    portion of any such argument with a fixed placeholder so the secret
    never reaches a result object, a log line, or an exception message.
"""

import os
import re

from typing import List, Optional


REDACTED_PLACEHOLDER = "***"

# The Windows vpn-client-management renderer stages secret file content
# (Tailscale auth key, Twingate connector config) by base64-encoding it
# into a PowerShell ``FromBase64String('<payload>')`` scriptblock. base64
# is trivially reversible, so the encoded payload is a secret that must be
# scrubbed from any recorded/logged command. This pattern captures that
# payload; base64 contains no single quote so ``[^']*`` bounds it exactly.
_FROM_BASE64_STRING_PATTERN = re.compile(r"FromBase64String\('([^']*)'\)")

# Long-option flags whose ``=value`` payload is a secret.  Matching is
# done against the portion of an argv token preceding the first ``=``.
_SECRET_OPTION_FLAGS = (
    "--authkey",
    "--auth-key",
    "--access-token",
    "--refresh-token",
    "--setup-token",
    "--api-token",
    "--token",
)

# Long-option flags whose secret value is supplied as the *following*
# argv token (``--flag value`` form rather than ``--flag=value``).
_SECRET_SPACED_FLAGS = (
    "--authkey",
    "--auth-key",
    "--access-token",
    "--refresh-token",
    "--setup-token",
    "--api-token",
    "--token",
)


def redact_secret_argument(*, argument: str) -> str:
    """
        Redact a single argv token if it carries a secret payload.

        Handles the ``--flag=secret`` form.  A token that is not a
        recognised secret-bearing flag is returned unchanged.

        :param argument: A single argv token.

        :returns: The token with any secret payload replaced by the
                  redaction placeholder.
    """
    if argument is None:
        rtnval = argument
        return rtnval

    separator_index = argument.find("=")
    if separator_index < 0:
        rtnval = argument
        return rtnval

    flag_part = argument[:separator_index]
    if flag_part in _SECRET_OPTION_FLAGS:
        rtnval = "{}={}".format(flag_part, REDACTED_PLACEHOLDER)
        return rtnval

    rtnval = argument
    return rtnval


def _redact_base64_staged_content(*, argument: str) -> str:
    """
        Redact the base64 payload inside any PowerShell
        ``FromBase64String('<payload>')`` construct within an argv token.

        A token that contains no such construct is returned unchanged.

        :param argument: A single argv token.

        :returns: The token with any base64-staged payload replaced by
                  the redaction placeholder.
    """
    if argument is None:
        rtnval = argument
        return rtnval

    replacement = "FromBase64String('{}')".format(REDACTED_PLACEHOLDER)
    rtnval = _FROM_BASE64_STRING_PATTERN.sub(replacement, argument)
    return rtnval


def redact_command(
    *,
    command: Optional[List[str]],
) -> Optional[List[str]]:
    """
        Return a copy of an argv list with every secret-bearing token
        replaced by the redaction placeholder.

        The ``--flag=secret`` and ``--flag secret`` forms are handled,
        as is the Windows ``FromBase64String('<payload>')`` staging form
        used to write secret file content via PowerShell.  ``None`` is
        returned unchanged.

        :param command: The argv list to redact, or ``None``.

        :returns: A redacted copy of the argv list, or ``None``.
    """
    if command is None:
        rtnval: Optional[List[str]] = None
        return rtnval

    redacted: List[str] = []
    redact_next = False
    for token in command:
        if redact_next is True:
            redacted.append(REDACTED_PLACEHOLDER)
            redact_next = False
            continue

        if token in _SECRET_SPACED_FLAGS:
            redacted.append(token)
            redact_next = True
            continue

        safe_token = redact_secret_argument(argument=token)
        safe_token = _redact_base64_staged_content(argument=safe_token)
        redacted.append(safe_token)

    rtnval = redacted
    return rtnval


def redact_text(*, text: Optional[str]) -> Optional[str]:
    """
        Redact secret payloads embedded in a free-form text blob.

        Any whitespace-separated token of the ``--flag=secret`` form is
        rewritten; this covers exception messages and detail strings
        that stringify an argv list.

        :param text: The text to scrub, or ``None``.

        :returns: The scrubbed text, or ``None``.
    """
    if text is None:
        rtnval: Optional[str] = None
        return rtnval

    if len(text) == 0:
        rtnval = text
        return rtnval

    pieces = text.split(" ")
    scrubbed: List[str] = []
    for piece in pieces:
        safe_piece = redact_secret_argument(argument=piece)
        scrubbed.append(safe_piece)

    rtnval = " ".join(scrubbed)
    return rtnval


__all__ = [
    "REDACTED_PLACEHOLDER",
    "redact_command",
    "redact_secret_argument",
    "redact_text",
]
