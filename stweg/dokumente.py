"""Dokumenten-Repository der Gemeinschaft: Pflichtkategorien, Gültigkeit, Sichtbarkeit.

PFLICHTKATEGORIEN, die das System überwacht: Begründungsakt, STWEG-Reglement, Nutzungs- und
Verwaltungsordnung, Versicherungspolice, Jahresrechnung.

  · Begründungsakt, Reglement, Nutzungsordnung — ERSETZEND: gültig ist jeweils die jüngste Fassung
    (`gueltig_ab` bis heute); ältere bleiben als Verlauf erhalten.
  · Versicherungspolice — PARALLEL: mehrere Policen gelten nebeneinander (Gebäude, Haftpflicht);
    gefordert ist mindestens eine, die nicht abgelaufen ist.
  · Jahresrechnung — AUTOMATISCH: jede abgeschlossene Abrechnung ist für ihre Eigentümer ein
    Dokument (der persönliche Beleg); ein hochgeladenes Dokument dieser Kategorie ist zusätzlich möglich.

Was fehlt oder abgelaufen ist, meldet `pruefen` und legt `aufgaben_nachziehen` als Pendenz an.
"""
from datetime import date

from django.utils import timezone

from core.models import Pendenz
from core.utils.uploads import validiere_dokument
from stweg.models import StwegAbrechnung, StwegDokument

K = StwegDokument
ERSETZEND = (K.BEGRUENDUNGSAKT, K.REGLEMENT, K.NUTZUNGSORDNUNG)
PFLICHT = (K.BEGRUENDUNGSAKT, K.REGLEMENT, K.NUTZUNGSORDNUNG, K.VERSICHERUNG, K.JAHRESRECHNUNG)
PREFIX = 'stweg:dokument:'


class DokumentFehler(ValueError):
    pass


def hochladen(liegenschaft, kategorie, titel, datei, *, gueltig_ab=None, gueltig_bis=None,
              sichtbar=True, user=None):
    if kategorie not in dict(K.KATEGORIE_CHOICES):
        raise DokumentFehler('Unbekannte Kategorie.')
    if not (titel or '').strip():
        raise DokumentFehler('Ein Titel ist nötig.')
    ok, fehler = validiere_dokument(datei)
    if not ok:
        raise DokumentFehler(fehler)
    gueltig_ab = gueltig_ab or timezone.localdate()
    if gueltig_bis and gueltig_bis < gueltig_ab:
        raise DokumentFehler('«Gültig bis» liegt vor «gültig ab».')
    return K.objects.create(liegenschaft=liegenschaft, kategorie=kategorie, titel=titel.strip()[:200], datei=datei,
                            gueltig_ab=gueltig_ab, gueltig_bis=gueltig_bis, sichtbar=sichtbar,
                            hochgeladen_von=user)


def aktuell(liegenschaft, kategorie, heute=None):
    """Die heute geltenden Dokumente der Kategorie (bei «ersetzend» höchstens eines)."""
    heute = heute or date.today()
    gueltig = [d for d in K.objects.filter(liegenschaft=liegenschaft, kategorie=kategorie, gueltig_ab__lte=heute)
               if d.gueltig_bis is None or d.gueltig_bis >= heute]
    gueltig.sort(key=lambda d: (d.gueltig_ab, d.pk), reverse=True)
    return gueltig[:1] if kategorie in ERSETZEND else gueltig


def pruefen(liegenschaft, heute=None):
    """Status je Pflichtkategorie: [{'kategorie', 'name', 'status': ok|fehlt|abgelaufen|automatisch, 'dokumente'}]."""
    heute = heute or date.today()
    namen = dict(K.KATEGORIE_CHOICES)
    ergebnis = []
    for kat in PFLICHT:
        if kat == K.JAHRESRECHNUNG:
            n = StwegAbrechnung.objects.filter(liegenschaft=liegenschaft,
                                               status=StwegAbrechnung.STATUS_ABGESCHLOSSEN).count()
            ergebnis.append({'kategorie': kat, 'name': namen[kat], 'status': 'automatisch',
                             'dokumente': aktuell(liegenschaft, kat, heute), 'anzahl_abrechnungen': n})
            continue
        docs = aktuell(liegenschaft, kat, heute)
        if docs:
            status = 'ok'
        elif K.objects.filter(liegenschaft=liegenschaft, kategorie=kat).exists():
            status = 'abgelaufen'
        else:
            status = 'fehlt'
        ergebnis.append({'kategorie': kat, 'name': namen[kat], 'status': status, 'dokumente': docs})
    return ergebnis


def luecken(liegenschaft, heute=None):
    return [p for p in pruefen(liegenschaft, heute) if p['status'] in ('fehlt', 'abgelaufen')]


def aufgaben_nachziehen(liegenschaft, heute=None):
    """Legt für jede Lücke genau eine offene Pendenz an und erledigt die, deren Lücke geschlossen ist.
    Idempotent. Gibt (angelegt, erledigt) zurück."""
    offen = {p['kategorie']: p for p in luecken(liegenschaft, heute)}
    angelegt = erledigt = 0
    for kat in PFLICHT:
        quelle = f'{PREFIX}{kat}'
        pend = Pendenz.objects.filter(liegenschaft=liegenschaft, quelle=quelle, erledigt=False).first()
        if kat in offen and pend is None:
            p = offen[kat]
            Pendenz.objects.create(
                liegenschaft=liegenschaft, quelle=quelle, kategorie='aufgabe',
                titel=(f'Dokument {"abgelaufen" if p["status"] == "abgelaufen" else "fehlt"}: {p["name"]}')[:200],
                beschreibung='Pflichtdokument der Gemeinschaft im Dokumenten-Repository hinterlegen.')
            angelegt += 1
        elif kat not in offen and pend is not None:
            pend.erledigt, pend.erledigt_am = True, heute or timezone.localdate()
            pend.save(update_fields=['erledigt', 'erledigt_am'])
            erledigt += 1
    return angelegt, erledigt


def fuer_eigentuemer(liegenschaft, heute=None):
    """Was ein Eigentümer im Portal sieht: nur freigegebene Dokumente, je Kategorie, jüngste zuerst;
    `aktuell` markiert die heute geltenden."""
    heute = heute or date.today()
    geltende = {d.pk for kat in dict(K.KATEGORIE_CHOICES) for d in aktuell(liegenschaft, kat, heute)}
    gruppen = []
    for kat, name in K.KATEGORIE_CHOICES:
        docs = list(K.objects.filter(liegenschaft=liegenschaft, kategorie=kat, sichtbar=True))
        for d in docs:
            d.ist_aktuell = d.pk in geltende
        if docs:
            gruppen.append({'kategorie': kat, 'name': name, 'dokumente': docs})
    return gruppen
