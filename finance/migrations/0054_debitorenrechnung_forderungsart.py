# Art der Forderung an der Debitorenrechnung (Audit MIET-02, Art. 257d OR).

from django.db import migrations, models

#: Die Titel der beiden Wege, die eine Forderung für Mietzins oder Nebenkosten anlegen:
#: die monatliche Sollstellung (`core/services/automation.py`) und die Nachzahlung der
#: Nebenkostenabrechnung (`core/views/fw/nebenkosten.py`). Der Bestand erkennt die Sollstellung an
#: demselben Titel (`faelle/lauf_dienst.py`, `core/services/inbox.py`).
MIETE_TITEL = ('Miete & NK ', 'NK-Abrechnung Nachzahlung')


def bestand_einordnen(apps, schema_editor):
    """Alles, was nicht eindeutig Mietzins oder Nebenkosten ist, wird «sonstige Forderung».

    Im Bestand entstehen Forderungen nur über benannte Wege (Sollstellung, NK-Nachzahlung, Weiterverrechnung,
    Selbstbehalt, Schlussabrechnung, Schadenersatz, Betreibungskosten, Nutzungsentschädigung, Mahngebühr/Zins,
    freie Rechnung). Die Titel der ersten beiden sind fest; was darüber hinaus gilt, wäre geraten und bleibt
    bewusst ausserhalb der Fristansetzung (konservativ: lieber eine Forderung zu wenig nennen als eine zu viel).
    Eine Forderung mit Stammrechnung (Mahngebühr, Zins) ist nie Mietzins.
    """
    DebitorenRechnung = apps.get_model('finance', 'DebitorenRechnung')
    manager = DebitorenRechnung._base_manager
    miete = models.Q(stammrechnung__isnull=True, quell_kreditor__isnull=True)
    titel = models.Q()
    for praefix in MIETE_TITEL:
        titel |= models.Q(titel__startswith=praefix)
    manager.exclude(miete & titel).update(forderungsart='sonstige')


def zurueck(apps, schema_editor):
    """Rückwärts gibt es nichts zu tun: Das Feld verschwindet mit der Schemaänderung."""


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0053_datum_vorgabe_zuercher_tag"),
    ]

    operations = [
        migrations.AddField(
            model_name="debitorenrechnung",
            name="forderungsart",
            field=models.CharField(
                choices=[
                    ("miete", "Mietzins / Nebenkosten (Art. 257d OR)"),
                    ("sonstige", "Sonstige Forderung"),
                ],
                default="miete",
                max_length=10,
                verbose_name="Art der Forderung",
            ),
        ),
        migrations.RunPython(bestand_einordnen, zurueck),
    ]
