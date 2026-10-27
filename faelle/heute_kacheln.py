"""Die Aufgabenkacheln der Startseite (Dashboard-Reduktion, 26.10.2026).

«Heute» beantwortet eine Frage: Was muss ich jetzt tun? Jede Kachel ist eine
Zahl, eine Zeile Bedeutung und ein Verb — und sie steht nur, wenn die Zahl
nicht null ist. Ein ruhiger Tag sieht deshalb ruhig aus.

WAS WEGGEFALLEN IST (und wo es steht)

Die Ember-Bento-Reihe zeigte sechs Karten, davon vier ohne Handlung:
Zahlungsquote als Halbkreis, Ø Verzug, Objekte nach Ort, Mieteingang der
letzten sieben Monate, dazu ein Wochenraster und drei Zahlen über dem Raster.
Geld kam dreimal vor (Zahlungseingang, Mieteingang, Lage-Streifen), Ausstände
dreimal, Termine dreimal. Die Auswertungen stehen unter /neu/berichte/ und im
Portfolio; auf der Startseite steht, was eine Handlung auslöst.

SCHWERPUNKT STATT NEUER ROLLEN

Eine Rolle «Buchhaltung» gibt es nicht, und eine neue Rolle griffe ins
Berechtigungsmodell. Der Schwerpunkt wählt nur die Kacheln:

    bewirtschaftung   Fristen, nicht zugewiesene Tickets, Posteingang, Freigaben
    buchhaltung       überfällige Rechnungen, Klärungsfälle, Läufe, Kreditoren
    uebersicht        der Kennzahlenstreifen aus `faelle/lage.py`

Ohne gespeicherte Wahl folgt er der Rolle: Inhaber und Lesezugriff sehen die
Übersicht, Verwalter und Sachbearbeiter die Bewirtschaftung.

Alle Abfragen laufen durch die Mandantenmanager (`objects`).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils.translation import gettext as _, gettext_lazy, ngettext

log = logging.getLogger(__name__)

SCHWERPUNKTE = (
    ('bewirtschaftung', gettext_lazy('Bewirtschaftung')),
    ('buchhaltung', gettext_lazy('Buchhaltung')),
    ('uebersicht', gettext_lazy('Übersicht')),
)
_GUELTIG = {k for k, _b in SCHWERPUNKTE}
_SESSION = 'startseite_schwerpunkt'

#: Reihenfolge der Dringlichkeit; die erste Kachel trägt den Ember-Akzent.
_RANG = {'crit': 0, 'warn': 1, '': 2}


def _mitgliedschaft(request):
    from crm.models import Mitgliedschaft
    organisation = getattr(request, 'organisation', None)
    if organisation is None or not request.user.is_authenticated:
        return None
    return Mitgliedschaft.objects.filter(benutzer=request.user, organisation=organisation).first()


def standard_schwerpunkt(request):
    """Der Schwerpunkt nach Rolle, wenn keiner gewählt ist."""
    from core.auth import ROLLE_SACHBEARBEITER, ROLLE_VERWALTER
    m = _mitgliedschaft(request)
    if m is not None and m.rolle in (ROLLE_VERWALTER, ROLLE_SACHBEARBEITER):
        return 'bewirtschaftung'
    if m is None and not request.user.is_superuser:
        return 'bewirtschaftung'
    return 'uebersicht'


def schwerpunkt_von(request):
    """Gewählter Schwerpunkt — aus der Mitgliedschaft, ohne sie (Superuser)
    aus der Sitzung, sonst nach Rolle."""
    m = _mitgliedschaft(request)
    gewaehlt = m.schwerpunkt if m is not None else request.session.get(_SESSION, '')
    return gewaehlt if gewaehlt in _GUELTIG else standard_schwerpunkt(request)


def schwerpunkt_setzen(request, wert):
    """Speichert die Wahl. Ein unbekannter Wert wird abgelehnt (False)."""
    if wert not in _GUELTIG:
        return False
    m = _mitgliedschaft(request)
    if m is not None:
        m.schwerpunkt = wert
        m.save(update_fields=['schwerpunkt'])
    else:
        request.session[_SESSION] = wert
    return True


def _kachel(schluessel, titel, zahl, text, knopf, ziel, ton='', betrag=None):
    return {'schluessel': schluessel, 'titel': titel, 'zahl': zahl, 'text': text,
            'knopf': knopf, 'ziel': ziel, 'ton': ton, 'betrag': betrag}


def rueckstand(heute, aktive_lg=None):
    """Überfällige Debitorenrechnungen: Anzahl und Summe."""
    from finance.models import DebitorenRechnung
    qs = (DebitorenRechnung.objects.filter(status__in=('offen', 'teilbezahlt'))
          .filter(Q(faellig_am__lt=heute) | Q(faellig_am__isnull=True, datum__lt=heute)))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    a = qs.aggregate(n=Count('id'), s=Sum('betrag'))
    return {'n': a['n'] or 0, 'summe': a['s'] or Decimal('0.00')}


def _schluessel_kachel(heute, aktive_lg):
    """Modul 2: Schlüssel, deren Rückgabefrist überschritten ist. Liegen alle
    an einer Liegenschaft, führt die Kachel direkt in deren Schliessanlage."""
    from core.services.schluessel import faellige
    ueber = list(faellige(heute, aktive_lg, nur_ueberfaellig=True)
                 .values_list('schluessel__liegenschaft_id', flat=True))
    if not ueber:
        return []
    lg_ids = set(ueber)
    ziel = (f'/neu/liegenschaften/{ueber[0]}/?tab=stammdaten#schliessanlage' if len(lg_ids) == 1
            else '/neu/schluessel/faellig/')
    return [_kachel('schluessel', _('Schlüssel'), len(ueber),
                    ngettext('Rückgabe ist überfällig', 'Rückgaben sind überfällig', len(ueber)),
                    _('Zurückfordern'), ziel, 'warn')]


def _bewirtschaftung(heute, aktive_lg, av, faellig):
    from tickets.models import SchadenMeldung
    kacheln = []
    ueber = sum(1 for e in faellig if e['tage'] < 0)
    if faellig:
        kacheln.append(_kachel(
            'vorgaenge', _('Fristen & Vorgänge'), ueber or len(faellig),
            _('überfällig') if ueber else _('heute fällig'),
            _('Erledigen'), '?ansicht=heute#h-vorrat', 'crit' if ueber else 'warn'))
    tickets = SchadenMeldung.objects.exclude(status='erledigt').filter(zugewiesen_an__isnull=True)
    if aktive_lg:
        tickets = tickets.filter(liegenschaft=aktive_lg)
    n = tickets.count()
    if n:
        kacheln.append(_kachel('tickets', _('Tickets'), n,
                               _('niemandem zugewiesen'),
                               _('Zuweisen'), '/neu/schaeden/?zustaendig=niemand', 'warn'))
    kacheln.extend(_schluessel_kachel(heute, aktive_lg))
    n = av.get('av_eingaenge_gesamt') or 0
    if n:
        kacheln.append(_kachel('posteingang', _('Posteingang'), n,
                               ngettext('Eingang nicht zugeordnet', 'Eingänge nicht zugeordnet', n),
                               _('Zuordnen'), '/neu/zulauf/'))
    n = av.get('av_freigaben_gesamt') or 0
    if n:
        kacheln.append(_kachel('freigaben', _('Freigaben'), n,
                               ngettext('wartet auf Entscheid', 'warten auf Entscheid', n),
                               _('Prüfen'), '?ansicht=ohnefrist#h-vorrat',
                               'warn' if (av.get('av_liegezeit') or 0) > 5 else ''))
    return kacheln


def _buchhaltung(heute, aktive_lg, av):
    # Ab so vielen Tagen auf dem Durchlaufkonto ist ein Klärungsfall dringend —
    # dieselbe Grenze wie im Zahlungs-Cockpit.
    from core.services.zahlungsklaerung import KLAERUNG_WARN_TAGE
    from finance.models import KreditorenRechnung, Zahlungseingang
    kacheln = []
    r = rueckstand(heute, aktive_lg)
    if r['n']:
        kacheln.append(_kachel('rueckstand', _('Überfällige Rechnungen'), r['n'],
                               ngettext('Rechnung über Fälligkeit', 'Rechnungen über Fälligkeit', r['n']),
                               _('Mahnlauf'), '/neu/mahnwesen/', 'crit', betrag=r['summe']))
    klaer = Zahlungseingang.objects.filter(status='verbucht', konto__nummer='1190')
    n = klaer.count()
    if n:
        alt = klaer.filter(datum_eingang__lte=heute - timedelta(days=KLAERUNG_WARN_TAGE)).count()
        kacheln.append(_kachel(
            'klaerung', _('Klärungsfälle'), n,
            (ngettext('%(n)s länger als %(t)s Tage ungeklärt', '%(n)s länger als %(t)s Tage ungeklärt', alt)
             % {'n': alt, 't': KLAERUNG_WARN_TAGE}) if alt
            else ngettext('Zahlung ohne Zuordnung', 'Zahlungen ohne Zuordnung', n),
            _('Klären'), '/neu/bankabgleich/?spur=klaerung', 'crit' if alt else 'warn',
            betrag=klaer.aggregate(s=Sum('betrag'))['s']))
    faellig = av.get('av_laeufe_faellig') or 0
    blockiert = av.get('av_laeufe_blockiert') or 0
    if faellig or blockiert:
        kacheln.append(_kachel(
            'laeufe', _('Läufe'), faellig + blockiert,
            (ngettext('%(n)s blockiert', '%(n)s blockiert', blockiert) % {'n': blockiert}) if blockiert
            else _('fällig, z. B. Sollstellung'),
            _('Starten'), '/neu/laeufe/', 'crit' if blockiert else 'warn'))
    kred = KreditorenRechnung.objects.filter(status='neu')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)
    a = kred.aggregate(n=Count('id'), s=Sum('betrag'))
    if a['n']:
        kacheln.append(_kachel('kreditoren', _('Eingangsrechnungen'), a['n'],
                               _('zur Freigabe'),
                               _('Freigeben'), '/neu/kreditoren/', betrag=a['s']))
    return kacheln


def kacheln(schwerpunkt, heute, aktive_lg, av, faellig):
    """Die Aufgabenkacheln eines Schwerpunkts, dringendste zuerst.

    `faellig`: die heute fälligen Vorgänge (`was_reisst`, tage ≤ 0) — schon
    gerechnet, nicht ein zweites Mal gesammelt. Für «Übersicht» leer: Dort
    steht der Kennzahlenstreifen.
    """
    try:
        if schwerpunkt == 'buchhaltung':
            liste = _buchhaltung(heute, aktive_lg, av)
        elif schwerpunkt == 'bewirtschaftung':
            liste = _bewirtschaftung(heute, aktive_lg, av, faellig)
        else:
            return []
    except Exception:
        # Eine Kachel darf die Startseite nicht kosten — der Arbeitsvorrat
        # darunter bleibt die Quelle.
        log.exception('Startseite: Aufgabenkacheln nicht ladbar')
        return []
    liste.sort(key=lambda k: _RANG.get(k['ton'], 2))
    return liste[:4]
