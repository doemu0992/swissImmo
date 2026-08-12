"""Datenkorrektur: Mahn-Historie mit stornierten Mahngebühren abgleichen.

Vor dem Fix wurde beim Erfassen einer Mahnung eine hartcodierte Gebühr (z.B.
40.-) gebucht, obwohl beim Mandanten 0.- konfiguriert war. Nutzer haben die
falsche Mahngebühr-Rechnung storniert (revisionssicher, Gegenbuchung) — die
Mahn-Historie (finance.Mahnung.gebuehr) zeigte die Gebühr aber weiter an.

Diese Migration setzt gebuehr in der Historie auf 0, WENN zur Mahnung keine
aktive (nicht-stornierte) Mahngebühr-Rechnung mehr existiert. Sie fasst nur
Einträge an, deren Gebühren-Rechnung tatsächlich storniert wurde — legitime,
noch offene/bezahlte Gebühren bleiben unangetastet. Idempotent.
"""
import re

from django.db import migrations


def reconcile(apps, schema_editor):
    Mahnung = apps.get_model('finance', 'Mahnung')
    DebitorenRechnung = apps.get_model('finance', 'DebitorenRechnung')
    for mn in Mahnung.objects.filter(gebuehr__gt=0, debitoren_rechnung__isnull=False):
        titel = f"Mahngebühr {mn.stufe}. Mahnung"
        fees = DebitorenRechnung.objects.filter(
            stammrechnung_id=mn.debitoren_rechnung_id, titel=titel)
        if not fees.exists():
            # Keine zuordenbare Gebühren-Rechnung (z.B. Alt-Daten) — nicht anfassen.
            continue
        if fees.exclude(status='storniert').exists():
            # Es gibt noch eine gültige Gebühren-Rechnung → Gebühr ist berechtigt.
            continue
        alt = mn.gebuehr
        mn.gebuehr = 0
        verm = f"Mahngebühr CHF {alt} storniert"
        mn.bemerkung = (f"{mn.bemerkung} · {verm}" if mn.bemerkung else verm)[:255]
        mn.save(update_fields=['gebuehr', 'bemerkung'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0031_alter_nebenkostenbeleg_verteilschluessel'),
    ]

    operations = [
        migrations.RunPython(reconcile, noop),
    ]
