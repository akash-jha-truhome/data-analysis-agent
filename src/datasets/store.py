"""Dataset store: persist an uploaded CSV locally + record a DatasetRow.

Files land under ``<data_dir>/datasets/<dataset_id>/`` as ``original.csv`` and
``data.parquet`` (the normalized full dataframe the sandbox reloads per run).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from config.settings import get_settings
from db.models import DatasetRow
from db.session import create_db_session

from datasets.loader import load_csv, profile_dataframe, write_parquet


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


def _meta_from_row(row: DatasetRow) -> dict:
    return {
        "dataset_id": row.id,
        "filename": row.filename,
        "n_rows": row.n_rows,
        "n_cols": row.n_cols,
        "columns": json.loads(row.schema_json),
        "sample_rows": json.loads(row.sample_rows_json),
        "parquet_path": row.parquet_path,
    }


def store_dataset(*, file_path: str | Path, filename: str) -> dict:
    """Load the CSV, profile it, persist the original + parquet + a DatasetRow.

    Returns meta::

        {"dataset_id", "filename", "n_rows", "n_cols",
         "columns": [{"name","dtype"}], "sample_rows": [...], "parquet_path"}

    Raises ValueError for an unparseable/empty CSV (the API layer maps to 400).
    """
    src = Path(file_path)
    if not src.exists():
        raise ValueError(f"Upload source file not found: {src}")

    # Parse first — an empty/garbage CSV must fail before we persist anything.
    df = load_csv(src)
    if df.shape[0] == 0:
        raise ValueError("CSV file contains a header but no data rows.")

    profile = profile_dataframe(df, _sample_rows())

    dataset_id = str(uuid4())
    dest_dir = _data_root() / "datasets" / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    original_path = dest_dir / "original.csv"
    parquet_path = dest_dir / "data.parquet"

    shutil.copyfile(src, original_path)
    write_parquet(df, parquet_path)

    with create_db_session() as session:
        row = DatasetRow(
            id=dataset_id,
            filename=filename,
            storage_path=str(original_path),
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


def get_dataset_meta(dataset_id: str) -> dict | None:
    """Return the stored meta (incl. parquet_path) or None if unknown."""
    with create_db_session() as session:
        row = session.get(DatasetRow, dataset_id)
        if row is None:
            return None
        return _meta_from_row(row)
