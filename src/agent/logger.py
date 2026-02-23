import logging
import os
from datetime import datetime
from pathlib import Path


LOGS_DIR = Path(__file__).parent.parent.parent / "logs"

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_setup_done = False


def _setup():
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    LOGS_DIR.mkdir(exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger("agent")
    root.setLevel(logging.DEBUG)

    # Console — INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    # Single session file — everything DEBUG and above
    session_filename = datetime.now().strftime("session_%Y%m%d_%H%M%S.log")
    session_file = logging.FileHandler(
        LOGS_DIR / session_filename,
        encoding="utf-8",
    )
    session_file.setLevel(logging.DEBUG)
    session_file.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(session_file)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named child logger under the 'agent' hierarchy.
    Call this at module level: logger = get_logger(__name__)
    """
    _setup()
    return logging.getLogger(name)
