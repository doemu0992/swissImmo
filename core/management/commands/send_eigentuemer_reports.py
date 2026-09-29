"""Versendet jedem Eigentümer (Eigentuemer mit E-Mail) automatisch seinen
Portfolio-Report + Steuerauszug als PDF-Anhang.

Zum periodischen Planen (z.B. quartalsweise / jährlich) im
PythonAnywhere-Scheduler:
    python manage.py send_eigentuemer_reports
Optionen:
    --jahr 2025          Steuerauszug-Jahr (Standard: Vorjahr)
    --nur-mit-portal     nur Mandate mit aktivem Portal-Login
    --dry-run            nichts senden, nur auflisten
    --organisation 3     nur diese Verwaltung

JE VERWALTUNG EIN LAUF. Der Report nennt Liegenschaften, Mieterträge und
Leerstände — ein Lauf über den gesamten Bestand schickte einem Eigentümer die
Zahlen fremder Portfolios. Seit Etappe 6.2 wirft `Eigentuemer.objects` ohne
Kontext, statt die falschen Empfänger zu bedienen.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sendet Eigentümern Portfolio-Report + Steuerauszug per E-Mail."

    def add_arguments(self, parser):
        parser.add_argument('--jahr', type=int, default=None)
        parser.add_argument('--nur-mit-portal', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        jahr = opts['jahr'] or (datetime.date.today().year - 1)
        _, fehler = je_organisation(lambda organisation: self._senden(organisation, jahr, opts),
                                    auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"{len(fehler)} Verwaltung(en) abgebrochen — "
                               f"{', '.join(str(o) for o, _ in fehler)}.")

    def _senden(self, organisation, jahr, opts):
        from django.utils import translation
        from django.utils.translation import gettext
        from crm.models import Eigentuemer
        from core.services.dokumentsprache import in_sprache, sprache_von
        from core.services.portfolio_report import generate_portfolio_report_fuer
        from core.services.steuerauszug import generate_steuerauszug_pdf
        from core.utils.email_service import send_report_mail

        qs = Eigentuemer.objects.exclude(email='').filter(email__isnull=False)
        if opts['nur_mit_portal']:
            qs = qs.filter(benutzer__isnull=False)

        gesendet = 0
        for md in qs:
            if not md.email:
                continue
            try:
                report = generate_portfolio_report_fuer(md)
                # Der Steuerauszug bleibt deutsch: Seine Begriffe (AfA,
                # Liegenschaftsrechnung) haben kantonal festgelegte
                # Entsprechungen, die nicht geraten werden.
                with translation.override('de'):
                    steuer = generate_steuerauszug_pdf(md, jahr)
            except Exception as e:
                self.stderr.write(f"  ✗ {md.firma_oder_name}: Report-Fehler {e}")
                continue
            anhaenge = [
                (f"Portfolio-Report_{md.firma_oder_name}.pdf", report),
                (f"Steuerauszug_{jahr}.pdf", steuer),
            ]
            # Begleitmail in der Sprache des Eigentümers (D11).
            with in_sprache(sprache_von(md)):
                gruss = gettext('Guten Tag %(name)s') % {'name': md.firma_oder_name}
                text = gettext('Im Anhang finden Sie den aktuellen Portfolio-Report sowie den '
                               'Steuerauszug %(jahr)s zu Ihren Liegenschaften. Alle Details '
                               'jederzeit in Ihrem Eigentümer-Portal.') % {'jahr': jahr}
                schluss = gettext('Freundliche Grüsse')
                absender = gettext('Ihre Liegenschaftsverwaltung')
                betreff = gettext('Ihr Liegenschafts-Report %(jahr)s') % {'jahr': jahr}
            html = f"<p>{gruss}</p><p>{text}</p><p>{schluss}<br>{absender}</p>"
            if opts['dry_run']:
                self.stdout.write(f"  (dry-run) → {md.firma_oder_name} <{md.email}>")
                continue
            if send_report_mail(md.email, betreff, html, anhaenge):
                gesendet += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ {md.firma_oder_name} <{md.email}>"))

        self.stdout.write(self.style.SUCCESS(
            f"{organisation}: {gesendet} Report-Mail(s) versendet (Jahr {jahr})."))
        return gesendet
