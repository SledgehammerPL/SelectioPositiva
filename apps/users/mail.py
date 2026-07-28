"""SMTP backend z opcją wyłączenia weryfikacji certyfikatu TLS (lokalny Postfix)."""

from __future__ import annotations

import ssl

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend


class EmailBackend(SMTPBackend):
    """
    Jak standardowy SMTP, ale gdy EMAIL_SSL_VERIFY=False tworzy
    ssl context bez weryfikacji certyfikatu (self-signed / localhost).
    """

    def open(self):
        if self.ssl_context is None and not getattr(settings, "EMAIL_SSL_VERIFY", True):
            self.ssl_context = ssl._create_unverified_context()
        return super().open()
