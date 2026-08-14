# E3-Folgemigration: Das Feld heisst nicht mehr `mandant`, sondern
# `eigentuemer` — die Spalte entsprechend `eigentuemer_id`.
#
# Anders als beim Modell (dort nagelt ein altes `db_table` die Tabelle fest,
# siehe crm/0029) ist hier nichts festgeschrieben. Die Spalte wird deshalb
# wirklich umbenannt, damit Schema und Code dasselbe Wort benutzen. Ein
# Spaltenwechsel ist eine gewoehnliche, umkehrbare Operation; Daten gehen
# dabei nicht verloren.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0029_mandant_zu_eigentuemer'),
        ('portfolio', '0030_liegenschaft_anlagekosten_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='liegenschaft',
            old_name='mandant',
            new_name='eigentuemer',
        ),
    ]
