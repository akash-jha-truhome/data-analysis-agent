"""Dataset upload + fetch endpoints (spec/api.md)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form

from api._common import ok, api_error
from config.settings import get_settings

router = APIRouter()


_EXCEL_SUFFIXES = {".xlsx", ".xls"}


@router.post("/datasets")
def upload_dataset(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
) -> dict:
    from datasets.store import store_dataset, store_excel

    if file is None or not file.filename:
        raise api_error("BAD_REQUEST", "No file provided.", 400)

    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    suffix = Path(file.filename).suffix or ".csv"
    is_excel = suffix.lower() in _EXCEL_SUFFIXES

    # Stream to a temp file, enforcing the size cap as we go.
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

        if is_excel:
            try:
                metas = store_excel(
                    file_path=tmp.name,
                    filename=file.filename,
                    session_id=session_id,
                )
            except ValueError as exc:
                raise api_error("UNPARSEABLE_EXCEL", str(exc), 400)
            except Exception as exc:  # local storage / write failure
                raise api_error(
                    "STORAGE_FAILURE", f"Failed to store dataset: {exc}", 500
                )

            return ok(
                {
                    "is_excel": True,
                    "datasets": [
                        {
                            "dataset_id": m["dataset_id"],
                            "filename": m["filename"],
                            "var_name": m["var_name"],
                            "n_rows": m["n_rows"],
                            "n_cols": m["n_cols"],
                            "columns": m["columns"],
                            "sample_rows": m["sample_rows"],
                        }
                        for m in metas
                    ],
                }
            )

        try:
            meta = store_dataset(
                file_path=tmp.name,
                filename=file.filename,
                session_id=session_id,
            )
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
                "var_name": meta["var_name"],
                "is_excel": False,
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
