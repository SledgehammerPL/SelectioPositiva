from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Formularz logowania: email zamiast loginu."""

    username = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.TextInput(
            attrs={
                "placeholder": "demo@selectio.local",
                "autocomplete": "email",
                "inputmode": "email",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs.update(
            {"placeholder": "••••••••", "autocomplete": "current-password"}
        )
        self.error_messages["invalid_login"] = "Nieprawidłowy email lub hasło."

    def clean_username(self) -> str:
        return (self.cleaned_data.get("username") or "").strip().lower()
