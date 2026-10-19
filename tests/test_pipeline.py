import json

import pytest
from fastapi.testclient import TestClient

from app.core import Library, Settings, chunks, extract
from app.main import create_app


@pytest.fixture
def library(tmp_path):
    lib = Library(Settings(data_dir=str(tmp_path), _env_file=None))
    yield lib
    lib.close()


def test_ingest_isolation_delete_duplicate(library):
    a, b = library.create("A")["id"], library.create("B")["id"]
    data = b"# API\n\nSSE sends events over HTTP.\n\nSQL stores records."
    doc = library.ingest(a, "guide.md", data)
    library.process(doc["id"])
    assert library.ingest(a, "copy.md", data)["duplicate"]
    hits = library.search(a, "SSE")
    assert hits and "SSE" in hits[0]["text"]
    assert library.search(b, "SSE") == []
    library.delete(doc["id"])
    assert library.search(a, "SSE") == []
    assert library.vector.count(library.collection).count == 0


def test_failure_retry_and_validation(library):
    kb = library.create("A")["id"]
    doc = library.ingest(kb, "empty.txt", b" ")
    library.process(doc["id"])
    assert library.rows("SELECT status FROM documents")[0]["status"] == "failed"
    library.execute("UPDATE documents SET source=? WHERE id=?", (b"Recovered text", doc["id"]))
    library.process(doc["id"])
    assert library.rows("SELECT status FROM documents")[0]["status"] == "ready"
    with pytest.raises(ValueError):
        extract(b"hello", "bad.exe")
    with pytest.raises(ValueError):
        library.ingest("missing", "x.txt", b"x")


def test_headings_and_overlap():
    result = chunks([(2, "# Heading\n\n" + "a" * 1400)])
    assert result[0]["heading"] == "Heading"
    assert result[0]["page"] == 2
    assert result[0]["text"][-150:] == result[1]["text"][:150]


def test_stream_citations_and_no_answer(tmp_path):
    with TestClient(create_app(Settings(data_dir=str(tmp_path), _env_file=None))) as client:
        kb = client.post("/api/libraries", json={"name": "Demo"}).json()["id"]
        client.post(f"/api/libraries/{kb}/documents", files={"file": ("sse.md", b"SSE streams events.")})
        response = client.post(f"/api/libraries/{kb}/chat", json={"question": "SSE"})
        assert "event: sources" in response.text and "[1]" in response.text
        payloads = [json.loads(x[6:]) for x in response.text.splitlines() if x.startswith("data: ")]
        assert payloads[-1]["citations_valid"] is True
        empty = client.post("/api/libraries", json={"name": "Empty"}).json()["id"]
        assert "无法回答" in client.post(f"/api/libraries/{empty}/chat", json={"question": "x"}).text
        assert (
            client.post(
                f"/api/libraries/{kb}/search", json={"question": "SSE", "strategy": "rerank"}
            ).status_code
            == 400
        )
