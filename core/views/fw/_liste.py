"""Listen-Werkzeugkasten: Suche, Sortierung, Seiten und CSV (Audit Etappe 4).

Die Kernlisten hatten davon je nach Seite etwas oder nichts, und wo es etwas
gab, war es dreimal anders gebaut (Debitoren, Kreditoren, Logbuch). Hier steht
es einmal — für Listen, deren Zeilen schon in Python vorliegen (die
Liegenschaftsliste rechnet ihre Befunde je Zeile), und für Abfragen
(Mietverhältnisse, Personen), bei denen die Datenbank sortiert und blättert.

Die Reihenfolge ist immer dieselbe, und sie ist nicht beliebig:

    alle Zeilen → Suche → Befund-/Statusfilter → Sortierung → CSV oder Seite

Der CSV-Export nimmt dieselben Filter und dieselbe Sortierung wie die Ansicht,
aber ALLE Zeilen, nicht nur die aktuelle Seite. Wer «Leerstand» filtert und
exportiert, bekommt die Leerstände — und nicht die ersten 50 davon.
"""
import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable

from django.core.paginator import Paginator
from django.http import HttpResponse

PRO_SEITE = 50


@dataclass(frozen=True)
class Sortierung:
    """Eine wählbare Sortierung: Beschriftung, Schlüssel, Richtung."""

    label: str
    schluessel: Callable | None      # None = Reihenfolge wie geliefert
    absteigend: bool = False
    #: Für Abfragen: Felder für `order_by`. Dann sortiert die Datenbank, und
    #: `blaettern` liest nur die Zeilen der Seite — nicht den ganzen Bestand.
    felder: tuple = ()


def suchtext(request, feld='suche'):
    """Der Suchbegriff, getrimmt — auf die Länge eines Suchfelds begrenzt."""
    return (request.GET.get(feld) or '').strip()[:100]


def suche_anwenden(rows, begriff, text_von):
    """Zeilen, deren Text alle Wörter des Begriffs enthält (gross/klein egal).

    Mehrere Wörter grenzen ein: «Bahnhof Bern» findet die Bahnhofstrasse in
    Bern, nicht jede Liegenschaft in Bern und jede Bahnhofstrasse.
    """
    woerter = begriff.casefold().split()
    if not woerter:
        return rows
    return [r for r in rows
            if all(w in text_von(r).casefold() for w in woerter)]


def natuerlich(text):
    """Sortierschlüssel, der Zahlen als Zahlen liest: «Seeweg 9» vor
    «Seeweg 10». Bei Adressen mit Hausnummern ist alles andere falsch."""
    return [(0, int(t), '') if t.isdigit() else (1, 0, t)
            for t in re.split(r'(\d+)', (text or '').casefold()) if t]


def sortierung_waehlen(request, sorten, standard):
    """Der gewählte Sortierschlüssel; Unbekanntes fällt auf den Standard."""
    wahl = request.GET.get('sort') or standard
    return wahl if wahl in sorten else standard


def sortieren(rows, sorten, wahl):
    s = sorten[wahl]
    if s.felder:
        return rows.order_by(*s.felder)
    if s.schluessel is None:
        return list(rows)
    return sorted(rows, key=s.schluessel, reverse=s.absteigend)


def blaettern(request, rows, pro_seite=PRO_SEITE):
    """Die angefragte Seite und der Querystring ohne `seite`.

    `get_page` fängt Unsinn ab («abc» → erste, 999 → letzte Seite); ein Link
    auf eine Seite, die es nach dem Filtern nicht mehr gibt, endet so nicht
    auf einer leeren Liste.
    """
    seite = Paginator(rows, pro_seite).get_page(request.GET.get('seite') or 1)
    return seite, query_ohne(request, 'seite', 'export')


def query_ohne(request, *felder):
    q = request.GET.copy()
    for f in felder:
        q.pop(f, None)
    return q.urlencode()


def verdeckte_felder(request, *ausser):
    """(Name, Wert) der übrigen Parameter — als `<input type="hidden">` im
    Such-/Sortierformular, damit Absenden Filter und Liegenschaft nicht
    verliert. `seite` und `export` fallen immer weg."""
    weg = {'seite', 'export', *ausser}
    return [(k, v) for k, werte in request.GET.lists() if k not in weg
            for v in werte]


def query_mit(request, **aenderungen):
    """Querystring mit geänderten Werten; `None` oder '' entfernt ein Feld.

    Ein Wechsel von Filter, Suche oder Sortierung beginnt wieder auf Seite 1 —
    sonst landet man auf Seite 3 einer Liste, die nur noch eine Seite hat.
    """
    q = request.GET.copy()
    q.pop('seite', None)
    q.pop('export', None)
    for k, v in aenderungen.items():
        if v in (None, ''):
            q.pop(k, None)
        else:
            q[k] = v
    s = q.urlencode()
    return '?' + s if s else '?'


# Zeichen, mit denen Excel und LibreOffice eine Zelle als Formel lesen.
# Eine Strasse «=HYPERLINK(…)» wäre sonst beim Öffnen ein aktiver Link.
_FORMEL_ANFANG = ('=', '+', '-', '@', '\t', '\r')


def _zelle(wert):
    if wert is None:
        return ''
    if isinstance(wert, Decimal):
        return f'{wert:.2f}'
    if isinstance(wert, date):
        return wert.strftime('%d.%m.%Y')
    if isinstance(wert, (int, float)):
        return str(wert)
    text = str(wert)
    return "'" + text if text.startswith(_FORMEL_ANFANG) else text


def csv_antwort(dateiname, kopf, zeilen):
    """CSV für Excel (Schweiz): Semikolon, UTF-8 mit BOM, Beträge mit Punkt.

    Zahlen bleiben Zahlen — kein «CHF», kein Tausendertrennzeichen —, damit
    die Spalte in der Tabellenkalkulation rechnet.
    """
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{dateiname}"'
    resp.write('﻿')
    w = csv.writer(resp, delimiter=';')
    w.writerow(kopf)
    for z in zeilen:
        w.writerow([_zelle(x) for x in z])
    return resp
