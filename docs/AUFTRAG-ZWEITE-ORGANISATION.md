# Die zweite Organisation

**Stand:** 18.08.2026 · nach Abschluss von Phase 2
**Basis:** `main`
**Agenten:** `chirurg` für die Anlage, `mandanten-auditor` für den Betrieb

---

## Worum es geht

Alles bisher war Vorbereitung. 63 Modelle tragen den Organisationsbezug, 25 Isolationstests sind grün, der `TenantManager` filtert, sieben Rückfälle sind getilgt.

**Bewiesen ist damit, dass die Trennung im Test hält.** Ob sie im Betrieb hält, weiss niemand — es gab bisher nur eine Organisation, und wo es nichts zu trennen gibt, kann auch nichts falsch getrennt werden.

Das ist die Etappe, die aus einer geprüften Annahme eine belegte Eigenschaft macht.

---

## Ein Befund vorweg: es gibt keinen Weg, eine Organisation anzulegen

Gesucht über den ganzen Bestand — kein View, kein Management-Command, keine Stelle, die eine `Mitgliedschaft` erzeugt. Der einzige Treffer ist ein Notbehelf in `core/utils/market_data.py`:

```python
ziele = [Organisation.objects.create(firma="Meine Verwaltung")]
```

Das ist folgerichtig: Bisher gab es genau eine, angelegt vor Jahren. Für die zweite fehlt der Weg vollständig — und mit ihm alles, was eine neue Verwaltung an Grunddaten braucht.

**Nach heutigem Stand mindestens:**

| Was | Warum |
|---|---|
| `Buchungskonto` je Organisation | `organisation` ist `null=False`. Ohne Kontenplan keine Buchung, keine Rechnung, keine Sollstellung. Es gibt `ensure_kontenplan(organisation)` — läuft es je Organisation? |
| `Lebensdauer` je Organisation | trägt seit Etappe 5 einen eigenen Bezug; `seed_lebensdauer(organisation)` existiert |
| Referenzzins und LIK | stehen an der Organisation und werden vom Marktdatenlauf gefüllt — für die neue initial gesetzt? |
| Rollen und erste Mitgliedschaft | sonst kann sich niemand anmelden |
| Vorlagen | Systemvorlagen tragen `organisation = NULL` und gelten für alle. Die neue Verwaltung sieht sie — greift der `Q(organisation=org) \| Q(organisation__isnull=True)`-Weg überall? |

Das ist der eigentliche Arbeitsanteil dieser Etappe. Ein `Organisation.objects.create()` ist eine Zeile; eine **arbeitsfähige** Verwaltung ist es nicht.

### Richtigstellung zum Befund (Vorrang des Bestands, 18.08.2026)

Nachgesehen statt übernommen. Der Kern des Befunds stimmt und ist sogar schärfer als beschrieben; zwei Einzelheiten drumherum stimmen nicht.

**Schärfer:** Es gibt nicht nur keinen Anlageweg für die Organisation — es gibt im ganzen Bestand **keine einzige Stelle**, die eine `Mitgliedschaft` erzeugt. Gesucht über alle Dateien, ausserhalb von Tests und Migrationen: kein Treffer. Selbst wer die Organisation von Hand in der Shell anlegte, käme also nicht hinein. Die einzigen `Organisation.objects.create()` ausserhalb der Tests sind der genannte Notbehelf in `core/utils/market_data.py:172` und drei Performance-Testdateien.

**Falsch: `import_standard_kontenplan` gibt es nicht.** Der Befehl heisst

```
finance/booking.py:82   def ensure_kontenplan(organisation=None):
```

Der Unterschied ist nicht nur der Name: `ensure_` sagt, dass die Funktion idempotent gedacht ist, und der Parameter nimmt die Organisation bereits entgegen. Ob sie für eine **frische** Verwaltung wirklich den vollen Plan anlegt oder nur fehlende Konten nachträgt, gehört im Rahmen dieser Etappe geprüft — vermutet wird hier nichts. Die Tabelle oben ist entsprechend korrigiert.

**Erledigt: die beiden Vorbedingungen unten.** Der Abschnitt «Was vorher erledigt sein muss» ist am selben Tag abgearbeitet worden, nach dem Verfassen dieses Auftrags. Einzelheiten dort.

---

## Vorgehen

### Schritt 1 — Nicht auf der Produktion

Die zweite Organisation entsteht zuerst in einer **Kopie des Produktivbestands**. Der Weg dafür ist seit dem Wiederherstellungs-Probelauf beschrieben und einmal gelaufen — `SICHERUNG.md`, Abschnitt „Durchgespielt am 18.08.2026".

> Bestätigt am 18.08.2026: Der Server trägt die Kopie. Sie kostet eine zweite
> PostgreSQL-Datenbank und rund 190 MB Medien, und sie bleibt für die Dauer der
> Etappe stehen — anders als die Probedatenbank, die nach einer Stunde wieder weg war.

Grund: Wenn die Isolation an einer Stelle nicht hält, sind in der Kopie zwei Testbestände betroffen. In der Produktion wären es die echten Daten der ersten Verwaltung — und die gehören einem Kunden.

### Schritt 2 — Der Anlageweg

Als Management-Command, nicht als View. Eine neue Verwaltung anzulegen ist ein seltener, folgenreicher Vorgang mit Grunddaten im Schlepptau; ein Formular verleitet dazu, ihn nebenbei zu machen.

Der Befehl legt an: Organisation, erste Mitgliedschaft mit Rolle Inhaber, Kontenplan, Lebensdauer, Startwerte für Referenzzins und LIK. Er ist **wiederholbar** und meldet, was schon existiert.

### Schritt 3 — Der Betriebstest

Mit zwei vollständigen Verwaltungen in der Kopie durchspielen, was eine Verwaltung täglich tut:

- Liegenschaft, Einheit, Mieter, Mietvertrag anlegen
- Sollstellung laufen lassen — **für beide**, im selben Lauf
- Debitorenrechnung, Zahlungseingang, Mahnlauf
- Nebenkostenabrechnung
- Ein Dokument hochladen, ein PDF erzeugen, eine E-Mail versenden
- Eigentümer- und Mieterportal je Verwaltung
- Bankabgleich mit einer camt.053-Datei

**Nach jedem Schritt: Sieht Verwaltung B etwas von A?** Und die weniger offensichtliche Frage: Trägt jedes erzeugte Dokument den richtigen Absender, liegt jede Datei im richtigen Ordner, nennt jeder Logeintrag die richtige Organisation?

### Schritt 4 — Die Hintergrundläufe

Der gefährlichste Teil, weil er unbeaufsichtigt läuft. `taeglicher_lauf`, `monatslauf`, `mahnlauf`, `jahresabschluss_lauf`, `fristen_digest`, `send_eigentuemer_reports`, `fetch_replies`, `fetch_rechnungen`.

Je Lauf: Verarbeitet er beide Organisationen? Bleibt der Bestand der jeweils anderen unberührt? Und tragen die Ausgaben — Mahnung, Bericht, E-Mail — den Absender der richtigen Verwaltung?

`fetch_replies` und `fetch_rechnungen` verdienen besondere Aufmerksamkeit: **ein IMAP-Postfach für alles.** Wie wird eine eingehende Rechnung der richtigen Verwaltung zugeordnet? Das war schon in `ANALYSE.md` als offen vermerkt.

### Entschieden am 18.08.2026: ein Postfach JE VERWALTUNG

Nicht ein gemeinsames Postfach mit Zuordnungsregeln, sondern **je Organisation ein eigenes**, in der Oberfläche konfigurierbar. Der Betreiber hat das so festgelegt.

Das ist die robustere Antwort, und zwar aus einem Grund, der über Bequemlichkeit hinausgeht: Eine Zuordnung *nach dem Empfang* — an der Empfängeradresse, an einem Präfix im Betreff — rät. Rät sie falsch, landet die Rechnung einer fremden Verwaltung im Bestand der eigenen, und niemand merkt es, weil eine Kreditorenrechnung nun einmal von aussen kommt. Getrennte Postfächer machen die Zuordnung zur **Voraussetzung** statt zum Ergebnis: Was in Postfach B liegt, gehört B, ohne Interpretation.

Heute stehen die Zugangsdaten in Umgebungsvariablen — `RECHNUNGS_IMAP_USER`, `RECHNUNGS_IMAP_PASSWORD`, `RECHNUNGS_IMAP_HOST` (`fetch_rechnungen`), und in `fetch_replies.py:104` steht der Server sogar fest im Code. Für die Umstellung heisst das:

| | |
|---|---|
| Felder an der `Organisation` | Host, Port, Benutzer, Passwort, Ordner — plus ein Schalter «Eingang aktiv» |
| Beide Befehle | laufen über `je_organisation` und nehmen die Zugangsdaten der jeweiligen Verwaltung |
| Rückfall | Ist an einer Organisation nichts konfiguriert, wird sie übersprungen — **nicht** stillschweigend auf die Umgebungsvariablen zurückgefallen. Sonst holt Verwaltung B aus dem Postfach von A. |
| Der feste Server in `fetch_replies` | muss weg, sonst gilt er für alle |

#### Das Passwort: verschlüsselt, Schlüssel ausserhalb der Datenbank

Mit der Konfiguration in der Oberfläche wandert das Postfachpasswort aus einer Umgebungsvariablen in die **Datenbank** — und damit in jede Sicherung und jeden `pg_dump`. Entschieden am 18.08.2026: **anwendungsseitig verschlüsselt**, mit einem Schlüssel, der nicht in der Datenbank steht.

Der Weg kostet nichts an Abhängigkeiten: `cryptography==46.0.3` steht bereits in `requirements.txt:32`. Fernet genügt.

**Was das leistet — und was nicht.** Es schützt gegen einen abhandengekommenen **Datenbankauszug**: eine kopierte Sicherung, ein `pg_dump` auf einem falschen Datenträger, ein Zugang zur Datenbank ohne Zugang zum Dateisystem. Es schützt **nicht** gegen jemanden, der auf dem Server ist — dort liegt der Schlüssel in der `.env` daneben. Das ist kein Einwand, aber es gehört hier festgehalten, damit später niemand mehr Sicherheit annimmt, als da ist.

**Der Preis:** Schlüssel weg heisst Passwörter weg. Nicht dramatisch — jede Verwaltung tippt ihres neu ein —, aber der Schlüssel gehört an dieselbe Stelle und in dieselbe Sorgfalt wie das Datenbankpasswort, und der Wiederanlauf gehört dokumentiert.

#### Die Grenze, die nicht bei uns liegt: nicht jeder Anbieter kann das

«Nach Wahl, was die Verwaltung ohnehin hat» ist der richtige Gedanke, stösst aber an eine Grenze beim Anbieter:

| Anbieter | IMAP mit Benutzer + Passwort |
|---|---|
| Hoststar, cyon, Infomaniak, eigener Server | funktioniert |
| Gmail / Google Workspace | nur mit **App-Passwort**, das setzt 2FA im Google-Konto voraus |
| **Microsoft 365 / Exchange Online** | **funktioniert nicht** — Microsoft hat Basic Auth für IMAP abgeschaltet, es geht nur über OAuth2 |

Ein erheblicher Teil kleiner Schweizer Verwaltungen sitzt auf Microsoft 365. Für die ist das Feature mit Benutzer und Passwort nicht benutzbar — und sie merken es erst beim Einrichten.

**Trotzdem so bauen.** Benutzer und Passwort deckt die klassischen Hoster ab, und OAuth2 für Microsoft ist ein eigenes Vorhaben (App-Registrierung im Azure-Portal, Token-Erneuerung, ein weiterer Geheimnis-Speicher). Aber es gehört **ins Formular**, nicht ins Handbuch: ein Satz neben dem Feld, dass Microsoft 365 derzeit nicht unterstützt wird. Sonst suchen Leute den Fehler bei sich.

#### Drei Randbedingungen, die beim Bauen nicht neu verhandelt werden

1. **Ein «Verbindung testen»-Knopf, und erst danach speichern.** Ohne ihn merkt eine Verwaltung erst nachts um drei im Scheduled Task, dass ihre Zugangsdaten nicht stimmen — und der Task schweigt, weil er niemanden hat, dem er es sagen könnte. Der Knopf verbindet sich, meldet den gefundenen Ordner und die Zahl ungelesener Nachrichten.
2. **Das Passwortfeld ist schreibend, nie lesend.** Es wird nie wieder in den Browser gerendert, auch nicht maskiert mit den echten Zeichen dahinter. Angezeigt wird «gesetzt am …» plus die Möglichkeit, es zu ersetzen. Sonst steht das Postfachpasswort im HTML jeder Einstellungsseite.
3. **Kein stiller Rückfall** (siehe Tabelle oben) — der wichtigste der drei.

**Nicht Teil dieser Etappe.** Für den Betriebstest genügt es, die Läufe mit zwei Organisationen zu fahren und festzuhalten, was heute passiert; die Umstellung auf Postfächer je Verwaltung ist ein eigener Auftrag.

---

## Was vorher erledigt sein muss

> **Beide Punkte sind am 18.08.2026 erledigt worden** — nach dem Verfassen dieses Auftrags, im selben Arbeitstag. Sie stehen hier weiter, weil ihr Ergebnis für diese Etappe zählt.

- ~~**`medien_umziehen` sauber zu Ende.**~~ **Erledigt.** Der Lauf brach tatsächlich nach zwei von zehn Dateien ab — die Ursache war nicht der Bestand, sondern der Befehl: Sein `save()` löste Modell-Hooks aus, die über `objects` lesen und ohne Mandantenkontext werfen. Dazu kam eine zweite, gefährlichere Falle, die im Traceback gar nicht auftauchte: Wo der Hook nicht warf, legte er die Datei über `upload_to` unter einem **neuen Namen** ab — der Befehl meldete einen Umzug, den er nicht ausgeführt hatte. Behoben (`.update()` statt `save()`), sechs Tests, beide Gegenproben protokolliert. Der Nachlauf auf der Produktion: 9 Verweise, 0 Fehler, alle 10 Dateien liegen unter `organisation/4/`.

- ~~**`medien_pruefen` einmal auf der Produktion.**~~ **Erledigt.** Ergebnis: **10 Verweise, alle vorhanden**, und gegen den Sicherungsstand geprüft auch alle im Archiv. Die vier toten Verweise des Probelaufs stammten damit nachweislich aus den Entwicklungsdaten. Der Produktivbestand hat keinen.

---

## Abnahme

- Anlagebefehl vorhanden, wiederholbar, mit Test
- Zweite Organisation in der Kopie angelegt und **arbeitsfähig**: eine vollständige Sollstellung mit Debitorenrechnung und Mahnung durchgelaufen
- Betriebstest aus Schritt 3 dokumentiert — je Punkt, was geprüft wurde und was herauskam
- Alle acht Hintergrundläufe mit zwei Organisationen gefahren, Ergebnis dokumentiert
- `mandanten-auditor` über den Diff und über die Beobachtungen
- Testsuite grün: `manage.py test` ohne Labels, Zahl gegen Discovery abgeglichen
- **Ein Bericht im Repo** — `docs/ZWEITE-ORGANISATION.md` — mit dem, was nicht funktioniert hat

Der letzte Punkt ist der wichtigste. Nach dem Wiederherstellungs-Probelauf war der Abschnitt „Was nicht funktioniert hat" der eigentliche Ertrag: vier tote Dateiverweise und zwei Vergleiche, die nichts verglichen und Erfolg meldeten. Hier wird es nicht anders sein.

---

## Erst danach: die Produktion

Wenn der Betriebstest in der Kopie sauber ist, kann die zweite Verwaltung produktiv entstehen. Nicht vorher.

Und ein Punkt, der dann sofort relevant wird und heute noch offen ist: **Die Sicherung liegt auf demselben Konto wie die Produktion.** Sie trägt den Ausfall eines Datenträgers, nicht den Verlust des Kontos. Solange nur eigene Daten betroffen sind, ist das eine Risikoentscheidung. Mit fremden Kundendaten wird daraus eine Haftungsfrage — und eine Kopie ausser Haus ist ein externer Dienst mit Kosten, also eine Entscheidung für Dominik.

---

## Nebenbefund

Die Wartungsmodus-Meldung listet weiterhin **alle** fehlenden Migrationen — bei leerer Datenbank 205 Namen in einer Logzeile mit über 20'000 Zeichen. Das macht das Log unlesbar und war schon am 16.08. angemerkt. Fünf nennen, dann „… und 200 weitere" — die Handlungsanweisung ist ohnehin dieselbe.

> Nachgeprüft am 18.08.2026: Der Befund stimmt. `core/wartung.py:139` gibt
> `', '.join(FEHLENDE_MIGRATIONEN)` in einer einzigen `logger.error`-Zeile aus,
> ohne jede Begrenzung.
