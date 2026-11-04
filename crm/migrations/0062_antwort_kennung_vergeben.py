import re
import secrets
import unicodedata

from django.db import migrations

ZEICHEN = "abcdefghjkmnpqrstuvwxyz23456789"


def kennung_vergeben(apps, schema_editor):
    """Jede bestehende Verwaltung bekommt ihre Kennung: lesbares Präfix aus der Firma plus Zufall."""
    Organisation = apps.get_model("crm", "Organisation")
    vergeben = set(Organisation.objects.exclude(antwort_kennung="").values_list("antwort_kennung", flat=True))
    for org in Organisation.objects.filter(antwort_kennung="").order_by("pk"):
        # Präfix: nur a-z0-9, ohne Umlaute (ü -> u), höchstens 12 Zeichen.
        ascii_firma = unicodedata.normalize("NFKD", org.firma or "").encode("ascii", "ignore").decode().lower()
        praefix = re.sub(r"[^a-z0-9]", "", ascii_firma)[:12] or "verwaltung"
        while True:
            kennung = praefix + "-" + "".join(secrets.choice(ZEICHEN) for _ in range(10))
            if kennung not in vergeben:
                break
        vergeben.add(kennung)
        Organisation.objects.filter(pk=org.pk).update(antwort_kennung=kennung)


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0061_organisation_antwort_kennung"),
    ]

    operations = [
        # Rückwärts nichts tun: die Felder verschwinden mit 0061.
        migrations.RunPython(kennung_vergeben, migrations.RunPython.noop),
    ]
