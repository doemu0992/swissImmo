"""Pflege der verschlüsselten Werte ohne Terminal: Zustand, Nachholen, Schlüsselwechsel (Oberfläche und Deploy).

Dieselben Schritte, die früher `ahv_verschluesseln`, `postfaecher_uebernehmen` und `schluessel_wechseln` von Hand liefen,
laufen jetzt (a) automatisch nach jedem `migrate` (Deploy) und (b) per Knopf unter Einstellungen → Sicherheit.
Gerechnet wird mit SQL auf der Spalte, nicht über die Felder: Werte werden nur umgeschrieben, nie im Klartext gehalten
oder protokolliert.
"""
import logging
import os
from dataclasses import dataclass, field

from django.apps import apps
from django.db import connection, transaction

from core.services import geheimnis
from core.verschluesselt import sieht_verschluesselt_aus

logger = logging.getLogger(__name__)

#: Alles, was mit dem Schlüssel verschlüsselt in der Datenbank steht: (App, Modell, Feld).
#: Neue verschlüsselte Spalten gehören HIER hinein — sonst überleben sie keinen Schlüsselwechsel.
GEHEIME_FELDER = (
    ('core', 'Postfach', 'passwort_geheim'),
    ('core', 'Postfach', 'refresh_token_geheim'),
    ('crm', 'Mieter', 'ahv_nummer'),
    ('core', 'ZweiterFaktor', 'geheimnis'),
)


def _spalte(app, modell, feld):
    m = apps.get_model(app, modell)
    return m._meta.db_table, m._meta.get_field(feld).column, m._meta.pk.column


def _werte():
    """Alle gespeicherten, nicht leeren Rohwerte: ((App, Modell, Feld), Tabelle, Spalte, pk-Spalte, pk, Wert)."""
    with connection.cursor() as cur:
        for app, modell, feld in GEHEIME_FELDER:
            try:
                tabelle, spalte, pk = _spalte(app, modell, feld)
                cur.execute(f'SELECT "{pk}", "{spalte}" FROM "{tabelle}" WHERE "{spalte}" <> %s', [''])
                zeilen = cur.fetchall()
            except Exception:                                    # noqa: BLE001 — Tabelle noch nicht da (frische Datenbank)
                continue
            for zeile_pk, wert in zeilen:
                yield (app, modell, feld), tabelle, spalte, pk, zeile_pk, wert


@dataclass
class Zustand:
    quelle: str = ''
    schluessel_anzahl: int = 0
    klartext: int = 0            # noch unverschlüsselt (Altbestand)
    aktuell: int = 0             # mit dem aktuellen (ersten) Schlüssel lesbar
    alt: int = 0                 # nur mit einem älteren Schlüssel lesbar → umstellen
    unlesbar: list = field(default_factory=list)
    erneuerbar: bool = False     # Schlüssel liegt in der selbst angelegten Datei → «Erneuern» per Knopf möglich

    @property
    def alles_gut(self):
        return bool(self.quelle) and not self.klartext and not self.alt and not self.unlesbar


def zustand() -> Zustand:
    z = Zustand(quelle=geheimnis.schluessel_quelle())
    if not z.quelle:
        return z
    z.schluessel_anzahl = len(geheimnis._schluesselliste())
    z.erneuerbar = z.quelle == 'automatisch'
    for (app, modell, feld), _t, _s, _p, zeile_pk, wert in _werte():
        if not sieht_verschluesselt_aus(wert):
            z.klartext += 1
        elif geheimnis.mit_erstem_schluessel_lesbar(wert):
            z.aktuell += 1
        else:
            try:
                geheimnis.entschluesseln(wert)
                z.alt += 1
            except geheimnis.GeheimtextKaputt:
                z.unlesbar.append(f'{app}.{modell}.{feld} #{zeile_pk}')
    return z


def nachholen() -> int:
    """Verschlüsselt Werte, die noch im Klartext stehen (Altbestand). Gibt die Anzahl zurück. Wiederholbar."""
    if not geheimnis.schluessel_vorhanden():
        return 0
    neu = []
    for _f, tabelle, spalte, pk, zeile_pk, wert in _werte():
        if not sieht_verschluesselt_aus(wert):
            neu.append((tabelle, spalte, pk, zeile_pk, geheimnis.verschluesseln(wert)))
    _schreiben(neu)
    return len(neu)


def umstellen():
    """Schreibt alles, was mit einem älteren Schlüssel lesbar ist, auf den ersten um. → (umgeschrieben, unlesbar)."""
    neu, unlesbar = [], []
    for (app, modell, feld), tabelle, spalte, pk, zeile_pk, wert in _werte():
        if not sieht_verschluesselt_aus(wert) or geheimnis.mit_erstem_schluessel_lesbar(wert):
            continue
        try:
            neu.append((tabelle, spalte, pk, zeile_pk, geheimnis.neu_verschluesseln(wert)))
        except geheimnis.GeheimtextKaputt:
            unlesbar.append(f'{app}.{modell}.{feld} #{zeile_pk}')
    _schreiben(neu)
    return len(neu), unlesbar


def _schreiben(aenderungen):
    if not aenderungen:
        return
    with transaction.atomic(), connection.cursor() as cur:
        for tabelle, spalte, pk, zeile_pk, wert in aenderungen:
            cur.execute(f'UPDATE "{tabelle}" SET "{spalte}" = %s WHERE "{pk}" = %s', [wert, zeile_pk])


class ErneuernNichtMoeglich(Exception):
    """Der Schlüssel kommt nicht aus der selbst angelegten Datei — dann liegt er in der `.env` o. Ä., und die
    Anwendung ändert fremde Konfiguration nicht."""


def erneuern():
    """Neuer Schlüssel für die selbst angelegte Datei, alles umstellen, alten verwerfen. → (umgeschrieben, unlesbar).

    Reihenfolge, die nie etwas verliert: (1) Datei = NEU + ALT, (2) alles auf NEU umstellen, (3) Datei = NEU — nur,
    wenn nichts unlesbar blieb. Bricht es in (2) ab, stehen beide Schlüssel weiter in der Datei."""
    from cryptography.fernet import Fernet
    if geheimnis.schluessel_quelle() != 'automatisch':
        raise ErneuernNichtMoeglich('Der Schlüssel liegt nicht in der selbst angelegten Schlüsseldatei.')
    pfad = geheimnis.autoschluessel_pfad()
    alt = pfad.read_text(encoding='utf-8').strip()
    neu = Fernet.generate_key().decode()
    _datei_ersetzen(pfad, f'{neu}\n{alt}\n')
    umgeschrieben, unlesbar = umstellen()
    if not unlesbar:
        _datei_ersetzen(pfad, neu + '\n')
    return umgeschrieben, unlesbar


def _datei_ersetzen(pfad, inhalt):
    """Atomar ersetzen (temporäre Datei, dann umbenennen), Rechte 600."""
    tmp = pfad.with_name(pfad.name + '.neu')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(inhalt)
    os.replace(tmp, pfad)


def nach_migration(**_kw):
    """`post_migrate`: Beim Deploy Altbestand von selbst verschlüsseln (statt `ahv_verschluesseln` von Hand).

    Nie ein Grund, das Deploy zu stören: Fehler werden protokolliert, nicht geworfen."""
    try:
        n = nachholen()
        if n:
            logger.info('%s Werte nach dem Deploy verschlüsselt.', n)
    except Exception:                                            # noqa: BLE001
        logger.warning('Verschlüsselung des Altbestands nach dem Deploy nicht möglich.', exc_info=True)
