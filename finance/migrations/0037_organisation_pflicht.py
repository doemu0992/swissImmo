"""Etappe 5, PR 6 — Schritt 3 von 3: Pflicht und die vier neuen Eindeutigkeiten.

Die vier Constraints ersetzen globale `unique=True`-Felder. Jede von ihnen war
in einer mandantenfaehigen Anwendung nicht bloss zu streng, sondern falsch:

  Buchungskonto.nummer   — Konto 1020 «Bank» hat jede Verwaltung. Global
                           koennte die zweite gar nicht eingerichtet werden.
  LieferantProfil.name_key — Verwaltung B koennte «Muster AG» nicht lernen und
                           bekaeme bei get_or_create DEREN Konto und IBAN.
  NebenkostenLernRegel.suchwort — dasselbe fuer die Zuordnungsregeln.
  ZahlerZuordnung.name_norm — derselbe Absender zeigt je Verwaltung auf einen
                           anderen Vertrag.
  Buchung.beleg_nr       — siehe `Buchung.save()`: Hier genuegt die Constraint
                           allein NICHT, auch die Vergabe zaehlt je Organisation.
"""
from django.db import migrations, models
import django.db.models.deletion


MODELLE = [
    'abrechnungsperiode', 'abschreibung', 'anlage', 'bankbewegung', 'buchung',
    'buchungskonto', 'erneuerungsfonds', 'hypothek', 'jahresabschluss',
    'kontoauszug', 'lieferantprofil', 'mietzinskontrolle', 'nebenkostenbeleg',
    'nebenkostenlernregel', 'zahlerzuordnung',
]

CONSTRAINTS = [
    ('buchung',              ('organisation', 'beleg_nr'),  'uniq_beleg_nr_je_organisation'),
    ('buchungskonto',        ('organisation', 'nummer'),    'uniq_konto_je_organisation'),
    ('lieferantprofil',      ('organisation', 'name_key'),  'uniq_lieferant_je_organisation'),
    ('nebenkostenlernregel', ('organisation', 'suchwort'),  'uniq_lernregel_je_organisation'),
    ('zahlerzuordnung',      ('organisation', 'name_norm'), 'uniq_zahler_je_organisation'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('finance', '0036_organisation_befuellen'),
    ]

    operations = [
        migrations.AlterField(
            model_name=modell,
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        )
        for modell in MODELLE
    ] + [
        migrations.AddConstraint(
            model_name=modell,
            constraint=models.UniqueConstraint(fields=felder, name=name),
        )
        for modell, felder, name in CONSTRAINTS
    ]
