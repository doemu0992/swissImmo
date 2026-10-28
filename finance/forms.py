"""Formulare der Kreditorenbuchhaltung (Audit Etappe 2)."""
import re
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
    # Anschrift des Lieferanten für die Zahlungsdatei (pain.001). Die Längen
    # sind die des ISO-Schemas. Beim Erfassen darf sie fehlen — der Zahllauf
    # verlangt sie vor der Dateierzeugung (Ort und Land).
    lieferant_strasse = forms.CharField(max_length=70, required=False)
    lieferant_hausnummer = forms.CharField(max_length=16, required=False)
    lieferant_plz = forms.CharField(max_length=16, required=False)
    lieferant_ort = forms.CharField(max_length=35, required=False)
    lieferant_land = forms.CharField(required=False)

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

    def clean_lieferant_land(self):
        return land_pruefen(self.cleaned_data.get('lieferant_land'))

    def clean(self):
        daten = super().clean()
        von, bis = daten.get('leistungs_von'), daten.get('leistungs_bis')
        if von and bis and von > bis:
            self.add_error('leistungs_bis', _t('«Leistung bis» liegt vor «Leistung von».'))
        adresse_pruefen(self, daten, 'lieferant_')
        return daten


def land_pruefen(wert):
    """Ländercode: leer heisst «CH» (Vorgabe), sonst zwei Buchstaben (ISO 3166)."""
    code = (wert or '').strip().upper()
    if not code:
        return 'CH'
    if not re.fullmatch(r'[A-Z]{2}', code):
        raise forms.ValidationError(_t('Zweibuchstabiger Ländercode, z. B. CH, DE, AT, FR, IT, LI.'))
    return code


def adresse_pruefen(form, daten, praefix):
    """Gemeinsame Prüfung der Anschrift (Kreditorformular und Adressseite):
    steht die Hausnummer noch in der Strasse, wird sie abgetrennt; und wer
    irgendeine Angabe macht, muss auch den Ort nennen — eine halbe Anschrift
    wäre in der Zahlungsdatei wertlos."""
    from core.utils.qr_code import strasse_und_nummer
    strasse = (daten.get(f'{praefix}strasse') or '').strip()
    nummer = (daten.get(f'{praefix}hausnummer') or '').strip()
    if strasse and not nummer:
        strasse, nummer = strasse_und_nummer(strasse)
        daten[f'{praefix}strasse'], daten[f'{praefix}hausnummer'] = strasse, nummer
    ort = (daten.get(f'{praefix}ort') or '').strip()
    angaben = any((daten.get(f'{praefix}{f}') or '').strip() for f in ('strasse', 'hausnummer', 'plz'))
    if angaben and not ort and not form.has_error(f'{praefix}ort'):
        form.add_error(f'{praefix}ort', _t('Ort fehlt — die Anschrift ist sonst unvollständig.'))


class KreditorAdresseForm(forms.Form):
    """Nur die Anschrift eines Kreditors — für Rechnungen, die schon freigegeben
    sind und deshalb sonst nicht mehr bearbeitet werden. Die Anschrift ändert
    keine Buchung; sie ergänzt, was die Zahlungsdatei braucht. Der Ort ist hier
    Pflicht: Wer diese Seite öffnet, will die Anschrift vervollständigen."""

    lieferant_strasse = forms.CharField(max_length=70, required=False)
    lieferant_hausnummer = forms.CharField(max_length=16, required=False)
    lieferant_plz = forms.CharField(max_length=16, required=False)
    lieferant_ort = forms.CharField(max_length=35, required=True,
                                    error_messages={'required': _t('Der Ort fehlt.')})
    lieferant_land = forms.CharField(required=False)

    def clean_lieferant_land(self):
        return land_pruefen(self.cleaned_data.get('lieferant_land'))

    def clean(self):
        daten = super().clean()
        adresse_pruefen(self, daten, 'lieferant_')
        return daten
