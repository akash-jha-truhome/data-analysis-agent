"""API contract tests — no LLM key required, the graph is not invoked."""
import io

import pytest


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """Redirect dataset-store writes into tmp so uploads don't touch the repo."""
    import datasets.store as store_module

    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    return root


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_ask_missing_fields_returns_400(api_client):
    r = api_client.post("/ask", json={"dataset_id": "", "question": ""})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_ask_unknown_dataset_returns_400(api_client):
    r = api_client.post("/ask", json={"dataset_id": "nope", "question": "total x"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNKNOWN_DATASET"


def test_get_run_not_found_returns_404(api_client):
    r = api_client.get("/runs/does-not-exist")
    assert r.status_code == 404


def test_get_dataset_not_found_returns_404(api_client):
    r = api_client.get("/datasets/does-not-exist")
    assert r.status_code == 404


def test_upload_no_file_returns_422(api_client):
    # FastAPI rejects a missing required multipart field with 422.
    r = api_client.post("/datasets")
    assert r.status_code == 422


def test_upload_empty_file_returns_400(api_client, data_root):
    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400


def test_upload_unparseable_csv_returns_400(api_client, data_root):
    files = {"file": ("header.csv", io.BytesIO(b"a,b,c\n"), "text/csv")}  # header, no rows
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400


def test_upload_then_fetch_dataset_round_trip(api_client, data_root):
    csv = b"region,revenue\nWest,1200.5\nEast,980.0\n"
    files = {"file": ("sales.csv", io.BytesIO(csv), "text/csv")}
    up = api_client.post("/datasets", files=files)
    assert up.status_code == 200
    data = up.json()["data"]
    assert data["n_rows"] == 2
    assert data["n_cols"] == 2
    assert [c["name"] for c in data["columns"]] == ["region", "revenue"]
    assert len(data["sample_rows"]) == 2
    dataset_id = data["dataset_id"]

    got = api_client.get(f"/datasets/{dataset_id}")
    assert got.status_code == 200
    assert got.json()["data"]["dataset_id"] == dataset_id
    assert got.json()["data"]["n_rows"] == 2
