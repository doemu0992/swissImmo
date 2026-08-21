"""Befunde je Schadenmeldung — was an ihr hängt.

WARUM

Der Bestand am 21.08.2026 (Bildschirmfoto): Drei Kacheln übereinander, jede
einen halben Bildschirm hoch, jede mit einer Null. «0 Offen», «0 In
Bearbeitung», «0 Total angezeigt». Danach sieben Filterchips über drei Zeilen
und ein zweites Suchfeld. Erst darunter — ausserhalb des Bildschirms — hätte
die Arbeit begonnen.

Drei Einwände:

1. «Total angezeigt» ist keine Kennzahl. Es zählt, was der eigene Filter
   übriggelassen hat, und sagt über den Bestand nichts aus.
2. Die sieben Chips bilden die STATUSTABELLE ab, nicht die Arbeit. «Neu» und
   «In Bearbeitung» sind Systemzustände; niemand beginnt den Tag mit «zeig mir
   alle in Bearbeitung».
3. Sortiert wurde nach `-erstellt_am`. Der Wasserschaden von heute Morgen
   steht damit über der Meldung, die seit sechs Wochen ungelesen liegt.

Grundentscheidung G9: **«Was fehlt ist wichtiger als was da ist.»**

DAS VERSPRECHEN IM UNTERTITEL — UND WIE ES GEMESSEN WIRD

Die Seite trägt den Satz «Meldung → Auftrag → automatische Info an Melder».
Das ist eine Zusage an den Mieter. Ob sie eingehalten wurde, stand nirgends:
Eine Meldung ohne einzige ausgehende Nachricht sah genauso aus wie eine, bei
der alles lief.

**Woran man das erkennt, ist der heikelste Punkt dieser Datei.** Ein erster
Entwurf prüfte den Nachrichten-TYP und liess `antwort_senden`, `email`,
`mail_antwort` und `system` als Echo gelten. Zwei davon sind falsch, und der
Fehler geht in die gefährliche Richtung — er bringt den Befund zum Schweigen:

* **`mail_antwort` ist EINGEHEND.** Diesen Typ erzeugen `core/views/webhooks.py`
  und `fetch_replies.py`, wenn der MIETER auf die Ticket-Mail antwortet. Als
  Echo gewertet, schwiege der Befund ausgerechnet dann, wenn jemand geschrieben
  hat und niemand geantwortet — genau der Fall, für den es ihn gibt.
* **`system` ist überwiegend INTERN.** «Auftrag an X vergeben» und «Status
  geändert» tragen `is_intern=True` und erreichen den Mieter nie. Da eine
  Auftragsvergabe IMMER eine solche Notiz schreibt, hätte praktisch jede
  Meldung mit Handwerker als «Melder informiert» gegolten.

Massgeblich ist deshalb, was den Mieter TATSÄCHLICH erreicht — und diese
Definition gibt es im Haus bereits: Das Mieterportal zeigt den Verlauf als
`t.nachrichten.exclude(is_intern=True)` (`core/views/portal.py`). Hier gilt
dasselbe, plus die zwei Systemnotizen, die eine nachweislich versandte Mail
protokollieren (sie entstehen nur nach erfolgreichem Versand).
"""
import logging
from datetime import timedelta

from django.utils import timezone

log = logging.getLogger(__name__)

#: Ab wann eine ungelesene Meldung nicht mehr «heute reingekommen» ist.
#: Ein Arbeitstag ist die Kulanz, die man einer Verwaltung zugesteht.
UNGELESEN_WARN_TAGE = 1
UNGELESEN_CRIT_TAGE = 3

#: Ab wann ein Schaden ohne Handwerkerauftrag erklärungsbedürftig wird.
OHNE_AUFTRAG_TAGE = 3

#: Ab wann eine ausstehende Eigentümerfreigabe zum Problem wird. Eine Woche
#: ohne Antwort heisst in der Praxis: Es wurde vergessen, nicht überlegt.
FREIGABE_CRIT_TAGE = 7

#: Ab wann «wartet auf Dritte» kein Wartezustand mehr ist, sondern ein
#: Liegenbleiber. Wer seit drei Wochen auf den Handwerker wartet, wartet
#: nicht — er wurde vergessen.
LIEGT_TAGE = 21

#: Ab wann das ausbleibende Echo an den Melder ein Befund ist.
OHNE_ECHO_TAGE = 2

STUFEN_RANG = {'crit': 0, 'warn': 1, 'good': 2}

#: Hohe Priorität hebt eine Meldung innerhalb ihrer Befundstufe nach oben,
#: begründet aber für sich allein keinen Befund: Ein Notfall, der heute
#: gemeldet und heute beauftragt wurde, läuft korrekt.
PRIO_RANG = {'hoch': 0, 'mittel': 1, 'tief': 2}

WARTEZUSTAENDE = ('warte_auf_mieter', 'warte_auf_handwerker')

#: Die zwei Systemnotizen, die einen NACHGEWIESENEN Versand an den Melder
#: protokollieren — beide entstehen ausschliesslich nach erfolgreichem
#: `send_ticket_email` (`core/views/fw/schaeden.py`, «Melder automatisch
#: informiert (…)» und «Melder über Status '…' informiert»).
#:
#: Ein Textabgleich ist zerbrechlich, und das ist hier bewusst sichtbar: Der
#: Wortlaut wird an genau zwei Stellen erzeugt, und
#: `test_schadensliste.py::ProtokollWortlautTests` hält beide fest. Ändert
#: jemand die Formulierung, wird der Test rot — statt dass der Befund
#: stillschweigend zu oft meldet.
ECHO_PROTOKOLL_PRAEFIX = 'Melder '


def _tage(seit, stichtag):
    """Tage zwischen einem Zeitpunkt und dem Stichtag, robust gegen Zeitzonen."""
    if seit is None:
        return None
    wert = timezone.localdate(seit) if timezone.is_aware(seit) else seit.date()
    return (stichtag - wert).days


def hat_echo(meldung):
    """Ist an den Melder je etwas hinausgegangen?

    Zwei Wege zählen, und nur diese zwei:

    1. Eine Nachricht der Verwaltung, die NICHT intern ist. Das ist dieselbe
       Bedingung, mit der das Mieterportal entscheidet, was der Mieter sieht.
    2. Eine interne Systemnotiz, die einen erfolgreichen Mailversand an den
       Melder protokolliert (siehe `ECHO_PROTOKOLL_PRAEFIX`).

    Eine eingehende Antwort des Mieters (`mail_antwort`) zählt ausdrücklich
    NICHT — sie belegt, dass jemand geschrieben hat, nicht dass jemand
    geantwortet hat.
    """
    for n in meldung.nachrichten.all():
        if n.is_von_verwaltung and not n.is_intern:
            return True
        if n.is_intern and (n.nachricht or '').startswith(ECHO_PROTOKOLL_PRAEFIX):
            return True
    return False


def _befunde(t, stichtag):
    """Was an dieser einen Meldung hängt.

    Ein erledigter Schaden meldet nichts. Das klingt selbstverständlich, ist
    aber die Stelle, an der solche Listen üblicherweise verrauschen: Ein
    abgeschlossener Fall ohne erfasste Kosten mag buchhalterisch unschön sein
    — auf der Arbeitsfläche ist er trotzdem erledigt.
    """
    if t.status == 'erledigt':
        return []

    befunde = []
    alter = _tage(t.erstellt_am, stichtag)
    ruht_seit = _tage(t.aktualisiert_am, stichtag)

    if not t.gelesen and alter is not None and alter >= UNGELESEN_WARN_TAGE:
        stufe = 'crit' if alter >= UNGELESEN_CRIT_TAGE else 'warn'
        befunde.append({
            'stufe': stufe, 'text': 'Ungelesen',
            'titel': f'seit {alter} Tag{"en" if alter != 1 else ""}'})

    auftraege = list(t.handwerker_auftraege.all())

    # Freigabe zuerst: Wer auf die Eigentuemerfreigabe wartet, hat seine Arbeit
    # getan — «kein Auftrag» waere dort eine falsche Anklage. Die beiden Zweige
    # schliessen sich ohnehin aus (`wartet_auf_freigabe` kann nur nicht-leer
    # sein, wenn es Auftraege gibt); ein `elif` stand hier zuerst und
    # suggerierte eine Vorrangregel, die keine ist.
    wartet_auf_freigabe = [a for a in auftraege
                           if a.freigabe_status == 'ausstehend']
    if wartet_auf_freigabe:
        seit = min((_tage(a.beauftragt_am, stichtag) or 0)
                   for a in wartet_auf_freigabe)
        befunde.append({
            'stufe': 'crit' if seit >= FREIGABE_CRIT_TAGE else 'warn',
            'text': 'Freigabe ausstehend',
            'titel': f'beim Eigentümer seit {seit} Tag{"en" if seit != 1 else ""}'})
    if not auftraege and alter is not None and alter >= OHNE_AUFTRAG_TAGE:
        befunde.append({
            'stufe': 'crit', 'text': 'Kein Auftrag',
            'titel': f'seit {alter} Tagen gemeldet, kein Handwerker'})

    if t.status in WARTEZUSTAENDE and ruht_seit is not None and ruht_seit >= LIEGT_TAGE:
        wer = 'Mieter' if t.status == 'warte_auf_mieter' else 'Handwerker'
        befunde.append({
            'stufe': 'warn', 'text': f'Liegt beim {wer}',
            'titel': f'seit {ruht_seit} Tagen keine Bewegung'})

    # DAS VERSPRECHEN AUS DEM UNTERTITEL: «automatische Info an Melder».
    # Ohne Kontaktweg laesst sich nichts senden — dann ist das Schweigen keine
    # Versaeumnis, sondern eine Tatsache, und eine Ruege waere unfair.
    erreichbar = bool(t.email_melder or t.gemeldet_von_id)
    if erreichbar and alter is not None and alter >= OHNE_ECHO_TAGE and not hat_echo(t):
        befunde.append({
            'stufe': 'warn', 'text': 'Melder ohne Rückmeldung',
            'titel': f'seit {alter} Tagen keine Nachricht hinaus'})

    return befunde


def zeilen(meldungen, stichtag=None):
    """Eine Zeile je Meldung, sortiert nach Befund.

    Die Reihenfolge: Befundstufe, dann Priorität, dann Alter — die älteste
    zuerst. Vorher stand `-erstellt_am` allein, und damit stand der Schaden von
    heute Morgen über dem, der seit sechs Wochen liegt.
    """
    stichtag = stichtag or timezone.localdate()

    ergebnis = []
    for t in meldungen:
        try:
            befunde = _befunde(t, stichtag)
        except Exception:
            # Ein stiller `except` erzeugte hier eine dauerhaft ruhige Liste,
            # die aussieht wie eine Verwaltung ohne offene Schaeden (Befund P6).
            log.exception('Schadensbefunde fehlgeschlagen (Meldung %s)', t.id)
            befunde = []
        stufe = min((b['stufe'] for b in befunde),
                    key=lambda s: STUFEN_RANG.get(s, 9), default='good')
        ergebnis.append({
            't': t, 'befunde': befunde, 'stufe': stufe,
            'offen': t.status != 'erledigt',
            'wartet': t.status in WARTEZUSTAENDE,
            'alter': _tage(t.erstellt_am, stichtag),
        })

    ergebnis.sort(key=lambda z: (
        STUFEN_RANG.get(z['stufe'], 9),
        PRIO_RANG.get((z['t'].prioritaet or 'mittel').lower(), 1),
        -(z['alter'] or 0)))
    return ergebnis


def streifen(zeilenliste):
    """Vier Zahlen für den Kopf — schmal, nicht als Kachelwand.

    «Total angezeigt» ist bewusst nicht dabei: Es zählt, was der eigene Filter
    übriggelassen hat. An seine Stelle tritt die Liegezeit der ältesten offenen
    Meldung — die einzige der vier Zahlen, die eine Verwaltung im Streitfall
    erklären muss.
    """
    offen = [z for z in zeilenliste if z['offen']]
    ungelesen = [z for z in offen if not z['t'].gelesen]
    wartet = [z for z in offen if z['wartet']]
    aeltester = max((z['alter'] or 0) for z in offen) if offen else 0
    mit_befund = sum(1 for z in zeilenliste if z['befunde'])
    return {
        'offen': len(offen),
        'offen_stufe': 'warn' if offen else '',
        'ungelesen': len(ungelesen),
        'ungelesen_stufe': 'crit' if ungelesen else '',
        'wartet': len(wartet),
        'aeltester': aeltester,
        'aeltester_stufe': ('crit' if aeltester >= LIEGT_TAGE
                            else ('warn' if aeltester >= OHNE_AUFTRAG_TAGE else '')),
        'mit_befund': mit_befund,
    }
