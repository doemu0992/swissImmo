# Etappe 3 — Custom User Model

**Stand:** 15.08.2026 · gemessen an `main` nach Abschluss von Etappe 2
**Grundlage:** `docs/PHASE-2-PLAN.md` (Etappe 3), `docs/ANALYSE.md` (TS-1)
**Basis:** `main`
**Agent:** `chirurg`

---

## Warum das jetzt kommt und nicht später

Django erlaubt den Wechsel des Benutzermodells nach Produktivgang praktisch nicht mehr. Am `auth.User` hängen bereits beide Portale, das Rollenmodell und eine Benutzerverwaltung — jeder weitere Monat macht den Schritt teurer, ohne ihn einfacher zu machen.

Es ist der erste Schritt der Kette. Ohne ihn kann `Organisation` nicht sauber am Benutzer hängen, und ohne das gibt es keine Mandantentrennung.

---

## Ein Befund vorweg: zwei Konventionen nebeneinander

Im Bestand stehen **beide** Schreibweisen:

| Schreibweise | Fundstellen in `models.py` |
|---|---|
| `'auth.User'` hart verdrahtet | **10** |
| `settings.AUTH_USER_MODEL` | **2** (beide in `core/models.py`) |

**Das ist die Stelle, an der dieser Schritt schiefgehen kann.** Wird `AUTH_USER_MODEL` in den Settings umgestellt, zeigen die zehn harten Verweise weiterhin auf `auth.User`. Das Ergebnis wäre kein Fehler beim Start, sondern **zwei Benutzertabellen im Betrieb**: Der neue Benutzer wird angelegt, die Fremdschlüssel auf `auth.User` bleiben leer oder verweisen ins Leere.

Deshalb ist Schritt 1 unten die Vereinheitlichung — **bevor** irgendetwas an den Settings geändert wird.

Betroffen sind, mit Zeilennummern am 15.08.2026:

| Datei | Fundstellen |
|---|---|
| `crm/models.py` | `Eigentuemer.benutzer` (102), `Mieter.benutzer` (275), `Kommunikation.erstellt_von` (448) |
| `finance/models.py` | 130, 297, 319, 486, 781 (`erstellt_von`) und 844 (`importiert_von`) — **6 Stellen, nicht 5** |
| `tickets/models.py` | `hochgeladen_von` (72) |

---

## Was am Benutzer hängt

Alle Zahlen am 15.08.2026 gegen den Bestand geprüft.

| Bereich | Umfang |
|---|---|
| Portale | `Eigentuemer.benutzer` und `Mieter.benutzer`, je `OneToOneField` |
| Rollen | über `user.groups` — `hat_rolle()` und `ist_eigentuemer()` in `core/auth.py` |
| Benutzerverwaltung | `core/views/fw/benutzer.py`, 110 Zeilen, 2 Views |
| Direktzugriffe | 15 Stellen `User.objects.…` im Produktivcode |
| Importe | 8 Module mit `from django.contrib.auth.models import …` |
| Migrationen | **14** mit Bezug auf `auth.User` |
| **Testmodule** | **10** mit hartem `User`-Import — siehe unten |

**`core/auth.py` selbst importiert `User` nicht.** Es arbeitet ausschliesslich über `user.groups`. Das ist die gute Nachricht dieses Auftrags: Das Rollenmodell ist vom konkreten Benutzermodell entkoppelt und sollte den Wechsel unverändert überstehen. Zu prüfen bleibt es trotzdem.

### Die zehn Testmodule sind nicht nebensächlich

`core/tests/_helfer.py`, `core/tests/_isolation.py`, `test_nebenkosten`, `test_oberflaeche`, `test_berichte`, `test_pendenzen`, `test_sicherheit`, `tests_perf`, `tests_perf2`, `tests_verify_perf`.

Zwei davon sind kritisch:

- **`core/tests/_helfer.py`** enthält `_team_user()` — die Grundlage praktisch jeder Testklasse. Bricht sie, bricht alles gleichzeitig, und die eigentliche Ursache verschwindet hinter tausend Fehlern.
- **`core/tests/_isolation.py`** ist das Fixture aus Etappe 2. Die Abnahme unten verlangt, dass die drei grünen Selbstprüfungstests grün bleiben — genau dieses Modul importiert `User` hart und ist damit unmittelbar betroffen.

---

## Die vier Schritte

Alle vier gehören in **einen** PR. Das ist die Ausnahme von der Regel „ein Schritt pro PR" aus dem Agentenauftrag: Jeder Zwischenzustand zwischen Schritt 1 und 4 ist ein kaputtes System, und ein halb ausgeführter Benutzerwechsel ist der teuerste Zustand, den dieses Projekt annehmen kann.

**1 — Vereinheitlichen.** Alle 10 harten `'auth.User'` auf `settings.AUTH_USER_MODEL` umstellen. Erzeugt Migrationen, ändert aber noch kein Verhalten — `AUTH_USER_MODEL` zeigt weiterhin auf `auth.User`.

**2 — Modell anlegen.** Neue App oder `core`: ein Modell, das von `AbstractUser` erbt. **Keine zusätzlichen Felder in diesem Schritt** — die Organisation kommt in Etappe 4, nicht hier. Wer beides zusammenlegt, kann bei einem Fehler nicht mehr sagen, welcher Teil ihn verursacht hat.

**3 — Umstellen.** `AUTH_USER_MODEL` in den Settings, Migration, Datenübernahme der bestehenden Benutzer. Der heikle Teil: Django kann `auth.User` nicht in ein anderes Modell migrieren, ohne dass die Tabellen und Fremdschlüssel bewusst behandelt werden. **Vorher beschreiben, wie der Bestand übernommen wird**, und den Weg vorlegen, bevor er ausgeführt wird.

**4 — Nachziehen.** Alle 8 Importe, die 15 `User.objects`-Zugriffe, `core/auth.py`, die Benutzerverwaltung, die Portale — **und die zehn Testmodule**. `get_user_model()` statt direktem Import.

---

## Was vorher beschrieben und vorgelegt werden muss

Der `chirurg` beginnt nicht mit Code. Vor dem ersten Commit gehört Folgendes schriftlich vorgelegt:

- Welcher Weg für die Datenübernahme gewählt wird und warum
- Welcher Zwischenzustand entsteht, falls das Deployment mittendrin abbricht — und wie man dann herauskommt
- Ob die bestehenden Benutzer-IDs erhalten bleiben (sie müssen, sonst brechen `Eigentuemer.benutzer`, `Mieter.benutzer` und alle `erstellt_von`-Verweise)
- Was am Ende des Schritts noch **nicht** funktioniert

Wird der Schritt grösser als geplant: aufhören und melden, nicht durchziehen.

---

## Abnahme

- Keine harte `'auth.User'`-Referenz mehr im Produktivcode
- `AUTH_USER_MODEL` zeigt auf das neue Modell
- **Vorwärts- und Rückwärtsmigration ausgeführt**, beide protokolliert
- Bestehende Benutzer inklusive IDs, Gruppen und Passwort-Hashes übernommen
- Beide Portale erreichbar: ein Eigentümer und ein Mieter melden sich an und sehen ihre Daten
- Rollenprüfung greift: `hat_rolle()` und `rolle_erforderlich` funktionieren unverändert
- Testsuite grün, Testzahl nicht gesunken (Stand vorher: **1'093**, davon 11 `expectedFailure` und 4 übersprungen)
- Die 11 Isolationstests aus Etappe 2 sind **weiterhin** `expectedFailure` — dieser Schritt stellt noch keine Isolation her. Schlägt einer in „unexpected success" um, ist das kein Fortschritt, sondern ein Zeichen, dass der Test nicht mehr prüft, was er soll.
- `manage.py check`, `makemigrations --check`, Ruff sauber
- `mandanten-auditor` über den Diff, ohne Leckfund

Die drei grünen Tests aus `IsolationstestsSelbstpruefungTests` müssen grün bleiben. Werden sie rot, ist das Fixture gebrochen — dann prüfen die Isolationstests nichts mehr, und das fällt sonst erst in Etappe 4 auf.

**Ruffs `F821` ist auch hier das erste Netz.** Ein vergessener Import nach dem Umstellen fällt beim Linten auf, nicht erst im Testlauf — das hat sich in Etappe 1 an dreizehn Stellen bewährt. Es fängt aber **keine** falschen Re-Exporte und keine Modellverweise in Migrationen; dafür braucht es die Testsuite und `makemigrations --check`.

---

## Was nicht Teil dieser Etappe ist

- **`Organisation`** — Etappe 4. Auch nicht „schon mal als Feld vorbereiten".
- **Rollen je Organisation** — Etappe 4, Schritt 4.
- **Zusätzliche Benutzerfelder** jeder Art. Ein Custom User Model kann später ohne Weiteres Felder bekommen; der Wechsel selbst kann nur einmal sauber gemacht werden.
- **Aufräumen „bei der Gelegenheit"** in den berührten Dateien. In die PR-Beschreibung, eigener PR.
