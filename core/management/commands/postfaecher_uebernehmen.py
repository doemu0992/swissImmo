"""Die alten IMAP-Umgebungsvariablen nachträglich in Postfächer übernehmen.

Wird gebraucht, wenn `IMAP_SCHLUESSEL` beim Deploy noch nicht gesetzt war: Die
Migration 0014 hat die Übernahme dann übersprungen, und eine bereits
angewendete Migration läuft nicht noch einmal.

    python manage.py postfaecher_uebernehmen

Wiederholbar — ein bestehendes Postfach wird nie überschrieben.
"""
from django.core.management.base import BaseCommand

from core.models import Postfach
from core.services.geheimnis import UMGEBUNGSNAME, schluessel_vorhanden
from core.services.postfach_uebernahme import uebernehmen
from crm.models import Organisation


class Command(BaseCommand):
    help = 'Übernimmt RECHNUNGS_IMAP_* und EMAIL_REPLY_* in Postfächer (wiederholbar).'

    def handle(self, *args, **options):
        if not schluessel_vorhanden():
            # Vor der Arbeit prüfen und mit Exitcode enden: So sieht ein
            # Scheduler den Fehlschlag, statt eine beruhigende Ausgabe zu
            # bekommen, in der die Übernahme still übersprungen wurde.
            self.stderr.write(self.style.ERROR(
                f'{UMGEBUNGSNAME} ist nicht gesetzt — ohne Schlüssel lassen sich die '
                'Zugangsdaten nicht verschlüsselt ablegen.'))
            self.stderr.write(
                'Erzeugen mit:\n'
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"\n'
                f'als {UMGEBUNGSNAME}=… in die .env, dann diesen Befehl erneut aufrufen.')
            raise SystemExit(1)

        # `alle_organisationen`: Der Befehl läuft ohne Mandantenkontext, und
        # die Übernahme betrifft ohnehin den ganzen Bestand.
        angelegt = uebernehmen(_OhneFilter(Postfach), Organisation, melden=self.stdout.write)
        if angelegt:
            self.stdout.write(self.style.SUCCESS(f'{angelegt} Postfach/Postfächer angelegt.'))
        else:
            self.stdout.write('Nichts zu tun.')


class _OhneFilter:
    """Reicht `Postfach` durch, aber mit `alle_organisationen` als `objects`.

    Die Übernahme wird von der Migration mit einem **historischen** Modell
    aufgerufen, dessen `objects` ungefiltert ist. Damit hier dieselbe Funktion
    dieselbe Sicht bekommt, wird der übergreifende Manager untergeschoben —
    statt in der gemeinsamen Funktion eine Fallunterscheidung zu führen, die
    man beim Lesen erst verstehen muss.
    """

    def __init__(self, modell):
        self._modell = modell
        self.objects = modell.alle_organisationen
