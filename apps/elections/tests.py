"""Testy silnika Schulzego i cache wyników per okręg."""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from elections.models import (
    Ballot,
    Candidate,
    ElectionResultCache,
    ElectoralDistrict,
    Office,
)
from elections.services.results import get_cached_result, invalidate_district_results
from elections.services.schulze import compute_schulze, schulze_ranking, strongest_paths
from geo.models import TerritorialUnit


class SchulzeEngineTests(SimpleTestCase):
    def test_wikipedia_matrix_winner_e(self):
        ids = [1, 2, 3, 4, 5]
        wiki_d = {
            1: {1: 0, 2: 20, 3: 26, 4: 30, 5: 22},
            2: {1: 25, 2: 0, 3: 16, 4: 33, 5: 18},
            3: {1: 19, 2: 29, 3: 0, 4: 17, 5: 24},
            4: {1: 15, 2: 12, 3: 28, 4: 0, 5: 21},
            5: {1: 23, 2: 27, 3: 21, 4: 24, 5: 0},
        }
        p = strongest_paths(ids, wiki_d)
        first = {c: 0 for c in ids}
        ranking, winners, elected = schulze_ranking(ids, p, first, seats_count=1)
        self.assertEqual(elected, [5])
        self.assertEqual([r.candidate_id for r in ranking], [5, 1, 3, 2, 4])
        self.assertTrue(ranking[0].is_elected)
        self.assertFalse(ranking[1].is_elected)

    def test_multi_seat_elects_top_n(self):
        rankings = [[1, 2, 3, 4]] * 5 + [[2, 1, 3, 4]] * 2
        result = compute_schulze([1, 2, 3, 4], rankings, seats_count=2)
        self.assertEqual(len(result.elected), 2)
        self.assertTrue(all(r.is_elected for r in result.ranking if r.candidate_id in result.elected))
        self.assertEqual(result.seats_count, 2)

    def test_condorcet_winner_from_ballots(self):
        rankings = [[1, 2, 3]] * 3 + [[1, 3, 2]] * 2 + [[2, 1, 3]] * 1
        result = compute_schulze([1, 2, 3], rankings, seats_count=1)
        self.assertEqual(result.elected, [1])
        self.assertEqual(result.ballot_count, 6)

    def test_complete_tie(self):
        rankings = [[1, 2], [2, 1]]
        result = compute_schulze([1, 2], rankings, seats_count=1)
        self.assertEqual(len(result.elected), 1)
        # Remis na progu przy 1 mandacie i równych ścieżkach
        self.assertTrue(any(r.is_tied_at_threshold for r in result.ranking))

    def test_partial_ranking_beats_unranked(self):
        # Tylko kandydat 1 uporządkowany → bije 2 i 3; 2 vs 3 remis w tym głosie.
        from elections.services.schulze import build_pairwise_matrix

        d, first, n = build_pairwise_matrix([1, 2, 3], [[1]])
        self.assertEqual(n, 1)
        self.assertEqual(d[1][2], 1)
        self.assertEqual(d[1][3], 1)
        self.assertEqual(d[2][3], 0)
        self.assertEqual(d[3][2], 0)
        self.assertEqual(first[1], 1)

        result = compute_schulze([1, 2, 3], [[1], [1, 2]], seats_count=1)
        self.assertEqual(result.elected, [1])
        self.assertEqual(result.ballot_count, 2)


class ResultsCacheTests(TestCase):
    def setUp(self):
        self.unit = TerritorialUnit.objects.create(
            name="Polska",
            slug="test-polska",
            kind=TerritorialUnit.Kind.COUNTRY,
        )
        self.office = Office.objects.create(name="Test Office", slug="test-office")
        self.district = ElectoralDistrict.objects.create(
            office=self.office,
            name="Okręg testowy",
            slug="test-district",
            territorial_unit=self.unit,
            seats_count=1,
        )
        self.c1 = Candidate.objects.create(
            district=self.district, name="Alpha", display_order=0
        )
        self.c2 = Candidate.objects.create(
            district=self.district, name="Beta", display_order=1
        )
        User = get_user_model()
        self.user = User.objects.create_user("voter1", password="x")

    def test_cache_reused_until_vote(self):
        payload1 = get_cached_result(self.district)
        cache = ElectionResultCache.objects.get(district=self.district)
        self.assertFalse(cache.is_stale)
        fp = cache.fingerprint

        payload2 = get_cached_result(self.district)
        cache.refresh_from_db()
        self.assertEqual(cache.fingerprint, fp)
        self.assertEqual(payload1["schulze"]["ballot_count"], payload2["schulze"]["ballot_count"])

        Ballot.objects.create(
            user=self.user,
            district=self.district,
            ranked_candidate_ids=[self.c1.pk, self.c2.pk],
        )
        invalidate_district_results(self.district)
        cache.refresh_from_db()
        self.assertTrue(cache.is_stale)

        payload3 = get_cached_result(self.district)
        self.assertEqual(payload3["schulze"]["ballot_count"], 1)
        self.assertEqual(payload3["elected"][0]["candidate_id"], self.c1.pk)
        self.assertEqual(payload3["district"]["seats_count"], 1)
