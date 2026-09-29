"""Formulare der Liegenschaftsverwaltung.

Eigenes Modul statt `core/forms.py`: Dort baut `SchadenForm` beim IMPORT ein
`Liegenschaft.objects.all()` — ausserhalb einer Anfrage wirft das
(`OrganisationsFehler`), innerhalb fröre es den Filter der ersten Anfrage ein.
`core/forms.py` wird heute von niemandem importiert; dieses Modul soll es
nicht nebenbei zum Leben erwecken.
"""
from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _t

from portfolio.models import Liegenschaft


class LiegenschaftForm(forms.ModelForm):
    """Prüft die Stammdaten einer Liegenschaft, statt Fehler zu verschlucken.

    Vorher wertete die Ansicht `request.POST` von Hand aus: Eine Zahl, die sich
    nicht lesen liess («12.5.1990» im Baujahr, «ca. 2 Mio» im Verkehrswert),
    wurde STILL als leer gespeichert, eine unbekannte Heizart ebenso. Jetzt
    kommt das Formular mit der Meldung am Feld zurück, und die Eingabe bleibt
    stehen.

    Nicht hier: `eigentuemer` und `betreut_von`. Beide sind Mandantengrenzen,
    die die Ansicht selbst gegen die eigene Organisation prüft
    (`team_der_organisation`, `TenantManager`) — sie melden ihre Fehler aber
    über `add_error` in dieses Formular, damit alles an einer Stelle steht.
    """

    #: Beträge und Flächen: kommen mit Schweizer Tausender-Apostroph zurück
    #: («CHF 1'250'000.00»), weil der `chf`-Filter sie so anzeigt.
    ZAHLENFELDER = ('versicherungswert', 'grundstuecksflaeche_m2', 'gebaeudevolumen_m3',
                    'verkehrswert', 'anlagekosten', 'kaufpreis', 'energiebezugsflaeche_m2')

    class Meta:
        model = Liegenschaft
        fields = (
            'strasse', 'plz', 'ort', 'kanton', 'egid', 'kataster_nummer', 'baujahr',
            'versicherungswert', 'grundstuecksflaeche_m2', 'gebaeudevolumen_m3',
            'verkehrswert', 'anlagekosten', 'kaufpreis', 'energiebezugsflaeche_m2',
            'heizsystem', 'warmwasser', 'geak_klasse', 'geak_klasse_gesamt',
            'energietraeger', 'geak_datum',
            'hauswart_name', 'hauswart_telefon', 'sanitaer_name', 'sanitaer_telefon',
            'elektriker_name', 'elektriker_telefon', 'bank_name', 'iban',
            'hkvo_aktiv', 'hkvo_grundkosten_prozent',
        )

    def __init__(self, data=None, *args, **kwargs):
        if data is not None:
            from core.views.fw._basis import _num
            data = data.copy()
            for name in self.ZAHLENFELDER:
                if data.get(name):
                    data[name] = _num(data[name])
            for name in ('geak_klasse', 'geak_klasse_gesamt', 'kanton'):
                data[name] = (data.get(name) or '').strip().upper()
            # Leeres Feld = Standard 40 %, wie bisher. Nur eine UNLESBARE
            # Eingabe ist ein Fehler.
            if not (data.get('hkvo_grundkosten_prozent') or '').strip():
                data['hkvo_grundkosten_prozent'] = '40'
        super().__init__(data, *args, **kwargs)
        # `egid` ist in der Datenbank nullbar; die Ansicht speicherte bisher ''.
        # Dabei bleibt es — `not lg.egid` fragt beides ab, ein Filter auf ''
        # nicht.
        self.fields['egid'].empty_value = ''

    def clean_plz(self):
        plz = (self.cleaned_data.get('plz') or '').strip()
        if not (len(plz) == 4 and plz.isdigit()):
            raise forms.ValidationError(_t('Bitte eine vierstellige Postleitzahl angeben.'))
        return plz

    def clean_kanton(self):
        from core.services.kantone import KANTON_NAMEN
        kanton = self.cleaned_data.get('kanton') or ''
        if kanton and kanton not in KANTON_NAMEN:
            raise forms.ValidationError(_t('Unbekanntes Kantonskürzel (z. B. ZH, BE, SO).'))
        return kanton

    def clean_baujahr(self):
        # Plausibilitaet, keine Fachregel: Tippfehler wie «198» oder «19888»
        # sollen auffallen, statt in Rendite und Ersatzplanung zu rechnen.
        jahr = self.cleaned_data.get('baujahr')
        if jahr is not None and not (1000 <= jahr <= timezone.localdate().year + 10):
            raise forms.ValidationError(_t('Bitte ein Baujahr als vierstellige Jahreszahl angeben.'))
        return jahr

    def clean_hkvo_grundkosten_prozent(self):
        # Ein Anteil in Prozent. Das Modell kennt keine Grenze; bisher hielt
        # nur `max="100"` im Browser dagegen, und das umging jeder POST.
        wert = self.cleaned_data.get('hkvo_grundkosten_prozent')
        if wert is not None and not (0 <= wert <= 100):
            raise forms.ValidationError(_t('Der Anteil muss zwischen 0 und 100 % liegen.'))
        return wert

    def clean_iban(self):
        from core.services.iban import ist_gueltige_iban
        iban = (self.cleaned_data.get('iban') or '').strip()
        if iban and not ist_gueltige_iban(iban):
            raise forms.ValidationError(_t('Diese IBAN ist ungültig — bitte Länge und Prüfziffer kontrollieren.'))
        return iban
