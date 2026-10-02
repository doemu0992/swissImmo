"""Abnahmeprotokolle gehören zur Einheit; Protokolle bauen aufeinander auf.

Drei Schritte, damit der Bestand nie ohne Einheit dasteht:
1. Spalte `einheit` zunächst optional anlegen,
2. aus dem Vertrag befüllen,
3. Pflicht stellen.

Dazu: `vorgaenger`, `folge_vertrag` am Protokoll; `vorgaenger_position` und
`vorbestand_entscheid` an der Position.
"""
import django.db.models.deletion
from django.db import migrations, models


def einheit_aus_vertrag(apps, schema_editor):
    Protokoll = apps.get_model('rentals', 'Abnahmeprotokoll')
    for prot in Protokoll.objects.select_related('vertrag').filter(einheit__isnull=True):
        prot.einheit_id = prot.vertrag.einheit_id
        prot.save(update_fields=['einheit'])


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0042_versicherung_selbstbehalt'),
        ('rentals', '0040_abnahmeposition'),
    ]

    operations = [
        migrations.AddField(
            model_name='abnahmeprotokoll', name='einheit',
            field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='abnahmen', to='portfolio.einheit'),
        ),
        migrations.AddField(
            model_name='abnahmeprotokoll', name='vorgaenger',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='nachfolger', to='rentals.abnahmeprotokoll',
                                    verbose_name='Baut auf Protokoll'),
        ),
        migrations.AddField(
            model_name='abnahmeprotokoll', name='folge_vertrag',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to='rentals.mietvertrag'),
        ),
        migrations.AddField(
            model_name='abnahmeposition', name='vorgaenger_position',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='nachfolger', to='rentals.abnahmeposition'),
        ),
        migrations.AddField(
            model_name='abnahmeposition', name='vorbestand_entscheid',
            field=models.CharField(blank=True, default='', max_length=12,
                                   choices=[('', 'Offen'), ('mieter', 'Weiterhin dem Mieter belasten'),
                                            ('vorbestehend', 'Vorbestehend, nicht belasten')],
                                   verbose_name='Entscheid Vorbestand'),
        ),
        migrations.RunPython(einheit_aus_vertrag, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='abnahmeprotokoll', name='einheit',
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='abnahmen', to='portfolio.einheit'),
        ),
    ]
