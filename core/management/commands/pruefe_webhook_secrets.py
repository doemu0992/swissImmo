"""Warnt, wenn eine Integration läuft, ihr Webhook-Secret aber fehlt.

Die Webhook-Endpunkte weisen ohne konfiguriertes Secret ab (fail-closed). Das
ist richtig — hat aber eine Kehrseite: Wer die Integration bisher OHNE Secret
betrieben hat, bei dem hörte der Rücklauf schlagartig auf, und zwar lautlos.
Bei DocuSeal heisst das: Unterschriebene Verträge werden nicht mehr abgelegt,
und niemand merkt es, bis jemand einen Vertrag sucht.

Deshalb diese Prüfung im Deploy: Ist ein API-Schlüssel gesetzt (die Integration
wird also benutzt), das zugehörige Webhook-Secret aber nicht, steht der Hinweis
im Deploy-Protokoll — mit den zwei Schritten, die nötig sind.

    python manage.py pruefe_webhook_secrets
"""
from django.conf import settings
from django.core.management.base import BaseCommand

#: (Anzeigename, Schlüssel-Einstellung, Secret-Einstellung, wo es einzutragen ist)
INTEGRATIONEN = [
    ('DocuSeal', 'DOCUSEAL_API_KEY', 'DOCUSEAL_WEBHOOK_SECRET',
     'im DocuSeal-Webhook als Header «X-Webhook-Secret» (oder ?token= in der URL)'),
    ('Brevo', 'BREVO_API_KEY', 'BREVO_WEBHOOK_SECRET',
     'in der Brevo-Webhook-Konfiguration als Header «X-Webhook-Secret»'),
]


class Command(BaseCommand):
    help = "Warnt, wenn eine genutzte Integration kein Webhook-Secret gesetzt hat."

    def handle(self, *args, **opts):
        offen = []
        for name, schluessel_key, secret_key, wo in INTEGRATIONEN:
            genutzt = bool(getattr(settings, schluessel_key, None))
            secret = bool(getattr(settings, secret_key, None))
            if genutzt and not secret:
                offen.append((name, secret_key, wo))

        if not offen:
            self.stdout.write("✓ Webhook-Secrets: nichts offen.")
            return

        self.stderr.write("")
        self.stderr.write("⚠ WEBHOOK OHNE SECRET — RÜCKLAUF WIRD ABGEWIESEN")
        for name, secret_key, wo in offen:
            self.stderr.write(f"  {name}: {secret_key} ist nicht gesetzt.")
            self.stderr.write(f"    1. {secret_key} in der Umgebung setzen (langer Zufallswert).")
            self.stderr.write(f"    2. Denselben Wert {wo} eintragen.")
        self.stderr.write("  Bis dahin weist der Endpunkt jeden Aufruf ab — bei DocuSeal")
        self.stderr.write("  bedeutet das: unterschriebene Verträge werden nicht abgelegt.")
        self.stderr.write("")
