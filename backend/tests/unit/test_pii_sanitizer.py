"""Unit tests for the PIISanitizer domain service (RNF-005).

Unlike tests/retroactive/test_pii_sanitization.py (which defined its masker
inside the test file and exercised no production code), these drive the real
src.domain.services.pii_sanitizer.PIISanitizer.
"""
from src.domain.services.pii_sanitizer import PIISanitizer


def test_masks_cpf_email_and_phone():
    sanitizer = PIISanitizer()
    raw = "Patient CPF 123.456.789-00, email john.doe@hospital.com, phone (11) 91234-5678."

    out = sanitizer.sanitize(raw)

    assert "123.456.789-00" not in out
    assert "john.doe@hospital.com" not in out
    assert "91234-5678" not in out
    assert "[CPF_MASKED]" in out
    assert "[EMAIL_MASKED]" in out
    assert "[PHONE_MASKED]" in out


def test_leaves_non_pii_text_untouched():
    sanitizer = PIISanitizer()
    raw = "Gene BRCA1 shows a KD affinity of -7.82 kcal/mol in chromosome 17."

    assert sanitizer.sanitize(raw) == raw


def test_is_idempotent():
    sanitizer = PIISanitizer()
    raw = "email a@b.com and CPF 111.222.333-44"

    once = sanitizer.sanitize(raw)
    assert sanitizer.sanitize(once) == once


def test_handles_non_string_gracefully():
    sanitizer = PIISanitizer()
    # Non-string input is coerced to str rather than raising.
    assert sanitizer.sanitize(None) == "None"
