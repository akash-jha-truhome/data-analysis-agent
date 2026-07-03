"""Multi-file (multi-dataset) sessions + var_name convention (Phase 3).

Real pandas, isolated tmp SQLite DB (autouse conftest fixture), data root
redirected to tmp.
"""
from pathlib import Path

import pandas as pd
import pytest

import datasets.store as store_module
from datasets.loader import sanitize_var_name
from datasets.store import (
    get_session_datasets,
    link_dataset_to_session,
    store_dataset,
)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    return root


def _write_csv(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _make_session(session_id: str) -> None:
    from db.models import SessionRow
    from db.session import create_db_session

    with create_db_session() as s:
        s.add(SessionRow(id=session_id, dataset_id="placeholder"))


# --- sanitize_var_name edge cases ---------------------------------------


def test_sanitize_var_name_edge_cases():
    assert sanitize_var_name("Orders 2024.csv") == "orders_2024"
    assert sanitize_var_name("  weird!!name??.csv ") == "weird_name"
    assert sanitize_var_name("2020data") == "col_2020data"
    assert sanitize_var_name("class") == "class_"  # python keyword
    assert sanitize_var_name("") == "dataset"
    assert sanitize_var_name("...") == "dataset"
    # Result is always a valid identifier and lowercase.
    for raw in ["9 Lives", "café_data", "def", "a-b-c.xlsx"]:
        out = sanitize_var_name(raw)
        assert out.isidentifier()
        assert out == out.lower()


# --- store_dataset now includes var_name --------------------------------


def test_store_dataset_includes_var_name(tmp_path, data_root):
    csv = _write_csv(tmp_path / "Orders 2024.csv", [{"a": 1}, {"a": 2}])
    meta = store_dataset(file_path=csv, filename="Orders 2024.csv")
    assert meta["var_name"] == "orders_2024"


def test_store_dataset_single_file_session_var_name_is_df(tmp_path, data_root):
    _make_session("sess-single")
    csv = _write_csv(tmp_path / "Orders 2024.csv", [{"a": 1}, {"a": 2}])
    meta = store_dataset(
        file_path=csv, filename="Orders 2024.csv", session_id="sess-single"
    )
    # Convention: first (only) dataset in a session is `df`.
    assert meta["var_name"] == "df"


# --- multi-file linking -------------------------------------------------


def test_multi_file_linking(tmp_path, data_root):
    _make_session("sess-1")

    csv_a = _write_csv(
        tmp_path / "orders.csv",
        [{"region": "n", "amount": 10}, {"region": "s", "amount": 20}],
    )
    csv_b = _write_csv(
        tmp_path / "Customers 2024.csv",
        [{"cid": 1, "name": "a"}, {"cid": 2, "name": "b"}, {"cid": 3, "name": "c"}],
    )

    meta_a = store_dataset(
        file_path=csv_a, filename="orders.csv", session_id="sess-1"
    )
    meta_b = store_dataset(
        file_path=csv_b, filename="Customers 2024.csv", session_id="sess-1"
    )

    assert meta_a["var_name"] == "df"  # first
    assert meta_b["var_name"] == "customers_2024"  # sanitized

    linked = get_session_datasets("sess-1")
    assert len(linked) == 2
    # Ordered by link creation.
    assert linked[0]["var_name"] == "df"
    assert linked[1]["var_name"] == "customers_2024"
    assert linked[0]["dataset_id"] == meta_a["dataset_id"]
    assert linked[1]["dataset_id"] == meta_b["dataset_id"]

    # Schemas + sample rows + parquet paths per dataset.
    first = linked[0]
    assert [c["name"] for c in first["columns"]] == ["region", "amount"]
    assert len(first["sample_rows"]) <= 5
    assert Path(first["parquet_path"]).exists()

    second = linked[1]
    assert [c["name"] for c in second["columns"]] == ["cid", "name"]
    assert len(second["sample_rows"]) == 3
    assert second["parquet_path"] != first["parquet_path"]
    back = pd.read_parquet(second["parquet_path"])
    assert len(back) == 3


def test_link_dataset_to_session_idempotent(tmp_path, data_root):
    _make_session("sess-idem")
    csv = _write_csv(tmp_path / "d.csv", [{"a": 1}])
    meta = store_dataset(file_path=csv, filename="d.csv")

    v1 = link_dataset_to_session("sess-idem", meta["dataset_id"], "df")
    v2 = link_dataset_to_session("sess-idem", meta["dataset_id"], "df")
    assert v1 == v2 == "df"
    assert len(get_session_datasets("sess-idem")) == 1


def test_link_dataset_disambiguates_var_name(tmp_path, data_root):
    _make_session("sess-collide")
    a = store_dataset(
        file_path=_write_csv(tmp_path / "a.csv", [{"x": 1}]), filename="a.csv"
    )
    b = store_dataset(
        file_path=_write_csv(tmp_path / "b.csv", [{"y": 1}]), filename="b.csv"
    )
    c = store_dataset(
        file_path=_write_csv(tmp_path / "c.csv", [{"z": 1}]), filename="c.csv"
    )

    # First -> df (convention), then two collisions on "sales".
    assert link_dataset_to_session("sess-collide", a["dataset_id"], "sales") == "df"
    assert link_dataset_to_session("sess-collide", b["dataset_id"], "sales") == "sales"
    assert (
        link_dataset_to_session("sess-collide", c["dataset_id"], "sales")
        == "sales_2"
    )


def test_get_session_datasets_empty():
    assert get_session_datasets("no-such-session") == []


# --- POST /datasets response shapes -------------------------------------


def test_post_datasets_csv_shape(tmp_path, data_root, api_client):
    csv = _write_csv(tmp_path / "orders.csv", [{"a": 1}, {"a": 2}])
    with open(csv, "rb") as fh:
        resp = api_client.post(
            "/datasets", files={"file": ("orders.csv", fh, "text/csv")}
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # P1/P2 top-level keys preserved.
    for key in ["dataset_id", "filename", "n_rows", "n_cols", "columns", "sample_rows"]:
        assert key in data
    # Additive Phase 3 keys.
    assert data["is_excel"] is False
    assert data["var_name"] == "orders"


def test_post_datasets_excel_shape(tmp_path, data_root, api_client):
    xlsx = tmp_path / "wb.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="Orders", index=False)
        pd.DataFrame({"b": [3]}).to_excel(writer, sheet_name="Customers", index=False)

    with open(xlsx, "rb") as fh:
        resp = api_client.post(
            "/datasets",
            files={
                "file": (
                    "wb.xlsx",
                    fh,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["is_excel"] is True
    assert len(data["datasets"]) == 2
    var_names = {d["var_name"] for d in data["datasets"]}
    assert var_names == {"orders", "customers"}
    for d in data["datasets"]:
        for key in ["dataset_id", "filename", "n_rows", "n_cols", "columns", "sample_rows", "var_name"]:
            assert key in d
