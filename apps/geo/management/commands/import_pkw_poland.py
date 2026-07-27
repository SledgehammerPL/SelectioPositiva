"""
Import ogólnopolski: komisje + okręgi z danych PKW (Sejm/Senat 2023, samorząd 2024).

Użycie:
  python manage.py import_pkw_poland
  python manage.py import_pkw_poland --download
  python manage.py import_pkw_poland --skip-stations
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand

from elections.models import ElectoralDistrict, Office
from geo.models import PollingStation, TerritorialUnit
from geo.pkw import (
    SOURCES,
    col,
    fetch_source,
    iter_csv_rows_from_zip,
    norm_teryt,
)

OFFICES = [
    ("posel-sejm", "Poseł na Sejm RP", "Okręgi sejmowe (PKW 2023).", 10, False),
    ("senator", "Senator RP", "Okręgi senackie (PKW 2023).", 20, False),
    (
        "radny-sejmiku",
        "Radny sejmiku województwa",
        "Okręgi do sejmików (PKW samorząd 2024).",
        30,
        True,
    ),
    (
        "radny-powiatu",
        "Radny rady powiatu",
        "Okręgi do rad powiatów (PKW samorząd 2024).",
        40,
        True,
    ),
    (
        "radny-gminy",
        "Radny rady gminy / miasta",
        "Okręgi do rad gmin i miast (PKW samorząd 2024).",
        50,
        True,
    ),
    (
        "wojt-burmistrz-prezydent",
        "Wójt / Burmistrz / Prezydent",
        "Wybory wójtów, burmistrzów i prezydentów (PKW samorząd 2024).",
        60,
        False,
    ),
]

BATCH = 2000
UNIT_FIELDS = ["name", "kind", "teryt", "parent_id"]
DISTRICT_FIELDS = [
    "office_id",
    "name",
    "territorial_unit_id",
    "seats_count",
    "display_order",
]


class Command(BaseCommand):
    help = (
        "Importuje wszystkie polskie komisje oraz okręgi Sejmu, Senatu, "
        "sejmików, rad powiatów, rad gmin i wójtów/burmistrzów/prezydentów z PKW."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--download",
            action="store_true",
            help="Wymuś ponowne pobranie ZIP-ów z danewyborcze.kbw.gov.pl.",
        )
        parser.add_argument(
            "--skip-stations",
            action="store_true",
            help="Pomiń import komisji (tylko urzędy/okręgi/mapowania).",
        )
        parser.add_argument(
            "--skip-served",
            action="store_true",
            help="Pomiń budowę served_units.",
        )
        parser.add_argument(
            "--only-served",
            action="store_true",
            help="Tylko zbuduj served_units (wymaga wcześniejszego importu).",
        )
        parser.add_argument(
            "--only-stations",
            action="store_true",
            help="Tylko zaktualizuj komisje (bez okręgów).",
        )

    def handle(self, *args, **options):
        force = options["download"]
        self.stdout.write("Pobieranie / weryfikacja źródeł PKW…")
        paths = {key: fetch_source(key, force=force) for key in SOURCES}
        for key, path in paths.items():
            self.stdout.write(f"  {key}: {path.name} ({path.stat().st_size} B)")

        if options["only_served"]:
            poland = self._ensure_poland()
            admin = self._load_admin_maps()
            sejm = self._districts_by_prefix("sejm-")
            senat = self._districts_by_prefix("senat-")
            sejmik = self._sejmik_district_map()
            rada_powiat = self._keyed_district_map("rada-powiat-", key_len=4)
            rada_gminy = self._keyed_district_map("rada-gminy-", key_len=6)
            wbp = self._wbp_district_map()
            stats = self._build_served_units(
                paths=paths,
                poland=poland,
                admin=admin,
                sejm=sejm,
                senat=senat,
                sejmik=sejmik,
                rada_powiat=rada_powiat,
                rada_gminy=rada_gminy,
                wbp=wbp,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"served: komisje={stats['stations']} "
                    f"units={stats['unit_links']} districts={stats['district_links']} "
                    f"braki_mapowań_sejm={stats['missing']}"
                )
            )
            return

        offices = self._ensure_offices()
        poland = self._ensure_poland()
        admin = self._import_admin_units(paths["obwody"], poland)
        self.stdout.write(
            f"Jednostki admin.: woj={len(admin['woj'])} "
            f"powiat={len(admin['powiat'])} gmina={len(admin['gmina'])}"
        )

        if options["only_stations"]:
            created, updated = self._import_stations(paths["obwody"], admin["gmina"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Komisje: utworzono {created}, zaktualizowano {updated}."
                )
            )
            return

        sejm = self._import_numbered_okregi(
            paths["okregi_sejm"],
            office=offices["posel-sejm"],
            poland=poland,
            slug_prefix="sejm",
            district_name_fn=lambda nr, seat: f"Okręg nr {nr} — {seat}",
        )
        senat = self._import_numbered_okregi(
            paths["okregi_senat"],
            office=offices["senator"],
            poland=poland,
            slug_prefix="senat",
            district_name_fn=lambda nr, seat: f"Okręg senacki nr {nr} — {seat}",
        )
        sejmik = self._import_sejmik(
            paths["okregi_sejmik"], offices["radny-sejmiku"], admin["woj"]
        )
        rada_powiat = self._import_keyed_okregi(
            paths["okregi_rada_powiatu"],
            office=offices["radny-powiatu"],
            parents=admin["powiat"],
            slug_fn=lambda key, nr: f"rada-powiat-{key}-{nr}",
            key_from_row=lambda row: norm_teryt(col(row, "TERYT Powiatu"), 6)[:4],
        )
        rada_gminy = self._import_keyed_okregi(
            paths["okregi_rada_gminy"],
            office=offices["radny-gminy"],
            parents=admin["gmina"],
            slug_fn=lambda key, nr: f"rada-gminy-{key}-{nr}",
            key_from_row=lambda row: norm_teryt(col(row, "TERYT Gminy")),
        )
        mayor_count = self._import_mayors(
            paths["okregi_wbp"], offices["wojt-burmistrz-prezydent"], admin["gmina"]
        )
        wbp = self._wbp_district_map()

        self.stdout.write(
            f"Okręgi: sejm={len(sejm)} senat={len(senat)} "
            f"sejmik={len(sejmik)} rada_powiat={len(rada_powiat)} "
            f"rada_gminy={len(rada_gminy)} wbp={mayor_count}"
        )

        if not options["skip_stations"]:
            created, updated = self._import_stations(paths["obwody"], admin["gmina"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Komisje: utworzono {created}, zaktualizowano {updated}."
                )
            )

        if not options["skip_served"]:
            stats = self._build_served_units(
                paths=paths,
                poland=poland,
                admin=admin,
                sejm=sejm,
                senat=senat,
                sejmik=sejmik,
                rada_powiat=rada_powiat,
                rada_gminy=rada_gminy,
                wbp=wbp,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"served: komisje={stats['stations']} "
                    f"units={stats['unit_links']} districts={stats['district_links']} "
                    f"braki_mapowań_sejm={stats['missing']}"
                )
            )

        removed = self._cleanup_legacy_district_units()
        if removed:
            self.stdout.write(
                self.style.WARNING(
                    f"Usunięto {removed} przestarzałych TerritorialUnit (kind=district)."
                )
            )

        self.stdout.write(self.style.SUCCESS("Import PKW zakończony."))

    def _load_admin_maps(self) -> dict[str, dict[str, TerritorialUnit]]:
        woj = {
            u.teryt: u
            for u in TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.VOIVODESHIP
            ).exclude(teryt="")
        }
        powiat = {
            u.teryt: u
            for u in TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.COUNTY
            ).exclude(teryt="")
        }
        gmina = {
            u.teryt: u
            for u in TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.MUNICIPALITY
            ).exclude(teryt="")
        }
        return {"woj": woj, "powiat": powiat, "gmina": gmina}

    def _districts_by_prefix(self, prefix: str) -> dict[str, ElectoralDistrict]:
        """prefix np. 'sejm-' / 'senat-' — slug = prefix + numer."""
        out: dict[str, ElectoralDistrict] = {}
        for d in ElectoralDistrict.objects.filter(slug__startswith=prefix):
            nr = d.slug[len(prefix) :]
            if nr.isdigit():
                out[nr] = d
        return out

    def _sejmik_district_map(self) -> dict[tuple[str, str], ElectoralDistrict]:
        out: dict[tuple[str, str], ElectoralDistrict] = {}
        for d in ElectoralDistrict.objects.filter(slug__startswith="sejmik-"):
            parts = d.slug.split("-")
            if len(parts) >= 3:
                out[(parts[1], parts[2])] = d
        return out

    def _keyed_district_map(
        self, prefix: str, *, key_len: int
    ) -> dict[tuple[str, str], ElectoralDistrict]:
        out: dict[tuple[str, str], ElectoralDistrict] = {}
        for d in ElectoralDistrict.objects.filter(slug__startswith=prefix):
            rest = d.slug[len(prefix) :]
            key, _, nr = rest.partition("-")
            if len(key) == key_len and nr:
                out[(key, nr)] = d
        return out

    def _wbp_district_map(self) -> dict[str, ElectoralDistrict]:
        out: dict[str, ElectoralDistrict] = {}
        for d in ElectoralDistrict.objects.filter(slug__startswith="wbp-"):
            teryt = d.slug[4:]
            if len(teryt) == 6 and teryt.isdigit():
                out[teryt] = d
        return out

    def _cleanup_legacy_district_units(self) -> int:
        """Usuwa TerritorialUnit kind=district (okręgi nie należą do geo)."""
        from elections.models import Candidate

        district_ids = list(
            TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.DISTRICT
            ).values_list("pk", flat=True)
        )
        if not district_ids:
            return 0
        poland = TerritorialUnit.objects.filter(slug="polska").first()
        parent_map = dict(
            TerritorialUnit.objects.filter(pk__in=district_ids).values_list(
                "pk", "parent_id"
            )
        )

        def resolve(uid: int | None) -> int | None:
            seen: set[int] = set()
            while uid and uid in parent_map:
                if uid in seen:
                    return poland.pk if poland else None
                seen.add(uid)
                uid = parent_map.get(uid)
            return uid or (poland.pk if poland else None)

        children = list(
            TerritorialUnit.objects.filter(parent_id__in=district_ids).only(
                "id", "parent_id"
            )
        )
        for child in children:
            child.parent_id = resolve(child.parent_id)
        if children:
            TerritorialUnit.objects.bulk_update(
                children, ["parent_id"], batch_size=1000
            )

        eds = list(
            ElectoralDistrict.objects.filter(
                territorial_unit_id__in=district_ids
            ).only("id", "territorial_unit_id")
        )
        for ed in eds:
            ed.territorial_unit_id = resolve(ed.territorial_unit_id)
        if eds:
            ElectoralDistrict.objects.bulk_update(
                eds, ["territorial_unit_id"], batch_size=2000
            )

        stations = list(
            PollingStation.objects.filter(
                territorial_unit_id__in=district_ids
            ).only("id", "territorial_unit_id")
        )
        for st in stations:
            st.territorial_unit_id = resolve(st.territorial_unit_id)
        if stations:
            PollingStation.objects.bulk_update(
                stations, ["territorial_unit_id"], batch_size=1000
            )

        cands = list(
            Candidate.objects.filter(
                residence_municipality_id__in=district_ids
            ).only("id", "residence_municipality_id")
        )
        for cand in cands:
            cand.residence_municipality_id = resolve(cand.residence_municipality_id)
        if cands:
            Candidate.objects.bulk_update(
                cands, ["residence_municipality_id"], batch_size=1000
            )

        PollingStation.served_units.through.objects.filter(
            territorialunit_id__in=district_ids
        ).delete()

        deleted, _ = TerritorialUnit.objects.filter(
            kind=TerritorialUnit.Kind.DISTRICT
        ).delete()
        return deleted

    def _log(self, msg: str) -> None:
        safe = msg.encode("ascii", "replace").decode("ascii")
        self.stdout.write(safe)
        self.stdout.flush()

    def _ensure_offices(self) -> dict[str, Office]:
        out: dict[str, Office] = {}
        for slug, name, desc, order, residence in OFFICES:
            office, _ = Office.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": desc,
                    "is_open": True,
                    "display_order": order,
                    "requires_local_residence": residence,
                },
            )
            out[slug] = office
        return out

    def _ensure_poland(self) -> TerritorialUnit:
        poland, _ = TerritorialUnit.objects.update_or_create(
            slug="polska",
            defaults={
                "name": "Polska",
                "kind": TerritorialUnit.Kind.COUNTRY,
                "teryt": "",
                "parent": None,
            },
        )
        return poland

    def _bulk_upsert_units(self, specs: list[dict]) -> dict[str, TerritorialUnit]:
        """specs: {slug, name, kind, teryt, parent_id} → map slug→unit."""
        if not specs:
            return {}
        result: dict[str, TerritorialUnit] = {}
        for i in range(0, len(specs), BATCH):
            chunk = specs[i : i + BATCH]
            slugs = [s["slug"] for s in chunk]
            existing = {
                u.slug: u
                for u in TerritorialUnit.objects.filter(slug__in=slugs)
            }
            to_create: list[TerritorialUnit] = []
            to_update: list[TerritorialUnit] = []
            for s in chunk:
                cur = existing.get(s["slug"])
                if cur is None:
                    to_create.append(
                        TerritorialUnit(
                            slug=s["slug"],
                            name=s["name"][:200],
                            kind=s["kind"],
                            teryt=s.get("teryt") or "",
                            parent_id=s.get("parent_id"),
                        )
                    )
                else:
                    cur.name = s["name"][:200]
                    cur.kind = s["kind"]
                    cur.teryt = s.get("teryt") or ""
                    cur.parent_id = s.get("parent_id")
                    to_update.append(cur)
            if to_create:
                TerritorialUnit.objects.bulk_create(to_create, batch_size=BATCH)
            if to_update:
                TerritorialUnit.objects.bulk_update(
                    to_update, UNIT_FIELDS, batch_size=BATCH
                )
            for u in TerritorialUnit.objects.filter(slug__in=slugs):
                result[u.slug] = u
            if (i // BATCH) % 5 == 0:
                self._log(f"  jednostki {min(i + BATCH, len(specs))}/{len(specs)}")
        return result

    def _bulk_upsert_districts(self, specs: list[dict]) -> None:
        """specs: {slug, office_id, name, territorial_unit_id, seats_count, display_order}."""
        if not specs:
            return
        for i in range(0, len(specs), BATCH):
            chunk = specs[i : i + BATCH]
            slugs = [s["slug"] for s in chunk]
            existing = {
                d.slug: d
                for d in ElectoralDistrict.objects.filter(slug__in=slugs)
            }
            to_create: list[ElectoralDistrict] = []
            to_update: list[ElectoralDistrict] = []
            for s in chunk:
                seats = max(1, int(s.get("seats_count") or 1))
                cur = existing.get(s["slug"])
                if cur is None:
                    to_create.append(
                        ElectoralDistrict(
                            slug=s["slug"],
                            office_id=s["office_id"],
                            name=s["name"][:200],
                            territorial_unit_id=s["territorial_unit_id"],
                            seats_count=seats,
                            display_order=int(s.get("display_order") or 0),
                        )
                    )
                else:
                    cur.office_id = s["office_id"]
                    cur.name = s["name"][:200]
                    cur.territorial_unit_id = s["territorial_unit_id"]
                    cur.seats_count = seats
                    cur.display_order = int(s.get("display_order") or 0)
                    to_update.append(cur)
            if to_create:
                ElectoralDistrict.objects.bulk_create(to_create, batch_size=BATCH)
            if to_update:
                ElectoralDistrict.objects.bulk_update(
                    to_update, DISTRICT_FIELDS, batch_size=BATCH
                )
            if (i // BATCH) % 5 == 0:
                self._log(f"  okręgi {min(i + BATCH, len(specs))}/{len(specs)}")

    def _import_admin_units(
        self, obwody_path, poland: TerritorialUnit
    ) -> dict[str, dict[str, TerritorialUnit]]:
        self._log("Import jednostek administracyjnych…")
        woj_names: dict[str, str] = {}
        powiat_names: dict[str, tuple[str, str]] = {}
        gmina_rows: dict[str, tuple[str, str]] = {}

        for row in iter_csv_rows_from_zip(obwody_path):
            teryt = norm_teryt(col(row, "TERYT gminy", "TERYT Gminy"))
            if len(teryt) != 6:
                continue
            woj_code = teryt[:2]
            powiat_code = teryt[:4]
            woj_names[woj_code] = col(row, "Województwo")
            powiat_names[powiat_code] = (woj_code, col(row, "Powiat"))
            gmina_rows[teryt] = (powiat_code, col(row, "Gmina"))

        woj_map = self._bulk_upsert_units(
            [
                {
                    "slug": f"woj-{code}",
                    "name": f"Województwo {name}",
                    "kind": TerritorialUnit.Kind.VOIVODESHIP,
                    "teryt": code,
                    "parent_id": poland.pk,
                }
                for code, name in sorted(woj_names.items())
            ]
        )
        woj = {code: woj_map[f"woj-{code}"] for code in woj_names}

        powiat_map = self._bulk_upsert_units(
            [
                {
                    "slug": f"powiat-{code}",
                    "name": f"Powiat {name}",
                    "kind": TerritorialUnit.Kind.COUNTY,
                    "teryt": code,
                    "parent_id": woj[woj_code].pk,
                }
                for code, (woj_code, name) in sorted(powiat_names.items())
            ]
        )
        powiat = {code: powiat_map[f"powiat-{code}"] for code in powiat_names}

        gmina_map = self._bulk_upsert_units(
            [
                {
                    "slug": f"gmina-{teryt}",
                    "name": name,
                    "kind": TerritorialUnit.Kind.MUNICIPALITY,
                    "teryt": teryt,
                    "parent_id": powiat[powiat_code].pk,
                }
                for teryt, (powiat_code, name) in sorted(gmina_rows.items())
            ]
        )
        gmina = {teryt: gmina_map[f"gmina-{teryt}"] for teryt in gmina_rows}
        return {"woj": woj, "powiat": powiat, "gmina": gmina}

    def _import_numbered_okregi(
        self,
        path,
        *,
        office: Office,
        poland: TerritorialUnit,
        slug_prefix: str,
        district_name_fn,
    ) -> dict[str, ElectoralDistrict]:
        self._log(f"Import okręgów {slug_prefix}…")
        district_specs = []
        numbers: list[str] = []
        for row in iter_csv_rows_from_zip(path):
            nr = col(row, "Numer okręgu")
            seats = int(col(row, "Liczba mandatów") or "1")
            seat = col(row, "Siedziba OKW")
            slug = f"{slug_prefix}-{nr}"
            numbers.append(nr)
            district_specs.append(
                {
                    "slug": slug,
                    "office_id": office.pk,
                    "name": district_name_fn(nr, seat),
                    "territorial_unit_id": poland.pk,
                    "seats_count": seats,
                    "display_order": int(nr) if str(nr).isdigit() else 0,
                }
            )
        self._bulk_upsert_districts(district_specs)
        by_slug = {
            d.slug: d
            for d in ElectoralDistrict.objects.filter(
                slug__in=[f"{slug_prefix}-{nr}" for nr in numbers]
            )
        }
        return {nr: by_slug[f"{slug_prefix}-{nr}"] for nr in numbers if f"{slug_prefix}-{nr}" in by_slug}

    def _import_sejmik(
        self, path, office: Office, woj: dict[str, TerritorialUnit]
    ) -> dict[tuple[str, str], ElectoralDistrict]:
        self._log("Import okręgów sejmików…")
        district_specs = []
        keys: list[tuple[str, str]] = []
        for row in iter_csv_rows_from_zip(path):
            woj_teryt = norm_teryt(col(row, "TERYT Województwa"), 6)[:2]
            nr = col(row, "Numer okręgu")
            seats = int(col(row, "Liczba mandatów") or "1")
            organ = col(row, "Wybierany organ")
            parent = woj.get(woj_teryt)
            if parent is None:
                continue
            slug = f"sejmik-{woj_teryt}-{nr}"
            keys.append((woj_teryt, nr))
            district_specs.append(
                {
                    "slug": slug,
                    "office_id": office.pk,
                    "name": f"{organ} — okręg {nr}",
                    "territorial_unit_id": parent.pk,
                    "seats_count": seats,
                    "display_order": int(nr) if str(nr).isdigit() else 0,
                }
            )
        self._bulk_upsert_districts(district_specs)
        return self._sejmik_district_map()

    def _import_keyed_okregi(
        self,
        path,
        *,
        office: Office,
        parents: dict[str, TerritorialUnit],
        slug_fn,
        key_from_row,
    ) -> dict[tuple[str, str], ElectoralDistrict]:
        """
        Okręgi rady gminy/powiatu: ElectoralDistrict wskazuje na gminę/powiat,
        bez tworzenia TerritorialUnit per okręg.
        """
        self._log(f"Import okręgów ({office.slug})…")
        district_specs = []
        keys: list[tuple[str, str]] = []
        seen: set[str] = set()
        skipped = 0
        for row in iter_csv_rows_from_zip(path):
            key = key_from_row(row)
            nr = col(row, "Numer okręgu")
            if not key or not nr:
                continue
            slug = slug_fn(key, nr)
            if slug in seen:
                continue
            seen.add(slug)
            parent = parents.get(key)
            if parent is None:
                skipped += 1
                continue
            seats = int(col(row, "Liczba mandatów") or "1")
            organ = col(row, "Wybierany organ")
            keys.append((key, nr))
            district_specs.append(
                {
                    "slug": slug,
                    "office_id": office.pk,
                    "name": f"{organ} — okręg {nr}",
                    "territorial_unit_id": parent.pk,
                    "seats_count": seats,
                    "display_order": int(nr) if str(nr).isdigit() else 0,
                }
            )
        self._bulk_upsert_districts(district_specs)
        if skipped:
            self._log(f"  pominięto {skipped} wierszy bez jednostki admin.")
        slugs = [slug_fn(k, n) for k, n in keys]
        by_slug = {
            d.slug: d for d in ElectoralDistrict.objects.filter(slug__in=slugs)
        }
        return {(k, n): by_slug[slug_fn(k, n)] for k, n in keys if slug_fn(k, n) in by_slug}

    def _import_mayors(
        self, path, office: Office, gmina: dict[str, TerritorialUnit]
    ) -> int:
        self._log("Import mandatów wójt/burmistrz/prezydent…")
        specs = []
        for row in iter_csv_rows_from_zip(path):
            teryt = norm_teryt(col(row, "TERYT Gminy"))
            unit = gmina.get(teryt)
            if unit is None:
                continue
            organ = col(row, "Wybierany organ")
            specs.append(
                {
                    "slug": f"wbp-{teryt}",
                    "office_id": office.pk,
                    "name": organ,
                    "territorial_unit_id": unit.pk,
                    "seats_count": 1,
                    "display_order": 0,
                }
            )
        self._bulk_upsert_districts(specs)
        return len(specs)

    def _import_stations(
        self, path, gminy: dict[str, TerritorialUnit]
    ) -> tuple[int, int]:
        self._log("Import komisji wyborczych…")
        existing = {
            s.code: s.id for s in PollingStation.objects.only("id", "code").iterator()
        }
        to_create: list[PollingStation] = []
        to_update: list[PollingStation] = []
        created = updated = 0

        for row in iter_csv_rows_from_zip(path):
            teryt = norm_teryt(col(row, "TERYT gminy", "TERYT Gminy"))
            numer = col(row, "Numer")
            if not teryt or not numer:
                continue
            gmina = gminy.get(teryt)
            if gmina is None:
                continue
            code = f"{teryt}-{numer}"
            try:
                number = int(numer)
            except ValueError:
                number = None
            name = (col(row, "Siedziba") or f"Obwód nr {numer}")[:200]
            address = (col(row, "Pełna siedziba") or name)[:300]
            streets = col(row, "Opis granic")
            defaults = {
                "name": name,
                "number": number,
                "territorial_unit_id": gmina.pk,
                "address": address,
                "streets_served": streets,
            }
            pk = existing.get(code)
            if pk is None:
                to_create.append(PollingStation(code=code, **defaults))
                created += 1
            else:
                to_update.append(PollingStation(pk=pk, code=code, **defaults))
                updated += 1

            if len(to_create) >= BATCH:
                PollingStation.objects.bulk_create(to_create, batch_size=BATCH)
                to_create.clear()
            if len(to_update) >= BATCH:
                PollingStation.objects.bulk_update(
                    to_update,
                    [
                        "name",
                        "number",
                        "territorial_unit_id",
                        "address",
                        "streets_served",
                    ],
                    batch_size=BATCH,
                )
                to_update.clear()

        if to_create:
            PollingStation.objects.bulk_create(to_create, batch_size=BATCH)
        if to_update:
            PollingStation.objects.bulk_update(
                to_update,
                ["name", "number", "territorial_unit_id", "address", "streets_served"],
                batch_size=BATCH,
            )
        return created, updated

    def _protocol_station_map(
        self, path, *, teryt_keys: tuple[str, ...], okreg_keys: tuple[str, ...]
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
        self, path, *, teryt_keys: tuple[str, ...], okreg_keys: tuple[str, ...]
    ) -> dict[str, str]:
        per_gmina: dict[str, set[str]] = defaultdict(set)
        for row in iter_csv_rows_from_zip(path):
            teryt = norm_teryt(col(row, *teryt_keys))
            okreg = col(row, *okreg_keys)
            if teryt and okreg:
                per_gmina[teryt].add(okreg)
        return {t: next(iter(s)) for t, s in per_gmina.items() if len(s) == 1}

    def _build_served_units(
        self,
        *,
        paths,
        poland: TerritorialUnit,
        admin,
        sejm: dict[str, ElectoralDistrict],
        senat: dict[str, ElectoralDistrict],
        sejmik: dict[tuple[str, str], ElectoralDistrict],
        rada_powiat: dict[tuple[str, str], ElectoralDistrict],
        rada_gminy: dict[tuple[str, str], ElectoralDistrict],
        wbp: dict[str, ElectoralDistrict],
    ) -> dict[str, int]:
        self._log("Budowa mapowan komisja -> jednostki admin + okregi...")
        sejm_gmina = self._protocol_gmina_map(
            paths["prot_sejm"],
            teryt_keys=("TERYT Gminy",),
            okreg_keys=("Nr okręgu",),
        )
        senat_station = self._protocol_station_map(
            paths["prot_senat"],
            teryt_keys=("TERYT Gminy",),
            okreg_keys=("Nr okręgu",),
        )
        senat_gmina = self._protocol_gmina_map(
            paths["prot_senat"],
            teryt_keys=("TERYT Gminy",),
            okreg_keys=("Nr okręgu",),
        )
        sejmik_gmina = self._protocol_gmina_map(
            paths["prot_sejmik"],
            teryt_keys=("Teryt Gminy", "TERYT Gminy"),
            okreg_keys=("Nr okręgu",),
        )
        sejmik_by_gmina: dict[str, ElectoralDistrict] = {}
        for teryt, nr in sejmik_gmina.items():
            d = sejmik.get((teryt[:2], nr))
            if d:
                sejmik_by_gmina[teryt] = d

        rada_powiat_station = self._protocol_station_map(
            paths["prot_rada_powiatu"],
            teryt_keys=("Teryt Gminy", "TERYT Gminy"),
            okreg_keys=("Nr okręgu",),
        )
        rada_gminy_station: dict[tuple[str, str], str] = {}
        rada_gminy_station.update(
            self._protocol_station_map(
                paths["prot_rada_gminy_gt20"],
                teryt_keys=("Teryt Gminy", "TERYT Gminy"),
                okreg_keys=("Nr okręgu",),
            )
        )
        rada_gminy_station.update(
            self._protocol_station_map(
                paths["prot_rada_gminy_lt20"],
                teryt_keys=("Teryt Gminy", "TERYT Gminy"),
                okreg_keys=("Nr okręgu",),
            )
        )

        ThroughUnits = PollingStation.served_units.through
        ThroughDistricts = PollingStation.served_districts.through
        qs = PollingStation.objects.select_related("territorial_unit").filter(
            code__regex=r"^[0-9]{6}-[0-9]+$"
        )
        pkw_ids = list(qs.values_list("id", flat=True))
        pkw_id_set = set(pkw_ids)
        self._log(f"Czyszczenie served_* dla {len(pkw_ids)} komisji PKW…")
        for i in range(0, len(pkw_ids), 5000):
            chunk = pkw_ids[i : i + 5000]
            ThroughUnits.objects.filter(pollingstation_id__in=chunk).delete()
            ThroughDistricts.objects.filter(pollingstation_id__in=chunk).delete()

        unit_links: list = []
        district_links: list = []
        missing = 0
        linked_stations = 0

        for station in qs.iterator(chunk_size=2000):
            teryt = station.territorial_unit.teryt or ""
            if len(teryt) != 6:
                teryt = station.code.split("-")[0]
            nr = str(station.number or station.code.split("-")[-1])
            woj = admin["woj"].get(teryt[:2])
            powiat = admin["powiat"].get(teryt[:4])
            gmina = admin["gmina"].get(teryt)

            unit_ids: set[int] = {poland.pk}
            if woj:
                unit_ids.add(woj.pk)
            if powiat:
                unit_ids.add(powiat.pk)
            if gmina:
                unit_ids.add(gmina.pk)

            district_ids: set[int] = set()

            sejm_nr = sejm_gmina.get(teryt)
            if sejm_nr and sejm_nr in sejm:
                district_ids.add(sejm[sejm_nr].pk)
            else:
                missing += 1

            senat_nr = senat_station.get((teryt, nr)) or senat_gmina.get(teryt)
            if senat_nr and senat_nr in senat:
                district_ids.add(senat[senat_nr].pk)

            sejmik_d = sejmik_by_gmina.get(teryt)
            if sejmik_d:
                district_ids.add(sejmik_d.pk)

            rp_nr = rada_powiat_station.get((teryt, nr))
            if rp_nr:
                rp_d = rada_powiat.get((teryt[:4], rp_nr))
                if rp_d:
                    district_ids.add(rp_d.pk)

            rg_nr = rada_gminy_station.get((teryt, nr))
            if rg_nr:
                rg_d = rada_gminy.get((teryt, rg_nr))
                if rg_d:
                    district_ids.add(rg_d.pk)

            wbp_d = wbp.get(teryt)
            if wbp_d:
                district_ids.add(wbp_d.pk)

            for uid in unit_ids:
                unit_links.append(
                    ThroughUnits(
                        pollingstation_id=station.pk, territorialunit_id=uid
                    )
                )
            for did in district_ids:
                district_links.append(
                    ThroughDistricts(
                        pollingstation_id=station.pk, electoraldistrict_id=did
                    )
                )
            linked_stations += 1

            if len(unit_links) >= 10000 or len(district_links) >= 10000:
                if unit_links:
                    ThroughUnits.objects.bulk_create(
                        unit_links, batch_size=5000, ignore_conflicts=True
                    )
                    unit_links.clear()
                if district_links:
                    ThroughDistricts.objects.bulk_create(
                        district_links, batch_size=5000, ignore_conflicts=True
                    )
                    district_links.clear()
                self._log(f"  …powiązano {linked_stations} komisji")

        if unit_links:
            ThroughUnits.objects.bulk_create(
                unit_links, batch_size=5000, ignore_conflicts=True
            )
        if district_links:
            ThroughDistricts.objects.bulk_create(
                district_links, batch_size=5000, ignore_conflicts=True
            )

        return {
            "stations": linked_stations,
            "unit_links": ThroughUnits.objects.filter(
                pollingstation_id__in=pkw_id_set
            ).count(),
            "district_links": ThroughDistricts.objects.filter(
                pollingstation_id__in=pkw_id_set
            ).count(),
            "missing": missing,
        }
