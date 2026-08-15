# Etappe 4.1: Liegenschaft.verwaltung heisst ab hier Liegenschaft.organisation.
#
# Anders als die Modellumbenennung in crm/0032 ist das eine ECHTE
# Spaltenumbenennung (`verwaltung_id` → `organisation_id`). Sie ist verlustfrei
# und auf SQLite wie PostgreSQL eine reine Metadatenoperation.
#
# Warum überhaupt: Ein Fremdschlüssel namens `verwaltung`, der auf eine
# `Organisation` zeigt, wäre die halbe Umbenennung, vor der E3 ausdrücklich
# gewarnt hat — dasselbe Wort mit zwei Bedeutungen im selben Code.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0031_liegenschaft_eigentuemer'),
        # Erst umbenennen, dann das Feld nachziehen: Vorher heisst das Ziel
        # noch `crm.Verwaltung`.
        ('crm', '0032_verwaltung_zu_organisation'),
    ]

    operations = [
        migrations.RenameField(
            model_name='liegenschaft',
            old_name='verwaltung',
            new_name='organisation',
        ),
    ]
