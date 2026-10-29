"""Auskunftsrecht (DSG Art. 25) und Datenübertragung (Art. 28): alle Daten zu EINER Person.

Die Verwaltung muss einer Person auf Verlangen mitteilen, welche Personendaten über sie
bearbeitet werden (innert 30 Tagen, Art. 25 DSG; Verordnung Art. 16-18 VDSG). Bisher
musste das aus 15 Tabellen von Hand zusammengesucht werden (Audit SICH-13).

`auskunft_daten(mieter)` sammelt alles, was an der Person hängt, als Datenstruktur;
`auskunft_zip(mieter)` verpackt sie als `auskunft.json` (gängiges, maschinenlesbares
Format) und legt die Dokumente der Person bei.

Mandantentrennung: Alle Abfragen laufen über die Tenant-Manager. Eine Person einer anderen
Verwaltung ist hier nicht erreichbar, und es gelangen nur Daten dieser Verwaltung ins Paket.

Nicht Teil davon (Fachpunkt): Daten, die ausserhalb dieser Anwendung liegen (Postfach der
Verwaltung, Hausbank, DocuSeal, Groq, Brevo) und die Empfänger nach Art. 25 Abs. 2 lit. c
DSG. Die Datenschutzerklärung nennt sie noch nicht vollständig (SICH-13).
"""
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q

#: Technische Spalten, die nicht zur Auskunft gehören.
_NICHT = {'organisation'}


def _wert(wert):
    if isinstance(wert, (datetime, date)):
        return wert.isoformat()
    if isinstance(wert, Decimal):
        return str(wert)
    if hasattr(wert, 'name') and hasattr(wert, 'storage'):          # FieldFile
        return wert.name or ''
    return wert


def _zeile(objekt, ohne=()):
    """Alle Spalten eines Datensatzes als Dict (Fremdschlüssel als ID, Dateien als Name)."""
    daten = {}
    for feld in objekt._meta.concrete_fields:
        if feld.name in _NICHT or feld.name in ohne:
            continue
        daten[feld.name] = _wert(getattr(objekt, feld.attname if feld.is_relation else feld.name))
    return daten


def _liste(qs, ohne=()):
    return [_zeile(o, ohne) for o in qs]


def auskunft_daten(mieter):
    """Sammelt die Daten der Person. Rückgabe: (daten: dict, dateien: [(zip_pfad, FieldFile)])."""
    from core.models import AktivitaetsLog
    from crm.models import Kommunikation
    from finance.models import Betreibung, DebitorenRechnung, Mahnung, Zahlungseingang
    from mietprozess.models import Mietbewerbung
    from rentals.models import Abnahmeprotokoll, Dokument, Kuendigung, Mietvertrag
    from tickets.models import SchadenMeldung, TicketNachricht

    vertraege = Mietvertrag.objects.filter(
        Q(mieter=mieter) | Q(mitmieter=mieter) | Q(weitere_mieter=mieter)).distinct()
    schaeden = SchadenMeldung.objects.filter(gemeldet_von=mieter)
    if mieter.email:
        schaeden = SchadenMeldung.objects.filter(Q(gemeldet_von=mieter) | Q(email_melder__iexact=mieter.email))
    dokumente = list(Dokument.objects.filter(Q(mieter=mieter) | Q(vertrag__in=vertraege)).distinct())

    daten = {
        'hinweis': ('Auskunft nach Art. 25 DSG. Enthält die Daten, die diese Verwaltung zur Person '
                    'in immoswiss bearbeitet. Daten ausserhalb der Anwendung sind nicht enthalten.'),
        'erstellt_am': datetime.now().astimezone().isoformat(timespec='seconds'),
        'person': _zeile(mieter),
        'adressen': _liste(mieter.adressen.all()),
        'mietvertraege': _liste(vertraege),
        'rechnungen': _liste(DebitorenRechnung.objects.filter(vertrag__in=vertraege)),
        'zahlungen': _liste(Zahlungseingang.objects.filter(vertrag__in=vertraege)),
        'mahnungen': _liste(Mahnung.objects.filter(vertrag__in=vertraege)),
        'betreibungen': _liste(Betreibung.objects.filter(vertrag__in=vertraege)),
        'kuendigungen': _liste(Kuendigung.objects.filter(vertrag__in=vertraege)),
        'abnahmeprotokolle': _liste(Abnahmeprotokoll.objects.filter(vertrag__in=vertraege)),
        'korrespondenz': _liste(Kommunikation.objects.filter(mieter=mieter)),
        'schadenmeldungen': _liste(schaeden),
        'schaden_nachrichten': _liste(TicketNachricht.objects.filter(ticket__in=[s.pk for s in schaeden])),
        'dokumente': _liste(dokumente),
        'bewerbungen': _liste(Mietbewerbung.objects.filter(email__iexact=mieter.email)) if mieter.email else [],
        'aktivitaeten': _liste(AktivitaetsLog.objects.filter(ziel_typ='person', ziel_id=mieter.pk),
                               ohne=('ip_adresse',)),
        'portal_konto': ({'benutzername': mieter.benutzer.username, 'email': mieter.benutzer.email}
                         if mieter.benutzer_id else None),
    }
    dateien = [(f'dokumente/{d.pk}_{(d.datei.name or "").rsplit("/", 1)[-1]}', d.datei) for d in dokumente if d.datei]
    return daten, dateien


def auskunft_zip(mieter):
    """Das Auskunftspaket als ZIP-Bytes: `auskunft.json` plus `dokumente/…`."""
    daten, dateien = auskunft_daten(mieter)
    daten['dateien'] = [pfad for pfad, _f in dateien]
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('auskunft.json', json.dumps(daten, ensure_ascii=False, indent=2, default=str))
        for pfad, datei in dateien:
            try:
                with datei.storage.open(datei.name, 'rb') as f:
                    z.writestr(pfad, f.read())
            except (OSError, ValueError):
                z.writestr(pfad + '.fehlt.txt', 'Die Datei ist im Speicher nicht mehr vorhanden.')
    return puffer.getvalue()
