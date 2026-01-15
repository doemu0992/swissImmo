from django import forms
from .models import SchadenMeldung, TicketNachricht, Liegenschaft

# ==============================================================================
# 1. MIETZINSANPASSUNG
# ==============================================================================
class MietanpassungForm(forms.Form):
    alt_zins = forms.DecimalField(label="Zins (Alt) %", max_digits=4, decimal_places=2, required=True)
    neu_zins = forms.DecimalField(label="Zins (Neu) %", max_digits=4, decimal_places=2, required=True)
    alt_index = forms.DecimalField(label="Index (Alt)", max_digits=6, decimal_places=1, required=True)
    neu_index = forms.DecimalField(label="Index (Neu)", max_digits=6, decimal_places=1, required=True)
    alt_miete = forms.DecimalField(label="Bisherige Miete", max_digits=8, decimal_places=2, required=True)
    alt_nk = forms.DecimalField(label="Bisherige NK", max_digits=8, decimal_places=2, required=True)
    neue_miete = forms.DecimalField(label="Neue Nettomiete", max_digits=8, decimal_places=2, required=False)
    neue_nk = forms.DecimalField(label="Neue Nebenkosten", max_digits=8, decimal_places=2, required=False)
    datum_wirksam = forms.CharField(label="Wirksam ab", initial="01.04.2026")
    begruendung = forms.CharField(label="Begründung (für PDF)", widget=forms.Textarea(attrs={'rows': 2}), required=False)
    differenz = forms.DecimalField(widget=forms.HiddenInput(), required=False)
    total_prozent = forms.CharField(widget=forms.HiddenInput(), required=False)

# ==============================================================================
# 2. SCHADENMELDUNG (Ticket Erstellen)
# ==============================================================================
class SchadenForm(forms.ModelForm):
    # Auswahl der Liegenschaft für den Mieter (oder hidden field)
    liegenschaft = forms.ModelChoiceField(
        queryset=Liegenschaft.objects.all(),
        empty_label="Bitte Liegenschaft wählen",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = SchadenMeldung
        fields = [
            'liegenschaft', 'titel', 'beschreibung', 'foto',
            'mieter_email', 'mieter_telefon', 'zutritt'
        ]
        widgets = {
            'titel': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Kurzer Titel (z.B. Heizung tropft)'}),
            'beschreibung': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Bitte beschreiben Sie das Problem...'}),
            'mieter_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Ihre E-Mail'}),
            'mieter_telefon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tel. Nr.'}),
            'zutritt': forms.Select(attrs={'class': 'form-select'}),
            'foto': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'titel': 'Was ist defekt?',
            'zutritt': 'Zutritt für Handwerker',
        }

# ==============================================================================
# 3. CHAT / NACHRICHTEN (Antworten)
# ==============================================================================
class NachrichtForm(forms.ModelForm):
    class Meta:
        model = TicketNachricht
        fields = ['nachricht', 'datei']
        widgets = {
            'nachricht': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Ihre Antwort schreiben...'}),
            'datei': forms.FileInput(attrs={'class': 'form-control'}),
        }