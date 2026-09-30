"""Der Auszug als EIN Vorgang: der Fall «Mieterwechsel» begleitet ihn von der Kündigung bis zur Kaution.

Stresstest 30.09.2026: Kündigung → Abnahme → Schlussabrechnung → Kaution → Leerstand →
Neuvermietung existierten als neun lose Pendenzen mit Stichwort-Abgleich. Die
Fallart «Mieterwechsel» (`manage.py fallarten_anlegen`) gab es, aber kein Code
eröffnete je einen Fall; niemand sah den Vorgang als Ganzes.

Jetzt:

· Die Kündigung eröffnet den Fall (nur wenn die Organisation die Fallart
  eingerichtet hat — sonst bleibt es bei den Pendenzen, nichts wird aufgezwungen).
· Dieselben Ereignisse, die Pendenzen abhaken (`erledige_pendenzen_fuer`),
  haken die zugehörigen Fallschritte ab. Eine zweite Buchführung gibt es nicht:
  die Stichwörter sind dieselben.
· Sind alle Pflichtschritte erledigt, schliesst sich der Fall.

Zuordnung Stichwort → Schritt als Tabelle, nicht als Logik: Eine Verwaltung darf
ihre Schrittbezeichnungen ändern (Schrittvorlagen sind Daten); passt eine nicht
mehr, bleibt der Schritt offen und wird von Hand abgehakt — nie falsch abgehakt.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

FALLART_SCHLUESSEL = 'mieterwechsel'

#: Stichwort (wie in `erledige_pendenzen_fuer`) → Teile der Schrittbezeichnung.
STICHWORT_SCHRITTE = {
    'schriftlich': ('Kündigungsbestätigung',),
    'Kündigungsformular': ('Kündigungsbestätigung',),
    'Abnahmetermin': ('Rückgabetermin',),
    'Wohnungsabnahme': ('Protokoll erfassen',),
    'Zählerstände': ('Zählerstände und Schlüssel',),
    'Schlüssel': ('Zählerstände und Schlüssel',),
    'Mängelrüge Art. 267a': ('Protokoll erfassen',),
    'Schlussabrechnung': ('Mängel bewerten', 'Nebenkosten anteilig'),
    'Kaution': ('Kaution abrechnen',),
}


def _fall_des_vertrags(vertrag):
    from django.contrib.contenttypes.models import ContentType

    from faelle.models import Fall
    ct = ContentType.objects.get_for_model(type(vertrag))
    return (Fall.objects.offen()
            .filter(akte_typ=ct, akte_id=vertrag.pk, fallart__schluessel=FALLART_SCHLUESSEL)
            .first())


def eroeffnen(vertrag, benutzer=None):
    """Eröffnet den Mieterwechsel-Fall (idempotent) und hakt «Kündigung erfassen» ab.
    Gibt den Fall zurück oder None, wenn die Fallart nicht eingerichtet ist."""
    from core.tenancy import organisation_kontext
    from faelle.models import Fall, Fallart

    with organisation_kontext(vertrag.organisation):
        art = Fallart.objects.filter(schluessel=FALLART_SCHLUESSEL, aktiv=True).first()
        if art is None:
            return None
        fall = _fall_des_vertrags(vertrag)
        if fall is None:
            fall = Fall(fallart=art, akte=vertrag, zustaendig=benutzer,
                        betreff=f'Mieterwechsel {vertrag.mieter.display_name} – {vertrag.einheit.bezeichnung}')
            fall.save()
            fall.schritte_anlegen()
        _abhaken(fall, ('Kündigung erfassen',), benutzer)
        return fall


def _abhaken(fall, teile, benutzer=None):
    n = 0
    for schritt in fall.schritte.filter(erledigt_am__isnull=True):
        if any(t.lower() in schritt.bezeichnung.lower() for t in teile):
            schritt.erledigen(benutzer)
            n += 1
    return n


def schritte_abhaken(vertrag, stichwoerter, benutzer=None):
    """Hakt die Fallschritte zu den Stichwörtern ab; schliesst den Fall, wenn alle
    Pflichtschritte erledigt sind. Ohne Fall: nichts. Gibt die Zahl abgehakter Schritte."""
    from core.tenancy import organisation_kontext

    if vertrag is None or not getattr(vertrag, 'pk', None):
        return 0
    with organisation_kontext(vertrag.organisation):
        fall = _fall_des_vertrags(vertrag)
        if fall is None:
            return 0
        teile = []
        for kw in stichwoerter:
            teile.extend(STICHWORT_SCHRITTE.get(kw, ()))
        n = _abhaken(fall, tuple(teile), benutzer) if teile else 0
        if n:
            _schliessen_wenn_fertig(fall)
        return n


def _schliessen_wenn_fertig(fall):
    from faelle.models import Fall
    if fall.schritte.filter(pflicht=True, erledigt_am__isnull=True).exists():
        return False
    jetzt = timezone.now()
    fall.status = Fall.ABGESCHLOSSEN
    fall.abgeschlossen_am = jetzt
    fall.letzte_bewegung = jetzt
    fall.save(update_fields=['status', 'abgeschlossen_am', 'letzte_bewegung'])
    return True


#: Schritte der Vermietung, die mit einem aktiven Nachmieter erledigt sind.
NACHMIETER_SCHRITTE = ('Exposé', 'Auf Kanälen', 'Besichtigung', 'Bewerbungen prüfen',
                       'Zuschlag', 'Vertrag erstellen')


def nachmieter_aktiv(alter_vertrag, neuer_vertrag=None, benutzer=None):
    """Ein Nachfolger-Vertrag ist aktiv: Ausschreibung bis Vertragsabschluss sind getan.

    Zwei weitere Schritte erledigen sich nur, wenn der Nachfolger es hergibt:

    · «Anfangsmietzins prüfen» — wenn der neue Nettomietzins den alten nicht
      übersteigt (keine Erhöhung gegenüber dem Vormieter, die eine Formularpflicht
      auslösen könnte). Steigt er, bleibt der Schritt für einen Menschen offen.
    · «Kaution einfordern» — wenn der Nachfolger keine Kaution hat oder sie schon
      einbezahlt ist (sonst beim Einzahlen, `kaution_einbezahlt`).

    Kaution, Abnahme und Endabrechnung des Vorgängers bleiben seine Sache.
    """
    from core.tenancy import organisation_kontext

    with organisation_kontext(alter_vertrag.organisation):
        fall = _fall_des_vertrags(alter_vertrag)
        if fall is None:
            return 0
        teile = list(NACHMIETER_SCHRITTE)
        if neuer_vertrag is not None:
            if (neuer_vertrag.netto_mietzins or 0) <= (alter_vertrag.netto_mietzins or 0):
                teile.append('Anfangsmietzins prüfen')
            if not neuer_vertrag.kautions_betrag or neuer_vertrag.kautions_einbezahlt_am:
                teile.append('Kaution einfordern')
        n = _abhaken(fall, tuple(teile), benutzer)
        if n:
            _schliessen_wenn_fertig(fall)
        return n


def kaution_einbezahlt(neuer_vertrag, benutzer=None):
    """Die Kaution des Nachfolgers ist einbezahlt: «Kaution einfordern» im offenen
    Mieterwechsel-Fall der Vorgänger-Verträge ist erledigt."""
    from core.tenancy import organisation_kontext

    n = 0
    with organisation_kontext(neuer_vertrag.organisation):
        for alt in (neuer_vertrag.einheit.vertraege.filter(status__in=('gekuendigt', 'archiviert'))
                    .exclude(pk=neuer_vertrag.pk)):
            fall = _fall_des_vertrags(alt)
            if fall is None:
                continue
            k = _abhaken(fall, ('Kaution einfordern',), benutzer)
            if k:
                _schliessen_wenn_fertig(fall)
            n += k
    return n
