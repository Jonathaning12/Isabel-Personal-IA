"""Retrieval evaluation: does search find the right document for each golden question?

Indexes tests/fixtures/docs into an in-memory Qdrant using the REAL Nebius embeddings,
then reports recall@k (was the expected document in the top k?) and MRR (how high
it ranked). It never touches your real Qdrant data.

Usage: uv run python scripts/eval_retrieval.py [--k 5]
"""

import argparse
import asyncio
import json
from pathlib import Path

from qdrant_client import AsyncQdrantClient

from assistant.config import get_settings
from assistant.ingest.pipeline import Ingestor
from assistant.llm.client import build_client
from assistant.llm.embeddings import Embedder
from assistant.memory.retrieval import Retriever
from assistant.memory.store import MemoryStore

FIXTURES = Path("tests/fixtures")


async def main(k: int) -> None:
    settings = get_settings()
    settings.retrieval_min_score = 0.0  # measure raw ranking; threshold tuned separately
    embedder = Embedder(build_client(settings), settings)
    store = MemoryStore(AsyncQdrantClient(location=":memory:"), settings.embed_dim)
    await store.ensure_collections()

    ingestor = Ingestor(store, embedder, settings)
    for path in sorted((FIXTURES / "docs").iterdir()):
        await ingestor.ingest(path.name, path.read_bytes())

    retriever = Retriever(store, embedder, settings)
    golden = [json.loads(line) for line in (FIXTURES / "golden.jsonl").read_text().splitlines()]
    hits, reciprocal_ranks = 0, 0.0
    hit_scores, miss_scores = [], []
    print(f"{'#':>2}  {'rank':>4}  {'top score':>9}  pregunta")
    for i, item in enumerate(golden, 1):
        results = await retriever.search(item["question"], k=k)
        sources = [c.source_path for c in results]
        rank = sources.index(item["expected"]) + 1 if item["expected"] in sources else None
        if rank:
            hits += 1
            reciprocal_ranks += 1 / rank
            hit_scores.append(results[rank - 1].score)
        miss_scores += [c.score for c in results if c.source_path != item["expected"]]
        top = results[0].score if results else 0
        print(f"{i:>2}  {rank or '✘':>4}  {top:>9.3f}  {item['question']}")

    n = len(golden)
    print(f"\nrecall@{k} = {hits / n:.2f}   MRR = {reciprocal_ranks / n:.2f}   ({hits}/{n})")
    if hit_scores and miss_scores:
        print(
            f"score of correct docs: min {min(hit_scores):.3f} · "
            f"score of other docs: max {max(miss_scores):.3f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    asyncio.run(main(parser.parse_args().k))
