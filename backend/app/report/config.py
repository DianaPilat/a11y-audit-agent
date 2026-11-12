"""Report settings. Defaults are the client-safe ones."""

import os

INCLUDE_UNREVIEWED_ENV = "REPORT_INCLUDE_UNREVIEWED"


def include_unreviewed_default() -> bool:
    """Demo switch (off by default): also list findings no human has approved or rejected, labeled "Unreviewed"."""
    return os.environ.get(INCLUDE_UNREVIEWED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
