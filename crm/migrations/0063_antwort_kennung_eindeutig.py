from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0062_antwort_kennung_vergeben"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organisation",
            name="antwort_kennung",
            field=models.CharField(blank=True, editable=False, max_length=40, unique=True,
                                   verbose_name="Antwort-Kennung"),
        ),
    ]
