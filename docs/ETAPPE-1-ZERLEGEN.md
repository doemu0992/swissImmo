# Etappe 1 — `fw.py` zerlegen

**Stand:** 14.08.2026 · gemessen an `main` (Commit `2894081`)
**Grundlage:** `docs/PHASE-2-PLAN.md` (Etappe 1), `docs/ANALYSE.md` (TS-2)
**Basis:** `main`
**Agent:** `zerleger`

---

## Warum das vor Phase 2 kommt

`core/views/fw.py` hat **14'983 Zeilen und 232 Views**. Jede mandantenbezogene Änderung, jedes Entitlement und jede Übersetzung muss durch diese Datei. Die Definition of Done verlangt geprüfte Mandantentrennung — ein Diff über 14'983 Zeilen ist nicht prüfbar, und ein Review, das niemand ernsthaft leisten kann, ist keines.

Die Etappe ändert **kein Verhalten**. Sie macht die folgenden überhaupt erst reviewbar.

---

## Die Schnittkanten liegen schon im Code

Die Datei ist mit Blockkommentaren gegliedert (`# ====` gefolgt von einer Überschrift). Das ergibt **33 Blöcke** plus einen Kopfbereich von 440 Zeilen. Diese Struktur hat jemand bereits gedacht — ihr folgen, keine eigenen Grenzen erfinden.

```bash
grep -nE "^# =+$" -A1 core/views/fw.py | grep -E "^[0-9]+-# [A-ZÄÖÜ0-9]"
```

Die acht grössten Blöcke:

| Zeilen | Views | Block |
|---:|---:|---|
| 1'834 | 33 | Etappe C: Detailseiten mit Breadcrumb + Tabs |
| 1'442 | 32 | Create-/Action-Views: alles in `/neu/` |
| 1'170 | 15 | Etappe B: Listen als Datentabellen |
| 1'089 | 4 | Etappe D: Bankabgleich |
| 862 | 22 | Profil-Menü: Account, Benutzer, Mandate, Vorlagen |
| 808 | 16 | Person-Detail (Mieter) |
| 714 | 5 | Etappe D: Vertragserstellung |
| 596 | 14 | Etappe D: Schadensfälle (Tickets) |

Die übrigen 25 liegen zwischen **34 und 585 Zeilen**.

---

## Zielstruktur

```
core/views/fw/
    __init__.py       re-exportiert alle Views — urls.py bleibt unberührt
    _basis.py         Kopfbereich: Modulimporte, blockübergreifende Helfer
    listen.py
    detailseiten.py
    mahnwesen.py
    bankabgleich.py
    …                 ein Modul je Block
```

`swiss_immo/urls.py` importiert weiter aus `core.views.fw` — durch das Re-Export in `__init__.py` bleibt jede der 293 benannten URLs unverändert. Damit bleibt der PR auf die Views beschränkt.

---

## Zwei Befunde, die den Umzug erleichtern

**Die Importe sind bereits lokal.** In der Datei stehen **1'063 Importe innerhalb von Funktionen** gegenüber nur **21 auf Modulebene**. Das ist kein Stilfehler, sondern umgeht bestehende Zyklen — und es bedeutet, dass ein Block seine Abhängigkeiten beim Umzug grösstenteils mitbringt.

**Diese lokalen Importe nicht ans Modulende hochziehen**, auch wenn es sauberer aussähe. Sie stehen dort mit Grund. Wer sie hochzieht, holt sich die Zyklen zurück, die jemand mühsam umgangen hat — und merkt es erst zur Laufzeit.

**Nur 8 von 43 Helfern werden in mehr als einem Block genutzt.** Sie gehören nach `_basis.py`:

| Helfer | genutzt in | steht heute in |
|---|---:|---|
| `_global_filter` | **32 Blöcken** — der Einstiegspunkt jeder View | Kopfbereich |
| `_num` | 19 Blöcken | Kopfbereich |
| `_vermietung_pipeline` | 3 | Block 32 |
| `_pendenz_ziel` | 2 | Block 29 |
| `_mwst_beleg`, `_mwst_bereits_verbucht`, `_mwst_periode` | je 2 | Block 27 |
| `_kaution_bilanziert` | 2 | Block 1 |

**Sechs der acht liegen heute mitten in einem Block, nicht im Kopfbereich.** Sie werden beim Umzug ihres Heimatblocks leicht mitgenommen — und dann fehlen sie den anderen. Das ist der wahrscheinlichste Weg, Etappe 1 zu brechen.

Zwei Sonderfälle, die keine geteilten Helfer sind, aber Aufmerksamkeit brauchen:

- **`_park_konto`** ist in Block 32 definiert und **ausschliesslich in Block 5** benutzt (Bankabgleich) — rund 10'000 Zeilen entfernt. Wandert Block 5 zuerst, bricht er, wenn der Helfer nicht mitkommt. Am einfachsten mit nach `_basis.py`.
- **`_parse_adresse`** steht im Kopfbereich und wird von genau einem Block gebraucht. Es kann dort bleiben; nichts zu tun.

`_global_filter` ist zugleich der Ansatzpunkt für Etappe 4 — es lohnt sich, ihn sauber zu isolieren.

---

## Vorgehen je Block

**Ein Block, ein PR, sofort gemergt.** Nicht 33 Blöcke auf einem Zweig sammeln. Der Feind ist die lang lebende Umbau-Verzweigung, nicht die parallele Arbeit; bei kleinen Schnitten existiert nie ein Zweig, mit dem etwas kollidieren könnte.

Reihenfolge: **klein anfangen.** Die ersten zwei bis drei Blöcke aus dem Mittelfeld (100 bis 300 Zeilen), damit das Verfahren sitzt, bevor die 1'834-Zeilen-Detailseiten drankommen.

Vor jedem Block:

```bash
git fetch origin main
git log --oneline HEAD..origin/main -- core/views/fw.py    # leer = sicher
```

Nach jedem Block:

```bash
export DEBUG=False SECURE_SSL_REDIRECT=False
python manage.py check
python manage.py shell -c "
from django.urls import get_resolver
print(len([k for k in get_resolver().reverse_dict if isinstance(k,str)]), 'benannte URLs')"
git diff --stat
```

**Die Zeilenbilanz ist die wichtigste Prüfung.** Bei einem reinen Umzug ist die Summe aus Entferntem und Hinzugefügtem gleich — bis auf die Import- und Re-Export-Zeilen, die entstehen müssen. Weicht sie darüber hinaus ab, wurde etwas geändert. Dann herausfinden was, bevor es weitergeht.

Erwartungswerte, die stimmen müssen: **293 benannte URLs**, **1'076 Testfälle**, Ruff sauber.

---

## Womit zu rechnen ist

**Vergessene Dekoratoren.** `@rolle_erforderlich` und die Rollenkonstanten müssen im Zielmodul importiert sein. Ein fehlender Import macht sich als `NameError` erst zur Laufzeit bemerkbar — also möglicherweise erst im Betrieb. Deshalb nach jedem Block die **volle** Testsuite, nicht nur die Tests des Blocks.

*Ruff hilft hier: `F821` (undefinierter Name) ist seit P0.6 scharf und bei 0. Ein vergessener Import fällt damit schon beim Linten auf, nicht erst im Test — das war der Zweck der Regelauswahl.*

**Die Testsuite seriell laufen lassen, nicht mit `--parallel`.** Der Prozesspool kann eine echte Fehlermeldung hinter `TypeError: cannot pickle 'traceback' object` verstecken. Bei einem Umzug ist genau die Meldung das Wertvolle.

**Blöcke, deren Grenze nicht sauber ist.** Manche Views passen thematisch in zwei Blöcke. Im Zweifel dort lassen, wo sie stehen — die Blockgrenze ist die Kante, nicht das eigene Urteil über die richtige Zuordnung.

**Auffallende Fehler.** Bei 14'983 Zeilen wird etwas auftauchen: eine tote View, ein doppelter Helfer, eine Query ohne Filter. **Nicht mitkorrigieren.** In die PR-Beschreibung unter „Bewusst nicht getan", eigener PR danach. Sonst weiss beim Review niemand, ob der Umzug oder die Korrektur etwas gebrochen hat.

*Ein solcher Posten liegt schon bereit: `fw_schaden_detail` markiert ein Ticket auch für die reine Leserolle als gelesen (Fund aus E1c). Ein-Zeilen-Fix — und trotzdem nicht in einem Umzugs-PR.*

Der Skill `swissimmo-review` gilt: Widerspricht der Bestand diesem Dokument, gilt der Bestand — die Zahlen hier sind am 14.08.2026 gemessen und veralten.

---

## Abnahme der Etappe

- Alle 33 Blöcke in eigenen Modulen, `fw.py` als Paket mit `__init__.py`
- 293 benannte URLs auflösbar
- Testsuite grün, Testzahl nicht gesunken
- Ruff sauber, `manage.py check` ohne Beanstandung
- Im Gesamtdiff keine inhaltliche Änderung

Danach ist `core/tests.py` (16'670 Zeilen, 221 Klassen) an der Reihe — nach Fachgebiet **und Laufzeit**, sonst blockieren die langsamen Tests später die CI. Zur Grössenordnung: Der volle Lauf dauert derzeit rund **8½ Minuten**.
