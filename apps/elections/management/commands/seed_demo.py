"""
Zasiewa hierarchię terytorialną + urzędy + okręgi z seats_count + demo użytkownika.

Użycie: python manage.py seed_demo
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from elections.models import Candidate, ElectoralDistrict, Office, VoterProfile
from geo.models import PollingStation, TerritorialUnit


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


class Command(BaseCommand):
    help = "Tworzy dane demo z okręgami wyborczymi (seats_count na okręgu)."

    @transaction.atomic
    def handle(self, *args, **options):
        poland, _ = TerritorialUnit.objects.update_or_create(
            slug="polska",
            defaults={
                "name": "Polska",
                "kind": TerritorialUnit.Kind.COUNTRY,
                "parent": None,
                "boundary": _box(14.1, 49.0, 24.2, 54.9),
                "center_lat": "52.100000",
                "center_lng": "19.400000",
            },
        )
        slask, _ = TerritorialUnit.objects.update_or_create(
            slug="slaskie",
            defaults={
                "name": "Województwo Śląskie",
                "kind": TerritorialUnit.Kind.VOIVODESHIP,
                "parent": poland,
                "boundary": _box(18.0, 49.35, 19.85, 50.95),
                "center_lat": "50.250000",
                "center_lng": "19.000000",
            },
        )
        okreg, _ = TerritorialUnit.objects.update_or_create(
            slug="okreg-katowice",
            defaults={
                "name": "Okręg wyborczy Katowice",
                "kind": TerritorialUnit.Kind.DISTRICT,
                "parent": slask,
                "boundary": _box(18.80, 50.12, 19.40, 50.42),
                "center_lat": "50.270000",
                "center_lng": "19.050000",
            },
        )
        gmina, _ = TerritorialUnit.objects.update_or_create(
            slug="gmina-katowice",
            defaults={
                "name": "Gmina Katowice",
                "kind": TerritorialUnit.Kind.MUNICIPALITY,
                "parent": okreg,
                "boundary": _box(18.92, 50.20, 19.15, 50.33),
                "center_lat": "50.264900",
                "center_lng": "19.023800",
            },
        )
        okreg_miejski, _ = TerritorialUnit.objects.update_or_create(
            slug="okreg-miejski-katowice",
            defaults={
                "name": "Okręg miejski Katowice",
                "kind": TerritorialUnit.Kind.DISTRICT,
                "parent": gmina,
                "boundary": _box(18.96, 50.22, 19.10, 50.31),
                "center_lat": "50.260000",
                "center_lng": "19.020000",
            },
        )

        mazowsze, _ = TerritorialUnit.objects.update_or_create(
            slug="mazowieckie",
            defaults={
                "name": "Województwo Mazowieckie",
                "kind": TerritorialUnit.Kind.VOIVODESHIP,
                "parent": poland,
                "boundary": _box(19.5, 51.5, 22.0, 53.5),
                "center_lat": "52.230000",
                "center_lng": "21.010000",
            },
        )
        okreg_waw, _ = TerritorialUnit.objects.update_or_create(
            slug="okreg-warszawa",
            defaults={
                "name": "Okręg wyborczy Warszawa",
                "kind": TerritorialUnit.Kind.DISTRICT,
                "parent": mazowsze,
                "boundary": _box(20.7, 52.05, 21.3, 52.4),
                "center_lat": "52.230000",
                "center_lng": "21.010000",
            },
        )
        gmina_waw, _ = TerritorialUnit.objects.update_or_create(
            slug="gmina-warszawa",
            defaults={
                "name": "Gmina Warszawa",
                "kind": TerritorialUnit.Kind.MUNICIPALITY,
                "parent": okreg_waw,
                "boundary": _box(20.85, 52.15, 21.2, 52.35),
                "center_lat": "52.229700",
                "center_lng": "21.012200",
            },
        )

        station, _ = PollingStation.objects.update_or_create(
            code="KTW-001",
            defaults={
                "name": "Obwodowa Komisja Wyborcza nr 1",
                "territorial_unit": okreg_miejski,
                "address": "ul. Młyńska 4, 40-098 Katowice",
                "latitude": "50.259100",
                "longitude": "19.021600",
            },
        )
        station_waw, _ = PollingStation.objects.update_or_create(
            code="WAW-001",
            defaults={
                "name": "Obwodowa Komisja Wyborcza nr 1 — Warszawa",
                "territorial_unit": gmina_waw,
                "address": "ul. Senatorska 2, 00-075 Warszawa",
                "latitude": "52.244500",
                "longitude": "21.013000",
            },
        )

        # Urzędy (bez terytorium / seats)
        offices_data = [
            ("prezydent-rp", "Prezydent RP", "Wybory ogólnokrajowe.", 1),
            ("eurodeputowany", "Poseł do Europarlamentu", "Mandaty europejskie.", 2),
            ("posel-sejm", "Poseł na Sejm RP", "Wybory do Sejmu.", 3),
            ("senator", "Senator RP", "Wybory do Senatu.", 4),
            ("prezydent-miasta", "Prezydent Miasta", "Wybory samorządowe — prezydent.", 5),
            ("radny", "Radny Rady Miasta", "Wybory samorządowe — rada.", 6),
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

        # Okręgi: (district_slug, office_slug, name, unit, seats, candidates, order)
        districts_spec = [
            (
                "prezydent-rp-kraj",
                "prezydent-rp",
                "Okręg ogólnopolski",
                poland,
                1,
                ["Anna Kowalska", "Jan Nowak", "Piotr Wiśniewski", "Maria Zielińska"],
                1,
            ),
            (
                "euro-slask",
                "eurodeputowany",
                "Okręg — Województwo Śląskie",
                slask,
                2,
                ["Ewa Maj", "Tomasz Król", "Barbara Lewandowska", "Igor Nowicki"],
                1,
            ),
            (
                "sejm-31-katowice",
                "posel-sejm",
                "Okręg nr 31 — Katowice",
                okreg,
                12,
                [
                    "Krzysztof Wójcik",
                    "Agnieszka Kamińska",
                    "Michał Szymański",
                    "Joanna Dąbrowska",
                    "Paweł Lis",
                    "Ewelina Bąk",
                ],
                1,
            ),
            (
                "senat-katowice",
                "senator",
                "Okręg senacki Katowice",
                okreg,
                1,
                ["Paweł Jankowski", "Natalia Woźniak", "Adam Kaczmarek"],
                1,
            ),
            (
                "prezydent-katowice",
                "prezydent-miasta",
                "Gmina Katowice",
                gmina,
                1,
                ["Magdalena Pawlak", "Robert Grabowski", "Karolina Michalska"],
                1,
            ),
            (
                "rada-katowice",
                "radny",
                "Okręg miejski Katowice",
                okreg_miejski,
                3,
                [
                    "Łukasz Zając",
                    "Dorota Sikora",
                    "Marcin Walczak",
                    "Aleksandra Górska",
                    "Igor Czarnecki",
                ],
                1,
            ),
            (
                "prezydent-warszawa",
                "prezydent-miasta",
                "Gmina Warszawa",
                gmina_waw,
                1,
                ["Hanna Nowicka", "Stefan Borkowski", "Julia Malinowska"],
                2,
            ),
            (
                "sejm-19-warszawa",
                "posel-sejm",
                "Okręg nr 19 — Warszawa",
                okreg_waw,
                20,
                [
                    "Adam Warszawski",
                    "Beata Stołeczna",
                    "Cezary Mazur",
                    "Danuta Wisła",
                    "Emil Praga",
                ],
                2,
            ),
        ]

        for dslug, oslug, dname, unit, seats, candidates, order in districts_spec:
            district, _ = ElectoralDistrict.objects.update_or_create(
                slug=dslug,
                defaults={
                    "office": offices[oslug],
                    "name": dname,
                    "territorial_unit": unit,
                    "seats_count": seats,
                    "display_order": order,
                },
            )
            for idx, cname in enumerate(candidates):
                Candidate.objects.update_or_create(
                    district=district,
                    name=cname,
                    defaults={"is_active": True, "display_order": idx, "bio": ""},
                )

        User = get_user_model()
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

        VoterProfile.objects.update_or_create(
            user=user,
            defaults={"polling_station": station},
        )

        self.stdout.write(self.style.SUCCESS("Seed demo OK."))
        self.stdout.write("  Login: demo / demo1234")
        self.stdout.write(f"  Komisja: {station}")
        self.stdout.write(f"  Alternatywna komisja: {station_waw}")
