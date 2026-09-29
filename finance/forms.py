"""Formulare der Kreditorenbuchhaltung (Audit Etappe 2)."""
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _t

from core.formfelder import SchweizerZahl


class KreditorForm(forms.Form):
    """Erfassen und Bearbeiten einer Kreditorenrechnung.

    Vorher wertete die Ansicht `request.POST` von Hand aus:
    - Ein unlesbares Rechnungsdatum beim Erfassen war ein SERVERFEHLER
      (`date.fromisoformat` ungeschützt).
    - Ein unlesbarer MWST-Satz wurde still 0 % — und damit ein falscher
      Vorsteuerabzug bei der Freigabe.
    - Ein unlesbarer Betrag beim Bearbeiten wurde still leer.
    - Die IBAN wurde nicht geprüft; eine falsche fiel erst im Zahllauf auf.

    `erfassen=True`: Betrag ist Pflicht (Neuerfassung von Hand). Beim
    Bearbeiten darf er fehlen — gescannte Belege kommen oft ohne erkannten
    Betrag an und werden hier erst vervollständigt.

    Liegenschaft und Konto prüft die Ansicht (Mandantengrenze über den
    `TenantManager`).
    """

    lieferant = forms.CharField(max_length=200)
    betrag = SchweizerZahl(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), required=False)
    # Zwei Nachkommastellen ANNEHMEN, eine speichern: «8.10» ist 8.1 und kein
    # Fehler. `clean_mwst_satz` lehnt nur ab, was sich nicht verlustfrei kürzen
    # lässt («7.75»).
    mwst_satz = SchweizerZahl(max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False)
    datum = forms.DateField(required=False)
    faellig_am = forms.DateField(required=False)
    leistungs_von = forms.DateField(required=False)
    leistungs_bis = forms.DateField(required=False)
    referenz = forms.CharField(max_length=100, required=False)
    iban = forms.CharField(max_length=50, required=False)

    def __init__(self, *args, erfassen=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['betrag'].required = erfassen

    def clean_mwst_satz(self):
        satz = self.cleaned_data.get('mwst_satz')
        if satz is None:
            return None
        gekuerzt = satz.quantize(Decimal('0.1'))
        if gekuerzt != satz:
            raise forms.ValidationError(_t('Der MWST-Satz hat höchstens eine Nachkommastelle (z. B. 8.1).'))
        return gekuerzt

    def clean_iban(self):
        from core.services.iban import ist_gueltige_iban, normalisiere_iban
        iban = (self.cleaned_data.get('iban') or '').strip()
        if not iban:
            return ''
        if not ist_gueltige_iban(iban):
            raise forms.ValidationError(_t('Diese IBAN ist ungültig — bitte Länge und Prüfziffer kontrollieren.'))
        # Ohne Leerzeichen gespeichert, wie bisher.
        return normalisiere_iban(iban)

    def clean(self):
        daten = super().clean()
        von, bis = daten.get('leistungs_von'), daten.get('leistungs_bis')
        if von and bis and von > bis:
            self.add_error('leistungs_bis', _t('«Leistung bis» liegt vor «Leistung von».'))
        return daten
