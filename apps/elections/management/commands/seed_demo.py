"""
Seed kont demo / urzędów demo.

Gdy w bazie są już dane PKW (komisje z TERYT), NIE tworzy jednostek
geograficznych ani obwodów demonstracyjnych — używa prawdziwych.

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

# Slugi/kody tworzone kiedyś przez seed — do usunięcia przy obecności PKW.
DEMO_UNIT_SLUGS = (
    "gmina-katowice",
    "gmina-warszawa",
    "obwod-katowice-1",
    "obwod-warszawa-1",
    "slaskie",  # tylko jeśli bez TERYT — PKW używa woj-XX
    "mazowieckie",
)
DEMO_STATION_CODES = ("KTW-001", "WAW-001")


class Command(BaseCommand):
    help = (
        "Tworzy użytkowników/partie/urzędy demo. "
        "Nie dokłada fałszywych obwodów, gdy baza ma dane PKW."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        has_pkw = PollingStation.objects.filter(
            code__regex=r"^[0-9]{6}-[0-9]+$",
            precinct__isnull=False,
        ).exists()

        if has_pkw:
            removed = self._purge_demo_geo()
            if removed:
                self.stdout.write(
                    self.style.WARNING(
                        f"Usunięto {removed} demonstracyjnych jednostek/komisji "
                        "(baza ma dane PKW)."
                    )
                )
            poland = TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.COUNTRY
            ).first() or TerritorialUnit.objects.filter(slug="polska").first()
            station = (
                PollingStation.objects.filter(
                    code="246901-1", precinct__isnull=False
                ).first()
                or PollingStation.objects.filter(
                    code__startswith="246901-", precinct__isnull=False
                )
                .order_by("number")
                .first()
            )
            station_waw = (
                PollingStation.objects.filter(
                    code__startswith="146501-", precinct__isnull=False
                )
                .order_by("number")
                .first()
                or station
            )
            if station is None:
                self.stdout.write(
                    self.style.ERROR(
                        "Brak komisji PKW z obwodem — uruchom import_pkw_poland "
                        "/ backfill_precincts."
                    )
                )
                return
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Brak danych PKW — seed nie tworzy już geografii demo. "
                    "Najpierw: python manage.py import_pkw_poland && "
                    "python manage.py backfill_precincts && "
                    "python manage.py backfill_district_units"
                )
            )
            return

        # ── Urzędy (tylko brakujące / aktualizacja metadanych) ───────────────
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

        for slug, pname, abbr, order in [
            ("partia-a", "Partia Demo A", "PDA", 1),
            ("partia-b", "Partia Demo B", "PDB", 2),
        ]:
            Party.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": pname,
                    "abbreviation": abbr,
                    "is_active": True,
                    "display_order": order,
                },
            )

        # Demo-okręg prezydencki — tylko jeśli brak; nie nadpisuj M2M PKW.
        if poland and not ElectoralDistrict.objects.filter(slug="prezydent-rp-kraj").exists():
            d = ElectoralDistrict.objects.create(
                slug="prezydent-rp-kraj",
                office=offices["prezydent-rp"],
                name="Okręg ogólnopolski",
                seats_count=1,
                min_age=35,
                display_order=1,
            )
            d.territorial_units.set([poland])

        # ── Użytkownicy demo na prawdziwych obwodach ─────────────────────────
        candidates_data = [
            ("anna", "Kowalska", date(1975, 3, 15), station),
            ("jan", "Nowak", date(1968, 7, 22), station),
            ("piotr", "Wisniewski", date(1982, 1, 5), station),
            ("maria", "Zielinska", date(1990, 11, 30), station),
            ("ewa", "Maj", date(1978, 6, 10), station),
            ("tomasz", "Krol", date(1985, 9, 18), station),
            ("barbara", "Lewandowska", date(1972, 4, 25), station),
            ("hanna", "Nowicka", date(1980, 2, 14), station_waw),
            ("stefan", "Borkowski", date(1965, 12, 3), station_waw),
            ("julia", "Malinowska", date(1993, 8, 27), station_waw),
            ("adam", "Warszawski", date(1977, 5, 9), station_waw),
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
                    "territorial_unit": st.precinct,
                    "birth_date": birth_date,
                },
            )

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
            defaults={
                "territorial_unit": station.precinct,
                "birth_date": date(1990, 5, 12),
            },
        )

        self.stdout.write(self.style.SUCCESS("Seed demo OK (bez geografii demo)."))
        self.stdout.write("  Login: demo / demo1234")
        self.stdout.write(f"  Obwód demo: {station.precinct}")
        self.stdout.write(f"  Komisja (lokalizacja): {station}")

    def _purge_demo_geo(self) -> int:
        """Usuwa stare komisje/obwody/gminy demo, które kolidują z PKW."""
        removed = 0

        # Najpierw odłącz profile od demo-obwodów
        demo_precincts = TerritorialUnit.objects.filter(
            slug__in=("obwod-katowice-1", "obwod-warszawa-1")
        )
        VoterProfile.objects.filter(territorial_unit__in=demo_precincts).update(
            territorial_unit=None
        )

        deleted_st, _ = PollingStation.objects.filter(
            code__in=DEMO_STATION_CODES
        ).delete()
        removed += deleted_st

        # Usuń demo-obwody i demo-gminy bez TERYT (nie ruszaj woj-* / gmina-XXXXXX z PKW)
        for slug in (
            "obwod-katowice-1",
            "obwod-warszawa-1",
            "gmina-katowice",
            "gmina-warszawa",
        ):
            qs = TerritorialUnit.objects.filter(slug=slug)
            # Nie kasuj jeśli to jednostka PKW z TERYT (nie powinno się zdarzyć)
            for u in qs:
                if u.teryt:
                    continue
                # Odłącz okręgi demo od tej jednostki
                for d in ElectoralDistrict.objects.filter(territorial_units=u):
                    d.territorial_units.remove(u)
                u.delete()
                removed += 1

        # Stare slugi województw bez TERYT (PKW ma woj-24 itd.)
        for slug in ("slaskie", "mazowieckie"):
            u = TerritorialUnit.objects.filter(slug=slug, teryt="").first()
            if u is None:
                continue
            # Tylko jeśli nie ma dzieci PKW pod spodem
            if u.children.exists():
                continue
            for d in ElectoralDistrict.objects.filter(territorial_units=u):
                d.territorial_units.remove(u)
            u.delete()
            removed += 1

        return removed
