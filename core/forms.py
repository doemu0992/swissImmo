from django import forms
from .models import SchadenMeldung

# --- 1. MIETZINSANPASSUNG ---
class MietanpassungForm(forms.Form):
    # --- TEIL 1: DIE GRUNDLAGEN ---
    alt_zins = forms.DecimalField(label="Zins (Alt) %", max_digits=4, decimal_places=2, required=True)
    neu_zins = forms.DecimalField(label="Zins (Neu) %", max_digits=4, decimal_places=2, required=True)

    alt_index = forms.DecimalField(label="Index (Alt)", max_digits=6, decimal_places=1, required=True)
    neu_index = forms.DecimalField(label="Index (Neu)", max_digits=6, decimal_places=1, required=True)

    # --- TEIL 2: DIE FINANZEN ---
    alt_miete = forms.DecimalField(label="Bisherige Miete", max_digits=8, decimal_places=2, required=True)
    alt_nk = forms.DecimalField(label="Bisherige NK", max_digits=8, decimal_places=2, required=True)

    # Das Ergebnis (wird berechnet)
    neue_miete = forms.DecimalField(label="Neue Nettomiete", max_digits=8, decimal_places=2, required=False)
    neue_nk = forms.DecimalField(label="Neue Nebenkosten", max_digits=8, decimal_places=2, required=False)

    # --- TEIL 3: SONSTIGES ---
    datum_wirksam = forms.CharField(label="Wirksam ab", initial="01.04.2026")
    begruendung = forms.CharField(label="Begründung (für PDF)", widget=forms.Textarea(attrs={'rows': 2}), required=False)

    # Versteckte Felder für Statistik
    differenz = forms.DecimalField(widget=forms.HiddenInput(), required=False)
    total_prozent = forms.CharField(widget=forms.HiddenInput(), required=False)

# --- 2. SCHADENMELDUNG (KORRIGIERT) ---
class SchadenForm(forms.ModelForm):
    class Meta:
        model = SchadenMeldung
        # KORREKTUR: 'bild' zu 'foto' geändert, 'prioritaet' entfernt
        fields = ['betreff', 'beschreibung', 'foto', 'gemeldet_von']
        widgets = {
            'betreff': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. Heizung tropft'}),
            'beschreibung': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Bitte beschreiben Sie das Problem...'}),
            'gemeldet_von': forms.Select(attrs={'class': 'form-select'}),
            # KORREKTUR: Widget für 'foto' angepasst
            'foto': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'foto': 'Foto hochladen (optional)',
            'betreff': 'Was ist passiert?',
            'beschreibung': 'Beschreibung'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['gemeldet_von'].required = False
        self.fields['gemeldet_von'].label = "Ihr Name (Optional)"