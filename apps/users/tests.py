from django.contrib.auth import get_user_model
from django.test import TestCase

from elections.models import Ballot, ElectoralDistrict, Office, VoterProfile
from elections.services import get_eligible_districts
from elections.services.eligibility import user_may_run_in_district
from elections.services.results import compute_district_schulze
from geo.models import PollingStation, TerritorialLevel, TerritorialUnit
from users.services.station_change import change_user_polling_station

User = get_user_model()


def _level(slug: str) -> TerritorialLevel:
    return TerritorialLevel.objects.get(slug=slug)


def _make_hierarchy(prefix: str):
    """Tworzy kraj → woj → gmina → obwód i zwraca słownik."""
    country = TerritorialUnit.objects.create(
        name="Polska", slug=f"{prefix}-polska", kind=TerritorialUnit.Kind.COUNTRY
    )
    woj = TerritorialUnit.objects.create(
        name="Śląskie", slug=f"{prefix}-slask", kind=TerritorialUnit.Kind.VOIVODESHIP, parent=country
    )
    gmina = TerritorialUnit.objects.create(
        name="Katowice", slug=f"{prefix}-ktw", kind=TerritorialUnit.Kind.MUNICIPALITY, parent=woj
    )
    precinct = TerritorialUnit.objects.create(
        name="Obwód 1", slug=f"{prefix}-obwod1", kind=TerritorialUnit.Kind.PRECINCT, parent=gmina
    )
    return {"country": country, "woj": woj, "gmina": gmina, "precinct": precinct}


def _make_station(code: str, precinct: TerritorialUnit) -> PollingStation:
    return PollingStation.objects.create(
        code=code,
        name=f"Komisja {code}",
        precinct=precinct,
        address=f"ul. Testowa 1 ({code})",
    )


def _make_user(label: str, station: PollingStation, birth_year: int = 1985) -> User:
    from datetime import date
    from users.services.accounts import ensure_user

    digit_tail = abs(hash(label)) % 100_000_000
    email = f"{label}.{digit_tail}@selectio.test"
    return ensure_user(
        email=email,
        password="x",
        first_name=label.capitalize()[:30],
        last_name="Testowy",
        birth_date=date(birth_year, 6, 1),
        territorial_unit=station.precinct,
    )

class StationChangeTests(TestCase):
    def setUp(self):
        h1 = _make_hierarchy("sc1")
        country = h1["country"]
        woj2 = TerritorialUnit.objects.create(
            name="Mazowieckie", slug="sc-maz", kind=TerritorialUnit.Kind.VOIVODESHIP, parent=country
        )
        gmina2 = TerritorialUnit.objects.create(
            name="Warszawa", slug="sc-waw-m", kind=TerritorialUnit.Kind.MUNICIPALITY, parent=woj2
        )
        precinct2 = TerritorialUnit.objects.create(
            name="Obwód 1 Waw", slug="sc-waw-obwod", kind=TerritorialUnit.Kind.PRECINCT, parent=gmina2
        )

        self.st1 = _make_station("SC-S1", h1["precinct"])
        self.st2 = _make_station("SC-S2", precinct2)

        office_national = Office.objects.create(name="Prezydent", slug="sc-prez")
        office_local = Office.objects.create(name="Prezydent miasta", slug="sc-prez-m")

        self.d_national = ElectoralDistrict.objects.create(
            office=office_national, name="Kraj", slug="sc-d-prez", seats_count=1
        )
        self.d_national.territorial_units.set([h1["country"]])

        self.d_local = ElectoralDistrict.objects.create(
            office=office_local, name="Katowice", slug="sc-d-ktw", seats_count=1
        )
        self.d_local.territorial_units.set([h1["gmina"]])

        self.user = _make_user("sc_changer", self.st1)

        for district in (self.d_national, self.d_local):
            Ballot.objects.create(user=self.user, district=district, ranked_user_ids=[self.user.pk])

    def test_change_voids_out_of_scope_and_keeps_national(self):
        result = change_user_polling_station(self.user, self.st2)
        self.assertEqual({d.slug for d in result.voided_districts}, {"sc-d-ktw"})
        self.assertEqual(result.active_ballots, 1)
        self.assertEqual(result.voided_ballots, 1)

        national = Ballot.objects.get(user=self.user, district=self.d_national)
        local = Ballot.objects.get(user=self.user, district=self.d_local)
        self.assertFalse(national.is_voided)
        self.assertTrue(local.is_voided)

        eligible = set(get_eligible_districts(self.user).values_list("slug", flat=True))
        self.assertIn("sc-d-prez", eligible)
        self.assertNotIn("sc-d-ktw", eligible)

        schulze = compute_district_schulze(self.d_local)
        self.assertEqual(schulze.ballot_count, 0)

    def test_return_restores_voided_ballots(self):
        change_user_polling_station(self.user, self.st2)
        result = change_user_polling_station(self.user, self.st1)
        self.assertEqual({d.slug for d in result.restored_districts}, {"sc-d-ktw"})
        local = Ballot.objects.get(user=self.user, district=self.d_local)
        self.assertFalse(local.is_voided)
        self.assertEqual(local.void_reason, "")


class EligibilityByHierarchyTests(TestCase):
    """Eligibility zależy od poddrzewa precinct → gmina → kraj."""

    def setUp(self):
        self.country = TerritorialUnit.objects.create(
            name="Polska", slug="eh-pol", kind=TerritorialUnit.Kind.COUNTRY
        )
        woj = TerritorialUnit.objects.create(
            name="Śląskie", slug="eh-slask", kind=TerritorialUnit.Kind.VOIVODESHIP, parent=self.country
        )
        self.gmina = TerritorialUnit.objects.create(
            name="Katowice", slug="eh-ktw", kind=TerritorialUnit.Kind.MUNICIPALITY, parent=woj
        )
        self.precinct = TerritorialUnit.objects.create(
            name="Obwód 1", slug="eh-obw1", kind=TerritorialUnit.Kind.PRECINCT, parent=self.gmina
        )
        woj2 = TerritorialUnit.objects.create(
            name="Mazowieckie", slug="eh-maz", kind=TerritorialUnit.Kind.VOIVODESHIP, parent=self.country
        )
        gmina2 = TerritorialUnit.objects.create(
            name="Warszawa", slug="eh-waw", kind=TerritorialUnit.Kind.MUNICIPALITY, parent=woj2
        )
        precinct2 = TerritorialUnit.objects.create(
            name="Obwód 1 Waw", slug="eh-obw2", kind=TerritorialUnit.Kind.PRECINCT, parent=gmina2
        )

        self.station_ktw = _make_station("EH-KTW", self.precinct)
        self.station_waw = _make_station("EH-WAW", precinct2)

        office = Office.objects.create(
            name="Rada gminy",
            slug="eh-rada",
            candidacy_level=_level("municipality"),
        )
        office_nat = Office.objects.create(
            name="Prezydent",
            slug="eh-prez",
            candidacy_level=_level("country"),
        )

        self.district_local = ElectoralDistrict.objects.create(
            office=office, name="Rada gminy Katowice", slug="eh-d-rada", seats_count=3
        )
        self.district_local.territorial_units.set([self.gmina])

        self.district_nat = ElectoralDistrict.objects.create(
            office=office_nat, name="Kraj", slug="eh-d-prez", seats_count=1
        )
        self.district_nat.territorial_units.set([self.country])

    def test_ktw_user_eligible_for_local_and_national(self):
        user = _make_user("eh_ktw", self.station_ktw)
        eligible = set(get_eligible_districts(user).values_list("slug", flat=True))
        self.assertIn("eh-d-rada", eligible)
        self.assertIn("eh-d-prez", eligible)

    def test_waw_user_not_eligible_for_ktw_local(self):
        user = _make_user("eh_waw", self.station_waw)
        eligible = set(get_eligible_districts(user).values_list("slug", flat=True))
        self.assertNotIn("eh-d-rada", eligible)
        self.assertIn("eh-d-prez", eligible)

    def test_no_station_cannot_vote(self):
        from users.services.accounts import ensure_user

        user = ensure_user(
            email="bez.obwodu@selectio.test",
            password="x",
            first_name="Bez",
            last_name="Obwodu",
        )
        eligible = get_eligible_districts(user)
        self.assertFalse(eligible.exists())

    def test_candidacy_country_allows_other_municipality(self):
        """Poziom kraj → kandydat spoza gminy okręgu może startować."""
        user = _make_user("eh_cand_waw", self.station_waw)
        precinct = user.voter_profile.territorial_unit
        self.assertTrue(user_may_run_in_district(precinct, self.district_nat))

    def test_candidacy_municipality_blocks_other_city(self):
        user = _make_user("eh_cand_block", self.station_waw)
        precinct = user.voter_profile.territorial_unit
        self.assertFalse(user_may_run_in_district(precinct, self.district_local))
