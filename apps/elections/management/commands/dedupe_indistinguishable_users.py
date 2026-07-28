"""
Usuwa zdublowane konta nierozróżnialnych osób
(to samo imię/2. imię/nazwisko; jednostka ta sama lub w hierarchii;
data ur. zgodna — brak daty + znana data = ta sama osoba).

Zostawia użytkownika o najniższym id; usuwa pozostałych.
Przemapowuje Ballot.ranked_user_ids.

Użycie:
  python manage.py dedupe_indistinguishable_users
  python manage.py dedupe_indistinguishable_users --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from elections.services.identity import (
    dedupe_indistinguishable_users,
    find_duplicate_groups,
)


class Command(BaseCommand):
    help = (
        "Deduplikacja nierozróżnialnych użytkowników "
        "(imię + 2. imię + nazwisko + spokrewniona jednostka + data ur.)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Naprawdę usuń duplikaty (bez flagi = tylko podgląd)",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=15,
            help="Ile przykładów grup pokazać (domyślnie 15)",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        show = options["show"]

        groups = find_duplicate_groups()
        extra = sum(len(users) - 1 for _, users in groups)
        self.stdout.write(f"Grup zdublowanych: {len(groups)}")
        self.stdout.write(f"Kont do usunięcia (wyższe id): {extra}")

        for key, users in groups[:show]:
            first, second, last = key
            name = " ".join(p for p in (first, second, last) if p)
            births = sorted(
                {
                    str(u.voter_profile.birth_date)
                    for u in users
                    if getattr(u, "voter_profile", None)
                }
            )
            units = sorted(
                {
                    u.voter_profile.territorial_unit_id
                    for u in users
                    if getattr(u, "voter_profile", None)
                    and u.voter_profile.territorial_unit_id
                }
            )
            ids = ", ".join(f"{u.pk}:{u.email}" for u in users)
            self.stdout.write(
                f"  keep={users[0].pk} | {name} | units={units} | "
                f"ur={births} | {ids}"
            )
        if len(groups) > show:
            self.stdout.write(f"  … i {len(groups) - show} kolejnych grup")

        if not apply:
            self.stdout.write(
                self.style.WARNING("Podgląd — uruchom z --apply, aby usunąć.")
            )
            return

        stats = dedupe_indistinguishable_users(apply=True)
        self.stdout.write(
            self.style.SUCCESS(
                f"Usunięto użytkowników: {stats['deleted']}, "
                f"przemapowano kart: {stats['ballots_remapped']}."
            )
        )
