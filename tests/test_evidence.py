import json

from fastapi.testclient import TestClient

from app.core import Settings
from app.main import create_app


def test_invalid_citations_are_flagged(tmp_path, monkeypatch):
    with TestClient(create_app(Settings(data_dir=str(tmp_path), _env_file=None))) as client:
        lib = client.app.state.library
        kb = lib.create("test")["id"]
        doc = lib.ingest(kb, "test.txt", b"SSE streams events.")
        lib.process(doc["id"])
        monkeypatch.setattr(lib, "answer", lambda *args: iter(["Answer [99]"]))
        result = client.post(f"/api/libraries/{kb}/chat", json={"question": "SSE"}).text
        data = [json.loads(line[6:]) for line in result.splitlines() if line.startswith("data: ")]
        assert data[-1]["citations_valid"] is False


def test_generation_error_is_explicit(tmp_path, monkeypatch):
    with TestClient(create_app(Settings(data_dir=str(tmp_path), _env_file=None))) as client:

        def broken(*args):
            raise ValueError("Provider unavailable")

        monkeypatch.setattr(client.app.state.library, "answer", broken)
        result = client.post("/api/libraries/empty/chat", json={"question": "SSE"}).text
        assert "event: error" in result
        assert "event: done" not in result
        assert "非模型生成" not in result


def test_dataset_has_60_grounded_questions():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dataset = json.loads((root / "evals/questions.json").read_text(encoding="utf-8"))
    assert len(dataset["questions"]) == 60
    assert len({q["id"] for q in dataset["questions"]}) == 60
    for question in dataset["questions"]:
        for evidence in question["evidence"]:
            text = (root / "examples/docs" / evidence["document"]).read_text(encoding="utf-8")
            assert evidence["text"] in text
