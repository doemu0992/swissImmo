"""Eigentümerportal v2: was ein Eigentümer von seinen Liegenschaften sehen darf.

ZUGRIFF HAT ZWEI SCHICHTEN, UND BEIDE GEHÖREN HIER HER

1. Mandantentrennung: Der Default-Manager filtert auf die Organisation des
   Anfragekontexts (`core.middleware_tenancy` leitet sie für ein Portal-Konto
   aus dessen Liegenschaft ab).
2. Eigentümerbezug: Innerhalb einer Organisation gibt es viele Eigentümer. Wer
   sich als Eigentümer A anmeldet, sieht die Liegenschaften von Eigentümer B
   derselben Verwaltung nicht. Das leistet der Mandantenfilter NICHT — es ist
   ein eigener Filter, `eigentuemer=…`, und jede Abfrage dieses Moduls trägt ihn.

Alle Funktionen nehmen den `Eigentuemer` und leiten daraus ab, was sichtbar ist.
Eine ID aus der Adresszeile wird nie für sich genommen, sondern immer als
Einschränkung auf die eigene Menge (`eigene_liegenschaften(...).filter(pk=…)`).

LESEND: Dieses Modul ändert nichts, ausser `anfrage_senden` (eine Pendenz für die
Verwaltung, dieselbe Art wie die Anfrage eines Stockwerkeigentümers).
"""
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import ExtractYear
from django.utils import translation
from django.utils.translation import gettext, gettext_lazy as _

from core.zeit import datum_heute

logger = logging.getLogger(__name__)

NULL = Decimal('0.00')

#: Vorbemerkung der Quelle an der Pendenz: kennzeichnet eine Anfrage aus dem Portal
#: und den Eigentümer, der sie gestellt hat (Verlauf «Meine Mitteilungen»).
ANFRAGE_QUELLE = 'portal-eigentuemer:'

#: Arten einer Anfrage (Schlüssel -> Bezeichnung). Der Eigentümer sieht sie in seiner Sprache;
#: im Titel der Pendenz steht die deutsche Fassung, denn die Verwaltung arbeitet auf Deutsch.
ANFRAGE_ARTEN = (
    ('frage', _('Allgemeine Frage')),
    ('abrechnung', _('Abrechnung oder Auszahlung')),
    ('unterhalt', _('Unterhalt oder Schaden')),
    ('stammdaten', _('Änderung meiner Angaben')),
    ('mandat', _('Mandat oder Vertrag')),
)

BETREFF_MAX = 150
TEXT_MAX = 4000


# ---------------------------------------------------------------------------
# Menge der eigenen Daten
# ---------------------------------------------------------------------------

def eigene_liegenschaften(eigentuemer):
    """Alle Liegenschaften dieses Eigentümers — archivierte eingeschlossen."""
    from portfolio.models import Liegenschaft
    return Liegenschaft.objects.filter(eigentuemer=eigentuemer).order_by('strasse', 'id')


def mandat_status(eigentuemer):
    """Der Archiveintrag des Mandats, wenn es beendet ist, sonst None."""
    from core.services.archiv import eintrag
    return eintrag(eigentuemer)


def _archiveintraege(modell_label, ids):
    from core.models import Archiveintrag
    if not ids:
        return {}
    return {e.objekt_id: e for e in Archiveintrag.objects.filter(typ=modell_label, objekt_id__in=ids)}


# ---------------------------------------------------------------------------
# Liegenschaften, Objekte, Belegung
# ---------------------------------------------------------------------------

def _offene_posten_je_liegenschaft(lg_ids, heute):
    """`{lg_id: (offen, ueberfaellig)}` — offener Restbetrag, nicht der Rechnungsbetrag."""
    from finance.models import DebitorenRechnung
    out = defaultdict(lambda: [NULL, NULL])
    qs = (DebitorenRechnung.objects
          .filter(status__in=('offen', 'teilbezahlt'))
          .filter(Q(liegenschaft_id__in=lg_ids) | Q(vertrag__einheit__liegenschaft_id__in=lg_ids))
          .select_related('vertrag__einheit')
          .prefetch_related('zahlungseingaenge'))
    for r in qs:
        lg_id = r.liegenschaft_id
        if lg_id not in lg_ids and r.vertrag_id and r.vertrag.einheit_id:
            lg_id = r.vertrag.einheit.liegenschaft_id
        if lg_id not in lg_ids:
            continue
        offen = r.offener_betrag
        out[lg_id][0] += offen
        if (r.faellig_am or r.datum) < heute:
            out[lg_id][1] += offen
    return out


def offene_posten(eigentuemer, heute=None):
    """Offene Debitoren der eigenen Liegenschaften, älteste Fälligkeit zuerst.

    Liste von dicts: `titel`, `faellig`, `betrag` (Rest), `ueberfaellig`, `liegenschaft`."""
    from finance.models import DebitorenRechnung
    heute = heute or datum_heute()
    lgs = {lg.pk: lg for lg in eigene_liegenschaften(eigentuemer)}
    qs = (DebitorenRechnung.objects
          .filter(status__in=('offen', 'teilbezahlt'))
          .filter(Q(liegenschaft_id__in=lgs) | Q(vertrag__einheit__liegenschaft_id__in=lgs))
          .select_related('vertrag__einheit')
          .prefetch_related('zahlungseingaenge'))
    zeilen = []
    for r in qs:
        lg_id = r.liegenschaft_id if r.liegenschaft_id in lgs else (
            r.vertrag.einheit.liegenschaft_id if r.vertrag_id and r.vertrag.einheit_id else None)
        if lg_id not in lgs:
            continue
        faellig = r.faellig_am or r.datum
        zeilen.append({'titel': r.titel, 'faellig': faellig, 'betrag': r.offener_betrag,
                       'ueberfaellig': faellig < heute, 'liegenschaft': lgs[lg_id]})
    zeilen.sort(key=lambda z: (z['faellig'], z['titel']))
    return zeilen


def liegenschaften_karten(eigentuemer, heute=None):
    """Eine Zeile je Liegenschaft mit Belegung und Zahlen — konstant viele Abfragen.

    `lg`, `archiviert` (Archiveintrag oder None), `objekte`, `leer`, `soll_monat` (netto),
    `offen`, `ueberfaellig`."""
    from core.services.rendite import soll_jahresmieten
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    heute = heute or datum_heute()
    lgs = list(eigene_liegenschaften(eigentuemer))
    ids = {lg.pk for lg in lgs}
    if not ids:
        return []
    archiviert = _archiveintraege('portfolio.Liegenschaft', ids)
    gesamt = defaultdict(int)
    for lg_id in Einheit.objects.filter(liegenschaft_id__in=ids).values_list('liegenschaft_id', flat=True):
        gesamt[lg_id] += 1
    belegt = defaultdict(set)
    for lg_id, einheit_id in (Mietvertrag.objects.filter(status__in=('aktiv', 'gekuendigt'),
                                                         einheit__liegenschaft_id__in=ids)
                              .values_list('einheit__liegenschaft_id', 'einheit_id')):
        belegt[lg_id].add(einheit_id)
    soll = soll_jahresmieten(lgs, heute)
    offen = _offene_posten_je_liegenschaft(ids, heute)
    karten = []
    # Laufende Liegenschaften zuerst, archivierte danach.
    for lg in sorted(lgs, key=lambda x: (x.pk in archiviert, x.strasse, x.pk)):
        karten.append({
            'lg': lg, 'archiviert': archiviert.get(lg.pk),
            'objekte': gesamt[lg.pk], 'leer': max(0, gesamt[lg.pk] - len(belegt[lg.pk])),
            'soll_monat': soll[lg.pk][0] / 12,
            'offen': offen[lg.pk][0], 'ueberfaellig': offen[lg.pk][1],
        })
    return karten


def belegung(eigentuemer, lg_pk, heute=None):
    """Objekte einer eigenen Liegenschaft mit aktuellem Mietverhältnis.

    Gibt `None` zurück, wenn die Liegenschaft nicht diesem Eigentümer gehört —
    der Aufrufer macht daraus 404, nie 403 (kein Hinweis, dass die ID existiert)."""
    from core.services.archiv import ausblenden
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    heute = heute or datum_heute()
    lg = eigene_liegenschaften(eigentuemer).filter(pk=lg_pk).first()
    if lg is None:
        return None
    einheiten = list(ausblenden(Einheit.objects.filter(liegenschaft=lg)).order_by('bezeichnung', 'id'))
    vertraege = {}
    qs = (Mietvertrag.objects.filter(einheit__liegenschaft=lg, status__in=('aktiv', 'gekuendigt'))
          .select_related('mieter')
          .prefetch_related('anpassungen', 'staffelstufen', 'mietzins_komponenten',
                            'einheit__sollmietzinse')
          .order_by('einheit_id', 'beginn', 'id'))
    for v in qs:
        # Bei zwei laufenden Verträgen derselben Einheit gilt der jüngere (letzte).
        vertraege[v.einheit_id] = v
    zeilen = []
    for e in einheiten:
        v = vertraege.get(e.pk)
        netto = brutto = None
        if v is not None:
            netto = v.effektiver_netto_mietzins(heute) or NULL
            brutto = netto + (v.effektive_nebenkosten(heute) or NULL)
        zeilen.append({'einheit': e, 'vertrag': v, 'netto': netto, 'brutto': brutto})
    belegt = sum(1 for z in zeilen if z['vertrag'] is not None)
    eintrag = _archiveintraege('portfolio.Liegenschaft', [lg.pk]).get(lg.pk)
    return {'lg': lg, 'archiviert': eintrag, 'zeilen': zeilen, 'objekte': len(zeilen),
            'belegt': belegt, 'leer': len(zeilen) - belegt,
            'soll_netto': sum((z['netto'] or NULL for z in zeilen), NULL)}


# ---------------------------------------------------------------------------
# Abrechnungen, Kontokorrent, Auszahlungen
# ---------------------------------------------------------------------------

def ergebnis_je_jahr(eigentuemer):
    """`{jahr: {lg_pk: [ertrag, aufwand]}}` aus dem Hauptbuch, in EINER Summenabfrage.

    Dieselbe Rechnung wie `eigentuemer_kontokorrent.kontokorrent` und
    `_mandat_abrechnung_daten` (Ertrag = Haben − Soll auf Ertragskonten, Aufwand =
    Soll − Haben auf Aufwandskonten, Abschlussbuchungen ausgenommen), nur nicht je
    Konto und Liegenschaft einzeln abgefragt. Dass die Zahlen übereinstimmen,
    sichert `test_eigentuemer_portal`."""
    from core.services.jahresabschluss import abschluss_buchungen_q
    from finance.models import Buchung, Buchungskonto
    ids = list(eigene_liegenschaften(eigentuemer).values_list('pk', flat=True))
    if not ids:
        return {}
    typ = dict(Buchungskonto.objects.filter(typ__in=('ertrag', 'aufwand')).values_list('pk', 'typ'))
    zeilen = (Buchung.objects.filter(liegenschaft_id__in=ids).exclude(abschluss_buchungen_q())
              .order_by()
              .values('liegenschaft_id', 'soll_konto_id', 'haben_konto_id', jahr=ExtractYear('datum'))
              .annotate(t=Sum('betrag')))
    out = defaultdict(lambda: defaultdict(lambda: [NULL, NULL]))
    for z in zeilen:
        summe = out[z['jahr']][z['liegenschaft_id']]
        t = z['t'] or NULL
        if typ.get(z['haben_konto_id']) == 'ertrag':
            summe[0] += t
        if typ.get(z['soll_konto_id']) == 'ertrag':
            summe[0] -= t
        if typ.get(z['soll_konto_id']) == 'aufwand':
            summe[1] += t
        if typ.get(z['haben_konto_id']) == 'aufwand':
            summe[1] -= t
    return {jahr: dict(je_lg) for jahr, je_lg in out.items()}


def abrechnung_jahr(eigentuemer, jahr, ergebnis=None):
    """Zeilen und Summen einer Jahresabrechnung — die Form, die `generate_mandat_abrechnung_pdf` erwartet.

    Je eigene Liegenschaft eine Zeile (auch ohne Bewegung, wie die Abrechnung der Verwaltung).
    Rückgabe: `(zeilen, totals, von, bis)`."""
    ergebnis = ergebnis if ergebnis is not None else ergebnis_je_jahr(eigentuemer)
    je_lg = ergebnis.get(jahr, {})
    zeilen = []
    ertrag = aufwand = NULL
    for lg in eigene_liegenschaften(eigentuemer):
        e, a = je_lg.get(lg.pk, (NULL, NULL))
        zeilen.append({'lg': lg, 'ertrag': e, 'aufwand': a, 'saldo': e - a})
        ertrag += e
        aufwand += a
    return (zeilen, {'ertrag': ertrag, 'aufwand': aufwand, 'saldo': ertrag - aufwand},
            date(jahr, 1, 1), date(jahr, 12, 31))


def konto_stand(eigentuemer, ergebnis=None):
    """Kontokorrent in einer Zahl: Ergebnis aller Jahre abzüglich verbuchter Auszahlungen.

    `guthaben` ist die Sollbasis des Kontokorrents (wie `kontokorrent()['offen']`),
    NICHT das, was die Bank heute auszahlen kann — das entscheidet die Verwaltung."""
    from finance.models import EigentuemerAuszahlung
    ergebnis = ergebnis if ergebnis is not None else ergebnis_je_jahr(eigentuemer)
    ertrag = sum((e for je_lg in ergebnis.values() for e, _a in je_lg.values()), NULL)
    aufwand = sum((a for je_lg in ergebnis.values() for _e, a in je_lg.values()), NULL)
    ausz = list(EigentuemerAuszahlung.objects.filter(eigentuemer=eigentuemer, status='verbucht')
                .order_by('-datum', '-id'))
    ausbezahlt = sum((a.betrag for a in ausz), NULL)
    return {'ertrag': ertrag, 'aufwand': aufwand, 'ergebnis': ertrag - aufwand,
            'ausbezahlt': ausbezahlt, 'guthaben': ertrag - aufwand - ausbezahlt,
            'letzte_auszahlung': ausz[0] if ausz else None}


def auszahlungen(eigentuemer):
    """Alle Auszahlungen an diesen Eigentümer, neueste zuerst (auch stornierte, als solche)."""
    from finance.models import EigentuemerAuszahlung
    return list(EigentuemerAuszahlung.objects.filter(eigentuemer=eigentuemer)
                .select_related('konto').order_by('-datum', '-id'))


def jahre_mit_daten(eigentuemer, ergebnis=None, heute=None):
    """Jahre für die Abrechnungsliste: das laufende, die fünf davor und jedes Jahr mit Buchungen."""
    heute = heute or datum_heute()
    ergebnis = ergebnis if ergebnis is not None else ergebnis_je_jahr(eigentuemer)
    jahre = set(range(heute.year - 5, heute.year + 1)) | {j for j in ergebnis if j and j <= heute.year}
    return sorted(jahre, reverse=True)


# ---------------------------------------------------------------------------
# Übersicht
# ---------------------------------------------------------------------------

def uebersicht(eigentuemer, heute=None):
    """Alle Kennzahlen der Startseite — leerer Bestand ergibt Nullen, nie einen Fehler."""
    heute = heute or datum_heute()
    karten = liegenschaften_karten(eigentuemer, heute)
    aktiv = [k for k in karten if k['archiviert'] is None]
    ergebnis = ergebnis_je_jahr(eigentuemer)
    stand = konto_stand(eigentuemer, ergebnis)
    objekte = sum(k['objekte'] for k in aktiv)
    leer = sum(k['leer'] for k in aktiv)
    soll_monat = sum((k['soll_monat'] for k in aktiv), NULL)
    gebucht = sum((e for e, _a in ergebnis.get(heute.year, {}).values()), NULL)
    return {
        'karten': karten, 'aktive': len(aktiv), 'archivierte': len(karten) - len(aktiv),
        'objekte': objekte, 'leer': leer, 'belegt': objekte - leer,
        'leerquote': (Decimal(leer) / Decimal(objekte) * 100) if objekte else NULL,
        'soll_monat': soll_monat, 'soll_jahr': soll_monat * 12, 'gebucht_jahr': gebucht,
        'offen': sum((k['offen'] for k in karten), NULL),
        'ueberfaellig': sum((k['ueberfaellig'] for k in karten), NULL),
        'konto': stand, 'jahr': heute.year,
    }


# ---------------------------------------------------------------------------
# Dokumente
# ---------------------------------------------------------------------------

def sichtbare_dokumente(eigentuemer):
    """Dokumente der eigenen Liegenschaften und Objekte, die die Verwaltung freigegeben hat.

    Nicht freigegebene (intern), archivierte und Dateilose erscheinen nicht. Das ist
    zugleich die Menge, aus der ein Download einzig bedient wird."""
    from core.services.archiv import ausblenden
    from portfolio.models import Dokument
    lg_ids = list(eigene_liegenschaften(eigentuemer).values_list('pk', flat=True))
    qs = (Dokument.objects.filter(im_portal_sichtbar=True)
          .filter(Q(liegenschaft_id__in=lg_ids) | Q(einheit__liegenschaft_id__in=lg_ids))
          .exclude(datei='')
          .select_related('liegenschaft', 'einheit__liegenschaft')
          .order_by('-datum', '-id'))
    return ausblenden(qs)


# ---------------------------------------------------------------------------
# Mitteilungen an die Verwaltung
# ---------------------------------------------------------------------------

class AnfrageFehler(ValueError):
    """Die Anfrage ist unvollständig; `str(e)` ist für den Eigentümer bestimmt."""


def anfrage_senden(eigentuemer, benutzer, *, liegenschaft_pk, art, betreff, text):
    """Legt die Anfrage als Pendenz der Verwaltung an und benachrichtigt sie per E-Mail.

    Bestehender Weg: dieselbe Pendenz wie bei der Anfrage eines Stockwerkeigentümers
    (`stweg.anfragen`), dieselben Empfänger (`verwaltung_empfaenger`: betreuende Person,
    sonst Adresse der Verwaltung). Die Pendenz ist gespeichert, bevor die Mail rausgeht —
    scheitert die Mail, geht die Anfrage nicht verloren."""
    from core.models import Pendenz
    betreff = ' '.join((betreff or '').split())
    text = (text or '').strip()
    if mandat_status(eigentuemer) is not None:
        raise AnfrageFehler(gettext('Das Mandat ist beendet. Bitte wenden Sie sich direkt an die Verwaltung.'))
    if not betreff:
        raise AnfrageFehler(gettext('Bitte einen Betreff angeben.'))
    if len(betreff) > BETREFF_MAX:
        raise AnfrageFehler(gettext('Der Betreff ist zu lang (höchstens %(n)s Zeichen).') % {'n': BETREFF_MAX})
    if not text:
        raise AnfrageFehler(gettext('Bitte Ihre Nachricht eingeben.'))
    if len(text) > TEXT_MAX:
        raise AnfrageFehler(gettext('Die Nachricht ist zu lang (höchstens %(n)s Zeichen).') % {'n': TEXT_MAX})
    if art not in dict(ANFRAGE_ARTEN):
        raise AnfrageFehler(gettext('Bitte die Art der Anfrage wählen.'))
    from core.utils.parameter import id_param
    lg = (eigene_liegenschaften(eigentuemer).exclude(status='archiviert')
          .filter(pk=id_param(liegenschaft_pk)).first())
    if lg is None:
        raise AnfrageFehler(gettext('Bitte eine Ihrer Liegenschaften wählen.'))
    with translation.override('de'):
        art_de = str(dict(ANFRAGE_ARTEN)[art])
    pendenz = Pendenz.objects.create(
        liegenschaft=lg, kategorie='aufgabe',
        titel=f'Eigentümeranfrage ({art_de}): {betreff}'[:200],
        beschreibung=f'{eigentuemer.firma_oder_name}, {lg.strasse}, {lg.ort}\n\n{text}',
        quelle=f'{ANFRAGE_QUELLE}{eigentuemer.pk}', erstellt_von=benutzer)
    _verwaltung_benachrichtigen(pendenz, eigentuemer, lg, art_de, betreff, text)
    return pendenz


def _verwaltung_benachrichtigen(pendenz, eigentuemer, lg, art, betreff, text):
    from django.core.mail import send_mail
    from stweg.anfragen import verwaltung_empfaenger
    empfaenger = verwaltung_empfaenger(lg)
    if not empfaenger:
        logger.warning('Eigentümeranfrage %s: keine Empfängeradresse — sie steht nur in den Pendenzen.',
                       pendenz.pk)
        return False
    try:
        send_mail(f'Eigentümeranfrage: {betreff}'[:200],
                  f'{eigentuemer.firma_oder_name} ({lg.strasse}, {lg.ort}) — {art}\n\n{text}',
                  None, empfaenger, fail_silently=False)
    except Exception:                                                   # noqa: BLE001
        logger.warning('Mail zur Eigentümeranfrage %s fehlgeschlagen', pendenz.pk, exc_info=True)
        return False
    return True


def meine_anfragen(eigentuemer):
    """Die eigenen Anfragen aus dem Portal, neueste zuerst; `erledigt` setzt die Verwaltung."""
    from core.models import Pendenz
    return list(Pendenz.objects.filter(quelle=f'{ANFRAGE_QUELLE}{eigentuemer.pk}')
                .select_related('liegenschaft').order_by('-erstellt_am', '-id')[:50])
