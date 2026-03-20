"""ChromaDB-based RAG store for aircraft manuals and aviation knowledge."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from .sim_client import FlightPhase, SimState

logger = logging.getLogger(__name__)

# Map flight phases to relevant document topics for smarter retrieval
PHASE_TOPICS: dict[FlightPhase, list[str]] = {
    FlightPhase.PREFLIGHT: ["preflight", "checklist", "weight and balance", "fuel planning"],
    FlightPhase.TAXI: ["taxi", "ground operations", "airport diagram"],
    FlightPhase.TAKEOFF: ["takeoff", "departure", "engine failure", "V-speeds", "rejected takeoff"],
    FlightPhase.CLIMB: ["climb", "cruise climb", "engine management", "oxygen"],
    FlightPhase.CRUISE: ["cruise", "fuel management", "navigation", "weather"],
    FlightPhase.DESCENT: ["descent", "approach briefing", "STAR", "altimeter"],
    FlightPhase.APPROACH: ["approach", "ILS", "VOR", "RNAV", "minimums", "go-around"],
    FlightPhase.LANDING: ["landing", "crosswind", "short field", "go-around", "flare"],
    FlightPhase.LANDED: ["after landing", "shutdown", "parking"],
}


class ContextStore:
    """Vector store for aviation documents with flight-phase-aware retrieval."""

    def __init__(self, persist_path: str = "./data/chromadb") -> None:
        self._client = chromadb.PersistentClient(
            path=persist_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="merlin_docs",
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def document_count(self) -> int:
        return self._collection.count()

    async def ingest_document(
        self,
        path: str | Path,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> int:
        """Ingest a text document into the vector store.

        Splits the document into overlapping chunks and stores each with
        metadata for filtered retrieval. Returns the number of chunks ingested.
        """
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        base_meta = {"source": str(path), "filename": path.name}
        if metadata:
            base_meta.update(metadata)

        chunks = self._split_text(text, chunk_size, chunk_overlap)
        if not chunks:
            return 0

        ids = []
        documents = []
        metadatas = []
        for i, chunk in enumerate(chunks):
            doc_hash = hashlib.sha256(f"{path}:{i}".encode()).hexdigest()[:16]
            ids.append(f"{path.stem}_{doc_hash}")
            documents.append(chunk)
            metadatas.append({**base_meta, "chunk_index": i})

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("Ingested %d chunks from %s", len(chunks), path.name)
        return len(chunks)

    async def query(
        self,
        text: str,
        n_results: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query the store and return matching documents with metadata."""
        where = filters if filters else None
        results = self._collection.query(
            query_texts=[text],
            n_results=n_results,
            where=where,
        )

        docs = []
        if results["documents"] and results["metadatas"]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0] if results["distances"] else [0.0] * len(results["documents"][0]),
            ):
                docs.append({"content": doc, "metadata": meta, "distance": dist})
        return docs

    async def get_relevant_context(
        self,
        sim_state: SimState,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve documents relevant to the current aircraft and flight phase."""
        topics = PHASE_TOPICS.get(sim_state.flight_phase, ["general"])
        query_text = f"{sim_state.aircraft_title} {' '.join(topics)}"

        filters = None
        if sim_state.aircraft_title:
            # Try aircraft-specific docs first; fall back to unfiltered if empty
            aircraft_results = await self.query(
                query_text,
                n_results=n_results,
                filters={"aircraft_type": sim_state.aircraft_title},
            )
            if aircraft_results:
                return aircraft_results

        return await self.query(query_text, n_results=n_results, filters=filters)

    @staticmethod
    def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start += chunk_size - overlap
        return chunks
