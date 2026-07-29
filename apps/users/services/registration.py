"""Rejestracja konta z weryfikacją email."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from elections.models import VoterProfile

User = get_user_model()


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp) -> str:
        return f"{user.pk}{user.email}{user.is_active}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()


def make_email_uid(user) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


def parse_email_uid(uidb64: str) -> int | None:
    try:
        return int(force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError):
        return None


@transaction.atomic
def register_user(*, email: str, password: str) -> User:
    """Tworzy nieaktywne konto (email + hasło) i pusty profil wyborcy."""
    normalized = email.strip().lower()
    user = User(
        username=f"_tmp_{normalized[:20]}",
        email=normalized,
        is_active=False,
    )
    user.set_password(password)
    user.save()
    user.username = f"u{user.pk}"
    user.save(update_fields=["username"])

    VoterProfile.objects.create(user=user, is_approved=False)
    return user


def activate_user_from_token(*, uidb64: str, token: str) -> User | None:
    pk = parse_email_uid(uidb64)
    if pk is None:
        return None
    user = User.objects.filter(pk=pk).first()
    if user is None or user.is_active:
        return None
    if not email_verification_token.check_token(user, token):
        return None
    user.is_active = True
    user.save(update_fields=["is_active"])
    return user
