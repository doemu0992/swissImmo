"""Täglicher Sammellauf für PythonAnywhere Scheduled Task (einmal pro Tag):

    python manage.py taeglicher_lauf
    python manage.py taeglicher_lauf --organisation 3

Generiert Auto-Pendenzen (Fristen), aktualisiert Marktdaten (Referenzzins/LIK)
und verschickt am gewählten Wochentag das Fristen-Wochenmail — so genügt ein
einziger täglicher Scheduled Task.

ZWEI ARTEN VON TEILLÄUFEN, und sie dürfen nicht vermischt werden:

**Teile mit eigener Schleife** — `generate_auto_pendenzen`,
`update_verwaltung_rates` und `fristen_digest` gehen selbst über alle
Verwaltungen (Etappe 6.1/6.2). Sie werden hier GENAU EINMAL aufgerufen. Steckte
man sie zusätzlich in die Schleife unten, liefe jeder von ihnen n-mal über n
Verwaltungen: das Fristen-Mail käme n-fach an, und die Marktdaten würden n-mal
abgeholt.

**Teile ohne eigene Schleife** — `run_adress_umzuege` und die
Bewerbungs-Bereinigung greifen über `Mieter.objects` bzw.
`Mietbewerbung.objects` zu und brauchen darum je Verwaltung einen Kontext.

Der Aktivitätslog wird je Verwaltung geschrieben; er ist selbst Mandantendaten.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import AktivitaetsLog
from core.services.automation import generate_auto_pendenzen, run_adress_umzuege


class Command(BaseCommand):
    help = "Täglicher Lauf: Auto-Pendenzen (Fristen) + Marktdaten + wöchentl. Fristen-Mail."

    def add_arguments(self, parser):
        parser.add_argument('--horizont', type=int, default=90, help="Vorlauf in Tagen")
        parser.add_argument('--digest-weekday', type=int, default=0,
                            help="Wochentag fürs Fristen-Mail (0=Montag … 6=Sonntag, -1=nie)")
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        gemeinsam = []

        # ── Teile mit eigener Schleife: genau einmal ──────────────────────
        neu = generate_auto_pendenzen(horizont_tage=opts['horizont'], user=None)
        gemeinsam.append(f"{neu} neue Pendenz(en)")

        # Marktdaten (Referenzzins/LIK) best-effort aktualisieren
        try:
            from core.utils.market_data import update_verwaltung_rates
            update_verwaltung_rates()
            gemeinsam.append("Marktdaten aktualisiert")
        except Exception as e:
            gemeinsam.append(f"Marktdaten übersprungen ({e})")

        # Wöchentliches Fristen-Mail am gewählten Wochentag (Standard Montag)
        wd = opts['digest_weekday']
        if wd is not None and wd >= 0 and timezone.localdate().weekday() == wd:
            try:
                call_command('fristen_digest')
                gemeinsam.append("Fristen-Mail versendet")
            except Exception as e:
                gemeinsam.append(f"Fristen-Mail übersprungen ({e})")

        # ── Teile ohne eigene Schleife: je Verwaltung ─────────────────────
        _, fehler = je_organisation(
            lambda organisation: self._je_verwaltung(organisation, gemeinsam),
            auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"Täglicher Lauf: {len(fehler)} Verwaltung(en) abgebrochen — "
                               f"{', '.join(str(o) for o, _ in fehler)}.")

    def _je_verwaltung(self, organisation, gemeinsam):
        details = list(gemeinsam)

        # Fällige Adresswechsel aktivieren (aus dem GET-Lesepfad hierher verlagert)
        try:
            umz = run_adress_umzuege()
            if umz:
                details.append(f"{umz} Adresswechsel aktiviert")
        except Exception as e:
            details.append(f"Adresswechsel übersprungen ({e})")

        # Bewerbungsdossiers nach dem Vermietungsentscheid bereinigen (DSG).
        # Ausweiskopie, Lohnausweis und Betreibungsauszug von Personen, die die
        # Wohnung nicht bekommen haben, dürfen nicht liegen bleiben — sie haben
        # keinen Zweck mehr und keine Aufbewahrungspflicht.
        try:
            from core.services.bewerbung_aufbewahrung import bereinige
            n_dok, n_anon = bereinige(timezone.localdate(), anwenden=True)
            if n_dok or n_anon:
                details.append(f"{n_dok} Bewerbungsdossier(s) bereinigt, {n_anon} anonymisiert")
        except Exception as e:
            details.append(f"Bewerbungs-Bereinigung übersprungen ({e})")

        msg = "Täglicher Lauf: " + ", ".join(details) + "."
        AktivitaetsLog.objects.create(aktion="Täglicher Lauf (Scheduler)", objekt="", details=msg)
        self.stdout.write(self.style.SUCCESS(f"{organisation}: {msg}"))
        return msg
