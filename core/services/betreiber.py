"""Kundenübersicht für den Betreiber: alle Verwaltungen auf einen Blick, mit Befund, was fehlt.

Gelesen wird über ALLE Organisationen (`Organisation` hat keinen TenantManager; Mitgliedschaft und Abonnement über
`alle_organisationen`). Es werden nur Zähler und Abo-Daten gezeigt, nie Verträge, Personen oder Buchungen (DSG).
Die Seite dazu: `core/views/fw/betreiber.py`, nur für den Betreiber (Superuser).
"""
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from abo import dienst
from abo.models import Abonnement
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
    befunde: list = field(default_factory=list)

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
    zeilen = []
    for org in Organisation.objects.all().order_by('firma', 'pk'):
        k = Kunde(organisation=org, abo=abos.get(org.pk), inhaber=inhaber.get(org.pk, 0))
        k.einheiten = dienst.zaehle(org.pk, 'einheiten')
        k.nutzer = dienst.zaehle(org.pk, 'nutzer')
        k.stufe = f.STUFEN_NAMEN.get(f.stufe_von(org), '')
        if k.abo is None:
            k.befunde.append(_('Keine Abonnement-Zeile: wird nicht abgerechnet und nicht eingeschränkt.'))
        if k.inhaber == 0:
            k.befunde.append(_('Kein Inhaber: niemand kann Benutzer und Einstellungen verwalten.'))
        if not org.email:
            k.befunde.append(_('Keine E-Mail-Adresse: Rechnungen und Zahlungserinnerungen gehen ins Leere.'))
        if k.abo is not None and not k.abo.uneingeschraenkt and k.abo.abrechnung_ab is None:
            k.befunde.append(_('«Abrechnung ab» ist nicht gesetzt: Es wird nichts in Rechnung gestellt.'))
        if k.abo is not None and k.abo.zustand != Abonnement.ZUSTAND_AKTIV:
            k.befunde.append(_('Zahlung überfällig seit %(datum)s.') % {'datum': k.abo.ueberfaellig_seit or '—'})
        zeilen.append(k)
    return zeilen
