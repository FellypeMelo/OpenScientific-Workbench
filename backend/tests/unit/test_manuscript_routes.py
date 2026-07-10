"""RF-008: /manuscript/compile route. The compiler is overridden via
dependency_overrides so no tectonic binary is needed."""
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
