# Onboarding — wie man Kunde wird (vor P3.1)

Entwurf zur Entscheidung, kein Umbau. Stand 20.09.2026, gemessen gegen `b68387e`.

Aufgefallen beim Ausarbeiten des Entitlement-Entwurfs
(`docs/PHASE-3-ENTITLEMENTS.md`, Abschnitt 5.3a): Ein Abo-System sperrt
Funktionen nach Stufe. Bevor das einen Wert hat, muss jemand eine Stufe kaufen
können — und dafür muss er überhaupt erst hineinkommen.

---

## 1. Was es gibt und was fehlt — nachgemessen

| Schritt | Stand |
|---|---|
| Anmelden, Passwort vergessen, Passwort neu setzen | **vorhanden** — `login/`, `passwort/vergessen/`, `passwort/neu/<uidb64>/<token>/`, Django-Bordmittel |
| Zwei-Faktor beim Anmelden | **vorhanden** — TOTP, Notfallcodes, organisationsweite Pflicht |
| Kollegen zu einer **bestehenden** Organisation hinzufügen | **vorhanden** — `core/views/fw/benutzer.py:121`, mit Rolle |
| Vier Rollen | **vorhanden** — Inhaber, Verwalter, Sachbearbeiter, Lesezugriff |
| Eine **Organisation** anlegen | **war** nur ein Notbehelf in `core/utils/market_data.py:172` — seit E2.78 `organisation_anlegen` |
| Die **erste** Mitgliedschaft einer neuen Organisation | **war** nicht möglich — seit E2.78 im selben Dienst |
| Testphase | **seit E2.78** als `abo_start`/`abo_bis` am Modell |
| Öffentliche Registrierung | fehlt — und bleibt vorerst weg, siehe Entscheid 1 |
| Einladung per E-Mail | fehlt |

*Die Befunde oben sind der Stand vom 20.09.2026 vor E2.78; die Spalte sagt,
was daraus geworden ist. Der Abschnitt bleibt als Ausgangslage lesbar, weil
sonst nicht mehr nachvollziehbar wäre, wogegen gebaut wurde.*

**Die Lücke ist kleiner, als sie zuerst aussah, und genauer zu benennen.** Es
fehlt kein Benutzerverwaltungs-System — das steht. Es fehlt der **Einstieg**:
der Weg vom leeren Bildschirm zur ersten Organisation mit ihrem ersten
Inhaber.

> **Korrektur im Vorgängerdokument:** Dort stand zuerst, keine Stelle lege eine
> `Mitgliedschaft` an. Der Grep suchte `objects.create` und übersah
> `update_or_create`. Festgehalten als `bekannte-fallen` 2c.

## 2. Das Henne-Ei-Problem

`fw_benutzer_form` liest `request.organisation`. Wer Mitglied ist, kann
Kollegen hinzufügen; wer keine Organisation hat, kommt nicht hinein.

Jeder Onboarding-Entwurf muss genau diesen Knoten lösen: **ein Weg, der ohne
bestehende Mitgliedschaft auskommt.**

Der erste Entwurf hielt das für die heikelste Stelle der ganzen Sache, weil
die Mandantentrennung darauf beruht, dass nichts ohne Kontext arbeitet. Beim
Bauen erwies sich das als falsch — siehe 3.2. Die Sorgfalt liegt woanders:
darin, keine Organisation ohne Inhaber zurückzulassen.

---

## 3. Entwurf

### 3.1 Der Weg

```
/registrieren/        E-Mail + Passwort + Firmenname
      |
      v
E-Mail mit Bestätigungslink (Token, begrenzt gültig)
      |
      v
/registrieren/bestaetigen/<token>/
      |
      +-- Organisation anlegen       (firma aus dem Formular)
      +-- Benutzer anlegen           (falls noch nicht vorhanden)
      +-- Mitgliedschaft anlegen     (Rolle: Inhaber)
      +-- Testphase setzen           (abo_bis = heute + N Tage)
      |
      v
Anmeldung, dann der bestehende Einrichtungsweg
```

**Warum Bestätigung per E-Mail vor dem Anlegen:** Sonst legt jeder Besucher
Organisationen an. Eine Organisation ist in diesem System der Mandant — der
Anker, an dem die gesamte Datentrennung hängt. Leere Mandanten sind kein
Schönheitsfehler, sie sind Datensätze, die niemandem gehören.

### 3.2 Der Mandantenkontext ist gar nicht das Problem — korrigiert beim Bauen

Dieser Abschnitt entwarf zuerst einen benannten Ausstieg aus dem
Mandantenkontext (`alle_organisationen`), weil eine Organisation ja ohne
Kontext entsteht. **Beim Bauen stellte sich heraus: den braucht es nicht.**
Zwei Gründe, beide im Bestand nachgelesen statt angenommen:

1. `Organisation` trägt **keinen** `TenantManager`. Sie IST der Anker, an dem
   der Kontext hängt — ein Filter auf sich selbst wäre zirkulär.
2. `TenantManager` filtert **Lesen**, nicht Schreiben. `core/tenancy.py` sagt
   es wörtlich: «Schreiben braucht keinen Kontext, Lesen schon», weil ein
   `create` nichts herausgibt.

Nötig ist der Kontext an genau einer Stelle, und aus dem umgekehrten Grund:
Die Mitgliedschaft entsteht mit `update_or_create`, und das **liest zuerst**.
Dafür wird der Kontext auf die eben angelegte Organisation gesetzt — kein
Ausstieg, sondern der normale Weg.

> Dreimal in dieser Reihe hat sich ein aus Überlegung geschriebener Entwurf
> beim Nachmessen als zu pessimistisch erwiesen. Der Bestand ist freundlicher
> als die Vermutung — was kein Grund ist, weniger nachzusehen, sondern einer,
> Entwürfe als Vermutung zu kennzeichnen.

### 3.3 Testphase

`docs/MARKT.md` nennt 30 Tage als Marktstandard (Fairwalter). Technisch
braucht es dafür zwei Felder an der Organisation:

```python
abo_start = models.DateField(null=True, blank=True)
abo_bis   = models.DateField(null=True, blank=True)   # Ende der Testphase
```

Die Testphase ist damit **kein eigener Zustand**, sondern ein Datum — und das
passt genau auf die Zustandslogik aus dem Entitlement-Entwurf (Abschnitt 2C):
Ist `abo_bis` überschritten und keine Zahlung hinterlegt, greift derselbe
Weg wie bei Zahlungsverzug. Eine zweite Mechanik dafür wäre die Stelle, an
der beide auseinanderlaufen.

### 3.4 Einladung statt Selbstregistrierung für Kollegen

Der zweite und jeder weitere Benutzer kommt **nicht** über `/registrieren/`,
sondern über die bestehende Benutzerverwaltung. Heute vergibt sie ein
Passwort; besser wäre eine Einladung per E-Mail mit Token, damit niemand ein
fremdes Passwort kennt.

Das ist eine Verbesserung, keine Lücke — der Weg funktioniert.

---

## 4. Was daran heikel ist

### 4.1 Eine öffentliche Seite, die schreibt

`/registrieren/` ist ohne Anmeldung erreichbar und legt Datensätze an. Im
Bestand gibt es dafür zwei Vorbilder mit denselben Anforderungen: das
öffentliche Bewerbungsformular (`mietprozess/api.py`, mit Drosselung — die
Antwort kennt `429`) und das Schadenformular vom Aushang.

Mindestens nötig: Drosselung je IP, Bestätigung per E-Mail vor dem Anlegen,
und eine Obergrenze offener Registrierungen je Adresse.

### 4.2 Die erste Rolle ist Inhaber

Wer registriert, wird Inhaber — das ist die Rolle mit den weitesten Rechten
(`INHABER_ROLLEN`). Das ist richtig, weil es sonst niemanden gäbe, der
Kollegen hinzufügen kann. Es heisst aber: Der Registrierungsweg vergibt die
höchste Rolle im System, und er ist öffentlich erreichbar. Die Absicherung
aus 4.1 ist deshalb keine Feinarbeit.

### 4.3 Die harte Grenze aus Phase 2 gilt weiter

`docs/PHASE-2-ABSCHLUSS.md` hält fest: **keine zweite Organisation, bevor
PostgreSQL, der Wiederherstellungs-Probelauf und 2FA erledigt sind.**

Stand heute: 2FA ist erledigt (`docs/MARKT.md`, Abschnitt 8, korrigiert am
20.09.2026). Für PostgreSQL ist der Unterbau da (`DB_ENGINE=postgres`), der
Umzug selbst offen. Der Wiederherstellungs-Probelauf ist hier nicht geprüft.

**Ein Registrierungsweg ist die Maschine, die zweite Organisationen
erzeugt.** Er darf frühestens scharf geschaltet werden, wenn diese Grenze
fällt — gebaut und getestet werden kann er vorher.

---

## 5. Reihenfolge

| Schritt | Inhalt | Stand |
|---|---|---|
| 1 | Felder `abo_start`/`abo_bis` an `Organisation` | **erledigt** (E2.78) |
| 2 | Dienst `organisation_anlegen(...)` samt Isolationstests | **erledigt** (E2.78, `core/services/onboarding.py`) |
| 2a | Management-Command `organisation_anlegen` | **erledigt** (E2.78) |
| 3 | `/registrieren/` mit E-Mail-Bestätigung und Drosselung | offen — und nach Entscheid 1 unten vorerst **nicht** vorgesehen |
| 4 | Einladung per E-Mail statt Passwortvergabe | offen |
| 5 | Scharfschalten | wartet auf PostgreSQL-Umzug und Wiederherstellungs-Probelauf |

Der Command verweigert eine **zweite** Organisation, solange nicht `--zweite`
mitgegeben wird, und nennt im Fehlertext die Bedingungen aus
`docs/PHASE-2-ABSCHLUSS.md`. Damit steht die harte Grenze im Weg und nicht
nur im Text.

Die Schritte 1 bis 4 sind unabhängig von der Entitlement-Arbeit und
unabhängig vom Zahlungsanbieter. Schritt 5 ist ein Entscheid, kein Bau.

---

## 6. Was entschieden werden muss

1. **Selbstregistrierung oder Anlage von Hand?** Solange es um einzelne
   Kunden geht, ist ein Management-Command plus ein Gespräch ehrlicher und
   billiger als ein öffentlicher Registrierungsweg mit allem, was 4.1
   verlangt. Der öffentliche Weg lohnt sich ab dem Punkt, an dem Kunden
   schneller kommen, als man sie von Hand anlegen mag.

   > **Empfehlung:** Erst der Command (Schritt 2 ohne Schritt 3). Er ist
   > ohnehin die Grundlage, und er lässt sich nicht missbrauchen.

2. **Länge der Testphase.** MARKT.md nennt 30 Tage als Marktstandard und
   führt die Frage als offen.

3. **Welche Stufe während der Testphase gilt.** Heute bekommt eine neu
   angelegte Organisation `abo_plan='pro'` — den Vorgabewert des Modells. In
   der bestätigten Vierer-Struktur gibt es `pro` nicht. Das ist folgenlos,
   solange keine Prüfstelle den Plan abfragt (gemessen: keine), und wird mit
   Schritt 7 des Entitlement-Entwurfs erledigt. Zu entscheiden ist dann, ob
   eine Testphase auf der höchsten Stufe läuft (alles zeigen, was man kaufen
   kann) oder auf der gebuchten.

4. **Was am Ende der Testphase geschieht** — sperren wie bei Zahlungsverzug
   (Lesen und Export), oder vorher aktiv nachfassen. Das ist eine
   Vertriebsfrage mit technischer Folge.
