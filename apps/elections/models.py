from django.conf import settings
from django.db import models

from geo.models import TerritorialUnit


class VoterProfile(models.Model):
    """
    Profil wyborcy.

    Każdy użytkownik ma dokładnie jeden profil.
    `territorial_unit` to węzeł hierarchii (kraj, gmina, obwód…).
    Aby głosować, użytkownik musi mieć powiązaną `polling_station`
    (komisja wyborczą → obwód → …).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="voter_profile",
        verbose_name="użytkownik",
    )
    territorial_unit = models.ForeignKey(
        "geo.TerritorialUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="residents",
        verbose_name="jednostka terytorialna",
        help_text=(
            "Węzeł hierarchii, z którym powiązany jest wyborca. "
            "Minimum: kraj. Jeśli ustawiona komisja, obwód komisji "
            "jest używany do wyznaczenia uprawnień."
        ),
    )
    polling_station = models.ForeignKey(
        "geo.PollingStation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voters",
        verbose_name="komisja wyborcza",
        help_text="Wymagana do głosowania. Komisja musi należeć do obwodu będącego potomkiem territorial_unit.",
    )
    birth_date = models.DateField(
        "data urodzenia",
        null=True,
        blank=True,
        help_text="Wymagana do weryfikacji limitu wieku w okręgu wyborczym.",
    )

    class Meta:
        verbose_name = "profil wyborcy"
        verbose_name_plural = "profile wyborców"

    def __str__(self) -> str:
        if self.polling_station_id:
            return f"{self.user} @ {self.polling_station}"
        return f"{self.user} ({self.territorial_unit})"

    def can_vote(self) -> bool:
        """Użytkownik może głosować tylko jeśli ma przypisaną komisję."""
        return self.polling_station_id is not None

    def effective_unit(self) -> "TerritorialUnit":
        """Węzeł używany do wyznaczania uprawnień — obwód komisji lub territorial_unit."""
        if self.polling_station_id and self.polling_station.precinct_id:
            return self.polling_station.precinct
        return self.territorial_unit


class Party(models.Model):
    """Partia polityczna / ugrupowanie."""

    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    abbreviation = models.CharField("skrót", max_length=32, blank=True)
    is_active = models.BooleanField("aktywna", default=True)
    display_order = models.PositiveIntegerField("kolejność", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "partia"
        verbose_name_plural = "partie"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        if self.abbreviation:
            return f"{self.name} ({self.abbreviation})"
        return self.name


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
    Okręg wyborczy.

    `territorial_units` (M2M) — węzły hierarchii należące do okręgu.
    Wyborca jest uprawniony do głosowania, gdy jego obwód (lub przodek)
    leży wśród tych węzłów.

    Przykłady:
    - Prezydent RP → [kraj Polska]
    - Sejm okręg 31 → [powiat katowicki, powiat bielski, …]
    - Rada gminy okręg 3 → [obwód 3 w gminie Katowice]

    `min_age` — minimalne wymagane lat do głosowania i do kandydowania.
    """

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name="districts",
        verbose_name="urząd",
    )
    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    territorial_units = models.ManyToManyField(
        "geo.TerritorialUnit",
        related_name="electoral_districts",
        verbose_name="jednostki terytorialne",
        blank=True,
        help_text=(
            "Węzły hierarchii należące do tego okręgu. "
            "Wyborca jest uprawniony, gdy jego obwód leży w poddrzewie "
            "któregoś z tych węzłów."
        ),
    )
    seats_count = models.PositiveIntegerField(
        "liczba mandatów",
        default=1,
        help_text="Ile mandatów obsadzanych jest w tym okręgu (metoda Schulzego).",
    )
    min_age = models.PositiveSmallIntegerField(
        "minimalny wiek",
        default=18,
        help_text="Minimalny wiek (w latach) wymagany do głosowania i kandydowania w tym okręgu.",
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


def _ancestor_of_kind(
    unit: TerritorialUnit | None, kind: str
) -> TerritorialUnit | None:
    current = unit
    seen: set[int] = set()
    while current is not None and current.pk not in seen:
        if current.kind == kind:
            return current
        seen.add(current.pk)
        current = current.parent
    return None


def unit_is_descendant_of_any(unit: TerritorialUnit, ancestor_ids: set[int]) -> bool:
    """
    Zwraca True, gdy `unit` lub któryś z jego przodków należy do `ancestor_ids`.
    Używane do sprawdzania, czy obwód wyborcy należy do okręgu.
    """
    current: TerritorialUnit | None = unit
    seen: set[int] = set()
    while current is not None and current.pk not in seen:
        if current.pk in ancestor_ids:
            return True
        seen.add(current.pk)
        current = current.parent
    return False


class Ballot(models.Model):
    """
    Głos użytkownika (ranking Schulzego) w danym okręgu.

    `ranked_user_ids` — lista ID użytkowników od najwyżej preferowanego.
    Pozostali uprawnieni użytkownicy okręgu są traktowani jako unranked.
    Przy zmianie komisji głos poza zasięgiem jest zamrażany (is_voided).
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
    ranked_user_ids = models.JSONField(
        "ranking użytkowników",
        default=list,
        help_text=(
            "Lista ID użytkowników od najwyżej preferowanego. "
            "Pozostali uprawnieni użytkownicy okręgu = nieuporządkowani (unranked)."
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
