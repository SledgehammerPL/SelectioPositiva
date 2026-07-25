from django.conf import settings
from django.db import models


class VoterProfile(models.Model):
    """Profil wyborcy — przypisanie użytkownika do komisji wyborczej."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="voter_profile",
        verbose_name="użytkownik",
    )
    polling_station = models.ForeignKey(
        "geo.PollingStation",
        on_delete=models.PROTECT,
        related_name="voters",
        verbose_name="komisja wyborcza",
    )

    class Meta:
        verbose_name = "profil wyborcy"
        verbose_name_plural = "profile wyborców"

    def __str__(self) -> str:
        return f"{self.user} @ {self.polling_station}"


class Office(models.Model):
    """Urząd / rodzaj mandatu (np. Poseł na Sejm RP, Prezydent Miasta)."""

    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    description = models.TextField("opis", blank=True)
    is_open = models.BooleanField(
        "głosowanie otwarte",
        default=True,
        help_text="Czy użytkownicy mogą oddawać i zmieniać głosy na okręgi tego urzędu.",
    )
    display_order = models.PositiveIntegerField("kolejność", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "urząd"
        verbose_name_plural = "urzędy"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name


class ElectoralDistrict(models.Model):
    """
    Okręg wyborczy powiązany z urzędem i jednostką terytorialną.

    Liczba mandatów (seats_count) jest atrybutem okręgu, nie urzędu.
    """

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name="districts",
        verbose_name="urząd",
    )
    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    territorial_unit = models.ForeignKey(
        "geo.TerritorialUnit",
        on_delete=models.PROTECT,
        related_name="electoral_districts",
        verbose_name="jednostka terytorialna",
    )
    seats_count = models.PositiveIntegerField(
        "liczba mandatów",
        default=1,
        help_text="Ile mandatów obsadzanych jest w tym okręgu (metoda Schulzego).",
    )
    display_order = models.PositiveIntegerField("kolejność", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "okręg wyborczy"
        verbose_name_plural = "okręgi wyborcze"
        ordering = ["office__display_order", "display_order", "name"]

    def __str__(self) -> str:
        return f"{self.office.name} — {self.name}"

    @property
    def is_open(self) -> bool:
        return self.office.is_open


class Candidate(models.Model):
    """Kandydat w konkretnym okręgu wyborczym."""

    district = models.ForeignKey(
        ElectoralDistrict,
        on_delete=models.CASCADE,
        related_name="candidates",
        verbose_name="okręg",
    )
    name = models.CharField("imię i nazwisko", max_length=200)
    committee = models.CharField(
        "komitet",
        max_length=200,
        blank=True,
        help_text="Nazwa komitetu wyborczego (opcjonalnie).",
    )
    bio = models.TextField("biogram", blank=True)
    is_active = models.BooleanField(
        "aktywny",
        default=True,
        help_text="Nieaktywni kandydaci nie biorą udziału w nowych głosowaniach.",
    )
    display_order = models.PositiveIntegerField("kolejność wyświetlania", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "kandydat"
        verbose_name_plural = "kandydaci"
        ordering = ["district", "display_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.district})"


class Ballot(models.Model):
    """
    Głos użytkownika (ranking Schulzego) w danym okręgu.

    Przechowuje tylko jawnie uporządkowanych kandydatów (`ranked_candidate_ids`).
    Pozostali kandydaci okręgu są traktowani jako nieuporządkowani (unranked).
    Przy zmianie komisji głos poza zasięgiem jest zamrażany (is_voided), nie usuwany.
    """

    class VoidReason(models.TextChoices):
        CHANGE_OF_POLLING_STATION = (
            "CHANGE_OF_POLLING_STATION",
            "Zmiana komisji wyborczej",
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ballots",
        verbose_name="użytkownik",
    )
    district = models.ForeignKey(
        ElectoralDistrict,
        on_delete=models.CASCADE,
        related_name="ballots",
        verbose_name="okręg",
    )
    ranked_candidate_ids = models.JSONField(
        "uporządkowani kandydaci",
        default=list,
        help_text=(
            "Lista ID kandydatów od najwyżej preferowanego. "
            "Pozostali kandydaci okręgu = nieuporządkowani (unranked)."
        ),
    )
    is_voided = models.BooleanField(
        "unieważniony / zawieszony",
        default=False,
        db_index=True,
        help_text="Głos zamrożony (np. po zmianie komisji poza zasięgiem okręgu).",
    )
    void_reason = models.CharField(
        "powód unieważnienia",
        max_length=64,
        choices=VoidReason.choices,
        blank=True,
        default="",
    )
    voided_at = models.DateTimeField("unieważniono", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Aktualizowane przy każdej zmianie głosu.",
    )

    class Meta:
        verbose_name = "głos"
        verbose_name_plural = "głosy"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "district"],
                name="unique_ballot_per_user_district",
            ),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        mark = " [zawieszony]" if self.is_voided else ""
        return f"Głos {self.user} → {self.district}{mark}"

    @property
    def ranking(self) -> list:
        """Alias wsteczny."""
        return self.ranked_candidate_ids


class ElectionResultCache(models.Model):
    """Cache wyniku Schulzego dla okręgu wyborczego."""

    district = models.OneToOneField(
        ElectoralDistrict,
        on_delete=models.CASCADE,
        related_name="result_cache",
        verbose_name="okręg",
    )
    payload = models.JSONField("wynik", default=dict)
    ballot_count = models.PositiveIntegerField("liczba głosów", default=0)
    fingerprint = models.CharField("odcisk głosów", max_length=64, blank=True)
    is_stale = models.BooleanField("wymaga przeliczenia", default=True)
    computed_at = models.DateTimeField("wyliczono", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "cache wyniku"
        verbose_name_plural = "cache wyników"

    def __str__(self) -> str:
        state = "stale" if self.is_stale else "fresh"
        return f"Wynik {self.district} ({state})"
