"""Zahlungs-Cockpit V12: Verwendung eines Mieterguthabens, Klärungsnotiz.

Bestehende Zeilen bekommen «offen»: Ein Guthaben, das vor dieser Version
entstand, wurde nie mit einer automatischen Verrechnung angekündigt und wird
deshalb nicht nachträglich ungefragt verrechnet. Neue Zeilen bekommen danach
den Standard «naechste_rechnung» (zweiter Schritt).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0045_phase1_audit_basis"),
    ]

    operations = [
        migrations.AddField(
            model_name="zahlungseingang",
            name="guthaben_verwendung",
            field=models.CharField(
                choices=[
                    ("naechste_rechnung", "Mit nächster Rechnung verrechnen"),
                    ("nk_abrechnung", "Für die Nebenkostenabrechnung reservieren"),
                    ("offen", "Offen lassen (Entscheid von Hand)"),
                ],
                default="offen",
                max_length=20,
                verbose_name="Verwendung des Guthabens",
            ),
        ),
        migrations.AlterField(
            model_name="zahlungseingang",
            name="guthaben_verwendung",
            field=models.CharField(
                choices=[
                    ("naechste_rechnung", "Mit nächster Rechnung verrechnen"),
                    ("nk_abrechnung", "Für die Nebenkostenabrechnung reservieren"),
                    ("offen", "Offen lassen (Entscheid von Hand)"),
                ],
                default="naechste_rechnung",
                max_length=20,
                verbose_name="Verwendung des Guthabens",
            ),
        ),
        migrations.AddField(
            model_name="zahlungseingang",
            name="klaerung_notiz",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Klärungsnotiz"
            ),
        ),
    ]
