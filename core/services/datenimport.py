"""Datenimport für Wechselkunden (Audit FUNK-09): Eigentümer, Liegenschaften, Objekte,
Mieter und laufende Mietverträge aus CSV oder XLSX.

Grundsätze

* **Nichts wird halb importiert.** Alle Dateien eines Laufs werden in EINER Transaktion
  verarbeitet. Meldet auch nur eine Zeile einen Fehler, wird zurückgerollt: Es bleibt kein
  Datensatz zurück. Die Fehlerliste nennt Datei, Zeile (wie in Excel gezählt), Spalte und Grund.
* **Trockenlauf = dieselbe Verarbeitung.** Die Vorschau schreibt die Zeilen wirklich (so greifen
  Feldlängen, Pflichtfelder und die Regeln der Modelle) und rollt am Ende zurück. Es gibt keine
  zweite, vereinfachte Prüfung, die von der Ausführung abweichen könnte.
* **Die Regeln des Bestands, nicht neue.** Das Mietzinsmodell prüft `core/services/mietzinsmodell.py`
  (Art. 269b/269c OR), die Kündigungsfrist `rentals.services.kuendigungsfrist_fehler`
  (Art. 266a–266d OR), die Kaution `faelle.regelwerk.kaution_hoechstbetrag` (Art. 257e OR), den Rest
  `full_clean()` der Modelle. Was ein Wert bedeutet, wird nicht erraten: Fehlt eine Pflichtangabe,
  ist es ein Fehler, kein Vorgabewert.
* **Mandantentrennung.** Der Lauf gehört einer Organisation und läuft in ihrem Kontext
  (`organisation_kontext`). Verknüpfungen zwischen den Dateien werden über `DatenImportReferenz`
  aufgelöst, das ebenfalls durch den `TenantManager` gefiltert ist: Ein Schlüssel einer
  anderen Organisation ist nicht auffindbar.
* **Wiederholbar.** Ein Schlüssel, der schon importiert wurde, wird übersprungen, nicht doppelt
  angelegt. So lassen sich Dateien in Etappen nachliefern.

Nicht Teil davon (Fachpunkte, siehe Bericht): Staffelmiete (die Stufen brauchen eine eigene
Tabelle), Eröffnungssalden und offene Posten, Dokumente, STWEG-Liegenschaften.
"""
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from core.services.datenimport_lesen import DateiFehler, kopf_normieren, lese_tabelle
from core.utils.betrag import betrag_parsen
from core.tenancy import organisation_kontext
from core.zeit import datum_heute

logger = logging.getLogger(__name__)

#: Reihenfolge der Verarbeitung = Reihenfolge der Abhängigkeiten.
ARTEN = ('eigentuemer', 'liegenschaften', 'objekte', 'mieter', 'vertraege')

ART_TITEL = {
    'eigentuemer': gettext_lazy('Eigentümer'),
    'liegenschaften': gettext_lazy('Liegenschaften'),
    'objekte': gettext_lazy('Objekte (Wohnungen, Gewerbe, Parkplätze)'),
    'mieter': gettext_lazy('Mieter'),
    'vertraege': gettext_lazy('Laufende Mietverträge'),
}

#: Obergrenze der gespeicherten Meldungen (die Zähler bleiben exakt).
MAX_MELDUNGEN = 1000

STUFE_FEHLER = 'fehler'
STUFE_HINWEIS = 'hinweis'


def _spalte(name, pflicht=False, beispiel='', text=''):
    return {'name': name, 'pflicht': pflicht, 'beispiel': beispiel, 'text': text}


#: Aufbau der Dateien. Daraus entstehen die Vorlagen und die Beschreibung auf der Seite.
SPALTEN = {
    'eigentuemer': [
        _spalte('schluessel', True, 'E1', gettext_lazy('Ihr eigener Schlüssel; verknüpft die Liegenschaften')),
        _spalte('name', True, 'Muster Immobilien AG', gettext_lazy('Name oder Firma')),
        _spalte('kontaktperson', False, 'Anna Muster'),
        _spalte('strasse', False, 'Bahnhofstrasse 1'),
        _spalte('plz', False, '8000'),
        _spalte('ort', False, 'Zürich'),
        _spalte('telefon', False, '044 000 00 00'),
        _spalte('email', False, 'eigentuemer@example.ch'),
        _spalte('sprache', False, 'de', gettext_lazy('de, fr, it oder en; leer = de')),
        _spalte('bank_name', False, 'ZKB'),
        _spalte('iban', False, 'CH93 0076 2011 6238 5295 7'),
        _spalte('honorar_prozent', False, '4.5', gettext_lazy('Verwaltungshonorar in Prozent, 0 bis 100; leer = 0')),
    ],
    'liegenschaften': [
        _spalte('schluessel', True, 'L1', gettext_lazy('Ihr eigener Schlüssel; verknüpft die Objekte')),
        _spalte('strasse', True, 'Seestrasse 12'),
        _spalte('plz', True, '8002', gettext_lazy('vierstellig')),
        _spalte('ort', True, 'Zürich'),
        _spalte('eigentuemer', False, 'E1', gettext_lazy('Schlüssel aus der Eigentümerdatei')),
        _spalte('kanton', False, 'ZH', gettext_lazy('Kürzel; bestimmt Formulare und Fristen. Leer = später eintragen')),
        _spalte('baujahr', False, '1975'),
        _spalte('egid', False, '1234567'),
        _spalte('bank_name', False, 'ZKB'),
        _spalte('iban', False, 'CH93 0076 2011 6238 5295 7'),
        _spalte('typ', False, 'MIETE', gettext_lazy('nur Mietliegenschaften; Stockwerkeigentum bitte in der Oberfläche anlegen')),
    ],
    'objekte': [
        _spalte('schluessel', True, 'L1-01', gettext_lazy('Ihr eigener Schlüssel; verknüpft die Verträge')),
        _spalte('liegenschaft', True, 'L1', gettext_lazy('Schlüssel aus der Liegenschaftsdatei')),
        _spalte('bezeichnung', True, '3.5 Zi, 2. OG links'),
        _spalte('typ', True, 'whg', gettext_lazy('whg (Wohnung), gew (Gewerbe), pp (Parkplatz), gar (Garage), bas (Bastelraum)')),
        _spalte('etage', False, '2. OG'),
        _spalte('zimmer', False, '3.5'),
        _spalte('flaeche_m2', False, '82.5'),
        _spalte('volumen_m3', False, '210'),
        _spalte('ewid', False, '1'),
        _spalte('nettomiete', False, '1850', gettext_lazy('Soll-Nettomiete des Objekts (Referenz, ersetzt keinen Vertrag)')),
        _spalte('nebenkosten', False, '220', gettext_lazy('Soll-Nebenkosten des Objekts')),
        _spalte('miete_gueltig_ab', False, '2024-01-01', gettext_lazy('Leer = heute')),
        _spalte('notizen', False),
    ],
    'mieter': [
        _spalte('schluessel', True, 'M1', gettext_lazy('Ihr eigener Schlüssel; verknüpft die Verträge')),
        _spalte('typ', False, 'person', gettext_lazy('person, firma oder verein; leer = person')),
        _spalte('anrede', False, 'Frau'),
        _spalte('vorname', False, 'Beat'),
        _spalte('nachname', False, 'Muster', gettext_lazy('Pflicht bei Privatpersonen')),
        _spalte('firmenname', False, 'Muster AG', gettext_lazy('Pflicht bei Firma und Verein')),
        _spalte('kontaktperson', False),
        _spalte('geburtsdatum', False, '1980-05-17'),
        _spalte('email', False, 'beat.muster@example.ch'),
        _spalte('telefon', False, '044 000 00 00'),
        _spalte('mobile', False, '079 000 00 00'),
        _spalte('strasse', False, 'Seestrasse 12'),
        _spalte('plz', False, '8002'),
        _spalte('ort', False, 'Zürich'),
        _spalte('land', False, 'Schweiz', gettext_lazy('Leer = Schweiz')),
        _spalte('sprache', False, 'de', gettext_lazy('de, fr, it oder en; leer = de')),
        _spalte('iban', False, 'CH93 0076 2011 6238 5295 7'),
    ],
    'vertraege': [
        _spalte('schluessel', True, 'V1', gettext_lazy('Ihr eigener Schlüssel')),
        _spalte('objekt', True, 'L1-01', gettext_lazy('Schlüssel aus der Objektdatei')),
        _spalte('mieter', True, 'M1', gettext_lazy('Schlüssel aus der Mieterdatei')),
        _spalte('mitmieter', False, 'M2', gettext_lazy('Zweite Vertragspartei (Ehegatte, Mitmieter)')),
        _spalte('status', False, 'aktiv', gettext_lazy('aktiv oder gekuendigt; leer = aktiv')),
        _spalte('beginn', True, '2019-04-01'),
        _spalte('ende', False, '', gettext_lazy('Ende der Befristung oder Kündigungstermin')),
        _spalte('befristet', False, 'nein', gettext_lazy('ja oder nein; Pflicht, wenn ein Ende steht')),
        _spalte('netto_mietzins', True, '1850.00', gettext_lazy('Franken pro Monat')),
        _spalte('nebenkosten', True, '220.00', gettext_lazy('Franken pro Monat; 0, wenn keine')),
        _spalte('nk_abrechnungsart', False, 'akonto', gettext_lazy('akonto, pauschal, inbegriffen oder direkt; leer = akonto')),
        _spalte('zahlungsrhythmus', False, 'monatlich', gettext_lazy('monatlich, vierteljahr, halbjahr oder jahr')),
        _spalte('kaution', False, '5550.00'),
        _spalte('kautionsart', False, 'sperrkonto', gettext_lazy('sperrkonto oder versicherung; Pflicht, wenn eine Kaution steht')),
        _spalte('kautionskonto', False, 'CH93 0076 2011 6238 5295 7', gettext_lazy('IBAN des Sperrkontos')),
        _spalte('kaution_einbezahlt_am', False, '2019-03-20'),
        _spalte('kuendigungsfrist_monate', False, '3', gettext_lazy('Leer = 3 (Wohnen) bzw. 6 (Geschäftsraum)')),
        _spalte('kuendigungstermine', False, 'Ende jedes Monats ausser Dezember'),
        _spalte('erstmals_kuendbar_auf', False, ''),
        _spalte('mietzinsmodell', False, 'fest', gettext_lazy('fest oder index; leer = fest. Staffelmiete: nicht per Import')),
        _spalte('basis_referenzzinssatz', False, '1.25', gettext_lazy('Referenzzinssatz zum Vertragsabschluss; leer = heutiger Stand')),
        _spalte('basis_lik_punkte', False, '100.0', gettext_lazy('LIK-Basis; bei Indexmiete Pflicht')),
        _spalte('basis_lik_stand', False, '2019-03', gettext_lazy('Monat der LIK-Basis; bei Indexmiete Pflicht')),
        _spalte('index_weitergabe_prozent', False, '100', gettext_lazy('Nur Indexmiete; leer = 100')),
        _spalte('index_intervall_monate', False, '12', gettext_lazy('Nur Indexmiete; leer = 12')),
        _spalte('familienwohnung', False, 'nein'),
        _spalte('anzahl_personen', False, '2'),
        _spalte('mwst_pflichtig', False, 'nein', gettext_lazy('Option nach Art. 22 MWSTG, nur Geschäftsräume')),
        _spalte('mwst_satz', False, '8.1', gettext_lazy('Pflicht, wenn mwst_pflichtig = ja')),
    ],
}


def vorlage_csv(art):
    """Die Kopfzeile der Vorlage (Semikolon, UTF-8 mit BOM für Excel). Bewusst ohne Beispielzeile."""
    if art not in SPALTEN:
        raise KeyError(art)
    return '﻿' + ';'.join(s['name'] for s in SPALTEN[art]) + '\r\n'


# ── Ergebnis ──────────────────────────────────────────────────────────────────
@dataclass
class Ergebnis:
    zaehler: dict = field(default_factory=dict)
    meldungen: list = field(default_factory=list)
    anzahl_fehler: int = 0
    anzahl_hinweise: int = 0

    @property
    def ok(self):
        return self.anzahl_fehler == 0


class _Zurueck(Exception):
    """Innen: die Transaktion zurückrollen (Fehler gefunden oder Trockenlauf)."""


class _Kontext:
    """Zustand eines Laufs: Meldungen, Zähler, Zwischenspeicher für Verknüpfungen."""

    def __init__(self, organisation):
        self.organisation = organisation
        self.ergebnis = Ergebnis()
        self.cache = {}
        self.sammler = {}

    def melde(self, art, zeile, feld, stufe, text):
        e = self.ergebnis
        if stufe == STUFE_FEHLER:
            e.anzahl_fehler += 1
        else:
            e.anzahl_hinweise += 1
        if len(e.meldungen) < MAX_MELDUNGEN:
            e.meldungen.append({'art': art, 'zeile': zeile, 'feld': feld, 'stufe': stufe, 'text': str(text)})

    def zaehle(self, art, was, n=1):
        z = self.ergebnis.zaehler.setdefault(art, {'zeilen': 0, 'neu': 0, 'vorhanden': 0, 'fehler': 0})
        z[was] += n

    def sammle(self, art, schluessel, vorlage_text):
        """Ein Hinweis für viele Zeilen: «%(n)s Verträge …», am Ende einmal gemeldet."""
        eintrag = self.sammler.setdefault((art, schluessel), [vorlage_text, 0])
        eintrag[1] += 1

    def sammler_melden(self):
        for (art, _schluessel), (text, n) in self.sammler.items():
            self.melde(art, None, '', STUFE_HINWEIS, text % {'n': n})


# ── Zeilen lesen und prüfen ───────────────────────────────────────────────────
_DATUM_CH = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$')
_DATUM_ISO = re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$')
_MONAT_ISO = re.compile(r'^(\d{4})-(\d{1,2})$')
_MONAT_CH = re.compile(r'^(\d{1,2})\.(\d{4})$')
_JA = {'ja', 'j', 'yes', 'y', 'true', '1', 'x', 'oui', 'si', 'sì', 'wahr'}
_NEIN = {'nein', 'n', 'no', 'false', '0', 'non', 'falsch'}


def datum_parsen(t):
    """TT.MM.JJJJ oder JJJJ-MM-TT -> date. `ValueError` mit einem Satz für den Menschen."""
    t = (t or '').strip()
    try:
        m = _DATUM_ISO.match(t)
        if m:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        else:
            m = _DATUM_CH.match(t)
            if not m:
                raise ValueError
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        raise ValueError(_('«%(wert)s» ist kein Datum (erwartet: TT.MM.JJJJ oder JJJJ-MM-TT).') % {'wert': t})
    if not 1900 <= d.year <= 2100:
        raise ValueError(_('Das Jahr %(j)s ist nicht plausibel.') % {'j': d.year})
    return d


class _Zeile:
    """Eine Zeile mit den Lesefunktionen. Jeder Fehler wird gemeldet UND merkt sich die Zeile."""

    def __init__(self, ctx, art, nr, daten):
        self.ctx, self.art, self.nr, self.d = ctx, art, nr, daten
        self.fehler_n = 0
        self._gemeldet = set()

    @property
    def ok(self):
        return self.fehler_n == 0

    def fehler(self, feld, text):
        if (feld, str(text)) in self._gemeldet:
            return
        self._gemeldet.add((feld, str(text)))
        self.fehler_n += 1
        self.ctx.melde(self.art, self.nr, feld, STUFE_FEHLER, text)

    def hinweis(self, feld, text):
        self.ctx.melde(self.art, self.nr, feld, STUFE_HINWEIS, text)

    def roh(self, feld):
        return (self.d.get(feld) or '').strip()

    def text(self, feld, pflicht=False, laenge=None):
        t = re.sub(r'\s+', ' ', self.roh(feld)) if feld not in ('notizen', 'besondere_vereinbarungen') else self.roh(feld)
        if not t:
            if pflicht:
                self.fehler(feld, _('Pflichtangabe fehlt.'))
            return ''
        if laenge and len(t) > laenge:
            self.fehler(feld, _('Zu lang: höchstens %(n)s Zeichen, hier %(m)s.') % {'n': laenge, 'm': len(t)})
        return t

    def zahl(self, feld, pflicht=False, minimum=None, maximum=None, stellen=2, ziffern=8):
        t = self.roh(feld)
        if not t:
            if pflicht:
                self.fehler(feld, _('Pflichtangabe fehlt.'))
            return None
        try:
            d = betrag_parsen(t)
        except ValueError:
            self.fehler(feld, _('«%(wert)s» ist keine Zahl.') % {'wert': self.roh(feld)})
            return None
        if not d.is_finite():
            self.fehler(feld, _('«%(wert)s» ist keine Zahl.') % {'wert': self.roh(feld)})
            return None
        norm = d.normalize()
        if -norm.as_tuple().exponent > stellen:
            self.fehler(feld, _('Höchstens %(n)s Nachkommastellen; es wird nicht gerundet.') % {'n': stellen})
            return None
        d = d.quantize(Decimal(1).scaleb(-stellen))
        if len(d.as_tuple().digits) > ziffern:
            self.fehler(feld, _('Der Wert ist zu gross.'))
            return None
        if minimum is not None and d < minimum:
            self.fehler(feld, _('Der Wert darf nicht unter %(n)s liegen.') % {'n': minimum})
            return None
        if maximum is not None and d > maximum:
            self.fehler(feld, _('Der Wert darf nicht über %(n)s liegen.') % {'n': maximum})
            return None
        return d

    def ganzzahl(self, feld, pflicht=False, minimum=None, maximum=None):
        d = self.zahl(feld, pflicht, minimum, maximum, stellen=0, ziffern=9)
        return None if d is None else int(d)

    def datum(self, feld, pflicht=False):
        t = self.roh(feld)
        if not t:
            if pflicht:
                self.fehler(feld, _('Pflichtangabe fehlt.'))
            return None
        try:
            return datum_parsen(t)
        except ValueError as e:
            self.fehler(feld, str(e))
            return None

    def monat(self, feld, pflicht=False):
        """Monat als Datum (1. des Monats): JJJJ-MM, MM.JJJJ oder ein volles Datum."""
        t = self.roh(feld)
        if not t:
            if pflicht:
                self.fehler(feld, _('Pflichtangabe fehlt.'))
            return None
        try:
            m = _MONAT_ISO.match(t)
            if m:
                return date(int(m.group(1)), int(m.group(2)), 1)
            m = _MONAT_CH.match(t)
            if m:
                return date(int(m.group(2)), int(m.group(1)), 1)
        except ValueError:
            self.fehler(feld, _('«%(wert)s» ist kein Monat (erwartet: JJJJ-MM).') % {'wert': t})
            return None
        d = self.datum(feld)
        return d.replace(day=1) if d else None

    def ja_nein(self, feld, standard=None):
        t = self.roh(feld).lower()
        if not t:
            return standard
        if t in _JA:
            return True
        if t in _NEIN:
            return False
        self.fehler(feld, _('«%(wert)s» ist weder ja noch nein.') % {'wert': self.roh(feld)})
        return standard

    def wahl(self, feld, zulaessig, standard=None, pflicht=False):
        """`zulaessig`: {gelesener Wert (klein): Schlüssel}. Unbekannte Werte sind ein Fehler."""
        t = self.roh(feld).lower()
        if not t:
            if pflicht:
                self.fehler(feld, _('Pflichtangabe fehlt.'))
            return standard
        schluessel = zulaessig.get(t) or zulaessig.get(kopf_normieren(t))
        if schluessel is None:
            erlaubt = ', '.join(sorted(set(zulaessig.values())))
            self.fehler(feld, _('«%(wert)s» ist nicht zulässig. Erlaubt: %(erlaubt)s.')
                        % {'wert': self.roh(feld), 'erlaubt': erlaubt})
            return standard
        return schluessel

    def iban(self, feld):
        from core.services.iban import ist_gueltige_iban, normalisiere_iban
        t = self.roh(feld)
        if not t:
            return ''
        if not ist_gueltige_iban(t):
            self.fehler(feld, _('«%(wert)s» ist keine gültige IBAN.') % {'wert': t})
            return ''
        return normalisiere_iban(t)

    def email(self, feld):
        from django.core.validators import validate_email
        t = self.roh(feld)
        if not t:
            return ''
        try:
            validate_email(t)
        except ValidationError:
            self.fehler(feld, _('«%(wert)s» ist keine gültige E-Mail-Adresse.') % {'wert': t})
            return ''
        return t

    def modell_fehler(self, fehler, spalten=None):
        """Fehler aus `full_clean()` auf die Spalten abbilden (`spalten`: Modellfeld -> Spalte)."""
        spalten = spalten or {}
        if hasattr(fehler, 'error_dict'):
            for modellfeld, liste in fehler.message_dict.items():
                for text in liste:
                    self.fehler(spalten.get(modellfeld, '' if modellfeld == '__all__' else modellfeld), text)
        else:
            for text in fehler.messages:
                self.fehler('', text)


def _sprache(z):
    return z.wahl('sprache', {'de': 'de', 'deutsch': 'de', 'fr': 'fr', 'franzoesisch': 'fr', 'it': 'it',
                              'italienisch': 'it', 'en': 'en', 'englisch': 'en'}, standard='de')


# ── Verknüpfungen ─────────────────────────────────────────────────────────────
def _referenz_setzen(ctx, art, schluessel, objekt, lauf):
    from core.models import DatenImportReferenz
    DatenImportReferenz.objects.update_or_create(
        art=art, schluessel=schluessel, defaults={'objekt_id': objekt.pk, 'lauf': lauf})
    ctx.cache[(art, schluessel)] = objekt


def _referenz_holen(ctx, art, schluessel, modell):
    """Der Datensatz zum Schlüssel oder None. Ein Schlüssel, dessen Datensatz inzwischen gelöscht
    wurde, gilt als unbekannt (die veraltete Referenz wird überschrieben, sobald neu angelegt wird)."""
    from core.models import DatenImportReferenz
    if (art, schluessel) in ctx.cache:
        return ctx.cache[(art, schluessel)]
    ref = DatenImportReferenz.objects.filter(art=art, schluessel=schluessel).first()
    objekt = modell.objects.filter(pk=ref.objekt_id).first() if ref else None
    ctx.cache[(art, schluessel)] = objekt
    return objekt


def _verweis(ctx, z, feld, art, modell, pflicht=True, titel=''):
    """Löst eine Spalte, die auf den Schlüssel einer anderen Datei zeigt, in den Datensatz auf."""
    schluessel = z.text(feld, pflicht=pflicht, laenge=120)
    if not schluessel:
        return None
    objekt = _referenz_holen(ctx, art, schluessel, modell)
    if objekt is None:
        z.fehler(feld, _('Der Schlüssel «%(s)s» ist nicht bekannt. Er muss in der Datei «%(datei)s» stehen '
                         '(im selben oder in einem früheren Import).') % {'s': schluessel, 'datei': titel or ART_TITEL[art]})
    return objekt


class _Doppelt:
    """Schlüssel, die in einer Datei mehrfach vorkommen."""

    def __init__(self):
        self.gesehen = {}

    def pruefe(self, z, schluessel):
        if not schluessel:
            return False
        if schluessel in self.gesehen:
            z.fehler('schluessel', _('Der Schlüssel «%(s)s» steht schon in Zeile %(n)s.')
                     % {'s': schluessel, 'n': self.gesehen[schluessel]})
            return True
        self.gesehen[schluessel] = z.nr
        return False


# ── Die fünf Arten ────────────────────────────────────────────────────────────
def _eigentuemer(ctx, z, lauf):
    from crm.models import Eigentuemer
    schluessel = z.text('schluessel', pflicht=True, laenge=120)
    name = z.text('name', pflicht=True, laenge=100)
    if not schluessel or not z.ok:
        return None
    if _referenz_holen(ctx, 'eigentuemer', schluessel, Eigentuemer):
        return 'vorhanden'
    vorhanden = Eigentuemer.objects.filter(firma_oder_name__iexact=name).first()
    if vorhanden:
        _referenz_setzen(ctx, 'eigentuemer', schluessel, vorhanden, lauf)
        z.hinweis('name', _('Eigentümer «%(n)s» besteht schon und wurde zugeordnet; nichts verändert.') % {'n': name})
        return 'vorhanden'
    honorar = z.zahl('honorar_prozent', minimum=Decimal('0'), maximum=Decimal('100'), ziffern=5)
    obj = Eigentuemer(
        firma_oder_name=name, kontaktperson=z.text('kontaktperson', laenge=100), strasse=z.text('strasse', laenge=100),
        plz=z.text('plz', laenge=10), ort=z.text('ort', laenge=100), telefon=z.text('telefon', laenge=30),
        email=z.email('email'), sprache=_sprache(z), bank_name=z.text('bank_name', laenge=100),
        iban=z.iban('iban'), honorar_prozent=honorar if honorar is not None else Decimal('0.00'))
    if not z.ok:
        return None
    try:
        obj.full_clean(exclude=['organisation', 'benutzer'])
    except ValidationError as e:
        z.modell_fehler(e, {'firma_oder_name': 'name'})
        return None
    obj.save()
    _referenz_setzen(ctx, 'eigentuemer', schluessel, obj, lauf)
    return 'neu'


def _liegenschaft(ctx, z, lauf):
    from crm.models import Eigentuemer
    from core.services.kantone import KANTON_NAMEN, plz_to_kanton
    from portfolio.models import Liegenschaft
    schluessel = z.text('schluessel', pflicht=True, laenge=120)
    strasse = z.text('strasse', pflicht=True, laenge=200)
    plz = z.text('plz', pflicht=True, laenge=10)
    ort = z.text('ort', pflicht=True, laenge=100)
    if plz and not re.fullmatch(r'\d{4}', plz):
        z.fehler('plz', _('Die Postleitzahl einer Liegenschaft hat vier Ziffern.'))
    typ = z.wahl('typ', {'miete': 'MIETE', 'mietliegenschaft': 'MIETE', 'stweg': 'STWEG'}, standard='MIETE')
    if typ == 'STWEG':
        z.fehler('typ', _('Stockwerkeigentum (STWEG) wird nicht importiert: Die Wertquoten müssen aufgehen. '
                          'Bitte in der Oberfläche anlegen.'))
    eigentuemer = None
    if z.roh('eigentuemer'):
        eigentuemer = _verweis(ctx, z, 'eigentuemer', 'eigentuemer', Eigentuemer, pflicht=False)
    kanton = z.roh('kanton').upper()
    if kanton and kanton not in KANTON_NAMEN:
        z.fehler('kanton', _('«%(k)s» ist kein Kantonskürzel.') % {'k': z.roh('kanton')})
    baujahr = z.ganzzahl('baujahr', minimum=1000, maximum=date.today().year + 5)
    if not schluessel or not z.ok:
        return None
    if _referenz_holen(ctx, 'liegenschaften', schluessel, Liegenschaft):
        return 'vorhanden'
    vorhanden = Liegenschaft.objects.filter(strasse__iexact=strasse, plz=plz, ort__iexact=ort).first()
    if vorhanden:
        _referenz_setzen(ctx, 'liegenschaften', schluessel, vorhanden, lauf)
        z.hinweis('strasse', _('Die Liegenschaft «%(a)s» besteht schon und wurde zugeordnet; nichts verändert.')
                  % {'a': f'{strasse}, {plz} {ort}'})
        return 'vorhanden'
    if not kanton:
        moeglich = plz_to_kanton(plz)
        z.hinweis('kanton', _('Kein Kanton angegeben%(vorschlag)s: Formulare und Fristen je Kanton bleiben unvollständig, '
                              'bis er eingetragen ist.') % {'vorschlag': f' ({moeglich}?)' if moeglich else ''})
    obj = Liegenschaft(
        eigentuemer=eigentuemer, typ='MIETE', status=Liegenschaft.STATUS_AKTIV, strasse=strasse, plz=plz, ort=ort,
        kanton=kanton, baujahr=baujahr, egid=z.text('egid', laenge=20) or None,
        bank_name=z.text('bank_name', laenge=100), iban=z.iban('iban'))
    if not z.ok:
        return None
    try:
        obj.full_clean(exclude=['organisation', 'betreut_von'])
    except ValidationError as e:
        z.modell_fehler(e)
        return None
    obj.save()
    _referenz_setzen(ctx, 'liegenschaften', schluessel, obj, lauf)
    return 'neu'


_OBJEKT_TYPEN = {
    'whg': 'whg', 'wohnung': 'whg', 'gew': 'gew', 'gewerbe': 'gew', 'geschaeft': 'gew', 'stwe': 'stwe',
    'pp': 'pp', 'parkplatz': 'pp', 'gar': 'gar', 'garage': 'gar', 'bas': 'bas', 'bastelraum': 'bas',
}


def _objekt(ctx, z, lauf):
    from portfolio.models import Einheit, Liegenschaft, Sollmietzins
    schluessel = z.text('schluessel', pflicht=True, laenge=120)
    lg = _verweis(ctx, z, 'liegenschaft', 'liegenschaften', Liegenschaft, titel=_('Liegenschaften'))
    bezeichnung = z.text('bezeichnung', pflicht=True, laenge=50)
    typ = z.wahl('typ', _OBJEKT_TYPEN, pflicht=True)
    if typ == 'stwe':
        z.fehler('typ', _('STWEG-Einheiten werden nicht importiert (Wertquoten, Stockwerkeigentümer).'))
    zimmer = z.zahl('zimmer', minimum=Decimal('0'), maximum=Decimal('99.9'), stellen=1, ziffern=3)
    flaeche = z.zahl('flaeche_m2', minimum=Decimal('0'), ziffern=7)
    volumen = z.zahl('volumen_m3', minimum=Decimal('0'), ziffern=7)
    netto = z.zahl('nettomiete', minimum=Decimal('0'), ziffern=8)
    nk = z.zahl('nebenkosten', minimum=Decimal('0'), ziffern=6)
    gueltig_ab = z.datum('miete_gueltig_ab')
    if not schluessel or not z.ok:
        return None
    if _referenz_holen(ctx, 'objekte', schluessel, Einheit):
        return 'vorhanden'
    vorhanden = Einheit.objects.filter(liegenschaft=lg, bezeichnung__iexact=bezeichnung).first()
    if vorhanden:
        _referenz_setzen(ctx, 'objekte', schluessel, vorhanden, lauf)
        z.hinweis('bezeichnung', _('Das Objekt «%(b)s» besteht in dieser Liegenschaft schon und wurde zugeordnet; '
                                   'nichts verändert.') % {'b': bezeichnung})
        return 'vorhanden'
    obj = Einheit(liegenschaft=lg, bezeichnung=bezeichnung, typ=typ, etage=z.text('etage', laenge=50),
                  zimmer=zimmer, flaeche_m2=flaeche, volumen_m3=volumen,
                  ewid=z.text('ewid', laenge=20) or None, notizen=z.text('notizen'))
    if not z.ok:
        return None
    try:
        obj.full_clean(exclude=['organisation', 'stockwerkeigentuemer', 'gehoert_zu', 'wertquote', 'nettomiete_aktuell',
                                'nebenkosten_aktuell', 'ref_zinssatz', 'lik_punkte'])
    except ValidationError as e:
        z.modell_fehler(e)
        return None
    obj.save()
    # Wie die Oberfläche bei der Neuanlage: Die Soll-Miete des Objekts steht in der datierten
    # Sollmietzins-Historie (einzige Quelle), nicht direkt am Objekt.
    nk_wert = Decimal('0.00') if obj.ist_einstellplatz else (nk or Decimal('0.00'))
    if (netto or 0) > 0 or nk_wert > 0:
        Sollmietzins.objects.create(einheit=obj, gueltig_ab=gueltig_ab or datum_heute(),
                                    netto_mietzins=netto or Decimal('0.00'), nebenkosten=nk_wert,
                                    notiz='Datenimport')
    _referenz_setzen(ctx, 'objekte', schluessel, obj, lauf)
    return 'neu'


def _mieter(ctx, z, lauf):
    from crm.models import Mieter
    schluessel = z.text('schluessel', pflicht=True, laenge=120)
    typ = z.wahl('typ', {'person': 'person', 'privatperson': 'person', 'firma': 'firma', 'unternehmen': 'firma',
                         'verein': 'verein', 'stiftung': 'verein'}, standard='person')
    vorname = z.text('vorname', laenge=100)
    nachname = z.text('nachname', laenge=100)
    firma = z.text('firmenname', laenge=200)
    if typ == 'person' and not nachname:
        z.fehler('nachname', _('Bei einer Privatperson ist der Nachname Pflicht.'))
    if typ in ('firma', 'verein') and not firma:
        z.fehler('firmenname', _('Bei Firma und Verein ist der Firmenname Pflicht.'))
    email = z.email('email')
    geburtsdatum = z.datum('geburtsdatum')
    if geburtsdatum and geburtsdatum > datum_heute():
        z.fehler('geburtsdatum', _('Das Geburtsdatum liegt in der Zukunft.'))
    sprache = _sprache(z)
    iban = z.iban('iban')
    if not schluessel or not z.ok:
        return None
    if _referenz_holen(ctx, 'mieter', schluessel, Mieter):
        return 'vorhanden'
    if email and Mieter.objects.filter(email__iexact=email).exists():
        z.hinweis('email', _('Ein Mieter mit der E-Mail-Adresse «%(e)s» besteht schon. Dieser Eintrag wird trotzdem '
                             'neu angelegt; Doppelte später zusammenführen.') % {'e': email})
    obj = Mieter(
        typ=typ, anrede=z.text('anrede', laenge=20), vorname=vorname, nachname=nachname, firmen_name=firma,
        kontaktperson=z.text('kontaktperson', laenge=100), geburtsdatum=geburtsdatum, email=email,
        telefon_privat=z.text('telefon', laenge=50), mobile=z.text('mobile', laenge=50),
        strasse=z.text('strasse', laenge=200), plz=z.text('plz', laenge=10), ort=z.text('ort', laenge=100),
        land=z.text('land', laenge=50) or 'Schweiz', sprache=sprache, iban=iban)
    if not z.ok:
        return None
    try:
        obj.full_clean(exclude=['organisation', 'benutzer', 'ahv_nummer'])
    except ValidationError as e:
        z.modell_fehler(e, {'firmen_name': 'firmenname', 'telefon_privat': 'telefon'})
        return None
    obj.save()
    _referenz_setzen(ctx, 'mieter', schluessel, obj, lauf)
    return 'neu'


_FELD_ZU_SPALTE = {
    'netto_mietzins': 'netto_mietzins', 'nebenkosten': 'nebenkosten', 'kautions_betrag': 'kaution',
    'kautions_art': 'kautionsart', 'kautions_konto': 'kautionskonto', 'mietzins_modell': 'mietzinsmodell',
    'ist_befristet': 'befristet', 'vermieter_kuendigungsverzicht_bis': 'mietzinsmodell',
    'index_weitergabe_prozent': 'index_weitergabe_prozent', 'index_intervall_monate': 'index_intervall_monate',
    'basis_lik_punkte': 'basis_lik_punkte', 'basis_lik_stand': 'basis_lik_stand',
    'basis_referenzzinssatz': 'basis_referenzzinssatz', 'kuendigungsfrist_monate': 'kuendigungsfrist_monate',
    'kuendigungstermine': 'kuendigungstermine', 'erstmals_kuendbar_auf': 'erstmals_kuendbar_auf',
    'beginn': 'beginn', 'ende': 'ende', 'status': 'status', 'einheit': 'objekt', 'mieter': 'mieter',
    'mitmieter': 'mitmieter', 'anzahl_personen': 'anzahl_personen', 'mwst_satz': 'mwst_satz',
    'mwst_pflichtig': 'mwst_pflichtig', 'zahlungsrhythmus': 'zahlungsrhythmus',
    'nk_abrechnungsart': 'nk_abrechnungsart', 'kautions_einbezahlt_am': 'kaution_einbezahlt_am',
}


def _vertrag(ctx, z, lauf):
    from crm.models import Mieter
    from faelle.regelwerk import kaution_hoechstbetrag
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    from rentals.services import kuendigungsfrist_fehler
    from core.services import mietzinsmodell

    schluessel = z.text('schluessel', pflicht=True, laenge=120)
    einheit = _verweis(ctx, z, 'objekt', 'objekte', Einheit, titel=_('Objekte'))
    mieter = _verweis(ctx, z, 'mieter', 'mieter', Mieter, titel=_('Mieter'))
    mitmieter = _verweis(ctx, z, 'mitmieter', 'mieter', Mieter, pflicht=False, titel=_('Mieter')) if z.roh('mitmieter') else None
    if mitmieter and mieter and mitmieter.pk == mieter.pk:
        z.fehler('mitmieter', _('Hauptmieter und Mitmieter sind dieselbe Person.'))

    status = z.wahl('status', {'aktiv': 'aktiv', 'laufend': 'aktiv', 'gekuendigt': 'gekuendigt'}, standard='aktiv')
    beginn = z.datum('beginn', pflicht=True)
    ende = z.datum('ende')
    befristet = z.ja_nein('befristet')
    heute = datum_heute()
    if beginn and ende and ende < beginn:
        z.fehler('ende', _('Das Ende liegt vor dem Beginn.'))
    if ende and befristet is None:
        z.fehler('befristet', _('Bei einem Enddatum angeben, ob der Vertrag befristet ist (ja) '
                                'oder auf diesen Termin gekündigt wurde (nein).'))
    if befristet and not ende:
        z.fehler('ende', _('Ein befristeter Vertrag braucht ein Enddatum.'))
    if status == 'gekuendigt' and not ende:
        z.fehler('ende', _('Ein gekündigter Vertrag braucht den Kündigungstermin als Enddatum.'))
    if status == 'gekuendigt' and befristet:
        z.fehler('befristet', _('Ein befristeter Vertrag wird nicht gekündigt; Status «aktiv» verwenden.'))
    if beginn and beginn > heute and status == 'aktiv':
        z.hinweis('beginn', _('Der Vertrag beginnt erst am %(d)s, ist aber als aktiv eingetragen.')
                  % {'d': beginn.strftime('%d.%m.%Y')})
    if ende and ende < heute and status == 'aktiv':
        z.hinweis('ende', _('Das Ende (%(d)s) liegt in der Vergangenheit, der Vertrag ist aber als aktiv eingetragen.')
                  % {'d': ende.strftime('%d.%m.%Y')})

    netto = z.zahl('netto_mietzins', pflicht=True, minimum=Decimal('0'), ziffern=8)
    nk = z.zahl('nebenkosten', pflicht=True, minimum=Decimal('0'), ziffern=6)
    nk_art = z.wahl('nk_abrechnungsart', {'akonto': 'akonto', 'pauschal': 'pauschal', 'inbegriffen': 'inbegriffen',
                                          'direkt': 'direkt'}, standard='akonto')
    rhythmus = z.wahl('zahlungsrhythmus', {'monatlich': 'monatlich', 'vierteljahr': 'vierteljahr',
                                           'vierteljaehrlich': 'vierteljahr', 'halbjahr': 'halbjahr',
                                           'halbjaehrlich': 'halbjahr', 'jahr': 'jahr', 'jaehrlich': 'jahr'},
                      standard='monatlich')

    kaution = z.zahl('kaution', minimum=Decimal('0'), ziffern=8)
    kautionsart = z.wahl('kautionsart', {'sperrkonto': 'sperrkonto', 'versicherung': 'versicherung',
                                         'kautionsversicherung': 'versicherung'}, standard='')
    if kaution and not kautionsart:
        z.fehler('kautionsart', _('Bei einer Kaution angeben, ob Sperrkonto oder Versicherung.'))
    kautionskonto = z.iban('kautionskonto')
    einbezahlt = z.datum('kaution_einbezahlt_am')

    modell = z.wahl('mietzinsmodell', {'fest': 'fest', 'index': 'index', 'indexmiete': 'index', 'staffel': 'staffel',
                                       'staffelmiete': 'staffel'}, standard='fest')
    if modell == 'staffel':
        z.fehler('mietzinsmodell', _('Staffelmieten werden nicht importiert: Die Stufen brauchen eine eigene Tabelle '
                                     '(Art. 269c OR). Den Vertrag in der Oberfläche erfassen.'))
    basis_zins = z.zahl('basis_referenzzinssatz', minimum=Decimal('0'), maximum=Decimal('20'), ziffern=4)
    basis_lik = z.zahl('basis_lik_punkte', minimum=Decimal('0'), stellen=1, ziffern=6)
    basis_stand = z.monat('basis_lik_stand')
    if modell == 'index' and basis_lik is None:
        z.fehler('basis_lik_punkte', _('Bei Indexmiete ist die Basis des Landesindexes (Punkte) Pflicht; sie wird nicht vorgegeben.'))
    if modell == 'index' and basis_stand is None and not z.roh('basis_lik_stand'):
        z.fehler('basis_lik_stand', _('Bei Indexmiete ist der Stand-Monat der Index-Basis Pflicht.'))
    weitergabe = z.zahl('index_weitergabe_prozent', stellen=1, ziffern=5)
    intervall = z.ganzzahl('index_intervall_monate')

    fam = z.ja_nein('familienwohnung', standard=False)
    personen = z.ganzzahl('anzahl_personen', minimum=1, maximum=50)
    mwst = z.ja_nein('mwst_pflichtig', standard=False)
    mwst_satz = z.zahl('mwst_satz', minimum=Decimal('0'), maximum=Decimal('100'), stellen=1, ziffern=4)
    if mwst and mwst_satz is None:
        z.fehler('mwst_satz', _('Bei MWST-Pflicht den Steuersatz angeben; er wird nicht vorgegeben.'))
    if not mwst and mwst_satz:
        z.hinweis('mwst_satz', _('Der MWST-Satz wird ignoriert, weil mwst_pflichtig nicht «ja» ist.'))

    if einheit is not None:
        if mwst and einheit.mietrecht_kategorie == 'wohnen':
            z.fehler('mwst_pflichtig', _('Für Wohnräume gibt es keine MWST-Option (Art. 22 Abs. 2 lit. b MWSTG).'))
        standard_frist = 6 if einheit.mietrecht_kategorie == 'gewerbe' else 3
    else:
        standard_frist = 3
    frist = z.ganzzahl('kuendigungsfrist_monate', minimum=0, maximum=60)
    if frist is None:
        frist = standard_frist
    elif einheit is not None:
        meldung = kuendigungsfrist_fehler(frist, einheit)
        if meldung:
            z.fehler('kuendigungsfrist_monate', meldung)
    termine = z.text('kuendigungstermine', laenge=100)
    erstmals = z.datum('erstmals_kuendbar_auf')
    if beginn and erstmals and erstmals < beginn:
        z.fehler('erstmals_kuendbar_auf', _('«Erstmals kündbar auf» liegt vor dem Beginn.'))

    if not schluessel or not z.ok:
        return None
    if _referenz_holen(ctx, 'vertraege', schluessel, Mietvertrag):
        return 'vorhanden'

    if einheit.ist_einstellplatz and (nk or 0) > 0:
        z.hinweis('nebenkosten', _('Für Einstellplätze führt die Oberfläche keine Nebenkosten; der Wert wird so übernommen.'))
    # Zeitliche Überschneidung am selben Objekt: ein Objekt hat zu einem Zeitpunkt einen Mieter.
    ende_wirksam = ende or date(2100, 12, 31)
    for anderer in Mietvertrag.objects.filter(einheit=einheit, status__in=('aktiv', 'gekuendigt')).select_related('mieter'):
        a_ende = anderer.ende or date(2100, 12, 31)
        if anderer.beginn <= ende_wirksam and beginn <= a_ende:
            if anderer.mieter_id == mieter.pk and anderer.beginn == beginn:
                z.fehler('schluessel', _('Dieser Vertrag besteht schon (gleiches Objekt, gleicher Mieter, gleicher Beginn).'))
            else:
                z.fehler('objekt', _('Das Objekt ist im selben Zeitraum schon an %(m)s vermietet (Vertrag %(id)s, '
                                     'ab %(b)s).') % {'m': anderer.mieter.display_name, 'id': anderer.pk,
                                                      'b': anderer.beginn.strftime('%d.%m.%Y')})
            break
    if not z.ok:
        return None

    if basis_zins is None:
        ctx.sammle('vertraege', 'ohne_zins', _('%(n)s Verträge ohne Basis-Referenzzinssatz: es gilt der heutige Stand. '
                                                 'Mietzinsanpassungen nach Referenzzins sind dann erst ab heute zuverlässig.'))
    if basis_lik is None and modell != 'index':
        ctx.sammle('vertraege', 'ohne_lik', _('%(n)s Verträge ohne LIK-Basis: es gilt der heutige Stand.'))

    werte = dict(
        mieter=mieter, einheit=einheit, mitmieter=mitmieter, status=status, beginn=beginn, ende=ende,
        ist_befristet=bool(befristet), netto_mietzins=netto, nebenkosten=nk, nk_abrechnungsart=nk_art,
        zahlungsrhythmus=rhythmus, mietzins_modell=modell, kuendigungsfrist_monate=frist,
        erstmals_kuendbar_auf=erstmals, familienwohnung=bool(fam), anzahl_personen=personen or 1,
        mwst_pflichtig=bool(mwst), kautions_betrag=kaution or None, kautions_art=kautionsart or 'sperrkonto',
        kautions_konto=kautionskonto, kautions_einbezahlt_am=einbezahlt)
    if termine:
        werte['kuendigungstermine'] = termine
    if mwst:
        werte['mwst_satz'] = mwst_satz
    if basis_zins is not None:
        werte['basis_referenzzinssatz'] = basis_zins
    if basis_lik is not None:
        werte['basis_lik_punkte'] = basis_lik
    if basis_stand is not None:
        werte['basis_lik_stand'] = basis_stand
    if weitergabe is not None:
        werte['index_weitergabe_prozent'] = weitergabe
    if intervall is not None:
        werte['index_intervall_monate'] = intervall
    vertrag = Mietvertrag(**werte)

    # Die Regelquelle für Index- und Staffelmiete (Art. 269b/269c OR).
    for b in mietzinsmodell.pruefe_vertrag(vertrag):
        spalte = _FELD_ZU_SPALTE.get(b.feld or '', b.feld or 'mietzinsmodell')
        if b.ist_sperre:
            z.fehler(spalte, b.volltext)
        elif b.regel != 'index_anpassung':
            z.hinweis(spalte, b.volltext)
    # Kaution (Art. 257e OR): `Mietvertrag.save()` würde den Betrag stillschweigend kürzen; ein Import
    # ändert keine Beträge hinter dem Rücken der Verwaltung.
    if kaution:
        k = kaution_hoechstbetrag(kaution, netto, nk, kategorie=einheit.mietrecht_kategorie)
        if not k.ok:
            z.fehler('kaution', k.meldung)
    if not z.ok:
        return None
    try:
        vertrag.full_clean(exclude=['organisation', 'pdf_datei', 'kautions_zertifikat'])
    except ValidationError as e:
        z.modell_fehler(e, _FELD_ZU_SPALTE)
        return None
    vertrag.save()
    _referenz_setzen(ctx, 'vertraege', schluessel, vertrag, lauf)
    return 'neu'


_VERARBEITER = {
    'eigentuemer': _eigentuemer, 'liegenschaften': _liegenschaft, 'objekte': _objekt,
    'mieter': _mieter, 'vertraege': _vertrag,
}


# ── Lauf ──────────────────────────────────────────────────────────────────────
def _art_verarbeiten(ctx, art, name, inhalt, lauf):
    try:
        kopf, zeilen = lese_tabelle(name, inhalt, blatt=art)
    except DateiFehler as e:
        ctx.melde(art, None, '', STUFE_FEHLER, f'{name}: {e}')
        ctx.zaehle(art, 'fehler')
        return
    bekannt = {s['name'] for s in SPALTEN[art]}
    fehlend = [s['name'] for s in SPALTEN[art] if s['pflicht'] and s['name'] not in kopf]
    if fehlend:
        ctx.melde(art, 1, '', STUFE_FEHLER, _('In der Datei fehlen Pflichtspalten: %(s)s.') % {'s': ', '.join(fehlend)})
        ctx.zaehle(art, 'fehler')
        return
    unbekannt = [k for k in kopf if k not in bekannt]
    if unbekannt:
        ctx.melde(art, 1, '', STUFE_HINWEIS, _('Diese Spalten sind unbekannt und werden nicht gelesen: %(s)s.')
                  % {'s': ', '.join(unbekannt)})
    if not zeilen:
        ctx.melde(art, None, '', STUFE_HINWEIS, _('Die Datei enthält keine Datenzeilen.'))
        return
    doppelt = _Doppelt()
    verarbeiter = _VERARBEITER[art]
    for nr, daten in zeilen:
        ctx.zaehle(art, 'zeilen')
        z = _Zeile(ctx, art, nr, daten)
        doppelt.pruefe(z, z.roh('schluessel'))
        ergebnis = None
        if z.ok:
            try:
                with transaction.atomic():
                    ergebnis = verarbeiter(ctx, z, lauf)
                    if not z.ok:
                        # Teilweise Geschriebenes dieser Zeile (Objekt vor dem Sollmietzins) wieder entfernen.
                        raise _Zurueck
            except _Zurueck:
                ergebnis = None
            except Exception as e:   # noqa: BLE001 — jede Zeile soll ihren Grund nennen, der Lauf läuft weiter
                logger.warning('Datenimport %s Zeile %s: %s', art, nr, e, exc_info=True)
                z.fehler('', _('Die Zeile konnte nicht gespeichert werden: %(e)s') % {'e': e})
                ergebnis = None
        if ergebnis in ('neu', 'vorhanden') and z.ok:
            ctx.zaehle(art, ergebnis)
        else:
            ctx.zaehle(art, 'fehler')
    n_vorhanden = ctx.ergebnis.zaehler.get(art, {}).get('vorhanden', 0)
    if n_vorhanden:
        ctx.melde(art, None, '', STUFE_HINWEIS,
                  _('%(n)s Zeilen waren schon importiert oder entsprechen einem bestehenden Datensatz und wurden '
                    'übersprungen.') % {'n': n_vorhanden})


def verarbeite(organisation, dateien, *, ausfuehren, lauf=None):
    """Verarbeitet die Dateien in EINER Transaktion.

    `dateien`: {art: (dateiname, bytes)}. `ausfuehren=False` ist der Trockenlauf: am Ende wird
    zurückgerollt. Mit Fehlern wird auch beim Ausführen zurückgerollt. Gibt ein `Ergebnis` zurück.
    """
    unbekannt = set(dateien) - set(ARTEN)
    if unbekannt:
        raise ValueError(f'Unbekannte Art: {sorted(unbekannt)}')
    with organisation_kontext(organisation):
        ctx = _Kontext(organisation)
        try:
            with transaction.atomic():
                for art in ARTEN:
                    if art in dateien:
                        name, inhalt = dateien[art]
                        _art_verarbeiten(ctx, art, name, inhalt, lauf if ausfuehren else None)
                ctx.sammler_melden()
                if ctx.ergebnis.anzahl_fehler or not ausfuehren:
                    raise _Zurueck
        except _Zurueck:
            pass
    ctx.ergebnis.zaehler = {a: ctx.ergebnis.zaehler[a] for a in ARTEN if a in ctx.ergebnis.zaehler}
    return ctx.ergebnis


# ── Läufe mit Protokoll ───────────────────────────────────────────────────────
def _packen(dateien):
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for art, (name, inhalt) in dateien.items():
            zf.writestr(f'{art}/{name or art}', inhalt)
    return puffer.getvalue()


def _entpacken(blob):
    dateien = {}
    with zipfile.ZipFile(io.BytesIO(bytes(blob))) as zf:
        for info in zf.infolist():
            art, _sep, name = info.filename.partition('/')
            if art in ARTEN:
                dateien[art] = (name, zf.read(info))
    return dateien


def _in_lauf_schreiben(lauf, ergebnis):
    lauf.zaehler = ergebnis.zaehler
    lauf.meldungen = ergebnis.meldungen
    lauf.anzahl_fehler = ergebnis.anzahl_fehler
    lauf.anzahl_hinweise = ergebnis.anzahl_hinweise


def vorschau_erstellen(organisation, benutzer, dateien):
    """Trockenlauf mit Protokoll: legt einen Lauf an, der bei Erfolg ausführbar ist."""
    from core.models import DatenImportLauf
    with organisation_kontext(organisation):
        ergebnis = verarbeite(organisation, dateien, ausfuehren=False)
        lauf = DatenImportLauf(benutzer=benutzer)
        _in_lauf_schreiben(lauf, ergebnis)
        if ergebnis.ok and ergebnis.zaehler:
            lauf.status = DatenImportLauf.STATUS_VORSCHAU
            lauf.daten = _packen(dateien)
        else:
            lauf.status = DatenImportLauf.STATUS_FEHLERHAFT
            if ergebnis.ok:
                lauf.meldungen = [{'art': '', 'zeile': None, 'feld': '', 'stufe': STUFE_FEHLER,
                                   'text': str(_('Es wurde keine Datei hochgeladen.'))}]
                lauf.anzahl_fehler = 1
        lauf.save()
    return lauf


class AusfuehrungsFehler(Exception):
    """Der Lauf ist nicht (mehr) ausführbar. `str(e)` ist für den Menschen."""


def lauf_ausfuehren(organisation, lauf_id, benutzer):
    """Führt eine Vorschau aus, genau mit den Dateien, die geprüft wurden. Gibt den Lauf zurück.

    Die Zeile des Laufs wird gesperrt: Zwei gleichzeitige «Importieren» legen nichts doppelt an
    (der zweite findet den Status «importiert»). Gefunden wird nur ein Lauf der eigenen
    Organisation (`TenantManager`); `DoesNotExist` für jeden anderen."""
    from core.models import DatenImportLauf
    with organisation_kontext(organisation), transaction.atomic():
        lauf = DatenImportLauf.objects.select_for_update().get(pk=lauf_id)
        if lauf.status != DatenImportLauf.STATUS_VORSCHAU or not lauf.daten:
            raise AusfuehrungsFehler(_('Dieser Import ist nicht mehr ausführbar. Bitte die Dateien neu hochladen.'))
        dateien = _entpacken(lauf.daten)
        ergebnis = verarbeite(organisation, dateien, ausfuehren=True, lauf=lauf)
        _in_lauf_schreiben(lauf, ergebnis)
        if ergebnis.ok:
            lauf.status = DatenImportLauf.STATUS_IMPORTIERT
            lauf.ausgefuehrt_am = timezone.now()
        else:
            lauf.status = DatenImportLauf.STATUS_ABGEBROCHEN
        lauf.daten = b''
        lauf.save()
    return lauf


def lauf_verwerfen(organisation, lauf_id):
    from core.models import DatenImportLauf
    with organisation_kontext(organisation), transaction.atomic():
        lauf = DatenImportLauf.objects.select_for_update().get(pk=lauf_id)
        if lauf.status in (DatenImportLauf.STATUS_VORSCHAU, DatenImportLauf.STATUS_FEHLERHAFT):
            lauf.status = DatenImportLauf.STATUS_VERWORFEN
            lauf.daten = b''
            lauf.save()
    return lauf
