"""DSG-Löschung/Anonymisierung von Personendaten.

Nach dem Datenschutzgesetz (DSG) haben betroffene Personen ein Recht auf
Löschung ihrer Personendaten, sobald diese für den Zweck nicht mehr benötigt
werden. Buchhaltungsbelege (Debitorenrechnungen, Buchungen) unterliegen aber
der 10-jährigen Aufbewahrungspflicht (Art. 958f OR) und dürfen NICHT gelöscht
werden. Deshalb wird die Person nicht gelöscht, sondern ihre Stammdaten werden
ANONYMISIERT — die Buchungshistorie bleibt für die Revision erhalten, der
Personenbezug der Master-Daten wird aber entfernt.

Zusätzlich werden die hochgeladenen Bewerber-Dokumente (Ausweis, Lohnausweis,
Betreibungsauszug) physisch gelöscht — diese besonders schützenswerten Daten
haben keine Aufbewahrungspflicht.
"""
import logging
import os
import re

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Ersatztext für geschwärzte Stellen.
GESCHWAERZT = '[anonymisiert]'

#: Fachpunkt F2 (Audit): Die Vertragsdatei ist ein Geschäftsdokument (Art. 958f OR) UND trägt den
#: Namen im Inhalt. Standard: Datei und Inhalt bleiben aufbewahrt, aber der Dateiname wird
#: neutral (`Vertrag_<Name>.pdf` -> `Dokument_<id>.pdf`). Auf `True` setzen, wenn die Fachperson
#: entscheidet, dass die Datei beim Löschbegehren selbst entfernt wird.
VERTRAGSDATEI_LOESCHEN = False

#: Was nach der Anonymisierung bewusst stehen bleibt (mit Grund): Buchungsbelege und
#: Rechnungstitel sind unveränderlich bzw. Belege (Art. 958f OR). Der Test
#: `test_dsg_vollstaendig` hält diese Liste klein.
AUFBEWAHRT = {
    'finance.Buchung.beleg_text': 'Buchungsbeleg, unveränderlich (Art. 958f OR)',
    'finance.DebitorenRechnung.titel': 'Rechnungsbeleg (Art. 958f OR)',
}


def _kennzeichen(mieter):
    """Die Zeichenfolgen, an denen die Person in Freitexten erkennbar ist (längste zuerst)."""
    roh = [
        f'{mieter.vorname} {mieter.nachname}'.strip(), mieter.nachname, mieter.vorname, mieter.firmen_name,
        mieter.kontaktperson, mieter.email, mieter.ebill_email, mieter.telefon_privat, mieter.telefon_geschaeft,
        mieter.mobile, mieter.iban, mieter.zahler_iban, mieter.zahler_name, mieter.strasse, mieter.ahv_nummer,
        mieter.arbeitgeber, mieter.notfall_name, mieter.notfall_telefon,
    ]
    # Mindestlänge: «Ab» oder «Zi» in Freitexten zu schwärzen, zerstörte mehr als es schützt.
    return sorted({str(t).strip() for t in roh if t and len(str(t).strip()) >= 4}, key=len, reverse=True)


def _schwaerzen(text, kennzeichen):
    if not text:
        return text
    for k in kennzeichen:
        text = re.sub(re.escape(k), GESCHWAERZT, text, flags=re.IGNORECASE)
    return text


def _felder_schwaerzen(zeilen, felder, kennzeichen):
    """Schwärzt `felder` in jeder Zeile von `zeilen` (nur Zeilen, die sich ändern, werden gespeichert)."""
    n = 0
    for z in zeilen:
        geaendert = []
        for f in felder:
            alt = getattr(z, f, '') or ''
            neu = _schwaerzen(alt, kennzeichen)
            if neu != alt:
                setattr(z, f, neu)
                geaendert.append(f)
        if geaendert:
            z.save(update_fields=geaendert)
            n += 1
    return n


def _dateiname_neutralisieren(dokument, pid):
    """Benennt die Datei eines Dokuments um (`Vertrag_<Name>.pdf` -> `Dokument_<id>.pdf`), mit gleichem Inhalt.

    Mit `VERTRAGSDATEI_LOESCHEN` wird die Datei stattdessen entfernt."""
    if not dokument.datei:
        return
    try:
        if VERTRAGSDATEI_LOESCHEN:
            dokument.datei.delete(save=False)
            dokument.datei = ''
            dokument.save(update_fields=['datei'])
            return
        speicher = dokument.datei.storage
        alt = dokument.datei.name
        ordner, datei = os.path.split(alt)
        endung = os.path.splitext(datei)[1]
        with speicher.open(alt, 'rb') as quelle:
            from django.core.files.base import ContentFile
            neu = speicher.save(os.path.join(ordner, f'Dokument_{dokument.pk}{endung}'), ContentFile(quelle.read()))
        speicher.delete(alt)
        dokument.datei.name = neu
        dokument.save(update_fields=['datei'])
    except Exception:                                            # noqa: BLE001
        logger.exception('DSG: Dateiname von Dokument %s konnte nicht neutralisiert werden', dokument.pk)


def _freitexte_anonymisieren(mieter, kennzeichen, pid):
    """Schwärzt die Person in allen Freitexten, die an ihr hängen (Audit SICH-07: 16 Spalten)."""
    from core.models import AktivitaetsLog, Archiveintrag
    from crm.models import Kommunikation
    from finance.models import Zahlungseingang
    from rentals.models import Dokument, Mietvertrag
    from tickets.models import SchadenMeldung, TicketNachricht

    vertraege = Mietvertrag.objects.filter(mieter=mieter)
    _felder_schwaerzen(Kommunikation.objects.filter(mieter=mieter), ('betreff', 'inhalt'), kennzeichen)
    _felder_schwaerzen(vertraege, ('mitmieter_name',), kennzeichen)
    _felder_schwaerzen(Zahlungseingang.objects.filter(vertrag__in=vertraege), ('bemerkung', 'bank_referenz', 'klaerung_notiz'),
                       kennzeichen)

    # Schadenmeldungen: die der Person und die mit ihrer Kontaktangabe (Meldung per QR-Aushang).
    from django.db.models import Q
    bedingung = Q(gemeldet_von=mieter)
    for kontakt in (mieter.email, mieter.mobile, mieter.telefon_privat):
        if kontakt:
            bedingung |= Q(email_melder__iexact=kontakt) | Q(tel_melder=kontakt)
    meldungen = list(SchadenMeldung.objects.filter(bedingung).distinct())
    for sm in meldungen:
        sm.melder_vorname, sm.melder_nachname = 'Anonymisiert', f'#{pid}'
        sm.email_melder, sm.tel_melder = '', ''
        sm.save(update_fields=['melder_vorname', 'melder_nachname', 'email_melder', 'tel_melder'])
    _felder_schwaerzen(meldungen, ('titel', 'beschreibung'), kennzeichen)
    _felder_schwaerzen(TicketNachricht.objects.filter(ticket__in=[sm.pk for sm in meldungen]),
                       ('absender_name', 'nachricht'), kennzeichen)

    # Dokumente: Bezeichnung schwärzen, Dateiname neutral.
    dokumente = list(Dokument.objects.filter(Q(mieter=mieter) | Q(vertrag__in=vertraege)).distinct())
    _felder_schwaerzen(dokumente, ('bezeichnung',), kennzeichen)
    for d in dokumente:
        _dateiname_neutralisieren(d, pid)

    # Audit-Log und Archiv: Spur bleibt (wer, wann, was), der Name nicht.
    def _enthaelt(*feldnamen):
        q = Q(pk__in=[])
        for k in kennzeichen:
            for f in feldnamen:
                q |= Q(**{f'{f}__icontains': k})
        return q

    _felder_schwaerzen(AktivitaetsLog.objects.filter(_enthaelt('objekt', 'details')), ('objekt', 'details'), kennzeichen)
    _felder_schwaerzen(Archiveintrag.objects.filter(_enthaelt('bezeichnung', 'grund')), ('bezeichnung', 'grund'),
                       kennzeichen)



def kann_anonymisieren(mieter):
    """(ok, grund) — ein aktives Mietverhältnis blockiert die Anonymisierung."""
    aktiv = mieter.vertraege.filter(status='aktiv').count()
    aktiv += mieter.vertraege_als_mitmieter.filter(status='aktiv').count()
    if aktiv:
        return False, f"Person hat {aktiv} aktives/aktive Mietverhältnis(se) — zuerst beenden."
    if mieter.anonymisiert:
        return False, "Person ist bereits anonymisiert."
    return True, ""


def anonymisiere_person(mieter, *, grund='', user=None):
    """Anonymisiert die Stammdaten der Person + löscht Bewerber-Dokumente.
    Buchungsbelege bleiben erhalten (OR 958f). Gibt (ok, meldung) zurück."""
    ok, warum = kann_anonymisieren(mieter)
    if not ok:
        return False, warum

    pid = mieter.id
    # 1) Verknüpften Portal-Login entfernen (enthält Name/E-Mail).
    if mieter.benutzer_id:
        # Loslassen statt ueberall loeschen: Dasselbe Konto kann in einer
        # anderen Verwaltung noch ein Profil oder eine Mitgliedschaft haben.
        # Die Anonymisierung DIESER Person darf dort nichts entfernen.
        from core.auth import konto_freigeben
        _konto = mieter.benutzer
        mieter.benutzer = None
        konto_freigeben(_konto, getattr(mieter, 'organisation', None))

    # 2) Bewerbungen der Person anonymisieren + hochgeladene Dokumente löschen.
    from mietprozess.models import Mietbewerbung
    bewerbungen = Mietbewerbung.objects.filter(email__iexact=(mieter.email or '\x00'))
    for b in bewerbungen:
        for feld in ('betreibungsauszug', 'ausweiskopie', 'lohnausweis', 'weitere_dokumente'):
            datei = getattr(b, feld, None)
            if datei:
                try:
                    datei.delete(save=False)
                except Exception:
                    logger.debug("Fehler bewusst übergangen", exc_info=True)
        b.vorname = 'Anonymisiert'; b.nachname = f'#{pid}'
        b.email = f'anon-{pid}@example.invalid'; b.mobilnummer = ''
        b.adresse = ''; b.einkommen_jahr = ''; b.arbeitgeber = ''
        try:
            b.save()
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # 2b) Freitexte, Korrespondenz, Schadenakten, Dateinamen (VOR dem Überschreiben der Stammdaten,
    #     denn die Kennzeichen kommen aus ihnen).
    _freitexte_anonymisieren(mieter, _kennzeichen(mieter), pid)

    # 3) Stammdaten der Person überschreiben (Buchungsbelege bleiben unberührt).
    mieter.anrede = ''; mieter.kontaktperson = ''
    mieter.vorname = 'Anonymisiert'; mieter.nachname = f'Person #{pid}'
    mieter.firmen_name = ''; mieter.uid_nummer = ''
    mieter.geburtsdatum = None; mieter.ahv_nummer = ''
    mieter.zivilstand = ''; mieter.nationalitaet = ''; mieter.heimatort = ''
    mieter.erwerbsstatus = ''; mieter.beruf = ''; mieter.arbeitgeber = ''; mieter.einkommen_jahr = ''
    mieter.email = ''; mieter.telefon_privat = ''; mieter.telefon_geschaeft = ''; mieter.mobile = ''
    mieter.strasse = ''; mieter.adresszusatz = ''; mieter.postfach = ''; mieter.plz = ''; mieter.ort = ''
    # Datierte Adress-Historie enthält frühere Wohnorte (Personendaten) → löschen.
    try:
        mieter.adressen.all().delete()
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)
    mieter.aufenthaltsbewilligung = ''; mieter.bewilligung_gueltig_bis = None
    mieter.haftpflicht_gesellschaft = ''; mieter.haftpflicht_police = ''
    mieter.notfall_name = ''; mieter.notfall_telefon = ''; mieter.notfall_beziehung = ''
    mieter.haushalt_erwachsene = 0; mieter.haushalt_kinder = 0
    mieter.haustiere = False; mieter.haustiere_details = ''
    mieter.iban = ''; mieter.bank_name = ''; mieter.bonitaet_datum = None
    mieter.betreibung_ergebnis = ''
    mieter.zahlungsart = ''; mieter.ebill_email = ''; mieter.mahnsperre = False
    mieter.zahler_name = ''; mieter.zahler_adresse = ''; mieter.zahler_iban = ''
    mieter.ref_vermieter_name = ''; mieter.ref_vermieter_telefon = ''; mieter.ref_vermieter_email = ''
    mieter.vertretung_art = ''; mieter.vertretung_name = ''; mieter.vertretung_kontakt = ''
    heute = timezone.localdate()
    mieter.notizen = f"[{heute:%d.%m.%Y}] DSG-Anonymisierung{f' — {grund}' if grund else ''}."
    mieter.anonymisiert = True
    mieter.anonymisiert_am = heute
    mieter.save()

    from core.models import AktivitaetsLog
    AktivitaetsLog.objects.create(aktion="DSG-Anonymisierung", objekt=f"Person #{pid}",
                                  details=(grund or "Personendaten anonymisiert; Belege bleiben (OR 958f)."))
    return True, f"Person #{pid} anonymisiert — Buchungsbelege bleiben aufbewahrt (OR 958f)."
