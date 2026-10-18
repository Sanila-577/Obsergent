"""Deleting the database while the server runs (`make reset-db`) must give empty pages, not HTTP 500."""
import pytest
from fastapi.testclient import TestClient

from agenttrace.server.app import create_app
from agenttrace.storage.sqlite import SQLiteStorage

PAGES = ["/api/traces", "/api/sessions", "/api/servers", "/api/tools", "/api/topology", "/api/stats/overview",
         "/api/findings", "/api/gateway/summary", "/api/models"]


@pytest.fixture
def client_after_reset(tmp_path):
    path = tmp_path / "agenttrace.db"
    client = TestClient(create_app(SQLiteStorage(path)))
    for suffix in ("", "-wal", "-shm"):  # what `make reset-db` does, while the server keeps running
        (tmp_path / f"agenttrace.db{suffix}").unlink(missing_ok=True)
    return client


@pytest.mark.parametrize("page", PAGES)
def test_every_list_endpoint_answers_after_the_file_was_deleted(client_after_reset, page):
    answer = client_after_reset.get(page)
    assert answer.status_code == 200, answer.text


def test_the_lists_are_empty_and_the_counts_zero(client_after_reset):
    assert client_after_reset.get("/api/traces").json() == []
    assert client_after_reset.get("/api/sessions").json() == []
    overview = client_after_reset.get("/api/stats/overview").json()
    assert overview["counts"]["runs"] == 0 and overview["open_findings"] == 0


def test_unknown_runs_are_a_404_not_a_500(client_after_reset):
    assert client_after_reset.get("/api/traces/abc").status_code == 404


def test_the_folder_may_be_gone_too(tmp_path):
    folder = tmp_path / "gone"
    storage = SQLiteStorage(folder / "a.db")
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
    assert storage.list_traces() == []
