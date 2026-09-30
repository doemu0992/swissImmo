"""Formulare rund um den Mietvertrag (Audit Etappe 2, Nachtrag Mietverhältnis)."""
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _t

from core.formfelder import SchweizerZahl

#: Mehr Personen in einer Wohnung ist ein Tippfehler, keine Grossfamilie.
PERSONEN_MAX = 30

#: Freitextfelder mit Längengrenze im Modell. Ohne diese Prüfung endete ein zu
#: langer Wert auf PostgreSQL mit einem Serverfehler.
FREITEXT = ('mitmieter_name', 'kuendigungstermine', 'zweckbestimmung', 'kautions_konto')


def _betrag(feld, **kw):
    """Betragsfeld mit der Stellenzahl des Modells — sonst lehnt erst die
    Datenbank ab (PostgreSQL: Serverfehler), und alle Eingaben sind weg."""
    from rentals.models import Mietvertrag
    f = Mietvertrag._meta.get_field(feld)
    return SchweizerZahl(max_digits=f.max_digits, decimal_places=f.decimal_places, **kw)


class VertragBearbeitenForm(forms.Form):
    """Prüft «Vertrag bearbeiten», bevor gespeichert wird.

    Vorher las die Ansicht `request.POST` von Hand aus:
    - Ein unlesbares Vertragsende wurde still LEER — und bei einem aktiven
      Vertrag folgt die Befristung dem Ende. Aus einem befristeten Vertrag
      wurde so ein unbefristeter, ohne Meldung.
    - Ein unlesbares «Erstmals kündbar auf» wurde still leer.
    - Eine unlesbare Kündigungsfrist oder Personenzahl blieb still beim alten
      Wert; man sah «gespeichert» und glaubte, die Änderung stehe.
    - Beim Entwurf wurde ein unlesbarer Nettomietzins still CHF 0.00, ein
      unlesbarer Mietbeginn still der alte.
    - Eine Index-Weitergabe von 0 % oder weniger wurde still ignoriert.

    `entwurf=False` (aktiver, gekündigter, archivierter Vertrag): Die
    mietzinswirksamen Felder sind gesperrt und werden hier gar nicht erst
    angenommen — das erzwingt weiterhin die Ansicht, dieses Formular prüft sie
    nur beim Entwurf.
    """

    ende = forms.DateField(required=False)
    erstmals_kuendbar = forms.DateField(required=False)
    kuendigungsfrist = forms.IntegerField(required=False, min_value=1)
    anzahl_personen = forms.IntegerField(required=False, min_value=1, max_value=PERSONEN_MAX)
    index_weitergabe_prozent = SchweizerZahl(required=False, max_digits=5, decimal_places=1)
    index_intervall_monate = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, entwurf=False, beginn=None, einheit=None, **kwargs):
        super().__init__(*args, **kwargs)
        from rentals.models import Mietvertrag
        self.beginn_alt = beginn
        self.einheit = einheit
        self.entwurf = entwurf
        for name in FREITEXT:
            self.fields[name] = forms.CharField(
                required=False, max_length=Mietvertrag._meta.get_field(name).max_length)
        if entwurf:
            self.fields['beginn'] = forms.DateField(required=False)
            self.fields['netto_mietzins'] = _betrag('netto_mietzins', required=False, min_value=0)
            self.fields['nebenkosten'] = _betrag('nebenkosten', required=False, min_value=0)
            self.fields['kautions_betrag'] = _betrag('kautions_betrag', required=False, min_value=0)
            self.fields['mwst_satz'] = SchweizerZahl(required=False, max_digits=5, decimal_places=2,
                                                     min_value=0, max_value=100)

    def clean_index_weitergabe_prozent(self):
        # Über 100 % wird auf 100 % GEKÜRZT, nicht abgelehnt — so entschieden
        # in E2.53 und festgehalten in `test_ueber_hundert_prozent_wird_gekappt`
        # (mehr als die Teuerung weiterzugeben, sieht das Gesetz nicht vor).
        # Abgelehnt wird, was vorher still ignoriert wurde: 0 und weniger.
        w = self.cleaned_data.get('index_weitergabe_prozent')
        if w is None:
            return None
        if w <= 0:
            raise forms.ValidationError(_t('Die Weitergabe muss über 0 % liegen.'))
        return min(w, Decimal('100'))

    def clean_mwst_satz(self):
        # Wie beim Kreditor: «8.10» ist 8.1 und kein Fehler; «7.75» lässt sich
        # nicht verlustfrei auf eine Nachkommastelle kürzen.
        satz = self.cleaned_data.get('mwst_satz')
        if satz is None:
            return None
        gekuerzt = satz.quantize(Decimal('0.1'))
        if gekuerzt != satz:
            raise forms.ValidationError(_t('Der MWST-Satz hat höchstens eine Nachkommastelle (z. B. 8.1).'))
        return gekuerzt

    def clean(self):
        daten = super().clean()
        beginn = daten.get('beginn') or self.beginn_alt
        ende = daten.get('ende')
        if beginn and ende and ende < beginn:
            self.add_error('ende', _t('Das Mietende liegt vor dem Mietbeginn.'))
        # Wertebereiche wie im Assistenten (eine Stelle: rentals/validierung.py).
        # Nur beim Entwurf: bei aktiven Verträgen sind diese Felder gesperrt und
        # kommen gar nicht erst aus dem Formular.
        if self.entwurf:
            from rentals.validierung import pruefe_vertragswerte
            einstellplatz = bool(getattr(self.einheit, 'ist_einstellplatz', False))
            for feld, meldung in pruefe_vertragswerte(
                    netto=daten.get('netto_mietzins'), nebenkosten=daten.get('nebenkosten'),
                    kaution=daten.get('kautions_betrag'), beginn=daten.get('beginn'),
                    einheit=self.einheit, einstellplatz=einstellplatz).items():
                if feld != 'ende' and feld not in self.errors:
                    self.add_error(feld, meldung)
        return daten
