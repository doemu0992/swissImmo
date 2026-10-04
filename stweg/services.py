"""StwegAbrechnungService — Kostenverteilung einer STWEG nach Wertquoten.

Ablauf einer Abrechnung für (Liegenschaft, Jahr):
  1. Wertquoten prüfen — Summe ≠ Total → `WertquotenFehler`, keine Abrechnung.
  2. Allgemeine Kosten sammeln: Kreditorenrechnungen der Liegenschaft, die im
     Jahr datiert sind, nicht einer einzelnen Einheit zugeordnet (`einheit` leer)
     und weder `neu` (ungeprüfter Scan) noch `storniert`. Bei aufgeteilten
     Rechnungen zählen nur die Positionen dieser Liegenschaft.
  3. Jede Kostenzeile nach dem Schlüssel ihres Kontos verteilen (`stweg.schluessel`;
     ohne Zuordnung: Standardschlüssel «Allgemeine Wertquote»). Je Schlüssel einmal
     verteilt, grösster Rest — die Rappen gehen auf.
  4. Geleistete Akonto-Zahlungen des Jahres je Einheit abziehen.
  5. Saldo je Einheit: positiv = Zahllast, negativ = Guthaben.

Nicht Teil der Abrechnung: Fonds-Einlagen (`stweg.fonds`) — sie sind keine Kosten.
"""
from django.utils.translation import gettext
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from core.tenancy import organisation_kontext
from finance.models import KreditorenRechnung
from stweg import hauptbuch
from stweg.models import (StwegAbrechnung, StwegAbrechnungAnteil, StwegAbrechnungKosten,
                          StwegAbrechnungPosition, StwegAkonto)
from stweg.schluessel import SchluesselFehler, schluessel_fuer_konto, verteile
from stweg.validierung import pruefe_wertquoten, stimm_einheiten

NULL = Decimal('0.00')
#: `neu` = noch nicht freigegeben, `storniert` = ungültig.
AUSGESCHLOSSENE_STATUS = ('neu', 'storniert')


class AbrechnungsFehler(ValueError):
    pass


class StwegAbrechnungService:
    def __init__(self, liegenschaft):
        if not liegenschaft.ist_stweg:
            raise AbrechnungsFehler(gettext('«%(liegenschaft)s» ist keine STWEG-Liegenschaft.') % {'liegenschaft': liegenschaft})
        self.liegenschaft = liegenschaft

    def _rechnungen(self, jahr):
        lg = self.liegenschaft
        return (KreditorenRechnung.objects
                .filter(Q(liegenschaft=lg) | Q(positionen__liegenschaft=lg) | Q(positionen__einheit__liegenschaft=lg),
                        datum__year=jahr)
                .exclude(status__in=AUSGESCHLOSSENE_STATUS)
                .distinct().prefetch_related('positionen').order_by('datum', 'id'))

    def _zeilen(self, jahr):
        """Alle Kostenzeilen der Gemeinschaft; `einheit` ist die belastete Einheit oder None (allgemein)."""
        lg = self.liegenschaft
        zeilen = []
        for r in self._rechnungen(jahr):
            positionen = list(r.positionen.all())
            if positionen:
                for p in positionen:
                    einheit = p.einheit if p.einheit_id and p.einheit.liegenschaft_id == lg.pk else None
                    if p.liegenschaft_id == lg.pk and p.einheit_id is None or einheit is not None:
                        zeilen.append({'datum': r.datum, 'lieferant': r.lieferant, 'text': p.bezeichnung,
                                       'betrag': p.betrag, 'konto': p.konto or r.konto, 'einheit': einheit})
            elif r.liegenschaft_id == lg.pk:
                einheit = r.einheit if r.einheit_id and r.einheit.liegenschaft_id == lg.pk else None
                if r.einheit_id is None or einheit is not None:
                    zeilen.append({'datum': r.datum, 'lieferant': r.lieferant, 'text': '',
                                   'betrag': r.betrag or NULL, 'konto': r.konto, 'einheit': einheit})
        return zeilen

    def kostenzeilen(self, jahr):
        """Die allgemeinen Kosten der Gemeinschaft im Jahr, Zeile für Zeile."""
        return [z for z in self._zeilen(jahr) if z['einheit'] is None]

    def einzelkosten(self, jahr):
        """Kosten, die einer einzelnen Einheit zugeordnet sind (z. B. Reparatur in einer Wohnung).

        Sie gehören nicht in die Verteilung auf alle, sondern zu dieser Einheit — dem Eigentümer des
        Hauptobjekts, auch wenn die Rechnung auf einen Nebenraum (Keller, Parkplatz) lautet. Früher
        fielen sie aus der Abrechnung heraus: Die Gemeinschaft bezahlte, belastet wurde niemand."""
        zeilen = []
        for z in self._zeilen(jahr):
            if z['einheit'] is not None:
                haupt = z['einheit'].gehoert_zu or z['einheit']
                zeilen.append({**z, 'einheit': haupt})
        return zeilen

    def allgemeine_kosten(self, jahr):
        """Summe aller allgemeinen Kosten der Gemeinschaft im Jahr."""
        return sum((z['betrag'] for z in self.kostenzeilen(jahr)), NULL).quantize(Decimal('0.01'))

    def akonto_je_einheit(self, jahr):
        rows = (StwegAkonto.objects.filter(einheit__liegenschaft=self.liegenschaft, datum__year=jahr,
                                         zweck=StwegAkonto.AKONTO)
                .values('einheit').annotate(s=Sum('betrag')))
        return {r['einheit']: r['s'] or NULL for r in rows}

    @transaction.atomic
    def abrechnen(self, jahr):
        lg = self.liegenschaft
        with organisation_kontext(lg.organisation):
            if lg.status != lg.STATUS_AKTIV:
                raise AbrechnungsFehler(gettext('«%(lg)s» ist nicht aktiv — es wird nicht abgerechnet.') % {'lg': lg})
            pruefe_wertquoten(lg)       # hart: nie mit falschen Quoten abrechnen

            bestehend = StwegAbrechnung.objects.filter(liegenschaft=lg, jahr=jahr).first()
            if bestehend is not None:
                if bestehend.status == StwegAbrechnung.STATUS_ABGESCHLOSSEN:
                    raise AbrechnungsFehler(gettext('Die Abrechnung %(jahr)s ist abgeschlossen.') % {'jahr': jahr})
                bestehend.delete()      # Entwurf wird neu berechnet

            einheiten = list(stimm_einheiten(lg).order_by('pk'))
            zeilen = self.kostenzeilen(jahr)
            einzel = self.einzelkosten(jahr)
            ids = {e.pk for e in einheiten}
            for z in einzel:
                if z['einheit'].pk not in ids:
                    raise AbrechnungsFehler(gettext('Einzelkosten (%(wert)s, CHF %(wert2)s) hängen an einer Einheit ohne Stimmrecht: «%(bezeichnung)s».') % {'wert': z['lieferant'], 'wert2': z['betrag'], 'bezeichnung': z['einheit'].bezeichnung})
            kosten = sum((z['betrag'] for z in zeilen + einzel), NULL).quantize(Decimal('0.01'))
            akonto = self.akonto_je_einheit(jahr)

            # Kosten je Schlüssel bündeln und je Schlüssel EINMAL verteilen (Rappen gehen auf).
            je_schluessel = {}
            for z in zeilen:
                sl = schluessel_fuer_konto(lg, z['konto'])
                je_schluessel.setdefault(sl.pk, [sl, NULL])[1] += z['betrag']
            verteilt = {}
            for pk, (sl, summe) in je_schluessel.items():
                try:
                    anteile, gew = verteile(summe.quantize(Decimal('0.01')), sl, einheiten)
                except SchluesselFehler as e:
                    raise AbrechnungsFehler(str(e))
                verteilt[pk] = (sl, summe.quantize(Decimal('0.01')), anteile, gew)
            anteil_je_einheit = {e.pk: NULL for e in einheiten}
            for sl, summe, anteile, gew in verteilt.values():
                for e in einheiten:
                    anteil_je_einheit[e.pk] += anteile[e.pk]

            abrechnung = StwegAbrechnung.objects.create(
                liegenschaft=lg, jahr=jahr, gesamtkosten=kosten)
            for z in zeilen:
                sl = schluessel_fuer_konto(lg, z['konto'])
                StwegAbrechnungKosten.objects.create(
                    abrechnung=abrechnung, datum=z['datum'], lieferant=z['lieferant'], text=z['text'],
                    betrag=z['betrag'], schluessel=sl, schluessel_name=sl.name)
            direkt = {e.pk: NULL for e in einheiten}
            for z in einzel:
                name = f"Direkt belastet: {z['einheit'].bezeichnung}"
                StwegAbrechnungKosten.objects.create(
                    abrechnung=abrechnung, datum=z['datum'], lieferant=z['lieferant'], text=z['text'],
                    betrag=z['betrag'], schluessel_name=name)
                direkt[z['einheit'].pk] += z['betrag']
                anteil_je_einheit[z['einheit'].pk] += z['betrag']
            for e in einheiten:
                anteil = anteil_je_einheit[e.pk]
                bezahlt = akonto.get(e.pk, NULL)
                position = StwegAbrechnungPosition.objects.create(
                    abrechnung=abrechnung, einheit=e, eigentuemer=e.stockwerkeigentuemer,
                    wertquote=e.wertquote, wertquote_total=lg.wertquote_total,
                    kostenanteil=anteil, akonto=bezahlt, saldo=anteil - bezahlt)
                for sl, summe, anteile, gew in verteilt.values():
                    StwegAbrechnungAnteil.objects.create(
                        position=position, schluessel=sl, schluessel_name=sl.name,
                        gewicht=gew[e.pk], gewicht_total=sum(gew.values(), Decimal('0')),
                        kosten_total=summe, betrag=anteile[e.pk])
                if direkt[e.pk]:
                    StwegAbrechnungAnteil.objects.create(
                        position=position, schluessel=None, schluessel_name='Direkt belastet',
                        gewicht=Decimal('1'), gewicht_total=Decimal('1'), kosten_total=direkt[e.pk],
                        betrag=direkt[e.pk])
            return abrechnung

    @staticmethod
    @transaction.atomic
    def abschliessen(abrechnung, *, user=None):
        """Schliesst die Abrechnung ab und bucht sie ins Hauptbuch (`stweg.hauptbuch.abschluss_buchen`).
        Ein zweiter Aufruf ändert nichts und bucht nichts nochmals."""
        abrechnung.refresh_from_db(fields=['status'])
        if abrechnung.status == StwegAbrechnung.STATUS_ABGESCHLOSSEN:
            return abrechnung
        try:
            hauptbuch.abschluss_buchen(abrechnung, user=user)
        except hauptbuch.HauptbuchFehler as e:
            raise AbrechnungsFehler(str(e))
        abrechnung.status = StwegAbrechnung.STATUS_ABGESCHLOSSEN
        abrechnung.save(update_fields=['status'])
        return abrechnung
