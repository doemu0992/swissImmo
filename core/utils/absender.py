"""Absender und Antwortadresse ausgehender Mails (FUNK-12).

Alle Mails laufen über ein einziges SMTP-Konto (`DEFAULT_FROM_EMAIL`). Bis zum Audit vom
28.10.2026 hiess der Absender deshalb bei jeder Verwaltung gleich, und nur ein Teil der
Sendepfade setzte überhaupt ein Reply-To: Eine Mahnung oder Nebenkostenabrechnung ging
«von ImmoSwiss Verwaltung», und die Antwort des Mieters landete bei der Plattform.

DIE REGEL, und warum sie so ist

* **From-Adresse bleibt die des SMTP-Kontos.** Nur sie ist durch SPF und DKIM der Absenderdomain
  gedeckt. Eine fremde Adresse (die der Verwaltung) im From ohne deren eigenes SPF/DKIM wird von
  Empfängern als Fälschung abgewiesen oder als Spam einsortiert. Eigene Domain je Verwaltung ist
  eine Betriebsfrage (DNS, eigener SMTP) und nicht Teil dieses Moduls.
* **Anzeigename = Firma der Verwaltung** («Muster Verwaltung AG via immoswiss»). Der Mieter sieht,
  wer schreibt.
* **Reply-To je Verwaltung**, in dieser Reihenfolge: ausdrücklich übergebene Adresse, aktives
  «Antworten»-Postfach der Verwaltung (das `fetch_replies` abruft), `Organisation.email`. Erst
  ohne all das gilt die globale Adresse.

Der Mandant kommt aus dem Aufruf (`organisation`) oder, wenn der fehlt, aus dem Mandantenkontext.
In einem eigenen Thread gibt es keinen Kontext: dort muss der Aufrufer die Organisation vorher
bestimmen und übergeben.
"""
import os
import re
from email.utils import formataddr, parseaddr

from django.conf import settings

#: Steuerzeichen und Zeichen, die einen Anzeigenamen als Adresse missverstehen lassen.
_UNERWUENSCHT = re.compile(r'[\x00-\x1f\x7f<>"@;,\\]')
_MAX_NAME = 60
GLOBALE_ANTWORT_STANDARD = 'reply@immoswiss.app'


def _organisation_aufloesen(organisation):
    """`organisation` als Objekt, ID oder `None` → Organisation oder `None` (Kontext)."""
    from core.tenancy import aktuelle_organisation
    if organisation is None:
        return aktuelle_organisation()
    if isinstance(organisation, int):
        from crm.models import Organisation
        return Organisation.objects.filter(pk=organisation).first()
    return getattr(organisation, 'organisation', organisation)


def anzeigename(organisation):
    """Firma als Anzeigename, bereinigt; `''` ohne Firma."""
    firma = (getattr(organisation, 'firma', '') or '').strip()
    firma = re.sub(r'\s+', ' ', _UNERWUENSCHT.sub(' ', firma)).strip()
    return firma[:_MAX_NAME].strip()


def _konto_adresse():
    """Die reine Adresse des SMTP-Kontos aus `DEFAULT_FROM_EMAIL`."""
    return parseaddr(settings.DEFAULT_FROM_EMAIL)[1] or settings.DEFAULT_FROM_EMAIL


def _plattform_name():
    return parseaddr(settings.DEFAULT_FROM_EMAIL)[0] or 'immoswiss'


def absender(organisation=None):
    """Der From-Header: Firma der Verwaltung, Adresse des SMTP-Kontos."""
    org = _organisation_aufloesen(organisation)
    name = anzeigename(org) if org else ''
    if not name:
        return settings.DEFAULT_FROM_EMAIL
    return formataddr((f'{name} via {_plattform_name()}', _konto_adresse()))


def antwortadresse(organisation=None, reply_to=None):
    """Reply-To als Liste mit genau einer Adresse (siehe Kopf für die Reihenfolge)."""
    if reply_to and '@' in reply_to:
        return [reply_to]
    org = _organisation_aufloesen(organisation)
    if org is not None:
        from core.models import Postfach
        pf = (Postfach.alle_organisationen
              .filter(organisation_id=org.pk, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True)
              .order_by('pk').first())
        if pf and '@' in (pf.benutzer or ''):
            return [pf.benutzer]
        eigene = (getattr(org, 'email', '') or '').strip()
        if '@' in eigene and '\n' not in eigene and '\r' not in eigene:
            return [eigene]
    return [os.environ.get('EMAIL_REPLY_USER') or GLOBALE_ANTWORT_STANDARD]


def kopfzeilen(organisation=None, reply_to=None):
    """`from_email=` und `reply_to=` für `EmailMessage`/`EmailMultiAlternatives` in einem Wurf."""
    org = _organisation_aufloesen(organisation)
    return {'from_email': absender(org), 'reply_to': antwortadresse(org, reply_to)}
