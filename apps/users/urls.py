from django.urls import path

from users import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "register/verify/<uidb64>/<token>/",
        views.verify_email,
        name="verify_email",
    ),
    path("settings/profile/", views.profile, name="profile"),
    path("settings/station/", views.change_station, name="change_station"),
    path(
        "settings/station/children/",
        views.station_unit_children,
        name="station_unit_children",
    ),
    path(
        "settings/station/stations/",
        views.station_unit_stations,
        name="station_unit_stations",
    ),
    path(
        "settings/station/preview/",
        views.preview_station_change_api,
        name="preview_station_change",
    ),
]
