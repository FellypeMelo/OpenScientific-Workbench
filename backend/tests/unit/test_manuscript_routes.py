"""RF-008: /manuscript/compile + /manuscript/critique routes. The compiler is
overridden via dependency_overrides so no tectonic binary is needed; the
critique route's BYOK `ModelProviderPort` is faked at the
`ModelClientFactory.get_client` boundary, exactly like `test_task_routes.py`
and `test_chat_rag_wiring.py` fake it for their own LLM-backed routes."""
import httpx
from uuid import uuid4

from fastapi.testclient import TestClient

from src.infrastructure.latex.tectonic_compiler import TectonicNotAvailableError
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token
from src.presentation.routes.manuscript import get_tectonic_compiler

_AUTH = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


class FakeCompiler:
    def __init__(self, pdf=b"%PDF-1.5 ok", error=None):
        self._pdf = pdf
        self._error = error

    def compile(self, latex_source: str) -> bytes:
        if self._error is not None:
            raise self._error
        return self._pdf


def _override(compiler):
    app.dependency_overrides[get_tectonic_compiler] = lambda: compiler


def _clear():
    app.dependency_overrides.pop(get_tectonic_compiler, None)


def test_compile_returns_pdf():
    _override(FakeCompiler(pdf=b"%PDF-1.5 hello"))
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/manuscript/compile",
                json={"latex_source": "\\documentclass{article}\\begin{document}Hi\\end{document}"},
                headers=_AUTH,
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.content.startswith(b"%PDF")
    finally:
        _clear()


def test_compile_returns_503_when_tectonic_absent():
    _override(FakeCompiler(error=TectonicNotAvailableError("tectonic not found")))
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/manuscript/compile", json={"latex_source": "x"}, headers=_AUTH
            )
        assert resp.status_code == 503
    finally:
        _clear()


def test_compile_returns_422_on_invalid_latex():
    _override(FakeCompiler(error=RuntimeError("Tectonic compilation failed: ! LaTeX Error")))
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/manuscript/compile", json={"latex_source": "bad"}, headers=_AUTH
            )
        assert resp.status_code == 422
    finally:
        _clear()


_SOURCE = "\\documentclass{article}\\begin{document}The afinity was high.\\end{document}"


class _FakeCritiqueClient:
    def __init__(self, response: str = None, error: Exception = None):
        self._response = response
        self._error = error
        self.calls = 0

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._response

    async def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        raise NotImplementedError
        yield ""


def test_critique_returns_real_comments_from_the_model(monkeypatch):
    resp = '{"comments": [{"target_text": "afinity", "suggestion": "affinity"}]}'
    monkeypatch.setattr(
        "src.presentation.routes.manuscript.ModelClientFactory.get_client",
        lambda provider_name: _FakeCritiqueClient(response=resp),
    )

    with TestClient(app) as client:
        resp_ = client.post(
            "/api/v1/manuscript/critique",
            json={"latex_source": _SOURCE},
            headers=_AUTH,
        )

    assert resp_.status_code == 200
    body = resp_.json()
    assert body["comments"] == [
        {"id": "c1", "target_text": "afinity", "suggestion": "affinity", "resolved": False}
    ]


def test_critique_returns_empty_comments_when_critic_finds_no_issues(monkeypatch):
    monkeypatch.setattr(
        "src.presentation.routes.manuscript.ModelClientFactory.get_client",
        lambda provider_name: _FakeCritiqueClient(response='{"comments": []}'),
    )

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/manuscript/critique",
            json={"latex_source": _SOURCE},
            headers=_AUTH,
        )

    assert resp.status_code == 200
    assert resp.json()["comments"] == []


def test_critique_returns_400_for_unsupported_provider():
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/manuscript/critique",
            json={"latex_source": _SOURCE, "provider": "not-a-real-provider"},
            headers=_AUTH,
        )

    assert resp.status_code == 400
    assert "Unsupported model provider" in resp.json()["detail"]


def test_critique_returns_400_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/manuscript/critique",
            json={"latex_source": _SOURCE, "provider": "deepseek"},
            headers=_AUTH,
        )

    assert resp.status_code == 400
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]


def test_critique_returns_502_when_model_response_is_unparseable(monkeypatch):
    monkeypatch.setattr(
        "src.presentation.routes.manuscript.ModelClientFactory.get_client",
        lambda provider_name: _FakeCritiqueClient(response="I cannot help with that."),
    )

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/manuscript/critique",
            json={"latex_source": _SOURCE},
            headers=_AUTH,
        )

    assert resp.status_code == 502


def test_critique_returns_502_when_provider_transport_fails(monkeypatch):
    monkeypatch.setattr(
        "src.presentation.routes.manuscript.ModelClientFactory.get_client",
        lambda provider_name: _FakeCritiqueClient(
            error=httpx.ConnectError("connection refused")
        ),
    )

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/manuscript/critique",
            json={"latex_source": _SOURCE},
            headers=_AUTH,
        )

    assert resp.status_code == 502
