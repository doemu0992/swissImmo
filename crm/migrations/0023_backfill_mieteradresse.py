"""Seed the dated address history from existing flat Mieter fields.

- Every Mieter with a flat address gets an initial `wohn` row (gueltig_ab far in
  the past) so the effective delivery address is unchanged.
- Every Mieter with a pending `zukuenftig_ab` move gets a future-dated `wohn` row
  from the zukuenftige_* fields, so the planned move survives as a dated line.
"""
from datetime import date
from django.db import migrations

SENTINEL = date(2000, 1, 1)


def seed(apps, schema_editor):
    Mieter = apps.get_model('crm', 'Mieter')
    MieterAdresse = apps.get_model('crm', 'MieterAdresse')
    for m in Mieter.objects.all():
        if MieterAdresse.objects.filter(mieter=m, art='wohn').exists():
            continue
        if m.strasse or m.plz or m.ort:
            MieterAdresse.objects.create(
                mieter=m, art='wohn', gueltig_ab=SENTINEL,
                strasse=m.strasse or '', adresszusatz=m.adresszusatz or '',
                plz=m.plz or '', ort=m.ort or '',
                quelle='backfill', notiz='Initiale Adresse (Übernahme Stammdaten)')
        # geplanter Umzug → datierte Zukunfts-Zeile
        if m.zukuenftig_ab and (m.zukuenftige_strasse or m.zukuenftige_plz or m.zukuenftiger_ort):
            MieterAdresse.objects.get_or_create(
                mieter=m, art='wohn', gueltig_ab=m.zukuenftig_ab,
                defaults=dict(
                    strasse=m.zukuenftige_strasse or '', plz=m.zukuenftige_plz or '',
                    ort=m.zukuenftiger_ort or '', quelle='backfill',
                    notiz='Geplanter Einzug (Übernahme)'))


def unseed(apps, schema_editor):
    MieterAdresse = apps.get_model('crm', 'MieterAdresse')
    MieterAdresse.objects.filter(quelle='backfill').delete()


class Migration(migrations.Migration):
    dependencies = [('crm', '0022_mieteradresse')]
    operations = [migrations.RunPython(seed, unseed)]
