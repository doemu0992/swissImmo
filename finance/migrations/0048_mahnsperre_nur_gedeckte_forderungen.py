"""Mahnsperre aus Zahlungsvereinbarungen: vom Mieter auf die gedeckten Forderungen.

WAS SICH ÄNDERT

Bis 26.10.2026 setzte `core.services.zahlungsvereinbarung.anlegen` beim Erfassen
eines Ratenplans das Häkchen `crm.Mieter.mahnsperre` — und hob es beim Erfüllen,
Brechen oder Abbrechen wieder auf. Das Häkchen sperrt den ganzen Mieter: Auch jede
NEUE Monatsmiete, die während des Ratenplans fällig wurde, blieb ungemahnt. Seither
sperrt eine aktive Vereinbarung nur die Forderungen, die sie deckt
(`zahlungsvereinbarung.ist_durch_vereinbarung_gesperrt`); `Mieter.mahnsperre`
bleibt ein reiner Handschalter der Verwaltung.

WAS DIESE MIGRATION TUT

Für jeden Mieter mit einer Vereinbarung im Status `aktiv` wird `mahnsperre` auf
False gesetzt. Das Häkchen stammt bei ihnen mit grosser Wahrscheinlichkeit aus dem
Dienst, nicht von Hand: `anlegen` hat es in genau diesem Fall immer gesetzt. Die
gedeckten Forderungen bleiben über die Vereinbarung gesperrt — für sie ändert sich
nichts. Neu gemahnt werden nur Forderungen ausserhalb des Ratenplans.

DIE GRENZE

Ob ein Mieter das Häkchen ZUSÄTZLICH von Hand gesetzt hatte, lässt sich im Bestand
nicht unterscheiden — es gibt kein Protokoll dazu. Wer es bewusst gesetzt hatte,
muss es nach dieser Migration auf der Personenakte wieder setzen. Mieter OHNE
aktive Vereinbarung behalten ihr Häkchen unverändert.

Rückwärts nicht umkehrbar (noop): Welche Mieter vorher gesperrt waren, ist
nach dem Lauf nicht mehr bekannt, und ein pauschales Wiedersetzen wäre falsch.
"""
from django.db import migrations


def mahnsperre_aus_vereinbarung_loesen(apps, schema_editor):
    # Historische Modelle tragen keinen Mandantenfilter; die Migration läuft
    # bewusst über alle Organisationen — die Regel ist für alle dieselbe.
    Zahlungsvereinbarung = apps.get_model('finance', 'Zahlungsvereinbarung')
    Mieter = apps.get_model('crm', 'Mieter')
    mieter_ids = set(Zahlungsvereinbarung.objects.filter(status='aktiv')
                     .values_list('vertrag__mieter_id', flat=True))
    mieter_ids.discard(None)
    if mieter_ids:
        Mieter.objects.filter(pk__in=mieter_ids, mahnsperre=True).update(mahnsperre=False)


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0047_betreibung_vertieft'),
        ('crm', '0052_mitgliedschaft_schwerpunkt'),
    ]

    operations = [
        migrations.RunPython(mahnsperre_aus_vereinbarung_loesen, migrations.RunPython.noop),
    ]
