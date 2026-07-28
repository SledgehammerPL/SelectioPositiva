"""
Tożsamość osoby: imię + drugie imię + nazwisko + jednostka terytorialna.

Data urodzenia rozróżnia tylko gdy OBA rekordy mają datę i są różne.
Brak daty po jednej stronie = ta sama osoba (o ile jest jednoznacznie
kogo dopasować — przy wielu różnych datach w grupie nie zgadujemy).
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from elections.models import Ballot, VoterProfile

User = get_user_model()

# (first, second, last, unit_id)
NameUnitKey = tuple[str, str, str, int]
IdentityIndex = dict[NameUnitKey, list[User]]


def normalize_name_part(value: str) -> str:
    return (value or "").strip().casefold()


def name_unit_key(
    *,
    first_name: str,
    second_name: str,
    last_name: str,
    territorial_unit_id: int | None,
) -> NameUnitKey | None:
    if territorial_unit_id is None:
        return None
    return (
        normalize_name_part(first_name),
        normalize_name_part(second_name),
        normalize_name_part(last_name),
        territorial_unit_id,
    )


def name_unit_key_for_user(
    user: User, profile: VoterProfile | None = None
) -> NameUnitKey | None:
    if profile is None:
        profile = getattr(user, "voter_profile", None)
    if profile is None:
        return None
    return name_unit_key(
        first_name=user.first_name,
        second_name=profile.second_name or "",
        last_name=user.last_name,
        territorial_unit_id=profile.territorial_unit_id,
    )


def birth_dates_conflict(a: date | None, b: date | None) -> bool:
    """Konflikt tylko gdy obie daty są znane i różne."""
    return a is not None and b is not None and a != b


def birth_dates_compatible(a: date | None, b: date | None) -> bool:
    return not birth_dates_conflict(a, b)


def _profile_birth(user: User) -> date | None:
    profile = getattr(user, "voter_profile", None)
    return profile.birth_date if profile is not None else None


def build_identity_index(*, users: list[User] | None = None) -> IdentityIndex:
    """Mapa (imię, miasto) → lista użytkowników (po id rosnąco)."""
    index: IdentityIndex = {}
    if users is None:
        qs = (
            User.objects.filter(voter_profile__territorial_unit__isnull=False)
            .select_related("voter_profile")
            .order_by("id")
        )
        iterable = qs.iterator(chunk_size=2000)
    else:
        iterable = sorted(users, key=lambda u: u.pk)

    for user in iterable:
        key = name_unit_key_for_user(user)
        if key is None:
            continue
        index.setdefault(key, []).append(user)
    return index


def find_identity_match(
    index: IdentityIndex,
    *,
    first_name: str,
    second_name: str,
    last_name: str,
    territorial_unit_id: int | None,
    birth_date: date | None,
) -> User | None:
    key = name_unit_key(
        first_name=first_name,
        second_name=second_name,
        last_name=last_name,
        territorial_unit_id=territorial_unit_id,
    )
    if key is None:
        return None
    people = index.get(key) or []
    if not people:
        return None

    known_dates = {d for u in people if (d := _profile_birth(u)) is not None}

    if birth_date is None and len(known_dates) > 1:
        # Niezgadywanie: kilka różnych dat w grupie → tylko inni bez daty.
        matches = [u for u in people if _profile_birth(u) is None]
    else:
        matches = [
            u for u in people if birth_dates_compatible(birth_date, _profile_birth(u))
        ]

    if not matches:
        return None

    # Preferuj dokładną datę, potem znaną datę, potem najniższe id.
    def sort_key(u: User) -> tuple[int, int, int]:
        bd = _profile_birth(u)
        exact = 0 if birth_date is not None and bd == birth_date else 1
        has_date = 0 if bd is not None else 1
        return (exact, has_date, u.pk)

    matches.sort(key=sort_key)
    return matches[0]


def register_identity(index: IdentityIndex, user: User) -> None:
    key = name_unit_key_for_user(user)
    if key is None:
        return
    bucket = index.setdefault(key, [])
    if any(u.pk == user.pk for u in bucket):
        return
    bucket.append(user)
    bucket.sort(key=lambda u: u.pk)


def _cluster_same_name_unit(users: list[User]) -> list[list[User]]:
    """
    Dzieli osoby o tym samym imieniu/mieście na grupy do scalenia.
    Przy wielu różnych datach nie dokleja „bez daty” do żadnej z nich.
    """
    by_bd: dict[date | None, list[User]] = {}
    for user in users:
        by_bd.setdefault(_profile_birth(user), []).append(user)

    dated_keys = sorted(k for k in by_bd if k is not None)
    none_users = by_bd.get(None, [])
    clusters: list[list[User]] = []

    if not dated_keys:
        if len(none_users) > 1:
            clusters.append(sorted(none_users, key=lambda u: u.pk))
        return clusters

    if len(dated_keys) == 1:
        cluster = by_bd[dated_keys[0]] + none_users
        if len(cluster) > 1:
            clusters.append(sorted(cluster, key=lambda u: u.pk))
        return clusters

    for dk in dated_keys:
        group = by_bd[dk]
        if len(group) > 1:
            clusters.append(sorted(group, key=lambda u: u.pk))
    if len(none_users) > 1:
        clusters.append(sorted(none_users, key=lambda u: u.pk))
    return clusters


def find_duplicate_groups() -> list[tuple[NameUnitKey, list[User]]]:
    """Grupy nierozróżnialnych użytkowników (>1 konto)."""
    index = build_identity_index()
    groups: list[tuple[NameUnitKey, list[User]]] = []
    for key, people in index.items():
        if len(people) < 2:
            continue
        for cluster in _cluster_same_name_unit(people):
            if len(cluster) > 1:
                groups.append((key, cluster))
    return groups


def _merge_profile_data(keep: User, dup: User) -> None:
    """Przenieś znaną datę ur. z duplikatu na zachowane konto, jeśli brakuje."""
    keep_p = getattr(keep, "voter_profile", None)
    dup_p = getattr(dup, "voter_profile", None)
    if keep_p is None or dup_p is None:
        return
    updates: list[str] = []
    if keep_p.birth_date is None and dup_p.birth_date is not None:
        keep_p.birth_date = dup_p.birth_date
        updates.append("birth_date")
    if not (keep_p.second_name or "").strip() and (dup_p.second_name or "").strip():
        keep_p.second_name = dup_p.second_name
        updates.append("second_name")
    if updates:
        keep_p.save(update_fields=updates)


def _remap_ranked_user_ids(id_map: dict[int, int]) -> int:
    if not id_map:
        return 0
    changed = 0
    for ballot in Ballot.objects.iterator(chunk_size=500):
        ranked = list(ballot.ranked_user_ids or [])
        if not ranked:
            continue
        new_ranked: list[int] = []
        seen: set[int] = set()
        dirty = False
        for uid in ranked:
            mapped = id_map.get(uid, uid)
            if mapped != uid:
                dirty = True
            if mapped in seen:
                dirty = True
                continue
            seen.add(mapped)
            new_ranked.append(mapped)
        if dirty:
            ballot.ranked_user_ids = new_ranked
            ballot.save(update_fields=["ranked_user_ids", "updated_at"])
            changed += 1
    return changed


@transaction.atomic
def dedupe_indistinguishable_users(*, apply: bool = False) -> dict[str, int]:
    """
    W każdej grupie zostawia użytkownika o najniższym id, usuwa pozostałych.
    Przed usunięciem przepisuje datę urodzenia na zachowane konto, jeśli brakowało.
    """
    groups = find_duplicate_groups()
    extra = sum(len(users) - 1 for _, users in groups)
    if not apply:
        return {
            "groups": len(groups),
            "users_to_delete": extra,
            "deleted": 0,
            "ballots_remapped": 0,
        }

    id_map: dict[int, int] = {}
    to_delete: list[int] = []
    for _key, users in groups:
        keep = users[0]
        for dup in users[1:]:
            _merge_profile_data(keep, dup)
            id_map[dup.pk] = keep.pk
            to_delete.append(dup.pk)

    ballots_remapped = _remap_ranked_user_ids(id_map)
    deleted, _ = User.objects.filter(pk__in=to_delete).delete()
    return {
        "groups": len(groups),
        "users_to_delete": extra,
        "deleted": len(to_delete),
        "ballots_remapped": ballots_remapped,
        "objects_deleted": deleted,
    }
