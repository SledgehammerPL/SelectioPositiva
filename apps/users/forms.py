from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password

from elections.models import VoterProfile

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

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Hasła nie są identyczne.")
        if p1:
            validate_password(p1)
        return cleaned


class ProfileDataForm(forms.Form):
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
    birth_date = forms.DateField(
        label="Data urodzenia",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        profile = getattr(user, "voter_profile", None)
        if not self.is_bound:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            if profile is not None:
                self.fields["second_name"].initial = profile.second_name
                self.fields["birth_date"].initial = profile.birth_date

    def clean_first_name(self) -> str:
        return (self.cleaned_data.get("first_name") or "").strip()

    def clean_second_name(self) -> str:
        return (self.cleaned_data.get("second_name") or "").strip()

    def clean_last_name(self) -> str:
        return (self.cleaned_data.get("last_name") or "").strip()

    def save(self) -> None:
        user = self.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.save(update_fields=["first_name", "last_name"])

        profile, _ = VoterProfile.objects.get_or_create(user=user)
        profile.second_name = self.cleaned_data.get("second_name") or ""
        profile.birth_date = self.cleaned_data["birth_date"]
        profile.save(update_fields=["second_name", "birth_date"])


class ProfilePasswordChangeForm(PasswordChangeForm):
    """Zmiana hasła z polskimi etykietami."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Obecne hasło"
        self.fields["new_password1"].label = "Nowe hasło"
        self.fields["new_password2"].label = "Powtórz nowe hasło"
        for name in ("old_password", "new_password1", "new_password2"):
            self.fields[name].widget.attrs.update(
                {"placeholder": "••••••••", "autocomplete": "new-password"}
            )
        self.fields["old_password"].widget.attrs["autocomplete"] = "current-password"
