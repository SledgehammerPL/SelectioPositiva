"""Autentykacja po email."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailAuthBackend(ModelBackend):
    """Logowanie: email + hasło."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        email = str(username).strip().lower()
        if not email:
            return None

        UserModel = get_user_model()
        user = UserModel.objects.filter(email__iexact=email).first()
        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
