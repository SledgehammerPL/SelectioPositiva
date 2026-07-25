from django.urls import path

from users import views

urlpatterns = [
    path("settings/station/", views.change_station, name="change_station"),
    path(
        "settings/station/preview/",
        views.preview_station_change_api,
        name="preview_station_change",
    ),
]
