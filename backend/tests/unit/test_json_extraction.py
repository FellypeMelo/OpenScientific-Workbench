"""Unit tests for the shared best-effort JSON extraction domain service
(factored out of `infrastructure/llm/llm_task_planner.py` so
`application/use_cases/ingest_document.py` can reuse it without an
application-layer module importing from `infrastructure/`)."""
import pytest

from src.domain.services.json_extraction import extract_json


def test_extract_json_parses_plain_json_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_parses_plain_json_array():
    assert extract_json('[1, 2, 3]') == [1, 2, 3]


def test_extract_json_extracts_object_wrapped_in_prose_and_fences():
    text = 'Sure, here you go:\n```json\n{"triples": []}\n```\nHope that helps.'
    assert extract_json(text) == {"triples": []}


def test_extract_json_prefers_earliest_opening_container():
    text = 'Result: {"nodes": [1, 2]} (derived from [9, 9])'
    assert extract_json(text) == {"nodes": [1, 2]}


def test_extract_json_raises_when_nothing_parseable():
    with pytest.raises(ValueError):
        extract_json("I cannot help with that.")
