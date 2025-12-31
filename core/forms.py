from django import forms
from .models import SchadenMeldung, Mietvertrag

class SchadenMeldenForm(forms.ModelForm):
    mietvertrag = forms.ModelChoiceField(
        queryset=Mietvertrag.objects.filter(aktiv=True),
        label="Ihr Name / Wohnung",
        empty_label="-- Bitte auswählen --",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = SchadenMeldung
        fields = ['mietvertrag', 'betreff', 'beschreibung', 'foto', 'prioritaet']
        widgets = {
            'betreff': forms.TextInput(attrs={'class': 'form-control'}),
            'beschreibung': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'prioritaet': forms.Select(attrs={'class': 'form-control'}),
            'foto': forms.FileInput(attrs={'class': 'form-control'}),
        }
