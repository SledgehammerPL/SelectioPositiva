"""
Silnik metody Schulzego (beatpath) z obsługą wielu mandatów.

Algorytm:
1. Macierz pairwise d[a][b].
2. Siła ścieżek p[a][b] (Floyd–Warshall).
3. Ranking wg liczby zwycięstw Schulzego.
4. Pierwszych `seats_count` kandydatów = wybrani; remis na progu mandatowym,
   gdy p[A,B] == p[B,A] między miejscem seats_count a seats_count+1.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class CandidateStanding:
    candidate_id: int
    place: int
    schulze_wins: int
    first_preferences: int
    is_winner: bool
    is_tied_winner: bool
    is_elected: bool = False
    is_tied_at_threshold: bool = False


@dataclass
class SchulzeResult:
    candidate_ids: list[int]
    pairwise: dict[str, dict[str, int]]
    path_strength: dict[str, dict[str, int]]
    ranking: list[CandidateStanding]
    winners: list[int]
    elected: list[int]
    seats_count: int
    ballot_count: int
    first_preferences: dict[str, int]

    def to_payload(self) -> dict:
        return {
            "candidate_ids": self.candidate_ids,
            "pairwise": self.pairwise,
            "path_strength": self.path_strength,
            "ranking": [asdict(r) for r in self.ranking],
            "winners": self.winners,
            "elected": self.elected,
            "seats_count": self.seats_count,
            "ballot_count": self.ballot_count,
            "first_preferences": self.first_preferences,
        }

    @classmethod
    def from_payload(cls, data: dict) -> "SchulzeResult":
        ranking = [CandidateStanding(**row) for row in data["ranking"]]
        return cls(
            candidate_ids=list(data["candidate_ids"]),
            pairwise=data["pairwise"],
            path_strength=data["path_strength"],
            ranking=ranking,
            winners=list(data.get("winners") or data.get("elected") or []),
            elected=list(data.get("elected") or data.get("winners") or []),
            seats_count=int(data.get("seats_count", 1)),
            ballot_count=int(data["ballot_count"]),
            first_preferences=data["first_preferences"],
        )


def _sid(x: int) -> str:
    return str(x)


def build_pairwise_matrix(
    candidate_ids: Sequence[int],
    rankings: Iterable[Sequence[int]],
) -> tuple[dict[int, dict[int, int]], dict[int, int], int]:
    """
    Buduje d[A,B] z obsługą niepełnych rankingów.

    R = uporządkowani (kolejność 1..k), U = nieuporządkowani (C \\ R).
    - X,Y ∈ R: wyższa pozycja na liście wygrywa
    - X ∈ R, Y ∈ U: X bije Y
    - X,Y ∈ U: remis (brak aktualizacji macierzy)
    """
    ids = list(candidate_ids)
    id_set = set(ids)
    d: dict[int, dict[int, int]] = {a: {b: 0 for b in ids} for a in ids}
    first_prefs: dict[int, int] = {c: 0 for c in ids}
    count = 0

    for ranking in rankings:
        count += 1
        # Zachowaj kolejność, usuń duplikaty / obce ID.
        seen: set[int] = set()
        ranked: list[int] = []
        for cid in ranking:
            if cid in id_set and cid not in seen:
                ranked.append(cid)
                seen.add(cid)
        unranked = [cid for cid in ids if cid not in seen]

        if ranked and ranked[0] in first_prefs:
            first_prefs[ranked[0]] += 1

        # Preferencje wewnątrz R
        for i, a in enumerate(ranked):
            for b in ranked[i + 1 :]:
                d[a][b] += 1

        # Każdy z R bije każdego z U
        for a in ranked:
            for b in unranked:
                d[a][b] += 1

    return d, first_prefs, count


def strongest_paths(
    candidate_ids: Sequence[int],
    d: dict[int, dict[int, int]],
) -> dict[int, dict[int, int]]:
    ids = list(candidate_ids)
    p: dict[int, dict[int, int]] = {a: {b: 0 for b in ids} for a in ids}

    for a in ids:
        for b in ids:
            if a == b:
                continue
            if d[a][b] > d[b][a]:
                p[a][b] = d[a][b]
            else:
                p[a][b] = 0

    for k in ids:
        for i in ids:
            if i == k:
                continue
            for j in ids:
                if j == i or j == k:
                    continue
                via = min(p[i][k], p[k][j])
                if via > p[i][j]:
                    p[i][j] = via

    return p


def schulze_ranking(
    candidate_ids: Sequence[int],
    p: dict[int, dict[int, int]],
    first_prefs: dict[int, int],
    *,
    seats_count: int = 1,
) -> tuple[list[CandidateStanding], list[int], list[int]]:
    """
    Ranking + obsada mandatów.

    Remis na progu: gdy kandydat na pozycji seats_count i seats_count+1
    mają p[A,B] == p[B,A] (brak rozstrzygnięcia ścieżką).
    """
    ids = list(candidate_ids)
    wins = {a: 0 for a in ids}
    for a in ids:
        for b in ids:
            if a == b:
                continue
            if p[a][b] > p[b][a]:
                wins[a] += 1

    by_wins: dict[int, list[int]] = defaultdict(list)
    for cid in ids:
        by_wins[wins[cid]].append(cid)

    ordered_groups = sorted(by_wins.keys(), reverse=True)
    ordered: list[tuple[int, int, int]] = []  # (cid, wins, place)
    place = 1
    for win_count in ordered_groups:
        group = sorted(
            by_wins[win_count],
            key=lambda cid: (-first_prefs.get(cid, 0), cid),
        )
        for cid in group:
            ordered.append((cid, win_count, place))
        place += len(group)

    seats = max(1, int(seats_count))
    n = len(ordered)

    tied_threshold_ids: set[int] = set()
    if 0 < seats < n:
        a_id, _, _ = ordered[seats - 1]
        b_id, _, _ = ordered[seats]
        if p[a_id][b_id] == p[b_id][a_id]:
            # Cała grupa dzieląca miejsce progu.
            threshold_place = ordered[seats - 1][2]
            for cid, _, pl in ordered:
                if pl == threshold_place:
                    tied_threshold_ids.add(cid)
            # Dołącz też następną grupę, jeśli ta sama siła ścieżki względem progu.
            next_place = ordered[seats][2]
            for cid, _, pl in ordered:
                if pl == next_place:
                    tied_threshold_ids.add(cid)

    elected_ids: list[int] = []
    standing: list[CandidateStanding] = []
    for idx, (cid, win_count, pl) in enumerate(ordered):
        is_elected = idx < seats
        if is_elected:
            elected_ids.append(cid)
        is_tied_thr = cid in tied_threshold_ids
        # is_winner / is_tied_winner zachowane dla kompatybilności (top group).
        is_top = pl == 1
        tied_top = is_top and sum(1 for _, _, xpl in ordered if xpl == 1) > 1
        standing.append(
            CandidateStanding(
                candidate_id=cid,
                place=pl,
                schulze_wins=win_count,
                first_preferences=first_prefs.get(cid, 0),
                is_winner=is_elected,
                is_tied_winner=is_tied_thr and is_elected,
                is_elected=is_elected,
                is_tied_at_threshold=is_tied_thr,
            )
        )

    return standing, elected_ids, elected_ids


def compute_schulze(
    candidate_ids: Sequence[int],
    rankings: Sequence[Sequence[int]],
    *,
    seats_count: int = 1,
) -> SchulzeResult:
    ids = list(candidate_ids)
    if not ids:
        return SchulzeResult(
            candidate_ids=[],
            pairwise={},
            path_strength={},
            ranking=[],
            winners=[],
            elected=[],
            seats_count=seats_count,
            ballot_count=0,
            first_preferences={},
        )

    d, first_prefs, ballot_count = build_pairwise_matrix(ids, rankings)
    p = strongest_paths(ids, d)
    ranking, winners, elected = schulze_ranking(
        ids, p, first_prefs, seats_count=seats_count
    )

    return SchulzeResult(
        candidate_ids=ids,
        pairwise={_sid(a): {_sid(b): d[a][b] for b in ids} for a in ids},
        path_strength={_sid(a): {_sid(b): p[a][b] for b in ids} for a in ids},
        ranking=ranking,
        winners=winners,
        elected=elected,
        seats_count=max(1, int(seats_count)),
        ballot_count=ballot_count,
        first_preferences={_sid(c): first_prefs[c] for c in ids},
    )
