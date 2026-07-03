"""Append-only local audit log.

One JSON line per record written to ``<data_dir>/audit.log``. This is a
best-effort sink: an IO failure must never break the request path, so all
errors are swallowed (log-and-continue).
"""
from __future__ import annotations

import json
from pathlib import Path

from config.settings import get_settings
from observability.events import get_logger

_log = get_logger("audit")


def _data_root() -> Path:
    """Filesystem root for persisted data. Tests monkeypatch this."""
    root = getattr(get_settings(), "data_dir", None) or "data"
    return Path(root)


def _audit_path() -> Path:
    return _data_root() / "audit.log"


def append_audit(record: dict) -> None:
    """Append one JSON line to the audit log. Never raises."""
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, default=str, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 — best-effort sink, must not raise
        try:
            _log.warning("audit_log_write_failed", error=str(exc))
        except Exception:  # noqa: BLE001
            pass
