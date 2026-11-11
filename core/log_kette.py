"""Hash-Kette im Audit-Log (Roadmap 2.3): Manipulation lässt sich nachweisen.

WAS SIE LEISTET
Jeder Eintrag des Audit-Logs trägt eine laufende Nummer je Verwaltung (`kette_nr`) und einen Hash (`kette_hash`), der den
Hash des Vorgängers einschliesst. Wird ein Eintrag gelöscht, verschoben, eingefügt oder in den gehashten Feldern geändert, passt
die Kette nicht mehr: `manage.py log_kette_pruefen` meldet die erste Bruchstelle. Weil der Trigger der Datenbank
(`core/log_schutz.py`) Änderungen ohnehin abweist, richtet sich die Kette gegen jemanden, der am Trigger vorbeikommt
(Tabelleneigentümer, `DISABLE TRIGGER`, Wiederherstellung einer manipulierten Sicherung).

WAS DER HASH ABDECKT
Verwaltung, laufende Nummer, Zeitpunkt, Aktion, Ziel (Typ und ID), Kategorie und den Hash des Vorgängers. NICHT: Benutzer, Objekt,
Details und IP-Adresse. Der Benutzerbezug wird legitim geleert (Konto gelöscht), Objekt und Details legitim anonymisiert
(DSG, `core/services/dsg.py`); beides würde die Kette sonst brechen. Wer nur diese Freitexte fälscht, bleibt unentdeckt.

DIE GRENZE (ehrlich)
Wer die Datenbank beliebig schreiben kann, kann die GANZE Kette neu berechnen. Dagegen hilft nur ein Ankerpunkt AUSSERHALB der
Datenbank: `manage.py log_kette_anker` schreibt den Kopf der Kette je Verwaltung (Nummer, Hash, Zeitpunkt) in eine Datei; wird sie
regelmässig ausser Haus abgelegt, gleicht `log_kette_pruefen --anker DATEI` sie mit der Kette ab. Ohne Anker erkennt die Prüfung
Brüche und Lücken, aber keine vollständig neu gerechnete Kette.
"""
import hashlib
from datetime import timezone

NULLHASH = '0' * 64


def kanonisch(eintrag, vorher):
    """Die Zeichenfolge, über die gehasht wird. Reihenfolge und Trenner sind Teil des Formats: nie ändern."""
    zeit = eintrag.zeitpunkt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')
    return '|'.join((
        str(eintrag.kette_nr), str(eintrag.organisation_id), zeit, eintrag.aktion,
        eintrag.ziel_typ or '', '' if eintrag.ziel_id is None else str(eintrag.ziel_id), eintrag.kategorie or '', vorher))


def kettenhash(eintrag, vorher):
    return hashlib.sha256(kanonisch(eintrag, vorher).encode('utf-8')).hexdigest()


def pruefen(organisation_id=None):
    """Prüft die Kette(n) und gibt `(anzahl_geprueft, befunde, koepfe)` zurück.

    `befunde`: Liste von Texten (leer = alles in Ordnung). `koepfe`: `{organisation_id: (kette_nr, kette_hash)}` des
    jüngsten Kettenglieds. Gemeldet werden Lücken in der Nummerierung (gelöschte Einträge), falsche Hashes (geänderte
    Felder) und Einträge ohne Kettenglied NACH dem Beginn der Kette (eingeschleust per rohem SQL)."""
    from core.models import AktivitaetsLog
    qs = AktivitaetsLog.alle_organisationen.all()
    if organisation_id is not None:
        qs = qs.filter(organisation_id=organisation_id)
    befunde, koepfe, geprueft = [], {}, 0
    erwartet = {}                     # organisation_id -> (naechste_nr, vorheriger_hash)
    erster_zeitpunkt = {}
    # Die Kette läuft nach NUMMER, nicht nach Zeitpunkt: Der Zeitpunkt steht beim Erzeugen des Eintrags fest, die Nummer erst beim
    # Siegeln. Bei gleichzeitigen Einträgen kann der frühere Zeitpunkt die spätere Nummer tragen — das ist keine Lücke.
    for e in qs.filter(kette_nr__isnull=False).order_by('organisation_id', 'kette_nr').iterator(chunk_size=2000):
        org = e.organisation_id
        nr, vorher = erwartet.get(org, (1, NULLHASH))
        if e.kette_nr != nr:
            befunde.append(f'Verwaltung {org}: Lücke bei Eintrag #{e.pk}: erwartet Nr. {nr}, gefunden {e.kette_nr} '
                           '(Eintrag gelöscht?).')
        soll = kettenhash(e, vorher)
        if e.kette_hash != soll:
            befunde.append(f'Verwaltung {org}: Hash von Eintrag #{e.pk} (Nr. {e.kette_nr}) stimmt nicht '
                           '(ein Feld der Kette wurde geändert).')
        erwartet[org] = (e.kette_nr + 1, e.kette_hash)
        koepfe[org] = (e.kette_nr, e.kette_hash)
        erster_zeitpunkt.setdefault(org, e.zeitpunkt)
        geprueft += 1
    # Einträge ohne Kettenglied sind nur vor dem Beginn der Kette in Ordnung (Altbestand wird bei der Migration gesiegelt).
    for e in qs.filter(kette_nr__isnull=True).order_by('organisation_id', 'zeitpunkt', 'pk').iterator(chunk_size=2000):
        beginn = erster_zeitpunkt.get(e.organisation_id)
        if beginn is not None and e.zeitpunkt >= beginn:
            befunde.append(f'Verwaltung {e.organisation_id}: Eintrag #{e.pk} ({e.zeitpunkt:%d.%m.%Y %H:%M}) steht ausserhalb der '
                           'Kette (nach dem Beginn der Kette eingefügt?).')
    return geprueft, befunde, koepfe


def mit_anker_vergleichen(anker_zeilen):
    """Gleicht gespeicherte Ankerpunkte `{organisation, kette_nr, kette_hash}` mit der Kette ab. Gibt Befunde zurück."""
    from core.models import AktivitaetsLog
    befunde = []
    for a in anker_zeilen:
        eintrag = AktivitaetsLog.alle_organisationen.filter(
            organisation_id=a['organisation'], kette_nr=a['kette_nr']).first()
        if eintrag is None:
            befunde.append(f'Anker Verwaltung {a["organisation"]} Nr. {a["kette_nr"]}: Eintrag fehlt in der Datenbank.')
        elif eintrag.kette_hash != a['kette_hash']:
            befunde.append(f'Anker Verwaltung {a["organisation"]} Nr. {a["kette_nr"]}: Hash weicht vom Anker ab '
                           '(die Kette wurde nach dem Anker verändert oder neu berechnet).')
    return befunde
