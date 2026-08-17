"""Mietzins-Scanner: prüft aktive Mietverträge auf Anpassungspotenzial.

    python manage.py check_rents

JE ORGANISATION EIN DURCHGANG. Vorher nahm der Befehl den Referenzzinssatz und
den LIK-Stand der ERSTEN Verwaltung und rechnete damit die Verträge ALLER
durch. Beide Werte werden je Organisation gepflegt (`update_rates`); hat eine
Verwaltung noch nicht aktualisiert, rechnete der Scanner ihre Verträge gegen
einen fremden Stand — und die Ausgabe mischte die Mieternamen aller
Verwaltungen in eine Liste.

Der Referenzzinssatz ist zwar bundesweit derselbe, aber genau darauf darf man
sich hier nicht verlassen: Massgeblich ist der Stand, den die jeweilige
Verwaltung führt, denn an ihm hängt die Begründung einer Mietzinsanpassung
nach OR 269a.
"""
from django.core.management.base import BaseCommand

from crm.models import Organisation
from rentals.models import Mietvertrag
from rentals.services import berechne_mietpotenzial


class Command(BaseCommand):
    help = 'Prüft alle Mietverträge auf Anpassungspotenzial'

    def handle(self, *args, **options):
        from core.tenancy import organisation_kontext

        organisationen = list(Organisation.objects.order_by('pk'))
        if not organisationen:
            self.stdout.write(self.style.ERROR(
                "Keine Verwaltungs-Daten gefunden! Bitte erst update_rates laufen lassen."))
            return

        for verwaltung in organisationen:
            with organisation_kontext(verwaltung):
                self._scannen(verwaltung)

    def _scannen(self, verwaltung):
        curr_ref = verwaltung.aktueller_referenzzinssatz
        curr_lik = verwaltung.aktueller_lik_punkte

        if not curr_ref or not curr_lik:
            self.stdout.write(self.style.ERROR(
                f"{verwaltung.firma}: Marktdaten unvollständig (0.0) — übersprungen. "
                f"Bitte Update prüfen."))
            return

        self.stdout.write("\n==========================================")
        self.stdout.write(" 🏢 MIETZINS-SCANNER")
        self.stdout.write(f" {verwaltung.firma}")
        self.stdout.write(f" Basis heute: Ref.Zins {curr_ref}% | LIK {curr_lik} Punkte")
        self.stdout.write("==========================================\n")

        # Nur die Verträge DIESER Verwaltung — sonst rechnet der Scanner fremde
        # Verträge gegen den hiesigen Stand und nennt dabei fremde Mieternamen.
        vertraege = Mietvertrag.objects.filter(organisation=verwaltung, aktiv=True)

        potenzial_total = 0.0
        risiko_total = 0.0

        for v in vertraege:
            ergebnis = berechne_mietpotenzial(v, curr_ref, curr_lik)

            if not ergebnis:
                # Daten fehlen im Vertrag
                continue

            if ergebnis['action'] == 'UP':
                # Geld liegt auf der Strasse
                self.stdout.write(self.style.SUCCESS(
                    f"🟢 [ERHÖHUNG] {ergebnis['mieter']}: +{ergebnis['delta_chf']} CHF / Monat"
                ))
                self.stdout.write(f"    Grund: Zins {ergebnis['details_zins']} | Teuerung {ergebnis['details_lik']}")
                self.stdout.write(f"    Miete: {ergebnis['aktuell_chf']} -> {ergebnis['neu_chf']}\n")
                potenzial_total += float(ergebnis['delta_chf'])

            elif ergebnis['action'] == 'DOWN':
                # Gefahr!
                self.stdout.write(self.style.ERROR(
                    f"🔴 [RISIKO]   {ergebnis['mieter']}: {ergebnis['delta_chf']} CHF / Monat (Senkungsanspruch)"
                ))
                self.stdout.write(f"    Grund: Zins {ergebnis['details_zins']} | Teuerung {ergebnis['details_lik']}\n")
                risiko_total += float(abs(ergebnis['delta_chf']))

            # Verträge, die okay sind (weniger als 0.5% Abweichung), zeigen wir nicht an, um die Liste sauber zu halten.

        self.stdout.write("------------------------------------------")
        self.stdout.write(f"💰 Jährliches Potenzial:  +{potenzial_total * 12:,.2f} CHF")
        self.stdout.write(f"⚠️ Jährliches Risiko:     -{risiko_total * 12:,.2f} CHF")
        self.stdout.write("------------------------------------------")
