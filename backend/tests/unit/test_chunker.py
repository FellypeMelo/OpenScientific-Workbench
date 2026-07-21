"""Unit tests for the pure-Python paragraph/sentence-boundary chunker
(RAG-MARKER)."""
import pytest

from src.infrastructure.parsing.chunker import chunk_text


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_short_text_produces_single_chunk():
    text = "TP53 is a tumor suppressor gene. It regulates the cell cycle."
    chunks = chunk_text(text, target_tokens=800, overlap_tokens=100)
    assert len(chunks) == 1
    assert "TP53" in chunks[0]
    assert "regulates the cell cycle" in chunks[0]


def test_chunk_text_never_splits_a_sentence_across_chunks():
    # Build a paragraph made of clearly-delimited, uniquely-numbered
    # sentences so we can verify each survives intact in exactly one chunk.
    sentences = [f"Sentence number {i} describes finding {i}." for i in range(1, 60)]
    text = " ".join(sentences)

    chunks = chunk_text(text, target_tokens=50, overlap_tokens=10)

    assert len(chunks) > 1
    for sentence in sentences:
        assert sum(sentence in chunk for chunk in chunks) >= 1


def test_chunk_text_respects_approximate_target_token_budget():
    sentences = [f"Word{i} word{i} word{i} word{i} word{i}." for i in range(1, 40)]
    text = " ".join(sentences)

    chunks = chunk_text(text, target_tokens=50, overlap_tokens=10)

    for chunk in chunks[:-1]:  # last chunk may be a short remainder
        assert len(chunk.split()) <= 60  # target + one sentence's worth of slack


def test_chunk_text_produces_overlap_between_consecutive_chunks():
    sentences = [f"Fact {i} about gene X is stated here for context." for i in range(1, 40)]
    text = " ".join(sentences)

    chunks = chunk_text(text, target_tokens=60, overlap_tokens=20)

    assert len(chunks) >= 2
    # At least one sentence from the end of chunk[0] should reappear at the
    # start of chunk[1] (the overlap window).
    first_chunk_sentences = [s.strip() for s in chunks[0].split(".") if s.strip()]
    assert any(s + "." in chunks[1] for s in first_chunk_sentences[-2:])


def test_chunk_text_handles_paragraph_boundaries():
    text = "Paragraph one sentence A. Paragraph one sentence B.\n\nParagraph two sentence A. Paragraph two sentence B."
    chunks = chunk_text(text, target_tokens=800, overlap_tokens=100)
    assert len(chunks) == 1
    assert "Paragraph one" in chunks[0]
    assert "Paragraph two" in chunks[0]


def test_chunk_text_oversized_single_sentence_becomes_its_own_chunk_without_hanging():
    huge_sentence = "Word " * 500 + "sentence."
    text = f"{huge_sentence} Short next sentence follows here."

    chunks = chunk_text(text, target_tokens=50, overlap_tokens=10)

    assert len(chunks) == 2
    assert "Short next sentence" in chunks[1]


def test_chunk_text_rejects_invalid_target_and_overlap():
    with pytest.raises(ValueError):
        chunk_text("some text.", target_tokens=0)
    with pytest.raises(ValueError):
        chunk_text("some text.", target_tokens=100, overlap_tokens=-1)
    with pytest.raises(ValueError):
        chunk_text("some text.", target_tokens=100, overlap_tokens=100)
