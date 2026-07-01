import pytest
import re

class DataPurger:
    """
    Utility service to sanitize PII (Personally Identifiable Information)
    to comply with Brazilian Data Privacy Law (LGPD).
    """
    @staticmethod
    def sanitize(text: str) -> str:
        # 1. Mask CPF patterns (XXX.XXX.XXX-XX)
        cpf_pattern = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
        text = cpf_pattern.sub("[CPF_MASKED]", text)
        
        # 2. Mask Email patterns
        email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
        text = email_pattern.sub("[EMAIL_MASKED]", text)
        
        return text

def test_lgpd_pii_sanitization():
    raw_log = "Patient John Doe with CPF 123.456.789-00 and email john.doe@hospital.com has mutation."
    sanitized = DataPurger.sanitize(raw_log)
    
    assert "123.456.789-00" not in sanitized
    assert "john.doe@hospital.com" not in sanitized
    assert "[CPF_MASKED]" in sanitized
    assert "[EMAIL_MASKED]" in sanitized
