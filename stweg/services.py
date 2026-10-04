"""StwegAbrechnungService — Kostenverteilung einer STWEG nach Wertquoten.

Ablauf einer Abrechnung für (Liegenschaft, Jahr):
  1. Wertquoten prüfen — Summe ≠ Total → `WertquotenFehler`, keine Abrechnung.
  2. Allgemeine Kosten sammeln: Kreditorenrechnungen der Liegenschaft, die im
     Jahr datiert sind, nicht einer einzelnen Einheit zugeordnet (`einheit` leer)
     und weder `neu` (ungeprüfter Scan) noch `storniert`. Bei aufgeteilten
     Rechnungen zählen nur die Positionen dieser Liegenschaft.
  3. Nach Wertquoten verteilen (grösster Rest — die Rappen gehen auf).
  4. Geleistete Akonto-Zahlungen des Jahres je Einheit abziehen.
  5. Saldo je Einheit: positiv = Zahllast, negativ = Guthaben.

Nicht Teil der Abrechnung: Fonds-Einlagen (`stweg.fonds`) — sie sind keine Kosten.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from core.tenancy import organisation_kontext
from finance.models import KreditorenRechnung
from stweg.models import StwegAbrechnung, StwegAbrechnungKosten, StwegAbrechnungPosition, StwegAkonto
from stweg.validierung import pruefe_wertquoten
from stweg.verteilung import verteile_nach_quoten

NULL = Decimal('0.00')
#: `neu` = noch nicht freigegeben, `storniert` = ungültig.
AUSGESCHLOSSENE_STATUS = ('neu', 'storniert')


class AbrechnungsFehler(ValueError):
    pass


class StwegAbrechnungService:
    def __init__(self, liegenschaft):
        if not liegenschaft.ist_stweg:
            raise AbrechnungsFehler(f'«{liegenschaft}» ist keine STWEG-Liegenschaft.')
        self.liegenschaft = liegenschaft

    def kostenzeilen(self, jahr):
        """Die allgemeinen Kosten der Gemeinschaft im Jahr, Zeile für Zeile."""
        lg = self.liegenschaft
        rechnungen = (KreditorenRechnung.objects
                      .filter(Q(liegenschaft=lg) | Q(positionen__liegenschaft=lg), datum__year=jahr)
                      .exclude(status__in=AUSGESCHLOSSENE_STATUS)
                      .distinct().prefetch_related('positionen').order_by('datum', 'id'))
        zeilen = []
        for r in rechnungen:
            positionen = list(r.positionen.all())
            if positionen:
                for p in positionen:
                    if p.liegenschaft_id == lg.pk and p.einheit_id is None:
                        zeilen.append({'datum': r.datum, 'lieferant': r.lieferant,
                                       'text': p.bezeichnung, 'betrag': p.betrag})
            elif r.liegenschaft_id == lg.pk and r.einheit_id is None:
                zeilen.append({'datum': r.datum, 'lieferant': r.lieferant, 'text': '',
                               'betrag': r.betrag or NULL})
        return zeilen

    def allgemeine_kosten(self, jahr):
        """Summe aller allgemeinen Kosten der Gemeinschaft im Jahr."""
        return sum((z['betrag'] for z in self.kostenzeilen(jahr)), NULL).quantize(Decimal('0.01'))

    def akonto_je_einheit(self, jahr):
        rows = (StwegAkonto.objects.filter(einheit__liegenschaft=self.liegenschaft, datum__year=jahr)
                .values('einheit').annotate(s=Sum('betrag')))
        return {r['einheit']: r['s'] or NULL for r in rows}

    @transaction.atomic
    def abrechnen(self, jahr):
        lg = self.liegenschaft
        with organisation_kontext(lg.organisation):
            if lg.status != lg.STATUS_AKTIV:
                raise AbrechnungsFehler(f'«{lg}» ist nicht aktiv — es wird nicht abgerechnet.')
            pruefe_wertquoten(lg)       # hart: nie mit falschen Quoten abrechnen

            bestehend = StwegAbrechnung.objects.filter(liegenschaft=lg, jahr=jahr).first()
            if bestehend is not None:
                if bestehend.status == StwegAbrechnung.STATUS_ABGESCHLOSSEN:
                    raise AbrechnungsFehler(f'Die Abrechnung {jahr} ist abgeschlossen.')
                bestehend.delete()      # Entwurf wird neu berechnet

            einheiten = list(lg.einheiten.order_by('pk'))
            zeilen = self.kostenzeilen(jahr)
            kosten = sum((z['betrag'] for z in zeilen), NULL).quantize(Decimal('0.01'))
            anteile = verteile_nach_quoten(kosten, {e.pk: e.wertquote for e in einheiten})
            akonto = self.akonto_je_einheit(jahr)

            abrechnung = StwegAbrechnung.objects.create(
                liegenschaft=lg, jahr=jahr, gesamtkosten=kosten)
            for z in zeilen:
                StwegAbrechnungKosten.objects.create(abrechnung=abrechnung, **z)
            for e in einheiten:
                anteil = anteile[e.pk]
                bezahlt = akonto.get(e.pk, NULL)
                StwegAbrechnungPosition.objects.create(
                    abrechnung=abrechnung, einheit=e, eigentuemer=e.stockwerkeigentuemer,
                    wertquote=e.wertquote, wertquote_total=lg.wertquote_total,
                    kostenanteil=anteil, akonto=bezahlt, saldo=anteil - bezahlt)
            return abrechnung

    @staticmethod
    def abschliessen(abrechnung):
        abrechnung.status = StwegAbrechnung.STATUS_ABGESCHLOSSEN
        abrechnung.save(update_fields=['status'])
        return abrechnung
