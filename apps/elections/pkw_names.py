"""Wspólne parsowanie imion/nazwisk z CSV PKW (nazwisko CAPS)."""

from __future__ import annotations


def parse_pkw_full_name(full: str) -> tuple[str, str, str]:
    """
    'Wioleta Barbara TOMCZAK' → (Wioleta, Barbara, Tomczak)
    'Łukasz KOPEĆ' → (Łukasz, '', Kopeć)
    """
    parts = (full or "").split()
    if not parts:
        return "", "", ""

    i = 0
    while i < len(parts) and not parts[i].isupper():
        i += 1
    given = parts[:i]
    surname_parts = parts[i:]
    if not surname_parts:
        surname_parts = [parts[-1]]
        given = parts[:-1]

    first = given[0] if given else ""
    second = " ".join(given[1:]) if len(given) > 1 else ""
    last = " ".join(_title_token(t) for t in surname_parts)
    return first, second, last


def _title_token(token: str) -> str:
    if not token:
        return token
    if token.isupper() or token.islower():
        return token[:1].upper() + token[1:].lower()
    return token
