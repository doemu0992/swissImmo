"""Etappe 5, PR 3 — Schritt 1 von 3: Spalten fuer rentals.

Acht Modelle mit geschlossener Pflicht-Kette. Die Wege sind kuerzer als in
portfolio, weil `Einheit` die Organisation seit PR 1 selbst traegt und
`Mietvertrag` bzw. `Abnahmeprotokoll` sie hier dazubekommen:

    Mietvertrag, Leerstand                    → einheit
    Staffelstufe, VertragMietzins,
    MietzinsAnpassung, Kuendigung,
    Abnahmeprotokoll                          → vertrag
    AbnahmeMangel                             → protokoll

`AbnahmeMangel` sah in der ersten Einordnung nach Gruppe B aus, weil das
Suchskript ueber `ausstattung` (null=True) eine optionale Abkuerzung zuerst
fand. Nachgemessen ist die Kette protokoll → vertrag → einheit → liegenschaft
durchgehend pflichtig — also Gruppe C.

OFFEN und NICHT in diesem PR: `rentals.Dokument`. Fuenf optionale
Fremdschluessel, davon fuehren `mieter` und `eigentuemer` gar nicht zur
Liegenschaft. Ob es produktiv Dokumente gibt, die nur an einem Mieter haengen,
ist eine Frage an den Bestand — und was mit ihnen geschieht, eine fachliche.
"""
from django.db import migrations, models
import django.db.models.deletion


MODELLE = [
    'abnahmemangel', 'abnahmeprotokoll', 'kuendigung', 'leerstand',
    'mietvertrag', 'mietzinsanpassung', 'staffelstufe', 'vertragmietzins',
]


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('rentals', '0031_dokument_eigentuemer'),
    ]

    operations = [
        migrations.AddField(
            model_name=modell,
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        )
        for modell in MODELLE
    ]
