"""Kundenübersicht für den Betreiber: alle Verwaltungen auf einen Blick, mit Befund, was fehlt.

Gelesen wird über ALLE Organisationen (`Organisation` hat keinen TenantManager; Mitgliedschaft und Abonnement über
`alle_organisationen`). Es werden nur Zähler und Abo-Daten gezeigt, nie Verträge, Personen oder Buchungen (DSG).
Die Seite dazu: `core/views/fw/betreiber.py`, nur für den Betreiber (Superuser).
"""
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from abo import dienst
from abo.models import AboRechnung, Abonnement, KundenKontakt, Kundenstamm
from core import funktionen as f
from crm.models import Mitgliedschaft, Organisation


@dataclass
class Kunde:
    organisation: Organisation
    abo: object = None
    inhaber: int = 0
    einheiten: int = 0
    nutzer: int = 0
    stufe: str = ''
    stamm: object = None
    befunde: list = field(default_factory=list)

    @property
    def kundennummer(self):
        return f'K-{self.organisation.pk:04d}'

    @property
    def status_text(self):
        return self.stamm.get_status_display() if self.stamm is not None else ''

    @property
    def ansprechperson(self):
        return self.stamm.ansprechperson if self.stamm is not None else ''

    @property
    def telefon(self):
        """Die beste Nummer für einen Anruf: Natel der Ansprechperson, deren Telefon, sonst das der Firma."""
        s = self.stamm
        return ((s.ansprech_natel or s.ansprech_telefon or s.natel) if s is not None else '') or self.organisation.telefon

    @property
    def abo_text(self):
        if self.abo is None:
            return _('keines')
        return _('Bestand') if self.abo.uneingeschraenkt else _('verwaltet')


def kunden():
    """Alle Verwaltungen, nach Firma sortiert, je mit Zählern und Befunden."""
    abos = {a.organisation_id: a for a in Abonnement.alle_organisationen.all()}
    inhaber = {}
    for org_id in (Mitgliedschaft.alle_organisationen.filter(rolle=Mitgliedschaft.ROLLE_INHABER)
                   .values_list('organisation_id', flat=True)):
        inhaber[org_id] = inhaber.get(org_id, 0) + 1
    staemme = {k.organisation_id: k for k in Kundenstamm.alle_organisationen.all()}
    unversandt = {}
    for org_id in (AboRechnung.alle_organisationen.filter(status=AboRechnung.STATUS_OFFEN, versendet_am__isnull=True)
                   .values_list('organisation_id', flat=True)):
        unversandt[org_id] = unversandt.get(org_id, 0) + 1
    zeilen = []
    for org in Organisation.objects.all().order_by('firma', 'pk'):
        k = Kunde(organisation=org, abo=abos.get(org.pk), inhaber=inhaber.get(org.pk, 0), stamm=staemme.get(org.pk))
        k.einheiten = dienst.zaehle(org.pk, 'einheiten')
        k.nutzer = dienst.zaehle(org.pk, 'nutzer')
        k.stufe = f.STUFEN_NAMEN.get(f.stufe_von(org), '')
        if k.abo is None:
            k.befunde.append(_('Keine Abonnement-Zeile: wird nicht abgerechnet und nicht eingeschränkt.'))
        if k.inhaber == 0:
            k.befunde.append(_('Kein Inhaber: niemand kann Benutzer und Einstellungen verwalten.'))
        if not dienst.rechnungs_adresse(org):
            k.befunde.append(_('Keine E-Mail-Adresse: Rechnungen und Zahlungserinnerungen gehen ins Leere.'))
        if k.abo is not None and not k.abo.uneingeschraenkt and k.abo.abrechnung_ab is None:
            k.befunde.append(_('«Abrechnung ab» ist nicht gesetzt: Es wird nichts in Rechnung gestellt.'))
        if k.abo is not None and k.abo.zustand != Abonnement.ZUSTAND_AKTIV:
            k.befunde.append(_('Zahlung überfällig seit %(datum)s.') % {'datum': k.abo.ueberfaellig_seit or '—'})
        if unversandt.get(org.pk):
            k.befunde.append(_('%(n)s offene Rechnung(en) wurden noch nicht per Mail versandt: im Kunden «Erneut senden».')
                             % {'n': unversandt[org.pk]})
        zeilen.append(k)
    return zeilen


# ---------------------------------------------------------------------------
# Kundenkartei: Finanzen und Verlauf
# ---------------------------------------------------------------------------

#: Aktionen des Betreibers, die im Logbuch der Verwaltung stehen und im Verlauf der Kundenkartei mit erscheinen.
EREIGNISSE = (
    'Kunde angelegt', 'Abonnement angelegt', 'Stufe gewechselt', 'Abonnement eingestellt', 'Zahlung bestätigt',
    'Rechnung storniert', 'Rechnung gestellt', 'Rechnung gesendet', 'Zahlungserinnerung gesendet',
    'Kundendaten geändert',
)


def kartei(org):
    """Die Kundenkartei der Verwaltung; wird beim ersten Öffnen angelegt (Status «Kunde»)."""
    stamm = Kundenstamm.alle_organisationen.filter(organisation=org).first()
    if stamm is None:
        stamm = Kundenstamm.alle_organisationen.create(organisation=org)
    return stamm


def finanzen(org, heute=None):
    """Die Zahlen zu einem Kunden aus seinen Abo-Rechnungen: fakturiert, bezahlt, offen, überfällig, Zahlungen, nächste Rechnung.

    Stornierte Rechnungen zählen nirgends. Beträge sind Brutto inklusive Mahngebühr. «Tage nach Fälligkeit» ist negativ,
    wenn früher bezahlt wurde.
    """
    from decimal import Decimal

    from core.zeit import datum_heute
    heute = heute or datum_heute()
    rechnungen = list(AboRechnung.alle_organisationen.filter(organisation=org).exclude(status=AboRechnung.STATUS_STORNIERT)
                      .order_by('-rechnungsdatum', '-pk'))

    def betrag(r):
        return r.brutto + r.mahngebuehr

    bezahlt = [r for r in rechnungen if r.status == AboRechnung.STATUS_BEZAHLT]
    offen = [r for r in rechnungen if r.status == AboRechnung.STATUS_OFFEN]
    dauern = [(r.bezahlt_am - r.faellig_am).days for r in bezahlt if r.bezahlt_am]
    zahlungen = sorted((r for r in bezahlt if r.bezahlt_am), key=lambda r: r.bezahlt_am, reverse=True)[:12]
    ergebnis = {
        'fakturiert': sum((betrag(r) for r in rechnungen), Decimal('0')),
        'bezahlt': sum((betrag(r) for r in bezahlt), Decimal('0')),
        'offen': sum((betrag(r) for r in offen), Decimal('0')),
        'ueberfaellig': sum((betrag(r) for r in offen if r.faellig_am < heute), Decimal('0')),
        'anzahl': len(rechnungen),
        'zahlungsdauer': round(sum(dauern) / len(dauern), 1) if dauern else None,
        'zahlungen': [{'rechnung': r, 'tage': (r.bezahlt_am - r.faellig_am).days, 'betrag': betrag(r)} for r in zahlungen],
        'naechste': None,
    }
    abo = Abonnement.alle_organisationen.filter(organisation=org).first()
    if abo is not None and not abo.uneingeschraenkt and abo.abrechnung_ab:
        periode = dienst.naechste_periode(abo, org)
        if periode:
            netto, _bemerkung = dienst.betrag_fuer(f.stufe_von(org), dienst.zaehle(org.pk, 'einheiten'),
                                                   bool(org.abo_jaehrlich))
            ergebnis['naechste'] = {'von': periode[0], 'bis': periode[1], 'netto': netto}
    return ergebnis


def verlauf(org, limit=60):
    """Verlauf des Kunden, neueste zuerst: Kontakteinträge des Betreibers und seine Aktionen aus dem Logbuch der Verwaltung."""
    from core.models import AktivitaetsLog
    eintraege = [{'zeit': k.zeitpunkt, 'art': k.art, 'art_text': k.get_art_display(), 'text': k.text,
                  'von': k.erfasst_von, 'pk': k.pk, 'eigen': True}
                 for k in KundenKontakt.alle_organisationen.filter(organisation=org)[:limit]]
    for e in (AktivitaetsLog.alle_organisationen.filter(organisation=org, aktion__in=EREIGNISSE, kategorie='sicherheit')
              .select_related('benutzer').order_by('-zeitpunkt')[:limit]):
        eintraege.append({'zeit': e.zeitpunkt, 'art': 'system', 'art_text': _('System'),
                          'text': e.aktion + (f': {e.details}' if e.details else ''),
                          'von': e.benutzer.get_username() if e.benutzer_id else '', 'pk': None, 'eigen': False})
    eintraege.sort(key=lambda x: x['zeit'], reverse=True)
    return eintraege[:limit]

