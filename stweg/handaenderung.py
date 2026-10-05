"""Handänderungs-Abrechnung: taggenaue Aufteilung eines Jahres zwischen Verkäufer und Käufer (pro rata temporis).

ANNAHMEN (nicht rechtlich geprüft — vor Gebrauch bestätigen, im Kaufvertrag kann etwas anderes stehen):
  · Der Tag des Eigentumsübergangs (`StwegEigentuemerwechsel.datum`) ist der ERSTE Tag des Käufers. Der Verkäufer trägt
    die Tage vom 1. Januar bis zum Vortag, der Käufer den Rest des Jahres (Kalenderjahr: 365 bzw. 366 Tage).
  · Grundlage der Kosten ist das genehmigte JAHRESBUDGET der Einheit (die Summe ihrer Vorschreibungen des Jahres) —
    oder ein ausdrücklich übergebener Jahresbetrag (z. B. der Kostenanteil der abgeschlossenen Jahresabrechnung).
    Die Kosten fallen gleichmässig über das Jahr an (keine Saisonalität).
  · Rundung: Der Verkäuferanteil wird auf Rappen gerundet (kaufmännisch), der Käufer trägt den Rest — die beiden
    Anteile ergeben immer genau den Jahresbetrag.
  · Akonto-Zahlungen gehören der Partei, die am Zahlungstag Eigentümer war (nur der Kapitalanteil; Zins und Kosten
    sind Nebenforderungen und stehen getrennt).
  · Ausgleich: Die Gemeinschaft fordert den Rest des Jahres vom heutigen Eigentümer (Käufer). Hat der Verkäufer weniger
    bezahlt, als sein Tagesanteil beträgt, erstattet er die Differenz dem Käufer; hat er mehr bezahlt, erstattet der
    Käufer sie ihm. Der Ausgleich ist eine Rechnung zwischen den Parteien, keine Forderung der Gemeinschaft.
  · Verzugszins: Er folgt der Hauptforderung. Ausgewiesen wird, wie viel bis zum Vortag des Übergangs aufgelaufen ist
    und wie viel danach (Stichtag = heute oder der übergebene Tag).
"""
from calendar import isleap
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from stweg import inkasso
from stweg.models import StwegAkonto, StwegVorschreibung

NULL = Decimal('0.00')


def _runden(betrag):
    return Decimal(betrag).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def tage_aufteilung(jahr, uebergang):
    """(Tage des Verkäufers, Tage des Käufers, Tage des Jahres). Der Übergangstag zählt zum Käufer."""
    jahrestage = 366 if isleap(jahr) else 365
    verkaeufer = (uebergang - date(jahr, 1, 1)).days
    return verkaeufer, jahrestage - verkaeufer, jahrestage


def aufteilung(wechsel, *, jahresbetrag=None, stichtag=None):
    """Die Handänderungs-Abrechnung zu einem erfassten Wechsel. Gibt ein Dict mit den Zeilen für PDF und Seite."""
    einheit = wechsel.einheit
    jahr = wechsel.datum.year
    stichtag = stichtag or timezone.localdate()
    v_tage, k_tage, jahrestage = tage_aufteilung(jahr, wechsel.datum)
    quelle = 'übergeben'
    if jahresbetrag is None:
        jahresbetrag = sum((v.betrag for v in StwegVorschreibung.objects.filter(einheit=einheit, budget__jahr=jahr)),
                           NULL)
        quelle = f'Jahresbudget {jahr} (Summe der Vorschreibungen)' if jahresbetrag else \
            f'kein genehmigtes Budget {jahr} vorhanden'
    jahresbetrag = Decimal(jahresbetrag)
    verkaeufer_anteil = _runden(jahresbetrag * v_tage / jahrestage)
    kaeufer_anteil = jahresbetrag - verkaeufer_anteil

    akonto_v = akonto_k = NULL
    for z in StwegAkonto.objects.filter(einheit=einheit, zweck=StwegAkonto.AKONTO, datum__year=jahr):
        if z.datum < wechsel.datum:
            akonto_v += z.kapital
        else:
            akonto_k += z.kapital
    saldo_v = verkaeufer_anteil - akonto_v          # was der Verkäufer für seine Tage noch zu tragen hat (− = zu viel bezahlt)
    saldo_k = kaeufer_anteil - akonto_k

    vor = wechsel.datum - timedelta(days=1)
    zins_bis = sum((c['betrag'] for c in inkasso.forderungen(einheit, vor) if c['art'] == 'zins'), NULL)
    zins_heute = sum((c['betrag'] for c in inkasso.forderungen(einheit, max(stichtag, vor)) if c['art'] == 'zins'),
                     NULL)
    offen_verkaeufer = sum((c['offen'] for c in inkasso.forderungen(einheit, vor)
                            if c['art'] in ('akonto', 'abrechnung', 'fonds')), NULL)
    return {
        'wechsel': wechsel, 'einheit': einheit, 'jahr': jahr, 'quelle': quelle, 'stichtag': stichtag,
        'jahresbetrag': jahresbetrag, 'jahrestage': jahrestage,
        'verkaeufer': wechsel.bisheriger, 'kaeufer': wechsel.neu,
        'verkaeufer_tage': v_tage, 'kaeufer_tage': k_tage,
        'verkaeufer_anteil': verkaeufer_anteil, 'kaeufer_anteil': kaeufer_anteil,
        'akonto_verkaeufer': akonto_v, 'akonto_kaeufer': akonto_k,
        'saldo_verkaeufer': saldo_v, 'saldo_kaeufer': saldo_k,
        # Der Rest des Jahres wird vom Käufer verlangt; der Verkäufer erstattet seinen Teil (− = Käufer erstattet).
        'ausgleich_verkaeufer_an_kaeufer': saldo_v,
        'zins_bis_uebergang': zins_bis, 'zins_danach': zins_heute - zins_bis,
        'offen_verkaeufer_bei_uebergang': offen_verkaeufer,
    }
