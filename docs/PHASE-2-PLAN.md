# Phase 2 — Etappenplan

**Stand:** 14.08.2026
**Grundlage:** `docs/ANALYSE.md` (Bestandsanalyse), `.claude/TEAM.md` (Mannschaft)
**Ziel:** Mehrere Verwaltungen nutzen dieselbe Instanz, ohne je Daten anderer Mandanten zu sehen.

---

## Getroffene Entscheide

Diese vier blockierten die Planung. **Alle vier sind am 14.08.2026 ausgeführt.**

| # | Entscheid | Begründung und Ergebnis |
|---|---|---|
| ~~E1~~ | ~~**`/app/`-SPA wird entfernt**~~ — **erledigt** (E1a/E1b/E1c, siehe `docs/E1-SPA-ENTFERNEN.md`) | Kein `fw/`-Template rief die API auf. Gefallen sind **80 von 82 Endpunkten**, **15** SPA-Templates (nicht 12 wie geplant) samt 1'399 Zeilen JavaScript — und mit ihnen der ID-Offset-Hack aus TS-6, der ausschliesslich in SPA-Code stand. Geblieben sind zwei öffentliche Endpunkte: Bewerbungsformular und DocuSeal-Webhook. Halbiert den Aufwand jeder Folgephase. |
| ~~E2~~ | ~~**Unfold-Admin bleibt, wird aber entwaffnet**~~ — **erledigt** | Alle **27** registrierten Admins (25 eigene plus Djangos `auth.User`/`auth.Group`) und alle 18 Inlines sind lesend. **Die Annahme „14 von 25 ModelAdmins sind bereits schreibgeschützt" traf nicht zu:** Die vorhandenen Sperren sassen fast alle auf Inlines; schreibgeschützt war einzig `AktivitaetsLogAdmin`. Der Admin ist damit Betriebswerkzeug statt Zweitoberfläche und braucht weder Entitlements noch Übersetzung. **Pflicht bleibt:** Er umgeht den `TenantManager` über `_base_manager` und als Superuser — das ist in Etappe 4 ausdrücklich zu schliessen. |
| ~~E3~~ | ~~**`crm.Mandant` → `crm.Eigentuemer`**~~ — **erledigt** | Es waren **623 Vorkommen in 56 Dateien** (die Schätzung „135 Python- und 25 Template-Referenzen" zählte nur die Klassennamen, nicht die Feld- und Variablennamen). Ab Etappe 4 wäre daraus Code mit zwei kollidierenden Bedeutungen von „Mandant" geworden — kein Schönheitsfehler, sondern ein Datenleck-Risiko. |
| ~~E4~~ | ~~**`claude/fairwalter-rebuild` wird `main`**~~ — **erledigt** | `main` stand seit dem 21.05.2026 still. Die Umstellung lief als Fast-Forward: 0 Commits verloren, 513 dazugekommen. **Noch offen und nur über die GitHub-Oberfläche machbar:** `main` schützen. |

---

## Etappen

Jede Etappe endet an einem **Gate**: einer nachprüfbaren Bedingung. Ohne erfülltes Gate beginnt die nächste Etappe nicht.

### Etappe 0 — Aufräumen ✅ *(abgeschlossen am 14.08.2026)*

P0-Liste aus `docs/ANALYSE.md`, plus E1 bis E4. Agent: `aufraeumer`.

**Gate erfüllt:** Alle acht P0-Posten erledigt, Ruff läuft als eigener CI-Job, `main` ist aktuell (Schutz noch zu setzen), `Eigentuemer` durchgängig umbenannt.

### Etappe 1 — Zerlegen ✅ *(abgeschlossen am 15.08.2026)*

Auftrag und Abnahme: **`docs/ETAPPE-1-ZERLEGEN.md`**.

`core/views/fw.py` (14'988 Zeilen, 232 Views) ist ein Paket aus 35 Dateien; die grösste
hat 1'834 Zeilen. `core/tests.py` (16'733 Zeilen, 222 Klassen) ist ein Paket aus 22 Dateien,
aufgeteilt nach Fachgebiet **und Laufzeit** — dafür wurde die Laufzeit je Testklasse einmal
gemessen; kein Modul trägt mehr als 11 % der Testzeit. Agent: `zerleger`.

**Ein Block pro PR, sofort gemergt.** Nicht 34 Blöcke auf einem Zweig sammeln. Der eigentliche Feind bei einem Umzug ist nicht die parallele Arbeit, sondern die **lang lebende Umbau-Verzweigung**: Liegt `fw.py` zwei Wochen halb zerlegt auf einem Zweig, während am Original weitergearbeitet wird, kollidiert es. Wird jeder Block innerhalb einer Sitzung gemergt, existiert nie ein Zweig, mit dem etwas kollidieren könnte — und zwischen zwei Blöcken darf beliebig anderes passieren, auch an `fw.py`.

Die einzige harte Regel: **nicht zwei Sitzungen gleichzeitig an `fw.py`.** Das ist der Fall, in dem es tatsächlich kracht — eine zerlegt, die andere baut ein Feature ein, beide gehen von verschiedenen Ständen aus.

Billige Absicherung vor jedem Block-PR:

```bash
git fetch origin main
git log --oneline HEAD..origin/main -- core/views/fw.py   # leer = sicher
```

*(Eine frühere Fassung dieses Plans verlangte hier ein Freeze-Fenster von zwei bis drei Tagen. Das war aus einem Standardvorgehen für Teams übernommen, ohne zu prüfen, ob die Voraussetzung vorliegt — das Repository hat einen einzigen Autor. Kleine Schnitte lösen dasselbe Problem, ohne dass Etappe 1 auf irgendetwas warten muss.)*

**Gate erfüllt:** 293 URLs auflösbar, 1'079 Tests grün, Zeilenbilanz geht auf (+892 Zeilen, nur
Kopfkommentare und Importe), **jeder der 33 Blöcke und alle 222 Testklassen zeilenweise gegen
den Stand davor verglichen und identisch**.

### Etappe 2 — Isolationstests rot schreiben ✅ *(abgeschlossen am 15.08.2026)*

Katalog: **`docs/ISOLATIONSTESTS.md`** · Arbeitsauftrag: **`docs/ETAPPE-2-ISOLATIONSTESTS.md`**.

Rund 35 bis 40 Testmethoden, die über 240 Fälle abdecken — die Masse datengetrieben aus der URL- und Modell-Registry (152 URLs mit ID-Parameter, 63 Modelle), nicht abgetippt. Neue Views sind damit automatisch mitgeprüft. Dazu ein Wächter, der fehlschlägt, sobald ein Modell ohne Organisationsbezug hinzukommt.

*(Frühere Fassung dieses Plans nannte „rund 150 handgeschriebene Tests" — die Auszählung ergab eine andere Menge und eine bessere Bauform.)*

Sie sind zu diesem Zeitpunkt **alle rot**, weil `Organisation` noch nicht existiert. Genau das ist der Zweck: Ab hier ist die Definition of Done keine Behauptung mehr, sondern eine Zahl.

Läuft parallel, weil die Tests gegen URL-Namen geschrieben werden — die überleben den Split aus Etappe 1.

**Gate erfüllt:** `core/tests/test_isolation.py`, **14 Testmethoden über 263 Fälle** — 11 mit
`expectedFailure` plus 3 Selbstprüfungen ohne Marker. Die Fehlermeldungen wurden vor dem Setzen
des Markers einzeln gelesen; jeder Test scheitert an einem `assert`, nicht an einer Exception.

*(Der Gate nannte „35 bis 40 Testmethoden über rund 240 Fälle". Es wurden weniger Methoden bei
mehr Fällen: Die datengetriebenen Läufe über die URL- und Modell-Registry bündeln je einen ganzen
Prüfaspekt in einer Methode, statt ihn auf ein Dutzend aufzuteilen. Die Zahl, auf die es ankommt,
ist die der Fälle.)*

Zwei Tests waren zunächst **grün und bewiesen nichts** — genau die Falle, vor der der
Arbeitsauftrag warnt. Beide wurden verschärft und stehen im PR protokolliert. Ebenfalls gemessen:
`dossier_liegenschaft`, `dossier_mieter` und `dossier_vertrag` liefern heute **200** für fremde
Daten.

**Bauform E nachgetragen am 15.08.2026** (die Lücke fand der Auditor-Lauf über Etappe 3). Bauform A
sammelt über `_urls_mit_einem_parameter()` nur URLs mit genau **einem Pfadparameter** — daneben
stehen 108 parameterlose `fw_`-URLs, die ihre Filter aus dem **Querystring** lesen. Die lagen
vollständig ausserhalb.

Der Grund ist lehrreich: Bauform A ist datengetrieben und deckt deshalb „alle URLs" ab — aber nur
alle URLs ihrer eigenen Bauform. Eine Registry-Abfrage sieht nie, wonach sie nicht fragt. Wer aus
„152 von 152 geprüft" auf Vollständigkeit schliesst, hat die Frage mit der Antwort verwechselt.

`FremdeIdUeberQuerystringTests`, 6 Methoden, alle `expectedFailure`. Gemessen dabei: Von **107**
geprüften parameterlosen URLs übernehmen **61** die Liegenschaft von B, wenn ein Benutzer von A
sie mit deren `?lg=` aufruft. Auch der Liegenschaftswähler selbst liegt offen —
`_global_filter` legt `Liegenschaft.objects.all()` in den Kontext, also steht die Adresse jeder
fremden Liegenschaft im Auswahlmenü, ohne dass jemand eine ID raten müsste.

Ein Test war zunächst **rot aus dem falschen Grund**: Er prüfte alle Querystring-Parameter gegen
`fw_dashboard`, eine View, die `?mieter=` gar nicht liest, und scheiterte daran, dass
`assertNotContains` die blosse Ziffer „2" in jedem HTML findet (gemessen: 438-mal). Rot aus dem
falschen Grund ist derselbe Fehler wie grün aus dem falschen Grund, nur schwerer zu bemerken — der
Test sieht erfolgreich aus, solange man ihn nicht liest. Er ruft jetzt die View auf, die den
Parameter wirklich auswertet, und prüft den Kontextwert.

Suite damit **1'099** (1'088 + perf 6 + übrige Apps 5), 17 `expectedFailure`.

### Etappe 3 — Custom User Model ✅ *(abgeschlossen am 15.08.2026)*

Auftrag und Abnahme: **`docs/ETAPPE-3-USER-MODEL.md`** · Konzept und Messungen: **`docs/ETAPPE-3-KONZEPT.md`**.

Ein PR, eine Hand. Agent: `chirurg`. Mitzunehmen im selben PR: `Eigentuemer.benutzer`, `Mieter.benutzer`, das Rollenmodell über `user.groups`, die Benutzerverwaltung in `/neu/`.

Danach praktisch nicht mehr möglich — deshalb vor allem anderen Architekturschritt.

`AUTH_USER_MODEL` zeigt auf `benutzer.Benutzer`. Das Modell übernimmt die bestehende Tabelle
`auth_user` (`db_table`), statt die Daten zu kopieren — **keine Datenzeile wurde bewegt.** Der
Ausschlag gab nicht die Bequemlichkeit, sondern die 15 Fremdschlüsselspalten: Beim Kopieren hätte
Djangos Zustand behauptet, sie zeigten auf das neue Modell, während die Datenbank sie weiter auf
`auth_user` richtet. Django erzeugt dafür von sich aus keine Operation — die Abweichung wäre
unbemerkt geblieben und beim PostgreSQL-Umzug mitgewandert.

**Drei Funde, die der Auftrag nicht hatte:**

1. Auf einer **Bestandsdatenbank** bricht `migrate` mit `InconsistentMigrationHistory` ab,
   **bevor** eine Migration läuft — Djangos Konsistenzprüfung greift davor, keine Migration kann
   es lösen. Da `deploy.sh` unbeaufsichtigt läuft, ruft es jetzt `manage.py benutzer_uebernahme`
   davor auf: idempotent, tut genau einmal etwas, danach Leerlauf.
2. `core/migrations/0002_rollen_gruppen.py` holte das Benutzermodell hart über
   `apps.get_model('auth','User')` und wäre auf **jeder frischen Datenbank** abgestürzt. Das
   hätte die gesamte CI rot gemacht, ohne die Produktion zu berühren.
3. Die Vereinheitlichung der 10 harten `'auth.User'` erzeugt **keine einzige Migration** — die
   alte und die neue Schreibweise sind deckungsgleich.

**Gate erfüllt:** 1'093 Tests, unverändert gegenüber Etappe 2 (11 `expectedFailure`, 4
übersprungen). Die 11 Isolationstests sind weiterhin `expectedFailure`, die 3 Selbstprüfungen
grün — das Fixture trägt. Vorwärts- und Rückwärtsweg auf der echten Datenbank ausgeführt; der
Rückweg landet auf einem Zustand, der zeilenweise mit dem Ausgangspunkt übereinstimmt
(Tabellen, Spalten, alle 7 Benutzer samt Hashes, `django_migrations`). Ruff, `manage.py check`
und `makemigrations --check` sauber.

### Etappe 4 — Organisation und TenantManager

Auftrag, Entscheide und Ausführung: **`docs/ETAPPE-4-ORGANISATION.md`**.

Drei PRs nacheinander: `Organisation` (Verhältnis zu `crm.Verwaltung` geklärt), `TenantManager` plus Middleware, Rollen je Organisation.

**4.1 erledigt am 15.08.2026.** `crm.Verwaltung` heisst `crm.Organisation` (276 NAME-Token in 67 Dateien, `db_table` unverändert), `Liegenschaft.verwaltung` heisst `.organisation`, und `crm.Mitgliedschaft` verbindet Benutzer und Organisation mit einer Rolle. Der Bestand ist zugeordnet: 12 von 12 Liegenschaften, 4 Mitgliedschaften. **Noch kein Manager, noch keine Filterung** — die 17 roten Tests bleiben rot.

**4.2 teilweise erledigt am 15.08.2026.** Geliefert: `core/tenancy.py` (Kontext, `TenantManager`, `cache_key`), die Middleware, die Besitzprüfung in `_global_filter`. **Vier Tests grün**, jeder mit protokollierter Gegenprobe. **Nicht geliefert: die Anbindung des Managers an die Modelle** — gebaut, gemessen, zurückgenommen. Sie liess **922 von 1'072** Tests scheitern (638 auch noch, nachdem Schreiben ohne Kontext erlaubt wurde). Ursache: Testbenutzer haben keine Mitgliedschaft, also setzt die Middleware keinen Kontext, also wirft jede lesende View. Das ist die Form von Etappe 5 — je App ein PR, Manager und Organisationsbezug zusammen —, nicht die eines einzelnen Schrittes über die ganze Anwendung.

**4.3 erledigt am 15.08.2026.** Die Rollen hängen an der Mitgliedschaft statt an globalen Django-Gruppen. Zuordnung: Verwaltung→Verwalter, Sachbearbeitung→Sachbearbeiter, Lesend→Lesezugriff; `Inhaber` ist neu (Abo, Organisation löschen, Mitglieder einladen), die Migration setzt genau einen je Organisation. `hat_rolle()` ist **streng ohne Rückfall** auf die Gruppe. Der Schritt war klein, weil 246 von 250 `@rolle_erforderlich`-Dekoratoren über drei Konstanten-Tupel und **alle** durch `hat_rolle()` laufen — eine Funktion umzustellen kippt die ganze Anwendung. Belegt am Fixture: Benutzer B mit Gruppe `Verwaltung` hat in Organisation A jetzt `team=False`. Entschieden wurde: Mitgliedschaft statt Fremdschlüssel am Benutzer (ein Konto, ein Passwort, je Organisation eine Rolle), und Weg A für `Verwaltung` (Umbenennung statt zweitem Modell).

**Ohne gesetzte Organisation ist die richtige Antwort ein Fehler, nicht „alles zurückgeben".** Ein Manager, der im Zweifel alles liefert, ist schlimmer als keiner. Hier gehört auch die Admin-Umgehung aus E2 geschlossen.

#### Mitzunehmen aus Etappe 3

Fünf Punkte, alle aus dem `mandanten-auditor`-Lauf über den E3-Diff. Keiner davon ist heute ein
Leck — es gibt noch keine zweite Organisation. Alle fünf **werden** eines, sobald es sie gibt.

**1 — `Benutzer.username` ist global eindeutig.** Regel 5 des Skills `mandantentrennung`: Zwei
Verwaltungen können keinen Benutzer `info@` führen. Der Katalog aus Etappe 2 zählt diesen Fall
unter seinen sechs Constraints **nicht** mit; er gehört als siebter in
`UniqueConstraintsProOrganisationTests`. Etappe 3 hat ihn nicht behoben — `username` stammt aus
`AbstractUser`, eine Änderung bricht die Anmeldung.

**2 — Die Namensprüfung im Benutzerformular wird zum Existenz-Orakel.**
`core/views/fw/benutzer.py:50` meldet „Benutzername ist bereits vergeben" gegen **alle**
Organisationen. Verwaltung A erfährt damit durch Ausprobieren, welche E-Mail-Adressen Verwaltung B
führt — dieselbe Klasse wie „403 statt 404", nur über das Formular.

**3 — Der Aussperrschutz zählt über die Mandantengrenze.**
`core/views/fw/benutzer.py:105` zählt die aktiven Verwaltungs-Accounts global. A hält sich für
abgesichert, weil B noch Admins hat, und kann seinen letzten löschen. Kein Leck, aber
Datenverlust aus derselben Wurzel.

**4 — `email` identifiziert global, ist aber nicht eindeutig.**
`core/auth_backends.py:37` sammelt Konten über `username` **oder** `email` und meldet das an,
dessen Passwort passt — organisationsübergreifend. Heute unkritisch (Passwörter sind
Zufallsgeheimnisse, `create_user` hängt nie ein bestehendes fremdes Konto an einen Mieter), aber
die Annahme „E-Mail identifiziert eine Person global" steht nirgends geschrieben, und der
`[:10]`-Deckel wird bei einer geteilten Adresse zur stillen Grenze.

**5 — `eigentuemer_profil` und `mieter_profil` können am selben Konto koexistieren.**
`core/views/portal.py:29` prüft Eigentümer zuerst. Ein Konto, das in A Eigentümer und in B Mieter
ist, erreicht das Mieterportal nie. Routing-Frage, kein Leck — fällt aber erst auf, wenn Mandanten
Konten teilen können.

**Gate:** Erste Isolationstests werden grün. `mandanten-auditor` ohne Leckfund.

### Etappe 5 — Bezug je App nachrüsten

Sieben PRs, einer je App. Agent: `migrations-handwerker`, Rezepte im Skill `phase-2-migration`. Parallelisierbar.

Zwei Stellen zum Anhalten: Gruppe B mit Waisen (Bestandsdatensätze ohne Weg zur Liegenschaft) und Gruppe A generell — beides fachliche Entscheide, keine technischen.

**Gate:** Alle **65** Modelle mit Bezug, `null=False` — ausser `crm.Organisation` (ist der Mandant) und `benutzer.Benutzer` (hängt über `Mitgliedschaft` daran). Sechs globale Unique-Constraints umgebaut. `makemigrations --check` leer.

**Nachgemessen am 16.08.2026 (PR 1).** Die Analyse nannte 63 Modelle in den Gruppen 34/15/14; gezählt sind es **65** in **32/16/15**, plus zwei bereits fertige. Die Gruppengrenzen wurden über die Fremdschlüssel bestimmt, nicht über eine Textsuche — dieselbe Korrektur wie schon bei den Migrationszahlen (13 statt 16) und den `Mandant`-Vorkommen (623 statt 160).

**PR 1 (portfolio) erledigt am 16.08.2026.** Zwölf Modelle der Gruppe C, plus der Anker: `Liegenschaft.organisation` war `null=True, SET_NULL` und damit als Anker wertlos — eine Kette ist nur so pflichtig wie ihr schwächstes Glied. Jetzt `null=False, CASCADE`. Der Bezug wird **abgeleitet**, nicht eingegeben (`core/organisation_kette.py`): Als gewöhnliches Pflichtfeld müsste ihn jeder der hunderten Schreibpfade mitgeben — die Bauform, die 4.2 mit 922 roten Tests beendet hat. **1'101 Tests grün.** Offen in portfolio: Gruppe B (`Dokument`, `Geraet`, `Zaehler`, `ZaehlerStand` — braucht die Waisen-Zahlen der Produktion) und `Lebensdauer` (Gruppe A, fachlicher Entscheid).

### Etappe 6 — Alles, was den Prozess verlässt

Dateiablage auf `organisation/<id>/`, die 18 Management-Commands über Organisationen iterieren, PDF- und E-Mail-Absender aus der Organisation statt aus 132 Singleton-Lookups, `AktivitaetsLog` mit Organisationsspalte, Cache-Keys.

**Gate — und zugleich das Ende von Phase 2:** Alle Isolationstests grün. `mandanten-auditor` findet nichts.

---

## Parallelspur: 2FA

Unabhängig von der Kette, klein, verkaufsrelevant. Fairwalter führt Zwei-Faktor-Authentifizierung in **allen** Preisstufen; im Bestand fehlt sie (siehe `docs/MARKT.md`). Bei Mietverträgen, Lohnausweisen und Betreibungsauszügen ist das eine Ausschreibungsanforderung.

Sinnvoll nach Etappe 3, weil sie am User Model hängt.

---

## Was den Plan zum Scheitern bringen kann

**Lang lebende Umbau-Verzweigungen.** Nicht die parallele Arbeit ist das Risiko, sondern ein Zweig, der wochenlang halb umgebaut neben dem Original liegt. Etappen 1, 3 und 4 fassen Dateien an, die auch der laufende Betrieb braucht. Gegenmittel: kleine Schnitte, sofort mergen, und nie zwei Sitzungen gleichzeitig auf derselben Datei.

**Agenten, die überzeugende Filter schreiben, die nicht isolieren.** Deshalb Etappe 2 vor Etappe 3, und deshalb ist der `mandanten-auditor` an jedem Gate Pflicht — auch wenn es lästig ist.

**Etappe 5 als Fleissarbeit missverstehen.** 31 der 65 Modelle brauchen eine fachliche Entscheidung, keine Migration. Wer sie durchwinkt, löscht entweder Kundendaten oder legt sie offen.

**PostgreSQL-Wechsel zu spät.** SQLite trägt gleichzeitige Schreibzugriffe mehrerer Mandanten nicht. Der Wechsel (P1.4) gehört spätestens zwischen Etappe 4 und 5, besser früher. Der Treiber ist seit P0.5 vorhanden (`psycopg[binary]` in `requirements.txt`) — es fehlt nur noch der Umzug selbst.

---

## Entscheide, die noch ausstehen

| Frage | Wann nötig |
|---|---|
| Kostenrechnung je Mandant — trägt CHF 39 den Betrieb? | vor Preisfestlegung |
| Hosting-Standort: PythonAnywhere oder Schweiz | vor Markteintritt, beeinflusst P1.4 |
| Zahlungsanbieter — Offerten Payrexx, wallee, Stripe | Phase 3, freigabepflichtig |
| Gespräche mit 5 bis 10 Verwaltungen zur Zahlungsbereitschaft | vor Preisfestlegung |
| Groq: DPF-Zertifizierung prüfen, Auftragsbearbeitungsvertrag | offen aus P0.7, siehe `docs/GROQ-BELEGERKENNUNG.md` |
