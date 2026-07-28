"""SMTP backend z opcją wyłączenia weryfikacji certyfikatu TLS (lokalny Postfix)."""

from __future__ import annotations

import ssl

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.core.mail.utils import DNS_NAME


def build_ssl_context():
    """Kontekst TLS: bez weryfikacji gdy EMAIL_SSL_VERIFY=False."""
    if not getattr(settings, "EMAIL_SSL_VERIFY", True):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


class EmailBackend(SMTPBackend):
    """
    Lokalny Postfix na 127.0.0.1 wymaga STARTTLS, ale cert nie obejmuje IP.
    Przy EMAIL_SSL_VERIFY=False pomija weryfikację certyfikatu.
    """

    def open(self):
        if self.connection:
            return False

        if self._partial_connection is not None:
            self._close_connection(self._partial_connection)
            self._partial_connection = None

        connection_params = {"local_hostname": DNS_NAME.get_fqdn()}
        if self.timeout is not None:
            connection_params["timeout"] = self.timeout

        ssl_context = build_ssl_context()
        # Wymuś kontekst także przez atrybut (Django 6 cached_property).
        self.__dict__["ssl_context"] = ssl_context

        if self.use_ssl:
            connection_params["context"] = ssl_context

        try:
            self._partial_connection = self.connection_class(
                self.host, self.port, **connection_params
            )
            if not self.use_ssl and self.use_tls:
                self._partial_connection.starttls(context=ssl_context)
            if self.username and self.password:
                self._partial_connection.login(self.username, self.password)
            self.connection = self._partial_connection
            self._partial_connection = None
            return True
        except OSError:
            if not self.fail_silently:
                raise
            return None
