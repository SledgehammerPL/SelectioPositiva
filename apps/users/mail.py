"""SMTP backend z opcją wyłączenia weryfikacji certyfikatu TLS (lokalny Postfix)."""

from __future__ import annotations

import ssl

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.utils.functional import cached_property


class EmailBackend(SMTPBackend):
    """
    Jak standardowy SMTP, ale gdy EMAIL_SSL_VERIFY=False używa kontekstu
    bez weryfikacji certyfikatu (self-signed / IP mismatch na 127.0.0.1).
    """

    @cached_property
    def ssl_context(self):
        if not getattr(settings, "EMAIL_SSL_VERIFY", True):
            return ssl._create_unverified_context()
        # Django 6 default: verified TLS client context
        return super().ssl_context
