"""Etappe 5, PR 6 — Schritt 1 von 3: Spalten fuer finance.

FUENFZEHN der 22 Modelle. Die restlichen sieben warten, und zwar aus Gruenden,
die hier festgehalten gehoeren:

  KreditorenRechnung, DebitorenRechnung, Mahnung, Zahlungseingang — Gruppe B.
  Lokal hat KreditorenRechnung 3 von 17 Waisen (weder Liegenschaft noch Einheit
  noch Konto). Ob es die produktiv gibt und was mit ihnen geschieht, ist eine
  fachliche Frage, die keine Migration beantwortet.

  KreditorPosition, KreditorenZahlung — Gruppe C, aber ueber `rechnung` bzw.
  `kreditor` an KreditorenRechnung haengend. Sie koennen erst danach.

  EigentuemerAuszahlung — haengt pflichtig an `crm.Eigentuemer`, und das ist
  selbst noch ohne Bezug (Gruppe A, eigener PR).

DIE EINORDNUNG WURDE NACHGEMESSEN und weicht vom Plan ab (8/8/6 dort, 14/4/4
gemessen). Zwei Ursachen:

  1. `Buchungskonto` hat selbst keinen Fremdschluessel, haengt aber als
     PFLICHTFELD an Buchung, Bankbewegung und Kontoauszug. Sobald es die Spalte
     traegt, fallen diese drei von allein in Gruppe C — zusammen ueber tausend
     Zeilen.

  2. `Erneuerungsfonds.liegenschaft` ist ein pflichtiges OneToOneField. Das
     Einordnungsskript prueft `many_to_one` und hat es uebersehen; das Modell
     stand faelschlich in Gruppe A. Im ganzen Bestand gibt es drei
     OneToOne-Beziehungen, die anderen zwei zeigen auf `Benutzer` — die vier
     bereits gebauten Apps sind also nicht betroffen.

Zugleich fallen hier VIER globale Eindeutigkeiten. Sie werden in Schritt 3 als
Eindeutigkeit je Organisation neu gesetzt; dazwischen gibt es keine, damit die
Datenmigration nicht an der alten haengenbleibt.
"""
from django.db import migrations, models
import django.db.models.deletion


#: Alle 15, unabhaengig davon ob Kette oder Kontext — die Spalte sieht gleich aus.
MODELLE = [
    'abrechnungsperiode', 'abschreibung', 'anlage', 'bankbewegung', 'buchung',
    'buchungskonto', 'erneuerungsfonds', 'hypothek', 'jahresabschluss',
    'kontoauszug', 'lieferantprofil', 'mietzinskontrolle', 'nebenkostenbeleg',
    'nebenkostenlernregel', 'zahlerzuordnung',
]


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('rentals', '0034_organisation_pflicht'),
        ('finance', '0034_alter_eigentuemerauszahlung_eigentuemer'),
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
    ] + [
        # Die globalen Eindeutigkeiten fallen HIER, nicht erst in Schritt 3.
        # Sonst koennte die Datenmigration keine zweite Zeile mit demselben
        # Wert anlegen, und die neue Constraint waere nicht setzbar, solange
        # die alte steht.
        migrations.AlterField(
            model_name='buchung', name='beleg_nr',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Beleg-Nr'),
        ),
        migrations.AlterField(
            model_name='buchungskonto', name='nummer',
            field=models.CharField(max_length=10, verbose_name='Kontonummer'),
        ),
        migrations.AlterField(
            model_name='lieferantprofil', name='name_key',
            field=models.CharField(max_length=200, verbose_name='Namensschlüssel'),
        ),
        migrations.AlterField(
            model_name='nebenkostenlernregel', name='suchwort',
            field=models.CharField(max_length=100, verbose_name='Schlüsselwort (z.B. Firmenname)'),
        ),
        migrations.AlterField(
            model_name='zahlerzuordnung', name='name_norm',
            field=models.CharField(db_index=True, max_length=160,
                                   verbose_name='Absender (normalisiert)'),
        ),
    ]
