"""Pure-Python paragraph/sentence-boundary text chunker (RAG-MARKER).

Zero external dependencies (no tokenizer library, no NLTK/spaCy download):
"token" here is approximated as a whitespace-delimited word, which is
adequate for producing reasonably-sized, semantically-coherent embedding
windows -- exact LLM/tokenizer token counts vary by model and are not
required for this purpose, only a consistent, cheap-to-compute proxy for
"how much text is in this window".

Chunks are built by walking sentences (never splitting inside one) and
flushing a window once adding the next sentence would exceed
``target_tokens``, carrying the trailing ~``overlap_tokens`` worth of
sentences from the just-flushed window into the start of the next one so
retrieval doesn't lose context at a chunk boundary.
"""
import re
from typing import List

# Splits on a sentence-ending punctuation mark followed by whitespace and the
# start of what looks like a new sentence (capital letter, digit, quote, or
# opening paren). Heuristic, not a full NLP sentence tokenizer -- adequate
# for chunking purposes (an occasional mis-split, e.g. on an abbreviation,
# just yields one slightly-oddly-shaped chunk, not a correctness bug).
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
# Blank-line-separated paragraphs.
_PARAGRAPH_BOUNDARY_RE = re.compile(r"\n\s*\n")


def _split_sentences(paragraph: str) -> List[str]:
    paragraph = paragraph.strip()
    if not paragraph:
        return []
    return [s.strip() for s in _SENTENCE_BOUNDARY_RE.split(paragraph) if s.strip()]


def _word_count(text: str) -> int:
    return len(text.split())


def chunk_text(text: str, target_tokens: int = 800, overlap_tokens: int = 100) -> List[str]:
    """Splits ``text`` into a list of chunks of roughly ``target_tokens``
    (whitespace-word-count) each, respecting paragraph/sentence boundaries,
    with roughly ``overlap_tokens`` of trailing content repeated at the start
    of the next chunk.

    Returns ``[]`` for empty/whitespace-only input. A single sentence longer
    than ``target_tokens`` is never split mid-sentence -- it becomes its own
    (oversized) chunk rather than being truncated or broken apart.
    """
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive.")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be >= 0 and < target_tokens.")

    paragraphs = [p for p in _PARAGRAPH_BOUNDARY_RE.split(text) if p.strip()]
    sentences: List[str] = []
    for paragraph in paragraphs:
        sentences.extend(_split_sentences(paragraph))

    if not sentences:
        return []

    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        sentence_tokens = _word_count(sentence)

        if current and current_tokens + sentence_tokens > target_tokens:
            chunks.append(" ".join(current))

            # Seed the next window with as many TRAILING sentences from the
            # just-flushed one as fit within `overlap_tokens` -- walking
            # backwards and stopping (without forcing at least one sentence
            # in) the moment adding the next one would exceed the overlap
            # budget. Not forcing at least one avoids re-seeding with a
            # single oversized sentence that would just immediately overflow
            # again next iteration (an infinite-loop / duplicate-chunk trap).
            overlap_sentences: List[str] = []
            overlap_count = 0
            for s in reversed(current):
                s_tokens = _word_count(s)
                if overlap_count + s_tokens > overlap_tokens:
                    break
                overlap_sentences.insert(0, s)
                overlap_count += s_tokens

            current = overlap_sentences
            current_tokens = overlap_count
            continue  # retry adding this same sentence to the fresh window

        current.append(sentence)
        current_tokens += sentence_tokens
        i += 1

    if current:
        chunks.append(" ".join(current))

    return chunks
