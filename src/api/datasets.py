"""Dataset upload + fetch endpoints (spec/api.md)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File

from api._common import ok, api_error
from config.settings import get_settings

router = APIRouter()


@router.post("/datasets")
def upload_dataset(file: UploadFile = File(...)) -> dict:
    from datasets.store import store_dataset

    if file is None or not file.filename:
        raise api_error("BAD_REQUEST", "No file provided.", 400)

    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    # Stream to a temp file, enforcing the size cap as we go.
    suffix = Path(file.filename).suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    total = 0
    try:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise api_error(
                    "FILE_TOO_LARGE",
                    f"File exceeds the {settings.max_upload_mb} MB limit.",
                    400,
                )
            tmp.write(chunk)
        tmp.close()

        if total == 0:
            raise api_error("BAD_REQUEST", "Uploaded file is empty.", 400)

        try:
            meta = store_dataset(file_path=tmp.name, filename=file.filename)
        except ValueError as exc:
            raise api_error("UNPARSEABLE_CSV", str(exc), 400)
        except Exception as exc:  # local storage / write failure
            raise api_error("STORAGE_FAILURE", f"Failed to store dataset: {exc}", 500)

        return ok(
            {
                "dataset_id": meta["dataset_id"],
                "filename": meta["filename"],
                "n_rows": meta["n_rows"],
                "n_cols": meta["n_cols"],
                "columns": meta["columns"],
                "sample_rows": meta["sample_rows"],
            }
        )
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict:
    from datasets.store import get_dataset_meta

    meta = get_dataset_meta(dataset_id)
    if meta is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found.", 404)
    return ok(
        {
            "dataset_id": meta["dataset_id"],
            "filename": meta["filename"],
            "n_rows": meta["n_rows"],
            "n_cols": meta["n_cols"],
            "columns": meta["columns"],
            "sample_rows": meta["sample_rows"],
        }
    )
