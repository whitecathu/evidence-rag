"""Load the original sample handbook into a running API without sharing a Qdrant lock."""

from pathlib import Path

import httpx

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120, trust_env=False) as client:
    response = client.post("/api/libraries", json={"name": "Atlas 技术手册"})
    response.raise_for_status()
    kb = response.json()["id"]
    for path in sorted((Path(__file__).resolve().parents[1] / "examples/docs").glob("*.md")):
        result = client.post(f"/api/libraries/{kb}/documents", files={"file": (path.name, path.read_bytes())})
        result.raise_for_status()
    print(f"Uploaded 10 documents to library {kb}. Processing status is visible in the UI.")
