# Postfach je Verwaltung — vollständige Umsetzung

**Stand:** 18.08.2026
**Basis:** `main`
**Agent:** `chirurg`
**Umfang:** klassisch und OAuth2 zusammen, inklusive Oberfläche

---

## Zur Frage: ist das jetzt ein Problem?

**Nein, und der Zeitpunkt ist besser als später.**

Phase 2 ist abgeschlossen — 63 Modelle tragen den Organisationsbezug, der `TenantManager` filtert, 25 Isolationstests sind grün. Felder zu ergänzen ist eine gewöhnliche Migration; `crm` steht bei `0040`.

**Es gibt genau eine Organisation.** Die Datenmigration der heutigen Zugangsdaten betrifft **eine Zeile**. Nach der zweiten Verwaltung wären es zwei Bestände, und ein Fehler bei der Übertragung träfe fremde Daten.

**Die zweite Organisation kommt dann in ein System, in dem die Post schon getrennt ist** — statt dass man sie nachträglich trennt, während zwei Verwaltungen aus demselben Postfach lesen. Genau diesen Zustand benennt `docs/AUFTRAG-ZWEITE-ORGANISATION.md` als Leck.

Kein Konflikt mit der zweiten Organisation: Die legt Zeilen an und bringt einen Command, dieser Auftrag ändert Schema und Views.

---

## OAuth2 ohne Testverzeichnis: gebaut ist nicht bewiesen

Entschieden: **OAuth2 wird vollständig gebaut, auch ohne Microsoft-365-Verzeichnis zum Erproben.** Das ist vertretbar, aber es verändert die Abnahme, und das muss im Code und in der Oberfläche sichtbar sein.

**Was ohne echtes Verzeichnis prüfbar ist:** der eigene Code. Token holen, erneuern, XOAUTH2-Zeichenkette bilden, Fehler behandeln, verschlüsselt ablegen, im Fehlerfall melden. Alles gegen einen nachgebildeten Token-Endpunkt und einen nachgebildeten IMAP-Server.

**Was nicht prüfbar ist:** ob Microsoft die Zeichenkette annimmt. Registrierung, Zustimmungsablauf, Scope-Zusammensetzung, Verhalten von Exchange Online — das entscheidet sich erst am echten Verzeichnis.

Die bekannten Stolpersteine liegen genau dort: fehlendes `offline_access` (dann gibt es kein Refresh-Token, und das merkt man erst nach einer Stunde), IMAP am Postfach nicht eingeschaltet (`Set-CASMailbox -ImapEnabled $true`), unvollständige Scopes, widerrufene Zustimmung.

### Was das kompensiert

**Der Verbindungstest wird zum Abnahmewerkzeug.** Er muss für jeden bekannten Fehlerfall eine Meldung liefern, mit der ein Mensch etwas anfangen kann — nicht „Anmeldung fehlgeschlagen", sondern etwa „Der Server hat das Token abgelehnt. Häufigste Ursache: IMAP ist für dieses Postfach nicht freigegeben. Ihr Administrator aktiviert es mit `Set-CASMailbox -ImapEnabled $true`."

**Eine Prüfliste für die erste echte Einrichtung** gehört ins Repo — `docs/OAUTH2-ERSTEINRICHTUNG.md`. Sie macht die erste M365-Verwaltung zur Abnahme: Schritt für Schritt, mit den erwarteten Rückmeldungen und was zu tun ist, wenn eine ausbleibt. Der erste Kunde wird so zum Mitprüfer, nicht zum Betroffenen.

**In der Oberfläche gekennzeichnet.** Beim Verfahren OAuth2 ein Hinweis: neu, noch nicht mit einem Kundenverzeichnis erprobt, Rückmeldung erwünscht. Das ist unbequem und richtig — es kostet weniger als ein Kunde, der annimmt, es sei eine geprüfte Funktion.

**Und nicht bewerben, bevor es einmal lief.** M365-Unterstützung gehört erst in Verkaufsunterlagen und ins Handbuch, wenn die Prüfliste einmal vollständig abgehakt wurde. Das gehört als offener Punkt in `docs/MARKT.md`.

Falls es später blockiert: Ein Microsoft-Testverzeichnis lässt sich einrichten, auch ein Probeabonnement genügt. Dann ist die Prüfliste in einer Stunde durch.

---

## Die weiteren Entscheide

**Ein Postfach je Verwaltung**, in der Oberfläche konfigurierbar. Eine Zuordnung *nach* dem Empfang rät; rät sie falsch, landet die Rechnung einer fremden Verwaltung im eigenen Bestand, und es fällt niemandem auf. Getrennte Postfächer machen die Zuordnung zur Voraussetzung statt zum Ergebnis.

**Zwei Verfahren, wählbar:** klassisch mit Benutzername und Passwort — vollwertig, nicht Notlösung, deckt klassische Hoster und Gmail per App-Passwort ab. Und OAuth2 (Authorization Code mit Refresh-Token) für Microsoft 365.

**Alle Geheimnisse verschlüsselt** (Fernet; `cryptography==46.0.3` steht in `requirements.txt:32`), Schlüssel ausserhalb der Datenbank.

**Für Gmail kein OAuth2.** Der Scope `https://mail.google.com/` gilt als restricted und verlangt eine jährliche Sicherheitsbewertung durch einen zugelassenen Drittanbieter — unverhältnismässig. App-Passwort deckt es ab; für Workspace-Kunden gibt es später den Weg über die Freigabe durch ihren Administrator, ohne Prüfverfahren.

---

## Der Ist-Zustand

| Wo | Was |
|---|---|
| `fetch_rechnungen` | `RECHNUNGS_IMAP_USER`, `RECHNUNGS_IMAP_PASSWORD`, `RECHNUNGS_IMAP_HOST` aus der Umgebung |
| `fetch_replies.py:104` | **Server fest im Code**: `IMAP_SERVER = "lx37.hoststar.hosting"` |
| Fernet-Schlüssel | existiert nicht |
| Einstellungsseite | `core/views/fw/aktionen.py:968` rendert `fw/einstellungen.html` |

### Richtigstellung zum Ist-Zustand (Vorrang des Bestands, 18.08.2026)

Nachgesehen. Drei der vier Zeilen stimmen (`je_organisation` liegt tatsächlich in `core/tenancy.py:171`, `cryptography` in `requirements.txt:32`, der feste Server in `fetch_replies.py:104`). Zwei andere Angaben des Auftrags nicht:

**Die Einstellungsseite ist nicht «nur eine Überschrift».** `fw_einstellungen` (`core/views/fw/aktionen.py:952`) baut eine Liste `karten` mit acht Einträgen — Account, Benutzer & Rollen, Vorlagen, Integrationen, Abonnement, Anmeldung & Sicherheit, Logbuch, Rechtsgrundlagen — und `fw/einstellungen.html` rendert sie als Kachelgitter. Für diesen Auftrag ist das eine **Erleichterung**: Die Postfach-Verwaltung braucht keine neue Seitenstruktur, sondern **einen weiteren Eintrag in `karten`** und die drei Views dahinter. Der naheliegende Ort ist neben «Integrationen», wo heute E-Mail, DocuSeal und Banken stehen.

**`OrganisationAusKette` ist die falsche Grundlage.** Diese Basisklasse ist ausdrücklich für Modelle mit einer **geschlossenen Pflicht-Kette** gedacht — Gruppe C, wo die Organisation aus `liegenschaft.organisation` oder `schluessel.liegenschaft.organisation` *abgeleitet* wird und nicht eingegeben werden darf (`core/organisation_kette.py`, Kopfkommentar). Ein Postfach hängt an nichts dergleichen; es gehört unmittelbar der Verwaltung. Die richtige Bauform ist die von `portfolio.Liegenschaft`:

```python
organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE,
                                 related_name='postfaecher')
objects = TenantManager()
alle_organisationen = AlleOrganisationenManager()
```

Die beiden Manager **explizit** setzen — sie werden nicht global angehängt. Das ist die Bauform, die im Bestand rund vierzigmal vorkommt (`portfolio/models.py:92`, `crm/models.py:173` und weitere).

### Beim Umbau gefunden: `fetch_replies` war kaputt (18.08.2026)

Nicht Teil des Auftrags, aber beim Lesen aufgefallen und mit Schnitt 2 behoben. `SchadenMeldung` erbt von `OrganisationAusKette`, sein `objects` ist also ein `TenantManager` — und der wirft seit Etappe 6.2 ohne gesetzten Mandantenkontext. Die alte Fassung rief

```python
ticket = SchadenMeldung.objects.get(id=ticket_id)
```

mitten aus dem Befehl heraus auf, wo es nie einen Kontext gab, und fing das Ergebnis wieder ein:

```python
except Exception as db_err:
    self.stdout.write(self.style.ERROR(f"❌ DB Fehler: {db_err}"))
```

**Jede eingehende Ticket-Antwort scheiterte damit still** — mit einer Protokollzeile, die nach einem Datenbankproblem aussah. Das ist der Grund, warum ein `except Exception` mit einer Sammelmeldung so teuer ist: Der Fehler war nicht unsichtbar, er war nur nicht als Fehler erkennbar. Wie lange das so lief, lässt sich aus dem Code nicht sagen; Etappe 6.2 ist der früheste mögliche Zeitpunkt.

**Für den Betrieb heisst das:** Antworten, die in dieser Zeit eingingen, wurden am Server als gelesen markiert (`RFC822` setzt das Flag beim Holen) und sind nicht in die Tickets gelangt. Sie liegen noch im Postfach — sichtbar, aber ungelesen in der Anwendung. Der neue Abruf holt mit `BODY.PEEK[]` und setzt das Flag erst nach erfolgreicher Verarbeitung; wer die alten Antworten nachholen will, markiert sie im Postfach wieder als ungelesen.

---

## Umsetzung

### 1 — Modell

Eigenes Modell `Postfach`, nicht Feldgruppen an `Organisation`: Es sind zwei Zwecke (Antworten, Rechnungen), und verdoppelte Feldgruppen werden unübersichtlich. Direkter Pflicht-FK auf `Organisation` plus `TenantManager`/`AlleOrganisationenManager` (siehe Richtigstellung oben), `unique_together` auf `(organisation, zweck)`.

Felder: Zweck, Verfahren, Server, Port, Benutzer, TLS, aktiv. Verfahrensabhängig: Passwort — oder Mandanten-ID, Anwendungs-ID, Refresh-Token. Dazu Status: letzter erfolgreicher Abruf, letzter Fehler, Fehlertext, letzter Verbindungstest.

**Alle Geheimnisse verschlüsselt**, nicht nur das Passwort. Ein Refresh-Token ist genauso wertvoll — damit liest jemand das Postfach, bis es widerrufen wird.

### 2 — Verschlüsselung

Fernet, Schlüssel aus `IMAP_SCHLUESSEL`, **nicht** aus `SECRET_KEY` abgeleitet.

Was sie leistet, gehört in den Code: **Schutz** gegen einen abhandengekommenen Datenbankauszug — kopierte Sicherung, `pg_dump` auf falschem Datenträger. **Kein Schutz** gegen jemanden auf dem Server, wo der Schlüssel in der `.env` daneben liegt. Sonst nimmt später jemand mehr Sicherheit an, als da ist.

Preis beschreiben: Schlüssel weg heisst Zugänge weg, jede Verwaltung richtet neu ein.

### 3 — Die Befehle

Beide über `je_organisation` (`core/tenancy.py:171`).

**Kein stiller Rückfall auf die Umgebungsvariablen.** Der gefährlichste Punkt: Fällt eine Verwaltung ohne Postfach darauf zurück, holt B aus dem Postfach von A. Ohne Konfiguration wird **übersprungen**, mit Protokolleintrag. Der fest verdrahtete Server in `fetch_replies.py:104` muss weg.

> **Abweichung, bewusst (18.08.2026): nicht über `je_organisation`, sondern über die Postfächer.**
>
> `je_organisation` läuft über **alle** Verwaltungen und ruft je eine Funktion. Hier ist die Liste der eingerichteten Postfächer die natürliche Schleife: Eine Verwaltung ohne Postfach hat in diesem Lauf nichts verloren, und über sie zu iterieren, nur um dann festzustellen, dass nichts zu tun ist, kehrt die Sache um. Ausserdem hätte jede Verwaltung dann **zwei** Postfächer (Antworten, Rechnungen) — die Schleife über Organisationen bräuchte innen ohnehin eine über Postfächer.
>
> **Die Zusage von `je_organisation` wird trotzdem eingelöst:** Der Lauf fängt je Postfach, damit ein Fehler bei Verwaltung 3 die Verwaltungen 4 bis 20 nicht ohne Abruf lässt. Das ist getestet (`test_eine_kaputte_verwaltung_haelt_die_uebrigen_nicht_auf`), mit protokollierter Gegenprobe.

### 4 — OAuth2

Authorization Code mit Refresh-Token, Anwendung mandantenübergreifend registriert.

- **`offline_access` im Scope** — ohne dieses Scope kein Refresh-Token.
- **Scopes vollständig**, inklusive Outlook-Ressourcen-URL.
- **XOAUTH2:** `user={adresse}^Aauth=Bearer {token}^A^A`, base64-kodiert, `^A` ist `\001`. `imaplib` kennt `authenticate('XOAUTH2', …)`.
- **Zugriffstokens leben etwa eine Stunde**, der Abruf erneuert selbst.
- **Rückleitungsadresse** je Umgebung in der Anwendungsregistrierung.

**Prüfbar ohne Verzeichnis:** Token-Erneuerung, Zeichenkettenbildung, Fehlerbehandlung, Ablage — gegen nachgebildete Gegenstellen.

### 5 — Views und Oberfläche

Drei Views, eingehängt als **neunte Kachel** in `fw_einstellungen` (`core/views/fw/aktionen.py:957`, Liste `karten`) — keine neue Seitenstruktur nötig, siehe Richtigstellung oben.

**`fw_postfaecher`** — Liste beider Zwecke mit Status: konfiguriert, letzter Abruf, letzter Fehler. Für Inhaber und Verwalter; Lesezugriff sieht, ändert nichts.

**`fw_postfach_form`** — Anlegen und Bearbeiten. Verfahren wählbar, Felder richten sich danach.

**Das gespeicherte Geheimnis wird nie zurück ins Formular geschrieben.** Leeres Feld heisst „unverändert", nicht „löschen" — sonst löscht ein Verwalter beim Ändern der Portnummer versehentlich das Passwort.

**`fw_postfach_test`** — Verbindungstest mit **sprechenden Meldungen** je Fehlerfall. Ohne ihn merkt eine Verwaltung erst beim nächsten nächtlichen Lauf, dass etwas falsch ist, und dann meldet es niemand. Ohne echtes Testverzeichnis ist er zugleich das Werkzeug, mit dem die erste M365-Einrichtung abgenommen wird.

Bei OAuth2 zusätzlich der Zustimmungsablauf: Weiterleitung, Rückleitung, Refresh-Token speichern.

**Hinweistext ins Formular**, nicht ins Handbuch — sonst suchen Leute den Fehler bei sich:

> Klassischer Hoster (Hoststar, cyon, Infomaniak, eigener Server): Benutzername und Passwort.
> Gmail: Benutzername und **App-Passwort**. Setzt 2FA im Google-Konto voraus. Bei Google Workspace kann der Administrator App-Passwörter gesperrt haben — dann bitte bei ihm nachfragen.
> Microsoft 365 / Exchange Online: **nur OAuth2** — Microsoft hat den Zugang mit Benutzername und Passwort abgeschaltet. Diese Anbindung ist neu und noch nicht mit einem Kundenverzeichnis erprobt; bitte melden Sie sich bei uns, wenn etwas nicht funktioniert.

### 6 — Überwachung

Die Bedingung, unter der Authorization Code vertretbar ist. Refresh-Tokens können ablaufen oder widerrufen werden; dann hört der Abruf **still** auf.

Schlägt die Erneuerung fehl: Eintrag im Aktivitätslog, Fehlertext am Postfach, sichtbare Meldung für Inhaber und Verwalter, und der Lauf überspringt die Verwaltung statt still nichts zu tun.

Ein Abruf, der seit drei Wochen nichts holt, ist schlimmer als einer, der laut scheitert.

### 7 — Startcheck für den Schlüssel

Fehlt `IMAP_SCHLUESSEL`, darf die Anwendung nicht mit unklarem Verhalten starten. Empfehlung: Die Anwendung läuft, aber die Postfach-Befehle brechen mit klarer Meldung ab und die Oberfläche zeigt den Grund — ein fehlender Postfachschlüssel macht die Anwendung nicht unbenutzbar, nur den Mailabruf. `core/wartung.py` ist als Muster lesenswert.

`.env.example` und die Deploy-Anleitung ergänzen. **Der Schlüssel gehört auf dem Server gesetzt, bevor dieser Code ausgerollt wird.**

### 8 — Der Übergang

Datenmigration überträgt die heutigen Umgebungsvariablen einmalig auf das Postfach der bestehenden Organisation — eine Zeile.

**Reihenfolge auf dem Server:** Schlüssel setzen → deployen → Migration läuft → Verbindungstest in der Oberfläche → **erst dann** die Umgebungsvariablen entfernen.

Nicht beides dauerhaft parallel — zwei Quellen für dieselbe Angabe sind das Muster, das in dieser Phase schon zweimal zu Fehlern geführt hat. Der Übergang ist eine geordnete Abfolge, kein Rückfall im Code.

---

## Abnahme

- Modell `Postfach` mit Pflicht-Organisationsbezug und `unique_together (organisation, zweck)`
- **Alle** Geheimnisse verschlüsselt; ein Test belegt, dass in der Datenbank kein Klartext steht
- Beide Befehle über `je_organisation`, **kein Rückfall**; fest verdrahteter Server entfernt
- Test mit zwei Organisationen: A holt aus A, B aus B, eine ohne Konfiguration wird übersprungen — **mit protokollierter Gegenprobe**
- Drei Views, je mit Rollenprüfung; Lesezugriff kann nichts ändern
- Leeres Geheimnisfeld heisst „unverändert" — mit Test
- Verbindungstest für Verfahren A **gegen ein echtes Postfach** erprobt (das produktive genügt)
- OAuth2-Codepfad gegen nachgebildete Gegenstellen geprüft: Token holen, erneuern, Zeichenkette bilden, Fehler behandeln
- Verbindungstest liefert für jeden bekannten OAuth2-Fehlerfall eine **handlungsleitende** Meldung — mit Test je Fall
- Fehlgeschlagene Token-Erneuerung führt zu sichtbarer Meldung, mit Test
- Fehlender `IMAP_SCHLUESSEL` führt zu klarer Meldung, nicht zu unklarem Verhalten — mit Test
- `docs/OAUTH2-ERSTEINRICHTUNG.md` vorhanden: Prüfliste für die erste echte M365-Einrichtung
- OAuth2 in der Oberfläche als noch nicht erprobt gekennzeichnet
- Datenmigration für den Bestand; Grenzen der Verschlüsselung und Wiederanlauf ohne Schlüssel dokumentiert
- Testsuite grün: `manage.py test` **ohne Labels**, Zahl gegen Discovery abgeglichen

**Nicht Teil der Abnahme:** ein erfolgreicher OAuth2-Abruf gegen ein echtes Microsoft-Verzeichnis. Das bleibt ausdrücklich offen und ist als solches zu kennzeichnen — im Code, in der Oberfläche und in `docs/MARKT.md`.

---

## Ein Punkt für `docs/MARKT.md`

OAuth2 ist eine Marktzugangsfrage, keine technische Feinheit. Ohne es sind Verwaltungen auf Microsoft 365 nicht bedienbar.

Zwei Einträge gehören dorthin: **M365-Unterstützung gebaut, aber nicht erprobt** — nicht bewerben, bevor die Prüfliste einmal durchlief. Und die Frage für die Gespräche mit den fünf bis zehn Verwaltungen: **Welches Postfach nutzt ihr?** Kommt dort mehrheitlich M365, wird die Erprobung dringend.
