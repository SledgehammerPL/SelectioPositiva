from django.db import models


class TerritorialUnit(models.Model):
    """Jednostka podziału terytorialnego (hierarchia parent → children)."""

    class Kind(models.TextChoices):
        COUNTRY = "country", "Kraj"
        VOIVODESHIP = "voivodeship", "Województwo"
        DISTRICT = "district", "Okręg"
        MUNICIPALITY = "municipality", "Gmina"

    name = models.CharField("nazwa", max_length=200)
    slug = models.SlugField("slug", max_length=200, unique=True)
    kind = models.CharField("rodzaj", max_length=20, choices=Kind.choices)
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
    """Komisja wyborcza przypisana do jednostki terytorialnej."""

    name = models.CharField("nazwa", max_length=200)
    code = models.CharField("kod", max_length=32, unique=True)
    territorial_unit = models.ForeignKey(
        TerritorialUnit,
        on_delete=models.PROTECT,
        related_name="polling_stations",
        verbose_name="jednostka terytorialna",
    )
    address = models.CharField("adres", max_length=300)
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
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
