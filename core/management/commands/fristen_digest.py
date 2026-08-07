"""Wöchentliches Fristen-Mail an das Team (PythonAnywhere Scheduled Task):

    python manage.py fristen_digest            # überfällige + nächste 7 Tage
    python manage.py fristen_digest --tage 14
    python manage.py fristen_digest --dry-run  # nur anzeigen, nicht senden

Fasst die offenen, datierten Fristen zusammen und schickt sie an alle aktiven
Team-Benutzer (Verwaltung/Sachbearbeitung) mit E-Mail-Adresse. Fällt keine
Empfängeradresse an, wird an die Verwaltungs-Adresse gesendet."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

logger = logging.getLogger(__name__)



class Command(BaseCommand):
    help = "Wöchentliches Fristen-Mail an das Team (überfällig + nächste N Tage)."

    def add_arguments(self, parser):
        parser.add_argument('--tage', type=int, default=7, help="Vorlauf in Tagen (Standard 7)")
        parser.add_argument('--dry-run', action='store_true', help="Nicht senden, nur anzeigen")

    def handle(self, *args, **opts):
        from core.models import Pendenz, AktivitaetsLog
        from django.contrib.auth.models import User
        from crm.models import Verwaltung

        heute = timezone.localdate()
        grenze = heute + timedelta(days=opts['tage'])
        pq = (Pendenz.objects.filter(erledigt=False, faellig_am__isnull=False, faellig_am__lte=grenze)
              .select_related('liegenschaft', 'vertrag__mieter').order_by('faellig_am'))
        fristen = list(pq)

        if not fristen:
            self.stdout.write(self.style.SUCCESS("Keine anstehenden Fristen — kein Mail gesendet."))
            return

        # Empfänger: aktive Team-Benutzer mit E-Mail
        empfaenger = list(User.objects.filter(
            is_active=True, groups__name__in=['Verwaltung', 'Sachbearbeitung']
        ).exclude(email='').values_list('email', flat=True).distinct())
        if not empfaenger:
            vw = Verwaltung.objects.first()
            if vw and getattr(vw, 'email', ''):
                empfaenger = [vw.email]
        if not empfaenger:
            self.stdout.write(self.style.WARNING("Keine Empfängeradresse gefunden — abgebrochen."))
            return

        ueberfaellig = [p for p in fristen if p.faellig_am < heute]
        anstehend = [p for p in fristen if p.faellig_am >= heute]

        def _zeile(p):
            bezug = ''
            if p.vertrag_id and p.vertrag:
                bezug = p.vertrag.mieter.display_name if p.vertrag.mieter_id else ''
            elif p.liegenschaft_id:
                bezug = p.liegenschaft.strasse
            tage = (p.faellig_am - heute).days
            wann = f"{tage} Tage überfällig" if tage < 0 else ("heute" if tage == 0 else f"in {tage} Tagen")
            return p, bezug, wann

        text_zeilen = []
        html_zeilen = []
        for titel, gruppe in [("Überfällig", ueberfaellig), ("Anstehend", anstehend)]:
            if not gruppe:
                continue
            text_zeilen.append(f"\n{titel}:")
            html_zeilen.append(f'<h3 style="margin:16px 0 6px">{titel}</h3><ul style="padding-left:18px">')
            for p in gruppe:
                _p, bezug, wann = _zeile(p)
                text_zeilen.append(f"  • {p.faellig_am:%d.%m.%Y} — {p.titel}"
                                   f"{(' (' + bezug + ')') if bezug else ''} — {wann}")
                html_zeilen.append(
                    f'<li><b>{p.faellig_am:%d.%m.%Y}</b> — {p.titel}'
                    f'{(" · " + bezug) if bezug else ""} '
                    f'<span style="color:#888">({wann})</span></li>')
            html_zeilen.append('</ul>')

        betreff = f"Fristen-Übersicht: {len(ueberfaellig)} überfällig, {len(anstehend)} anstehend"
        text = ("Guten Tag\n\nAnstehende und überfällige Fristen der nächsten "
                f"{opts['tage']} Tage:\n" + "\n".join(text_zeilen) +
                "\n\nÖffnen im Fristen-Center der Verwaltung.\n")
        html = ("<div style='font-family:sans-serif;font-size:14px;color:#222'>"
                "<p>Guten Tag</p><p>Anstehende und überfällige Fristen der nächsten "
                f"{opts['tage']} Tage:</p>" + "".join(html_zeilen) +
                "<p style='color:#888;font-size:12px'>Automatischer Fristen-Report · "
                "Details im Fristen-Center der Verwaltung.</p></div>")

        if opts['dry_run']:
            self.stdout.write(text)
            self.stdout.write(self.style.WARNING(f"[dry-run] {len(empfaenger)} Empfänger, nicht gesendet."))
            return

        mail = EmailMultiAlternatives(subject=betreff, body=text,
                                      from_email=settings.DEFAULT_FROM_EMAIL, to=empfaenger)
        mail.attach_alternative(html, "text/html")
        # iCal-Datei anhängen (Import in den Kalender)
        try:
            from core.services.ical import build_ics, fristen_events
            mail.attach("swissimmo-fristen.ics", build_ics(fristen_events(fristen)), "text/calendar")
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
        mail.send()

        AktivitaetsLog.objects.create(
            aktion="Fristen-Mail versendet", objekt=f"{len(fristen)} Fristen",
            details=f"an {len(empfaenger)} Empfänger", kategorie='versand')
        self.stdout.write(self.style.SUCCESS(
            f"Fristen-Mail an {len(empfaenger)} Empfänger gesendet ({len(fristen)} Fristen)."))
