from django.db import models


class TerritorialUnit(models.Model):
    """
    Węzeł hierarchii administracyjno-wyborczej.

    Hierarchia (od najszerszego do najwęższego):
      kraj → województwo → powiat → gmina → obwód (precinct)

    Obwód wyborczy (`kind=precinct`) to podzbiór ulic/wsi pokrywający
    razem z innymi obwodami całą gminę. Komisja wyborcza jest przypisana
    do dokładnie jednego obwodu.

    Hierarchia jest dowolna (wynika wyłącznie z `parent`) — w innych
    krajach może być więcej lub mniej poziomów.
    """

    class Kind(models.TextChoices):
        COUNTRY = "country", "Kraj"
        VOIVODESHIP = "voivodeship", "Województwo"
        COUNTY = "county", "Powiat"
        DISTRICT = "district", "Okręg wyborczy (przestarzałe)"
        MUNICIPALITY = "municipality", "Gmina"
        PRECINCT = "precinct", "Obwód wyborczy"

    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    kind = models.CharField("rodzaj", max_length=20, choices=Kind.choices)
    teryt = models.CharField(
        "TERYT",
        max_length=7,
        blank=True,
        db_index=True,
        help_text="Kod TERYT (2/4/6 cyfr) dla jednostek administracyjnych.",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="jednostka nadrzędna",
    )
    # GeoJSON Polygon / MultiPolygon (EPSG:4326) do rysowania granic na mapie.
    boundary = models.JSONField("granica (GeoJSON)", null=True, blank=True)
    center_lat = models.DecimalField(
        "środek (szerokość)",
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    center_lng = models.DecimalField(
        "środek (długość)",
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "jednostka terytorialna"
        verbose_name_plural = "jednostki terytorialne"
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.name}"

    def get_ancestors(self, *, include_self: bool = True) -> list["TerritorialUnit"]:
        """Lista od korzenia do tej jednostki (lub bez niej)."""
        chain: list[TerritorialUnit] = []
        current: TerritorialUnit | None = self if include_self else self.parent
        seen: set[int] = set()
        while current is not None and current.pk not in seen:
            chain.append(current)
            seen.add(current.pk)
            current = current.parent
        chain.reverse()
        return chain


class PollingStation(models.Model):
    """
    Komisja wyborcza — przypisana do dokładnie jednego obwodu wyborczego.

    Hierarchia uprawnień wynika wyłącznie z drzewa `parent` obwodu:
    obwód → gmina → powiat → województwo → kraj.
    """

    name = models.CharField("nazwa", max_length=200)
    code = models.CharField("kod", max_length=64, unique=True)
    number = models.PositiveIntegerField(
        "numer komisji",
        null=True,
        blank=True,
        db_index=True,
        help_text="Numer obwodu głosowania (np. z PKW).",
    )
    precinct = models.ForeignKey(
        TerritorialUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="polling_stations",
        verbose_name="obwód wyborczy",
        limit_choices_to={"kind": TerritorialUnit.Kind.PRECINCT},
        help_text="Obwód wyborczy (węzeł w hierarchii), do którego należy komisja.",
    )
    address = models.CharField("adres", max_length=300)
    streets_served = models.TextField(
        "obsługiwane ulice",
        blank=True,
        help_text="Opis ulic / granic obwodu obsługiwanych przez komisję.",
    )
    latitude = models.DecimalField(
        "szerokość geograficzna",
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        "długość geograficzna",
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "komisja wyborcza"
        verbose_name_plural = "komisje wyborcze"
        ordering = ["number", "name"]

    def __str__(self) -> str:
        if self.number is not None:
            return f"Nr {self.number} — {self.name}"
        return f"{self.code} — {self.name}"

    def ancestor_unit_ids(self) -> list[int]:
        """
        IDs całego łańcucha jednostek od obwodu do korzenia (włącznie).
        Używane przez eligibility — okręg jest osiągalny, gdy jeden
        z jego territorial_units leży na tej ścieżce.
        """
        return [u.pk for u in self.precinct.get_ancestors(include_self=True)]
