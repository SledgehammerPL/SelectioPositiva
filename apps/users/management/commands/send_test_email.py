from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Wyślij testowy email przez aktualną konfigurację Django (EMAIL_*)."

    def add_arguments(self, parser):
        parser.add_argument(
            "to",
            nargs="?",
            default="",
            help="Adres odbiorcy (domyślnie: pytaj / DEFAULT_FROM_EMAIL)",
        )
        parser.add_argument(
            "--from",
            dest="from_email",
            default="",
            help="Nadawca (domyślnie DEFAULT_FROM_EMAIL)",
        )
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Test surowego SMTP (bez Django EmailMessage) — pokazuje odpowiedzi serwera",
        )

    def handle(self, *args, **options):
        from django.conf import settings
        from django.core.mail import get_connection, send_mail

        to = (options["to"] or "").strip()
        if not to:
            to = input("Adres odbiorcy: ").strip()
        if not to:
            self.stderr.write(self.style.ERROR("Brak adresu odbiorcy."))
            return

        from_email = (options["from_email"] or settings.DEFAULT_FROM_EMAIL).strip()

        self.stdout.write("Konfiguracja Django:")
        self.stdout.write(f"  EMAIL_BACKEND     = {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  EMAIL_HOST        = {settings.EMAIL_HOST}")
        self.stdout.write(f"  EMAIL_PORT        = {settings.EMAIL_PORT}")
        self.stdout.write(f"  EMAIL_USE_TLS     = {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  EMAIL_USE_SSL     = {settings.EMAIL_USE_SSL}")
        self.stdout.write(
            f"  EMAIL_SSL_VERIFY  = {getattr(settings, 'EMAIL_SSL_VERIFY', True)}"
        )
        self.stdout.write(f"  FROM              = {from_email}")
        self.stdout.write(f"  TO                = {to}")

        if options["raw"]:
            self._raw_smtp(settings, from_email, to)
            return

        try:
            connection = get_connection(fail_silently=False)
            sent = send_mail(
                subject="Selectio Positiva — test SMTP",
                message=(
                    "To jest testowy email z manage.py send_test_email.\n"
                    f"Host: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}\n"
                ),
                from_email=from_email,
                recipient_list=[to],
                connection=connection,
                fail_silently=False,
            )
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"BŁĄD: {type(exc).__name__}: {exc}"))
            raise SystemExit(1) from exc

        self.stdout.write(self.style.SUCCESS(f"OK — send_mail zwrócił {sent}"))

    def _raw_smtp(self, settings, from_email: str, to: str) -> None:
        import smtplib
        import ssl
        from email.message import EmailMessage

        host = settings.EMAIL_HOST
        port = int(settings.EMAIL_PORT)
        self.stdout.write(f"\nSurowy SMTP -> {host}:{port}")

        try:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.set_debuglevel(1)
                code, msg = smtp.ehlo()
                self.stdout.write(f"EHLO -> {code} {msg!r}")

                if settings.EMAIL_USE_TLS:
                    ctx = None
                    if not getattr(settings, "EMAIL_SSL_VERIFY", True):
                        ctx = ssl._create_unverified_context()
                        self.stdout.write("STARTTLS z EMAIL_SSL_VERIFY=False")
                    code, msg = smtp.starttls(context=ctx)
                    self.stdout.write(f"STARTTLS -> {code} {msg!r}")
                    smtp.ehlo()

                if settings.EMAIL_HOST_USER:
                    smtp.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

                mail = EmailMessage()
                mail["From"] = from_email
                mail["To"] = to
                mail["Subject"] = "Selectio Positiva — raw SMTP test"
                mail.set_content("Test surowego SMTP (smtplib).")

                refused = smtp.send_message(mail)
                if refused:
                    self.stderr.write(self.style.ERROR(f"Odrzucone: {refused}"))
                    raise SystemExit(1)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"BŁĄD: {type(exc).__name__}: {exc}"))
            raise SystemExit(1) from exc

        self.stdout.write(self.style.SUCCESS("OK — raw SMTP wysłał wiadomość"))
