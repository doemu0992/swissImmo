# Etappe 4.1: crm.Verwaltung heisst ab hier crm.Organisation.
#
# `Verwaltung` war der Singleton der einen Verwaltung — 23 Felder, an 79
# Stellen im Produktivcode über `.objects.first()` gelesen. Ab Phase 2 ist sie
# der Mandant im SaaS-Sinn, und der heisst durchgängig `Organisation`.
#
# Entschieden am 15.08.2026 (Weg A, siehe docs/ETAPPE-4-ORGANISATION.md): eine
# Umbenennung statt eines zweiten Modells. Bei 79 Fundstellen ist der Weg mit
# zwei Modellen der, bei dem Fehler entstehen — jede Stelle müsste einzeln
# entscheiden, welches der beiden sie meint.
#
# OHNE DATENRISIKO: `Meta.db_table = 'core_verwaltung'` ist festgeschrieben und
# bleibt es. Django benennt deshalb KEINE Tabelle um — `RenameModel` ist hier
# eine reine Zustandsoperation. Genau wie bei Mandant → Eigentuemer in E3.
#
# Das Feld `Liegenschaft.verwaltung` wandert mit: Ein Fremdschlüssel namens
# `verwaltung`, der auf eine `Organisation` zeigt, wäre die Art halber
# Umbenennung, vor der E3 gewarnt hat — Code mit zwei Bedeutungen desselben
# Wortes. `RenameField` benennt die Spalte tatsächlich um; das ist gewollt und
# auf SQLite wie PostgreSQL verlustfrei.
from django.db import migrations


class Migration(migrations.Migration):

    # Wie bei crm/0029: Die Fremd-Apps stehen hier nicht aus Höflichkeit,
    # sondern weil ihre ALTEN Migrationen `to='crm.verwaltung'` schreiben
    # (portfolio/0001_initial). Ohne diese Kanten darf Django die Umbenennung
    # irgendwo nach crm/0031 einsortieren — auch VOR portfolio/0031. Beim
    # Neuaufbau (Testlauf, frische Datenbank) bricht der Graph dann mit
    # „Related model 'crm.verwaltung' cannot be resolved". Auf einer bereits
    # migrierten Datenbank fällt das NICHT auf, weil dort nur die neuen
    # Migrationen laufen — der Fehler träfe erst den nächsten frischen Aufbau.
    dependencies = [
        ('crm', '0031_alter_eigentuemer_benutzer'),
        ('portfolio', '0031_liegenschaft_eigentuemer'),
        ('finance', '0034_alter_eigentuemerauszahlung_eigentuemer'),
        ('rentals', '0031_dokument_eigentuemer'),
    ]

    operations = [
        migrations.RenameModel(old_name='Verwaltung', new_name='Organisation'),
        migrations.AlterModelOptions(
            name='organisation',
            options={'verbose_name': 'Organisation',
                     'verbose_name_plural': 'Organisationen'},
        ),
    ]
