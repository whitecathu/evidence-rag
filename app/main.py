from __future__ import annotations

import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core import Library, Settings


class NewLibrary(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    strategy: Literal["vector", "hybrid", "rerank"] = "hybrid"


def create_app(settings: Settings | None = None):
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.library = Library(config)
        yield
        app.state.library.close()

    app = FastAPI(title="Evidence RAG", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "demo" if config.demo_mode else "live"}

    @app.get("/api/libraries")
    def libraries():
        return app.state.library.rows("SELECT * FROM libraries ORDER BY rowid DESC")

    @app.post("/api/libraries", status_code=201)
    def create(body: NewLibrary):
        return app.state.library.create(body.name)

    @app.get("/api/libraries/{kb}/documents")
    def documents(kb: str):
        return app.state.library.rows("SELECT id,name,status,error FROM documents WHERE kb=?", (kb,))

    @app.post("/api/libraries/{kb}/documents", status_code=202)
    async def upload(kb: str, tasks: BackgroundTasks, file: UploadFile = File(...)):
        data = await file.read(10 * 1024 * 1024 + 1)
        try:
            result = app.state.library.ingest(kb, file.filename or "untitled.txt", data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not result["duplicate"]:
            tasks.add_task(app.state.library.process, result["id"])
        return result

    @app.post("/api/documents/{doc}/retry")
    def retry(doc: str, tasks: BackgroundTasks):
        rows = app.state.library.rows("SELECT status FROM documents WHERE id=?", (doc,))
        if not rows:
            raise HTTPException(404, "文档不存在")
        tasks.add_task(app.state.library.process, doc)
        return {"status": "scheduled"}

    @app.delete("/api/documents/{doc}", status_code=204)
    def delete(doc: str):
        app.state.library.delete(doc)

    @app.post("/api/libraries/{kb}/search")
    def search(kb: str, body: Question):
        try:
            return app.state.library.search(kb, body.question, body.strategy)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/libraries/{kb}/chat")
    def chat(kb: str, body: Question):
        def stream():
            started = time.perf_counter()

            def event(name, data):
                return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

            try:
                evidence = app.state.library.search(kb, body.question, body.strategy)
                yield event("sources", evidence)
                answer = ""
                for text in app.state.library.answer(body.question, evidence):
                    answer += text
                    yield event("token", {"text": text})
                citations = [int(x) for x in re.findall(r"\[(\d+)\]", answer)]
                yield event(
                    "done",
                    {
                        "mode": "demo" if config.demo_mode else "live",
                        "elapsed_ms": round((time.perf_counter() - started) * 1000),
                        "citations_valid": all(1 <= x <= len(evidence) for x in citations),
                        "cited_sources": sorted(set(citations)),
                    },
                )
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                yield event("error", {"message": message})

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
