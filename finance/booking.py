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
    ('2030', 'Vorauszahlungen / Guthaben Mieter', 'passiv', False, 'm2'),
    ('2200', 'Geschuldete MWST (Umsatzsteuer)', 'bilanz', False, 'm2'),
    # Abrechnungskonto ESTV: Die Zahllast entsteht am Periodenende, gezahlt wird
    # erst mit der Abrechnung (Frist 60 Tage). Direkt gegen die Bank zu buchen
    # liess 1020 ab dem Stichtag vom realen Kontoauszug abweichen und erzeugte
    # beim späteren Bank-Import eine Doppelbuchung (Audit).
    ('2201', 'Abrechnungskonto MWST (ESTV)', 'passiv', False, 'm2'),
    ('2800', 'Erneuerungsfonds (Rückstellung)', 'bilanz', False, 'm2'),
    ('2850', 'Kontokorrent Eigentümer', 'passiv', False, 'm2'),
    ('2970', 'Jahresergebnis / Gewinnvortrag', 'passiv', False, 'm2'),
    ('3000', 'Mieterträge Wohnungen', 'ertrag', False, 'm2'),
    ('3010', 'Mieterträge Gewerbe/Parkplätze', 'ertrag', False, 'm2'),
    ('3020', 'Nebenkosten Akonto-Zahlungen', 'ertrag', False, 'm2'),
    ('3021', 'Nebenkosten Pauschal (Ertrag)', 'ertrag', False, 'm2'),
    ('3090', 'Mietzinsrabatte / Mietzinserlass (Ertragsminderung)', 'ertrag', False, 'm2'),
    # Getrennt von 3090, weil die Honorarbasis auf dem NETTO-Mietertrag (3000/3010)
    # rechnet und die Nebenkosten gar nicht enthält. Ein NK-Erlass auf 3090 hätte
    # eine Basis gemindert, in der die Nebenkosten nie standen (Audit).
    ('3091', 'Nebenkosten-Erlass (Ertragsminderung NK)', 'ertrag', False, 'm2'),
    ('3600', 'Übrige Erträge / Weiterverrechnung (Zuschlag)', 'ertrag', False, 'm2'),
    ('3805', 'Debitorenverluste (Forderungsverluste)', 'aufwand', False, 'm2'),
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


def _organisation(organisation=None):
    """Die Verwaltung, deren Kontenplan gemeint ist.

    Seit Etappe 5 gehoert ein Buchungskonto der Organisation, und `nummer` ist
    nur noch JE ORGANISATION eindeutig. Jede Suche muss den Bezug deshalb
    mitfuehren — sonst faende sie Konto 1020 einer fremden Verwaltung und buchte
    darauf. Das waere kein Leseleck mehr, sondern ein fremder Buchungssatz in
    fremden Buechern.

    `organisation_bestimmen` loest das auf: ausdrueckliches Argument, sonst der
    Mandantenkontext, sonst ein Fehler. Bis Etappe 6.3 stand dazwischen noch
    "die einzige vorhandene Organisation" — das hielt jeden Pfad am Leben, der
    ohne Kontext buchte, und waere beim zweiten Mandanten geschlossen
    ausgefallen. Getilgt, nachdem 6.1 und 6.2 den Kontext ueberall gesetzt
    hatten.
    """
    from core.organisation_kette import organisation_bestimmen
    return organisation_bestimmen(organisation)


def ensure_kontenplan(organisation=None):
    """Legt fehlende Standardkonten idempotent an. Gibt die Anzahl neu erstellter zurück."""
    from finance.models import Buchungskonto
    organisation = _organisation(organisation)
    created = 0
    for nummer, bez, typ, hnk, vs in STANDARD_KONTEN:
        _, c = Buchungskonto.objects.get_or_create(
            nummer=nummer, organisation=organisation,
            defaults={'bezeichnung': bez, 'typ': typ, 'is_hnk_relevant': hnk,
                      'standard_verteilschluessel': vs})
        if c:
            created += 1
    return created


def konto(nummer, organisation=None):
    """Holt ein Buchungskonto; legt ein bekanntes Standardkonto bei Bedarf nach.
    Wirft ValueError bei einer völlig unbekannten Kontonummer (statt stillem Skip)."""
    from finance.models import Buchungskonto
    organisation = _organisation(organisation)
    nummer = str(nummer)
    obj = Buchungskonto.objects.filter(nummer=nummer, organisation=organisation).first()
    if obj:
        return obj
    if nummer in _STANDARD_MAP:
        _, bez, typ, hnk, vs = _STANDARD_MAP[nummer]
        return Buchungskonto.objects.create(nummer=nummer, organisation=organisation,
                                            bezeichnung=bez, typ=typ,
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
        datum=datum or timezone.localdate(),
        beleg_text=str(beleg_text)[:255],
        soll_konto=sk, haben_konto=hk, betrag=betrag,
        liegenschaft=liegenschaft, erstellt_von=user,
        debitoren_rechnung=debitor, kreditoren_rechnung=kreditor, zahlungseingang=zahlung,
        ist_storno=storno)


def storniere_buchung(buchung, *, user=None, datum=None):
    """Revisionssichere Gegenbuchung (Soll↔Haben getauscht). Die Originalbuchung
    bleibt unverändert erhalten (append-only), wird aber als storniert markiert.

    Das Storno wird im laufenden (offenen) Datum gebucht — nicht rückdatiert in
    die u.U. gesperrte Ursprungsperiode. Gibt die Gegenbuchung zurück.
    """
    from finance.models import Buchung
    if buchung.ist_storno:
        raise ValueError("Eine Storno-Buchung kann nicht storniert werden.")
    if buchung.storniert_am is not None:
        raise ValueError("Diese Buchung wurde bereits storniert.")

    original_nr = buchung.beleg_nr
    gegen = Buchung.objects.create(
        datum=datum or timezone.localdate(),
        beleg_text=f"Storno Beleg #{original_nr}: {buchung.beleg_text}"[:255],
        soll_konto=buchung.haben_konto, haben_konto=buchung.soll_konto,
        betrag=buchung.betrag, liegenschaft=buchung.liegenschaft,
        erstellt_von=user, ist_storno=True, storno_von=buchung,
        # Beleg-Verknüpfungen mitführen, damit OP-/Nebenbuch-Bezug erhalten bleibt
        debitoren_rechnung=buchung.debitoren_rechnung,
        kreditoren_rechnung=buchung.kreditoren_rechnung,
        zahlungseingang=buchung.zahlungseingang)
    buchung.storniert_am = timezone.now()
    buchung.save(update_fields=['storniert_am'])
    return gegen
