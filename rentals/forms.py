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

    MIETZINSMODELL: Wird `vertrag` übergeben, prüft `clean()` die Felder, die das Formular ändert
    (Ende, Beginn, Kündigungsverzicht des Vermieters, Index-Weitergabe und -Intervall), gegen die
    Regeln von Art. 269b/269c OR (`core/services/mietzinsmodell.py`). Sperren landen als Fehler
    am Formular. Ändert die Eingabe keines der Modellfelder des Vertrags, wird ein Altvertrag
    nicht wegen eines früheren Verstosses blockiert.

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
    #: Nur wirksam, wenn das Feld mitgeschickt wird (sonst bleibt der Wert am Vertrag).
    vermieter_kuendigungsverzicht_bis = forms.DateField(required=False)

    def __init__(self, *args, entwurf=False, beginn=None, vertrag=None, **kwargs):
        super().__init__(*args, **kwargs)
        from rentals.models import Mietvertrag
        self.beginn_alt = beginn
        self.vertrag = vertrag
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
        if self.vertrag is not None and not self.errors:
            self._mietzinsmodell_pruefen(daten)
        return daten

    def _mietzinsmodell_pruefen(self, daten):
        """Hält den Vertrag mit den eingegebenen Werten gegen `pruefe` (nur Sperren)."""
        import copy

        from core.services.mietzinsmodell import pruefe_vertrag, sperren
        v = copy.copy(self.vertrag)
        v.ende = daten.get('ende')
        # Wie `fw_vertrag_bearbeiten`: Bei einem aktiven Vertrag folgt die Befristung dem Enddatum;
        # bei gekündigten/archivierten stammt `ende` aus der Kündigung.
        if v.status == 'aktiv':
            v.ist_befristet = bool(v.ende)
        if daten.get('beginn'):
            v.beginn = daten['beginn']
        if 'vermieter_kuendigungsverzicht_bis' in self.data:
            v.vermieter_kuendigungsverzicht_bis = daten.get('vermieter_kuendigungsverzicht_bis')
        if daten.get('index_weitergabe_prozent') is not None:
            v.index_weitergabe_prozent = daten['index_weitergabe_prozent']
        if daten.get('index_intervall_monate') is not None:
            v.index_intervall_monate = daten['index_intervall_monate']
        # Bei festem Mietzins entscheiden die Indexfelder nichts: Sie zu ändern ist keine Änderung am
        # Mietzinsmodell (die Regeln lesen sie dort nicht), und ein Altvertrag mit Staffelresten wird
        # deswegen nicht blockiert.
        felder = [f for f in v.MODELL_FELDER
                  if v.mietzins_modell != 'fest' or f not in ('basis_lik_punkte', 'basis_lik_stand',
                                                               'index_weitergabe_prozent', 'index_intervall_monate')]
        if all(getattr(v, f) == getattr(self.vertrag, f) for f in felder):
            return
        for b in sperren(pruefe_vertrag(v)):
            self.add_error(None, b.volltext)
