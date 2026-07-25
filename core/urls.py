from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", home, name="home"),
    path("", include("elections.urls")),
    path("", include("users.urls")),
]
