"""Unit tests for `CritiqueManuscriptUseCase` (RF-008 gap closure).

The `ModelProviderPort` is faked, so no API keys / network are needed: we
assert that the use case turns the critic model's JSON answer into a real
`CriticComment` list, filters out hallucinated (non-substring) quotes, and
raises on an unusable response instead of silently returning a fake empty
result.
"""
import pytest

from src.application.use_cases.critique_manuscript import CritiqueManuscriptUseCase
from src.domain.entities.manuscript import CriticComment


class FakeModel:
    def __init__(self, response: str):
        self._response = response
        self.prompts: list[tuple[str, str]] = []

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        self.prompts.append((prompt, system_instruction))
        return self._response

    def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        raise NotImplementedError


SOURCE = (
    "\\documentclass{article}\\begin{document}"
    "The predicted binding afinity of the ligand was -7.82 kcal/mol."
    "\\end{document}"
)


@pytest.mark.asyncio
async def test_execute_parses_model_json_into_critic_comments():
    resp = (
        '{"comments": ['
        '{"target_text": "afinity", "suggestion": "affinity"},'
        '{"target_text": "-7.82 kcal/mol", "suggestion": "-7.820 kcal/mol"}'
        "]}"
    )
    use_case = CritiqueManuscriptUseCase(FakeModel(resp))

    comments = await use_case.execute(SOURCE)

    assert comments == [
        CriticComment(id="c1", target_text="afinity", suggestion="affinity"),
        CriticComment(id="c2", target_text="-7.82 kcal/mol", suggestion="-7.820 kcal/mol"),
    ]


@pytest.mark.asyncio
async def test_execute_extracts_json_wrapped_in_prose_and_fences():
    resp = (
        "Sure, here is my review:\n```json\n"
        '{"comments": [{"target_text": "afinity", "suggestion": "affinity"}]}'
        "\n```\nHope that helps."
    )
    use_case = CritiqueManuscriptUseCase(FakeModel(resp))

    comments = await use_case.execute(SOURCE)

    assert len(comments) == 1
    assert comments[0].suggestion == "affinity"


@pytest.mark.asyncio
async def test_execute_returns_empty_list_for_empty_source_without_calling_model():
    model = FakeModel('{"comments": []}')
    use_case = CritiqueManuscriptUseCase(model)

    comments = await use_case.execute("   ")

    assert comments == []
    assert model.prompts == []  # never even called the model


@pytest.mark.asyncio
async def test_execute_returns_empty_list_when_critic_finds_no_issues():
    use_case = CritiqueManuscriptUseCase(FakeModel('{"comments": []}'))

    comments = await use_case.execute(SOURCE)

    assert comments == []


@pytest.mark.asyncio
async def test_execute_discards_comments_whose_target_text_is_not_a_literal_substring():
    """A hallucinated/paraphrased quote must never reach the frontend: applying
    it would silently fail `ManuscriptDocument.apply_correction`'s own
    substring check."""
    resp = (
        '{"comments": ['
        '{"target_text": "this text does not appear anywhere", "suggestion": "x"},'
        '{"target_text": "afinity", "suggestion": "affinity"}'
        "]}"
    )
    use_case = CritiqueManuscriptUseCase(FakeModel(resp))

    comments = await use_case.execute(SOURCE)

    assert len(comments) == 1
    assert comments[0].target_text == "afinity"


@pytest.mark.asyncio
async def test_execute_raises_when_no_json_present():
    use_case = CritiqueManuscriptUseCase(FakeModel("I cannot help with that."))

    with pytest.raises(ValueError, match="parseable JSON"):
        await use_case.execute(SOURCE)


@pytest.mark.asyncio
async def test_execute_raises_when_comments_field_missing():
    use_case = CritiqueManuscriptUseCase(FakeModel('{"not_comments": []}'))

    with pytest.raises(ValueError, match="comments"):
        await use_case.execute(SOURCE)


@pytest.mark.asyncio
async def test_execute_skips_malformed_individual_comment_entries():
    resp = (
        '{"comments": ['
        '"not-a-dict",'
        '{"target_text": 123, "suggestion": "affinity"},'
        '{"target_text": "afinity"},'
        '{"target_text": "afinity", "suggestion": "affinity"}'
        "]}"
    )
    use_case = CritiqueManuscriptUseCase(FakeModel(resp))

    comments = await use_case.execute(SOURCE)

    assert len(comments) == 1
    assert comments[0].target_text == "afinity"


@pytest.mark.asyncio
async def test_execute_truncates_very_long_source_before_sending_to_model():
    model = FakeModel('{"comments": []}')
    use_case = CritiqueManuscriptUseCase(model)
    long_source = "x" * 50000

    await use_case.execute(long_source)

    sent_prompt = model.prompts[0][0]
    assert len(sent_prompt) <= 12000
