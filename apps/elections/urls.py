from django.urls import path

from elections import views

urlpatterns = [
    path("login/", views.ElectionLoginView.as_view(), name="login"),
    path("logout/", views.ElectionLogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("vote/<slug:slug>/", views.vote_district, name="vote_district"),
    path("vote/<slug:slug>/clear/", views.clear_ballot, name="clear_ballot"),
    path("results/", views.results, name="results"),
]
