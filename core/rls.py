"""Row-Level-Security (PostgreSQL): die Datenbank trennt die Verwaltungen ein zweites Mal — zuerst nur beim Lesen der
Finanztabellen.

WARUM. Die Trennung der Verwaltungen liegt im Code (`core/tenancy.py`: `TenantManager`, Fehler ohne Kontext). Ein
Programmierfehler, der diesen Filter umgeht (rohes SQL, ein vergessener Manager), liest fremde Daten. Mit RLS blendet
PostgreSQL fremde Zeilen selbst aus.

DREI STUFEN (`settings.RLS_MODUS`, Umgebung `RLS_MODUS`)
* `aus`     (Vorgabe) nichts.
* `probe`   sperrt nichts. Die Anwendung protokolliert jeden Finanzdatensatz, der mit gesetzter Verwaltung geladen
            wird und einer ANDEREN gehört: genau die Zugriffe, die «scharf» ausblendete. Erst wenn das Protokoll leer
            bleibt, wird scharf geschaltet.
* `scharf`  die Anwendung setzt bei jeder Abfrage die Sitzungsvariable `swissimmo.organisation`; die Regeln in der
            Datenbank (`manage.py rls_einrichten`) blenden fremde Zeilen beim LESEN aus.

DIE REGEL IST BEWUSST VORSICHTIG. Ohne gesetzte Verwaltung (Migrationen, Sicherungen, tägliche Läufe über alle
Verwaltungen, Anmeldung) lässt die Datenbank alles durch. Geschützt ist der Fall, der zählt: Eine Anfrage in
Verwaltung A liest Daten von Verwaltung B. Schreiben bleibt wie bisher (eigene, offene Regeln je Befehl; ohne sie
wiese PostgreSQL bei eingeschalteter RLS jedes Schreiben ab).

EINSCHALTEN IST ZWEITEILIG und beides ist ein bewusster Schritt, nichts davon geschieht beim Deploy:
  1. `manage.py rls_einrichten` (als Eigentümerin der Tabellen) legt die Regeln an; `--entfernen` nimmt sie zurück.
  2. `RLS_MODUS=scharf` in der `.env`. Ohne die Variable bleiben die Regeln wirkungslos (alles sichtbar), ohne die
     Regeln bleibt die Variable wirkungslos: Jeder Teil lässt sich einzeln zurücknehmen.

WAS DAS NICHT LEISTET (ehrlich): Ein Superuser und (ohne `FORCE`, das hier gesetzt wird) die Eigentümerin der Tabelle
umgehen RLS. Zählungen und Summen über fremde Zeilen sieht die Probe nicht (sie prüft geladene Datensätze). Geschützt
sind vorerst nur die Finanztabellen.
"""
import logging
import traceback

from django.conf import settings

logger = logging.getLogger(__name__)

VARIABLE = 'swissimmo.organisation'
REGEL = 'swissimmo_mandant'
MODI = ('aus', 'probe', 'scharf')
#: Apps, deren Modelle mit `organisation`-Spalte geschützt werden. Erweiterbar, sobald die Probe für weitere leer ist.
APPS = ('finance',)


def modus():
    wert = (getattr(settings, 'RLS_MODUS', 'aus') or 'aus').lower()
    return wert if wert in MODI else 'aus'


def modelle():
    """Die geschützten Modelle: alle der `APPS` mit eigener `organisation`-Spalte."""
    from django.apps import apps
    liste = []
    for app in APPS:
        for modell in apps.get_app_config(app).get_models():
            if any(f.attname == 'organisation_id' for f in modell._meta.concrete_fields) and modell._meta.managed:
                liste.append(modell)
    return liste


def tabellen():
    return sorted({m._meta.db_table for m in modelle()})


# ── Stufe «probe» ───────────────────────────────────────────────────────────────────────────────────────────────
#: Je Fundstelle höchstens ein Eintrag je so vielen Sekunden (die Probe läuft bei jedem geladenen Datensatz).
PROBE_RUHE_SEKUNDEN = 3600
AKTION_PROBE = 'RLS-Probe: fremde Zeile gelesen'


def _fundstelle():
    """Die innerste Zeile des EIGENEN Codes im Aufrufstapel (Projektverzeichnis, ohne dieses Modul und den Kontext)."""
    basis = str(settings.BASE_DIR)
    for rahmen in reversed(traceback.extract_stack(limit=60)[:-2]):
        datei = rahmen.filename
        if not datei.startswith(basis) or datei.endswith(('core/rls.py', 'core/tenancy.py')):
            continue
        return f'{datei[len(basis):].lstrip("/")}:{rahmen.lineno}'
    return 'unbekannt'


def _probe(sender, instance, **_kw):
    """`post_init` der geschützten Modelle: gehört der geladene Datensatz einer anderen als der gesetzten Verwaltung?"""
    from core.tenancy import aktuelle_organisation
    kontext = aktuelle_organisation()
    if kontext is None:
        return
    zeile = instance.__dict__.get('organisation_id')          # nie nachladen (ein verzögertes Feld löste eine Abfrage aus)
    if zeile is None or zeile == kontext.pk or instance.pk is None:
        return
    try:
        from django.core.cache import cache
        stelle = _fundstelle()
        schluessel = f'rls_probe:{sender._meta.label}:{stelle}'
        if not cache.add(schluessel, 1, PROBE_RUHE_SEKUNDEN):
            return
        logger.warning('RLS-Probe: %s der Verwaltung %s geladen im Kontext der Verwaltung %s (%s)',
                       sender._meta.label, zeile, kontext.pk, stelle)
        from core.models import SicherheitsEreignis
        SicherheitsEreignis.objects.create(
            aktion=AKTION_PROBE, objekt=sender._meta.label,
            details=f'Zeile der Verwaltung {zeile}, Kontext Verwaltung {kontext.pk}, Stelle {stelle}')
    except Exception:                                        # noqa: BLE001 — die Probe darf nie eine Seite brechen
        logger.exception('RLS-Probe: Befund nicht gespeichert')


def befunde_seit(tage=14):
    """Zahl der Probe-Befunde der letzten `tage` Tage (für die Betreiber-Startseite)."""
    from datetime import timedelta

    from django.utils import timezone

    from core.models import SicherheitsEreignis
    return SicherheitsEreignis.objects.filter(
        aktion=AKTION_PROBE, zeitpunkt__gte=timezone.now() - timedelta(days=tage)).count()


# ── Stufe «scharf»: die Sitzungsvariable folgt dem Mandantenkontext ───────────────────────────────────────────────
class _Abgleich:
    """`execute_wrapper` je Verbindung: Vor jeder Abfrage steht `swissimmo.organisation` auf der Verwaltung des Kontexts.

    WARUM VOR JEDER ABFRAGE UND NICHT BEIM SETZEN DES KONTEXTS. Der Kontext ist eine `ContextVar`, die Verbindung ein
    eigenes Ding mit eigener Lebensdauer (`CONN_MAX_AGE`); wer den Kontext setzt, weiss nichts von ihr. Geprüft wird
    deshalb dort, wo beides zusammenkommt. Gesendet wird nur, wenn sich etwas geändert hat.

    TRANSAKTIONEN. `set_config(..., false)` gilt für die Sitzung, wird aber mit zurückgerollt, wenn die Transaktion
    oder der Sicherungspunkt scheitert, in dem es geschah. Der gemerkte Stand enthält deshalb die Sicherungspunkte:
    Ändern sie sich, wird neu gesendet. Lieber eine Abfrage zu viel als eine Variable, die auf der falschen
    Verwaltung steht."""

    def __init__(self, verbindung):
        self.verbindung = verbindung
        self.stand = None
        self.laeuft = False

    def __call__(self, execute, sql, params, many, context):
        if not self.laeuft:
            from core.tenancy import aktuelle_organisation
            organisation = aktuelle_organisation()
            wert = str(organisation.pk) if organisation is not None else ''
            v = self.verbindung
            soll = (wert, v.in_atomic_block, tuple(v.savepoint_ids))
            if soll != self.stand:
                self.laeuft = True
                try:
                    # Roher Cursor: keine erneute Runde durch diesen Abgleich und kein Eintrag im Abfrageprotokoll.
                    context['cursor'].cursor.execute('SELECT set_config(%s, %s, false)', [VARIABLE, wert])
                    self.stand = soll
                finally:
                    self.laeuft = False
        return execute(sql, params, many, context)


def _verbindung_neu(sender, connection, **_kw):
    if connection.vendor == 'postgresql' and modus() == 'scharf':
        connection.execute_wrappers.append(_Abgleich(connection))


def verbinden():
    """Beim Start (`CoreConfig.ready`): je nach Modus die Probe oder den Abgleich einhängen. `aus` kostet nichts."""
    from django.db.backends.signals import connection_created
    from django.db.models.signals import post_init
    aktuell = modus()
    if aktuell == 'probe':
        for modell in modelle():
            post_init.connect(_probe, sender=modell, dispatch_uid=f'rls_probe_{modell._meta.label}')
    elif aktuell == 'scharf':
        connection_created.connect(_verbindung_neu, dispatch_uid='rls_abgleich')


# ── Regeln in der Datenbank ───────────────────────────────────────────────────────────────────────────────────────
def sql_einrichten(tabelle):
    """Die Befehle für eine Tabelle. Lesen: nur die eigene Verwaltung, oder alles ohne gesetzte Verwaltung.
    Schreiben: offen (eigene Regeln je Befehl; ohne sie wiese PostgreSQL das Schreiben ab)."""
    t = f'"{tabelle}"'
    eigene = (f"(coalesce(current_setting('{VARIABLE}', true), '') = '' "
              f"OR organisation_id::text = current_setting('{VARIABLE}', true))")
    return [
        f'ALTER TABLE {t} ENABLE ROW LEVEL SECURITY',
        f'ALTER TABLE {t} FORCE ROW LEVEL SECURITY',
        f'DROP POLICY IF EXISTS {REGEL}_lesen ON {t}',
        f'DROP POLICY IF EXISTS {REGEL}_anlegen ON {t}',
        f'DROP POLICY IF EXISTS {REGEL}_aendern ON {t}',
        f'DROP POLICY IF EXISTS {REGEL}_loeschen ON {t}',
        f'CREATE POLICY {REGEL}_lesen ON {t} FOR SELECT USING {eigene}',
        f'CREATE POLICY {REGEL}_anlegen ON {t} FOR INSERT WITH CHECK (true)',
        f'CREATE POLICY {REGEL}_aendern ON {t} FOR UPDATE USING (true) WITH CHECK (true)',
        f'CREATE POLICY {REGEL}_loeschen ON {t} FOR DELETE USING (true)',
    ]


def sql_entfernen(tabelle):
    t = f'"{tabelle}"'
    return [
        f'DROP POLICY IF EXISTS {REGEL}_lesen ON {t}',
        f'DROP POLICY IF EXISTS {REGEL}_anlegen ON {t}',
        f'DROP POLICY IF EXISTS {REGEL}_aendern ON {t}',
        f'DROP POLICY IF EXISTS {REGEL}_loeschen ON {t}',
        f'ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY',
        f'ALTER TABLE {t} DISABLE ROW LEVEL SECURITY',
    ]


def _ausfuehren(befehle):
    from django.db import connection, transaction
    with transaction.atomic(), connection.cursor() as c:
        for befehl in befehle:
            c.execute(befehl)


def einrichten():
    """Legt die Regeln für alle geschützten Tabellen an (wiederholbar). Gibt die Tabellen zurück."""
    liste = tabellen()
    _ausfuehren([b for t in liste for b in sql_einrichten(t)])
    return liste


def entfernen():
    liste = tabellen()
    _ausfuehren([b for t in liste for b in sql_entfernen(t)])
    return liste


def status():
    """Je geschützter Tabelle: ist RLS eingeschaltet, erzwungen, und wie viele eigene Regeln gibt es? `None` ohne
    PostgreSQL. Dazu die Rolle der Anwendung: Ein Superuser umgeht jede Regel."""
    from django.db import connection
    if connection.vendor != 'postgresql':
        return None
    with connection.cursor() as c:
        c.execute('SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user')
        rolle, superuser, umgeht = c.fetchone()
        zeilen = []
        for t in tabellen():
            c.execute('SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s AND relkind = %s',
                      [t, 'r'])
            zeile = c.fetchone() or (False, False)
            c.execute('SELECT count(*) FROM pg_policies WHERE tablename = %s AND policyname LIKE %s', [t, REGEL + '%'])
            zeilen.append({'tabelle': t, 'ein': zeile[0], 'erzwungen': zeile[1], 'regeln': c.fetchone()[0]})
    return {'modus': modus(), 'rolle': rolle, 'umgeht': bool(superuser or umgeht), 'tabellen': zeilen}
