# AHV-Nummer verschlüsselt ablegen (Security-Audit, revDSG Art. 8).
#
# Zwei Schritte: Spalte verlängern (Fernet-Token sind länger als der Klartext),
# dann bestehende Klartext-Werte verschlüsseln. Fehlt `IMAP_SCHLUESSEL`, bleibt
# der Bestand im Klartext, die Migration läuft trotzdem durch (ein Deploy darf
# nicht an einem fehlenden Schlüssel scheitern) — nachgeholt wird mit
# `python manage.py ahv_verschluesseln`. Das Feld liest Klartext-Altwerte
# unverändert und verschlüsselt beim nächsten Speichern.

from django.db import migrations

import core.verschluesselt


def verschluesseln(apps, schema_editor):
    from core.services.geheimnis import schluessel_vorhanden
    from core.verschluesselt import sieht_verschluesselt_aus
    if not schluessel_vorhanden():
        return
    from core.services.geheimnis import verschluesseln as _v
    Mieter = apps.get_model('crm', 'Mieter')
    # Rohwerte über values_list: das Feld würde sonst beim Lesen entschlüsseln.
    for pk, wert in list(Mieter.objects.exclude(ahv_nummer='').values_list('pk', 'ahv_nummer')):
        if wert and not sieht_verschluesselt_aus(wert):
            Mieter.objects.filter(pk=pk).update(ahv_nummer=_v(wert))


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0045_abostufen_marktnamen'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mieter',
            name='ahv_nummer',
            field=core.verschluesselt.VerschluesseltesCharField(
                blank=True, default='', klartext_max_laenge=20, verbose_name='AHV-Nummer'),
        ),
        migrations.RunPython(verschluesseln, migrations.RunPython.noop),
    ]
