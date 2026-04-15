"""Tests for aviation-aware semantic chunking."""

from __future__ import annotations

from orchestrator.chunking import AviationChunker, chunk_document

# ---------------------------------------------------------------------------
# Basic chunking
# ---------------------------------------------------------------------------


class TestChunkDocument:
    def test_empty_text(self) -> None:
        assert chunk_document("") == []

    def test_short_text_single_chunk(self) -> None:
        chunks = chunk_document("Short text about flying.")
        assert len(chunks) == 1
        assert chunks[0].text == "Short text about flying."

    def test_metadata_propagated(self) -> None:
        chunks = chunk_document("Some text.", metadata={"aircraft_type": "C172"})
        assert len(chunks) >= 1
        assert chunks[0].metadata["aircraft_type"] == "C172"


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------


class TestSectionDetection:
    def test_markdown_headings_split(self) -> None:
        text = "# Section One\nContent one.\n\n# Section Two\nContent two."
        chunks = chunk_document(text)
        all_text = " ".join(c.text for c in chunks)
        assert "Content one" in all_text
        assert "Content two" in all_text

    def test_section_title_in_metadata(self) -> None:
        text = "# Limitations\nVne is 163 knots.\n\n# Performance\nTakeoff roll 960 ft."
        chunks = chunk_document(text)
        sections = [c.metadata.get("section", "") for c in chunks]
        assert any("Limitations" in s for s in sections)
        assert any("Performance" in s for s in sections)


# ---------------------------------------------------------------------------
# Checklist preservation
# ---------------------------------------------------------------------------


class TestChecklistPreservation:
    def test_checklist_not_split(self) -> None:
        checklist = (
            "1. Preflight inspection - COMPLETE\n"
            "2. Passenger briefing - COMPLETE\n"
            "3. Seats, belts, harnesses - ADJUSTED and LOCKED\n"
            "4. Fuel quantity - CHECKED\n"
            "5. Mixture - RICH\n"
        )
        chunker = AviationChunker(max_chunk_chars=2000)
        chunks = chunker.chunk(checklist)
        # Entire checklist should be in a single chunk
        assert len(chunks) == 1
        assert "1. Preflight" in chunks[0].text
        assert "5. Mixture" in chunks[0].text

    def test_procedure_steps_preserved(self) -> None:
        procedure = (
            "Step 1: Check fuel quantity\nStep 2: Verify oil level\nStep 3: Check flight controls\n"
        )
        chunker = AviationChunker(max_chunk_chars=2000)
        chunks = chunker.chunk(procedure)
        assert len(chunks) == 1
        assert "Step 1" in chunks[0].text
        assert "Step 3" in chunks[0].text


# ---------------------------------------------------------------------------
# Long text splitting
# ---------------------------------------------------------------------------


class TestLongTextSplitting:
    def test_long_text_creates_multiple_chunks(self) -> None:
        # Generate text longer than max_chunk_chars
        long_text = "This is a paragraph about aviation. " * 200
        chunker = AviationChunker(max_chunk_chars=500, min_chunk_chars=50)
        chunks = chunker.chunk(long_text)
        assert len(chunks) > 1
        # All chunks should be under the limit (with some tolerance for overlap)
        for chunk in chunks:
            assert chunk.char_count <= 600  # some tolerance

    def test_paragraph_boundaries_respected(self) -> None:
        text = (
            "First paragraph about takeoff procedures.\n\n"
            "Second paragraph about climb procedures.\n\n"
            "Third paragraph about cruise procedures."
        )
        chunker = AviationChunker(max_chunk_chars=200, min_chunk_chars=20)
        chunks = chunker.chunk(text)
        # Each paragraph should be intact in some chunk
        all_text = " ".join(c.text for c in chunks)
        assert "takeoff procedures" in all_text
        assert "cruise procedures" in all_text


# ---------------------------------------------------------------------------
# AviationChunker configuration
# ---------------------------------------------------------------------------


class TestAviationChunkerConfig:
    def test_custom_chunk_size(self) -> None:
        chunker = AviationChunker(max_chunk_chars=100, min_chunk_chars=10)
        # Use paragraphs so the chunker has split points
        text = "This is a test paragraph.\n\n" * 20  # ~540 chars
        chunks = chunker.chunk(text)
        assert len(chunks) > 1

    def test_chunk_has_metadata(self) -> None:
        chunker = AviationChunker()
        chunks = chunker.chunk("Test text.", base_metadata={"doc_type": "poh"})
        assert chunks[0].metadata["doc_type"] == "poh"

    def test_chunk_index_in_metadata(self) -> None:
        text = "Paragraph one.\n\n" * 50
        chunker = AviationChunker(max_chunk_chars=100, min_chunk_chars=10)
        chunks = chunker.chunk(text)
        if len(chunks) > 1:
            indices = [c.metadata.get("chunk_index", -1) for c in chunks]
            assert indices[0] == 0
            assert indices[-1] == len(chunks) - 1
