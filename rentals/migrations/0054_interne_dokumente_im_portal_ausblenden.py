"""Interne Schreiben aus dem Mieterportal nehmen (ROUTE-01).

Bis 28.10.2026 legte schon das blosse Öffnen einer PDF-Vorschau (GET) das
Dokument in der Vertragsakte ab, und der Standard von `im_portal_sichtbar`
war «sichtbar». Zwei Arten von Dokumenten sind nie für den Mieter bestimmt und
konnten so trotzdem bei ihm landen:

- «Betreibungsbegehren (Daten) …»: das interne Datenblatt für das Betreibungsamt
- «Kaution-Freigabe (Bank) …»: das Freigabeschreiben an die Bank

Beide werden ausgeblendet. Die Verwaltung kann sie in der Person-Akte wieder
freigeben. Die 257d-Mahnungen bleiben unberührt: Ob eine Mahnung dem Mieter
zugestellt wurde, lässt sich aus den Daten nicht sicher ableiten (E-Mail-Kopie
versandt oder nur angesehen) — diese Fälle prüft die Verwaltung von Hand, siehe
Bericht zu ROUTE-01.

Rückwärts: nichts zu tun. Welche Dokumente vorher sichtbar waren, ist nicht
festgehalten; sie bleiben ausgeblendet.
"""
from django.db import migrations

INTERNE_TITEL = ('Betreibungsbegehren (Daten)', 'Kaution-Freigabe (Bank)')


def ausblenden(apps, schema_editor):
    Dokument = apps.get_model('rentals', 'Dokument')
    for praefix in INTERNE_TITEL:
        Dokument.objects.filter(bezeichnung__startswith=praefix,
                                im_portal_sichtbar=True).update(im_portal_sichtbar=False)


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0053_dokument_portal_standard_unsichtbar'),
    ]

    operations = [
        migrations.RunPython(ausblenden, migrations.RunPython.noop),
    ]
