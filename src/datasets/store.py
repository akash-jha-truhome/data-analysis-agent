"""Dataset store: persist uploaded CSV/Excel data locally + record DatasetRows.

Files land under ``<data_dir>/datasets/<dataset_id>/`` as an optional
``original.csv`` and ``data.parquet`` (the normalized full dataframe the
sandbox reloads per run).

Phase 3 adds multi-file sessions: a session may have multiple datasets linked
through the ``session_datasets`` join table, each exposed in the sandbox/prompt
under a python ``var_name``. Convention: the FIRST dataset linked to a session
is exposed as ``df`` (preserving single-file behavior + the deterministic
quality script); subsequent datasets get a sanitized name derived from their
filename/sheet, deduplicated within the session.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pandas as pd

from config.settings import get_settings
from db.models import DatasetRow, SessionDatasetRow
from db.session import create_db_session

from datasets.loader import (
    load_csv,
    load_excel,
    profile_dataframe,
    sanitize_var_name,
    write_parquet,
)


def _data_root() -> Path:
    """Filesystem root for persisted data (``data/`` at the repo root by default).

    Tests monkeypatch this to redirect writes into a tmp directory.
    """
    root = getattr(get_settings(), "data_dir", None) or "data"
    # Anchor to an absolute path: the sandbox child process runs with cwd=src/,
    # so a relative parquet path (e.g. "data/…") would not resolve there.
    return Path(root).resolve()


def _sample_rows() -> int:
    return getattr(get_settings(), "sample_rows", 5)


def _meta_from_row(row: DatasetRow, var_name: str | None = None) -> dict:
    meta = {
        "dataset_id": row.id,
        "filename": row.filename,
        "n_rows": row.n_rows,
        "n_cols": row.n_cols,
        "columns": json.loads(row.schema_json),
        "sample_rows": json.loads(row.sample_rows_json),
        "parquet_path": row.parquet_path,
    }
    if var_name is not None:
        meta["var_name"] = var_name
    return meta


def _persist_dataframe(
    df: pd.DataFrame,
    *,
    filename: str,
    original_src: Path | None,
) -> dict:
    """Profile + persist a dataframe as a new DatasetRow. Returns bare meta.

    When ``original_src`` is given (CSV path) it is copied alongside the parquet
    as ``original.csv``. Excel sheets have no per-sheet original file.
    """
    profile = profile_dataframe(df, _sample_rows())

    dataset_id = str(uuid4())
    dest_dir = _data_root() / "datasets" / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = dest_dir / "data.parquet"
    storage_path = str(parquet_path)
    if original_src is not None:
        original_path = dest_dir / "original.csv"
        shutil.copyfile(original_src, original_path)
        storage_path = str(original_path)

    write_parquet(df, parquet_path)

    with create_db_session() as session:
        row = DatasetRow(
            id=dataset_id,
            filename=filename,
            storage_path=storage_path,
            parquet_path=str(parquet_path),
            n_rows=profile["n_rows"],
            n_cols=profile["n_cols"],
            schema_json=json.dumps(profile["columns"]),
            sample_rows_json=json.dumps(profile["sample_rows"]),
        )
        session.add(row)

    return {
        "dataset_id": dataset_id,
        "filename": filename,
        "n_rows": profile["n_rows"],
        "n_cols": profile["n_cols"],
        "columns": profile["columns"],
        "sample_rows": profile["sample_rows"],
        "parquet_path": str(parquet_path),
    }


def store_dataset(
    *, file_path: str | Path, filename: str, session_id: str | None = None
) -> dict:
    """Load the CSV, profile it, persist original + parquet + a DatasetRow.

    Returns meta::

        {"dataset_id", "filename", "n_rows", "n_cols",
         "columns": [{"name","dtype"}], "sample_rows": [...], "parquet_path",
         "var_name"}

    When ``session_id`` is given, the dataset is linked to the session and
    ``var_name`` reflects the final (deduped) name used there. Otherwise
    ``var_name`` is the sanitized filename.

    Raises ValueError for an unparseable/empty CSV (the API layer maps to 400).
    """
    src = Path(file_path)
    if not src.exists():
        raise ValueError(f"Upload source file not found: {src}")

    # Parse first — an empty/garbage CSV must fail before we persist anything.
    df = load_csv(src)
    if df.shape[0] == 0:
        raise ValueError("CSV file contains a header but no data rows.")

    meta = _persist_dataframe(df, filename=filename, original_src=src)

    if session_id is not None:
        final = link_dataset_to_session(
            session_id, meta["dataset_id"], sanitize_var_name(filename)
        )
        meta["var_name"] = final
    else:
        meta["var_name"] = sanitize_var_name(filename)
    return meta


def store_excel(
    *, file_path: str | Path, filename: str, session_id: str | None = None
) -> list[dict]:
    """Read every sheet of an Excel workbook, persist one DatasetRow per sheet.

    Each non-empty sheet becomes its own dataset with filename recorded as
    ``"<workbook>#<SheetName>"`` and ``var_name`` = ``sanitize_var_name(sheet)``
    (deduped within the workbook). Returns a list of metas (same shape as
    :func:`store_dataset`, each with ``var_name``).

    When ``session_id`` is given, each dataset is linked to the session and its
    ``var_name`` reflects the final (deduped) name used there.

    Raises ValueError if the workbook has no readable sheet with rows.
    """
    src = Path(file_path)
    if not src.exists():
        raise ValueError(f"Upload source file not found: {src}")

    sheets = load_excel(src)

    metas: list[dict] = []
    used_names: set[str] = set()
    for sheet_name, df in sheets.items():
        if df is None or df.shape[0] == 0 or df.shape[1] == 0:
            continue

        var_name = _dedupe(sanitize_var_name(sheet_name), used_names)
        used_names.add(var_name)

        sheet_filename = f"{filename}#{sheet_name}"
        meta = _persist_dataframe(df, filename=sheet_filename, original_src=None)

        if session_id is not None:
            final = link_dataset_to_session(
                session_id, meta["dataset_id"], var_name
            )
            meta["var_name"] = final
        else:
            meta["var_name"] = var_name
        metas.append(meta)

    if not metas:
        raise ValueError("Excel workbook has no readable sheet with data rows.")
    return metas


def _dedupe(name: str, used: set[str]) -> str:
    if name not in used:
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    return f"{name}_{i}"


def link_dataset_to_session(
    session_id: str, dataset_id: str, var_name: str
) -> str:
    """Idempotent upsert into ``session_datasets``; returns the final var_name.

    Convention: the FIRST dataset linked to a session is exposed as ``df``
    (preserving single-file behavior). Subsequent datasets keep their supplied
    (sanitized) name, disambiguated with a ``_2`` suffix if it collides with a
    var_name already used in the session.
    """
    with create_db_session() as session:
        existing = (
            session.query(SessionDatasetRow)
            .filter(SessionDatasetRow.session_id == session_id)
            .order_by(SessionDatasetRow.created_at)
            .all()
        )

        # Idempotent: same dataset already linked -> return its current name.
        for link in existing:
            if link.dataset_id == dataset_id:
                return link.var_name

        if not existing:
            final = "df"
        else:
            used = {link.var_name for link in existing}
            final = _dedupe(var_name or "dataset", used)

        session.add(
            SessionDatasetRow(
                id=str(uuid4()),
                session_id=session_id,
                dataset_id=dataset_id,
                var_name=final,
            )
        )
        return final


def get_session_datasets(session_id: str) -> list[dict]:
    """Return every dataset linked to the session, ordered by link creation.

    Each entry::

        {dataset_id, var_name, filename, n_rows, n_cols, columns,
         sample_rows, parquet_path}

    Returns [] if the session has no linked datasets.
    """
    with create_db_session() as session:
        links = (
            session.query(SessionDatasetRow)
            .filter(SessionDatasetRow.session_id == session_id)
            .order_by(SessionDatasetRow.created_at)
            .all()
        )
        result: list[dict] = []
        for link in links:
            row = session.get(DatasetRow, link.dataset_id)
            if row is None:
                continue
            meta = _meta_from_row(row, var_name=link.var_name)
            result.append(meta)
        return result


def get_dataset_meta(dataset_id: str) -> dict | None:
    """Return the stored meta (incl. parquet_path) or None if unknown."""
    with create_db_session() as session:
        row = session.get(DatasetRow, dataset_id)
        if row is None:
            return None
        return _meta_from_row(row)
