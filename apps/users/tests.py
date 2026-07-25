from django.contrib.auth import get_user_model
from django.test import TestCase

from elections.models import Ballot, Candidate, ElectoralDistrict, Office, VoterProfile
from elections.services import get_eligible_districts
from elections.services.results import compute_district_schulze
from geo.models import PollingStation, TerritorialUnit
from users.services.station_change import change_user_polling_station


class StationChangeTests(TestCase):
    def setUp(self):
        self.country = TerritorialUnit.objects.create(
            name="Polska",
            slug="c-polska",
            kind=TerritorialUnit.Kind.COUNTRY,
        )
        self.v1 = TerritorialUnit.objects.create(
            name="Śląskie",
            slug="c-slask",
            kind=TerritorialUnit.Kind.VOIVODESHIP,
            parent=self.country,
        )
        self.v2 = TerritorialUnit.objects.create(
            name="Mazowieckie",
            slug="c-maz",
            kind=TerritorialUnit.Kind.VOIVODESHIP,
            parent=self.country,
        )
        self.m1 = TerritorialUnit.objects.create(
            name="Katowice",
            slug="c-ktw",
            kind=TerritorialUnit.Kind.MUNICIPALITY,
            parent=self.v1,
        )
        self.m2 = TerritorialUnit.objects.create(
            name="Warszawa",
            slug="c-waw",
            kind=TerritorialUnit.Kind.MUNICIPALITY,
            parent=self.v2,
        )
        self.st1 = PollingStation.objects.create(
            code="S1",
            name="Komisja Katowice",
            territorial_unit=self.m1,
            address="Katowice 1",
        )
        self.st2 = PollingStation.objects.create(
            code="S2",
            name="Komisja Warszawa",
            territorial_unit=self.m2,
            address="Warszawa 1",
        )

        self.office_national = Office.objects.create(name="Prezydent", slug="c-prez")
        self.office_local = Office.objects.create(
            name="Prezydent miasta", slug="c-prez-miasto"
        )
        self.d_national = ElectoralDistrict.objects.create(
            office=self.office_national,
            name="Kraj",
            slug="c-d-prez",
            territorial_unit=self.country,
            seats_count=1,
        )
        self.d_local = ElectoralDistrict.objects.create(
            office=self.office_local,
            name="Katowice",
            slug="c-d-ktw",
            territorial_unit=self.m1,
            seats_count=1,
        )
        for district in (self.d_national, self.d_local):
            Candidate.objects.create(district=district, name=f"A-{district.slug}")
            Candidate.objects.create(district=district, name=f"B-{district.slug}")

        User = get_user_model()
        self.user = User.objects.create_user("changer", password="x")
        VoterProfile.objects.create(user=self.user, polling_station=self.st1)

        for district in (self.d_national, self.d_local):
            ids = list(district.candidates.values_list("id", flat=True))
            Ballot.objects.create(
                user=self.user, district=district, ranked_candidate_ids=ids
            )

    def test_change_voids_out_of_scope_and_keeps_national(self):
        result = change_user_polling_station(self.user, self.st2)
        self.assertEqual({d.slug for d in result.voided_districts}, {"c-d-ktw"})
        self.assertEqual(result.active_ballots, 1)
        self.assertEqual(result.voided_ballots, 1)

        national = Ballot.objects.get(user=self.user, district=self.d_national)
        local = Ballot.objects.get(user=self.user, district=self.d_local)
        self.assertFalse(national.is_voided)
        self.assertTrue(local.is_voided)

        eligible = set(get_eligible_districts(self.user).values_list("slug", flat=True))
        self.assertIn("c-d-prez", eligible)
        self.assertNotIn("c-d-ktw", eligible)

        schulze = compute_district_schulze(self.d_local)
        self.assertEqual(schulze.ballot_count, 0)

    def test_return_restores_voided_ballots(self):
        change_user_polling_station(self.user, self.st2)
        result = change_user_polling_station(self.user, self.st1)
        self.assertEqual({d.slug for d in result.restored_districts}, {"c-d-ktw"})
        local = Ballot.objects.get(user=self.user, district=self.d_local)
        self.assertFalse(local.is_voided)
        self.assertEqual(local.void_reason, "")
