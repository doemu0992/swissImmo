from django.db import migrations, models


class Migration(migrations.Migration):
    """Antwortadresse der Plattform je Verwaltung (Schritt 1 von 3: Felder, noch nicht eindeutig).

    Die Eindeutigkeit folgt in 0063, nachdem 0062 jeder bestehenden Verwaltung eine Kennung gegeben hat —
    zwei leere Kennungen wären sonst ein Konflikt."""

    dependencies = [
        ("crm", "0060_organisation_adress_versatz"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="antwort_kennung",
            field=models.CharField(blank=True, default="", editable=False, max_length=40,
                                   verbose_name="Antwort-Kennung"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="antwort_kennung_alt",
            field=models.CharField(blank=True, db_index=True, default="", editable=False, max_length=40,
                                   verbose_name="Vorherige Antwort-Kennung"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="antwort_kennung_alt_bis",
            field=models.DateTimeField(blank=True, editable=False, null=True,
                                       verbose_name="Vorherige Kennung gueltig bis"),
        ),
    ]
