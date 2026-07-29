from django import forms


class CandidateRequestForm(forms.Form):
    first_name = forms.CharField(
        label="Imię",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "Imię", "autocomplete": "given-name"}
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
            attrs={"placeholder": "Nazwisko", "autocomplete": "family-name"}
        ),
    )
    birth_date = forms.DateField(
        label="Data urodzenia",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    note = forms.CharField(
        label="Uwaga",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Opcjonalnie: skąd znasz tę osobę, partia…",
            }
        ),
    )

    def clean_first_name(self) -> str:
        return (self.cleaned_data.get("first_name") or "").strip()

    def clean_second_name(self) -> str:
        return (self.cleaned_data.get("second_name") or "").strip()

    def clean_last_name(self) -> str:
        return (self.cleaned_data.get("last_name") or "").strip()

    def clean_note(self) -> str:
        return (self.cleaned_data.get("note") or "").strip()
