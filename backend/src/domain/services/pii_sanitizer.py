import re


class PIISanitizer:
    """Masks personally identifiable information before it is persisted or logged
    (LGPD/GDPR, RNF-005).

    Covers the PII most likely to appear in clinical/exome task metadata: CPF,
    e-mail addresses and Brazilian mobile phone numbers. Masking is applied in a
    fixed order and is idempotent (re-sanitising already-masked text is a no-op).
    """

    _CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
    _EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b")
    # BR mobile: optional +55, DDD (2 digits, optional parens), then 9 + 8 digits.
    _PHONE = re.compile(r"(?:\+55\s?)?\(?\d{2}\)?[\s-]?9\d{4}[\s-]?\d{4}\b")

    def sanitize(self, text: object) -> str:
        text = str(text)
        text = self._CPF.sub("[CPF_MASKED]", text)
        text = self._PHONE.sub("[PHONE_MASKED]", text)
        text = self._EMAIL.sub("[EMAIL_MASKED]", text)
        return text
