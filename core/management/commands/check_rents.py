from django.core.management.base import BaseCommand
from core.models import Mietvertrag, Verwaltung
from core.mietrecht_logic import berechne_mietpotenzial
import sys

class Command(BaseCommand):
    help = 'Prüft alle Mietverträge auf Anpassungspotenzial'

    def handle(self, *args, **options):
        # 1. Aktuelle Marktdaten laden
        verwaltung = Verwaltung.objects.first()
        if not verwaltung:
            self.stdout.write(self.style.ERROR("Keine Verwaltungs-Daten gefunden! Bitte erst update_rates laufen lassen."))
            return

        curr_ref = verwaltung.aktueller_referenzzinssatz
        curr_lik = verwaltung.aktueller_lik_punkte

        if not curr_ref or not curr_lik:
             self.stdout.write(self.style.ERROR("Marktdaten sind unvollständig (0.0). Bitte Update prüfen."))
             return

        self.stdout.write(f"\n==========================================")
        self.stdout.write(f" 🏢 MIETZINS-SCANNER")
        self.stdout.write(f" Basis heute: Ref.Zins {curr_ref}% | LIK {curr_lik} Punkte")
        self.stdout.write(f"==========================================\n")

        # 2. Verträge laden (nur aktive)
        vertraege = Mietvertrag.objects.filter(aktiv=True)

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