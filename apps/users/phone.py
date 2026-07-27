"""Normalizacja i walidacja numerów telefonu PL (+48…)."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

PHONE_RE = re.compile(r"^\+48\d{9}$")


def normalize_pl_phone(raw: str) -> str:
    """
    Sprowadza numer do formatu E.164: +48XXXXXXXXX (9 cyfr po +48).

    Akceptuje m.in. +48 500 100 100, 48500100100, 500100100.
    """
    text = (raw or "").strip()
    if not text:
        raise ValidationError("Podaj numer telefonu.", code="required")

    digits = "".join(c for c in text if c.isdigit())
    if digits.startswith("48") and len(digits) == 11:
        phone = f"+{digits}"
    elif len(digits) == 9:
        phone = f"+48{digits}"
    elif text.startswith("+") and digits.startswith("48") and len(digits) == 11:
        phone = f"+{digits}"
    else:
        raise ValidationError(
            "Numer musi być w formacie +48 i 9 cyfr (np. +48500100100).",
            code="invalid",
        )

    if not PHONE_RE.match(phone):
        raise ValidationError(
            "Numer musi być w formacie +48XXXXXXXXX.",
            code="invalid",
        )
    return phone


def is_valid_pl_phone(raw: str) -> bool:
    try:
        normalize_pl_phone(raw)
        return True
    except ValidationError:
        return False
