"""Setzt/erstellt deterministisch den Mieterportal-Zugang eines Mieters.

Verwendung (PythonAnywhere-Konsole, im Projektordner):

    python manage.py mieter_zugang --email doemugerber@gmail.com --passwort MeinPW123
    python manage.py mieter_zugang --mieter-id 42 --passwort MeinPW123
    python manage.py mieter_zugang --email x@y.ch                # zeigt nur den Status

Stellt sicher, dass der Mieter GENAU EIN aktives Login-Konto hat, setzt das
angegebene Passwort und gibt den exakten Benutzernamen aus.
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Mieterportal-Zugang eines Mieters erstellen/reparieren und Passwort setzen."

    def add_arguments(self, parser):
        parser.add_argument('--email', help='E-Mail des Mieters (aus dem Mieter-Datensatz)')
        parser.add_argument('--mieter-id', type=int, help='ID des Mieters')
        parser.add_argument('--passwort', help='Neues Passwort (wenn weggelassen: nur Status)')

    def handle(self, *args, **opts):
        from crm.models import Mieter

        User = get_user_model()

        m = None
        if opts.get('mieter_id'):
            m = Mieter.objects.filter(id=opts['mieter_id']).first()
        elif opts.get('email'):
            m = Mieter.objects.filter(email__iexact=opts['email'].strip()).first()
        else:
            raise CommandError("Bitte --email oder --mieter-id angeben.")
        if not m:
            raise CommandError("Kein Mieter gefunden.")

        self.stdout.write(f"Mieter: {m.display_name} (ID {m.id}, E-Mail: {m.email or '—'})")

        u = getattr(m, 'benutzer', None)
        if u is None:
            # E-Mail-Kollision auflösen: eindeutigen Benutzernamen finden
            basis = (m.email or f"mieter{m.id}").strip().lower()
            username = basis
            i = 1
            while User.objects.filter(username=username).exists():
                username = f"{basis}.{i}"
                i += 1
            u = User.objects.create_user(username=username, email=m.email or '')
            m.benutzer = u
            m.save(update_fields=['benutzer'])
            self.stdout.write(self.style.SUCCESS(f"Neues Login-Konto angelegt: {username}"))
        else:
            self.stdout.write(f"Vorhandenes Login-Konto: {u.username} (aktiv: {u.is_active})")

        # Konto immer aktiv schalten
        if not u.is_active:
            u.is_active = True
            u.save(update_fields=['is_active'])
            self.stdout.write(self.style.WARNING("Konto war inaktiv → jetzt aktiviert."))

        pw = opts.get('passwort')
        if pw:
            u.set_password(pw)
            u.save()
            # Verifikation
            ok = User.objects.get(pk=u.pk).check_password(pw)
            self.stdout.write(self.style.SUCCESS(
                f"Passwort gesetzt. Verifikation: {'OK' if ok else 'FEHLGESCHLAGEN'}"))
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("── Zugangsdaten ──"))
            self.stdout.write(self.style.SUCCESS(f"  Login-Seite:  /login/"))
            self.stdout.write(self.style.SUCCESS(f"  Benutzername: {u.username}"))
            self.stdout.write(self.style.SUCCESS(f"  Passwort:     {pw}"))
        else:
            self.stdout.write("Kein --passwort angegeben → Passwort unverändert.")

        # Warnung bei verwaisten Konten mit gleicher Basis
        basis = (m.email or '').strip().lower()
        if basis:
            verwandte = User.objects.filter(username__istartswith=basis).exclude(pk=u.pk)
            if verwandte.exists():
                namen = ', '.join(f"{x.username}(aktiv={x.is_active})" for x in verwandte[:10])
                self.stdout.write(self.style.WARNING(
                    f"Hinweis: weitere Konten mit ähnlichem Namen existieren: {namen}"))
