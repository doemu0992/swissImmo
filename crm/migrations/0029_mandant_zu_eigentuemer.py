# E3: crm.Mandant heisst ab hier crm.Eigentuemer.
#
# Der Grund ist keine Kosmetik: `Mandant` bezeichnete im Bestandscode den
# EIGENTÜMER einer Liegenschaft, in der Projektanweisung zur Mandantenfähigkeit
# dagegen den TENANT. Solange beides gleich heisst, ist in Phase 2 jeder Satz
# über „den Mandanten" zweideutig — und eine falsch verstandene Zeile trennt
# dann die falschen Daten. Der Tenant heisst künftig `Organisation`.
#
# OHNE DATENRISIKO: `Meta.db_table = 'core_mandant'` ist festgeschrieben und
# bleibt es. Django benennt deshalb KEINE Tabelle um — `RenameModel` ist hier
# eine reine Zustandsoperation.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    # Die drei Fremd-Apps stehen hier nicht aus Höflichkeit, sondern weil ihre
    # ALTEN Migrationen `to='crm.mandant'` schreiben. Ohne diese Kanten darf
    # Django die Umbenennung irgendwo nach crm/0028 einsortieren — auch VOR
    # portfolio/0030. Beim Neuaufbau (Testlauf, frische Datenbank) bricht der
    # Graph dann mit „Related model 'crm.mandant' cannot be resolved". Auf einer
    # bereits migrierten Datenbank fällt das NICHT auf, weil dort nur die neuen
    # Migrationen laufen — der Fehler träfe erst den nächsten frischen Aufbau.
    dependencies = [
        ('crm', '0028_mandant_mahn_konfig'),
        ('portfolio', '0030_liegenschaft_anlagekosten_and_more'),
        ('finance', '0032_reconcile_stornierte_mahngebuehr'),
        ('rentals', '0030_kuendigung_ende_vorher'),
    ]

    operations = [
        migrations.RenameModel(old_name='Mandant', new_name='Eigentuemer'),
        migrations.AlterModelOptions(
            name='eigentuemer',
            options={'verbose_name': 'Eigentümer', 'verbose_name_plural': 'Eigentümer'},
        ),
        # Nur `related_name` ändert sich (mandant_profil → eigentuemer_profil).
        # Das ist eine reine Python-Angelegenheit, kein Spaltenwechsel.
        migrations.AlterField(
            model_name='eigentuemer',
            name='benutzer',
            field=models.OneToOneField(
                blank=True,
                help_text='Optionaler Benutzer-Account für das Eigentümer-Portal.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='eigentuemer_profil',
                to='auth.user',
                verbose_name='Portal-Login',
            ),
        ),
    ]
