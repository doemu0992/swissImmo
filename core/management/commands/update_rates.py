from django.core.management.base import BaseCommand
# HIER WAR DER FEHLER: Wir holen es jetzt aus dem "utils" Ordner
from core.utils.market_data import update_verwaltung_rates
from django.utils import timezone
import pytz

class Command(BaseCommand):
    help = 'Aktualisiert Referenzzinssatz und LIK automatisch (Alle 4h)'

    def handle(self, *args, **options):
        # 1. Wir holen die aktuelle Weltzeit (UTC)
        now_utc = timezone.now()

        # 2. Wir rechnen sie HART in Zürich-Zeit um
        try:
            zurich_tz = pytz.timezone('Europe/Zurich')
            now_zurich = now_utc.astimezone(zurich_tz)
        except:
            # Fallback, falls pytz zickt (sollte nicht passieren)
            now_zurich = now_utc

        # 3. Das ist der Stempel für das Logbuch
        timestamp = now_zurich.strftime('%d.%m.%Y %H:%M:%S')

        # 4. Update starten
        status, errors = update_verwaltung_rates()

        # 5. Ergebnis schreiben
        if errors:
            # Wir prüfen kurz, ob es nur die harmlose "Warten auf BFS"-Meldung ist
            error_str = str(errors)
            if "Warten" in error_str or "noch nicht" in error_str:
                 self.stdout.write(f"[{timestamp}] ℹ️  INFO: {errors[0]}")
            else:
                 self.stdout.write(f"[{timestamp}] ⚠️  FEHLER: {errors}")
        else:
            self.stdout.write(f"[{timestamp}] ✅ {status}")