"""Rundschreiben per E-Mail als EIN Ablauf — für den Knopf und für den Auftrag im Hintergrund.

Jede Mail geht einzeln über SMTP hinaus; bei vielen Empfängern reicht das Zeitlimit des Hosters nicht. Deshalb kann der
Versand ein Auftrag werden (`core/services/auftraege.py`, Art `rundschreiben`).

KEINE MAIL DOPPELT: Ein abgestürzter Auftrag wird neu gestartet. `versenden` bekommt deshalb `erledigt` (IDs, an die
schon gesendet wurde) und meldet jede gelungene Mail sofort über `nach_jedem`; der Auftrag schreibt das in seine
Parameter. Der Neustart überspringt die Erledigten.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

#: Ab so vielen Empfängern geht der Versand IMMER in den Hintergrund (siehe `mahnlauf_lauf.SCHWELLE_HINTERGRUND`).
SCHWELLE_HINTERGRUND = 30


def schwelle():
    return getattr(settings, 'RUNDSCHREIBEN_SCHWELLE_HINTERGRUND', SCHWELLE_HINTERGRUND)


def im_hintergrund(anzahl):
    return anzahl >= schwelle()


def versenden(betreff, text, mieter_ids, benutzer=None, erledigt=(), nach_jedem=None, frist_datum=None, frist_tage=None):
    """Schickt die Mitteilung an jeden Mieter mit E-Mail-Adresse und trägt sie ins Kommunikationsjournal ein.

    Gibt die Zahl der in DIESEM Aufruf versandten Mails zurück. Läuft im gesetzten Mandantenkontext: Eine fremde
    Mieter-ID findet der gefilterte Manager nicht und wird übergangen."""
    from core.utils.email_service import journal_email, send_ticket_email
    from crm.models import Mieter
    schon = {int(i) for i in erledigt}
    gesendet = 0
    for mid in mieter_ids:
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            continue
        if mid in schon:
            continue
        m = Mieter.objects.filter(id=mid).first()
        if not (m and m.email):
            continue
        # Platzhalter je Empfänger ersetzen (23.11.2026): Vorher ging der Text mit `{mieter.anrede}` roh hinaus,
        # obwohl die Maske «werden pro Empfänger automatisch ersetzt» verspricht.
        b, t, e, v = _fuer_empfaenger(betreff, text, m, frist_datum, frist_tage)
        if send_ticket_email(m.email, b, t):
            gesendet += 1
            schon.add(mid)
            journal_email(b, t, mieter=m, user=benutzer, empfaenger=m.email)
            # Ablage und Frist wie beim Brief (23.11.2026). Die Mail ist hinaus: Scheitert die Ablage, wird das protokolliert,
            # aber nicht nochmals gesendet.
            try:
                _ablegen_und_frist(betreff, text, b, m, v, e, frist_datum, frist_tage, benutzer)
            except Exception:
                logger.exception('Rundschreiben: Ablage oder Fristeintrag gescheitert (Mieter %s)', mid)
            if nach_jedem is not None:
                nach_jedem(mid)
    return gesendet


def _fuer_empfaenger(betreff, text, mieter, frist_datum=None, frist_tage=None):
    """Betreff und Text mit den Werten dieses Empfängers — dieselbe Auflösung wie im Serienbrief-PDF."""
    from core.services.serienbrief import _ersetze, empfaenger_kontext
    v, ph = empfaenger_kontext(mieter, frist_datum=frist_datum, frist_tage=frist_tage)
    lg = v.einheit.liegenschaft if (v is not None and v.einheit_id) else None
    e = {
        'name': mieter.display_name, 'anrede': mieter.anrede or '',
        'strasse': mieter.strasse or (lg.strasse if lg else ''),
        'plz': mieter.plz or (lg.plz if lg else ''), 'ort': mieter.ort or (lg.ort if lg else ''),
        'objekt': (f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}" if lg else ''),
        'liegenschaft': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
        '_ph': ph,
    }
    return _ersetze(betreff, e), _ersetze(text, e), e, v


def _ablegen_und_frist(betreff_roh, text_roh, betreff, mieter, vertrag, e, frist_datum, frist_tage, benutzer):
    """Legt die versandte Mitteilung als PDF in der Akte ab (Mieter und Vertrag) und trägt eine im Text gesetzte Frist ein.

    Dieselbe Darstellung und dieselbe Pendenz wie beim Serienbrief-PDF; der Titel beginnt mit «E-Mail:», damit in der Akte
    erkennbar ist, auf welchem Weg die Mitteilung hinausging."""
    from django.utils import timezone

    from core.models import Pendenz
    from core.services.ablage import ablegen
    from core.services.brief_aus_vorlage import _pendenz_anlegen
    from core.services.serienbrief import frist_art_im_text, generate_serienbrief_pdf
    from core.tenancy import aktuelle_organisation
    org = aktuelle_organisation()
    absender = {'firma': org.firma if org else '', 'strasse': org.strasse if org else '',
                'plz': org.plz if org else '', 'ort': org.ort if org else ''}
    logo = None
    if org and getattr(org, 'logo', None):
        try:
            logo = org.logo.path
        except Exception:
            logo = None
    pdf = generate_serienbrief_pdf(absender, betreff_roh, text_roh, [e], logo_path=logo)
    dok = ablegen(pdf, f"E-Mail: {betreff}", kategorie='korrespondenz', vertrag=vertrag, mieter=mieter,
                  im_portal_sichtbar=True)
    frist_art = frist_art_im_text(betreff_roh, text_roh, frist_datum, frist_tage)
    if dok and frist_art:
        _pendenz_anlegen(Pendenz, dok, mieter, vertrag, betreff, False, frist_art, frist_datum, frist_tage,
                         timezone.localdate(), benutzer)
