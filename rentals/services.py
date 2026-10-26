# rentals/services.py
import logging
import re
from decimal import Decimal

import requests
from django.core.files.base import ContentFile

from .models import Dokument, Mietvertrag

logger = logging.getLogger(__name__)

def bisheriger_stand(vertrag, wirksam_ab=None):
    """(Netto-Mietzins, Referenzzins, LIK), die unmittelbar VOR `wirksam_ab` gelten.

    Befund A (26.10.2026): Gerechnet wurde auf `vertrag.netto_mietzins` — dem
    Ursprungsmietzins, den keine Anpassung je fortschreibt. Die zweite Erhöhung
    setzte damit auf dem Betrag von vor der ersten auf, und die Prüfung
    «ist das eine Erhöhung?» verglich mit demselben veralteten Wert.

    Stichtag ist der Tag vor dem Wirksamwerden: Was dann gilt, ist der
    «bisherige» Mietzins des amtlichen Formulars — auch eine bereits versandte,
    aber erst später wirksame Anpassung zählt dazu. Ohne `wirksam_ab` gilt heute.
    Entwürfe zählen nie (`Mietvertrag._wirksame_anpassung`).
    """
    stichtag = (wirksam_ab - _dt.timedelta(days=1)) if wirksam_ab else _dt.date.today()
    netto = vertrag.effektiver_netto_mietzins(stichtag)
    ref, lik = vertrag.effektive_basis(stichtag)
    return netto, ref, lik


def berechne_mietpotenzial(vertrag, aktuell_ref, aktuell_lik, allg_kosten_pct=Decimal('0.00'),
                           wirksam_ab=None):
    """
    Berechnet das Erhöhungs- oder Senkungspotenzial nach Schweizer Mietrecht.
    Inklusive Referenzzinssatz, Teuerung (LIK) und allgemeiner Kostensteigerung.
    Rechenkerne und Herleitung: core.services.mietzins_rechner.

    Basis und Ausgangsmietzins sind der Stand, auf dem der Mietzins unmittelbar
    vor `wirksam_ab` beruht (`bisheriger_stand`: jüngste gebuchte Anpassung,
    Zeitplan, sonst Vertragsbeginn) — sonst würde ein bereits weitergegebener
    Zinsschritt ein zweites Mal verrechnet, und zwar auf dem falschen Betrag.
    """
    from core.services import mietzins_rechner as rz
    from core.services.mietrecht import runde_mietzins

    if not vertrag.basis_referenzzinssatz or not vertrag.basis_lik_punkte:
        return None

    netto_miete, basis_ref, basis_lik = bisheriger_stand(vertrag, wirksam_ab)
    basis_ref = Decimal(str(basis_ref))
    basis_lik = Decimal(str(basis_lik))
    curr_ref = Decimal(str(aktuell_ref))
    curr_lik = Decimal(str(aktuell_lik))
    netto_miete = Decimal(str(netto_miete or 0))

    zins_prozent = rz.referenzzins_prozent(basis_ref, curr_ref)       # 1. Referenzzinssatz
    lik_prozent = rz.lik_prozent(basis_lik, curr_lik)                 # 2. Teuerung (40 %)
    kosten_prozent = Decimal(str(allg_kosten_pct)).quantize(Decimal('0.01'))   # 3. Kosten
    total_prozent = zins_prozent + lik_prozent + kosten_prozent

    # Auf 5 Rappen gerundet (core.services.mietrecht.runde_mietzins): Der Vorschlag
    # 1699.08 war nicht zahlbar. Die Differenz folgt dem gerundeten Betrag.
    neue_miete = runde_mietzins(netto_miete * (1 + total_prozent / Decimal('100')))
    differenz_chf = neue_miete - netto_miete

    action = 'OK'
    if total_prozent > Decimal('0.5'):
        action = 'UP'
    elif total_prozent < Decimal('-0.5'):
        action = 'DOWN'

    hinweise = []
    if max(basis_ref, curr_ref) >= Decimal('5.00'):
        hinweise.append(
            f"Referenzzins {basis_ref} % → {curr_ref} %: Der Überwälzungssatz von 3 % je Viertelprozent gilt "
            "nur unter 5 % (Art. 13 VMWG). Bei höheren Sätzen gelten andere Sätze — "
            "Berechnung von Hand prüfen.")
    return {
        'hinweise': hinweise,
        'mieter': f"{vertrag.mieter}",
        'objekt': str(vertrag.einheit),
        'aktuell_chf': round(netto_miete, 2),
        'neu_chf': round(neue_miete, 2),
        'delta_chf': round(differenz_chf, 2),
        'delta_prozent': total_prozent,
        'zins_pct': zins_prozent, 'lik_pct': lik_prozent, 'kosten_pct': kosten_prozent,
        'zins_schritte': rz.zins_schritte(basis_ref, curr_ref),
        'details_zins': f"{zins_prozent}% (Ref: {basis_ref} -> {curr_ref})",
        'details_lik': f"{lik_prozent}% (Index: {basis_lik} -> {curr_lik})",
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


#: Numerischer Termin im Freitext: «31.03.», «30.6», «31.12» — Tag und Monat.
#: Eine Jahreszahl dahinter («31.03.2027») stört nicht, sie wird nicht gelesen.
_TERMIN_ZIFFERN = re.compile(r'(?<!\d)(\d{1,2})\.\s?(\d{1,2})(?!\d)')


def kuendigungstermine_parsen(kuendigungstermine: str):
    """Liest das Freitextfeld `kuendigungstermine` zu einer Liste (tag, monat).

    Gibt `None` zurück, wenn der Text KEINE Termine erkennen lässt — leer,
    «ortsüblich» o. Ä. Das ist der Unterschied zur Fassung bis 26.10.2026: Sie
    las einen leeren Text und Ziffern wie «31.03., 30.06., 30.09.» als «jedes
    Monatsende». Ein Vertrag mit drei Quartalsterminen wurde damit auf jedes
    Monatsende kündbar gerechnet — bis zu zwei Monate zu früh.

    Erkannt werden:
      · Ziffern «TT.MM» — der Tag wird übernommen, wie er dasteht;
      · Monatsnamen — Tag 31 (Monatsende, wird später auf die Monatslänge
        geklemmt), wie bisher;
      · «jedes Monat(s)» / «monatlich» — alle zwölf Monatsenden;
      · ein Ausschluss nach «ausser/ausgenommen» — per Name oder Ziffer.
    """
    txt = (kuendigungstermine or '').lower()
    if not txt.strip():
        return None
    pos_aus = [p for p in (txt.find('ausser'), txt.find('ausgenommen'), txt.find('ausg.'))
               if p >= 0]
    trenn = min(pos_aus) if pos_aus else len(txt)
    kopf, schwanz = txt[:trenn], txt[trenn:]

    termine = {}
    for t, m in _TERMIN_ZIFFERN.findall(kopf):
        tag, monat = int(t), int(m)
        if 1 <= tag <= 31 and 1 <= monat <= 12:
            termine[(tag, monat)] = True
    for name, num in _MONATE.items():
        if name in kopf:
            termine[(31, num)] = True
    if 'jedes monat' in kopf or 'jeden monat' in kopf or 'monatlich' in kopf:
        for num in range(1, 13):
            termine.setdefault((31, num), True)
    if not termine:
        return None

    if schwanz:
        aus_monate = {num for name, num in _MONATE.items() if name in schwanz}
        aus_monate |= {int(m) for _t, m in _TERMIN_ZIFFERN.findall(schwanz) if 1 <= int(m) <= 12}
        termine = {k: v for k, v in termine.items() if k[1] not in aus_monate}
    return sorted(termine, key=lambda tm: (tm[1], tm[0])) or None


#: Herkunft der Termine, mit denen gerechnet wird — für Hinweise in der Oberfläche.
TERMINE_VERTRAG = 'vertrag'
TERMINE_KANTON = 'kanton'
TERMINE_FEHLEN = 'fehlt'


def _kanton_termine(vertrag):
    """Termine aus der Kündigungsregel des Kantons (Regelwerk der Organisation),
    als (tag, monat) — oder None.

    Das ist der Ort, an dem ortsübliche Termine in diesem Bestand hinterlegt
    werden (`faelle.regelwerk_models.Regel`, Parameter `termine`). Der Grund-
    Regelsatz trägt bewusst KEINE Termine (siehe `regelwerk_grundsatz`): sie
    sind kantonal verschieden. Fehlt die Regel, wird nichts angenommen.
    """
    try:
        from faelle.regelwerk import regel_holen
        from core.views.fw.regelwerk import _kanton_zum_vertrag
        regel = regel_holen(vertrag.organisation, 'kuendigungstermin',
                            _kanton_zum_vertrag(vertrag))
    except Exception:
        logger.warning("Kantonsregel für Kündigungstermine nicht lesbar", exc_info=True)
        return None
    roh = list((getattr(regel, 'parameter', None) or {}).get('termine') or [])
    termine = []
    for eintrag in roh:
        try:
            t, m = (int(x) for x in str(eintrag).strip().rstrip('.').split('.')[:2])
        except ValueError:
            continue
        if 1 <= t <= 31 and 1 <= m <= 12:
            termine.append((t, m))
    return termine or None


def kuendigungstermine_fuer(vertrag):
    """(Termine als [(tag, monat)], Herkunft).

    Reihenfolge: was im Vertrag steht → die Kantonsregel des Regelwerks →
    nichts. Bei «nichts» (`TERMINE_FEHLEN`) rechnet `berechne_kuendigungstermin`
    weiter mit jedem Monatsende, damit Aufrufer ein Datum haben — das ist
    dann der FRÜHESTE denkbare Termin, kein geltender. Jede Oberfläche, die
    ihn zeigt, muss den fehlenden Eintrag melden (`TERMINE_FEHLEN`).
    """
    eigene = kuendigungstermine_parsen(getattr(vertrag, 'kuendigungstermine', ''))
    if eigene:
        return eigene, TERMINE_VERTRAG
    if getattr(vertrag, 'pk', None):
        kanton = _kanton_termine(vertrag)
        if kanton:
            return kanton, TERMINE_KANTON
    return [(31, m) for m in range(1, 13)], TERMINE_FEHLEN


def _monatsende(jahr: int, monat: int) -> _dt.date:
    return _dt.date(jahr, monat, calendar.monthrange(jahr, monat)[1])


# Postweg + 7-Tage-Abholfrist eines Einschreibens: das Formular muss dem Mieter
# ZUGEHEN (Empfangstheorie), nicht bloss versandt sein. Ohne Puffer wäre eine am
# Stichtag versandte Erhöhung real zu spät zugestellt → erst am Folgetermin
# wirksam bzw. anfechtbar. Gleicher Wert wie ZUSTELL_PUFFER in fw_verzug_257d.
ZUSTELL_PUFFER_TAGE = 7


def vermuteter_zugang(versand_am: _dt.date, zugang_am: _dt.date = None) -> _dt.date:
    """Bestätigter Zugang, sonst Versand + Zustellpuffer.

    Dieselbe Vermutung wie für Art. 269d (unten) und die 257d-Fristansetzung
    (`fw_verzug_257d`): Massgebend ist, wann das Schreiben dem Empfänger
    ZUGEHT. Solange das nicht feststeht, wird spät angenommen — eine darauf
    gerechnete Frist endet dann eher zu spät als zu früh."""
    if zugang_am:
        return zugang_am
    return versand_am + _dt.timedelta(days=ZUSTELL_PUFFER_TAGE)


def naechster_anpassungstermin(vertrag, ankuendigung_datum: _dt.date,
                               zugang_am: _dt.date = None) -> _dt.date:
    """Frühester Termin, auf den eine Mietzinserhöhung wirksam werden kann.
    Die Mitteilung muss dem Mieter mindestens 10 Tage VOR Beginn der Kündigungs-
    frist ZUGEHEN (Art. 269d OR, Empfangstheorie). Wir rechnen daher den Zugang
    (bestätigt, sonst Ankündigung + Zustellpuffer für Postweg/Abholfrist) + 10
    Tage wie einen Kündigungseingang und nehmen den nächsten ordentlichen
    Kündigungstermin."""
    fiktiver_eingang = (vermuteter_zugang(ankuendigung_datum, zugang_am)
                        + _dt.timedelta(days=10))
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
    termine, _herkunft = kuendigungstermine_fuer(vertrag)

    # Ende der Kündigungsfrist: Eingang + Frist, Tag auf die Monatslänge
    # geklemmt. Für Monatsend-Termine ergibt das dasselbe wie die frühere
    # Rechnung «Ende des Monats Eingang + Frist»; für einen Termin mitten im
    # Monat («15.03.») ist es die genaue Grenze.
    m = eingang_datum.month - 1 + frist
    jahr = eingang_datum.year + m // 12
    monat = m % 12 + 1
    fristende = _dt.date(jahr, monat, min(eingang_datum.day, calendar.monthrange(jahr, monat)[1]))

    def _naechster(ab):
        kandidaten = sorted(
            _dt.date(j, mo, min(t, calendar.monthrange(j, mo)[1]))
            for j in range(ab.year, ab.year + 4)
            for t, mo in termine)
        return next((k for k in kandidaten if k >= ab), _monatsende(ab.year, ab.month))

    regulaer = _naechster(fristende)
    erstmals = vertrag.erstmals_kuendbar_auf
    if erstmals and erstmals > regulaer:
        # «Erstmals kündbar auf» ist selbst ein vereinbarter Termin — liegt er
        # in einem Terminmonat, gilt er wie bisher unmittelbar.
        if any(mo == erstmals.month for _t, mo in termine):
            return erstmals
        return _naechster(erstmals)
    return regulaer


def termine_aus_vertrag(vertrag) -> list:
    """Die Kündigungstermine des Vertrags als ['TT.MM', ...] für das Regelwerk.

    DIE NAHTSTELLE ZWISCHEN FREITEXT UND REGEL

    `Mietvertrag.kuendigungstermine` ist ein Freitextfeld («Ende jedes Monats
    ausser Dezember»). `faelle.regelwerk.kuendigungstermin` erwartet dagegen
    eine Liste konkreter Termine. Diese Funktion ist die einzige Stelle, an der
    das eine ins andere übersetzt wird — die Freitext-Deutung bleibt damit bei
    `kuendigungstermine_parsen` und wird nicht ein zweites Mal geschrieben.

    Bei Monatsnamen ist der Tag `31`. `regelwerk.termine_als_daten` klemmt ihn
    auf die Monatslänge, aus `31.02` wird der 28. bzw. 29. Februar. Ein hier
    fest verdrahteter 28. wäre in Schaltjahren falsch. Bei Ziffern («30.06.»)
    gilt der genannte Tag.
    """
    # Leer, wenn der Vertrag nichts Lesbares enthält: Dann greift im Regelwerk
    # die Kantonsregel (`pruefung_zum_vertrag`) — und fehlt auch sie, meldet
    # die Prüfung «keine Kündigungstermine hinterlegt», statt wie bis
    # 26.10.2026 stillschweigend jedes Monatsende zuzulassen.
    return [f'{tag:02d}.{monat:02d}' for tag, monat in (
        kuendigungstermine_parsen(vertrag.kuendigungstermine) or [])]


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
    # `alle_organisationen`: DocuSeal ruft als Webhook auf — keine Anmeldung,
    # kein Mandantenkontext. Ueber `objects` fand die Zeile seit Etappe 6.2
    # nichts mehr, sondern warf; die Ausnahme wurde vom Aufrufer geschluckt und
    # der Webhook meldete 200 OK. Folge: Ein unterschriebener Vertrag wurde
    # NIE abgelegt, ohne dass irgendwo ein Fehler erschien.
    #
    # Die Vertrags-ID stammt aus dem Namen der Submission, den wir selbst
    # gesetzt haben. Ab dem Fund gilt der Kontext dieses Vertrags.
    vertrag = Mietvertrag.alle_organisationen.filter(id=vertrag_id).first() if vertrag_id else None
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
