"""Wspólne parsowanie imion/nazwisk z CSV PKW (nazwisko CAPS)."""

from __future__ import annotations


def parse_pkw_full_name(full: str) -> tuple[str, str, str]:
    """
    Format sejm/PE: 'Wioleta Barbara TOMCZAK' → (Wioleta, Barbara, Tomczak)
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


def parse_pkw_full_name_surname_first(full: str) -> tuple[str, str, str]:
    """
    Format samorząd: 'KRZYŻANOWSKI Marcin Rafał' → (Marcin, Rafał, Krzyżanowski)
    """
    parts = (full or "").split()
    if not parts:
        return "", "", ""

    i = 0
    while i < len(parts) and parts[i].isupper():
        i += 1
    if i == 0:
        return parse_pkw_full_name(full)

    surname_parts = parts[:i]
    given = parts[i:]
    last = " ".join(_title_token(t) for t in surname_parts)
    first = given[0] if given else ""
    second = " ".join(given[1:]) if len(given) > 1 else ""
    return first, second, last


def _title_token(token: str) -> str:
    if not token:
        return token
    if "-" in token:
        return "-".join(_title_token(p) for p in token.split("-"))
    if token.isupper() or token.islower():
        return token[:1].upper() + token[1:].lower()
    return token
