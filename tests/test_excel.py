"""Excel multi-sheet ingestion (Phase 3).

Real pandas + openpyxl, isolated tmp SQLite DB (autouse conftest fixture),
data root redirected to tmp.
"""
from pathlib import Path

import pandas as pd
import pytest

import datasets.store as store_module
from datasets.loader import load_excel, sanitize_var_name
from datasets.store import store_excel


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    return root


def _write_xlsx(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return path


def test_load_excel_reads_all_sheets(tmp_path):
    xlsx = _write_xlsx(
        tmp_path / "wb.xlsx",
        {
            "Orders": pd.DataFrame({"id": [1, 2], "amount": [10, 20]}),
            "Customers": pd.DataFrame({"cid": [1], "name": ["a"]}),
        },
    )
    sheets = load_excel(xlsx)
    assert set(sheets) == {"Orders", "Customers"}
    assert list(sheets["Orders"].columns) == ["id", "amount"]


def test_store_excel_two_sheets(tmp_path, data_root):
    xlsx = _write_xlsx(
        tmp_path / "workbook.xlsx",
        {
            "Orders 2024": pd.DataFrame(
                {"id": [1, 2, 3], "amount": [10, 20, 30]}
            ),
            "Customers": pd.DataFrame({"cid": [1, 2], "name": ["a", "b"]}),
        },
    )

    metas = store_excel(file_path=xlsx, filename="workbook.xlsx")

    assert len(metas) == 2
    by_var = {m["var_name"]: m for m in metas}
    assert "orders_2024" in by_var
    assert "customers" in by_var

    orders = by_var["orders_2024"]
    assert orders["filename"] == "workbook.xlsx#Orders 2024"
    assert orders["n_rows"] == 3
    assert orders["n_cols"] == 2
    assert [c["name"] for c in orders["columns"]] == ["id", "amount"]
    assert len(orders["sample_rows"]) <= 5

    # Each sheet has its own parquet with the right rows.
    back = pd.read_parquet(orders["parquet_path"])
    assert len(back) == 3
    assert int(back["amount"].sum()) == 60

    cust = by_var["customers"]
    assert cust["n_rows"] == 2
    assert Path(cust["parquet_path"]).exists()
    assert orders["parquet_path"] != cust["parquet_path"]


def test_store_excel_skips_empty_sheet(tmp_path, data_root):
    xlsx = _write_xlsx(
        tmp_path / "mixed.xlsx",
        {
            "Real": pd.DataFrame({"a": [1, 2]}),
            "Empty": pd.DataFrame({"x": []}),
        },
    )
    metas = store_excel(file_path=xlsx, filename="mixed.xlsx")
    assert len(metas) == 1
    assert metas[0]["var_name"] == "real"


def test_store_excel_all_empty_raises(tmp_path, data_root):
    xlsx = _write_xlsx(
        tmp_path / "blank.xlsx",
        {"Empty": pd.DataFrame({"x": []})},
    )
    with pytest.raises(ValueError):
        store_excel(file_path=xlsx, filename="blank.xlsx")


def test_store_excel_dedupes_var_names(tmp_path, data_root):
    # Two sheets that sanitize to the same var_name.
    xlsx = _write_xlsx(
        tmp_path / "dupe.xlsx",
        {
            "Data 1": pd.DataFrame({"a": [1]}),
            "Data-1": pd.DataFrame({"b": [2]}),
        },
    )
    metas = store_excel(file_path=xlsx, filename="dupe.xlsx")
    names = sorted(m["var_name"] for m in metas)
    assert names == ["data_1", "data_1_2"]


def test_store_excel_links_session(tmp_path, data_root):
    from db.models import SessionRow
    from db.session import create_db_session
    from datasets.store import get_session_datasets

    with create_db_session() as s:
        s.add(SessionRow(id="sess-x", dataset_id="placeholder"))

    xlsx = _write_xlsx(
        tmp_path / "wb.xlsx",
        {
            "First": pd.DataFrame({"a": [1, 2]}),
            "Second": pd.DataFrame({"b": [3]}),
        },
    )
    metas = store_excel(
        file_path=xlsx, filename="wb.xlsx", session_id="sess-x"
    )
    # First sheet linked to a session becomes `df` by convention.
    assert metas[0]["var_name"] == "df"
    assert metas[1]["var_name"] == "second"

    linked = get_session_datasets("sess-x")
    assert [d["var_name"] for d in linked] == ["df", "second"]
