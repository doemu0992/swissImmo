"""Etappe 5, PR 7 — Schritt 2 von 3: den Bestand versorgen.

Reihenfolge ist wieder Abhaengigkeit: `KreditorenRechnung` und
`DebitorenRechnung` muessen vor den Modellen laufen, die von ihnen ableiten
(`KreditorPosition`, `KreditorenZahlung`, `Mahnung`, `Zahlungseingang`).

WAS MIT DEM REST GESCHIEHT

Nach den Ketten bleiben Datensaetze uebrig, deren Wege alle leer sind — auf der
Produktion die eine stornierte `DebitorenRechnung` Nr. 35. Sie bekommen die
Ausgangsorganisation, nach derselben Regel wie ueberall: eine Organisation →
zuordnen, mehrere → abbrechen.

Ein Storno wird dabei ausdruecklich ZUGEORDNET und nicht geloescht. Es ist Teil
der Buchhaltung, nicht deren Abfall — eine Migration, die Buchungsbelege
wegraeumt, weil sie unbequem sind, waere ein Revisionsproblem.
"""
from django.db import migrations


#: (Modell, Traegermodell-App, Traegermodell, Feld) — in Abhaengigkeitsreihenfolge.
ABLEITUNGEN = [
    # zuerst die Traeger selbst
    ('KreditorenRechnung', 'portfolio', 'Einheit',       'einheit'),
    ('KreditorenRechnung', 'portfolio', 'Liegenschaft',  'liegenschaft'),
    ('KreditorenRechnung', 'finance',   'Buchungskonto', 'konto'),
    ('DebitorenRechnung',  'rentals',   'Mietvertrag',   'vertrag'),
    ('DebitorenRechnung',  'portfolio', 'Einheit',       'einheit'),
    ('DebitorenRechnung',  'portfolio', 'Liegenschaft',  'liegenschaft'),
    ('DebitorenRechnung',  'finance',   'Buchungskonto', 'konto_haben'),
    # dann, was von ihnen abhaengt
    ('KreditorPosition',   'finance',   'KreditorenRechnung', 'rechnung'),
    ('KreditorenZahlung',  'finance',   'KreditorenRechnung', 'kreditor'),
    ('Mahnung',            'finance',   'DebitorenRechnung',  'debitoren_rechnung'),
    ('Mahnung',            'rentals',   'Mietvertrag',        'vertrag'),
    ('Zahlungseingang',    'rentals',   'Mietvertrag',        'vertrag'),
    ('Zahlungseingang',    'portfolio', 'Liegenschaft',       'liegenschaft'),
    ('Zahlungseingang',    'finance',   'DebitorenRechnung',  'debitoren_rechnung'),
    ('Zahlungseingang',    'finance',   'Buchungskonto',      'konto'),
]

#: Alle sieben — auch die, die nur den Rueckfall bekommen.
ALLE = ['KreditorenRechnung', 'DebitorenRechnung', 'KreditorPosition',
        'KreditorenZahlung', 'Mahnung', 'Zahlungseingang', 'EigentuemerAuszahlung']


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        return                      # frische Datenbank, nichts zuzuordnen
    ausgangs_organisation = organisationen[0]

    def uebertragen(traeger, ziel_modell, feld):
        """Je Organisation EIN `UPDATE`, und nur auf noch leere Zeilen.

        `organisation__isnull=True` ist hier nicht Kosmetik: Die Wege werden der
        Reihe nach abgearbeitet, und der erste, der traegt, soll gewinnen. Ohne
        die Bedingung ueberschriebe der letzte Weg alles zuvor Gesetzte.
        """
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            (ziel_modell.objects
             .filter(**{f'{feld}_id__in': traeger_ids, 'organisation__isnull': True})
             .update(organisation_id=organisation_id))

    for modellname, traeger_app, traeger_name, feld in ABLEITUNGEN:
        uebertragen(apps.get_model(traeger_app, traeger_name),
                    apps.get_model('finance', modellname), feld)

    # --- Rest: kein Weg trug --------------------------------------------
    for modellname in ALLE:
        modell = apps.get_model('finance', modellname)
        offen = modell.objects.filter(organisation__isnull=True)
        anzahl = offen.count()
        if not anzahl:
            continue
        if len(organisationen) > 1:
            raise RuntimeError(
                f'{anzahl} {modellname}-Datensatz/-saetze ohne ableitbaren Bezug, '
                f'aber es gibt mehr als eine Organisation. Welche zustaendig ist, '
                f'entscheidet diese Migration nicht.')
        offen.update(organisation=ausgangs_organisation)


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('rentals', '0034_organisation_pflicht'),
        ('finance', '0038_organisation_rest_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
