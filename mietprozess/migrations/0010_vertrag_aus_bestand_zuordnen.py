"""Bestehende Bewerbungen ihrem Vertragsentwurf zuordnen — nur wo eindeutig.

Bis 10/2026 kannte eine Bewerbung ihren Vertrag nicht. `fw_bewerbung_zu_vertrag`
fand ihn über Name und E-Mail des Mieters auf derselben Einheit. Dieselbe
Suche ordnet hier den Bestand zu, aber enger:

* nur Bewerbungen mit Status «zugesagt» — nur sie hat die Umwandlung erzeugt;
* nur Verträge auf derselben Einheit, die nicht vor der Bewerbung beginnen —
  sonst träfe ein früheres, längst beendetes Mietverhältnis derselben Person;
* nur bei genau EINEM Treffer, und nur wenn kein zweiter Bewerber denselben
  Vertrag beansprucht.

Alles andere bleibt leer und steht danach als «zugesagt · Vertrag noch nicht
erzeugt» auf dem Board. Ein fehlender Bezug fällt dort auf und lässt sich
mit einem Klick nachholen; ein falscher sähe richtig aus.

Die Einheit legt die Organisation fest (beide Seiten hängen an ihr), eine
Zuordnung über die Mandantengrenze ist damit ausgeschlossen. Historische
Modelle tragen keinen Mandantenfilter — hier ist das gewollt, der Lauf geht
über den ganzen Bestand.
"""
from collections import Counter

from django.db import migrations


def kandidaten(apps):
    """{bewerbung_id: vertrag_id} für alle eindeutigen Fälle."""
    Mietbewerbung = apps.get_model('mietprozess', 'Mietbewerbung')
    Mietvertrag = apps.get_model('rentals', 'Mietvertrag')
    vergeben = set(Mietbewerbung.objects.filter(vertrag__isnull=False)
                   .values_list('vertrag_id', flat=True))

    gefunden = {}
    offen = (Mietbewerbung.objects.filter(status='zugesagt', vertrag__isnull=True)
             .exclude(vorname='Anonymisiert'))
    for b in offen:
        vertraege = Mietvertrag.objects.filter(einheit_id=b.einheit_id,
                                               beginn__gte=b.erstellt_am.date())
        treffer = set()
        if b.email and b.nachname:
            treffer |= set(vertraege.filter(mieter__email__iexact=b.email,
                                            mieter__nachname__iexact=b.nachname)
                           .values_list('pk', flat=True))
        if b.vorname and b.nachname:
            treffer |= set(vertraege.filter(mieter__vorname__iexact=b.vorname,
                                            mieter__nachname__iexact=b.nachname)
                           .values_list('pk', flat=True))
        treffer -= vergeben
        if len(treffer) == 1:
            gefunden[b.pk] = treffer.pop()

    mehrfach = {v for v, n in Counter(gefunden.values()).items() if n > 1}
    return {b: v for b, v in gefunden.items() if v not in mehrfach}


def zuordnen(apps, schema_editor):
    Mietbewerbung = apps.get_model('mietprozess', 'Mietbewerbung')
    for bewerbung_id, vertrag_id in kandidaten(apps).items():
        # `update()` statt `save()`: Der Zeitstempel `aktualisiert_am` bleibt —
        # an ihm hängen die Löschfristen nach DSG.
        Mietbewerbung.objects.filter(pk=bewerbung_id).update(vertrag_id=vertrag_id)


class Migration(migrations.Migration):

    dependencies = [
        ('mietprozess', '0009_vertrag_pruefung_ablage'),
    ]

    operations = [
        migrations.RunPython(zuordnen, migrations.RunPython.noop),
    ]
