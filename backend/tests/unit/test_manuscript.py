"""RF-008: manuscript entity (critic-linked corrections) + Tectonic compiler.

The tectonic binary is mocked so the compile path is asserted without requiring
tectonic to be installed.
"""
import subprocess
import types

import pytest

import src.infrastructure.latex.tectonic_compiler as tc
from src.domain.entities.manuscript import CriticComment, ManuscriptDocument
from src.infrastructure.latex.tectonic_compiler import TectonicCompiler, TectonicNotAvailableError


def _doc():
    return ManuscriptDocument(
        latex_source="\\documentclass{article}\\begin{document}The affinty is high.\\end{document}",
        comments=[CriticComment(id="c1", target_text="affinty", suggestion="affinity")],
    )


def test_apply_correction_updates_source_and_resolves_comment():
    doc = _doc()

    doc.apply_correction("c1", "affinity")

    assert "affinity" in doc.latex_source
    assert "affinty" not in doc.latex_source
    assert doc.comments[0].resolved is True


def test_apply_correction_unknown_comment_raises():
    with pytest.raises(ValueError, match="No critic comment"):
        _doc().apply_correction("nope", "x")


def test_compile_returns_pdf_bytes(monkeypatch):
    monkeypatch.setattr(tc.shutil, "which", lambda _b: "/usr/bin/tectonic")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        return types.SimpleNamespace(stdout=b"%PDF-1.5\n...", stderr=b"", returncode=0)

    monkeypatch.setattr(tc.subprocess, "run", fake_run)

    pdf = TectonicCompiler().compile("\\documentclass{article}\\begin{document}Hi\\end{document}")

    assert pdf.startswith(b"%PDF")
    assert captured["argv"][0] == "tectonic"
    assert b"Hi" in captured["input"]


def test_compile_raises_when_binary_absent(monkeypatch):
    monkeypatch.setattr(tc.shutil, "which", lambda _b: None)

    with pytest.raises(TectonicNotAvailableError):
        TectonicCompiler().compile("\\documentclass{article}\\end{document}")


def test_compile_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(tc.shutil, "which", lambda _b: "/usr/bin/tectonic")
    monkeypatch.setattr(
        tc.subprocess, "run",
        lambda argv, **k: types.SimpleNamespace(stdout=b"", stderr=b"! LaTeX Error", returncode=1),
    )

    with pytest.raises(RuntimeError, match="Tectonic compilation failed"):
        TectonicCompiler().compile("bad")
