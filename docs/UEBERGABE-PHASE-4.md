# Übergabe an Phase 4 — Ausgangslage Design

**Stand:** 19.08.2026 · gemessen an `main`
**Zweck:** Damit die Design-Arbeit auf gemessenen Zahlen aufsetzt statt auf der Bestandsanalyse vom 14.08., die an mehreren Stellen überholt ist.

---

## Was sich seit `docs/ANALYSE.md` geändert hat

Die Analyse beschrieb **fünf Oberflächenwelten** mit drei JavaScript-Ansätzen. Das gilt nicht mehr:

- Die **Vue-SPA unter `/app/` ist entfernt** (Entscheid E1) — mit ihr sieben Tab-Templates, 1'399 Zeilen Inline-JavaScript und 80 von 82 API-Endpunkten.
- Der **Unfold-Admin ist seit E2 lesend** und auf Superuser beschränkt. Er ist Betriebswerkzeug, keine zweite Schreiboberfläche, und braucht weder Entitlements noch Übersetzung.

**Phase 4 muss also nicht vier Welten vereinheitlichen, sondern eine ausbauen.** Das ist der grösste Unterschied zur ursprünglichen Einschätzung.

---

## Der Bestand in Zahlen

| | |
|---|---|
| Templates gesamt | 173 |
| davon unter `core/templates/fw/` | **101** |
| erben `fw/base.html` | **91** |
| Design-Tokens (`--ds-*`) | **23**, eingebettet in `fw/base.html` |
| `ds-`-Hilfsklassen in Verwendung | **keine** — siehe unten |
| **Inline-`style`-Attribute** | **468** |
| `fw/base.html` | 905 Zeilen |

> Drei dieser Zahlen sind gegenüber dem ersten Entwurf berichtigt: 174 → 173 Templates
> (dieselbe Zahl, die `KONZEPT-UI.md` nennt), 511 → 468 Inline-`style`-Attribute, und die
> 24 `ds-`-Hilfsklassen gibt es nicht. Messwege am Ende des Dokuments.

Grösste Einzeltemplates: `vertrag_neu` 953, `objekt_detail` 846, `vertrag_detail` 612, `liegenschaft_detail` 603.

---

## Was schon steht — und mehr ist als erwartet

`fw/base.html` enthält bereits einen brauchbaren Token-Satz mit **23 Variablen**, dreifach ausgeprägt: Grundwerte im `:root`, Dunkelvariante über `prefers-color-scheme`, und ein manueller Umschalter über `[data-theme]`. Ein Skript im `<head>` setzt das Thema früh, damit es beim Laden nicht flackert.

Die Tokens decken ab:

- **Flächen:** `--ds-bg`, `--ds-surface`, `--ds-surface-2`
- **Text:** `--ds-ink`, `--ds-muted`, `--ds-faint`
- **Linien:** `--ds-line`
- **Marke:** `--ds-brand`, `--ds-brand-600`, `--ds-brand-soft`
- **Status** je mit weicher Variante: `--ds-good`, `--ds-warn`, `--ds-crit`, `--ds-info`
- **Form:** `--ds-shadow-sm`, `--ds-shadow`, `--ds-radius`, `--ds-radius-sm`, `--ds-pill`

Das ist eine tragfähige Grundlage. Der Entwurf sollte sie erweitern, nicht ersetzen — 91 Templates hängen daran.

Die Beschreibung stimmt bis ins Detail: Der Umschaltblock ist als `@media (prefers-color-scheme:dark){:root:not([data-theme="light"])}` geschrieben, die manuelle Wahl gewinnt also in beide Richtungen, und das Skript gegen das Flackern steht in Zeile 7, noch vor jedem Stylesheet.

**Aber: eine Komponentenschicht gibt es nicht.** Der erste Entwurf nannte hier „24 `ds-`-Hilfsklassen in Verwendung". Nachgemessen sind es null. Es gibt kein einziges `class="ds-…"` in irgendeinem Template und keine einzige `.ds-*`-Regel im Stylesheet. Was aussieht wie 23 Hilfsklassen, sind die 23 **Tokennamen** selbst — sie erscheinen 159-mal als `var(--ds-…)` in Stilangaben.

Das ist keine Erbsenzählerei, es verschiebt die Aufgabe. Vorhanden ist eine **Farb- und Formschicht**; die Komponenten der Projektanweisung — Buttons, Formulare, Tabellen, Modals, Statusanzeigen, leere Zustände — existieren als wiederverwendbare Bausteine **gar nicht**. Sie sind heute in jedem Template neu aus Tailwind-Klassen zusammengesetzt. Die 468 Inline-`style`-Attribute sind genau das Symptom davon.

Für den Entwurf heisst das: Er beginnt bei den Komponenten nicht auf halbem Weg, sondern bei null — und muss dafür nichts abreissen, weil nichts da ist, das im Weg stünde.

---

## Vier Punkte, die den Entwurf beeinflussen

### 1. Die Tokens müssen aus `base.html` heraus

Solange sie im Basistemplate stehen, ist **mandantenspezifisches Branding nicht möglich**. Die Projektanweisung sieht Logo und Akzentfarbe je Verwaltung als Funktion höherer Abo-Stufen vor.

`crm.Organisation` hat heute genau ein Branding-Feld: `logo`. Keine Akzentfarbe.

Sauberster Weg: Tokens in eine eigene Stildatei, Überschreibung je Organisation als `:root`-Block. Dann ist Branding **eine Token-Überschreibung**, keine zweite Vorlage — und verzahnt sich mit dem Entitlement-System aus Phase 3, statt daneben zu stehen.

### 2. Der CDN-Punkt ist nicht nur technisch

Nachgemessen, welcher Fremdserver wo hängt:

| Host | Templates | davon in einem Basistemplate |
|---|---:|---|
| `fonts.googleapis.com` | 17 | `fw/base.html` **und** `modern_base.html` |
| `cdn.tailwindcss.com` | 15 | `fw/base.html` **und** `modern_base.html` |
| `cdnjs.cloudflare.com` (Font Awesome) | 10 | `fw/base.html` **und** `modern_base.html` |
| `cdn.jsdelivr.net` | 5 | nur `modern_base.html` (Alpine, Bootstrap Icons, signature_pad) |
| `unpkg.com` | 2 | in keinem Basistemplate |

Entscheidend ist die rechte Spalte: Die ersten drei stehen in `fw/base.html` selbst. Damit gehen sie bei **jedem** Aufruf der gesamten `/neu/`-Oberfläche hinaus, nicht nur auf einzelnen Seiten — bei allen 91 erbenden Templates. Auf einem System mit Mieterdaten, Betreibungsauszügen und Lohnausweisen verlässt damit bei jedem Klick mindestens die IP-Adresse der Nutzerin die Schweiz, ein eigenständiges Datenschutzthema, unabhängig davon, dass Fairwalter Schweizer Hosting bewirbt.

`modern_base.html` — die öffentliche Seite aus Punkt 4 — lädt zusätzlich Alpine.js und `signature_pad` von jsdelivr. Ausgerechnet dort, wo Interessenten und Mieter unterschreiben, hängt die Unterschriftenkomponente an einem Fremdserver.

Dazu läuft **Tailwind über die Play-CDN**, die ausdrücklich nicht für Produktion vorgesehen ist — und zwar ebenfalls in `fw/base.html`, also überall.

Ein Build-Schritt löst beides. `package.json` existiert bereits, enthält aber nur Playwright.

### 3. Vier Sprachen kommen noch

Phase 5 bringt Deutsch, Französisch, Italienisch, Englisch. Französische Beschriftungen sind oft ein Drittel länger als deutsche.

Komponenten sollten das aushalten, ohne umzubrechen — feste Breiten für Knöpfe und Tabellenköpfe rächen sich später. Im Entwurf kostet es nichts, in 101 Templates nachträglich viel.

### 4. Vier öffentliche Templates hängen noch nach

`modern_base.html`, `public_ticket_form.html`, `bewerbung.html`, `public_bewerbung_form.html` nutzen Alpine.js beziehungsweise Vue und erben **nicht** von `fw/base.html`.

Sie sind das Erste, was ein Interessent oder Mieter sieht — Schadenmeldung, Ticketformular, Bewerbung. Wenn sie nicht mitgedacht werden, bleiben sie als zweite Welt zurück, und zwar ausgerechnet an der Aussenseite.

---

## Was der Entwurf liefern sollte

Aus der Projektanweisung, Phase 4: Farb-Token, Typografie, Abstände, und Komponenten für **Buttons, Formulare, Tabellen, Modals, Statusanzeigen, leere Zustände**.

Der letzte Punkt verdient Aufmerksamkeit: **Leere Zustände** gibt es heute praktisch nicht. Eine Verwaltung, die neu anfängt, sieht leere Tabellen ohne Hinweis, was zu tun ist — und das ist der erste Eindruck beim Onboarding, also genau dort, wo ein Produkt gewinnt oder verliert.

Ebenfalls nicht vorhanden und im Entwurf zu bedenken: **Meldungen bei Fehlern**. Der Verbindungstest für Postfächer hat gerade gezeigt, wie viel eine handlungsleitende Meldung wert ist gegenüber einem blossen „fehlgeschlagen".

---

## Reihenfolge

Phase 4 hängt an keiner offenen Etappe. Sie kann parallel entworfen werden, während Phase 3 läuft.

Für die **Umsetzung** gilt aber: Die Token-Auslagerung (Punkt 1) sollte vor oder mit dem Entitlement-System kommen, sonst wird Branding zweimal gebaut.

Und ein Hinweis aus Phase 2, der hier genauso zählt: **Ein Block pro PR, sofort gemergt.** 101 Templates auf einem langlebigen Zweig umzustellen ist derselbe Fehler wie ein Big-Bang bei `fw.py` — und die Erfahrung dort war eindeutig.

---

## Messwege

Damit die nächste Bestandsaufnahme nicht wieder schätzt — und damit sichtbar bleibt, wie eine Zahl zustande kam:

```bash
# Templates gesamt (173) und unter fw/ (101)
find . -name '*.html' -path '*/templates/*' -not -path './.git/*' | wc -l
find core/templates/fw -name '*.html' | wc -l

# erben fw/base.html (91)
grep -rl "extends ['\"]fw/base.html['\"]" --include='*.html' . | grep -v node_modules | wc -l

# Design-Tokens: 23 verschiedene Namen, definiert in fw/base.html
grep -o -- '--ds-[a-z0-9-]*\s*:' core/templates/fw/base.html | sed 's/\s*:$//' | sort -u | wc -l

# ds-Hilfsklassen: 0 — beide Abfragen bleiben leer
find . -name '*.html' -path '*/templates/*' -print0 | xargs -0 \
  grep -ohE 'class="[^"]*"' | grep -oE '\bds-[a-z0-9-]+' | sort -u
grep -rnoE '^\s*\.ds-[a-z0-9-]+' --include='*.html' --include='*.css' core/

# Inline-style-Attribute (468)
find . -name '*.html' -path '*/templates/*' -not -path './.git/*' -print0 \
  | xargs -0 grep -o 'style="' | wc -l

# Fremdserver je Host, und ob der Host im Basistemplate steht
for h in fonts.googleapis.com cdn.tailwindcss.com cdnjs.cloudflare.com \
         cdn.jsdelivr.net unpkg.com; do
  echo "$h: $(find . -name '*.html' -path '*/templates/*' -print0 \
    | xargs -0 grep -l "$h" | wc -l) Templates"
done
grep -nE "unpkg|jsdelivr|cdnjs|fonts\.googleapis|tailwindcss" core/templates/fw/base.html
```

Zwei Fallstricke, in die die erste Zählung gelaufen ist und die nächste wieder laufen kann:

**Tokens am Zeilenanfang zählen ergibt 13, nicht 23.** Zehn Definitionen stehen nicht am Zeilenanfang. Gezählt werden müssen die verschiedenen **Namen**, nicht die Zeilen — der erste Entwurf hat das bereits selbst korrigiert.

**`\bds-` trifft auch `--ds-`.** Die Wortgrenze sitzt hinter dem Bindestrich, deshalb sieht ein `grep` nach `ds-…` die Tokennamen für Hilfsklassen an. Genau daraus entstanden die „24 Hilfsklassen", die es nicht gibt. Wer Klassen sucht, muss innerhalb von `class="…"` suchen.
