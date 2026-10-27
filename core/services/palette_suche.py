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

WAS NACH DER ABFRAGE NOCH GELADEN WIRD (`_NACHLADEN`)

Zwei Angaben lassen sich nicht in die Spaltenform pressen, weil sie aus
Fachregeln des Bestands folgen und nicht aus einer Spalte: der aktuell gültige
Netto-Mietzins eines Vertrags (`Mietvertrag.effektiver_netto_mietzins`:
Anpassungen, Komponenten, Staffel, Zeitplan) und der Belegungsstand eines
Objekts (`faelle.objekte.zeilen`, dieselbe Regel wie die Objektliste). Beide
laufen NACH dem Beschneiden auf fünf Zeilen, als Stapel für alle Treffer des
Modells zugleich (`prefetch_related`). Das kostet je Modell eine feste Zahl
Abfragen — nur, wenn es Treffer gibt, und unabhängig von deren Anzahl.

WER WAS SUCHEN DARF (`sicht_von`)

Die Rollenprüfung steht hier und nicht in der Ansicht oder der Oberfläche:
Das Team sucht in allen sechs Gruppen. Die Hauswartung (Rolle «Hauswart», keine
Team-Rolle) sucht nur in `HAUSWART_GRUPPEN`, und dort nur in den Liegenschaften,
die ihr zugeordnet sind. Wer keine der beiden Rollen hat, bekommt
`PermissionDenied`.

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

from django.core.exceptions import PermissionDenied
from django.db.models import (
    Case, CharField, DateField, DecimalField, Exists, F, IntegerField, OuterRef, Q, Subquery,
    Value, When)
from django.db.models.functions import Cast, Coalesce, Concat, Lower
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy, pgettext

#: Reihenfolge der Gruppen in der Antwort.
GRUPPEN = ('personen', 'immobilien', 'vertraege', 'buchhaltung', 'tickets', 'dokumente')

#: Treffer je Gruppe in der Antwort, und die Obergrenze der Zahl je Gruppe.
JE_GRUPPE = 5
ZAHL_MAX = 99

#: Was die Hauswartung suchen darf. Nur die Gruppen, deren Treffer sie auch
#: öffnen darf: Liegenschaften, Objekte, Personen, Verträge und Dokumente sind
#: für sie gesperrt (`rolle_erforderlich(*TEAM_ROLLEN)`, 403), die Schäden nicht
#: (`TICKET_LESE_ROLLEN`). Ein Treffer, der in eine Absage führt, wäre ein toter
#: Link — und bei Dokumenten und Verträgen zugleich eine Auskunft über Mieter,
#: die der Rolle nicht zusteht. Öffnet man der Hauswartung eine weitere Seite,
#: wird die Gruppe hier ergänzt (`test_hauswart_gruppen_sind_offen` hält beides
#: zusammen).
HAUSWART_GRUPPEN = ('tickets',)

#: Die ausführliche Suche, auf die «Alle Ergebnisse» und das Formular ohne
#: JavaScript führen: beim Team `/neu/suche/`, bei der Hauswartung (der diese
#: Seite gesperrt ist) die Schadenliste, die dasselbe `?q=` kennt.
SUCHSEITE_TEAM = '/neu/suche/'
SUCHSEITE_HAUSWART = '/neu/schaeden/'

#: Werte der Spalte `u_flag` bei Debitorenrechnungen (bei den übrigen Teilen 0/1).
FLAG_UEBERFAELLIG = 1
FLAG_BETREIBUNG = 2

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
#:   u_flag    0/1, Bedeutung je Teil (aktiver Vertrag, überfällig); bei Debitoren
#:             0/1/2 (`FLAG_UEBERFAELLIG`, `FLAG_BETREIBUNG`)
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


def _teile_personen(woerter, heute, sicht):
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


def _teile_immobilien(woerter, heute, sicht):
    from portfolio.models import Einheit, Liegenschaft

    yield _teil(
        Liegenschaft.objects.filter(wortweise(woerter, ('strasse', 'ort', 'plz'))),
        'liegenschaft', Lower('strasse'),
        texte=('strasse', 'plz', 'ort'), status='status')
    yield _teil(
        Einheit.objects.filter(wortweise(woerter, ('bezeichnung', 'liegenschaft__strasse'))),
        'objekt', Lower(Concat('liegenschaft__strasse', Value(' '), 'bezeichnung')),
        texte=('bezeichnung', 'liegenschaft__strasse'))


def _teile_vertraege(woerter, heute, sicht):
    from rentals.models import Mietvertrag

    yield _teil(
        Mietvertrag.objects.filter(wortweise(
            woerter, ('mieter__vorname', 'mieter__nachname', 'mieter__firmen_name',
                      'einheit__liegenschaft__strasse', 'einheit__bezeichnung'))),
        'vertrag', Coalesce('beginn', Value(_FRUEH, output_field=_TAG)),
        texte=('mieter__typ', 'mieter__vorname', 'mieter__nachname', 'mieter__firmen_name',
               'einheit__liegenschaft__strasse', 'einheit__bezeichnung'),
        status='status', datum='ende')


def _teile_buchhaltung(woerter, heute, sicht):
    from finance.models import Betreibung, DebitorenRechnung, KreditorenRechnung, Mahnung

    # Überfällig wie in der Debitorenliste (`fw_debitoren`, Ampel «rot»): noch
    # offen oder teilbezahlt, und die Fälligkeit — ersatzweise das
    # Rechnungsdatum — liegt vor heute.
    ueberfaellig_q = (Q(status__in=('offen', 'teilbezahlt'))
                      & (Q(faellig_am__lt=heute) | Q(faellig_am__isnull=True, datum__lt=heute)))
    # Das Mahnwesen des Bestands, als Unterabfragen in derselben Zeile (keine
    # Abfrage je Treffer): die höchste erfasste Mahnung (`finance.Mahnung`,
    # die revisionssichere Mahn-Historie) und eine noch offene Betreibung
    # (`finance.Betreibung`, als Hauptforderung oder unter den weiteren
    # Rechnungen). Beide über `objects`, also im eigenen Mandanten.
    hoechste_mahnung = Subquery(
        Mahnung.objects.filter(debitoren_rechnung=OuterRef('pk'))
        .order_by('-stufe').values('stufe')[:1], output_field=_ZAHL)
    offene_betreibung = Exists(
        Betreibung.objects.filter(Q(debitoren_rechnung=OuterRef('pk'))
                                  | Q(weitere_rechnungen=OuterRef('pk')))
        .exclude(status__in=Betreibung.ABGESCHLOSSEN))
    ueberfaellig = Case(
        When(ueberfaellig_q, then=Case(When(offene_betreibung, then=Value(FLAG_BETREIBUNG)),
                                       default=Value(FLAG_UEBERFAELLIG))),
        default=Value(0), output_field=_ZAHL)
    yield _teil(
        DebitorenRechnung.objects.filter(wortweise(
            woerter, ('titel', 'qr_referenz', 'vertrag__mieter__vorname',
                      'vertrag__mieter__nachname', 'vertrag__mieter__firmen_name'))),
        'debitor', 'datum',
        texte=('titel', 'vertrag__mieter__typ', 'vertrag__mieter__vorname',
               'vertrag__mieter__nachname', 'vertrag__mieter__firmen_name',
               'liegenschaft__strasse',
               Cast(Coalesce(hoechste_mahnung, Value(0)), output_field=_TEXT)),
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


def _teile_tickets(woerter, heute, sicht):
    from tickets.models import SchadenMeldung

    meldungen = SchadenMeldung.objects.all()
    if sicht.nur_hauswart:
        # Wie die Schadenliste (`fw_schaeden`): nur die zugeordneten Liegenschaften.
        meldungen = meldungen.filter(liegenschaft__hauswarte=sicht.benutzer)
    yield _teil(
        meldungen.filter(wortweise(
            woerter, ('titel', 'beschreibung', 'liegenschaft__strasse',
                      'betroffene_einheit__bezeichnung', 'melder_vorname', 'melder_nachname',
                      'gemeldet_von__vorname', 'gemeldet_von__nachname'),
            nummern=True)),
        'ticket', 'erstellt_am',
        texte=('titel', 'liegenschaft__strasse', 'betroffene_einheit__bezeichnung'),
        status='status')


def _teile_dokumente(woerter, heute, sicht):
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
    __slots__ = ('tag', 'pk', 'sort', 't', 'status', 'betrag', 'flag', 'datum', 'extra')

    def __init__(self, werte):
        d = dict(zip(SPALTEN, werte))
        self.tag, self.pk, self.sort = d['u_tag'], d['u_pk'], d['u_sort']
        self.t = [d[f'u_t{i}'] or '' for i in range(1, TEXTSPALTEN + 1)]
        self.status, self.betrag = d['u_status'], d['u_betrag']
        self.flag, self.datum = d['u_flag'], d['u_datum']
        self.extra = None                  # füllt `_NACHLADEN`, wo ein Modell es braucht


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
    return _treffer(gettext('Objekt'), bezeichnung, strasse, f'/neu/objekte/{z.pk}/', z.extra)


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
    return _treffer(gettext('Mietverhältnis'), label, zusatz, f'/neu/vertraege/{z.pk}/', status,
                    z.betrag)


#: Die ersten drei Stufen haben im Bestand eigene Übersetzungen (1er, 2e, 3e rappel);
#: für jede weitere gilt die Vorlage «%(stufe)s. Mahnung» der Mahnansicht.
_MAHNUNG_TEXT = {1: gettext_lazy('1. Mahnung'), 2: gettext_lazy('2. Mahnung'),
                 3: gettext_lazy('3. Mahnung')}


def _ueberfaellig_text(flag, mahnstufe):
    """«Überfällig», verfeinert um den Stand des Mahnwesens.

    Eine offene Betreibung geht vor, dann die höchste erfasste Mahnung. Der Ton
    bleibt «crit» in jeder Stufe: «Überfällig» war schon rot, und eine
    «1. Mahnung» in Gelb sähe aus, als wäre die Lage nach der Mahnung
    harmloser als davor.
    """
    if flag == FLAG_BETREIBUNG:
        return gettext('Betreibung')
    if mahnstufe.isdigit() and int(mahnstufe) > 0:
        stufe = int(mahnstufe)
        return str(_MAHNUNG_TEXT.get(stufe) or gettext('%(stufe)s. Mahnung') % {'stufe': stufe})
    return gettext('Überfällig')


def _dar_debitor(z, pills):
    from finance.models import DebitorenRechnung
    titel, typ, vorname, nachname, firma, strasse, mahnstufe = z.t[:7]
    wer = _mieter_name(typ, vorname, nachname, firma) if typ else strasse
    if z.flag:
        status = {'text': _ueberfaellig_text(z.flag, mahnstufe), 'ton': 'crit'}
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
# Nach der Abfrage: Angaben, die eine Fachregel des Bestands rechnet
# ---------------------------------------------------------------------------

#: Der Befund der Objektliste, der «gekündigt, wird frei» meint
#: (`faelle.objekte._befunde`). Ein Test hält ihn an einem echten Fall fest.
_BEFUND_WIRD_FREI = 'Wird frei'

#: Übersetzungskontext der Belegung EINES Objekts: Die Kennzahlen der Listen
#: («Vermietet», «Leer») stehen in der Mehrzahl, ein Chip an einem Objekt in der Einzahl.
_BELEGUNG = 'Belegung eines Objekts'


def _nachladen_vertraege(zeilen, heute):
    """Der aktuell gültige Netto-Mietzins je Vertrag, in `z.betrag`.

    `Mietvertrag.effektiver_netto_mietzins` — dieselbe Auskunft wie die
    Mietzinsliste und der Mieterspiegel: jüngste wirksame Anpassung, Komponente,
    Zeitplan oder Staffelstufe, sonst der Vertragswert. Der NETTO-Mietzins ohne
    Nebenkosten, und der Referenzwert, nicht der verrechnete: Ein Gratismonat
    ändert die Auskunft «was kostet das Verhältnis» nicht.

    Stichtag ist heute, bei einem schon beendeten Vertrag sein Ende. Der
    Sollmietzins-Zeitplan eines Objekts kennt kein Vertragsende
    (`_sollmietzins_zeile`); mit «heute» könnte ihm der Zeitplan des
    Nachmieters den Betrag setzen.

    Die vier Relationen, die die Methode liest, kommen im Stapel
    (`prefetch_related`); ohne sie wären es vier Abfragen je Vertrag.
    """
    from rentals.models import Mietvertrag
    je_pk = {z.pk: z for z in zeilen}
    vertraege = (Mietvertrag.objects.filter(pk__in=je_pk).select_related('einheit')
                 .prefetch_related('anpassungen', 'staffelstufen', 'mietzins_komponenten',
                                   'einheit__sollmietzinse'))
    for v in vertraege:
        stichtag = min(heute, v.ende) if v.ende else heute
        je_pk[v.pk].betrag = v.effektiver_netto_mietzins(stichtag)


def _nachladen_objekte(zeilen, heute):
    """Der Belegungsstand je Objekt, als Status in `z.extra`.

    Nach der Regel der Objektliste (`faelle.objekte.zeilen`), nicht nach einer
    zweiten: belegt, belegt mit baldigem Ende ohne Nachmieter, leer, oder
    heute leer mit Nachmieter ab einem Datum. Ein Objekt hat keinen
    gespeicherten Status, nur diese Herleitung.
    """
    from faelle.objekte import zeilen as belegung
    from portfolio.models import Einheit
    je_pk = {z.pk: z for z in zeilen}
    for e in belegung(Einheit.objects.filter(pk__in=je_pk), stichtag=heute):
        if e['belegt']:
            wird_frei = any(b['text'] == _BEFUND_WIRD_FREI for b in e['befunde'])
            status = ({'text': gettext('Wird frei'), 'ton': 'warn'} if wird_frei
                      else {'text': pgettext(_BELEGUNG, 'Vermietet'), 'ton': 'good'})
        elif e['nachmieter_ab']:
            status = {'text': pgettext(_BELEGUNG, 'Vermietet ab %(datum)s')
                      % {'datum': f"{e['nachmieter_ab']:%d.%m.%Y}"}, 'ton': 'good'}
        else:
            status = {'text': pgettext(_BELEGUNG, 'Leer'), 'ton': 'warn'}
        je_pk[e['e'].pk].extra = status


#: Tag des Teils -> Funktion, die die fünf Zeilen dieses Modells ergänzt.
_NACHLADEN = {'vertrag': _nachladen_vertraege, 'objekt': _nachladen_objekte}


# ---------------------------------------------------------------------------
# Wer darf was
# ---------------------------------------------------------------------------

class Sicht:
    """Was ein Benutzer in der aktiven Organisation durchsuchen darf."""
    __slots__ = ('benutzer', 'gruppen', 'nur_hauswart', 'suchseite')

    def __init__(self, benutzer, gruppen, nur_hauswart):
        self.benutzer, self.gruppen, self.nur_hauswart = benutzer, gruppen, nur_hauswart
        self.suchseite = SUCHSEITE_HAUSWART if nur_hauswart else SUCHSEITE_TEAM


def sicht_von(benutzer, rollen=None):
    """Die Sicht des Benutzers; `PermissionDenied` ohne Team- oder Hauswartrolle.

    `rollen`: die Rollen in der aktiven Organisation (`core.auth.eigene_rollen`),
    wenn der Aufrufer sie ohnehin gelesen hat — sonst eine Abfrage hier.

    Team (und Superuser) suchen überall. Die Hauswartung nur in
    `HAUSWART_GRUPPEN`; hat jemand beide Rollen, gilt das Team (wie
    `core.auth.ist_nur_hauswart`).
    """
    from core.auth import ROLLE_HAUSWART, TEAM_ROLLEN, eigene_rollen
    if getattr(benutzer, 'is_superuser', False):
        return Sicht(benutzer, GRUPPEN, False)
    if rollen is None:
        rollen = eigene_rollen(benutzer)
    if rollen & set(TEAM_ROLLEN):
        return Sicht(benutzer, GRUPPEN, False)
    if ROLLE_HAUSWART in rollen:
        return Sicht(benutzer, tuple(g for g in GRUPPEN if g in HAUSWART_GRUPPEN), True)
    raise PermissionDenied('Für die Suche fehlt die Berechtigung.')


# ---------------------------------------------------------------------------
# Der Einstieg
# ---------------------------------------------------------------------------

def _vereinigt(teile):
    teile = list(teile)
    return teile[0].union(*teile[1:], all=True) if len(teile) > 1 else teile[0]


def suche(eingabe, benutzer):
    """Sucht `eingabe` in den Gruppen, die `benutzer` durchsuchen darf.

    Gibt `(treffer, zahlen)` zurück: die Treffer in der Reihenfolge der Gruppen
    (je Treffer mit `gruppe`) und die Trefferzahl je durchsuchter Gruppe. Je
    Gruppe zwei Abfragen — Treffer und Zahl —, unabhängig von der Trefferzahl,
    dazu die Stapel von `_NACHLADEN`, wenn es Treffer dieser Modelle gibt.

    Die Rolle prüft dieser Dienst (`sicht_von`): Das Team bekommt alle sechs
    Gruppen, die Hauswartung nur ihre (`HAUSWART_GRUPPEN`, nur eigene
    Liegenschaften), alle anderen `PermissionDenied`.

    Der Aufrufer prüft die Mindestlänge; hier wird nicht mehr geprüft.
    """
    erlaubnis = sicht_von(benutzer)
    woerter = eingabe.split()
    heute = timezone.localdate()
    pills = _pills()
    treffer, zahlen = [], {}
    for gruppe in erlaubnis.gruppen:
        teile, neueste_zuerst = _GRUPPEN[gruppe]
        alle = _vereinigt(teile(woerter, heute, erlaubnis))
        # Sortiert wird nach dem Schlüssel, danach nach der Herkunft und dem
        # Primärschlüssel — damit die Reihenfolge bei gleichem Schlüssel nicht
        # vom Zufall der Datenbank abhängt.
        richtung = '-' if neueste_zuerst else ''
        zeilen = [_Zeile(w) for w in
                  alle.order_by(f'{richtung}u_sort', 'u_tag', f'{richtung}u_pk')[:JE_GRUPPE]]
        for tag, nachladen in _NACHLADEN.items():
            eigene = [z for z in zeilen if z.tag == tag]
            if eigene:
                nachladen(eigene, heute)
        for zeile in zeilen:
            treffer.append({'gruppe': gruppe, **_DARSTELLER[zeile.tag](zeile, pills)})
        # Gezählt wird bis ZAHL_MAX: «99» heisst «99 oder mehr», und die
        # Datenbank zählt nie mehr als nötig.
        zahlen[gruppe] = alle.order_by()[:ZAHL_MAX].count()
    return treffer, zahlen
