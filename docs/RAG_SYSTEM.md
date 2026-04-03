# RAG System

The retrieval-augmented generation (RAG) system provides MERLIN with access to aircraft manuals, FAA publications, checklists, and other aviation documents. v2 upgrades the pipeline with semantic chunking, cross-encoder re-ranking, and enhanced metadata filtering.

Source files:
- `orchestrator/orchestrator/chunking.py` -- Aviation-aware semantic chunking
- `orchestrator/orchestrator/reranker.py` -- Cross-encoder re-ranking
- `orchestrator/orchestrator/context_store.py` -- ChromaDB vector store with query cache

---

## Architecture Overview

```
Document Ingestion:
  File on disk
    --> AviationChunker (structure-aware splitting)
    --> ChromaDB upsert (with enhanced metadata)

Query Pipeline:
  Query text + filters
    --> Check _QueryCache (TTL 60s, invalidated on phase change)
    --> [cache miss] ChromaDB vector search (top-K candidates, K=20)
    --> CrossEncoderReranker (re-score and sort, return top-N, N=5)
    --> Cache result
    --> Return to Claude as context
```

---

## Semantic Chunking

The `AviationChunker` replaces naive character-based splitting with structure-aware chunking that preserves the integrity of aviation document elements.

### Design Principles

1. **Checklist items are atomic** -- A checklist step is never split across chunks.
2. **Procedure steps are atomic** -- Multi-line procedure entries stay together.
3. **Section boundaries are respected** -- Chunks do not cross section headings.
4. **Paragraphs are preferred split points** -- For prose text, paragraph boundaries are used before falling back to sentence boundaries.

### Section Detection

The chunker identifies section boundaries using these patterns:

| Pattern | Example |
|---|---|
| Markdown headings (`# `, `## `, etc.) | `## Normal Procedures` |
| `SECTION N` / `CHAPTER N` | `SECTION 4` |
| Numbered subsections (`N.N UPPERCASE`) | `4.1 Engine Starting` |
| Divider lines (`===` or `---`) | `----------` |
| Aviation section keywords | `LIMITATIONS`, `EMERGENCY PROCEDURES`, `PERFORMANCE` |

Text is split into `(title, body)` tuples at these boundaries. Each section is then chunked independently.

### List Block Detection

A text block is classified as a list/checklist if >= 50% of its lines match list item patterns:

- Numbered items: `1.`, `1)`, `A.`, `A)`
- Bullet points: `-`, `*`, bullet character
- Step format: `Step 1`, `Step 2`

List blocks under `max_chunk_chars` are kept as a single atomic chunk.

### Chunking Parameters

| Parameter | Default | Description |
|---|---|---|
| `max_chunk_chars` | 1,500 | Maximum characters per chunk |
| `min_chunk_chars` | 100 | Minimum characters (smaller chunks are discarded) |
| `overlap_chars` | 100 | Overlap between consecutive chunks for context continuity |

### Chunking Algorithm

For each section:

1. If the section fits within `max_chunk_chars`, emit it as a single chunk.
2. Otherwise, split by double-newline (paragraphs).
3. For each paragraph:
   - If it is a list block and fits within `max_chunk_chars`, keep it atomic.
   - If it exceeds `max_chunk_chars`, split at sentence boundaries.
4. Merge adjacent small blocks until reaching `max_chunk_chars`.
5. When splitting, carry `overlap_chars` from the end of the previous chunk into the start of the next, beginning at a word boundary.

### Chunk Output

Each chunk is a `Chunk` dataclass with:

```python
@dataclass
class Chunk:
    text: str
    metadata: dict[str, Any]  # section, chunk_index, plus base metadata
```

### Usage

```python
from orchestrator.chunking import chunk_document

chunks = chunk_document(
    text=document_text,
    metadata={
        "document_type": "poh",
        "aircraft_type": "C172",
        "aircraft_variant": "C172S",
    },
)
# Returns: list[Chunk]
```

---

## Cross-Encoder Re-Ranking

The `CrossEncoderReranker` implements a two-stage retrieval pipeline that dramatically improves precision for factual aviation queries.

### Why Re-Ranking

Bi-encoder similarity search (ChromaDB's default) is fast but approximate. It maps queries and documents independently to embedding vectors and compares them by cosine distance. This works well for topical relevance but can rank a document about "Cessna 172 cruise speed" higher than one about "Cessna 172 Vne" when the query is about speed limits.

Cross-encoders process the query and document **together**, allowing attention across both inputs. This produces much more accurate relevance scores but is too slow to run against the full collection. The two-stage approach gets the best of both:

1. **Stage 1**: Retrieve K=20 candidates from ChromaDB by vector similarity (fast, recall-oriented).
2. **Stage 2**: Re-rank those 20 candidates with the cross-encoder, return the top N=5 (precise, precision-oriented).

### Model

The default model is `cross-encoder/ms-marco-MiniLM-L-6-v2` from the sentence-transformers library. It is loaded lazily on first use to avoid startup overhead when re-ranking is not needed.

### Graceful Degradation

- If `sentence-transformers` is not installed, re-ranking is disabled and the original ChromaDB order is used.
- If the model fails to load, re-ranking is disabled for the session.
- If a re-ranking call fails at runtime, the original document order (truncated to `top_n`) is returned.

### Usage

```python
from orchestrator.reranker import CrossEncoderReranker

reranker = CrossEncoderReranker()
reranked = reranker.rerank(
    query="What is the Vne for a Cessna 172?",
    documents=[{"content": "...", "metadata": {...}}, ...],
    top_n=5,
)
# Each document gets a "rerank_score" field added
```

---

## Enhanced Metadata

The v2 context store supports five metadata fields for filtered retrieval:

| Field | Description | Example Values |
|---|---|---|
| `document_type` | Type of aviation document | `poh`, `checklist`, `aim`, `regulation` |
| `section` | Section within the document | `systems`, `limitations`, `procedures`, `performance` |
| `aircraft_type` | Aircraft type code | `C172`, `B738`, `A320` |
| `aircraft_variant` | Specific variant | `C172S`, `737-800`, `A320neo` |
| `source_page` | Page number in the source document | `42` |

These fields are set during ingestion and can be used as ChromaDB `where` filters during queries. The `get_relevant_context()` method automatically filters by `aircraft_type` when the sim state includes an aircraft identifier.

---

## Ingestion Pipeline

### Ingesting a Document

```python
store = ContextStore(chromadb_url="http://localhost:8000")

count = await store.ingest_document(
    path="data/manuals/c172s_poh.txt",
    metadata={
        "document_type": "poh",
        "aircraft_type": "C172",
        "aircraft_variant": "C172S",
    },
)
print(f"Ingested {count} chunks")
```

### What Happens During Ingestion

1. The file is read as UTF-8 text.
2. The `AviationChunker` splits it into structure-aware chunks with metadata.
3. Each chunk gets a deterministic ID based on `sha256(path:index)`.
4. Chunks are upserted into the `merlin_docs` ChromaDB collection (cosine distance).
5. Metadata values are filtered to ChromaDB-compatible types (str, int, float, bool).

### Bulk Ingestion Tool

The `tools/ingest.py` script handles bulk ingestion of document directories. See the script for usage.

---

## Query Pipeline

### Standard Query

```python
results = await store.query(
    text="What is the maximum crosswind component for landing?",
    n_results=5,
    filters={"aircraft_type": "C172"},
    phase=FlightPhase.LANDING,
)
```

### Query Flow

1. **Cache check**: The query is hashed with `(text, n_results, filters)` and checked against the in-memory cache. Cache entries expire after 60 seconds or when the flight phase changes.

2. **Vector retrieval**: On cache miss, ChromaDB is queried for `retrieve_k` (default 20) candidates using cosine similarity on the query embedding.

3. **Re-ranking**: If the cross-encoder is available and more candidates were retrieved than requested, the candidates are re-ranked. Each candidate gets a `rerank_score` field. The top `n_results` (default 5) are returned.

4. **Cache store**: Results are cached for subsequent identical queries within the same flight phase.

### Flight-Phase-Aware Retrieval

The `get_relevant_context()` method builds queries tuned to the current flight phase:

| Phase | Topic Keywords |
|---|---|
| PREFLIGHT | preflight, checklist, weight and balance, fuel planning |
| TAXI | taxi, ground operations, airport diagram |
| TAKEOFF | takeoff, departure, engine failure, V-speeds, rejected takeoff |
| CLIMB | climb, cruise climb, engine management, oxygen |
| CRUISE | cruise, fuel management, navigation, weather |
| DESCENT | descent, approach briefing, STAR, altimeter |
| APPROACH | approach, ILS, VOR, RNAV, minimums, go-around |
| LANDING | landing, crosswind, short field, go-around, flare |
| LANDED | after landing, shutdown, parking |

The query text is constructed as `"{aircraft} {topics}"` and first attempts a filtered query by `aircraft_type`. If no aircraft-specific results are found, it falls back to an unfiltered query.

### Cache Behavior

- **Key**: SHA-256 hash of `text|n_results|sorted(filters)`, truncated to 24 characters.
- **TTL**: 60 seconds (configurable via `_CACHE_TTL`).
- **Phase invalidation**: When the flight phase changes, the entire cache is cleared. Within a single phase, the relevant documents rarely change, so the generous TTL avoids redundant ChromaDB round-trips.

---

## Configuration

The context store accepts these constructor parameters:

| Parameter | Default | Description |
|---|---|---|
| `chromadb_url` | `http://localhost:8000` | ChromaDB server URL |
| `enable_reranking` | `True` | Enable cross-encoder re-ranking |
| `retrieve_k` | `20` | Number of candidates to retrieve from ChromaDB |
| `rerank_top_n` | `5` | Number of results to return after re-ranking |

ChromaDB runs as a Docker container. The URL is configured via the `CHROMADB_URL` environment variable (see `docs/CONFIGURATION.md`).
