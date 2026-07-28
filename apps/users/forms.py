from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


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


class RegistrationForm(forms.Form):
    first_name = forms.CharField(
        label="Pierwsze imię",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "Jan", "autocomplete": "given-name"}
        ),
    )
    second_name = forms.CharField(
        label="Drugie imię",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "opcjonalnie", "autocomplete": "additional-name"}
        ),
    )
    last_name = forms.CharField(
        label="Nazwisko",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "Kowalski", "autocomplete": "family-name"}
        ),
    )
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "jan@example.com",
                "autocomplete": "email",
                "inputmode": "email",
            }
        ),
    )
    birth_date = forms.DateField(
        label="Data urodzenia",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    password1 = forms.CharField(
        label="Hasło",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "••••••••", "autocomplete": "new-password"}
        ),
    )
    password2 = forms.CharField(
        label="Powtórz hasło",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "••••••••", "autocomplete": "new-password"}
        ),
    )

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Konto z tym adresem email już istnieje.")
        return email

    def clean_first_name(self) -> str:
        return (self.cleaned_data.get("first_name") or "").strip()

    def clean_second_name(self) -> str:
        return (self.cleaned_data.get("second_name") or "").strip()

    def clean_last_name(self) -> str:
        return (self.cleaned_data.get("last_name") or "").strip()

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Hasła nie są identyczne.")
        if p1:
            validate_password(p1)
        return cleaned
