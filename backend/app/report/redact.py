"""Scrub secrets from text that goes into a client-facing report.

Findings quote page content (selectors, URLs, code snippets), and a page can contain a token. Reports
therefore pass every free-text and URL field through `redact` before output.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

_SENSITIVE_PARAM = re.compile(r"token|key|secret|passw|pwd|auth|session|sid|credential|signature|code", re.I)

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),  # Anthropic API keys
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),  # generic sk- keys
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),  # AWS access key ids
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),  # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWTs
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{12,}=*"),
]
# name=value or name: value pairs where the name looks like a credential
_ASSIGNMENT = re.compile(
    r"""(?ix)\b([\w\-]*(?:api[_\-]?key|secret|passw(?:or)?d|token|auth(?:orization)?)[\w\-]*)(["']?\s*[:=]\s*["']?)([^\s"'<>&,;]{4,})"""
)


def redact_url(url: str) -> str:
    """Drop credentials and the values of sensitive-looking query parameters from a URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact(url)
    if not parts.scheme and not parts.netloc:
        return redact(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    query = urlencode(
        [(k, REDACTED if _SENSITIVE_PARAM.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)],
        safe="[]",
    )
    return redact(urlunsplit((parts.scheme, netloc, parts.path, query, "")))  # fragment dropped


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
