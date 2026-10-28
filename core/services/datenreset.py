"""Datenreset («Gefahrenzone»): alle Betriebsdaten EINER Verwaltung entfernen.

WARUM ES DIESES MODUL GIBT (Audit 28.10.2026, SICH-03)

Der Reset lief als Schleife in der Ansicht: ein `delete()` je Modell, Fehler nur
als `logger.warning`, keine Transaktion. Gemessen (`probe12.py`): Buchungen und
Zahlungseingänge weg, Debitorenrechnungen und Fälle blieben stehen, dazu das
Audit-Log der Verwaltung gelöscht — ein buchhalterisch inkonsistenter Rest, ohne
Sicherung und ohne erneute Anmeldung, ausgelöst durch ein Wort im Formular.

Jetzt gilt:

* **Atomar.** Alles oder nichts. Bleibt auch nur eine Zeile übrig oder wirft ein
  Löschen, wird zurückgerollt; nichts ist halb gelöscht.
* **Vollständig.** Alle Apps mit Betriebsdaten (`faelle`, `stweg` eingeschlossen).
  Die Liste ist keine Handarbeit, sondern folgt dem Modellbestand: Was die Spalte
  `organisation` trägt und nicht ausdrücklich in `BEHALTEN` steht, wird geleert.
  Ein neues Modell ist damit automatisch dabei.
* **Reihenfolge nach den Abhängigkeiten.** Seit dem Löschschutz (FUNK-03) sind
  Verträge, Rechnungen und Abschlüsse `PROTECT`: Wer sie zuerst löschen will,
  bekäme einen `ProtectedError`. Die Reihenfolge ergibt sich aus den
  Fremdschlüsseln, nicht aus einer abgeschriebenen Liste.
* **Zuerst gesichert.** `manage.py sicherung` läuft vorher; ohne gelungene
  Sicherung gibt es keinen Reset.
* **Das Audit-Log bleibt.** Es ist die Spur dessen, was hier geschieht
  (Revisionspflicht, Art. 957 ff. OR / GeBüV); ein Reset, der seine eigene Spur
  löscht, wäre der bequemste Weg, sie zu verwischen.

Nicht Teil davon: hochgeladene Dateien im Medienordner bleiben liegen (die
Sicherung enthält die Datenbank; die Medien werden nicht angefasst).
"""
import io
import logging

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import ProtectedError, RestrictedError

logger = logging.getLogger(__name__)

#: Apps mit Betriebsdaten einer Verwaltung.
EIGENE_APPS = ('core', 'crm', 'finance', 'mietprozess', 'portfolio', 'rentals', 'tickets',
               'faelle', 'stweg')

#: Was der Reset NICHT anfasst — mit Grund. Wer hier etwas ergänzt, entscheidet,
#: dass ein Reset es überlebt; wer etwas vergisst, lässt es löschen.
BEHALTEN = {
    # Die Verwaltung selbst und wer in ihr arbeitet: «Meine Daten zurücksetzen» ist
    # nicht «meine Firma abmelden». Ohne Mitgliedschaft hätte nach dem Reset kein
    # Benutzer mehr eine Rolle.
    'crm.Organisation': 'ist der Mandant selbst (Firma, IBAN, Logo, Referenzzins)',
    'crm.Mitgliedschaft': 'trägt die Rolle jedes Teammitglieds',
    # Das Audit-Log: Revisionspflicht. Wird nie gelöscht, auch nicht vom Reset.
    'core.AktivitaetsLog': 'Audit-Log (Revision) — der Reset schreibt seinen eigenen Eintrag dazu',
    # Betreiberlog und Konto-Sicherheit gehören der Installation bzw. dem Konto,
    # nicht der Verwaltung.
    'core.SicherheitsEreignis': 'Betreiberlog der Installation',
    'core.ZweiterFaktor': 'hängt am Konto, nicht an der Verwaltung',
    'core.Wiederherstellungscode': 'Notfallcodes eines Kontos',
    # Konfiguration der Fallmaschine (wird vom Betrieb angelegt, nicht erfasst).
    # Ohne sie schlügen Zahlungsverzug, Mieterwechsel und Läufe nach dem Reset
    # stumm fehl.
    'faelle.Fallart': 'Konfiguration der Fallmaschine',
    'faelle.SchrittVorlage': 'Konfiguration der Fallmaschine',
    'faelle.Laufart': 'Konfiguration der Läufe',
    'faelle.Regelsatz': 'Regelwerk der Verwaltung (Grundsatz)',
    'faelle.Regel': 'Regelwerk der Verwaltung (Grundsatz)',
}


class ResetFehler(Exception):
    """Der Reset ist nicht gelaufen (oder wurde zurückgerollt). `str(e)` ist für den Benutzer."""


def sicherung_erstellen():
    """Sichert die Datenbank (ohne Medien) mit dem Dienst `manage.py sicherung`.

    Wirft `ResetFehler`, wenn keine gelesene Sicherung entstanden ist — dann darf
    nichts gelöscht werden. Die Medien bleiben beim Reset unberührt und werden
    deshalb nicht mitgesichert (ein Archiv über Gigabytes hielte die Anfrage auf).
    """
    ausgabe = io.StringIO()
    try:
        call_command('sicherung', ohne_medien=True, stdout=ausgabe, stderr=ausgabe)
    except CommandError as fehler:
        raise ResetFehler(str(fehler)) from fehler
    except Exception as fehler:                              # noqa: BLE001
        logger.exception('Datenreset: Sicherung abgebrochen')
        raise ResetFehler(f'{type(fehler).__name__}: {fehler}') from fehler
    return ausgabe.getvalue()


def betroffene_modelle():
    """Die Modelle, die der Reset leert — in der Reihenfolge, in der gelöscht wird."""
    vorhanden = set(connection.introspection.table_names())
    modelle = []
    for modell in apps.get_models():
        meta = modell._meta
        if meta.app_label not in EIGENE_APPS or meta.label in BEHALTEN:
            continue
        if meta.proxy or not meta.managed or meta.db_table not in vorhanden:
            # Ein Modell ohne Tabelle (zum Beispiel ein Testmodell in der Registry)
            # ist kein Fehler; ein `DELETE` darauf bräche den ganzen Reset ab.
            continue
        if not any(f.name == 'organisation' for f in meta.concrete_fields):
            # Ohne eigene Spalte gibt es keine Grenze, an der sich schneiden liesse.
            # Die Zählung unten fiele es auf — hier stehen sie nur, weil sie keine
            # Organisation tragen (`Benutzer`, Framework-Tabellen).
            continue
        modelle.append(modell)
    return _nach_abhaengigkeit(modelle)


def _nach_abhaengigkeit(modelle):
    """Zuerst die, die auf andere zeigen (PROTECT/RESTRICT), dann die Referenzierten."""
    menge = set(modelle)
    # kinder[T] = Modelle, die T per PROTECT/RESTRICT referenzieren → müssen VOR T weg
    muessen_vor = {m: set() for m in modelle}
    for modell in modelle:
        for f in modell._meta.concrete_fields:
            if not (f.is_relation and f.many_to_one or f.one_to_one):
                continue
            ziel = f.related_model
            on_delete = getattr(f.remote_field, 'on_delete', None)
            name = getattr(on_delete, '__name__', '')
            if ziel in menge and ziel is not modell and name in ('PROTECT', 'RESTRICT'):
                muessen_vor[ziel].add(modell)
    reihenfolge, fertig = [], set()
    offen = list(modelle)
    while offen:
        fortschritt = False
        for modell in list(offen):
            if muessen_vor[modell] <= fertig:
                reihenfolge.append(modell)
                fertig.add(modell)
                offen.remove(modell)
                fortschritt = True
        if not fortschritt:
            # Zyklus: der Rest kommt in beliebiger Reihenfolge; `_leeren` versucht es
            # mehrfach und meldet, was bleibt.
            reihenfolge.extend(offen)
            break
    return reihenfolge


def _zeilen(modell, organisation):
    # `_base_manager`: bewusst ungefiltert, die Grenze steht im Ausdruck
    # (`organisation=`). Der Tenant-Manager lieferte bei `Vorlage` zusätzlich die
    # SYSTEMVORLAGEN (organisation IS NULL) — ein `delete()` darauf traf alle
    # Verwaltungen.
    return modell._base_manager.filter(organisation=organisation)


def _leeren(modelle, organisation):
    """Löscht die Zeilen der Organisation; wiederholt, bis nichts mehr geht."""
    offen = list(modelle)
    for _durchgang in range(len(modelle) + 1):
        zurueck = []
        for modell in offen:
            if not _zeilen(modell, organisation).exists():
                continue
            try:
                with transaction.atomic():              # Sicherungspunkt: PostgreSQL vergiftet sonst die Transaktion
                    _zeilen(modell, organisation).delete()
            except (ProtectedError, RestrictedError):
                zurueck.append(modell)
        if not zurueck:
            return
        if len(zurueck) == len(offen):
            break
        offen = zurueck
    raise ResetFehler('Folgende Daten lassen sich nicht löschen, weil andere daran hängen: '
                      + ', '.join(m._meta.label for m in offen))


def setze_zurueck(organisation):
    """Leert die Betriebsdaten von `organisation` und setzt die Grunddaten neu auf.

    Muss in einer Transaktion laufen (der Aufrufer öffnet sie); wirft `ResetFehler`,
    wenn etwas übrig bleibt. Gibt die Zahl der geleerten Modelle zurück.
    """
    from core.services.mahnstufen import standard_mahnstufen_anlegen
    from core.services.raumkatalog import seed_lebensdauer
    from finance.booking import ensure_kontenplan

    modelle = betroffene_modelle()
    _leeren(modelle, organisation)

    rest = {m._meta.label: n for m in modelle if (n := _zeilen(m, organisation).count())}
    if rest:
        # Ein inkonsistenter Rest ist schlimmer als kein Reset.
        raise ResetFehler('Nach dem Löschen sind Daten übrig geblieben: '
                          + ', '.join(f'{k} ({n})' for k, n in sorted(rest.items())))

    # Grunddaten neu: Kontenplan, Lebensdauertabelle, Standard-Mahnstufen.
    ensure_kontenplan(organisation)
    seed_lebensdauer(organisation)
    standard_mahnstufen_anlegen(organisation)
    return len(modelle)
