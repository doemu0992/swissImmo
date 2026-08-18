"""Der IMAP-Abruf — einmal, für beide Eingangs-Befehle.

Vorher stand die Verbindungslogik zweimal im Bestand, in
`fetch_rechnungen.check_mails` und `fetch_replies.check_emails`, und die beiden
Fassungen waren nicht gleich: Die eine schloss die Verbindung in einem
`finally`, die andere nur auf dem glücklichen Pfad; die eine las den Server aus
der Umgebung, die andere hatte ihn fest im Code
(`fetch_replies.py:104`, `lx37.hoststar.hosting`).

DIE REGEL, DIE HIER DURCHGESETZT WIRD

**Kein stiller Rückfall.** Hat eine Verwaltung kein eingerichtetes Postfach,
wird sie übersprungen — und zwar sichtbar. Der gefährliche Ausgang wäre der
andere: ein Rückfall auf die alten Umgebungsvariablen. Dann holte Verwaltung B
aus dem Postfach von A, und niemandem fiele es auf, weil eine eingehende
Rechnung nun einmal von aussen kommt.

WARUM DIE MAILS ERST NACH ERFOLGREICHER VERARBEITUNG GELESEN WERDEN

Gesucht wird mit `UNSEEN`. Ein `FETCH (RFC822)` setzt das Gelesen-Flag am
Server als Nebenwirkung — verarbeitet die Anwendung die Mail danach nicht
(Absturz, Ausnahme im Import), ist sie **weg**, ohne je angekommen zu sein.
Deshalb wird mit `BODY.PEEK[]` geholt und `\\Seen` erst gesetzt, wenn die
Verarbeitung durch ist. Eine doppelt verarbeitete Mail ist ein sichtbarer
Fehler; eine verschluckte ist keiner.
"""
import imaplib
import logging

logger = logging.getLogger(__name__)

#: Wie lange auf den Server gewartet wird. Ohne Zeitlimit hängt ein
#: Scheduler-Lauf im Zweifel bis zum nächsten — und dann laufen zwei.
ZEITLIMIT_SEKUNDEN = 60


class AbrufFehler(Exception):
    """Verbindung, Anmeldung oder Ordner haben nicht geklappt.

    Eigene Ausnahme, damit der Aufrufer sie am Postfach vermerken kann, statt
    sie mit einem Fehler aus der Verarbeitung einer einzelnen Mail zu
    verwechseln. Das eine heisst «Postfach falsch eingerichtet», das andere
    «diese eine Mail war kaputt».
    """


def verbinden(postfach):
    """Angemeldete IMAP-Verbindung für dieses Postfach.

    Wirft `AbrufFehler` mit einer Meldung, die im Fehlerprotokoll des
    Postfachs stehen kann und dort verständlich ist — `imaplib.error` allein
    hilft der Verwalterin nicht weiter.
    """
    if postfach.verfahren == postfach.VERFAHREN_OAUTH2:
        # Bewusst noch nicht gebaut (Schnitt 3). Wichtig ist, dass hier eine
        # klare Meldung steht und nicht etwa still auf das Passwortverfahren
        # zurückgefallen wird — dort ist gar keines hinterlegt.
        raise AbrufFehler(
            'OAuth2 ist für dieses Postfach eingestellt, der Abruf dafür ist '
            'aber noch nicht freigeschaltet. Bis dahin Benutzername und '
            'Passwort verwenden.')

    if not postfach.ist_einsatzbereit:
        raise AbrufFehler('Postfach ist nicht vollständig eingerichtet '
                          '(Server, Benutzername und Passwort werden gebraucht).')

    from core.services.geheimnis import GeheimtextKaputt, SchluesselFehlt

    try:
        passwort = postfach.passwort
    except (SchluesselFehlt, GeheimtextKaputt) as fehler:
        raise AbrufFehler(str(fehler)) from fehler

    try:
        verbindung = imaplib.IMAP4_SSL(postfach.server, postfach.port,
                                       timeout=ZEITLIMIT_SEKUNDEN)
    except Exception as fehler:                                # noqa: BLE001
        raise AbrufFehler(f'Keine Verbindung zu {postfach.server}:{postfach.port} '
                          f'— {fehler}') from fehler

    try:
        verbindung.login(postfach.benutzer, passwort)
    except imaplib.IMAP4.error as fehler:
        _schliessen(verbindung)
        # Der häufigste Fall im Betrieb, und der, bei dem die generische
        # Meldung am meisten Zeit kostet: Gmail und Microsoft 365 lehnen das
        # normale Kontopasswort ab.
        raise AbrufFehler(
            f'Anmeldung als {postfach.benutzer} abgelehnt ({fehler}). '
            'Bei Gmail wird ein App-Passwort gebraucht, bei Microsoft 365 '
            'OAuth2 — das normale Kontopasswort wird dort nicht akzeptiert.'
        ) from fehler

    try:
        status, _ = verbindung.select(postfach.ordner or 'INBOX')
        if status != 'OK':
            raise AbrufFehler(f'Ordner «{postfach.ordner}» nicht gefunden.')
    except AbrufFehler:
        _schliessen(verbindung)
        raise
    except Exception as fehler:                                # noqa: BLE001
        _schliessen(verbindung)
        raise AbrufFehler(f'Ordner «{postfach.ordner}» liess sich nicht öffnen '
                          f'— {fehler}') from fehler
    return verbindung


def hole_ungelesene(postfach, verarbeiten, ausgabe=None):
    """Alle ungelesenen Mails holen und einzeln `verarbeiten(rohbytes)` geben.

    Gibt `(verarbeitet, fehlgeschlagen)` zurück. Ein Fehler in einer Mail
    beendet den Lauf NICHT — sonst blockierte eine einzige kaputte Nachricht
    den gesamten Eingang, und zwar so lange, bis jemand sie von Hand löscht.
    """
    def sagen(text):
        if ausgabe is not None:
            ausgabe.write(text)

    verbindung = verbinden(postfach)
    verarbeitet = fehlgeschlagen = 0
    try:
        status, nachrichten = verbindung.search(None, 'UNSEEN')
        if status != 'OK':
            raise AbrufFehler('Die Suche nach ungelesenen Mails schlug fehl.')
        ids = nachrichten[0].split()
        if not ids:
            sagen('   (verbunden, keine neuen Mails)')
            return 0, 0
        sagen(f'   {len(ids)} neue Nachricht(en)')

        for kennung in ids:
            try:
                # PEEK: Das Gelesen-Flag wird unten von Hand gesetzt — siehe
                # Kopf dieser Datei.
                status, daten = verbindung.fetch(kennung, '(BODY.PEEK[])')
                if status != 'OK':
                    raise AbrufFehler('Die Mail liess sich nicht abholen.')
                roh = next((teil[1] for teil in daten if isinstance(teil, tuple)), None)
                if roh is None:
                    raise AbrufFehler('Die Antwort des Servers enthielt keine Mail.')
                verarbeiten(roh)
            except Exception as fehler:                        # noqa: BLE001
                fehlgeschlagen += 1
                logger.exception('Postfach %s: Mail %s fehlgeschlagen', postfach.pk, kennung)
                sagen(f'   FEHLER bei einer Mail: {fehler}')
                continue
            verarbeitet += 1
            try:
                verbindung.store(kennung, '+FLAGS', '\\Seen')
            except Exception:                                  # noqa: BLE001
                # Verarbeitet ist verarbeitet. Bleibt das Flag aus, kommt die
                # Mail beim nächsten Lauf noch einmal — unschön, aber harmlos
                # gegenüber der Alternative, den ganzen Lauf abzubrechen.
                logger.warning('Postfach %s: \\Seen liess sich nicht setzen', postfach.pk)
        return verarbeitet, fehlgeschlagen
    finally:
        _schliessen(verbindung)


def _schliessen(verbindung):
    """Verbindung schliessen, ohne dass ein Fehler dabei den Lauf kippt.

    Bewusst zweistufig und bewusst mit `debug`-Protokoll statt stillem `pass`:
    Ein Server, der beim Abmelden zickt, ist eine Randnotiz — aber eine, die
    man im Log finden können muss, wenn man sie sucht.
    """
    for schritt in ('close', 'logout'):
        try:
            getattr(verbindung, schritt)()
        except Exception:                                      # noqa: BLE001
            logger.debug('IMAP-%s fehlgeschlagen', schritt, exc_info=True)


def postfaecher_fuer(zweck):
    """Alle einsatzbereiten Postfächer dieses Zwecks, über alle Verwaltungen.

    Absichtlich `alle_organisationen`: Der Aufrufer steht ausserhalb jedes
    Mandantenkontexts — er ist es ja, der ihn gleich setzt. Mit `objects`
    fände er nichts und würfe stattdessen.
    """
    from core.models import Postfach

    return (Postfach.alle_organisationen
            .filter(zweck=zweck, aktiv=True)
            .select_related('organisation')
            .order_by('organisation_id'))
