"""Dataset ingestion + audit persistence — slice-data.

Uses an isolated tmp SQLite DB (via the autouse ``_isolated_db`` conftest
fixture) and redirects the on-disk data root into tmp. Real pandas, no stubs.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

import datasets.store as store_module
import observability.audit_log as audit_module
from datasets.loader import load_csv, profile_dataframe, write_parquet
from datasets.store import get_dataset_meta, store_dataset
from observability.audit_log import append_audit


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """Redirect the dataset store + audit log writes into a tmp data root."""
    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    monkeypatch.setattr(audit_module, "_data_root", lambda: root)
    return root


def _write_csv(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_store_dataset_round_trip(tmp_path, data_root):
    csv = _write_csv(
        tmp_path / "sales.csv",
        [
            {"region": "north", "amount": 10, "note": "a"},
            {"region": "south", "amount": 20, "note": "b"},
            {"region": "east", "amount": 30, "note": "c"},
        ],
    )

    meta = store_dataset(file_path=csv, filename="sales.csv")

    assert meta["filename"] == "sales.csv"
    assert meta["n_rows"] == 3
    assert meta["n_cols"] == 3
    col_names = [c["name"] for c in meta["columns"]]
    assert col_names == ["region", "amount", "note"]
    assert all("dtype" in c for c in meta["columns"])
    assert len(meta["sample_rows"]) <= 5
    assert len(meta["sample_rows"]) == 3

    # Files persisted on disk.
    ds_dir = data_root / "datasets" / meta["dataset_id"]
    assert (ds_dir / "original.csv").exists()
    parquet = Path(meta["parquet_path"])
    assert parquet.exists()
    assert parquet == ds_dir / "data.parquet"

    # DatasetRow round-trips with the same shape.
    fetched = get_dataset_meta(meta["dataset_id"])
    assert fetched is not None
    assert fetched["dataset_id"] == meta["dataset_id"]
    assert fetched["n_rows"] == 3
    assert fetched["n_cols"] == 3
    assert fetched["columns"] == meta["columns"]
    assert fetched["sample_rows"] == meta["sample_rows"]
    assert fetched["parquet_path"] == meta["parquet_path"]


def test_get_dataset_meta_unknown_returns_none(data_root):
    assert get_dataset_meta("does-not-exist") is None


def test_profile_caps_sample_rows_and_is_json_serializable(tmp_path):
    df = pd.DataFrame(
        {
            "x": list(range(20)),
            "y": [float("nan") if i % 2 else i * 1.5 for i in range(20)],
            "label": [f"row-{i}" for i in range(20)],
        }
    )

    profile = profile_dataframe(df, sample_rows=5)

    assert profile["n_rows"] == 20
    assert profile["n_cols"] == 3
    assert len(profile["sample_rows"]) == 5

    # NaN must be coerced to None and the whole payload must serialize cleanly.
    dumped = json.dumps(profile)
    reloaded = json.loads(dumped)
    # y at index 1 was NaN -> None
    assert reloaded["sample_rows"][1]["y"] is None


def test_full_parquet_persists_all_rows_not_just_sample(tmp_path, data_root):
    """A 60k-row CSV whose full column sum != the sample-row sum.

    Proves the parquet holds the entire dataset for the sandbox, not the
    sample shown to the LLM.
    """
    n = 60_000
    df = pd.DataFrame({"v": [1] * n})
    # Make the head (first 5) unrepresentative of the whole.
    df.loc[:4, "v"] = 0
    csv = tmp_path / "big.csv"
    df.to_csv(csv, index=False)

    meta = store_dataset(file_path=csv, filename="big.csv")
    assert meta["n_rows"] == n

    sample_sum = sum(r["v"] for r in meta["sample_rows"])
    full_sum = int(df["v"].sum())
    assert sample_sum == 0  # first 5 rows are all zero
    assert full_sum == n - 5  # the rest are ones
    assert sample_sum != full_sum

    back = pd.read_parquet(meta["parquet_path"])
    assert len(back) == n
    assert int(back["v"].sum()) == full_sum


def test_store_dataset_empty_csv_raises_value_error(tmp_path, data_root):
    empty = tmp_path / "empty.csv"
    empty.write_text("")  # no header, no data
    with pytest.raises(ValueError):
        store_dataset(file_path=empty, filename="empty.csv")


def test_store_dataset_header_only_csv_raises_value_error(tmp_path, data_root):
    header_only = tmp_path / "header.csv"
    header_only.write_text("a,b,c\n")
    with pytest.raises(ValueError):
        store_dataset(file_path=header_only, filename="header.csv")


def test_load_csv_garbage_raises_value_error(tmp_path):
    garbage = tmp_path / "garbage.bin"
    garbage.write_bytes(b"\x00\x01\x02\xff\xfe not a csv \x00")
    with pytest.raises(ValueError):
        load_csv(garbage)


def test_write_parquet_creates_parent_dirs(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3]})
    target = tmp_path / "nested" / "deeper" / "data.parquet"
    write_parquet(df, target)
    assert target.exists()
    assert len(pd.read_parquet(target)) == 3


def test_append_audit_writes_json_lines_and_is_repeat_safe(data_root):
    append_audit({"run_id": "r1", "status": "completed", "tokens": 42})
    append_audit({"run_id": "r2", "status": "failed", "error": "boom"})

    log_path = data_root / "audit.log"
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["run_id"] == "r1"
    assert second["status"] == "failed"


def test_append_audit_never_raises_on_bad_io(monkeypatch):
    # Point the audit path at a location whose parent can't be created.
    monkeypatch.setattr(audit_module, "_data_root", lambda: Path("/dev/null/nope"))
    # Must swallow the error, not raise.
    append_audit({"run_id": "x"})


def test_append_audit_serializes_non_native_values(data_root):
    # Non-JSON-native values (e.g. a Path) must not blow up thanks to default=str.
    append_audit({"run_id": "r3", "path": Path("/tmp/foo"), "n": 1})
    log_path = data_root / "audit.log"
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec["run_id"] == "r3"
