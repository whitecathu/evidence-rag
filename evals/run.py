"""Reproducible retrieval ablation; no fixture numbers passed off as live scores."""

import argparse
import hashlib
import json
import platform
import re
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core import Library, Settings

ROOT = Path(__file__).resolve().parents[1]


def evaluate(library, kb, questions, strategy):
    results = []
    for item in questions:
        started = time.perf_counter()
        hits = library.search(kb, item["question"], strategy)
        required = item["evidence"]
        found = [
            any(hit["name"] == e["document"] and e["text"] in hit["text"] for hit in hits) for e in required
        ]
        first = next(
            (
                i
                for i, hit in enumerate(hits, 1)
                if any(hit["name"] == e["document"] and e["text"] in hit["text"] for e in required)
            ),
            None,
        )
        results.append(
            {
                "id": item["id"],
                "category": item["category"],
                "recall_at_5": sum(found) / len(found) if found else None,
                "reciprocal_rank_at_5": 1 / first if first else (0 if required else None),
                "retrieved": [h["name"] for h in hits],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    scored = [r for r in results if r["recall_at_5"] is not None]
    latency = sorted(r["latency_ms"] for r in results)
    return {
        "strategy": strategy,
        "answerable_count": len(scored),
        "recall_at_5": statistics.mean(r["recall_at_5"] for r in scored),
        "mrr_at_5": statistics.mean(r["reciprocal_rank_at_5"] for r in scored),
        "latency_p50_ms": statistics.median(latency),
        "latency_p95_ms": latency[int(0.95 * (len(latency) - 1))],
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Explicitly allow embedding API calls")
    parser.add_argument("--rerank", action="store_true", help="Also evaluate configured rerank endpoint")
    parser.add_argument(
        "--answers", action="store_true", help="Collect real generated answers for manual evidence review"
    )
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--output", default="artifacts/retrieval.json")
    args = parser.parse_args()
    config = Settings()
    if not 1 <= args.limit <= 60:
        parser.error("limit must be 1..60")
    if args.answers and (not args.live or not config.llm_api_key or not config.llm_model):
        parser.error("--answers requires --live and configured LLM_API_KEY / LLM_MODEL")
    if args.live and (not config.embedding_api_key or not config.embedding_model):
        parser.error("Live evaluation requires EMBEDDING_API_KEY and EMBEDDING_MODEL")
    dataset_bytes = (ROOT / "evals/questions.json").read_bytes()
    dataset = json.loads(dataset_bytes)
    questions = dataset["questions"][: args.limit]
    answers = []
    with tempfile.TemporaryDirectory() as folder:
        config.data_dir = folder
        config.qdrant_url = ""  # Isolate evaluation from the user's persistent index.
        config.demo_mode = not args.live
        library = Library(config)
        try:
            kb = library.create("Evaluation")["id"]
            for path in sorted((ROOT / "examples/docs").glob("*.md")):
                document = library.ingest(kb, path.name, path.read_bytes())
                library.process(document["id"])
            failures = library.rows("SELECT name,error FROM documents WHERE status!='ready'")
            if failures:
                raise RuntimeError(f"Indexing failed: {failures}")
            strategies = ["vector", "hybrid"] + (["rerank"] if args.rerank else [])
            results = [evaluate(library, kb, questions, strategy) for strategy in strategies]
            if args.answers:
                for item in questions:
                    evidence = library.search(kb, item["question"], "hybrid")
                    answer = "".join(library.answer(item["question"], evidence))
                    cited = [int(x) for x in re.findall(r"\[(\d+)\]", answer)]
                    answers.append(
                        {
                            "id": item["id"],
                            "question": item["question"],
                            "answer": answer,
                            "sources": evidence,
                            "expected_answerable": bool(item["evidence"]),
                            "citation_numbers_valid": all(1 <= x <= len(evidence) for x in cited),
                            "semantic_support": "requires_manual_review",
                            "refusal_correct": "requires_manual_review",
                        }
                    )
        finally:
            library.close()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)
    report = {
        "mode": "live_embeddings" if args.live else "demo_hash_embeddings",
        "not_an_answer_quality_benchmark": True,
        "generation_and_refusal_evaluation": "collected_for_manual_review" if args.answers else "not_run",
        "answers": answers,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit.stdout.strip() or "uncommitted",
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_version": dataset["version"],
        "model": config.embedding_model if args.live else "sha256-192-demo",
        "python": platform.python_version(),
        "question_count": len(questions),
        "ablations": results,
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"mode": report["mode"], "questions": report["question_count"], "output": str(target)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
