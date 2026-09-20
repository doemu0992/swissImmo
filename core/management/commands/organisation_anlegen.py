"""Legt eine Organisation mit ihrem ersten Inhaber an.

WARUM EIN COMMAND UND KEIN ÖFFENTLICHES FORMULAR
------------------------------------------------
Entschieden am 20.09.2026, Begründung in `docs/PHASE-3-ONBOARDING.md`
Abschnitt 6.

Ein öffentliches `/registrieren/` müsste drosseln, per E-Mail bestätigen und
offene Registrierungen begrenzen — und es vergäbe über einen für jedermann
erreichbaren Weg die höchste Rolle im System (`Inhaber`). Solange Kunden
einzeln kommen, ist ein Command ehrlicher und billiger: Er lässt sich nicht
missbrauchen, weil er Zugang zum Server voraussetzt.

Er ist ausserdem die Grundlage, auf der ein Formular später aufsetzt — der
Dienst `core/services/onboarding.py` bleibt derselbe.

DIE HARTE GRENZE AUS PHASE 2 GILT WEITER
----------------------------------------
`docs/PHASE-2-ABSCHLUSS.md`: **keine zweite Organisation, bevor PostgreSQL,
der Wiederherstellungs-Probelauf und 2FA erledigt sind.** 2FA ist es
inzwischen; der PostgreSQL-Umzug nicht.

Dieser Command ist die Maschine, die zweite Organisationen erzeugt. Dass er
existiert, hebt die Grenze nicht auf — er warnt deshalb, wenn schon eine
Organisation da ist, und verlangt dann `--zweite`. Eine Warnung, die man
wegklicken kann, ist keine; eine, die eine zweite Eingabe verlangt, schon.

AUFRUF
------
    python manage.py organisation_anlegen \\
        --firma "Muster Immobilien AG" \\
        --benutzer lea --email lea@muster.ch

Ohne `--passwort` entsteht der Benutzer ohne brauchbares Passwort; er kommt
dann über «Passwort vergessen» hinein. Das ist der bessere Weg — so kennt
niemand sonst das Passwort.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Legt eine Organisation mit ihrem ersten Inhaber an.'

    def add_arguments(self, parser):
        parser.add_argument('--firma', required=True)
        parser.add_argument('--benutzer', required=True, help='Benutzername des Inhabers')
        parser.add_argument('--email', required=True)
        parser.add_argument('--passwort', default=None,
                            help='Optional. Ohne dieses Argument führt der Weg '
                                 'über «Passwort vergessen».')
        parser.add_argument('--vorname', default='')
        parser.add_argument('--nachname', default='')
        parser.add_argument('--tage', type=int, default=None,
                            help='Länge der Testphase in Tagen (Vorgabe 30). '
                                 '0 heisst: keine Testphase.')
        parser.add_argument('--zweite', action='store_true',
                            help='Bestätigt, dass eine WEITERE Organisation '
                                 'entstehen darf (siehe Modulkopf).')
        parser.add_argument('--probe', action='store_true',
                            help='Nur zeigen, was geschähe. Nichts wird angelegt.')

    def handle(self, *args, **o):
        from django.db import transaction

        from crm.models import Organisation
        from core.services.onboarding import (TESTPHASE_TAGE, OnboardingFehler,
                                              organisation_anlegen)

        vorhanden = Organisation.objects.count()
        if vorhanden and not o['zweite']:
            raise CommandError(
                f'Es gibt bereits {vorhanden} Organisation(en). '
                'Eine weitere anzulegen heisst, den Mehrmandantenbetrieb '
                'aufzunehmen — und dafür verlangt docs/PHASE-2-ABSCHLUSS.md '
                'PostgreSQL, einen Wiederherstellungs-Probelauf und 2FA. '
                'Wenn das erledigt ist: noch einmal mit --zweite.')

        tage = TESTPHASE_TAGE if o['tage'] is None else o['tage']
        tage = tage or None          # 0 -> keine Testphase

        if o['probe']:
            self.stdout.write('Probelauf — es wird nichts angelegt.')
            self.stdout.write(f"  Organisation  {o['firma']}")
            self.stdout.write(f"  Inhaber       {o['benutzer']} <{o['email']}>")
            self.stdout.write(f"  Testphase     {tage or 'keine'}"
                              + (' Tage' if tage else ''))
            self.stdout.write(f"  Bestand       {vorhanden} Organisation(en)")
            return

        try:
            # Der Dienst ist selbst atomar. Der zweite Block hier ist kein
            # Versehen, sondern die Klammer um Dienst UND Ausgabe: Bricht
            # etwas nach dem Anlegen ab, soll nichts zurückbleiben.
            with transaction.atomic():
                organisation, benutzer, neu = organisation_anlegen(
                    firma=o['firma'], benutzername=o['benutzer'], email=o['email'],
                    passwort=o['passwort'], vorname=o['vorname'],
                    nachname=o['nachname'], testphase_tage=tage)
        except OnboardingFehler as fehler:
            raise CommandError(str(fehler)) from fehler

        self.stdout.write(self.style.SUCCESS(
            f'Organisation «{organisation.firma}» angelegt (Nr. {organisation.pk}).'))
        self.stdout.write(
            f'  Inhaber: {benutzer.username}'
            + ('  (neu angelegt)' if neu else '  (bestehender Benutzer)'))
        if organisation.abo_bis:
            self.stdout.write(f'  Testphase bis {organisation.abo_bis:%d.%m.%Y}')
        if not o['passwort'] and neu:
            self.stdout.write(
                '  Kein Passwort gesetzt — der Weg führt über «Passwort vergessen».')
