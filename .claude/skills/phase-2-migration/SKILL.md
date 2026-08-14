---
name: phase-2-migration
description: Rezepte, um einem bestehenden swissImmo-Modell den Organisationsbezug nachzurüsten — drei verschiedene Wege je nach Modellgruppe, plus die Datenmigration über den Produktivbestand. Nutze diesen Skill immer, wenn eine Migration für Mandantenfähigkeit geschrieben wird, wenn ein Modell eine organisation-Spalte bekommen soll, wenn Unique-Constraints umgebaut werden, oder wenn zu klären ist, ob ein Modell überhaupt einen eigenen Bezug braucht.
---

# Organisationsbezug nachrüsten

Nicht jedes Modell braucht eine eigene `organisation`-Spalte. Der falsche Weg kostet entweder eine überflüssige Denormalisierung oder ein Datenleck. Zuerst einordnen, dann migrieren.

## Einordnung

Die Frage lautet: **Führt vom Modell ein Weg zur `Liegenschaft`, und ist dieser Weg pflichtig?**

```bash
# Gruppe eines Modells bestimmen — folgt allen Fremdschlüsseln bis Tiefe 4
python manage.py shell -c "
from django.apps import apps
m = apps.get_model('finance', 'Buchung')
for f in m._meta.concrete_fields:
    if f.is_relation and f.many_to_one:
        print(f.name, '->', f.related_model.__name__, '| null:', f.null)
"
```

| Gruppe | Kriterium | Weg | Anzahl im Bestand |
|---|---|---|---|
| **C** | geschlossene Pflicht-Kette zur Liegenschaft | Rezept C — denormalisierte Spalte, aus der Kette befüllt | 34 |
| **B** | Weg existiert, aber über `null=True` | Rezept B — Spalte, Bestand nachziehen, Kette pflichtig machen | 15 |
| **A** | kein Weg | Rezept A — fachliche Entscheidung, dann Spalte | 14 |

Gruppe A umfasst unter anderem `crm.Verwaltung`, `crm.Mandant`, `crm.Mieter`, `crm.Handwerker`, `crm.Vorlage`, `finance.Buchungskonto`, `finance.LieferantProfil`, `finance.NebenkostenLernRegel`, `finance.Kontoauszug`, `finance.EigentuemerAuszahlung`, `finance.Erneuerungsfonds`, `portfolio.Lebensdauer`, `core.AktivitaetsLog`.

## Rezept C — Pflicht-Kette vorhanden

Die Kette allein würde technisch genügen. Trotzdem eine denormalisierte Spalte anlegen: Ein Join über vier Ebenen bei jeder Query ist teuer, und der Manager muss ohne Join filtern können.

Drei getrennte Migrationen, in dieser Reihenfolge:

```python
# 0042_buchung_organisation.py — Spalte, zunächst nullable
migrations.AddField(
    model_name='buchung',
    name='organisation',
    field=models.ForeignKey('core.Organisation', on_delete=models.CASCADE,
                            null=True, related_name='buchungen'),
)
```

```python
# 0043_buchung_organisation_befuellen.py — Bestand aus der Kette ableiten
def befuellen(apps, schema_editor):
    Buchung = apps.get_model('finance', 'Buchung')
    # Chargenweise: der Produktivbestand passt nicht in den Speicher
    for b in Buchung.objects.filter(organisation__isnull=True).iterator(chunk_size=500):
        Buchung.objects.filter(pk=b.pk).update(
            organisation_id=b.liegenschaft.organisation_id)

def zurueck(apps, schema_editor):
    # Rückwärts ist verlustfrei: die Spalte verschwindet ohnehin
    pass
```

```python
# 0044_buchung_organisation_pflicht.py — erst wenn nichts mehr null ist
migrations.AlterField(..., null=False)
```

Nie in einer Migration zusammenfassen. Bricht die Datenmigration auf halber Strecke ab, muss der Zustand davor wiederherstellbar sein.

## Rezept B — Weg nur über optionale Fremdschlüssel

Hier steckt vor der Migration eine Datenfrage: **Es gibt Bestandsdatensätze ohne jede Beziehung.** Diese lassen sich nicht ableiten.

Zuerst zählen:

```bash
python manage.py shell -c "
from finance.models import KreditorenRechnung as M
print('gesamt      ', M.objects.count())
print('ohne Bezug  ', M.objects.filter(liegenschaft__isnull=True).count())
"
```

Ist die Zahl null, wie Rezept C verfahren. Ist sie grösser null, gehört sie **vorgelegt** — die Waisen sind entweder Datenmüll (löschen), Altlasten einer einzigen Verwaltung (der Ausgangsorganisation zuweisen) oder ein fachlicher Fall, der übersehen wurde. Diese Entscheidung nicht selbst treffen.

Nach der Migration die Kette pflichtig machen, damit keine neuen Waisen entstehen.

## Rezept A — kein Weg vorhanden

Erst die fachliche Frage klären, dann Code schreiben. Für jedes Modell:

**Gehört es je Organisation?** Dann Spalte, und der Bestand wird für die Ausgangsorganisation behalten. Bei Stammdaten, die jede Verwaltung neu aufbaut — Buchungskonten, Lieferantenprofile, Vorlagen, Lernregeln — ist das der Normalfall.

**Ist es echte Referenzdatei für alle?** Dann keine Spalte, aber ausdrücklich als solche kennzeichnen und schreibgeschützt stellen. `portfolio.Lebensdauer` ist ein Kandidat: eine Lebensdauertabelle nach Branchenstandard ist keine Kundeneigenschaft. Nur dann global lassen, wenn niemand sie je bearbeiten darf.

**`core.AktivitaetsLog` ist der heikelste Fall.** Der Audit-Trail muss die Organisation tragen, und er ist das Modell, das man am wenigsten nachträglich umschreiben möchte — je später, desto mehr Zeilen. Früh angehen.

## Unique-Constraints umbauen

```python
migrations.RemoveConstraint(...)  # bzw. AlterField mit unique=False
migrations.AddConstraint(
    model_name='buchungskonto',
    constraint=models.UniqueConstraint(
        fields=['organisation', 'nummer'], name='uniq_konto_je_organisation'),
)
```

Bekannte Fälle: `Buchungskonto.nummer`, `NebenkostenLernRegel.suchwort`, `LieferantProfil.name_key`, `Buchung.beleg_nr`, `ZahlerZuordnung.name_norm`, `Lebensdauer.kategorie`.

Bei `Buchung.beleg_nr` reicht die Constraint nicht: Auch die **Vergabe** der Nummer muss je Organisation zählen, sonst entstehen Lücken, aus denen sich die Buchungsmenge fremder Mandanten ablesen lässt.

## Vor dem PR

```bash
python manage.py makemigrations --check --dry-run   # muss leer sein
python manage.py migrate                            # vorwärts
python manage.py migrate <app> <vorherige_nummer>   # rückwärts, muss auch laufen
```

Die Rückwärtsmigration wird gern vergessen und ist genau dann wichtig, wenn ein Deployment schiefgeht. Einmal gelaufen zu sein ist die Mindestanforderung.

Zusätzlich zur normalen Testsuite gehört zu jeder dieser Migrationen ein Test, der prüft, dass nach der Migration **kein** Datensatz ohne Organisation existiert.
