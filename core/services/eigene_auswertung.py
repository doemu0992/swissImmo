"""Eigene Auswertungen und Exportvorlagen (Modul «Erweitertes Reporting»).

Eine Vorlage hält fest: WORAUS (Datenquelle), WAS (Spalten in gewählter Reihenfolge), WANN (Zeitraum) und WO
(optional eine Liegenschaft). Sie wird gespeichert, lässt sich jederzeit neu ausführen und als CSV herausgeben — die
wiederkehrende Liste fürs Treuhandbüro oder den Eigentümer muss nicht jedes Mal neu zusammengeklickt werden.

Bewusst KEIN freier Abfragebaukasten: Die Quellen und ihre Spalten stehen hier fest. Jede Spalte ist ein geprüfter Pfad
auf dem Modell; was hier nicht steht, lässt sich nicht abfragen (auch nicht über eine gebastelte Anfrage — `spalten_von`
verwirft unbekannte Schlüssel). Gelesen wird über `Model.objects`, also immer nur der Bestand der aktiven Verwaltung.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

ZEITRAEUME = [
    ('alle', _('Ganzer Bestand')),
    ('monat', _('Laufender Monat')),
    ('jahr', _('Laufendes Jahr')),
    ('vorjahr', _('Vorjahr')),
    ('12m', _('Letzte 12 Monate')),
]


def _debitoren():
    from finance.models import DebitorenRechnung
    return DebitorenRechnung.objects.annotate(
        _lg=Coalesce('liegenschaft__strasse', 'vertrag__einheit__liegenschaft__strasse'))


def _kreditoren():
    from finance.models import KreditorenRechnung
    return KreditorenRechnung.objects.all()


def _zahlungen():
    from finance.models import Zahlungseingang
    return Zahlungseingang.objects.annotate(
        _lg=Coalesce('liegenschaft__strasse', 'vertrag__einheit__liegenschaft__strasse'))


def _vertraege():
    from rentals.models import Mietvertrag
    return Mietvertrag.objects.all()


def _objekte():
    from portfolio.models import Einheit
    return Einheit.objects.all()


def _schaeden():
    from tickets.models import SchadenMeldung
    return SchadenMeldung.objects.all()


#: Quelle → Beschriftung, Abfrage, Datumsfeld (für den Zeitraum), Filter auf eine Liegenschaft, Sortierung, ob es
#: Finanzdaten sind (dann braucht es eine Finanzrolle), und die Spalten als (Schlüssel, Beschriftung, Pfad).
QUELLEN = {
    'debitoren': {
        'name': _('Debitoren (Rechnungen an Mieter)'), 'abfrage': _debitoren, 'datum': 'datum', 'finanz': True,
        'liegenschaft': lambda lg: Q(liegenschaft=lg) | Q(vertrag__einheit__liegenschaft=lg),
        'sortierung': ('datum', 'pk'),
        'spalten': [
            ('datum', _('Rechnungsdatum'), 'datum'), ('faellig_am', _('Fällig am'), 'faellig_am'),
            ('titel', _('Titel'), 'titel'), ('betrag', _('Betrag'), 'betrag'), ('status', _('Status'), 'status'),
            ('forderungsart', _('Forderungsart'), 'forderungsart'),
            ('mieter_nachname', _('Mieter Nachname'), 'vertrag__mieter__nachname'),
            ('mieter_vorname', _('Mieter Vorname'), 'vertrag__mieter__vorname'),
            ('mieter_firma', _('Mieter Firma'), 'vertrag__mieter__firmen_name'),
            ('objekt', _('Objekt'), 'vertrag__einheit__bezeichnung'), ('liegenschaft', _('Liegenschaft'), '_lg'),
            ('qr_referenz', _('QR-Referenz'), 'qr_referenz'),
        ]},
    'kreditoren': {
        'name': _('Kreditoren (Lieferantenrechnungen)'), 'abfrage': _kreditoren, 'datum': 'datum', 'finanz': True,
        'liegenschaft': lambda lg: Q(liegenschaft=lg), 'sortierung': ('datum', 'pk'),
        'spalten': [
            ('datum', _('Rechnungsdatum'), 'datum'), ('faellig_am', _('Fällig am'), 'faellig_am'),
            ('lieferant', _('Lieferant'), 'lieferant'), ('betrag', _('Betrag'), 'betrag'),
            ('mwst_betrag', _('MWST-Betrag'), 'mwst_betrag'), ('status', _('Status'), 'status'),
            ('konto', _('Konto'), 'konto__nummer'), ('liegenschaft', _('Liegenschaft'), 'liegenschaft__strasse'),
            ('objekt', _('Objekt'), 'einheit__bezeichnung'), ('referenz', _('Referenz'), 'referenz'),
            ('hnk', _('Nebenkostenrelevant'), 'is_hnk_relevant'),
        ]},
    'zahlungen': {
        'name': _('Zahlungseingänge'), 'abfrage': _zahlungen, 'datum': 'datum_eingang', 'finanz': True,
        'liegenschaft': lambda lg: Q(liegenschaft=lg) | Q(vertrag__einheit__liegenschaft=lg),
        'sortierung': ('datum_eingang', 'pk'),
        'spalten': [
            ('datum_eingang', _('Eingang am'), 'datum_eingang'), ('betrag', _('Betrag'), 'betrag'),
            ('status', _('Status'), 'status'),
            ('mieter_nachname', _('Mieter Nachname'), 'vertrag__mieter__nachname'),
            ('mieter_vorname', _('Mieter Vorname'), 'vertrag__mieter__vorname'),
            ('objekt', _('Objekt'), 'vertrag__einheit__bezeichnung'), ('liegenschaft', _('Liegenschaft'), '_lg'),
            ('rechnung', _('Rechnung'), 'debitoren_rechnung__titel'),
            ('bank_referenz', _('Bankreferenz'), 'bank_referenz'), ('bemerkung', _('Bemerkung'), 'bemerkung'),
        ]},
    'vertraege': {
        'name': _('Mietverträge'), 'abfrage': _vertraege, 'datum': 'beginn', 'finanz': False,
        'liegenschaft': lambda lg: Q(einheit__liegenschaft=lg),
        'sortierung': ('einheit__liegenschaft__strasse', 'einheit__bezeichnung', 'pk'),
        'spalten': [
            ('liegenschaft', _('Liegenschaft'), 'einheit__liegenschaft__strasse'),
            ('ort', _('Ort'), 'einheit__liegenschaft__ort'), ('objekt', _('Objekt'), 'einheit__bezeichnung'),
            ('mieter_nachname', _('Mieter Nachname'), 'mieter__nachname'),
            ('mieter_vorname', _('Mieter Vorname'), 'mieter__vorname'),
            ('mieter_firma', _('Mieter Firma'), 'mieter__firmen_name'),
            ('status', _('Status'), 'status'), ('beginn', _('Beginn'), 'beginn'), ('ende', _('Ende'), 'ende'),
            ('netto_mietzins', _('Nettomietzins'), 'netto_mietzins'), ('nebenkosten', _('Nebenkosten'), 'nebenkosten'),
            ('kautions_betrag', _('Kaution'), 'kautions_betrag'),
        ]},
    'objekte': {
        'name': _('Objekte'), 'abfrage': _objekte, 'datum': None, 'finanz': False,
        'liegenschaft': lambda lg: Q(liegenschaft=lg), 'sortierung': ('liegenschaft__strasse', 'bezeichnung', 'pk'),
        'spalten': [
            ('liegenschaft', _('Liegenschaft'), 'liegenschaft__strasse'), ('ort', _('Ort'), 'liegenschaft__ort'),
            ('bezeichnung', _('Bezeichnung'), 'bezeichnung'), ('typ', _('Typ'), 'typ'), ('etage', _('Etage'), 'etage'),
            ('zimmer', _('Zimmer'), 'zimmer'), ('flaeche_m2', _('Fläche m²'), 'flaeche_m2'),
            ('nettomiete', _('Nettomiete aktuell'), 'nettomiete_aktuell'),
            ('nebenkosten', _('Nebenkosten aktuell'), 'nebenkosten_aktuell'),
        ]},
    'schaeden': {
        'name': _('Schadenmeldungen'), 'abfrage': _schaeden, 'datum': 'erstellt_am__date', 'finanz': False,
        'liegenschaft': lambda lg: Q(liegenschaft=lg), 'sortierung': ('erstellt_am', 'pk'),
        'spalten': [
            ('erstellt_am', _('Gemeldet am'), 'erstellt_am'), ('titel', _('Titel'), 'titel'),
            ('kategorie', _('Kategorie'), 'kategorie'), ('status', _('Status'), 'status'),
            ('prioritaet', _('Priorität'), 'prioritaet'), ('liegenschaft', _('Liegenschaft'), 'liegenschaft__strasse'),
            ('objekt', _('Objekt'), 'betroffene_einheit__bezeichnung'),
        ]},
}

#: Höchstzahl Zeilen einer Auswertung (Anzeige blättert; der Export liefert bis hierhin).
MAX_ZEILEN = 20000


def quellen_fuer(darf_finanzen):
    """Die Quellen, die diese Person sehen darf: Finanzdaten nur mit Finanzrolle."""
    return [(k, q['name']) for k, q in QUELLEN.items() if darf_finanzen or not q['finanz']]


def spalten_von(quelle, schluessel):
    """Die gewählten Spalten als (Schlüssel, Beschriftung, Pfad), in gewählter Reihenfolge; Unbekanntes fällt weg."""
    bekannt = {k: (k, name, pfad) for k, name, pfad in QUELLEN[quelle]['spalten']}
    gesehen, liste = set(), []
    for k in schluessel or []:
        if k in bekannt and k not in gesehen:
            gesehen.add(k)
            liste.append(bekannt[k])
    return liste


def zeitraum(schluessel, heute=None):
    """(von, bis) eingeschlossen — oder (None, None) für den ganzen Bestand."""
    heute = heute or timezone.localdate()
    if schluessel == 'monat':
        naechster = (heute.replace(day=28) + timedelta(days=4)).replace(day=1)
        return heute.replace(day=1), naechster - timedelta(days=1)
    if schluessel == 'jahr':
        return date(heute.year, 1, 1), date(heute.year, 12, 31)
    if schluessel == 'vorjahr':
        return date(heute.year - 1, 1, 1), date(heute.year - 1, 12, 31)
    if schluessel == '12m':
        return heute - timedelta(days=365), heute
    return None, None


def abfrage(vorlage, heute=None):
    """Die gefilterte, sortierte Abfrage der Vorlage (im Mandantenkontext)."""
    q = QUELLEN[vorlage.quelle]
    qs = q['abfrage']()
    von, bis = zeitraum(vorlage.zeitraum, heute)
    if von is not None and q['datum']:
        qs = qs.filter(**{f"{q['datum']}__gte": von, f"{q['datum']}__lte": bis})
    if vorlage.liegenschaft_id:
        qs = qs.filter(q['liegenschaft'](vorlage.liegenschaft_id))
    return qs.order_by(*q['sortierung'])


def zeilen(vorlage, heute=None, grenze=MAX_ZEILEN):
    """(Kopfzeile, Zeilen) der Vorlage. Jede Zeile ist eine Liste roher Werte in Spaltenreihenfolge."""
    spalten = spalten_von(vorlage.quelle, vorlage.spalten)
    if not spalten:
        return [], []
    werte = abfrage(vorlage, heute).values_list(*(F(pfad) if pfad.startswith('_') else pfad
                                                   for _k, _n, pfad in spalten))[:grenze]
    return [str(name) for _k, name, _pfad in spalten], [list(z) for z in werte]


def anzeige(wert):
    """Ein Wert für die Bildschirmtabelle: Datum schweizerisch, Geld mit zwei Stellen, Ja/Nein, leer als Strich."""
    if wert is None or wert == '':
        return '—'
    if isinstance(wert, bool):
        return _('Ja') if wert else _('Nein')
    if isinstance(wert, Decimal):
        return f'{wert:,.2f}'.replace(',', "'")
    if hasattr(wert, 'strftime'):
        if hasattr(wert, 'hour'):
            wert = timezone.localtime(wert) if timezone.is_aware(wert) else wert
            return wert.strftime('%d.%m.%Y %H:%M')
        return wert.strftime('%d.%m.%Y')
    return str(wert)
