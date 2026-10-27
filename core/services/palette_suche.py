"""Die Datensuche hinter `/neu/palette/` — über alle Module.

WAS SIE TUT

Sechs Gruppen, höchstens fünf Treffer je Gruppe, dazu die Trefferzahl je
Gruppe (bis 99):

    personen     Mieter und Dienstleister (Handwerker)
    immobilien   Liegenschaften und Objekte (Einheiten)
    vertraege    Mietverträge
    buchhaltung  Debitoren- und Kreditorenrechnungen
    tickets      Schadenmeldungen
    dokumente    Dokumente der Vertragsablage, nur die neueste Fassung

WARUM EINE ABFRAGE JE GRUPPE UND NICHT JE MODELL

Die Palette läuft bei jedem Tastendruck. Neun Modelle mit je einer Abfrage
für die Treffer und einer für die Zahl wären 18 Abfragen; die Gruppe ist aber
das, was der Benutzer sieht, und sie darf nicht davon abhängen, wie viele
Modelle sich dahinter verbergen. Deshalb liefert jedes Modell seine Treffer in
EINER gemeinsamen Spaltenform (`SPALTEN`), die Teile einer Gruppe werden mit
`union()` zusammengesetzt, und die Datenbank sortiert und beschneidet. Je
Gruppe also genau zwei Abfragen: die Treffer und die Zahl. Die Anzahl ist fest
und hängt weder von der Trefferzahl noch von den Wörtern der Eingabe ab.

Die Zeilen werden dabei nicht als Modellobjekte geladen, sondern als Werte
(`values_list`). Damit gibt es keine Eigenschaft, die in einer Schleife
nachlädt, und keinen `select_related`, den jemand vergessen könnte: Was die
Darstellung braucht, steht in der Zeile.

MANDANTENTRENNUNG

Keine eigene Organisationslogik. Jeder Teil geht über `Modell.objects`, den
Manager mit dem Mandantenfilter. Auch der Unterabfrage-Zweig der Personen
(«hat einen aktiven Vertrag») fragt über `Mietvertrag.objects`.
`core/tests/test_omnisearch.py` prüft jede Gruppe mit einem zweiten Mandanten.
"""
import re
from datetime import date
from decimal import Decimal
from urllib.parse import quote_plus

from django.db.models import (
    Case, CharField, DateField, DecimalField, Exists, F, IntegerField, OuterRef, Q, Value, When)
from django.db.models.functions import Coalesce, Concat, Lower
from django.utils import timezone
from django.utils.translation import gettext

#: Reihenfolge der Gruppen in der Antwort.
GRUPPEN = ('personen', 'immobilien', 'vertraege', 'buchhaltung', 'tickets', 'dokumente')

#: Treffer je Gruppe in der Antwort, und die Obergrenze der Zahl je Gruppe.
JE_GRUPPE = 5
ZAHL_MAX = 99

#: Die gemeinsame Spaltenform. Jedes Modell füllt die Spalten, die es braucht,
#: den Rest mit einem Leerwert gleichen Typs — `union()` verlangt je Position
#: denselben Typ (PostgreSQL ist dabei strenger als SQLite).
#:
#:   u_tag     welches Modell die Zeile liefert (Schlüssel in `_DARSTELLER`)
#:   u_pk      Primärschlüssel
#:   u_sort    Sortierschlüssel (Text, Datum oder Zeitpunkt, je Gruppe einheitlich)
#:   u_t1..7   Textwerte; die Belegung steht beim jeweiligen Teil
#:   u_status  Statuscode des Modells (leer: kein Status)
#:   u_betrag  Betrag (NULL: kein Betrag)
#:   u_flag    0/1, Bedeutung je Teil (aktiver Vertrag, überfällig)
#:   u_datum   zweites Datum (Vertragsende)
TEXTSPALTEN = 7
SPALTEN = (('u_tag', 'u_pk', 'u_sort')
           + tuple(f'u_t{i}' for i in range(1, TEXTSPALTEN + 1))
           + ('u_status', 'u_betrag', 'u_flag', 'u_datum'))

_TEXT = CharField()
_GELD = DecimalField(max_digits=12, decimal_places=2)
_ZAHL = IntegerField()
_TAG = DateField()
_FRUEH = date(1900, 1, 1)


# ---------------------------------------------------------------------------
# Bedingungen
# ---------------------------------------------------------------------------

def wortweise(woerter, felder, dateinamen=(), nummern=False):
    """Jedes Wort der Eingabe muss in IRGENDEINEM der Felder vorkommen.

    WARUM WORTWEISE UND NICHT AM STÜCK

    Menschen tippen «Anna Blaser», das Programm speichert Vorname und
    Nachname getrennt. Ein `icontains` über die ganze Eingabe prüft dann
    «enthält der Vorname die Zeichenkette 'Anna Blaser'?» — nein, und
    «enthält der Nachname sie?» — auch nicht. Die Suche fand die Person
    also genau dann nicht, wenn man ihren vollen Namen kannte.

    Jedes Wort einzeln, alle mit UND verknüpft: «Anna Blaser» findet die
    Person, «Blaser Anna» ebenso, «Blaser Bahnhofstrasse» grenzt weiter
    ein statt mehr zu liefern.

    `dateinamen`: Dateifelder, von denen nur der NAME zählt, nicht der Pfad.
    Der Pfad einer Ablage lautet `organisation/<id>/<ordner>/<datum>/<name>`;
    ein `icontains` darauf fände «organisation» in jedem Dokument.

    `nummern`: Ein Wort wie «882» oder «#882» trifft zusätzlich die Nummer des
    Datensatzes (die Tickets heissen in der Oberfläche «#882»).
    """
    bedingung = Q()
    for wort in woerter:
        oder = Q()
        for feld in felder:
            oder |= Q(**{f'{feld}__icontains': wort})
        for feld in dateinamen:
            # Letzter Pfadabschnitt: nach dem letzten «/» darf nichts mehr
            # kommen, das ein «/» enthält. `re.escape` macht jedes Zeichen der
            # Eingabe wörtlich — «%», «_» und «.» sind hier keine Platzhalter.
            oder |= Q(**{f'{feld}__iregex': rf'[^/]*{re.escape(wort)}[^/]*$'})
        if nummern:
            ziffern = wort.lstrip('#')
            if ziffern.isdigit() and len(ziffern) <= 9:
                oder |= Q(pk=int(ziffern))
        bedingung &= oder
    return bedingung


# ---------------------------------------------------------------------------
# Die Teile: ein Modell in der gemeinsamen Spaltenform
# ---------------------------------------------------------------------------

def _ausdruck(wert, typ):
    """Feldname -> F(), None -> typisierter Leerwert, Ausdruck bleibt Ausdruck."""
    if wert is None:
        return Value(None, output_field=typ)
    if isinstance(wert, str):
        return F(wert)
    return wert


def _teil(qs, tag, sort, texte=(), status=None, betrag=None, flag=None, datum=None):
    """Das Queryset eines Modells in der Spaltenform `SPALTEN`."""
    texte = list(texte) + [None] * (TEXTSPALTEN - len(texte))
    spalten = {
        'u_tag': Value(tag, output_field=_TEXT),
        'u_pk': F('pk'),
        'u_sort': _ausdruck(sort, _TEXT),
        'u_status': _ausdruck(status, _TEXT) if status else Value('', output_field=_TEXT),
        'u_betrag': _ausdruck(betrag, _GELD),
        'u_flag': flag if flag is not None else Value(0, output_field=_ZAHL),
        'u_datum': _ausdruck(datum, _TAG),
    }
    for i, t in enumerate(texte, 1):
        spalten[f'u_t{i}'] = Value('', output_field=_TEXT) if t is None else _ausdruck(t, _TEXT)
    # `order_by()`: Ein Modell mit `Meta.ordering` bekäme sonst ein ORDER BY in
    # den Teil, und SQLite verbietet das in zusammengesetzten Abfragen.
    return qs.order_by().annotate(**spalten).values_list(*SPALTEN)


def _ja(bedingung):
    return Case(When(bedingung, then=Value(1)), default=Value(0), output_field=_ZAHL)


def _teile_personen(woerter, heute):
    from crm.models import Handwerker, Mieter
    from rentals.models import Mietvertrag

    # «Aktiv» heisst wie in der Personenliste: ein Vertrag im Status «aktiv»,
    # als Haupt- oder Mitmieter.
    aktiv = Exists(Mietvertrag.objects.filter(
        Q(mieter=OuterRef('pk')) | Q(mitmieter=OuterRef('pk')), status='aktiv'))
    yield _teil(
        Mieter.objects.filter(wortweise(
            woerter, ('vorname', 'nachname', 'firmen_name', 'email', 'ort'))),
        'mieter', Lower(Concat('nachname', Value(' '), 'firmen_name', Value(' '), 'vorname')),
        texte=('typ', 'vorname', 'nachname', 'firmen_name', 'ort', 'email'),
        flag=_ja(aktiv))
    yield _teil(
        Handwerker.objects.filter(wortweise(
            woerter, ('firma', 'kontaktperson', 'email', 'telefon'))),
        'handwerker', Lower('firma'),
        texte=('firma', 'branche', 'telefon', 'email'))


def _teile_immobilien(woerter, heute):
    from portfolio.models import Einheit, Liegenschaft

    yield _teil(
        Liegenschaft.objects.filter(wortweise(woerter, ('strasse', 'ort', 'plz'))),
        'liegenschaft', Lower('strasse'),
        texte=('strasse', 'plz', 'ort'), status='status')
    yield _teil(
        Einheit.objects.filter(wortweise(woerter, ('bezeichnung', 'liegenschaft__strasse'))),
        'objekt', Lower(Concat('liegenschaft__strasse', Value(' '), 'bezeichnung')),
        texte=('bezeichnung', 'liegenschaft__strasse'))


def _teile_vertraege(woerter, heute):
    from rentals.models import Mietvertrag

    yield _teil(
        Mietvertrag.objects.filter(wortweise(
            woerter, ('mieter__vorname', 'mieter__nachname', 'mieter__firmen_name',
                      'einheit__liegenschaft__strasse', 'einheit__bezeichnung'))),
        'vertrag', Coalesce('beginn', Value(_FRUEH, output_field=_TAG)),
        texte=('mieter__typ', 'mieter__vorname', 'mieter__nachname', 'mieter__firmen_name',
               'einheit__liegenschaft__strasse', 'einheit__bezeichnung'),
        status='status', datum='ende')


def _teile_buchhaltung(woerter, heute):
    from finance.models import DebitorenRechnung, KreditorenRechnung

    # Überfällig wie in der Debitorenliste (`fw_debitoren`, Ampel «rot»): noch
    # offen oder teilbezahlt, und die Fälligkeit — ersatzweise das
    # Rechnungsdatum — liegt vor heute.
    ueberfaellig = _ja(Q(status__in=('offen', 'teilbezahlt'))
                       & (Q(faellig_am__lt=heute) | Q(faellig_am__isnull=True, datum__lt=heute)))
    yield _teil(
        DebitorenRechnung.objects.filter(wortweise(
            woerter, ('titel', 'qr_referenz', 'vertrag__mieter__vorname',
                      'vertrag__mieter__nachname', 'vertrag__mieter__firmen_name'))),
        'debitor', 'datum',
        texte=('titel', 'vertrag__mieter__typ', 'vertrag__mieter__vorname',
               'vertrag__mieter__nachname', 'vertrag__mieter__firmen_name',
               'liegenschaft__strasse'),
        status='status', betrag='betrag', flag=ueberfaellig)

    # Storniertes steht nicht in der Kreditorenliste (`fw_kreditoren`), also
    # auch nicht hier: Die Adresse führt in diese Liste, und ein Treffer, den
    # sie nicht zeigt, wäre ein toter Link.
    ueberfaellig_k = _ja(Q(status__in=('neu', 'freigegeben', 'in_zahlung', 'teilbezahlt'))
                         & Q(faellig_am__lt=heute))
    yield _teil(
        KreditorenRechnung.objects.exclude(status='storniert').filter(wortweise(
            woerter, ('lieferant', 'referenz', 'liegenschaft__strasse'))),
        'kreditor', Coalesce('datum', Value(_FRUEH, output_field=_TAG)),
        texte=('lieferant', 'liegenschaft__strasse', 'referenz'),
        status='status', betrag='betrag', flag=ueberfaellig_k)


def _teile_tickets(woerter, heute):
    from tickets.models import SchadenMeldung

    yield _teil(
        SchadenMeldung.objects.filter(wortweise(
            woerter, ('titel', 'beschreibung', 'liegenschaft__strasse',
                      'betroffene_einheit__bezeichnung', 'melder_vorname', 'melder_nachname',
                      'gemeldet_von__vorname', 'gemeldet_von__nachname'),
            nummern=True)),
        'ticket', 'erstellt_am',
        texte=('titel', 'liegenschaft__strasse', 'betroffene_einheit__bezeichnung'),
        status='status')


def _teile_dokumente(woerter, heute):
    from rentals.models import Dokument

    yield _teil(
        Dokument.objects.neueste().exclude(datei='').filter(wortweise(
            woerter, ('bezeichnung', 'titel'), dateinamen=('datei',))),
        'dokument', 'datum',
        texte=('bezeichnung', 'titel', 'mieter__typ', 'mieter__vorname', 'mieter__nachname',
               'mieter__firmen_name', 'liegenschaft__strasse'))


#: Gruppe -> (Teile, neueste zuerst?). Textgruppen alphabetisch, Datumsgruppen
#: mit dem Jüngsten oben.
_GRUPPEN = {
    'personen': (_teile_personen, False),
    'immobilien': (_teile_immobilien, False),
    'vertraege': (_teile_vertraege, True),
    'buchhaltung': (_teile_buchhaltung, True),
    'tickets': (_teile_tickets, True),
    'dokumente': (_teile_dokumente, True),
}


# ---------------------------------------------------------------------------
# Status und Ton — aus dem Bestand, nicht erfunden
# ---------------------------------------------------------------------------

#: Die Töne, die die Oberfläche kennt (`fw-chip fw-<ton>`).
TOENE = ('crit', 'warn', 'good', 'mut')

#: Die Bestandsklassen der Statusfelder (`*_PILL` in den Ansichten) sagen, wie
#: die Oberfläche einen Status färbt; hier werden sie auf die vier Töne
#: abgebildet. «Info» und «Marke» (in Arbeit, in Zahlung) sind Zustände, in
#: denen etwas läuft — dort ist «warn» der nächste Ton.
_KLASSE_TON = (('fw-kritisch', 'crit'), ('fw-warnton', 'warn'), ('fw-info', 'warn'),
               ('fw-marke', 'warn'), ('fw-gut', 'good'), ('fw-mutet', 'mut'))

#: Liegenschaften haben im Bestand keine Statusfarbe; sie folgen den Verträgen
#: (aktiv grün, Entwurf und Archiv gedämpft).
_LIEGENSCHAFT_TON = {'aktiv': 'good', 'entwurf': 'mut', 'archiviert': 'mut'}


def ton_aus_klasse(klassen):
    """Der Ton zu den CSS-Klassen eines `*_PILL`-Eintrags (unbekannt: «mut»)."""
    teile = str(klassen).split()
    for klasse, ton in _KLASSE_TON:
        if klasse in teile:
            return ton
    return 'mut'


def _beschriftung(modell, code):
    """Das Statuslabel aus dem Modell (`get_status_display`), übersetzbar."""
    return str(dict(modell._meta.get_field('status').flatchoices).get(code, code))


def _status(modell, code, pill):
    """`{"text", "ton"}` für einen Statuscode, oder None ohne Code."""
    if not code:
        return None
    ton = ton_aus_klasse(pill[code][1]) if code in pill else 'mut'
    return {'text': _beschriftung(modell, code), 'ton': ton}


def _pills():
    from core.views.fw._basis import STATUS_PILL, VERTRAG_PILL
    from core.views.fw.kreditoren import KRED_PILL
    from core.views.fw.schaeden import TICKET_PILL
    return {'debitor': STATUS_PILL, 'kreditor': KRED_PILL, 'ticket': TICKET_PILL,
            'vertrag': VERTRAG_PILL}


# ---------------------------------------------------------------------------
# Darstellung: eine Zeile -> ein Treffer
# ---------------------------------------------------------------------------

def _chf(betrag):
    if betrag is None:
        return None
    return 'CHF ' + f'{Decimal(betrag):,.2f}'.replace(',', "'")


def _mieter_name(typ, vorname, nachname, firma):
    """Der Anzeigename einer Person — dieselbe Regel wie `Mieter.display_name`."""
    from crm.models import Mieter
    return Mieter(typ=typ or 'person', vorname=vorname or '', nachname=nachname or '',
                  firmen_name=firma or '').display_name


def _verbinden(*teile):
    return ' · '.join(t for t in teile if t)


class _Zeile:
    """Eine Zeile der Spaltenform mit Zugriff über Namen."""
    __slots__ = ('tag', 'pk', 'sort', 't', 'status', 'betrag', 'flag', 'datum')

    def __init__(self, werte):
        d = dict(zip(SPALTEN, werte))
        self.tag, self.pk, self.sort = d['u_tag'], d['u_pk'], d['u_sort']
        self.t = [d[f'u_t{i}'] or '' for i in range(1, TEXTSPALTEN + 1)]
        self.status, self.betrag = d['u_status'], d['u_betrag']
        self.flag, self.datum = d['u_flag'], d['u_datum']


def _treffer(art, label, zusatz, url, status=None, betrag=None):
    return {'art': art, 'label': label, 'zusatz': zusatz, 'url': url,
            'status': status, 'betrag': _chf(betrag)}


def _dar_mieter(z, pills):
    from rentals.models import Mietvertrag
    typ, vorname, nachname, firma, ort, email = z.t[:6]
    status = None
    if z.flag:
        status = _status(Mietvertrag, 'aktiv', pills['vertrag'])
    return _treffer(gettext('Person'), _mieter_name(typ, vorname, nachname, firma),
                    ort or email, f'/neu/personen/{z.pk}/', status)


def _dar_handwerker(z, pills):
    from crm.models import Handwerker
    firma, branche, telefon, email = z.t[:4]
    branche = _beschriftung_feld(Handwerker, 'branche', branche)
    return _treffer(gettext('Dienstleister'), firma, _verbinden(branche, telefon or email),
                    f'/neu/dienstleister/{z.pk}/')


def _beschriftung_feld(modell, feld, code):
    if not code:
        return ''
    return str(dict(modell._meta.get_field(feld).flatchoices).get(code, code))


def _dar_liegenschaft(z, pills):
    from portfolio.models import Liegenschaft
    strasse, plz, ort = z.t[:3]
    status = None
    if z.status:
        status = {'text': _beschriftung(Liegenschaft, z.status),
                  'ton': _LIEGENSCHAFT_TON.get(z.status, 'mut')}
    return _treffer(gettext('Liegenschaft'), strasse, f'{plz} {ort}'.strip(),
                    f'/neu/liegenschaften/{z.pk}/', status)


def _dar_objekt(z, pills):
    bezeichnung, strasse = z.t[:2]
    return _treffer(gettext('Objekt'), bezeichnung, strasse, f'/neu/objekte/{z.pk}/')


def _dar_vertrag(z, pills):
    from rentals.models import Mietvertrag
    typ, vorname, nachname, firma, strasse, bezeichnung = z.t[:6]
    hat_mieter = bool(typ)
    label = _mieter_name(typ, vorname, nachname, firma) if hat_mieter else f'MV-{z.pk}'
    zusatz = f'{strasse}, {bezeichnung}' if strasse else ''
    # Der Anzeige-Status, nicht der gespeicherte: ein Vertrag, dessen Ende
    # vorbei ist, gilt als «beendet» (`Mietvertrag.anzeige_status`).
    code = Mietvertrag(status=z.status, ende=z.datum).anzeige_status
    pill = pills['vertrag']
    status = {'text': str(dict(Mietvertrag._meta.get_field('status').flatchoices).get(code)
                          or pill[code][0]),
              'ton': ton_aus_klasse(pill[code][1]) if code in pill else 'mut'}
    return _treffer(gettext('Mietverhältnis'), label, zusatz, f'/neu/vertraege/{z.pk}/', status)


def _dar_debitor(z, pills):
    from finance.models import DebitorenRechnung
    titel, typ, vorname, nachname, firma, strasse = z.t[:6]
    wer = _mieter_name(typ, vorname, nachname, firma) if typ else strasse
    if z.flag:
        status = {'text': gettext('Überfällig'), 'ton': 'crit'}
    else:
        status = _status(DebitorenRechnung, z.status, pills['debitor'])
    return _treffer(gettext('Debitorenrechnung'), titel, wer,
                    f'/neu/debitoren/?q={quote_plus(titel)}', status, z.betrag)


def _dar_kreditor(z, pills):
    from finance.models import KreditorenRechnung
    lieferant, strasse, referenz = z.t[:3]
    if z.flag:
        status = {'text': gettext('Überfällig'), 'ton': 'crit'}
    else:
        status = _status(KreditorenRechnung, z.status, pills['kreditor'])
    suche = referenz or lieferant
    return _treffer(gettext('Kreditorenrechnung'), lieferant or referenz or f'#{z.pk}',
                    _verbinden(strasse, referenz), f'/neu/kreditoren/?q={quote_plus(suche)}',
                    status, z.betrag)


def _dar_ticket(z, pills):
    from tickets.models import SchadenMeldung
    titel, strasse, einheit = z.t[:3]
    ort = f'{strasse}, {einheit}' if strasse and einheit else strasse
    return _treffer(gettext('Ticket'), f'#{z.pk} {titel}', ort, f'/neu/schaeden/{z.pk}/',
                    _status(SchadenMeldung, z.status, pills['ticket']))


def _dar_dokument(z, pills):
    bezeichnung, titel, typ, vorname, nachname, firma, strasse = z.t[:7]
    # Wie die Dokumentenliste: Bezeichnung vor Titel — ausser die Bezeichnung
    # ist der Vorgabewert «Dokument» und es gibt einen Titel.
    if titel and bezeichnung in ('', 'Dokument'):
        label = titel
    else:
        label = bezeichnung or titel or gettext('Dokument')
    kontext = _mieter_name(typ, vorname, nachname, firma) if typ else strasse
    abgelegt = f'{z.sort:%d.%m.%Y}' if z.sort else ''
    return _treffer(gettext('Dokument'), label, _verbinden(kontext, abgelegt),
                    f'/neu/dokument/{z.pk}/verlauf/')


_DARSTELLER = {
    'mieter': _dar_mieter, 'handwerker': _dar_handwerker,
    'liegenschaft': _dar_liegenschaft, 'objekt': _dar_objekt,
    'vertrag': _dar_vertrag, 'debitor': _dar_debitor, 'kreditor': _dar_kreditor,
    'ticket': _dar_ticket, 'dokument': _dar_dokument,
}


# ---------------------------------------------------------------------------
# Der Einstieg
# ---------------------------------------------------------------------------

def _vereinigt(teile):
    teile = list(teile)
    return teile[0].union(*teile[1:], all=True) if len(teile) > 1 else teile[0]


def suche(eingabe):
    """Sucht `eingabe` in allen Gruppen.

    Gibt `(treffer, zahlen)` zurück: die Treffer in der Reihenfolge der Gruppen
    (je Treffer mit `gruppe`) und die Trefferzahl je Gruppe. Je Gruppe zwei
    Abfragen — Treffer und Zahl —, unabhängig von der Trefferzahl.

    Der Aufrufer prüft die Mindestlänge; hier wird nicht mehr geprüft.
    """
    woerter = eingabe.split()
    heute = timezone.localdate()
    pills = _pills()
    treffer, zahlen = [], {}
    for gruppe in GRUPPEN:
        teile, neueste_zuerst = _GRUPPEN[gruppe]
        alle = _vereinigt(teile(woerter, heute))
        # Sortiert wird nach dem Schlüssel, danach nach der Herkunft und dem
        # Primärschlüssel — damit die Reihenfolge bei gleichem Schlüssel nicht
        # vom Zufall der Datenbank abhängt.
        richtung = '-' if neueste_zuerst else ''
        zeilen = alle.order_by(f'{richtung}u_sort', 'u_tag', f'{richtung}u_pk')[:JE_GRUPPE]
        for werte in zeilen:
            zeile = _Zeile(werte)
            treffer.append({'gruppe': gruppe, **_DARSTELLER[zeile.tag](zeile, pills)})
        # Gezählt wird bis ZAHL_MAX: «99» heisst «99 oder mehr», und die
        # Datenbank zählt nie mehr als nötig.
        zahlen[gruppe] = alle.order_by()[:ZAHL_MAX].count()
    return treffer, zahlen
