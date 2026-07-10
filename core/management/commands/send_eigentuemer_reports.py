"""Versendet jedem Eigentümer (Mandant mit E-Mail) automatisch seinen
Portfolio-Report + Steuerauszug als PDF-Anhang.

Zum periodischen Planen (z.B. quartalsweise / jährlich) im
PythonAnywhere-Scheduler:
    python manage.py send_eigentuemer_reports
Optionen:
    --jahr 2025          Steuerauszug-Jahr (Standard: Vorjahr)
    --nur-mit-portal     nur Mandate mit aktivem Portal-Login
    --dry-run            nichts senden, nur auflisten
"""
import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sendet Eigentümern Portfolio-Report + Steuerauszug per E-Mail."

    def add_arguments(self, parser):
        parser.add_argument('--jahr', type=int, default=None)
        parser.add_argument('--nur-mit-portal', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from crm.models import Mandant
        from core.views.portal import _portfolio_daten
        from core.services.portfolio_report import generate_portfolio_report
        from core.services.steuerauszug import generate_steuerauszug_pdf
        from core.utils.email_service import send_report_mail

        jahr = opts['jahr'] or (datetime.date.today().year - 1)
        qs = Mandant.objects.exclude(email='').filter(email__isnull=False)
        if opts['nur_mit_portal']:
            qs = qs.filter(benutzer__isnull=False)

        gesendet = 0
        for md in qs:
            if not md.email:
                continue
            try:
                report = generate_portfolio_report(md, _portfolio_daten(md))
                steuer = generate_steuerauszug_pdf(md, jahr)
            except Exception as e:
                self.stderr.write(f"  ✗ {md.firma_oder_name}: Report-Fehler {e}")
                continue
            anhaenge = [
                (f"Portfolio-Report_{md.firma_oder_name}.pdf", report),
                (f"Steuerauszug_{jahr}.pdf", steuer),
            ]
            html = (
                f"<p>Guten Tag {md.firma_oder_name}</p>"
                f"<p>Im Anhang finden Sie den aktuellen Portfolio-Report sowie den "
                f"Steuerauszug {jahr} zu Ihren Liegenschaften. Alle Details jederzeit "
                f"in Ihrem Eigentümer-Portal.</p>"
                f"<p>Freundliche Grüsse<br>Ihre Liegenschaftsverwaltung</p>")
            if opts['dry_run']:
                self.stdout.write(f"  (dry-run) → {md.firma_oder_name} <{md.email}>")
                continue
            if send_report_mail(md.email, f"Ihr Liegenschafts-Report {jahr}", html, anhaenge):
                gesendet += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ {md.firma_oder_name} <{md.email}>"))

        self.stdout.write(self.style.SUCCESS(
            f"Fertig. {gesendet} Report-Mail(s) versendet (Jahr {jahr})."))
