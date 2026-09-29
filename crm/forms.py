"""Formulare der Personenverwaltung (Audit Etappe 2, Nachtrag Person)."""
import re
from datetime import date

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _t

#: Freitextfelder des Personenformulars. Geprüft wird nur ihre Länge — ohne
#: diese Prüfung endete ein zu langer Wert auf PostgreSQL mit einem
#: Serverfehler, und alle übrigen Eingaben waren weg.
FREITEXT = (
    'anrede', 'vorname', 'nachname', 'firmen_name', 'uid_nummer', 'kontaktperson',
    'telefon_privat', 'telefon_geschaeft', 'mobile', 'strasse', 'adresszusatz',
    'ort', 'land', 'zivilstand', 'nationalitaet', 'heimatort', 'ahv_nummer',
    'aufenthaltsbewilligung', 'erwerbsstatus', 'beruf', 'arbeitgeber',
    'einkommen_jahr', 'haftpflicht_gesellschaft', 'haftpflicht_police',
    'notfall_name', 'notfall_telefon', 'notfall_beziehung', 'haustiere_details',
    'bank_name', 'betreibung_ergebnis', 'zahler_name', 'zahler_adresse',
    'ref_vermieter_name', 'ref_vermieter_telefon', 'vertretung_art',
    'vertretung_name', 'vertretung_kontakt',
)

#: Mehr Personen in einem Haushalt ist ein Tippfehler, keine Grossfamilie.
HAUSHALT_MAX = 30


class PersonForm(forms.Form):
    """Prüft das Personenformular, bevor gespeichert wird.

    Vorher las die Ansicht `request.POST` von Hand aus:
    - Ein unlesbares Geburtsdatum, Bewilligungsende oder Bonitätsdatum wurde
      still LEER gespeichert — eine ablaufende Aufenthaltsbewilligung fiel so
      aus jeder Frist heraus.
    - Eine unlesbare Personenzahl im Haushalt wurde still 0.
    - Die IBAN des abweichenden Zahlers wurde gar nicht geprüft.
    - Fehler erschienen als Meldung oben rechts, nicht am Feld.

    Gespeichert wird weiterhin in der Ansicht (Adresshistorie, Dublettenprüfung,
    Logbuch); dieses Formular sagt nur, ob und wo etwas nicht stimmt.
    """

    typ = forms.ChoiceField(choices=(('person', 'person'), ('firma', 'firma'),
                                     ('verein', 'verein')))
    email = forms.EmailField(required=False)
    ebill_email = forms.EmailField(required=False)
    ref_vermieter_email = forms.EmailField(required=False)
    plz = forms.CharField(required=False, max_length=10)
    geburtsdatum = forms.DateField(required=False)
    bewilligung_gueltig_bis = forms.DateField(required=False)
    bonitaet_datum = forms.DateField(required=False)
    haushalt_erwachsene = forms.IntegerField(required=False, min_value=0, max_value=HAUSHALT_MAX)
    haushalt_kinder = forms.IntegerField(required=False, min_value=0, max_value=HAUSHALT_MAX)
    iban = forms.CharField(required=False, max_length=50)
    zahler_iban = forms.CharField(required=False, max_length=50)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from crm.models import Mieter
        for name in FREITEXT:
            self.fields[name] = forms.CharField(
                required=False, max_length=Mieter._meta.get_field(name).max_length)

    def clean_geburtsdatum(self):
        d = self.cleaned_data.get('geburtsdatum')
        if d and not (date(1900, 1, 1) <= d <= timezone.localdate()):
            raise forms.ValidationError(_t('Dieses Geburtsdatum ist nicht möglich.'))
        return d

    def clean_bonitaet_datum(self):
        d = self.cleaned_data.get('bonitaet_datum')
        if d and d > timezone.localdate():
            raise forms.ValidationError(_t('Eine Bonitätsprüfung kann nicht in der Zukunft liegen.'))
        return d

    def _iban(self, feld):
        from core.services.iban import formatiere_iban, ist_gueltige_iban
        wert = (self.cleaned_data.get(feld) or '').strip()
        if not wert:
            return ''
        if not ist_gueltige_iban(wert):
            raise forms.ValidationError(_t('Diese IBAN ist ungültig — bitte Länge und Prüfziffer kontrollieren.'))
        return formatiere_iban(wert)

    def clean_iban(self):
        return self._iban('iban')

    def clean_zahler_iban(self):
        return self._iban('zahler_iban')

    def clean(self):
        daten = super().clean()
        typ = daten.get('typ')
        if typ in ('firma', 'verein'):
            if not daten.get('firmen_name'):
                self.add_error('firmen_name', _t('Der Firmen- oder Organisationsname fehlt.'))
        elif typ == 'person' and not daten.get('nachname'):
            self.add_error('nachname', _t('Der Nachname fehlt.'))
        # Eine Schweizer PLZ hat vier Ziffern. Ausländische Adressen (Land
        # gesetzt und nicht Schweiz) haben andere Formen und bleiben frei.
        plz = (daten.get('plz') or '').strip()
        land = (daten.get('land') or '').strip().casefold()
        if plz and land in ('', 'schweiz', 'suisse', 'svizzera', 'switzerland', 'ch') \
                and not re.fullmatch(r'\d{4}', plz):
            self.add_error('plz', _t('Eine Schweizer Postleitzahl hat vier Ziffern.'))
        return daten
