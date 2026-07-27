from django import forms

from elections.models import CandidateRequest


class CandidateRequestForm(forms.ModelForm):
    class Meta:
        model = CandidateRequest
        fields = ("first_name", "last_name", "birth_date", "note")
        widgets = {
            "first_name": forms.TextInput(
                attrs={"placeholder": "Imię", "autocomplete": "given-name"}
            ),
            "last_name": forms.TextInput(
                attrs={"placeholder": "Nazwisko", "autocomplete": "family-name"}
            ),
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Opcjonalnie: skąd znasz tę osobę, partia…",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].label = "Imię"
        self.fields["last_name"].label = "Nazwisko"
        self.fields["birth_date"].label = "Data urodzenia"
        self.fields["note"].label = "Uwaga"
        self.fields["note"].required = False
