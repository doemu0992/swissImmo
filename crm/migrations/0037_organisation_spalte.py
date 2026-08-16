"""Etappe 5, PR 8 — Schritt 1 von 3: Spalten fuer crm.

Sechs Modelle, drei Bauformen — und das ist kein Zufall, sondern die Natur von
crm: Hier stehen die Stammdaten, und Stammdaten haengen an keiner Liegenschaft.

    MieterAdresse   Kette ueber `mieter` (pflichtig)
    Kommunikation   Tupel ('mieter', 'vertrag', 'liegenschaft') + Rueckfall
    Eigentuemer     eigene Spalte aus dem Kontext
    Mieter          eigene Spalte aus dem Kontext
    Handwerker      eigene Spalte aus dem Kontext
    Vorlage         eigene Spalte, NULLBAR

WARUM `Vorlage` NULLBAR BLEIBT — die einzige Ausnahme in Phase 2:

    NULL     = mitgelieferte Systemvorlage, fuer alle Verwaltungen gleich
    gesetzt  = eigene Vorlage dieser Verwaltung

Ohne die Unterscheidung bekaeme jede neue Verwaltung saemtliche
Standardvorlagen kopiert, und eine Korrektur am Original erreichte keine von
ihnen mehr. Der Preis steht am Modell: Lesende Queries muessen
`Q(organisation=org) | Q(organisation__isnull=True)` fragen.

`crm.Organisation` und `benutzer.Benutzer` bekommen bewusst KEINEN Bezug — die
eine IST der Anker, der andere haengt ueber `Mitgliedschaft` daran, damit eine
Person fuer mehrere Verwaltungen arbeiten kann (Entscheid vom 15.08.2026).
"""
from django.db import migrations, models
import django.db.models.deletion


PFLICHTIG = ['eigentuemer', 'handwerker', 'kommunikation', 'mieter', 'mieteradresse']


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('rentals', '0034_organisation_pflicht'),
        ('crm', '0036_rollen_je_organisation'),
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
        for modell in PFLICHTIG
    ] + [
        # Vorlage bekommt die Spalte gleich in ihrer Endgestalt: nullbar, und
        # das bleibt sie. Sie taucht deshalb in Schritt 3 nicht mehr auf.
        migrations.AddField(
            model_name='vorlage',
            name='organisation',
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        ),
    ]
