"""Semantic chunking for aviation documents.

Replaces naive character-based splitting with structure-aware chunking
that preserves checklist items, procedure steps, and limitation entries
as atomic units. Falls back to paragraph/sentence boundaries for prose.

Usage:
    from orchestrator.chunking import chunk_document, AviationChunker

    chunks = chunk_document(text, metadata={"document_type": "poh"})
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A single chunk of text with metadata."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)


# ---------------------------------------------------------------------------
# Section boundary detection
# ---------------------------------------------------------------------------

# Patterns that start a new section in aviation documents
_SECTION_PATTERNS = [
    re.compile(r"^#{1,4}\s+.+", re.MULTILINE),  # Markdown headings
    re.compile(r"^SECTION\s+\d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^CHAPTER\s+\d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\d+\.\d+\s+[A-Z]", re.MULTILINE),  # Numbered subsections
    re.compile(r"^={3,}$", re.MULTILINE),  # === dividers
    re.compile(r"^-{3,}$", re.MULTILINE),  # --- dividers
    re.compile(
        r"^(?:NORMAL\s+PROCEDURES|EMERGENCY\s+PROCEDURES|LIMITATIONS|PERFORMANCE"
        r"|WEIGHT\s+AND\s+BALANCE|GENERAL|SYSTEMS)",
        re.MULTILINE | re.IGNORECASE,
    ),
]

# Patterns that indicate a checklist or procedure list item
_LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"\d+[.)]\s+"  # 1. or 1)
    r"|[-*•]\s+"  # bullet points
    r"|[A-Z][.)]\s+"  # A. or A)
    r"|(?:Step\s+\d+)"  # Step 1, Step 2
    r")",
    re.MULTILINE,
)


def _find_section_boundaries(text: str) -> list[int]:
    """Find positions of section boundaries in text."""
    positions: set[int] = set()
    for pattern in _SECTION_PATTERNS:
        for match in pattern.finditer(text):
            positions.add(match.start())
    return sorted(positions)


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split text into (title, body) sections at detected boundaries."""
    boundaries = _find_section_boundaries(text)
    if not boundaries:
        return [("", text)]

    sections: list[tuple[str, str]] = []

    # Text before first boundary
    if boundaries[0] > 0:
        preamble = text[: boundaries[0]].strip()
        if preamble:
            sections.append(("preamble", preamble))

    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        section_text = text[start:end]

        # Extract title from first line
        first_newline = section_text.find("\n")
        if first_newline > 0:
            title = section_text[:first_newline].strip().lstrip("#").strip()
            body = section_text[first_newline:].strip()
        else:
            title = section_text.strip().lstrip("#").strip()
            body = ""

        if body:
            sections.append((title, body))

    return sections


# ---------------------------------------------------------------------------
# Aviation-aware chunking
# ---------------------------------------------------------------------------


class AviationChunker:
    """Structure-aware chunker for aviation documents.

    Preserves:
    - Checklist items as atomic units (never split a checklist item)
    - Procedure steps as atomic units
    - Limitation entries as atomic units
    - Paragraph boundaries for prose
    """

    def __init__(
        self,
        max_chunk_chars: int = 1500,
        min_chunk_chars: int = 100,
        overlap_chars: int = 100,
    ) -> None:
        self.max_chunk_chars = max_chunk_chars
        self.min_chunk_chars = min_chunk_chars
        self.overlap_chars = overlap_chars

    def chunk(
        self,
        text: str,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Chunk text preserving aviation document structure."""
        if not text.strip():
            return []

        base_meta = base_metadata or {}
        sections = _split_into_sections(text)
        chunks: list[Chunk] = []

        for title, body in sections:
            section_meta = {**base_meta, "section": title}
            section_chunks = self._chunk_section(body, section_meta)
            chunks.extend(section_chunks)

        return chunks

    def _chunk_section(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Chunk a single section, respecting list items and paragraphs."""
        if len(text) <= self.max_chunk_chars:
            return [Chunk(text=text.strip(), metadata=metadata)]

        # Try splitting by paragraphs first
        paragraphs = re.split(r"\n\s*\n", text)

        # If a paragraph contains a checklist/procedure, keep it atomic
        blocks: list[str] = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if self._is_list_block(para) and len(para) <= self.max_chunk_chars:
                # Keep list blocks atomic
                blocks.append(para)
            elif len(para) > self.max_chunk_chars:
                # Split long paragraphs at sentence boundaries
                blocks.extend(self._split_at_sentences(para))
            else:
                blocks.append(para)

        # Merge small blocks up to max_chunk_chars
        return self._merge_blocks(blocks, metadata)

    def _is_list_block(self, text: str) -> bool:
        """Check if text is a checklist or procedure list."""
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return False
        list_lines = sum(1 for line in lines if _LIST_ITEM_RE.match(line))
        return list_lines >= len(lines) * 0.5

    def _split_at_sentences(self, text: str) -> list[str]:
        """Split a long paragraph at sentence boundaries."""
        # Split on sentence-ending punctuation followed by space
        sentences = re.split(r"(?<=[.!?])\s+", text)
        blocks: list[str] = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) + 1 > self.max_chunk_chars and current:
                blocks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}" if current else sentence

        if current.strip():
            blocks.append(current.strip())

        return blocks

    def _merge_blocks(
        self,
        blocks: list[str],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Merge small blocks into chunks up to max size."""
        chunks: list[Chunk] = []
        current_text = ""

        for block in blocks:
            if not block.strip():
                continue

            if (
                current_text
                and len(current_text) + len(block) + 2 > self.max_chunk_chars
            ):
                chunks.append(Chunk(
                    text=current_text.strip(),
                    metadata={**metadata, "chunk_index": len(chunks)},
                ))
                # Add overlap from end of previous chunk
                if self.overlap_chars > 0 and len(current_text) > self.overlap_chars:
                    overlap = current_text[-self.overlap_chars :]
                    # Try to start overlap at a word boundary
                    space_idx = overlap.find(" ")
                    if space_idx > 0:
                        overlap = overlap[space_idx + 1 :]
                    current_text = overlap + "\n\n" + block
                else:
                    current_text = block
            else:
                current_text = f"{current_text}\n\n{block}" if current_text else block

        if current_text.strip() and len(current_text.strip()) >= self.min_chunk_chars:
            chunks.append(Chunk(
                text=current_text.strip(),
                metadata={**metadata, "chunk_index": len(chunks)},
            ))

        return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default chunker instance
_default_chunker = AviationChunker()


def chunk_document(
    text: str,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Chunk a document using the default aviation-aware chunker.

    Args:
        text: Full document text.
        metadata: Base metadata to attach to all chunks.

    Returns:
        List of Chunk objects with text and metadata.
    """
    return _default_chunker.chunk(text, base_metadata=metadata)
