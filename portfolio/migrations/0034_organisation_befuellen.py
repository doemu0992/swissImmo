"""Etappe 5, PR 1 — Schritt 2 von 3: den Bestand aus der Kette ableiten.

Reihenfolge ist hier keine Geschmacksfrage. `Liegenschaft` traegt die
Organisation selbst und ist der Anker; alle anderen leiten von ihr ab. Wird sie
nicht zuerst versorgt, erben die zwoelf abgeleiteten Modelle deren Luecken.

WAS MIT LIEGENSCHAFTEN OHNE ORGANISATION GESCHIEHT

Bis Etappe 5 war `Liegenschaft.organisation` optional. Es kann also
Bestandsdatensaetze ohne Bezug geben. Sie bekommen die AELTESTE Organisation —
dieselbe Regel, nach der Etappe 4.1 den Bestand zugeordnet hat
(`crm/0034_bestand_der_organisation_zuordnen.py`, `order_by('pk').first()`).
Das ist korrekt, solange es genau eine Organisation gibt, und das ist der
heutige Zustand: Die Anwendung ist einmandantig, Phase 2 macht sie erst
mehrmandantig. Gaebe es bereits mehrere, waere die Zuordnung eine fachliche
Frage und nicht Sache einer Migration — deshalb bricht sie dann ab, statt zu
raten.

RUECKWAERTS ist verlustfrei: Schritt 1 nimmt die Spalten ohnehin wieder mit.
"""
from django.db import migrations


MODELLE_UEBER_LIEGENSCHAFT = [
    ('LiegenschaftVerteilschluessel', 'liegenschaft'),
    ('Schluessel', 'liegenschaft'),
    ('Unterhalt', 'liegenschaft'),
    ('Versicherung', 'liegenschaft'),
    ('Wartungsfrist', 'liegenschaft'),
]

MODELLE_UEBER_EINHEIT = [
    ('Ausstattung', 'einheit'),
    ('EinheitFoto', 'einheit'),
    ('Sollmietzins', 'einheit'),
    ('StaffelVorlage', 'einheit'),
    ('Verteilschluessel', 'einheit'),
]


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    Liegenschaft = apps.get_model('portfolio', 'Liegenschaft')

    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        # Frische Datenbank (Testlauf, Neuinstallation): nichts zuzuordnen.
        # Der Bestand ist leer, die Spalten bleiben leer, Schritt 3 setzt die
        # Pflicht auf eine leere Tabelle — das geht.
        return
    ausgangs_organisation = organisationen[0]

    # --- Anker zuerst -----------------------------------------------------
    ohne_bezug = Liegenschaft.objects.filter(organisation__isnull=True)
    anzahl = ohne_bezug.count()
    if anzahl:
        if len(organisationen) > 1:
            raise RuntimeError(
                f'{anzahl} Liegenschaft(en) ohne Organisation, aber es gibt mehr '
                f'als eine Organisation. Welche zustaendig ist, ist eine fachliche '
                f'Frage — diese Migration entscheidet sie nicht. Bitte den Bezug '
                f'von Hand setzen und die Migration erneut starten.')
        ohne_bezug.update(organisation=ausgangs_organisation)

    # Je Organisation EIN `UPDATE`, nicht je Zeile. Ein Lauf ueber die
    # Bestandsdatensaetze einzeln waere auf der Produktion Tausende Queries fuer
    # ein Ergebnis, das eine einzige `IN`-Bedingung erzeugt.
    def uebertragen(traeger, ziel_modell, feld):
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True)
            ziel_modell.objects.filter(**{f'{feld}_id__in': list(traeger_ids)}).update(
                organisation_id=organisation_id)

    # --- ein Glied entfernt ----------------------------------------------
    for modellname, feld in MODELLE_UEBER_LIEGENSCHAFT:
        uebertragen(Liegenschaft, apps.get_model('portfolio', modellname), feld)

    # --- zwei Glieder entfernt (die Einheit traegt jetzt selbst) ----------
    Einheit = apps.get_model('portfolio', 'Einheit')
    uebertragen(Liegenschaft, Einheit, 'liegenschaft')
    for modellname, feld in MODELLE_UEBER_EINHEIT:
        uebertragen(Einheit, apps.get_model('portfolio', modellname), feld)

    # --- drei Glieder entfernt -------------------------------------------
    Schluessel = apps.get_model('portfolio', 'Schluessel')
    uebertragen(Schluessel, apps.get_model('portfolio', 'SchluesselAusgabe'), 'schluessel')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf.

    Der Anker (`Liegenschaft.organisation`) behaelt seinen Wert. Ihn zu leeren
    waere Datenverlust ohne Gegenwert: Die Spalte gab es schon vor dieser
    Migration, und wer rueckwaerts geht, will den Umbau zuruecknehmen, nicht die
    Zuordnung aus Etappe 4.1.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0033_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
