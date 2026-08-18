"""Die heutigen Zugangsdaten aus der Umgebung in die Postfächer übernehmen.

Betrifft **eine Zeile je Zweck**, weil es genau eine Organisation gibt — das
ist der Grund, warum dieser Umbau jetzt und nicht nach der zweiten Verwaltung
kommt.

ZWEI QUELLEN, nicht eine (im Auftrag stand nur die erste):

    fetch_rechnungen   RECHNUNGS_IMAP_USER / _PASSWORD / _HOST
    fetch_replies      EMAIL_REPLY_USER / EMAIL_REPLY_PASSWORD
                       Server stand dort FEST IM CODE: lx37.hoststar.hosting

WARUM DIESE MIGRATION NIEMALS SCHEITERT

Sie läuft im Deploy, unmittelbar vor dem Reload. Ein `migrate`, das an
fehlenden Zugangsdaten oder einem noch nicht gesetzten `IMAP_SCHLUESSEL`
abbricht, legt die ganze Anwendung lahm — wegen einer Bequemlichkeit. Fehlt
etwas, wird die Übernahme deshalb übersprungen und gemeldet; das Postfach lässt
sich danach in der Oberfläche von Hand einrichten.

Die Umgebungsvariablen bleiben nach dieser Migration bestehen. Entfernt werden
sie erst, wenn der Verbindungstest in der Oberfläche grün ist — vorher wäre der
Rückweg verbaut.
"""
import os

from django.db import migrations

#: Der Wert, der bis heute in `fetch_replies.py` fest verdrahtet war.
ALTER_FESTER_SERVER = 'lx37.hoststar.hosting'


def uebernehmen(apps, schema_editor):
    from core.services.geheimnis import SchluesselFehlt, verschluesseln

    Organisation = apps.get_model('crm', 'Organisation')
    Postfach = apps.get_model('core', 'Postfach')

    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        print('  · Keine Organisation vorhanden — nichts zu übernehmen.')
        return

    quellen = [
        ('rechnungen',
         os.getenv('RECHNUNGS_IMAP_USER', ''),
         os.getenv('RECHNUNGS_IMAP_PASSWORD', ''),
         os.getenv('RECHNUNGS_IMAP_HOST', '') or ALTER_FESTER_SERVER),
        ('antworten',
         os.getenv('EMAIL_REPLY_USER', ''),
         os.getenv('EMAIL_REPLY_PASSWORD', ''),
         ALTER_FESTER_SERVER),
    ]

    for zweck, benutzer, passwort, server in quellen:
        if not benutzer or not passwort:
            print(f'  · {zweck}: keine Zugangsdaten in der Umgebung — übersprungen. '
                  'In den Einstellungen von Hand einrichten.')
            continue
        if Postfach.objects.filter(organisation=organisation, zweck=zweck).exists():
            print(f'  · {zweck}: Postfach besteht bereits — unverändert gelassen.')
            continue
        try:
            geheim = verschluesseln(passwort)
        except SchluesselFehlt as fehler:
            # NICHT werfen: siehe Kopf. Ein abgebrochenes `migrate` kostet mehr
            # als eine von Hand nachgetragene Zeile.
            print(f'  ⚠ {zweck}: {fehler}')
            print('    Übernahme übersprungen — der Zugang bleibt vorerst in der Umgebung.')
            continue
        Postfach.objects.create(
            organisation=organisation, zweck=zweck, verfahren='passwort',
            server=server, port=993, benutzer=benutzer, ordner='INBOX',
            passwort_geheim=geheim, aktiv=True)
        print(f'  ✓ {zweck}: Postfach für «{organisation.firma}» angelegt ({benutzer}).')


def zurueck(apps, schema_editor):
    """Rückwärts: die Postfächer wieder entfernen.

    Verlustfrei, solange die Umgebungsvariablen noch stehen — und genau
    deshalb werden sie erst nach dem geglückten Verbindungstest entfernt.
    """
    apps.get_model('core', 'Postfach').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0013_postfach')]
    operations = [migrations.RunPython(uebernehmen, zurueck)]
