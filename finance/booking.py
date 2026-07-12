"""Zentrale Buchungsschicht — die einzige Stelle, an der ins Hauptbuch gebucht wird.

Ziele:
- Ein Kontenplan als Single Source of Truth (STANDARD_KONTEN). Fehlende
  Standardkonten werden bei Bedarf automatisch angelegt.
- ``buche(...)`` erzeugt genau eine doppelte Buchung. Fehlt ein Konto, wird
  es angelegt statt die Buchung stillschweigend zu verschlucken (kein
  ``except Buchungskonto.DoesNotExist: pass`` mehr → keine Drift zwischen
  Haupt- und Nebenbuch).
"""
from decimal import Decimal

from django.utils import timezone


# (Nummer, Bezeichnung, Typ, HNK-relevant, Verteilschlüssel)
STANDARD_KONTEN = [
    ('1015', 'Kautionssperrkonten (Mieterkautionen)', 'bilanz', False, 'm2'),
    ('1020', 'Bank', 'bilanz', False, 'm2'),
    ('1100', 'Forderungen (Debitoren)', 'bilanz', False, 'm2'),
    ('1170', 'Vorsteuer (MWST)', 'bilanz', False, 'm2'),
    ('1190', 'Durchlaufkonto Weiterverrechnungen', 'bilanz', False, 'm2'),
    ('1500', 'Sachanlagen (Anlagegüter)', 'bilanz', False, 'm2'),
    ('2000', 'Verbindlichkeiten (Kreditoren)', 'bilanz', False, 'm2'),
    ('2010', 'Kautionsverbindlichkeiten', 'bilanz', False, 'm2'),
    ('2200', 'Geschuldete MWST (Umsatzsteuer)', 'bilanz', False, 'm2'),
    ('2800', 'Erneuerungsfonds (Rückstellung)', 'bilanz', False, 'm2'),
    ('3000', 'Mieterträge Wohnungen', 'ertrag', False, 'm2'),
    ('3010', 'Mieterträge Gewerbe/Parkplätze', 'ertrag', False, 'm2'),
    ('3020', 'Nebenkosten Akonto-Zahlungen', 'ertrag', False, 'm2'),
    ('3600', 'Übrige Erträge / Weiterverrechnung (Zuschlag)', 'ertrag', False, 'm2'),
    ('4000', 'Unterhalt & Reparaturen', 'aufwand', False, 'm2'),
    ('4100', 'Heizkosten / Brennstoffe', 'aufwand', True, 'm2'),
    ('4110', 'Wasser / Abwasser', 'aufwand', True, 'm3'),
    ('4120', 'Hauswartung & Reinigung', 'aufwand', True, 'm2'),
    ('4130', 'Allgemeinstrom', 'aufwand', True, 'm2'),
    ('4140', 'Kehricht / Abgaben', 'aufwand', True, 'einheit'),
    ('4400', 'Sachversicherungen', 'aufwand', True, 'm3'),
    ('4500', 'Verwaltungshonorar', 'aufwand', False, 'm2'),
    ('6800', 'Abschreibungen', 'aufwand', False, 'm2'),
    ('6900', 'Einlage Erneuerungsfonds', 'aufwand', False, 'm2'),
]

_STANDARD_MAP = {k[0]: k for k in STANDARD_KONTEN}


def ensure_kontenplan():
    """Legt fehlende Standardkonten idempotent an. Gibt die Anzahl neu erstellter zurück."""
    from finance.models import Buchungskonto
    created = 0
    for nummer, bez, typ, hnk, vs in STANDARD_KONTEN:
        _, c = Buchungskonto.objects.get_or_create(
            nummer=nummer,
            defaults={'bezeichnung': bez, 'typ': typ, 'is_hnk_relevant': hnk,
                      'standard_verteilschluessel': vs})
        if c:
            created += 1
    return created


def konto(nummer):
    """Holt ein Buchungskonto; legt ein bekanntes Standardkonto bei Bedarf nach.
    Wirft ValueError bei einer völlig unbekannten Kontonummer (statt stillem Skip)."""
    from finance.models import Buchungskonto
    nummer = str(nummer)
    obj = Buchungskonto.objects.filter(nummer=nummer).first()
    if obj:
        return obj
    if nummer in _STANDARD_MAP:
        _, bez, typ, hnk, vs = _STANDARD_MAP[nummer]
        return Buchungskonto.objects.create(nummer=nummer, bezeichnung=bez, typ=typ,
                                            is_hnk_relevant=hnk, standard_verteilschluessel=vs)
    raise ValueError(f"Unbekanntes Buchungskonto '{nummer}' — nicht im Standard-Kontenplan. "
                     "Bitte im Kontenplan anlegen.")


def buche(soll, haben, betrag, beleg_text, *, datum=None, liegenschaft=None, user=None,
          debitor=None, kreditor=None, zahlung=None, storno=False):
    """Erzeugt eine doppelte Buchung (Soll/Haben). soll/haben sind Kontonummern (str)
    oder Buchungskonto-Instanzen. Beträge = 0/None werden übersprungen (gibt None).
    Legt fehlende Standardkonten an — verschluckt nichts."""
    from finance.models import Buchung, Buchungskonto
    if betrag is None:
        return None
    betrag = Decimal(str(betrag)).quantize(Decimal('0.01'))
    if betrag == 0:
        return None
    sk = soll if isinstance(soll, Buchungskonto) else konto(soll)
    hk = haben if isinstance(haben, Buchungskonto) else konto(haben)
    return Buchung.objects.create(
        datum=datum or timezone.now().date(),
        beleg_text=str(beleg_text)[:255],
        soll_konto=sk, haben_konto=hk, betrag=betrag,
        liegenschaft=liegenschaft, erstellt_von=user,
        debitoren_rechnung=debitor, kreditoren_rechnung=kreditor, zahlungseingang=zahlung,
        ist_storno=storno)
