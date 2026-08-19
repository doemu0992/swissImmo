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

**Die `ds-`-Hilfsklassen gibt es nicht — die Komponentenschicht schon.** Der erste Entwurf nannte hier „24 `ds-`-Hilfsklassen in Verwendung". Davon existiert keine: kein `class="ds-…"` in irgendeinem Template, keine `.ds-*`-Regel im Stylesheet. Was danach aussah, sind die 23 **Tokennamen** selbst, 159-mal als `var(--ds-…)` in Stilangaben.

**Das Präfix heisst aber `fw-`, nicht `ds-`, und darunter steht mehr, als die Zahl vermuten liess:**

| | |
|---|---|
| in `base.html` definierte `.fw-*`-Klassen | **56** |
| davon in Templates tatsächlich benutzt | **50** |
| häufigste | `fw-phead` 86× · `fw-kv` 71× · `fw-chip` 51× · `fw-btn` 44× · `fw-num` 28× · `fw-card` 24× |

Es gibt also Seitenkopf, Beschriftungspaare, Chips, Schaltflächen, Karten, Tabellen (`fw-table`, `fw-tablewrap`), Kennzahlen (`fw-kpi`, `fw-kpis`), Diagramme (`fw-donut`, `fw-chart`) und Zustandsfarben (`fw-good`, `fw-warn`, `fw-crit`) als benannte Bausteine.

Für Phase 4b heisst das etwas anderes als „bei null anfangen": Die Aufgabe ist, eine **begonnene Umstellung zu Ende zu führen**. Das Vokabular steht und ist erprobt; daneben liegen 8'225 rohe Farbklassen und 468 Inline-`style`-Attribute in Templates, die noch nicht umgestellt sind. Der Entwurf sollte deshalb an `fw-*` anschliessen und es erweitern — nicht ein zweites Vokabular daneben stellen.

> Diese Stelle war in der ersten Fassung dieses Dokuments falsch: Dort stand, eine Komponentenschicht existiere „gar nicht". Der Fehler entstand, weil nur nach dem Präfix `ds-` gesucht wurde — dem Präfix, das der Entwurf nannte — und aus dem Nullergebnis auf die ganze Frage geschlossen wurde. Ein Suchergebnis beantwortet nur die gestellte Frage.

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

## Es gibt bereits eine Übergangsschicht — sie steht nur nicht so da

Nachgetragen am 19.08.2026, nachdem ein Vorschlag für eine *zweite* Farbschicht geprüft und verworfen wurde.

**`fw/base.html` enthält 53 handgeschriebene Dunkelmodus-Regeln**, die genau die fest verdrahteten Tailwind-Klassen umbiegen: `.bg-slate-50/100/200`, `.bg-white`, `.border-slate-100/200/300`, `.divide-slate-*`, die Zustandsfarben und die häufigsten Hover-Varianten. Das *ist* die Überbrückung zwischen Utilities und Tokens. Wer in 4b eine Übergangsschicht plant, baut sie nicht neu — er **ersetzt diese**.

Eine zweite Schicht wäre ein zweiter Mechanismus für dieselbe Aufgabe, später in der Kaskade, der Teile der ersten still überschreibt. Der geprüfte Vorschlag hätte drei Dinge getan:

- **Auf neun Tokens verwiesen, die es nicht gibt** (`--ds-brand-50…900`, `--ds-line-stark`). Ein `var()` ohne Rückfallwert auf eine undefinierte Variable macht die Deklaration ungültig, `!important` schlägt Tailwind trotzdem. In Chromium gemessen: `bg-indigo-100` wurde durchsichtig, `border-slate-300` nahm die Textfarbe an.
- **Von einer Palette ausgegangen, die nicht existiert.** `--ds-brand` ist `#4f46e5` — Tailwind-Indigo-600. `--ds-bg`, `--ds-line`, `--ds-ink` sind die Slate-Werte. Die Tokens bilden heute die bestehende Palette ab; das Petrol-Konzept ist entworfen, aber nie in `base.html` gelandet. Wo Tokens existieren, änderte eine Umbiegeschicht deshalb nichts.
- **Die Kontrastregel zurückgenommen**, siehe unten.

**Reihenfolge für 4b, die sich daraus ergibt:** zuerst die Palette in `base.html` setzen — vollständig, hell und dunkel, mit allen Stufen, die Regeln später brauchen. Danach die 53 Regeln durch die neue Schicht ersetzen. Nicht umgekehrt: Eine Schicht auf eine unfertige Palette macht Flächen durchsichtig statt farbig.

### Die Kontrastregel

`base.html` zwingt `.text-slate-400` und `.text-slate-300` auf `var(--ds-muted)`, weil die Rohwerte WCAG AA verfehlen (2.34:1 und 1.48:1). Diese Regel muss jede Umgestaltung überleben — `--ds-faint` reicht mit 4.34:1 **nicht**.

Beim Prüfen fiel dabei ein bestehender Fehler auf und wurde behoben: Zwei Dunkelmodus-Zeilen setzten dieselben Klassen auf feste Hexwerte und machten die Regel im Dunkeln wieder zunichte — `.text-slate-300` lag mit `#6b7193` bei 3.60:1 auf `--ds-surface`. Die Zeilen sind entfernt; das Token schaltet selbst um und liefert 6.62:1.

`core/tests/test_farbschicht.py` bewacht beides: dass kein `var(--ds-…)` ohne Rückfallwert auf ein undefiniertes Token zeigt, und dass die Kontrastregel die letzte Aussage zu ihren Klassen bleibt.

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
