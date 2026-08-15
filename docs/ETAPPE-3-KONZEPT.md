# Etappe 3 — Migrationskonzept, vorgelegt vor dem ersten Commit

**Stand:** 15.08.2026 · **Auftrag:** `docs/ETAPPE-3-USER-MODEL.md` · **Agent:** `chirurg`

Der `chirurg` beginnt laut eigener Spezifikation nicht mit Code, sondern legt vor: Welcher Weg
für die Datenübernahme, welcher Zwischenzustand bei Abbruch, bleiben die IDs, was geht am Ende
noch nicht. Dieses Dokument beantwortet das — **gemessen, nicht geschätzt.**

Grundlage ist ein Wegwerf-Versuch auf einer Kopie der echten Datenbank (7 Benutzer,
3 Gruppenmitgliedschaften, 15 Fremdschlüsselspalten auf `auth_user`). Kein Commit, keine
Änderung am Repository.

---

## Drei Funde, die den Auftrag ändern

### 1. Der automatische Deploy scheitert — und zwar bevor eine einzige Migration läuft

Das ist der wichtigste Fund. Auf der **Bestandsdatenbank** bricht `manage.py migrate` sofort ab:

```
django.db.migrations.exceptions.InconsistentMigrationHistory:
Migration admin.0001_initial is applied before its dependency benutzer.0001_initial
```

Der Grund: Die 13 bereits angewendeten Migrationen mit `swappable_dependency` hängen nach dem
Tausch formal an `benutzer.0001_initial` — die nicht angewendet ist. Djangos Konsistenzprüfung
läuft **vor** dem ersten Schritt und bricht ab.

Das trifft dieses Projekt besonders, weil `deploy.sh` unbeaufsichtigt als Scheduled Task läuft
und `docs/AUTOMATISIERUNG.md` ausdrücklich zusichert: *„Es gibt keinen separaten
Migrationsschritt, den jemand von Hand nachziehen müsste."*

**Die gute Nachricht:** Der Abbruch ist sicher. `deploy.sh` lädt bei gescheiterter Migration
nicht neu — die alte Version bleibt live. Es gibt keinen halb migrierten Zustand.

**Die Konsequenz:** Etappe 3 braucht einen Schritt **vor** `migrate`. Keine Migration kann das
lösen, weil die Prüfung vor allen Migrationen greift.

### 2. Eine bestehende Daten-Migration stürzt auf jeder frischen Datenbank ab

`core/migrations/0002_rollen_gruppen.py` holt das Benutzermodell hart:

```python
User = apps.get_model('auth', 'User')       # Zeile 11
for user in User.objects.filter(is_active=True):
```

Nach dem Tausch:

```
AttributeError: Manager isn't available; 'auth.User' has been swapped for 'benutzer.Benutzer'
```

Das bricht **jeden Testlauf und die gesamte CI** — nicht die Produktion, wo die Migration längst
angewendet ist. Ohne diesen Fund wäre Etappe 3 mit einer vollständig roten CI gelandet.

Die Behebung ist der einzige Fall in diesem Schritt, in dem eine **bereits angewendete Migration
im Code geändert** werden muss: `apps.get_model(settings.AUTH_USER_MODEL)` plus
`swappable_dependency`. Zulässig, weil der erzeugte Datenbankzustand derselbe bleibt und die
Migration auf der Produktion nie wieder läuft.

### 3. Schritt 1 erzeugt keine Migrationen — bis auf eine, und die ist mein eigener Altlast

Die Vereinheitlichung der 10 harten `'auth.User'` auf `settings.AUTH_USER_MODEL` erzeugt
**keine einzige Migration**: `makemigrations --check` bleibt sauber. Django schreibt beim
Zerlegen eines Fremdschlüssels ohnehin `settings.AUTH_USER_MODEL`, solange das Ziel das
tauschbare Modell ist — die alte und die neue Schreibweise sind deckungsgleich. Schritt 1 ist
damit eine reine Textänderung ohne Datenbankwirkung.

Eine Ausnahme: `crm/migrations/0029_mandant_zu_eigentuemer.py:49` schreibt `to='auth.user'`
**hart**, statt die tauschbare Referenz zu verwenden. Das ist eine Altlast aus meiner eigenen
E3-Umbenennung. Sie friert den historischen Zustand auf `auth.User` ein, weshalb der
Autodetektor eine `AlterField`-Migration für `Eigentuemer.benutzer` verlangt.

Ich schlage vor, das **nicht** in der Historie zu reparieren, sondern die verlangte Migration
regulär entstehen zu lassen — sie betrifft eine Tabelle mit einer Zeile. Historie umschreiben,
wo eine Vorwärtsmigration genügt, ist die schlechtere Gewohnheit.

---

## Der empfohlene Weg: die Tabelle übernehmen, statt Daten zu kopieren

Es standen zwei Wege zur Wahl. Beide wurden auf einer Kopie der echten Datenbank ausprobiert.

| | **A — Kopieren** | **B — Übernehmen** *(empfohlen)* |
|---|---|---|
| Neue Tabelle | `benutzer_benutzer` | keine, `db_table = 'auth_user'` |
| Datenzeilen bewegt | 7 Benutzer + 3 Mitgliedschaften | **keine** |
| IDs, Passwort-Hashes, Sitzungen | müssen bewusst erhalten werden | unberührt |
| 15 Fremdschlüssel in der Datenbank | zeigen weiter auf `auth_user` → 12 handgeschriebene `AlterField` nötig | zeigen bereits richtig, **nichts zu tun** |
| Aufwand auf der Produktion | Tabellen anlegen, Zeilen kopieren, 12 Tabellen umbauen | 2 Spalten umbenennen, 1 Zeile eintragen |

Der Ausschlag gibt die Zeile mit den Fremdschlüsseln. Bei Weg A sagt Djangos Zustand, die
Fremdschlüssel zeigten auf das neue Modell — die Datenbank hat sie aber weiter auf `auth_user`.
Django erzeugt dafür **von sich aus keine Operation**; die Abweichung bliebe unbemerkt bestehen
und würde beim PostgreSQL-Umzug mitwandern. Bei Weg B stimmen Zustand und Datenbank überein,
weil das Ziel tatsächlich `auth_user` heisst.

Weg B ist auf der Datenbankkopie vollständig durchgelaufen. Danach:

```
Modell: benutzer.Benutzer | Tabelle: auth_user | M2M: auth_user_groups
Benutzer: 7 | IDs: [1, 2, 3, 4, 5, 6, 7]
  #2  chef            rollen=['Verwaltung']       team=True  verwaltung=True
  #3  sachbearbeiter  rollen=['Sachbearbeitung']  team=True  verwaltung=False
  #4  revision        rollen=['Lesend']           team=True  verwaltung=False
  #7  eigentuemer-…   eigentuemer=True
Eigentuemer mit Benutzer: 1 | Mieter mit Benutzer: 1
```

IDs, Passwort-Hashes (`pbkdf2_sha256…`), Gruppen, beide Portalverknüpfungen und das
Rollenmodell aus `core/auth.py` unverändert. Das Anmelde-Backend arbeitet ohne Änderung —
es holt das Modell schon heute über `get_user_model()`.

### Die zwei Spaltenumbenennungen

Django leitet die Namen der Zwischentabellen aus `db_table` ab — sie heissen also
weiterhin `auth_user_groups` und `auth_user_user_permissions`, ohne Zutun. Nur die
Spalte darin folgt dem **Modellnamen**: aus `user_id` wird `benutzer_id`.

Das ist der einzige Datenbankeingriff des ganzen Schritts, und er ist verlustfrei.

*(Alternative: das Modell `User` statt `Benutzer` nennen — dann entfiele auch das, weil die
Spalte `user_id` bliebe. Ich rate ab: Das Projekt benennt deutsch, `Eigentuemer` ist gerade erst
so umbenannt worden. Zwei `RENAME COLUMN` sind der günstigere Preis als eine Ausnahme in der
Namensgebung.)*

### Der Schritt vor `migrate`

Ein neuer, idempotenter Management-Command `benutzer_uebernahme`, den `deploy.sh` **vor**
`migrate` aufruft:

- `benutzer.0001_initial` steht schon in `django_migrations` → nichts tun
- `auth_user` existiert nicht (frische Datenbank, CI, Tests) → nichts tun
- sonst → 2 Spalten umbenennen, `benutzer.0001_initial` als angewendet eintragen

Er läuft genau einmal wirklich, danach für immer als Leerlauf. Damit bleibt die Zusicherung
aus `docs/AUTOMATISIERUNG.md` gültig: Niemand muss von Hand nachziehen.

**Das ist die eine Stelle, an der ich Bestätigung brauche** — es ist eine Änderung am
Ausrollen, nicht nur am Code.

---

## Antworten auf die vier Pflichtfragen des Auftrags

**Welcher Weg und warum.** Weg B, weil keine Zeile bewegt wird und die 15 Fremdschlüssel
bereits richtig zeigen. Weg A hätte eine stille Abweichung zwischen Djangos Zustand und der
Datenbank hinterlassen.

**Zwischenzustand bei Abbruch.** Gemessen: Bricht es ab, dann bei der Konsistenzprüfung
**vor** der ersten Migration. `deploy.sh` lädt dann nicht neu, die alte Version bleibt live,
die Datenbank ist unberührt. Bricht es nach der Übernahme ab, sind zwei Spalten umbenannt und
eine Zeile in `django_migrations` eingetragen — der Rückweg ist zwei `RENAME COLUMN` und ein
`DELETE`, beides im Command hinterlegt.

**Bleiben die IDs erhalten.** Ja, zwingend — die Zeilen werden nicht angefasst. Auf der
Datenbankkopie nachgewiesen: IDs 1–7 unverändert, `Eigentuemer.benutzer` und `Mieter.benutzer`
lösen weiterhin auf.

**Was danach noch nicht geht.** Keine Mandantentrennung — das ist Etappe 4. Die 11
Isolationstests bleiben `expectedFailure`. Kein zusätzliches Benutzerfeld, keine `Organisation`,
keine Rollen je Organisation. Der Admin umgeht den fehlenden `TenantManager` weiterhin.

---

## Umfang des PR

Alle vier Schritte in einem PR, wie der Auftrag verlangt.

| | Was | Umfang |
|---|---|---|
| 1 | 10 harte `'auth.User'` → `settings.AUTH_USER_MODEL` | 3 Dateien, 0 Migrationen |
| 2 | App `benutzer`, Modell `Benutzer(AbstractUser)`, `db_table='auth_user'` | 4 neue Dateien, 1 Migration |
| 3 | `AUTH_USER_MODEL`, Übernahme-Command, `deploy.sh` | Settings, 1 Command, 1 Zeile Deploy |
| 4 | 8 Importe, 15 `User.objects`, `core/admin.py`, 10 Testmodule | ~20 Dateien |

Bekannt aus dem Spike, gehört zu Schritt 4: `core/admin.py` bricht beim Start mit
`NotRegistered: The model User is not registered` — nach dem Tausch registriert Django den
`auth.User`-Admin nicht mehr, das `unregister` läuft ins Leere.

---

## Was ich ausdrücklich **nicht** vorhabe

- Historie umschreiben, wo eine Vorwärtsmigration genügt (`crm/0029` bleibt, wie es ist)
- Zusätzliche Felder am Benutzermodell — auch nicht „schon mal vorbereiten"
- Aufräumen in den ~20 berührten Dateien. Auffälliges kommt in die PR-Beschreibung.
- Etwas an den Isolationstests ändern, damit sie grün werden

---

## Zum Nachvollziehen

Der Versuchsaufbau liegt im Scratchpad unter `spike/` und ist nicht Teil des Repositories.
Er lässt sich mit einer Kopie von `db.sqlite3` wiederholen.

---

## Ausgeführt am 15.08.2026

Alle vier Schritte wie beschrieben, in einem PR. Zwei Abweichungen vom Konzept und ein Fund:

**Abweichung 1 — `AutoField` statt `BigAutoField`.** Die zuerst erzeugte Migration deklarierte
`id` als `BigAutoField` (der Projektstandard für neue Apps). Die übernommene Tabelle `auth_user`
hat aber einen 32-Bit-Integer, ebenso die 15 Fremdschlüsselspalten darauf. Auf SQLite bliebe das
unsichtbar — beim Wechsel auf PostgreSQL (P1.4) wäre es exakt die stille Abweichung zwischen
Djangos Zustand und der Datenbank, die dieser Weg vermeiden soll. `BenutzerConfig` setzt deshalb
`default_auto_field = 'django.db.models.AutoField'`, wie `django.contrib.auth` es tut.

**Abweichung 2 — die Spaltenumbenennung fällt kleiner aus als gedacht.** Das Konzept vermutete,
auch die Zwischentabellen müssten umbenannt werden. Falsch: Django leitet deren **Namen** aus
`db_table` ab, sie heissen ohnehin schon `auth_user_groups` und `auth_user_user_permissions`.
Nur die **Spalte** darin folgt dem Modellnamen. Es sind also zwei `RENAME COLUMN`, keine vier
Operationen.

**Fund — `Benutzer.username` ist global eindeutig.** Regel 5 des Skills `mandantentrennung`:
Zwei Verwaltungen können keinen Benutzer `info@` führen. Der Katalog aus Etappe 2 zählt diesen
Fall unter seinen sechs Constraints **nicht** mit. Nicht behoben — `username` stammt aus
`AbstractUser`, eine Änderung bricht die Anmeldung und gehört zusammen mit der Mitgliedschaft je
Organisation entschieden. Vermerkt in `PHASE-2-PLAN.md` bei Etappe 4.

### Belege

| Prüfung | Ergebnis |
|---|---|
| `ruff check .` | All checks passed |
| `manage.py check` | no issues (1 silenced) |
| `makemigrations --check --dry-run` | No changes detected |
| Testsuite | **1'093** (1'082 + 6 + 5), 11 `expectedFailure`, 4 übersprungen — unverändert |
| `IsolationstestsSelbstpruefungTests` | 3 grün |
| Vorwärtsweg | auf unberührter Kopie der echten Datenbank: `benutzer_uebernahme` → `migrate` → OK |
| Rückwärtsweg | `migrate crm 0030` + `benutzer_uebernahme --rueckwaerts` → Zustand zeilenweise identisch mit dem Ausgangspunkt (Tabellen, Spalten, 7 Benutzer samt Hashes, `django_migrations`) |
| Nach dem Vorwärtsweg | IDs 1–7, Rollen (`Verwaltung`/`Sachbearbeitung`/`Lesend`), `ist_eigentuemer`, `Eigentuemer.benutzer`, `Mieter.benutzer` alle unverändert |

### Nachtrag: der Auditor-Lauf über den eigenen Diff

Der `mandanten-auditor` fand **kein Leck**, aber drei Dinge, die im Diff selbst nachzubessern
waren. Alle drei sind eingearbeitet:

**Der Wächtertest wäre blind geworden.** `EIGENE_APPS` in `core/tests/test_isolation.py` zählte
sieben Apps auf; Etappe 3 legt eine achte an und trug sie nicht nach. Folge in Etappe 4: Sobald
die übrigen Modelle ihren Bezug haben, wird `test_jedes_modell_hat_einen_weg_zur_organisation`
grün, der Marker fällt planmässig weg — und ausgerechnet `benutzer.Benutzer`, das Modell, an dem
die Mandantenzugehörigkeit hängen wird, wäre das einzige, das der Wächter nie prüft. Ein Test, der
aufhört zu prüfen, ohne dass es auffällt. `benutzer` steht jetzt in `EIGENE_APPS`, und `Benutzer`
als **benannte** Ausnahme in `BEGRUENDETE_AUSNAHMEN` — eine Ausnahme kann man beim Lesen
widerrufen, eine fehlende Zeile in einem Tupel nicht.

**Die Zahl 13 war falsch.** Am Migrationsgraphen aufgelöst hängen **16** angewendete Migrationen
an `benutzer.0001_initial` — die 13 Projektmigrationen mit `swappable_dependency` plus Djangos
`admin.0001_initial` plus die beiden, die dieser Schritt selbst erzeugt. Meine 13 stammten aus
einer Textsuche über die Projektdateien, nicht aus dem Graphen. Korrigiert im Docstring des
Commands.

**Zwei Löcher im Rückweg.** `--rueckwaerts` benannte die Spalten zurück, ohne zu prüfen, ob der
laufende Code das verträgt — ein versehentlicher Aufruf hätte eine einwandfrei laufende Anwendung
lahmgelegt (fail-closed, aber Ausfall). Der Command verlangt jetzt `--code-wird-zurueckgerollt`,
solange `AUTH_USER_MODEL` noch auf dieses Modell zeigt; `--trocken` bleibt frei. Dazu ein
Vorabcheck auf SQLite ≥ 3.25: `ALTER TABLE … RENAME COLUMN` ist die eine Anweisung, an der der
ganze unbeaufsichtigte Deploy hängt, und ein Fehlschlag mittendrin liesse eine Spalte umbenannt
und die andere nicht.

**Und eine Zusicherung, die nicht mehr ganz galt.** `deploy.sh` versprach: „bei gescheiterter
Migration bleibt die alte Version aktiv." Das stimmte, solange `migrate` an der Konsistenzprüfung
abbrach, **bevor** es die Datenbank anfasste. Jetzt läuft die Übernahme davor — gelingt sie und
scheitert `migrate` danach, liest der noch laufende alte Prozess gegen ein Schema, das er nicht
kennt. Der Kommentar sagt das jetzt. Scheitert die Übernahme selbst, gilt die alte Zusicherung
unverändert.

Fünf weitere Funde betreffen erst Etappe 4 und stehen dort im Plan: `username` global eindeutig,
das Existenz-Orakel in der Namensprüfung, der Aussperrschutz über die Mandantengrenze, `email` als
globaler Identifikator, und Konten mit Eigentümer- **und** Mieterprofil. Dazu eine
Abdeckungslücke der Etappe-2-Tests (Bauform A erfasst keine Querystring-Filter), vermerkt bei
Etappe 2.

### Was bewusst offen bleibt

- Der Fund zu `username` (siehe oben) — Etappe 4.
- `crm/0029` behält `to='auth.user'`. Statt Historie umzuschreiben entsteht die reguläre
  Vorwärtsmigration `crm/0031`.
- Nichts aufgeräumt in den ~20 berührten Dateien. Die einzigen Umstellungen ausserhalb des
  Auftrags sind meine eigenen Einfügungen: `User = get_user_model()` steht hinter dem lokalen
  Importblock, nicht mittendrin.
