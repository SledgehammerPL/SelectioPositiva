"""
Tożsamość osoby: imię + drugie imię + nazwisko.

Jednostka terytorialna: dopasowanie gdy ta sama albo jedna jest przodkiem drugiej
(np. powiat Warszawa ↔ gmina Śródmieście). Wspólny przodek (np. tylko „Polska”)
nie wystarczy.

Data urodzenia rozróżnia tylko gdy OBA rekordy mają datę i są różne.
Brak daty po jednej stronie = ta sama osoba (o ile jest jednoznacznie
kogo dopasować — przy wielu różnych datach w grupie nie zgadujemy).
Osoby bez daty z różnych (nawet spokrewnionych) jednostek nie są scalane
bez wspólnej daty.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from elections.models import Ballot, VoterProfile
from geo.models import TerritorialUnit

User = get_user_model()

# (first, second, last)
NameKey = tuple[str, str, str]
IdentityIndex = dict[NameKey, list[User]]


def normalize_name_part(value: str) -> str:
    return (value or "").strip().casefold()


def name_key(
    *,
    first_name: str,
    second_name: str,
    last_name: str,
) -> NameKey:
    return (
        normalize_name_part(first_name),
        normalize_name_part(second_name),
        normalize_name_part(last_name),
    )


def name_key_for_user(user: User, profile: VoterProfile | None = None) -> NameKey | None:
    if profile is None:
        profile = getattr(user, "voter_profile", None)
    if profile is None:
        return None
    return name_key(
        first_name=user.first_name,
        second_name=profile.second_name or "",
        last_name=user.last_name,
    )


# Backwards-compatible aliases (stare importy z unit_id w kluczu).
NameUnitKey = tuple[str, str, str, int]


def name_unit_key(
    *,
    first_name: str,
    second_name: str,
    last_name: str,
    territorial_unit_id: int | None,
) -> NameUnitKey | None:
    if territorial_unit_id is None:
        return None
    first, second, last = name_key(
        first_name=first_name,
        second_name=second_name,
        last_name=last_name,
    )
    return (first, second, last, territorial_unit_id)


def name_unit_key_for_user(
    user: User, profile: VoterProfile | None = None
) -> NameUnitKey | None:
    if profile is None:
        profile = getattr(user, "voter_profile", None)
    if profile is None or profile.territorial_unit_id is None:
        return None
    nk = name_key_for_user(user, profile)
    if nk is None:
        return None
    return (*nk, profile.territorial_unit_id)


def birth_dates_conflict(a: date | None, b: date | None) -> bool:
    """Konflikt tylko gdy obie daty są znane i różne."""
    return a is not None and b is not None and a != b


def birth_dates_compatible(a: date | None, b: date | None) -> bool:
    return not birth_dates_conflict(a, b)


def _profile_birth(user: User) -> date | None:
    profile = getattr(user, "voter_profile", None)
    return profile.birth_date if profile is not None else None


def _profile_unit_id(user: User) -> int | None:
    profile = getattr(user, "voter_profile", None)
    return profile.territorial_unit_id if profile is not None else None


def _ancestor_id_set(
    unit_id: int | None,
    cache: dict[int, set[int]],
) -> set[int]:
    """Zbiór id jednostki i jej przodków (włącznie z sobą)."""
    if unit_id is None:
        return set()
    cached = cache.get(unit_id)
    if cached is not None:
        return cached
    ids: set[int] = set()
    current_id: int | None = unit_id
    while current_id is not None and current_id not in ids:
        ids.add(current_id)
        parent_id = (
            TerritorialUnit.objects.filter(pk=current_id)
            .values_list("parent_id", flat=True)
            .first()
        )
        current_id = parent_id
    cache[unit_id] = ids
    return ids


def units_related(
    a_id: int | None,
    b_id: int | None,
    *,
    cache: dict[int, set[int]] | None = None,
) -> bool:
    """True gdy ta sama jednostka albo jedna leży w hierarchii drugiej."""
    if a_id is None or b_id is None:
        return False
    if a_id == b_id:
        return True
    anc_cache = cache if cache is not None else {}
    a_anc = _ancestor_id_set(a_id, anc_cache)
    return b_id in a_anc or a_id in _ancestor_id_set(b_id, anc_cache)


def build_identity_index(*, users: list[User] | None = None) -> IdentityIndex:
    """Mapa (imię, 2. imię, nazwisko) → lista użytkowników (po id rosnąco)."""
    index: IdentityIndex = {}
    if users is None:
        qs = (
            User.objects.filter(voter_profile__territorial_unit__isnull=False)
            .select_related("voter_profile", "voter_profile__territorial_unit")
            .order_by("id")
        )
        iterable = qs.iterator(chunk_size=2000)
    else:
        iterable = sorted(users, key=lambda u: u.pk)

    for user in iterable:
        key = name_key_for_user(user)
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
    key = name_key(
        first_name=first_name,
        second_name=second_name,
        last_name=last_name,
    )
    people = index.get(key) or []
    if not people:
        return None

    anc_cache: dict[int, set[int]] = {}
    local = [
        u
        for u in people
        if units_related(territorial_unit_id, _profile_unit_id(u), cache=anc_cache)
    ]
    if not local:
        return None

    known_dates = {d for u in local if (d := _profile_birth(u)) is not None}

    if birth_date is None and len(known_dates) > 1:
        # Niezgadywanie: kilka różnych dat w grupie → tylko inni bez daty.
        matches = [u for u in local if _profile_birth(u) is None]
    else:
        matches = [
            u for u in local if birth_dates_compatible(birth_date, _profile_birth(u))
        ]

    if not matches:
        return None

    def sort_key(u: User) -> tuple[int, int, int]:
        bd = _profile_birth(u)
        exact = 0 if birth_date is not None and bd == birth_date else 1
        has_date = 0 if bd is not None else 1
        return (exact, has_date, u.pk)

    matches.sort(key=sort_key)
    return matches[0]


def register_identity(index: IdentityIndex, user: User) -> None:
    key = name_key_for_user(user)
    if key is None:
        return
    bucket = index.setdefault(key, [])
    if any(u.pk == user.pk for u in bucket):
        return
    bucket.append(user)
    bucket.sort(key=lambda u: u.pk)


def _same_unit_groups(users: list[User]) -> list[list[User]]:
    by_unit: dict[int, list[User]] = {}
    for user in users:
        uid = _profile_unit_id(user)
        if uid is None:
            continue
        by_unit.setdefault(uid, []).append(user)
    return [
        sorted(group, key=lambda u: u.pk)
        for group in by_unit.values()
        if len(group) > 1
    ]


def _unit_connected_components(
    users: list[User],
    *,
    cache: dict[int, set[int]],
) -> list[list[User]]:
    """Komponenty spójności względem units_related."""
    n = len(users)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if units_related(
                _profile_unit_id(users[i]),
                _profile_unit_id(users[j]),
                cache=cache,
            ):
                union(i, j)

    buckets: dict[int, list[User]] = {}
    for i, user in enumerate(users):
        buckets.setdefault(find(i), []).append(user)
    return [sorted(g, key=lambda u: u.pk) for g in buckets.values()]


def _cluster_same_name(users: list[User]) -> list[list[User]]:
    """
    Dzieli osoby o tym samym imieniu na grupy do scalenia.
    Cross-unit tylko gdy jednostki w relacji przodek↔potomek oraz
    daty nie konfliktują; bez daty nie sklejamy różnych jednostek.
    """
    by_bd: dict[date | None, list[User]] = {}
    for user in users:
        by_bd.setdefault(_profile_birth(user), []).append(user)

    dated_keys = sorted(k for k in by_bd if k is not None)
    none_users = by_bd.get(None, [])
    clusters: list[list[User]] = []
    anc_cache: dict[int, set[int]] = {}

    if not dated_keys:
        return _same_unit_groups(none_users)

    if len(dated_keys) == 1:
        dated = by_bd[dated_keys[0]]
        used_none: set[int] = set()
        for dcomp in _unit_connected_components(dated, cache=anc_cache):
            attached = list(dcomp)
            for nu in none_users:
                if nu.pk in used_none:
                    continue
                if any(
                    units_related(
                        _profile_unit_id(nu),
                        _profile_unit_id(d),
                        cache=anc_cache,
                    )
                    for d in dcomp
                ):
                    attached.append(nu)
                    used_none.add(nu.pk)
            if len(attached) > 1:
                clusters.append(sorted(attached, key=lambda u: u.pk))
        leftover = [u for u in none_users if u.pk not in used_none]
        clusters.extend(_same_unit_groups(leftover))
        return clusters

    for dk in dated_keys:
        for comp in _unit_connected_components(by_bd[dk], cache=anc_cache):
            if len(comp) > 1:
                clusters.append(comp)
    clusters.extend(_same_unit_groups(none_users))
    return clusters


def find_duplicate_groups() -> list[tuple[NameKey, list[User]]]:
    """Grupy nierozróżnialnych użytkowników (>1 konto)."""
    index = build_identity_index()
    groups: list[tuple[NameKey, list[User]]] = []
    for key, people in index.items():
        if len(people) < 2:
            continue
        for cluster in _cluster_same_name(people):
            if len(cluster) > 1:
                groups.append((key, cluster))
    return groups


def _unit_is_descendant(child_id: int, ancestor_id: int, cache: dict[int, set[int]]) -> bool:
    if child_id == ancestor_id:
        return False
    return ancestor_id in _ancestor_id_set(child_id, cache)


def _merge_profile_data(keep: User, dup: User) -> None:
    """Przenieś znaną datę / bardziej precyzyjną jednostkę z duplikatu."""
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
    keep_uid = keep_p.territorial_unit_id
    dup_uid = dup_p.territorial_unit_id
    if keep_uid is not None and dup_uid is not None and keep_uid != dup_uid:
        cache: dict[int, set[int]] = {}
        # Zachowaj bardziej szczegółową jednostkę (potomek w drzewie).
        if _unit_is_descendant(dup_uid, keep_uid, cache):
            keep_p.territorial_unit_id = dup_uid
            updates.append("territorial_unit_id")
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
    Przed usunięciem przepisuje datę urodzenia / jednostkę na zachowane konto.
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
