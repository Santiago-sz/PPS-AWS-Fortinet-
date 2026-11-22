"""
Helpers shared by the scripts that run on the operator's workstation
(`run_executor_local.py`, `diagnose_fortigate_local.py`).

They cover the FortiGate side of the environment only: reading and checking
`FORTIGATE_HOST` / `FORTIGATE_TOKEN` / `FORTIGATE_VERIFY_SSL`, keeping the
token out of every output, and the guidance shown when the device does not
answer. Standard library only: nothing here needs AWS.

This file lives in scripts/, which is not packaged into the Lambda zip.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys

REDACTED = "[REDACTED]"
GUIDE = "docs/context/local-executor-run.md"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class ConfigError(Exception):
    """Invalid configuration or input. The message is safe to print."""


class RedactingFilter(logging.Filter):
    """Removes the token from every log record before a handler emits it.

    Defence in depth: the local scripts never log the token, but a dependency
    may embed it in an error text (http.client includes the header value in
    the error it raises for a malformed header, and the client logs that text).
    """

    def __init__(self, secret: str):
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self._secret in message:
            record.msg = message.replace(self._secret, REDACTED)
            record.args = ()
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = formatted.replace(self._secret, REDACTED)
            record.exc_info = None
        elif record.exc_text and self._secret in record.exc_text:
            record.exc_text = record.exc_text.replace(self._secret, REDACTED)
        return True


def redact(value, secret: str):
    """Returns `value` with every occurrence of `secret` replaced, recursively."""
    if isinstance(value, str):
        return value.replace(secret, REDACTED)
    if isinstance(value, dict):
        return {redact(k, secret): redact(v, secret) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item, secret) for item in value]
    return value


def read_fortigate_env() -> dict:
    """Reads the FortiGate variables without judging them.

    Missing values come back as empty strings so that the caller can report
    every missing variable at once, together with its own.
    """
    return {
        "host": os.environ.get("FORTIGATE_HOST", "").strip(),
        "token": os.environ.get("FORTIGATE_TOKEN", "").strip(),
        "verify_ssl": os.environ.get("FORTIGATE_VERIFY_SSL", "true").lower() == "true",
    }


def require_env(named_values: list[tuple[str, str]]) -> None:
    """Raises `ConfigError` naming every variable whose value is empty."""
    missing = [name for name, value in named_values if not value]
    if missing:
        raise ConfigError(
            "Required environment variable(s) not set: " + ", ".join(missing) + f". See {GUIDE}."
        )


def check_fortigate_env(host: str, token: str) -> None:
    """Rejects a malformed host or token. Never echoes the token."""
    if any(ch.isspace() or not ch.isprintable() for ch in token):
        raise ConfigError(
            "FORTIGATE_TOKEN contains whitespace or control characters. "
            "Set it again with the exact token value (it is not shown here)."
        )
    if "://" in host or "/" in host:
        raise ConfigError("FORTIGATE_HOST must be a host or host:port, without scheme or path.")


def unreachable_message(headline: str, verify_ssl: bool) -> str:
    """Guidance for a FortiGate that did not answer the first read-only GET."""
    return "\n".join(
        [
            headline,
            "The log lines above show the HTTP status or the network error.",
            "Likely causes:",
            "  - The VPN (FortiClient) is not connected, or it does not route to that address.",
            "  - The trusted host of the REST API admin does not include the IP address",
            "    that the VPN assigned to this machine (HTTP 401 or 403, or a timeout).",
            "  - Wrong port: FORTIGATE_HOST accepts host:port when the admin HTTPS port",
            "    is not 443.",
            "  - Self-signed certificate: the log shows CERTIFICATE_VERIFY_FAILED. For a",
            f"    lab only, set FORTIGATE_VERIFY_SSL=false (current value: {verify_ssl}).",
            "  - Invalid or regenerated token, or a profile without read access (401/403).",
            f"Check it by hand with the curl command in {GUIDE}.",
        ]
    )


@contextlib.contextmanager
def redacted_logging(token: str):
    """Logs to stderr with the token redacted, for the duration of the block.

    Adds a stderr handler and puts the redacting filter on it and on every
    handler already attached to the root logger. Everything is undone on exit.
    """
    root = logging.getLogger()
    previous_level = root.level
    redacting_filter = RedactingFilter(token)
    own_handler = logging.StreamHandler(sys.stderr)
    own_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    filtered_handlers = [*root.handlers, own_handler]
    for handler in filtered_handlers:
        handler.addFilter(redacting_filter)
    root.addHandler(own_handler)
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    if previous_level == logging.NOTSET or previous_level > level:
        root.setLevel(level)
    try:
        yield
    finally:
        root.removeHandler(own_handler)
        for handler in filtered_handlers:
            handler.removeFilter(redacting_filter)
        root.setLevel(previous_level)
