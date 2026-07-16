"""Backfill: bestehende Mietzinsanpassungen als datierte Sollmietzins-Zeile am
Objekt nachtragen. Früher legte nur das neue amtliche Formular diese Zeile an —
über den Alt-Weg/Import erfasste Anpassungen fehlten im Objekt-Mietzins. Ab jetzt
erledigt das MietzinsAnpassung.save(); diese Migration holt Altbestand nach.

Sicher: legt NUR an, wenn am Objekt für das Datum noch keine Zeile existiert
(überschreibt keine manuellen Sollmietzins-/Gratismonat-Zeilen)."""
from decimal import Decimal
from django.db import migrations


def backfill(apps, schema_editor):
    MietzinsAnpassung = apps.get_model('rentals', 'MietzinsAnpassung')
    Sollmietzins = apps.get_model('portfolio', 'Sollmietzins')
    for anp in MietzinsAnpassung.objects.select_related('vertrag__einheit', 'vertrag__mieter'):
        v = getattr(anp, 'vertrag', None)
        e = getattr(v, 'einheit', None) if v else None
        if not e or anp.neuer_netto_mietzins is None or anp.wirksam_ab is None:
            continue
        if Sollmietzins.objects.filter(einheit=e, gueltig_ab=anp.wirksam_ab).exists():
            continue   # bestehende (evtl. manuelle) Zeile nicht antasten
        nk = getattr(e, 'nebenkosten_aktuell', None) or Decimal('0.00')
        teile = ['Amtliche Mietzinsanpassung']
        grund = (anp.begruendung or '').strip()
        if grund:
            teile.append(grund)
        m = getattr(v, 'mieter', None)
        name = ''
        if m:
            name = (getattr(m, 'firmen_name', '') or
                    f"{(m.vorname or '').strip()} {(m.nachname or '').strip()}".strip())
        if name:
            teile.append(name)
        Sollmietzins.objects.create(
            einheit=e, gueltig_ab=anp.wirksam_ab,
            netto_mietzins=anp.neuer_netto_mietzins, nebenkosten=nk,
            basis_referenzzinssatz=anp.neuer_referenzzinssatz,
            basis_lik_punkte=anp.neuer_lik_index,
            quelle_anpassung=anp, notiz=' · '.join(teile))


class Migration(migrations.Migration):
    dependencies = [
        ('rentals', '0025_cleanup_verwaiste_vertragsdokumente'),
        ('portfolio', '0028_alter_sollmietzins_quelle_anpassung'),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
