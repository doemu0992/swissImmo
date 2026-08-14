# rentals/services.py
import logging
import re
from decimal import Decimal

import requests
from django.core.files.base import ContentFile

from .models import Dokument, Mietvertrag

logger = logging.getLogger(__name__)

def berechne_mietpotenzial(vertrag, aktuell_ref, aktuell_lik, allg_kosten_pct=Decimal('0.00')):
    """
    Berechnet das Erhöhungs- oder Senkungspotenzial nach Schweizer Mietrecht.
    Inklusive Referenzzinssatz, Teuerung (LIK) und allgemeiner Kostensteigerung.
    """
    if not vertrag.basis_referenzzinssatz or not vertrag.basis_lik_punkte:
        return None

    basis_ref = Decimal(str(vertrag.basis_referenzzinssatz))
    curr_ref = Decimal(str(aktuell_ref))
    basis_lik = Decimal(str(vertrag.basis_lik_punkte))
    curr_lik = Decimal(str(aktuell_lik))
    netto_miete = Decimal(str(vertrag.netto_mietzins))

    # --- 1. REFERENZZINSSATZ ---
    zins_delta = curr_ref - basis_ref
    steps = int(zins_delta / Decimal('0.25'))
    zins_prozent = Decimal('0.00')

    if steps > 0:
        zins_prozent = Decimal(steps) * Decimal('3.00')
    elif steps < 0:
        abs_steps = abs(steps)
        zins_prozent = Decimal(abs_steps) * Decimal('-2.91')

    # --- 2. TEUERUNG (LIK) ---
    lik_prozent = Decimal('0.00')
    if curr_lik > basis_lik:
        teuerung = (curr_lik - basis_lik) / basis_lik
        lik_prozent = teuerung * Decimal('100') * Decimal('0.4')

    # --- 3. ALLGEMEINE KOSTENSTEIGERUNG ---
    kosten_prozent = Decimal(str(allg_kosten_pct))

    # --- 4. ZUSAMMENFASSUNG ---
    total_prozent = zins_prozent + lik_prozent + kosten_prozent

    faktor = 1 + (total_prozent / Decimal('100'))
    neue_miete = netto_miete * faktor
    differenz_chf = neue_miete - netto_miete

    action = 'OK'
    if total_prozent > 0.5:
        action = 'UP'
    elif total_prozent < -0.5:
        action = 'DOWN'

    return {
        'mieter': f"{vertrag.mieter}",
        'objekt': str(vertrag.einheit),
        'aktuell_chf': round(netto_miete, 2),
        'neu_chf': round(neue_miete, 2),
        'delta_chf': round(differenz_chf, 2),
        'delta_prozent': round(total_prozent, 2),
        'details_zins': f"{zins_prozent}% (Ref: {basis_ref} -> {curr_ref})",
        'details_lik': f"{round(lik_prozent, 2)}% (Index: {basis_lik} -> {curr_lik})",
        'details_kosten': f"{kosten_prozent}% (Allg. Kostensteigerung)",
        'action': action
    }


def archiviere_vertrag_wenn_unterzeichnet(vertrag):
    """
    Prüft, ob der Vertrag unterzeichnet ist und legt bei Bedarf
    automatisch ein Archiv-Dokument an.
    Gibt True zurück, wenn ein neues Dokument erstellt wurde, sonst False.
    """
    if vertrag.sign_status == 'unterzeichnet' and vertrag.pdf_datei:
        exists = Dokument.objects.filter(vertrag=vertrag, kategorie='vertrag').exists()

        if not exists:
            Dokument.objects.create(
                titel=f"Mietvertrag {vertrag.mieter}",
                kategorie='vertrag',
                vertrag=vertrag,
                mieter=vertrag.mieter,
                einheit=vertrag.einheit,
                datei=vertrag.pdf_datei
            )
            return True

    return False

# ---------------------------------------------------------------------------
# Kündigungs-Terminberechnung (Schweizer Mietrecht)
# ---------------------------------------------------------------------------
import calendar
import datetime as _dt

_MONATE = {
    'januar': 1, 'februar': 2, 'märz': 3, 'maerz': 3, 'april': 4, 'mai': 5,
    'juni': 6, 'juli': 7, 'august': 8, 'september': 9, 'oktober': 10,
    'november': 11, 'dezember': 12,
}


def _erlaubte_termin_monate(kuendigungstermine: str):
    """Parst das (Freitext-)Feld kuendigungstermine zu einer Menge erlaubter Monatszahlen (1-12)."""
    txt = (kuendigungstermine or '').lower()
    if not txt.strip():
        return set(range(1, 13))
    genannt = {num for name, num in _MONATE.items() if name in txt}
    # "jedes Monats" / "monatlich" => alle Monate als Basis
    if 'jedes monat' in txt or 'monatlich' in txt or 'jeden monat' in txt or not genannt:
        erlaubt = set(range(1, 13))
    else:
        erlaubt = set(genannt)
    # Ausschlüsse: "ausser Dezember", "ausgenommen ..."
    if 'ausser' in txt or 'ausgenommen' in txt or 'ausg.' in txt:
        pos = max(txt.find('ausser'), txt.find('ausgenommen'), txt.find('ausg.'))
        schwanz = txt[pos:]
        for name, num in _MONATE.items():
            if name in schwanz:
                erlaubt.discard(num)
    return erlaubt or set(range(1, 13))


def _monatsende(jahr: int, monat: int) -> _dt.date:
    return _dt.date(jahr, monat, calendar.monthrange(jahr, monat)[1])


# Postweg + 7-Tage-Abholfrist eines Einschreibens: das Formular muss dem Mieter
# ZUGEHEN (Empfangstheorie), nicht bloss versandt sein. Ohne Puffer wäre eine am
# Stichtag versandte Erhöhung real zu spät zugestellt → erst am Folgetermin
# wirksam bzw. anfechtbar. Gleicher Wert wie ZUSTELL_PUFFER in fw_verzug_257d.
ZUSTELL_PUFFER_TAGE = 7


def naechster_anpassungstermin(vertrag, ankuendigung_datum: _dt.date) -> _dt.date:
    """Frühester Termin, auf den eine Mietzinserhöhung wirksam werden kann.
    Die Mitteilung muss dem Mieter mindestens 10 Tage VOR Beginn der Kündigungs-
    frist ZUGEHEN (Art. 269d OR, Empfangstheorie). Wir rechnen daher Ankündigung
    + Zustellpuffer (Postweg/Abholfrist) + 10 Tage wie einen Kündigungseingang
    und nehmen den nächsten ordentlichen Kündigungstermin."""
    fiktiver_eingang = ankuendigung_datum + _dt.timedelta(days=ZUSTELL_PUFFER_TAGE + 10)
    termin = berechne_kuendigungstermin(vertrag, fiktiver_eingang)
    # Der Mietzins ist periodengerecht ab Monatsbeginn geschuldet — die Erhöhung
    # wird auf den ERSTEN des Folgemonats wirksam (Live-Test I). Explizit auf den
    # Monatsersten rechnen (nicht blind +1 Tag): der Normalfall ist ein Monatsende,
    # aber `erstmals_kuendbar_auf` könnte ausnahmsweise ein Nicht-Monatsende sein.
    if termin.month == 12:
        return _dt.date(termin.year + 1, 1, 1)
    return _dt.date(termin.year, termin.month + 1, 1)


def berechne_kuendigungstermin(vertrag, eingang_datum: _dt.date) -> _dt.date:
    """Nächster ordentlicher Kündigungstermin ab (Eingang + Kündigungsfrist),
    unter Beachtung der erlaubten Termin-Monate und 'erstmals kündbar auf'.

    Sonderfall gesondert vermietete Einstellplätze (Art. 266e OR): Frist von
    zwei Wochen auf Ende einer einmonatigen Mietdauer — nicht monatsbasiert."""
    einheit = getattr(vertrag, 'einheit', None)
    # Einstellplatz mit gesetzlicher 2-Wochen-Frist (kuendigungsfrist_monate <= 0).
    # Wurde eine LÄNGERE Monatsfrist vereinbart (> 0), gilt die normale
    # Monatslogik weiter unten (Frist in Monaten auf Monatsende).
    if (einheit is not None and getattr(einheit, 'ist_einstellplatz', False)
            and (vertrag.kuendigungsfrist_monate or 0) <= 0):
        # Frühestes Monatsende, das mindestens 14 Tage nach Eingang liegt.
        grenze = eingang_datum + _dt.timedelta(days=14)
        me = _monatsende(grenze.year, grenze.month)
        if me < grenze:
            nm = grenze.month % 12 + 1
            ny = grenze.year + (1 if grenze.month == 12 else 0)
            me = _monatsende(ny, nm)
        if vertrag.erstmals_kuendbar_auf and vertrag.erstmals_kuendbar_auf > me:
            return vertrag.erstmals_kuendbar_auf
        return me

    frist = int(vertrag.kuendigungsfrist_monate or 3)
    erlaubt = _erlaubte_termin_monate(vertrag.kuendigungstermine)

    # Frühestes Ende = Ende des Monats, der 'frist' Monate nach Eingang liegt
    m = eingang_datum.month - 1 + frist
    jahr = eingang_datum.year + m // 12
    monat = m % 12 + 1
    fruehestens = _monatsende(jahr, monat)
    if vertrag.erstmals_kuendbar_auf and vertrag.erstmals_kuendbar_auf > fruehestens:
        fruehestens = vertrag.erstmals_kuendbar_auf

    # Nächsten erlaubten Monats-Endtermin >= fruehestens finden (max 24 Monate vorwärts)
    kandidat = fruehestens
    for _ in range(25):
        if kandidat.month in erlaubt and kandidat >= fruehestens:
            return kandidat
        # nächster Monat
        nm = kandidat.month % 12 + 1
        ny = kandidat.year + (1 if kandidat.month == 12 else 0)
        kandidat = _monatsende(ny, nm)
    return fruehestens


def termin_257d(ab_datum: _dt.date) -> _dt.date:
    """Frühestmöglicher Kündigungstermin bei ausserordentlicher Kündigung wegen
    Zahlungsverzug (Art. 257d Abs. 2 OR): Frist von mindestens 30 Tagen auf Ende
    eines Monats. → Ende des Monats, in den (ab_datum + 30 Tage) fällt."""
    grenze = ab_datum + _dt.timedelta(days=30)
    return _monatsende(grenze.year, grenze.month)


# ---------------------------------------------------------------------------
# DocuSeal-Rueckläufer. Bisher in rentals/api.py, dort aber keine Endpunkte.
# Herausgezogen in E1a, unveraendert uebernommen.
# ---------------------------------------------------------------------------
def _erster_dokument_url(dokumente):
    """Extrahiert die erste Dokument-URL aus einer DocuSeal-Dokumentliste."""
    if isinstance(dokumente, list):
        for d in dokumente:
            if isinstance(d, dict) and d.get('url'):
                return d['url']
    return None


def _vertrag_id_aus_name(name):
    """Zieht die Vertrags-ID aus einem Namen wie 'Mietvertrag 3'."""
    if not name:
        return 0
    teil = str(name).split('Mietvertrag')[-1]
    ziffern = re.sub(r'[^0-9]', '', teil)
    try:
        return int(ziffern) if ziffern else 0
    except ValueError:
        return 0


def verarbeite_docuseal_event(payload):
    """Verarbeitet ein DocuSeal-Webhook-Event tolerant (verschiedene Payload-
    Varianten). Lädt bei Abschluss den unterschriebenen Vertrag herunter und
    legt ihn über vertrag.save() zentral überall ab. Gibt True zurück, wenn ein
    Vertrag aktualisiert wurde."""
    if not isinstance(payload, dict):
        return False
    event = str(payload.get('event_type') or payload.get('event') or '').lower()
    data = payload.get('data')
    if not isinstance(data, dict):
        data = payload
    status = str(data.get('status') or '').lower()
    if 'completed' not in event and status != 'completed':
        return False   # nur vollständig unterschriebene Verträge ablegen

    submission = data.get('submission') if isinstance(data.get('submission'), dict) else {}
    name = data.get('name') or submission.get('name') or ''
    vertrag_id = _vertrag_id_aus_name(name)
    vertrag = Mietvertrag.objects.filter(id=vertrag_id).first() if vertrag_id else None
    if not vertrag:
        return False

    doc_url = (data.get('combined_document_url')
               or submission.get('combined_document_url')
               or _erster_dokument_url(data.get('documents'))
               or _erster_dokument_url(submission.get('documents')))
    if not doc_url:
        return False
    # SSRF-Schutz: die doc_url stammt aus dem Webhook-Payload — nur HTTPS und
    # erlaubte DocuSeal-Hosts herunterladen (identisch zu core/views/docuseal.py).
    from core.services.docuseal_service import download_url_erlaubt
    if not download_url_erlaubt(doc_url):
        logger.warning("DocuSeal-Event: Download-URL abgewiesen (%s)", doc_url)
        return False
    try:
        r = requests.get(doc_url, timeout=30)
    except Exception:
        return False
    if r.status_code != 200:
        return False
    vertrag.pdf_datei.save(f"Unterschrieben_Mietvertrag_{vertrag.id}.pdf",
                           ContentFile(r.content), save=False)
    vertrag.sign_status = 'unterzeichnet'
    if vertrag.status in ('entwurf', 'offen'):
        vertrag.status = 'aktiv'
    vertrag.save()   # → zentrale Ablage (Portal, Person, Objekt) via Model.save
    return True
