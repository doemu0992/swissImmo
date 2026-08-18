"""Die alten Umgebungsvariablen in Postfächer übernehmen — wiederholbar.

WARUM NICHT NUR IN DER MIGRATION

Die Migration läuft **einmal**, im Deploy, und zwar genau dann, wenn der Code
ausgerollt wird. Steht `IMAP_SCHLUESSEL` zu diesem Zeitpunkt noch nicht in der
`.env`, überspringt sie die Übernahme — richtig so, denn ein abgebrochenes
`migrate` nähme die ganze Anwendung vom Netz. Nur: Danach ist der Zug abgefahren.
Ein zweites `migrate` führt eine bereits angewendete Migration nicht erneut aus.

Damit hinge die Übernahme an einer Reihenfolge, die jemand einhalten muss —
Schlüssel setzen, DANN deployen. Genau die Sorte Bedingung, die irgendwann
jemand nicht einhält, und dann steht der Mail-Eingang still, ohne dass klar
ist, wie man ihn zurückbekommt.

Deshalb liegt die Arbeit hier und wird von zwei Seiten aufgerufen: von der
Migration 0014 und vom Befehl `postfaecher_uebernehmen`. Die Reihenfolge ist
damit egal — wer den Schlüssel später setzt, ruft den Befehl nach.

Die Funktion ist **wiederholbar**: Ein bestehendes Postfach wird nie
überschrieben. Zweimal aufrufen ändert nichts.
"""
import os

#: Der Wert, der bis 18.08.2026 in `fetch_replies.py:104` fest verdrahtet war.
ALTER_FESTER_SERVER = 'lx37.hoststar.hosting'


def quellen_aus_umgebung():
    """Die beiden alten Konfigurationen als `(zweck, benutzer, passwort, server)`.

    Zwei Quellen, nicht eine — der Auftrag nannte nur die erste:

        fetch_rechnungen   RECHNUNGS_IMAP_USER / _PASSWORD / _HOST
        fetch_replies      EMAIL_REPLY_USER / EMAIL_REPLY_PASSWORD
                           Server stand dort fest im Code.
    """
    return [
        ('rechnungen',
         os.getenv('RECHNUNGS_IMAP_USER', ''),
         os.getenv('RECHNUNGS_IMAP_PASSWORD', ''),
         os.getenv('RECHNUNGS_IMAP_HOST', '') or ALTER_FESTER_SERVER),
        ('antworten',
         os.getenv('EMAIL_REPLY_USER', ''),
         os.getenv('EMAIL_REPLY_PASSWORD', ''),
         ALTER_FESTER_SERVER),
    ]


def uebernehmen(Postfach, Organisation, melden=print):
    """Fehlende Postfächer aus der Umgebung anlegen. Gibt die Anzahl zurück.

    `Postfach` und `Organisation` werden übergeben, weil die Migration mit
    **historischen** Modellen arbeitet (`apps.get_model`) — die kennen weder
    die eigenen Manager noch die `passwort`-Eigenschaft. Deshalb wird hier
    ausschliesslich mit `passwort_geheim` und dem einfachen Manager gearbeitet.

    Wirft nie. Fehlt der Schlüssel oder fehlen Zugangsdaten, wird gemeldet und
    übersprungen — siehe Kopf.
    """
    from core.services.geheimnis import SchluesselFehlt, verschluesseln

    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        melden('  · Keine Organisation vorhanden — nichts zu übernehmen.')
        return 0

    angelegt = 0
    for zweck, benutzer, passwort, server in quellen_aus_umgebung():
        if not benutzer or not passwort:
            melden(f'  · {zweck}: keine Zugangsdaten in der Umgebung — übersprungen. '
                   'In den Einstellungen von Hand einrichten.')
            continue
        if Postfach.objects.filter(organisation=organisation, zweck=zweck).exists():
            melden(f'  · {zweck}: Postfach besteht bereits — unverändert gelassen.')
            continue
        try:
            geheim = verschluesseln(passwort)
        except SchluesselFehlt as fehler:
            melden(f'  ! {zweck}: {fehler}')
            melden('    Übersprungen. Nach dem Setzen des Schlüssels nachholen mit:')
            melden('      python manage.py postfaecher_uebernehmen')
            continue
        Postfach.objects.create(
            organisation=organisation, zweck=zweck, verfahren='passwort',
            server=server, port=993, benutzer=benutzer, ordner='INBOX',
            passwort_geheim=geheim, aktiv=True)
        angelegt += 1
        melden(f'  + {zweck}: Postfach für «{organisation.firma}» angelegt ({benutzer}).')
    return angelegt
