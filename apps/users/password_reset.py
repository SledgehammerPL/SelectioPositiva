"""Widoki resetu hasła (email)."""

from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy

from users.forms import EmailPasswordResetForm, EmailSetPasswordForm


class SpPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    form_class = EmailPasswordResetForm
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        # Użyj DEFAULT_FROM_EMAIL z settings (domena akceptowana przez Postfix).
        from django.conf import settings

        self.from_email = settings.DEFAULT_FROM_EMAIL
        return super().form_valid(form)


class SpPasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class SpPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    form_class = EmailSetPasswordForm
    success_url = reverse_lazy("password_reset_complete")


class SpPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"
