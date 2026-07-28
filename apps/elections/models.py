from django.conf import settings
from django.db import models

from geo.models import TerritorialUnit


class VoterProfile(models.Model):
    """
    Profil wyborcy.

    Każdy użytkownik ma dokładnie jeden profil powiązany z węzłem hierarchii
    (`territorial_unit`: kraj … obwód).

    Głosować może tylko użytkownik przypisany do obwodu wyborczego
    (`territorial_unit.kind == precinct`). W UI wybór „komisji” ustawia
    właśnie ten obwód — sama komisja nie jest przechowywana w profilu.
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
            "Węzeł hierarchii wyborcy. Minimum: kraj. "
            "Do głosowania wymagany obwód wyborczy (kind=precinct)."
        ),
    )
    birth_date = models.DateField(
        "data urodzenia",
        null=True,
        blank=True,
        help_text="Wymagana do weryfikacji limitu wieku w okręgu wyborczym.",
    )
    second_name = models.CharField(
        "drugie imię",
        max_length=150,
        blank=True,
        default="",
        help_text="Opcjonalne drugie imię.",
    )

    class Meta:
        verbose_name = "profil wyborcy"
        verbose_name_plural = "profile wyborców"

    def __str__(self) -> str:
        name = self.full_name()
        if self.territorial_unit_id:
            return f"{name} ({self.territorial_unit})"
        return name

    def full_name(self) -> str:
        parts = [
            self.user.first_name,
            self.second_name,
            self.user.last_name,
        ]
        return " ".join(p for p in parts if p).strip() or (
            self.user.email or str(self.user_id)
        )

    def residence_municipality_name(self) -> str | None:
        """Nazwa gminy zamieszkania (przodek kind=municipality), o ile jest."""
        unit = self.territorial_unit
        if unit is None:
            return None
        gmina = _ancestor_of_kind(unit, TerritorialUnit.Kind.MUNICIPALITY)
        return gmina.name if gmina is not None else None

    def can_vote(self) -> bool:
        """Głosować może tylko użytkownik przypisany do obwodu."""
        unit = self.territorial_unit
        return bool(unit and unit.kind == TerritorialUnit.Kind.PRECINCT)

    def effective_unit(self) -> TerritorialUnit | None:
        """Węzeł używany do wyznaczania uprawnień."""
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
    """
    Urząd / rodzaj mandatu (np. Poseł na Sejm RP, Prezydent Miasta).

    Ograniczenia (wiek, poziom terytorialny kandydatury) ustawiane są tu,
    nie na poziomie pojedynczego okręgu.
    """

    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    description = models.TextField("opis", blank=True)
    is_open = models.BooleanField(
        "głosowanie otwarte",
        default=True,
        help_text="Czy użytkownicy mogą oddawać i zmieniać głosy na okręgi tego urzędu.",
    )
    min_age = models.PositiveSmallIntegerField(
        "minimalny wiek",
        default=18,
        help_text="Minimalny wiek (w latach) wymagany do głosowania i kandydowania.",
    )
    candidacy_level = models.ForeignKey(
        "geo.TerritorialLevel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="offices",
        verbose_name="poziom kandydatury",
        help_text=(
            "Na jakim poziomie hierarchii kandydat musi pokrywać się z okręgiem. "
            "Np. kraj = każdy z kraju; gmina = ta sama gmina; "
            "województwo = to samo województwo."
        ),
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

    Wiek i poziom kandydatury: patrz `Office`.
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


class CandidateRequest(models.Model):
    """
    Prośba wyborcy o dodanie osoby, której nie ma jeszcze w systemie.

    Wyborca może samodzielnie pojawić się w rankingu (jako zarejestrowany
    użytkownik). Inne osoby dodaje admin po zatwierdzeniu tej prośby.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Oczekująca"
        APPROVED = "approved", "Zatwierdzona"
        REJECTED = "rejected", "Odrzucona"

    district = models.ForeignKey(
        ElectoralDistrict,
        on_delete=models.CASCADE,
        related_name="candidate_requests",
        verbose_name="okręg",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate_requests",
        verbose_name="zgłaszający",
    )
    first_name = models.CharField("imię", max_length=150)
    last_name = models.CharField("nazwisko", max_length=150)
    birth_date = models.DateField("data urodzenia")
    note = models.TextField("uwaga dla admina", blank=True)
    status = models.CharField(
        "status",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    admin_note = models.TextField("notatka admina", blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_candidate_requests",
        verbose_name="rozpatrzył",
    )
    reviewed_at = models.DateTimeField("rozpatrzono", null=True, blank=True)
    created_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_from_candidate_requests",
        verbose_name="utworzony użytkownik",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "prośba o kandydata"
        verbose_name_plural = "prośby o kandydatów"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.get_status_display()})"
