"""
Budowa ElectoralDistrict.territorial_units na podstawie protokołów PKW.

Zasady:
- rada gminy / rada powiatu → obwody (precinct) z protokołów po komisjach
- sejm / senat / sejmik → gminy (z protokołów)
- wójt/burmistrz/prezydent → gmina (ze sluga)
- fallback ze sluga, gdy brak mapowania w protokole
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from django.db import transaction

from elections.models import ElectoralDistrict
from geo.models import PollingStation, TerritorialUnit
from geo.pkw import col, iter_csv_rows_from_zip, norm_teryt

BATCH = 5000


def _protocol_station_map(
    path, *, teryt_keys: tuple[str, ...], okreg_keys: tuple[str, ...]
) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for row in iter_csv_rows_from_zip(path):
        teryt = norm_teryt(col(row, *teryt_keys))
        nr = col(row, "Nr komisji")
        okreg = col(row, *okreg_keys)
        if teryt and nr and okreg:
            out[(teryt, nr)] = okreg
    return out


def _protocol_gmina_map(
    path, *, teryt_keys: tuple[str, ...], okreg_keys: tuple[str, ...]
) -> dict[str, str]:
    per_gmina: dict[str, set[str]] = defaultdict(set)
    for row in iter_csv_rows_from_zip(path):
        teryt = norm_teryt(col(row, *teryt_keys))
        okreg = col(row, *okreg_keys)
        if teryt and okreg:
            per_gmina[teryt].add(okreg)
    return {t: next(iter(s)) for t, s in per_gmina.items() if len(s) == 1}


def _load_admin() -> dict[str, dict[str, int]]:
    def by_kind(kind: str) -> dict[str, int]:
        return {
            teryt: pk
            for teryt, pk in TerritorialUnit.objects.filter(kind=kind)
            .exclude(teryt="")
            .values_list("teryt", "pk")
            if teryt
        }

    return {
        "woj": by_kind(TerritorialUnit.Kind.VOIVODESHIP),
        "powiat": by_kind(TerritorialUnit.Kind.COUNTY),
        "gmina": by_kind(TerritorialUnit.Kind.MUNICIPALITY),
    }


def _precinct_by_station_code() -> dict[str, int]:
    return dict(
        PollingStation.objects.filter(precinct_id__isnull=False)
        .exclude(code="")
        .values_list("code", "precinct_id")
    )


def _district_maps() -> dict:
    sejm: dict[str, int] = {}
    senat: dict[str, int] = {}
    sejmik: dict[tuple[str, str], int] = {}
    rada_powiat: dict[tuple[str, str], int] = {}
    rada_gminy: dict[tuple[str, str], int] = {}
    wbp: dict[str, int] = {}

    for pk, slug in ElectoralDistrict.objects.values_list("pk", "slug").iterator():
        if slug.startswith("sejm-") and slug[5:].isdigit():
            sejm[slug[5:]] = pk
        elif slug.startswith("senat-") and slug[6:].isdigit():
            senat[slug[6:]] = pk
        elif slug.startswith("sejmik-"):
            parts = slug.split("-")
            if len(parts) >= 3:
                sejmik[(parts[1], parts[2])] = pk
        elif slug.startswith("rada-powiat-"):
            rest = slug[len("rada-powiat-") :]
            key, _, nr = rest.partition("-")
            if len(key) == 4 and nr:
                rada_powiat[(key, nr)] = pk
        elif slug.startswith("rada-gminy-"):
            rest = slug[len("rada-gminy-") :]
            key, _, nr = rest.partition("-")
            if len(key) == 6 and nr:
                rada_gminy[(key, nr)] = pk
        elif slug.startswith("wbp-"):
            teryt = slug[4:]
            if len(teryt) == 6 and teryt.isdigit():
                wbp[teryt] = pk

    return {
        "sejm": sejm,
        "senat": senat,
        "sejmik": sejmik,
        "rada_powiat": rada_powiat,
        "rada_gminy": rada_gminy,
        "wbp": wbp,
    }


def build_district_unit_links(
    paths: dict,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """
    Zwraca statystyki. Zapisuje M2M ElectoralDistrict ↔ TerritorialUnit.
    """
    _log = log or (lambda _msg: None)
    admin = _load_admin()
    precinct_by_code = _precinct_by_station_code()
    maps = _district_maps()
    links: dict[int, set[int]] = defaultdict(set)

    _log("Czytanie protokołów PKW…")
    sejm_gmina = _protocol_gmina_map(
        paths["prot_sejm"],
        teryt_keys=("TERYT Gminy",),
        okreg_keys=("Nr okręgu",),
    )
    senat_station = _protocol_station_map(
        paths["prot_senat"],
        teryt_keys=("TERYT Gminy",),
        okreg_keys=("Nr okręgu",),
    )
    senat_gmina = _protocol_gmina_map(
        paths["prot_senat"],
        teryt_keys=("TERYT Gminy",),
        okreg_keys=("Nr okręgu",),
    )
    sejmik_gmina = _protocol_gmina_map(
        paths["prot_sejmik"],
        teryt_keys=("Teryt Gminy", "TERYT Gminy"),
        okreg_keys=("Nr okręgu",),
    )
    rada_powiat_station = _protocol_station_map(
        paths["prot_rada_powiatu"],
        teryt_keys=("Teryt Gminy", "TERYT Gminy"),
        okreg_keys=("Nr okręgu",),
    )
    rada_gminy_station: dict[tuple[str, str], str] = {}
    rada_gminy_station.update(
        _protocol_station_map(
            paths["prot_rada_gminy_gt20"],
            teryt_keys=("Teryt Gminy", "TERYT Gminy"),
            okreg_keys=("Nr okręgu",),
        )
    )
    rada_gminy_station.update(
        _protocol_station_map(
            paths["prot_rada_gminy_lt20"],
            teryt_keys=("Teryt Gminy", "TERYT Gminy"),
            okreg_keys=("Nr okręgu",),
        )
    )

    # ── Sejm: gminy ──────────────────────────────────────────────────────────
    for teryt, nr in sejm_gmina.items():
        did = maps["sejm"].get(nr)
        gid = admin["gmina"].get(teryt)
        if did and gid:
            links[did].add(gid)

    # ── Senat: obwody (preferowane) / gminy ───────────────────────────────────
    for (teryt, nr), okreg in senat_station.items():
        did = maps["senat"].get(okreg)
        if not did:
            continue
        pid = precinct_by_code.get(f"{teryt}-{nr}")
        if pid:
            links[did].add(pid)
        else:
            gid = admin["gmina"].get(teryt)
            if gid:
                links[did].add(gid)
    for teryt, okreg in senat_gmina.items():
        did = maps["senat"].get(okreg)
        gid = admin["gmina"].get(teryt)
        if did and gid and did not in links:
            links[did].add(gid)

    # ── Sejmik: gminy ────────────────────────────────────────────────────────
    for teryt, nr in sejmik_gmina.items():
        did = maps["sejmik"].get((teryt[:2], nr))
        gid = admin["gmina"].get(teryt)
        if did and gid:
            links[did].add(gid)

    # ── Rada powiatu: obwody ─────────────────────────────────────────────────
    for (teryt, nr), okreg in rada_powiat_station.items():
        did = maps["rada_powiat"].get((teryt[:4], okreg))
        if not did:
            continue
        pid = precinct_by_code.get(f"{teryt}-{nr}")
        if pid:
            links[did].add(pid)

    # ── Rada gminy: obwody ───────────────────────────────────────────────────
    for (teryt, nr), okreg in rada_gminy_station.items():
        did = maps["rada_gminy"].get((teryt, okreg))
        if not did:
            continue
        pid = precinct_by_code.get(f"{teryt}-{nr}")
        if pid:
            links[did].add(pid)

    # ── WBP: gmina ───────────────────────────────────────────────────────────
    for teryt, did in maps["wbp"].items():
        gid = admin["gmina"].get(teryt)
        if gid:
            links[did].add(gid)

    # ── Fallback ze sluga dla pustych okręgów ────────────────────────────────
    fallback = 0
    for nr, did in maps["sejm"].items():
        if did not in links:
            # bez protokołu — nie zgadujemy; zostaw puste
            pass
    for (woj, nr), did in maps["sejmik"].items():
        if did not in links:
            wid = admin["woj"].get(woj)
            if wid:
                links[did].add(wid)
                fallback += 1
    for (key, nr), did in maps["rada_powiat"].items():
        if did not in links:
            pid = admin["powiat"].get(key)
            if pid:
                links[did].add(pid)
                fallback += 1
    for (key, nr), did in maps["rada_gminy"].items():
        if did not in links:
            gid = admin["gmina"].get(key)
            if gid:
                links[did].add(gid)
                fallback += 1

    pkw_district_ids = set()
    for m in maps.values():
        pkw_district_ids.update(m.values())

    Through = ElectoralDistrict.territorial_units.through
    _log(f"Czyszczenie M2M dla {len(pkw_district_ids)} okręgów PKW…")
    # Usuwamy tylko powiązania okręgów PKW (nie demo prezydent-rp-kraj itd.)
    Through.objects.filter(electoraldistrict_id__in=pkw_district_ids).delete()

    rows = []
    for did, unit_ids in links.items():
        for uid in unit_ids:
            rows.append(
                Through(electoraldistrict_id=did, territorialunit_id=uid)
            )

    _log(f"Zapis {len(rows)} powiązań…")
    for i in range(0, len(rows), BATCH):
        Through.objects.bulk_create(
            rows[i : i + BATCH], batch_size=BATCH, ignore_conflicts=True
        )
        if i and i % (BATCH * 10) == 0:
            _log(f"  …{i}/{len(rows)}")

    with_units = (
        ElectoralDistrict.objects.filter(pk__in=pkw_district_ids)
        .filter(territorial_units__isnull=False)
        .distinct()
        .count()
    )
    return {
        "districts_pkw": len(pkw_district_ids),
        "districts_with_units": with_units,
        "links": len(rows),
        "fallback": fallback,
        "sejm_linked": sum(1 for d in maps["sejm"].values() if d in links),
        "senat_linked": sum(1 for d in maps["senat"].values() if d in links),
        "sejmik_linked": sum(1 for d in maps["sejmik"].values() if d in links),
        "rada_powiat_linked": sum(1 for d in maps["rada_powiat"].values() if d in links),
        "rada_gminy_linked": sum(1 for d in maps["rada_gminy"].values() if d in links),
        "wbp_linked": sum(1 for d in maps["wbp"].values() if d in links),
    }


@transaction.atomic
def rebuild_district_units(paths: dict, *, log: Callable[[str], None] | None = None) -> dict[str, int]:
    return build_district_unit_links(paths, log=log)
