"""
Zasiewa dane demo: jednostki terytorialne → obwody → komisje → okręgi → użytkownicy.

Użycie: python manage.py seed_demo
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from elections.models import ElectoralDistrict, Office, Party, VoterProfile
from geo.models import PollingStation, TerritorialUnit

User = get_user_model()


def _box(west: float, south: float, east: float, north: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }


def _unit(slug, name, kind, parent=None, boundary=None, lat=None, lng=None):
    defaults = {"name": name, "kind": kind, "parent": parent}
    if boundary:
        defaults["boundary"] = boundary
    if lat:
        defaults["center_lat"] = lat
    if lng:
        defaults["center_lng"] = lng
    obj, _ = TerritorialUnit.objects.update_or_create(slug=slug, defaults=defaults)
    return obj


class Command(BaseCommand):
    help = "Tworzy dane demo (jednostki, okręgi, komisje, użytkownicy-kandydaci)."

    @transaction.atomic
    def handle(self, *args, **options):
        # ── Jednostki administracyjne ────────────────────────────────────────
        poland = _unit(
            "polska", "Polska", TerritorialUnit.Kind.COUNTRY,
            boundary=_box(14.1, 49.0, 24.2, 54.9), lat="52.100000", lng="19.400000",
        )
        slask = _unit(
            "slaskie", "Województwo Śląskie", TerritorialUnit.Kind.VOIVODESHIP, poland,
            boundary=_box(18.0, 49.35, 19.85, 50.95), lat="50.250000", lng="19.000000",
        )
        gmina = _unit(
            "gmina-katowice", "Gmina Katowice", TerritorialUnit.Kind.MUNICIPALITY, slask,
            boundary=_box(18.92, 50.20, 19.15, 50.33), lat="50.264900", lng="19.023800",
        )
        mazowsze = _unit(
            "mazowieckie", "Województwo Mazowieckie", TerritorialUnit.Kind.VOIVODESHIP, poland,
            boundary=_box(19.5, 51.5, 22.0, 53.5), lat="52.230000", lng="21.010000",
        )
        gmina_waw = _unit(
            "gmina-warszawa", "Gmina Warszawa", TerritorialUnit.Kind.MUNICIPALITY, mazowsze,
            boundary=_box(20.85, 52.15, 21.2, 52.35), lat="52.229700", lng="21.012200",
        )

        # ── Obwody wyborcze (precinct) — podpoziom gminy ─────────────────────
        precinct_ktw = _unit(
            "obwod-katowice-1", "Obwód 1 Katowice (Śródmieście)",
            TerritorialUnit.Kind.PRECINCT, gmina,
        )
        precinct_waw = _unit(
            "obwod-warszawa-1", "Obwód 1 Warszawa (Śródmieście)",
            TerritorialUnit.Kind.PRECINCT, gmina_waw,
        )

        # ── Komisje wyborcze (przypisane do obwodów) ─────────────────────────
        station, _ = PollingStation.objects.update_or_create(
            code="KTW-001",
            defaults={
                "name": "Obwodowa Komisja Wyborcza nr 1",
                "number": 1,
                "precinct": precinct_ktw,
                "address": "ul. Młyńska 4, 40-098 Katowice",
                "streets_served": "ul. Młyńska, Stawowa (okolice rynku).",
                "latitude": "50.259100",
                "longitude": "19.021600",
            },
        )
        station_waw, _ = PollingStation.objects.update_or_create(
            code="WAW-001",
            defaults={
                "name": "Obwodowa Komisja Wyborcza nr 1 — Warszawa",
                "number": 1,
                "precinct": precinct_waw,
                "address": "ul. Senatorska 2, 00-075 Warszawa",
                "streets_served": "ul. Senatorska, Miodowa (fragment).",
                "latitude": "52.244500",
                "longitude": "21.013000",
            },
        )

        # ── Urzędy ───────────────────────────────────────────────────────────
        offices_data = [
            ("prezydent-rp", "Prezydent RP", "Wybory ogólnokrajowe.", 1),
            ("eurodeputowany", "Poseł do Europarlamentu", "Mandaty europejskie.", 2),
            ("posel-sejm", "Poseł na Sejm RP", "Wybory do Sejmu.", 3),
            ("senator", "Senator RP", "Wybory do Senatu.", 4),
            ("prezydent-miasta", "Prezydent Miasta", "Wybory samorządowe — prezydent.", 5),
            ("radny", "Radny Rady Miasta", "Wybory samorządowe — rada.", 6),
            ("radny-gminy", "Radny rady gminy / miasta", "Okręgi do rad gmin.", 50),
            ("radny-powiatu", "Radny rady powiatu", "Okręgi do rad powiatów.", 40),
            ("radny-sejmiku", "Radny sejmiku województwa", "Okręgi do sejmików.", 30),
        ]
        offices: dict[str, Office] = {}
        for slug, name, desc, order in offices_data:
            office, _ = Office.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": desc,
                    "is_open": True,
                    "display_order": order,
                },
            )
            offices[slug] = office

        # ── Partie ───────────────────────────────────────────────────────────
        parties = {}
        for slug, pname, abbr, order in [
            ("partia-a", "Partia Demo A", "PDA", 1),
            ("partia-b", "Partia Demo B", "PDB", 2),
        ]:
            party, _ = Party.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": pname,
                    "abbreviation": abbr,
                    "is_active": True,
                    "display_order": order,
                },
            )
            parties[slug] = party

        # ── Okręgi wyborcze → territorial_units (M2M) ───────────────────────
        # Każdy okręg jest powiązany z węzłem hierarchii, którego obwody są uprawnione.
        districts_spec = [
            # (slug, office_slug, name, [units], seats, min_age, order)
            ("prezydent-rp-kraj", "prezydent-rp", "Okręg ogólnopolski", [poland], 1, 35, 1),
            ("euro-slask", "eurodeputowany", "Okręg — Województwo Śląskie", [slask], 2, 18, 1),
            ("sejm-31-katowice", "posel-sejm", "Okręg nr 31 — Katowice", [poland], 12, 18, 1),
            ("senat-katowice", "senator", "Okręg senacki Katowice", [poland], 1, 30, 1),
            ("prezydent-katowice", "prezydent-miasta", "Gmina Katowice", [gmina], 1, 18, 1),
            ("rada-katowice", "radny", "Okręg miejski Katowice", [gmina], 3, 18, 1),
            ("prezydent-warszawa", "prezydent-miasta", "Gmina Warszawa", [gmina_waw], 1, 18, 2),
            ("sejm-19-warszawa", "posel-sejm", "Okręg nr 19 — Warszawa", [poland], 20, 18, 2),
        ]

        created_districts: dict[str, ElectoralDistrict] = {}
        for dslug, oslug, dname, units, seats, min_age, order in districts_spec:
            district, _ = ElectoralDistrict.objects.update_or_create(
                slug=dslug,
                defaults={
                    "office": offices[oslug],
                    "name": dname,
                    "seats_count": seats,
                    "min_age": min_age,
                    "display_order": order,
                },
            )
            district.territorial_units.set(units)
            created_districts[dslug] = district

        # ── Użytkownicy-kandydaci demo ────────────────────────────────────────
        candidates_data = [
            ("anna",     "Kowalska",     date(1975, 3, 15),  station),
            ("jan",      "Nowak",        date(1968, 7, 22),  station),
            ("piotr",    "Wisniewski",   date(1982, 1, 5),   station),
            ("maria",    "Zielinska",    date(1990, 11, 30), station),
            ("ewa",      "Maj",          date(1978, 6, 10),  station),
            ("tomasz",   "Krol",         date(1985, 9, 18),  station),
            ("barbara",  "Lewandowska",  date(1972, 4, 25),  station),
            ("hanna",    "Nowicka",      date(1980, 2, 14),  station_waw),
            ("stefan",   "Borkowski",    date(1965, 12, 3),  station_waw),
            ("julia",    "Malinowska",   date(1993, 8, 27),  station_waw),
            ("adam",     "Warszawski",   date(1977, 5, 9),   station_waw),
        ]
        for username, last_name, birth_date, st in candidates_data:
            u, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": username.capitalize(),
                    "last_name": last_name,
                    "email": f"{username}@selectio.local",
                },
            )
            if created:
                u.set_password("demo1234")
                u.save()
            VoterProfile.objects.update_or_create(
                user=u,
                defaults={
                    "polling_station": st,
                    "territorial_unit": st.precinct,
                    "birth_date": birth_date,
                },
            )

        # ── Demo-wyborca główny ───────────────────────────────────────────────
        user, created = User.objects.get_or_create(
            username="demo",
            defaults={
                "email": "demo@selectio.local",
                "first_name": "Anna",
                "last_name": "Wyborcza",
            },
        )
        if created or not user.has_usable_password():
            user.set_password("demo1234")
            user.save()

        # Preferuj prawdziwą komisję PKW Katowice, jeśli jest po imporcie.
        pkw = PollingStation.objects.filter(code="246901-1").first()
        effective_station = pkw or station
        effective_precinct = effective_station.precinct or precinct_ktw

        VoterProfile.objects.update_or_create(
            user=user,
            defaults={
                "polling_station": effective_station,
                "territorial_unit": effective_precinct,
                "birth_date": date(1990, 5, 12),
            },
        )

        self.stdout.write(self.style.SUCCESS("Seed demo OK."))
        self.stdout.write("  Login: demo / demo1234")
        self.stdout.write(f"  Komisja: {effective_station}")
        self.stdout.write(f"  Alternatywna komisja (WAW): {station_waw}")
        self.stdout.write(
            f"  Kandydaci demo: {', '.join(u for u, *_ in candidates_data)}"
        )
