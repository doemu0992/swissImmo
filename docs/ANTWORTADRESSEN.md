# E-Mail-Eingang der Plattform einrichten (Anleitung für den Betreiber)

Stand 4.11.2026. Diese Anleitung ist für Sie als Betreiber der Plattform, nicht für die Verwaltungen. Sie brauchen
keine Programmierkenntnisse; Sie klicken im Kundenbereich Ihres Mailhosters (oder bei Brevo), ergänzen eine Textdatei auf dem Server
und richten einen geplanten Abruf ein.

Es gibt **zwei Wege**, wie die Mails an die Plattformadressen (`<kennung>@immoswiss.app` für Antworten auf Tickets,
`<kennung>-rechnungen@immoswiss.app` für Rechnungen) bei der Anwendung ankommen. Sie wählen einen davon. (Technisch
gilt `ANTWORT_DOMAIN` für beide gemeinsam, und Brevo braucht eigene MX-Einträge für die Empfangsdomain; beide Wege
gleichzeitig sind darum nur mit einer eigenen Unterdomain für Brevo und einem Umbau der Adressen denkbar und nicht
vorgesehen.)

| | Variante A: Hoststar-Sammelpostfach | Variante B: Brevo |
|---|---|---|
| Neuer Anbieter | nein | ja (Brevo) |
| Zusätzliche Kosten | keine zusätzlichen Anbieterkosten (Postfach und Catch-all prüfen Sie in Ihrem Hoststar-Tarif) | je nach Brevo-Tarif |
| Datenschutz | die Mails bleiben bei Ihrem Mailhoster, kein zusätzlicher Dienstleister | Brevo ist zusätzlicher Auftragsbearbeiter |
| Eingang | die Anwendung ruft das Postfach selbst ab (geplanter Abruf, im Takt von etwa einer Minute) | Brevo schickt jede Mail sofort an die Anwendung |
| Anhänge von Rechnungen | liegen in der Mail, kein Schlüssel nötig | werden mit einem Brevo-API-Schlüssel geladen |

**Empfohlen ist Variante A.** Variante B steht weiter unten.

---

## Variante A: Hoststar-Sammelpostfach (empfohlen, kein neuer Anbieter)

### Worum es geht

Sie legen bei Hoststar **ein** Postfach an, zum Beispiel `eingang@immoswiss.app`, und stellen für die Domain ein
**Catch-all** (Sammelkonto) darauf ein. Ein Catch-all bedeutet: Alle Mails an Adressen der Domain, die es **nicht
gibt**, landen in diesem Postfach. Bestehende Adressen wie `info@`, `reply@` oder `buchhaltung@` haben Vorrang und
funktionieren unverändert weiter.

Weil jede Verwaltung eine eigene, zufällige Adresse hat (`muster-k3x9a2b7qz@immoswiss.app`), die Sie nirgends einzeln
anlegen, ist das Catch-all genau das Richtige: Alles an unbekannte Adressen kommt in `eingang@`. Die Anwendung ruft
dieses eine Postfach regelmässig per IMAP ab, ordnet jede Mail über die **Empfängeradresse** der richtigen Verwaltung
zu und verarbeitet sie wie die Antworten und Rechnungen, die über Brevo kämen. Alles, was zu keiner Verwaltung passt
(zum Beispiel Spam an erfundene Adressen), ignoriert die Anwendung und löscht es nach 14 Tagen aus dem Postfach.

**Das Passwort des Postfachs tragen Sie ausschliesslich in die Datei `.env` auf dem Server ein.** Geben Sie es nie in
einem Chat, einer Mail oder einem Ticket weiter, auch nicht an uns oder an eine Assistenz. Es steht nirgends sonst
(nicht in der Datenbank).

Was Sie vorher wissen sollten:

* Das Postfach `eingang@` ist ein **Sammelbecken für fremde Post**. Tippfehler-Adressen (`ifno@immoswiss.app`) und
  Spam an erfundene Adressen landen jetzt dort, statt vom Server abgewiesen zu werden. Der Spamfilter von Hoststar
  arbeitet weiter; die Anwendung ignoriert alles Unpassende.
* Mails mehrerer Verwaltungen liegen bis zu 14 Tage in diesem einen Postfach. Nur Sie haben Zugriff darauf. Erwähnen
  Sie es in Ihrer Datenschutzerklärung bzw. im Auftragsbearbeitungsvertrag mit den Verwaltungen (Sie verarbeiten die
  Mails ohnehin in deren Auftrag; es kommt kein weiterer Dienstleister hinzu).
* Die Beschriftungen im Kundenbereich bei hoststar.ch können von den Namen unten abweichen. Als Vorlage dient die
  Hoststar-Anleitung <https://www.hoststar.at/de/support/mail/konfigurieren/catch-all>.

### Schritt 1: Postfach `eingang@immoswiss.app` anlegen

1. Melden Sie sich im **My Panel** von Hoststar an.
2. Öffnen Sie den Bereich **Mail** und wählen Sie, eine **neue E-Mail-Adresse hinzuzufügen**.
3. Adresse: `eingang@immoswiss.app`. Vergeben Sie ein **starkes Passwort** (mindestens 16 Zeichen, zufällig, nur für
   dieses Postfach; ein Passwortmanager hilft). Speichern Sie.
4. Notieren Sie das Passwort in Ihrem Passwortmanager. Sie brauchen es gleich für die `.env` (Schritt 4).

### Schritt 2: Catch-all auf dieses Postfach legen

1. My Panel, **Mail**, **Catch-all**.
2. **Catch-all E-Mail-Adresse hinzufügen**.
3. Domain: `immoswiss.app`. Empfänger: `eingang@immoswiss.app`.
4. Speichern.

Bestehende Adressen (`info@`, `reply@`, `buchhaltung@` …) bleiben unberührt, weil bei Hoststar vorhandene Adressen
Vorrang vor dem Catch-all haben. Prüfen Sie das im nächsten Schritt.

### Schritt 3: Test, dass der Sammelkonto-Weg funktioniert

1. Senden Sie aus einem **fremden** Postfach (zum Beispiel Ihrem privaten) eine Mail an
   `irgendwas-test@immoswiss.app` (eine Adresse, die es nicht gibt).
2. Öffnen Sie das Webmail von `eingang@immoswiss.app`. Die Mail muss nach kurzer Zeit dort liegen.
3. Senden Sie je eine Mail an `info@immoswiss.app`, `reply@immoswiss.app` und `buchhaltung@immoswiss.app`. Jede muss
   weiterhin in **ihrem** Postfach ankommen und **nicht** in `eingang@`.

Kommt die Testmail nicht an oder bekommt der Absender eine Fehlermeldung, ist das Catch-all nicht aktiv: siehe
Fehlersuche unten.

### Schritt 4: Zugangsdaten in die `.env` auf dem Server

Öffnen Sie auf dem Server (PythonAnywhere: Reiter *Files*) die Datei `.env` im Projektordner und ergänzen Sie:

```
PLATTFORM_IMAP_HOST=lx37.hoststar.hosting
PLATTFORM_IMAP_PORT=993
PLATTFORM_IMAP_BENUTZER=eingang@immoswiss.app
PLATTFORM_IMAP_PASSWORT=<das Passwort aus Schritt 1>
ANTWORT_DOMAIN=immoswiss.app
```

* `PLATTFORM_IMAP_HOST`: der Mailserver Ihres bisherigen Postfachs. Bestätigen Sie ihn im Hoststar-Kundenbereich oder
  im Webmail (Hilfe zu «Mailprogramm einrichten», Posteingangsserver/IMAP). `lx37.hoststar.hosting` ist der Wert,
  den die Anwendung bisher schon für Ihre anderen Postfächer verwendet.
* `PLATTFORM_IMAP_PORT`: 993 (verschlüsselt, IMAP über SSL). Das ist die Vorgabe, die Zeile darf auch fehlen.
* `PLATTFORM_IMAP_BENUTZER`: die **ganze** Adresse. Bei einigen Hostern ist der Benutzername etwas anderes als die
  Adresse; der Hoster nennt ihn bei den Mailprogramm-Einstellungen.
* `PLATTFORM_IMAP_PASSWORT`: das Passwort aus Schritt 1, ohne Anführungszeichen und ohne Leerzeichen am Ende.
* Optional `PLATTFORM_IMAP_ORDNER` (Vorgabe `INBOX`).
* `ANTWORT_DOMAIN=immoswiss.app` ist die Vorgabe und darf fehlen.

Laden Sie danach die Anwendung neu (PythonAnywhere: Reiter *Web*, Knopf *Reload*). Erst jetzt tragen Ticket-Mails die
Plattformadresse als Antwortadresse, denn die Anwendung verwendet sie, sobald **mindestens ein** Empfangsweg
eingerichtet ist. **Richten Sie den Abruf (Schritt 5) deshalb im selben Zug ein**, sonst gehen Antworten an eine
Adresse, aus der noch niemand liest. Sie gehen dabei nicht verloren (die Mails liegen im Postfach und werden beim
ersten Abruf nachgeholt), erscheinen aber verspätet.

Die `.env` darf nur für Ihr Serverkonto lesbar sein. Das Passwort steht nur hier.

### Schritt 5: Abruf einrichten

Der Befehl heisst:

```
python manage.py fetch_plattform_eingang --einmal
```

Er holt alle ungelesenen Mails des Postfachs, verarbeitet sie, markiert sie erst danach als gelesen und räumt alte,
bereits bearbeitete Mails auf. Fehlen die Angaben in der `.env`, meldet er das freundlich und beendet sich.

**Takt: so oft wie möglich, ideal jede Minute.** Je kürzer der Takt, desto schneller erscheint eine Antwort im Ticket
und eine Rechnung in den Kreditoren. Zwei Möglichkeiten bei PythonAnywhere:

* **Always-on-Task (jede Minute, empfohlen; braucht einen bezahlten Tarif):** Reiter *Tasks*, *Always-on tasks*.
  Ein einziger Befehl ohne Schleife in der Zeile (wie beim Ausrollen, siehe `docs/AUTOMATISIERUNG.md`):

  ```
  /home/<benutzer>/.virtualenvs/<venv>/bin/python /home/<benutzer>/<projektordner>/manage.py fetch_plattform_eingang --dauerlauf
  ```

  Die Schleife steckt im Befehl: ein Durchlauf alle 60 Sekunden. Ein Fehler in einem Durchlauf (zum Beispiel der
  Mailserver ist kurz nicht erreichbar) beendet die Schleife nicht; er steht in der Ausgabe und auf der Seite
  *E-Mail-Eingang*. Beim Beenden (Neustart durch PythonAnywhere) macht der Befehl den laufenden Durchlauf noch fertig.
  **Nach jeder Änderung der `.env` den Always-on-Task neu starten** (Knopf *Restart*; der Reload der Web-App
  genügt dafür nicht).
* **Scheduled Task:** Reiter *Tasks*, *Scheduled tasks*, derselbe Befehl mit `--einmal` statt `--dauerlauf`, im
  kürzesten Takt, den Ihr Tarif erlaubt (je nach Tarif stündlich, täglich oder häufiger; die Hilfe von PythonAnywhere
  nennt die aktuellen Möglichkeiten). Der Takt bestimmt, wie lange eine Antwort braucht.

Lassen Sie **nur eine** der beiden Formen laufen, nicht beide. Die bisherigen geplanten Aufgaben `fetch_replies`
und `fetch_rechnungen` bleiben unverändert (siehe «Ohne Konfiguration» im Anhang).

### Schritt 6: Test über die Anwendung

1. Melden Sie sich in der Anwendung an: *Einstellungen*, *E-Mail-Eingang*. Beide Karten zeigen «Empfang
   eingerichtet», darunter steht «Empfang über das Plattform-Postfach.». Als Inhaber sehen Sie ganz unten die Zeile
   «Plattform-Postfach zuletzt abgerufen: …». Nach dem ersten Lauf steht dort die Uhrzeit, und kein Fehler.
2. Kopieren Sie die Adresse bei «Eingehende Rechnungen».
3. Senden Sie von einem normalen Postfach eine Mail mit einem PDF oder Foto einer Rechnung an diese Adresse.
4. Nach dem nächsten Abruf (etwa eine Minute): *Kreditoren* zeigt eine neue Rechnung im Status «Neu», mit dem Hinweis
   «Per E-Mail von … · Betreff · eingegangen …». Auf der Seite *E-Mail-Eingang* steht unter «Letzter Eingang» der
   Zeitpunkt. Im Webmail von `eingang@` ist die Mail als gelesen markiert.
5. Antworten testen: Eine Ticket-Mail auslösen (Schaden-Ticket mit E-Mail des Melders) und darauf antworten; die
   Antwort erscheint nach dem nächsten Abruf im Ticket.

### Schritt 7: Fehlersuche

| Beobachtung | Wahrscheinliche Ursache | Was tun |
|---|---|---|
| Die Testmail an `irgendwas-test@immoswiss.app` kommt in `eingang@` nicht an, der Absender bekommt eine Fehlermeldung («Adresse nicht gefunden») | Catch-all fehlt oder ist auf die falsche Domain/den falschen Empfänger gestellt | Schritt 2 prüfen: Domain `immoswiss.app`, Empfänger `eingang@immoswiss.app`; mit dem Hoststar-Support klären, ob Catch-all für Ihr Paket freigeschaltet ist |
| Die Mail kommt in `eingang@` an, aber nicht in der Anwendung, und «Plattform-Postfach zuletzt abgerufen» ist leer oder alt | Der Abruf läuft nicht | Task prüfen (PythonAnywhere *Tasks*, Ausgabe/Log des Tasks); Befehl von Hand ausführen: `python manage.py fetch_plattform_eingang --einmal` und die Ausgabe lesen |
| Seite zeigt «Fehler: Anmeldung am Plattform-Postfach abgelehnt» | Benutzer oder Passwort in der `.env` falsch (oder nach der Änderung kein Neustart des Always-on-Tasks) | `PLATTFORM_IMAP_BENUTZER` (ganze Adresse) und `PLATTFORM_IMAP_PASSWORT` prüfen, im Webmail mit denselben Angaben anmelden, Task neu starten |
| Seite zeigt «Fehler: Keine Verbindung zum Plattform-Postfach» | Host oder Port falsch, der Server ist nicht erreichbar | `PLATTFORM_IMAP_HOST` und `_PORT` gegen die Angaben im Hoststar-Kundenbereich prüfen. Genaueres steht im Serverprotokoll (dort auch der Servername, auf der Seite aus Datenschutzgründen nicht) |
| Seite zeigt «Fehler: Der Ordner … wurde nicht gefunden» | `PLATTFORM_IMAP_ORDNER` falsch | Zeile entfernen (Vorgabe `INBOX`) |
| Abruf läuft ohne Fehler, die Mail ist danach «gelesen», aber es passiert nichts | Die Anwendung hat die Mail bewusst ignoriert: Adresse mit unbekannter oder abgelaufener Kennung (nach «Adresse erneuern» gilt die alte 30 Tage), Mail an mehrere Verwaltungen oder an beide Adressen derselben Verwaltung zugleich, Spam-Markierung des Hosters, Verwaltung im Lesemodus (Zahlung überfällig), Ticketnummer gehört nicht zur Verwaltung | Bewusst ohne Begründung nach aussen, damit niemand etwas über andere Verwaltungen erfährt. Prüfen, ob die Adresse aktuell ist (*E-Mail-Eingang*) |
| Rechnungsmail angekommen, aber keine Rechnung; im Logbuch «Rechnungsmail ohne Anhang abgerufen» | Kein PDF-/JPG-/PNG-Anhang, Anhang zu gross oder Dateiinhalt passt nicht zum Typ | Erlaubt sind PDF, JPG, PNG, höchstens 15 MB, höchstens 10 Anhänge je Mail; Bilder unter 20 KB gelten als Signaturlogo. Absender bitten, die Rechnung als PDF zu senden |
| Logbuch: «Eingegangene Mail nicht verarbeitet … nach 5 Versuchen aufgegeben» | Die Mail liess sich fünfmal nicht verarbeiten (zum Beispiel ein Fehler im Rechnungsscanner) | Serverprotokoll lesen (dort steht der Fehler); Absender um erneuten Versand bitten, nachdem die Ursache behoben ist |
| Im Sammelpostfach liegt viel Spam | Das Catch-all nimmt Post an erfundene Adressen an | Spamfilter von Hoststar im My Panel prüfen/verschärfen. Die Anwendung ignoriert Spam (Hoster-Markierung `X-Spam-Flag: YES`, `X-Spam-Status: Yes`) und alles, was zu keiner Verwaltung passt, und löscht es nach 14 Tagen |
| Das Postfach läuft voll | Der Abruf läuft nicht, oder das Kontingent ist klein | Abruf prüfen (ohne Abruf wird nichts aufgeräumt); Kontingent im My Panel erhöhen |
| Antworten kommen im Ticket nicht an, Rechnungen aber schon | Die Verwaltung hat ein eigenes Antwort-Postfach, das gilt vor der Plattformadresse | Unter *E-Mail-Eingang, Erweitert* das Postfach abschalten oder löschen |
| Das Passwort wurde geändert | Anmeldung abgelehnt | Neues Passwort in die `.env`, Task neu starten |

### Schritt 8: Rückweg

1. Always-on-/Scheduled Task stoppen.
2. In der `.env` die Zeilen `PLATTFORM_IMAP_*` entfernen und die Anwendung neu laden. Ist auch Brevo nicht
   eingerichtet, tragen Ticket-Mails danach wieder die bisherige Antwortadresse.
3. Optional das Catch-all im My Panel löschen und das Postfach `eingang@` entfernen.

Antworten, die schon an Plattformadressen unterwegs sind, gehen verloren, sobald das Catch-all weg ist. Lassen Sie es
darum noch einige Tage bestehen. Ungelesene Mails im Postfach bleiben ungelesen und werden nachgeholt, wenn Sie den
Abruf später wieder einschalten.

### Anhang zu Variante A: wie die Anwendung die Mails behandelt (für die Technik)

* **Welche Adresse zählt.** Ein Catch-all leitet lokal weiter; welche Kopfzeile den ursprünglichen Empfänger behält,
  hängt vom Hoster ab. Die Anwendung sammelt deshalb alle Kandidaten aus `Delivered-To`, `X-Original-To`,
  `Envelope-To`, `X-Envelope-To`, `To`, `Cc` und `Resent-To`, schreibt sie klein und behält nur Adressen auf der
  `ANTWORT_DOMAIN`. Jede wird über die vorhandene Zuordnung (`zuordnung_zu_adresse`: Kennung, bisherige Kennung im
  30-Tage-Fenster, Zweck antworten oder rechnungen) einer Verwaltung zugeordnet. Führen die Adressen zu mehr als einer
  Verwaltung oder zu beiden Zwecken, wird die Mail verworfen. Findet sich keine, wird sie ignoriert.
* **Verarbeitung.** Dieselbe wie beim Webhook: `eingehende_antwort_verarbeiten` für Antworten, `anhang_importieren`
  für Rechnungen. Die Anhänge werden direkt aus der Mail gelesen: PDF, JPG, PNG, Dateikopf muss zum Typ passen,
  höchstens 15 MB und 10 Anhänge, Signaturlogos zählen nicht (`rechnungseingang.anhaenge_aus_mail`).
* **Gelesen erst nach Erfolg.** Geholt wird mit `BODY.PEEK`, `\Seen` wird erst nach erfolgreicher Verarbeitung (oder
  bewusstem Ignorieren) gesetzt. Schlägt eine Mail fehl, bleibt sie ungelesen, und der nächste Lauf versucht es noch
  einmal.
* **Poison-Schutz.** Die Tabelle `core_plattformmail` zählt Fehlversuche je Mail. Nach 5 Versuchen gilt die Mail als
  erledigt (`aufgegeben`): Serverprotokoll und, wenn die Verwaltung feststand, ein Logbucheintrag bei ihr.
* **Doppelte.** Dieselbe Message-ID wird je Verwaltung nur einmal verarbeitet (`tickets_eingegangenemail`, gemeinsam
  mit dem Brevo-Weg).
* **Grösse.** Mails über 25 MB werden nicht geladen, sondern ignoriert. Höchstens 100 Mails und 4 Minuten je Lauf; der
  Rest kommt beim nächsten Lauf.
* **Aufräumen.** Gelöscht (`\Deleted` plus `EXPUNGE`) wird eine Mail erst, wenn sie gelesen ist, älter als 14 Tage
  und in `core_plattformmail` als erledigt vermerkt ist, und der Vermerk ebenfalls älter als 14 Tage. Was die Anwendung
  nie angefasst hat (zum Beispiel im Webmail von Hand gelesene Mails), bleibt liegen. Ein `EXPUNGE` entfernt auch
  alles, was Sie im Webmail selbst zum Löschen markiert haben.
* **Status.** Zeitpunkt und letzter Fehler des Abrufs stehen in `core_plattformeingangstatus` und, für den Inhaber, auf
  der Seite *E-Mail-Eingang*. Die Fehlertexte enthalten weder Servernamen noch Benutzer.

---

## Variante B: Brevo (Inbound Parsing)

Die folgende Anleitung gilt für den Weg über Brevo. Sie ist unverändert gültig, wird aber nur gebraucht, wenn Sie
Variante A nicht einsetzen wollen. Setzen Sie dann `ANTWORT_DOMAIN` auf die Brevo-Empfangsdomain
(`antwort.immoswiss.app`), **nicht** auf `immoswiss.app`.

### Worum es geht

Bisher musste jede Verwaltung ein eigenes Postfach mit Benutzername und Passwort bei uns hinterlegen. Das ist
mühsam, weil sich Passwörter ändern. Neu bekommt **jede Verwaltung automatisch zwei Adressen** bei uns:

| Zweck | Adresse (Beispiel) | Was damit passiert |
|---|---|---|
| Antworten auf Tickets | `muster-k3x9a2b7qz@antwort.immoswiss.app` | Ticket-Mails tragen sie als «Antwort an». Antworten von Mietern und Handwerkern erscheinen im Ticket und im Chat. |
| Eingehende Rechnungen | `muster-k3x9a2b7qz-rechnungen@antwort.immoswiss.app` | Aus jedem PDF- oder Bild-Anhang entsteht eine Kreditorenrechnung (Status «Neu»), wie beim Hochladen im Kreditoren-Scanner. |

Die Adressen stehen in der Anwendung unter **Einstellungen, E-Mail-Eingang** und lassen sich dort kopieren. Wer sein
eigenes Postfach behalten will, richtet im Mailprogramm eine **Weiterleitung** auf die Rechnungsadresse ein und
hinterlegt keine Zugangsdaten. Das alte Verfahren (eigenes Postfach per IMAP) bleibt als Sonderfall unter
«Erweitert» erhalten.

Damit das funktioniert, nimmt Brevo (ein Dienst für E-Mail-Empfang und -Versand; den Versand der Plattform erledigt
weiterhin Ihr bisheriger Mailanbieter, Brevo wird hier nur für den EMPFANG gebraucht) für eine eigene Empfangsadresse
alle Mails entgegen und schickt sie uns. Dafür richten Sie jetzt einmalig Folgendes ein.

**Zwei Dinge vorab, die Sie entscheiden müssen:**

* **Kosten.** Prüfen Sie bei Brevo, ob Ihr Tarif das «Inbound Parsing» (Empfang eingehender Mails) enthält und was es
  kostet. Das ist Ihre Entscheidung; die Anwendung löst keine Kosten von sich aus aus.
* **Datenschutz.** Rechnungen der Verwaltungen (Namen, IBAN, Beträge) laufen kurz über Brevo, bevor wir sie abholen.
  Brevo ist ein zusätzlicher Dienstleister (Auftragsbearbeiter): schliessen Sie den Auftragsbearbeitungsvertrag mit
  Brevo ab bzw. prüfen Sie, dass er das Empfangen abdeckt, und nennen Sie Brevo in der Datenschutzerklärung.

### Was Sie am Ende haben

* eine Empfangsdomain `antwort.immoswiss.app` (**nicht** `immoswiss.app` selbst: dort empfängt Hoststar Ihre
  Büro-Post, und die bleibt unangetastet),
* einen API-Schlüssel von Brevo (damit wir Anhänge herunterladen dürfen),
* ein Geheimwort (`BREVO_WEBHOOK_SECRET`), mit dem sich Brevo bei uns ausweist,
* einen Webhook bei Brevo, der eingehende Mails an die Anwendung schickt.

### Schritt für Schritt

Halten Sie einen Notizzettel bereit: Sie erzeugen zwei geheime Werte (API-Schlüssel, Geheimwort) und brauchen sie
mehrmals.

#### Schritt 1: Brevo-Konto

Falls Sie noch kein Konto haben, legen Sie unter <https://www.brevo.com> eines an (die Anmeldung läuft über
<https://app.brevo.com>). Prüfen Sie dort Ihren Tarif auf «Inbound Parsing» bzw. «Eingehende E-Mails» (siehe «Kosten»
oben). Der Versand der Plattform bleibt bei Ihrem bisherigen Mailanbieter; Brevo empfängt nur.

#### Schritt 2: Empfangsdomain bei Brevo hinzufügen

1. Suchen Sie in Brevo den Bereich für **Domains** (je nach Version unter *Senders, Domains & Dedicated IPs*,
   *Domains* oder in den Kontoeinstellungen; Brevo benennt Menüs gelegentlich um, die Suchfunktion oben hilft).
2. Fügen Sie die Domain `antwort.immoswiss.app` hinzu und lassen Sie sie verifizieren. Brevo zeigt Ihnen danach die
   DNS-Einträge, die es erwartet.
3. Lassen Sie das Fenster offen oder notieren Sie die Einträge. Mindestens diese brauchen Sie:
   * zwei **MX-Einträge** (siehe Schritt 3) und
   * falls Brevo es verlangt, einen **TXT-Eintrag** zur Bestätigung der Domain. Kopieren Sie ihn genau so, wie
     Brevo ihn zeigt.

Wichtig: Die Empfangsdomain muss sich von der Domain unterscheiden, von der Sie versenden. Darum eine
Unterdomain (`antwort.…`) und nicht `immoswiss.app`.

#### Schritt 3: DNS-Einträge setzen

Die Einträge setzen Sie dort, wo die Domain `immoswiss.app` verwaltet wird (die «DNS-Zone»). Das ist der Anbieter,
bei dem Sie die Domain registriert haben oder der die Namensserver stellt, vermutlich **Hoststar**. Im Kundenbereich
heisst der Bereich meist *Domains, DNS* oder *DNS-Verwaltung*. Wenn Sie ihn nicht finden, fragen Sie den
Hoststar-Support: «Ich möchte für die Unterdomain antwort.immoswiss.app zwei MX-Einträge setzen.»

Legen Sie an:

| Typ | Name / Host | Priorität | Wert / Ziel |
|---|---|---|---|
| MX | `antwort` | 10 | `inbound1.sendinblue.com.` |
| MX | `antwort` | 20 | `inbound2.sendinblue.com.` |
| TXT | wie von Brevo angezeigt | – | wie von Brevo angezeigt (nur falls verlangt) |

Hinweise:

* Der Punkt am Ende von `inbound1.sendinblue.com.` gehört zum Eintrag. Manche Oberflächen ergänzen ihn selbst;
  dann lassen Sie ihn weg.
* «Name» ist nur `antwort`, nicht der volle Name (viele Oberflächen hängen `.immoswiss.app` selbst an).
* **Fassen Sie die bestehenden MX-Einträge von `immoswiss.app` nicht an.** Sie gehören zu Ihrer Büro-Post bei
  Hoststar.
* Es dauert, bis die Einträge überall bekannt sind (Minuten bis einige Stunden). Prüfen Sie mit einem
  MX-Prüfdienst im Internet (Suchbegriff «MX lookup») für `antwort.immoswiss.app`; er muss die beiden Brevo-Ziele
  nennen. Gehen Sie erst weiter, wenn das so ist und Brevo die Domain als verifiziert zeigt.

#### Schritt 4: API-Schlüssel erstellen (`BREVO_API_KEY`)

In Brevo unter dem Kontomenü (Ihr Name oben rechts), *SMTP & API* bzw. *API Keys*: neuen Schlüssel erzeugen (Name
zum Beispiel «immoswiss Anhänge»), kopieren, notieren. Brevo zeigt ihn nur einmal. Dieser Schlüssel erlaubt der
Anwendung, Anhänge eingehender Mails abzuholen. Behandeln Sie ihn wie ein Passwort.

#### Schritt 5: Geheimwort erzeugen (`BREVO_WEBHOOK_SECRET`)

Auf Ihrem Rechner mit Python (oder in der Konsole auf dem Server):

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

Die ausgegebene Zeichenfolge ist das Geheimwort. Notieren Sie es. Es besteht nur aus Buchstaben, Ziffern, `-` und
`_` und lässt sich darum ohne Umkodierung in eine Internetadresse einsetzen.

#### Schritt 6: Umgebungsvariablen auf dem Server (ohne Geheimwort!)

Öffnen Sie auf dem Server (PythonAnywhere: Reiter *Files*) die Datei `.env` im Projektordner und ergänzen Sie:

```
ANTWORT_DOMAIN=antwort.immoswiss.app
BREVO_API_KEY=<der Schlüssel aus Schritt 4>
```

**Noch nicht** `BREVO_WEBHOOK_SECRET` eintragen: Das kommt zuletzt (Schritt 9). Laden Sie die Anwendung neu
(PythonAnywhere: Reiter *Web*, Knopf *Reload*).

`IMAP_SCHLUESSEL` steht schon in der `.env`. Er betrifft nur die eigenen Postfächer unter «Erweitert». Ändern oder
entfernen Sie ihn nicht, sonst werden die dort hinterlegten Passwörter unlesbar (die Anwendung zeigt das dann an,
und die Plattformadresse springt ein).

#### Schritt 7: Webhook bei Brevo registrieren

Der Webhook sagt Brevo: «Schick alle Mails an `*@antwort.immoswiss.app` an diese Internetadresse.» Sie führen den
Befehl einmal aus (in einer Konsole mit `curl`; unter Windows PowerShell siehe Hinweis darunter). Ersetzen Sie die
drei Platzhalter in Spitzklammern:

```bash
curl -sS -X POST "https://api.brevo.com/v3/webhooks" \
  -H "api-key: <BREVO_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
        "type": "inbound",
        "events": ["inboundEmailProcessed"],
        "domain": "antwort.immoswiss.app",
        "url": "https://<IHRE-INSTANZ>/webhooks/brevo/inbound/?token=<BREVO_WEBHOOK_SECRET>",
        "description": "immoswiss E-Mail-Eingang"
      }'
```

* `<BREVO_API_KEY>`: Schlüssel aus Schritt 4.
* `<IHRE-INSTANZ>`: die Adresse Ihrer Anwendung ohne `https://` (zum Beispiel `app.immoswiss.app`).
* `<BREVO_WEBHOOK_SECRET>`: das Geheimwort aus Schritt 5.

Brevo antwortet mit einer Nummer (`{"id": 123}`). Das heisst: registriert. Notieren Sie die Nummer (für den Rückweg).

Hinweis Windows PowerShell: Dort heisst `curl` etwas anderes. Nutzen Sie `curl.exe` mit denselben Angaben oder die
Konsole auf dem Server.

Dass Brevo das Geheimwort in der Internetadresse trägt, ist so gewollt: Brevo kann keine Signatur mitschicken, und
die Anwendung prüft dieses Wort bei jedem Aufruf (ohne gültiges Wort: Fehler 403, es wird nichts gespeichert).

#### Schritt 8: Kurz prüfen, dass noch nichts passiert

Bis jetzt ist im Betrieb nichts anders: Ticket-Mails tragen weiter die bisherige Antwortadresse, weil das Geheimwort
auf dem Server noch fehlt. Das ist Absicht (siehe nächster Schritt).

#### Schritt 9: Geheimwort eintragen (ZULETZT) und neu laden

Ergänzen Sie in der `.env`:

```
BREVO_WEBHOOK_SECRET=<das Geheimwort aus Schritt 5>
```

Dann *Reload* (PythonAnywhere: Reiter *Web*).

**Warum zuletzt?** Solange das Geheimwort fehlt, lässt die Anwendung die Ticket-Mails unverändert und weist den Webhook
ab (403). Erst mit dem Geheimwort tragen Ticket-Mails die neue Antwortadresse und der Webhook nimmt Mails an. Hätten
Sie es früher gesetzt, könnten Antworten an eine Adresse gehen, die noch nichts empfängt, und gingen verloren.

#### Schritt 10: Test

**Rechnungen.**

1. Melden Sie sich in der Anwendung an und öffnen Sie *Einstellungen, E-Mail-Eingang*. Beide Karten sollten
   «Empfang eingerichtet» zeigen. (Steht bei den Rechnungen «Anhänge lassen sich nicht laden», fehlt
   `BREVO_API_KEY`.)
2. Kopieren Sie die Adresse bei «Eingehende Rechnungen».
3. Senden Sie von einem normalen Postfach eine Mail mit einem PDF oder Foto einer Rechnung an diese Adresse.
4. Nach etwa einer Minute: *Kreditoren* zeigt eine neue Rechnung im Status «Neu». In der Spalte der Hinweise steht
   «Per E-Mail von … · Betreff · eingegangen …». Auf der Seite *E-Mail-Eingang* steht unter «Letzter Eingang» der
   Zeitpunkt.

**Antworten.**

1. Lösen Sie in der Anwendung eine Ticket-Mail aus (zum Beispiel ein Schaden-Ticket mit E-Mail des Melders).
2. Antworten Sie auf diese Mail. Die Antwort erscheint nach etwa einer Minute im Ticket.

**Wo sehen Sie, was passiert ist?**

* Anwendung: *Kreditoren* (Rechnungen), das Ticket selbst (Antworten), *Logbuch* (Einträge «Rechnung per E-Mail
  eingegangen» und «Rechnungsmail ohne Anhang abgerufen»), *E-Mail-Eingang* (letzter Eingang).
* Server: das Fehlerprotokoll der Anwendung (PythonAnywhere: Reiter *Web*, *Error log*).
* Brevo: im Bereich der Webhooks bzw. der eingehenden Mails zeigt Brevo, was es zugestellt hat und ob die
  Anwendung mit Fehler geantwortet hat (Menüname je nach Version).

#### Fehlersuche

| Beobachtung | Wahrscheinliche Ursache | Was tun |
|---|---|---|
| Mail kommt gar nicht an (nichts bei «Letzter Eingang», nichts in Brevo) | MX-Einträge fehlen, falsch oder noch nicht überall bekannt | MX-Prüfdienst für `antwort.immoswiss.app`; Name `antwort` (nicht der volle Name) prüfen; ein paar Stunden warten |
| Absender bekommt eine Fehlermeldung «Domain nicht gefunden / nicht zustellbar» | gleiche Ursache, oder die Domain ist bei Brevo nicht verifiziert | Schritt 2 und 3 prüfen; TXT-Eintrag von Brevo gesetzt? |
| Brevo zeigt die Mail, die Anwendung nichts. Brevo meldet Fehler **403** | `BREVO_WEBHOOK_SECRET` in der `.env` und das Wort in der Webhook-Adresse stimmen nicht überein, oder nach dem Eintragen wurde nicht neu geladen | Beide Werte vergleichen (kein Leerzeichen, keine Anführungszeichen); *Reload* |
| Brevo meldet **500** oder Zeitüberschreitung | Fehler in der Anwendung | Fehlerprotokoll des Servers lesen; Brevo wiederholt automatisch, nichts doppelt gespeichert |
| Rechnungsmail kommt an, aber **keine Rechnung**, im Logbuch «Rechnungsmail ohne Anhang abgerufen» mit «Brevo-API-Schlüssel fehlt» | `BREVO_API_KEY` fehlt in der `.env` oder kein Reload | Schritt 6; danach den Absender bitten, die Rechnung noch einmal zu senden (die Mail selbst wird nicht nachgeholt) |
| Dasselbe, aber im Logbuch steht «Brevo antwortet mit 401/403» | API-Schlüssel falsch oder widerrufen | Neuen Schlüssel erzeugen (Schritt 4) |
| Dasselbe, aber «404» | Anhang bei Brevo nicht mehr vorhanden oder Brevo hat die Schnittstelle geändert | Absender erneut senden lassen. Tritt es bei jeder Mail auf: melden Sie es uns; der Pfad zum Anhang-Abruf steht in `core/services/rechnungseingang.py` (`BREVO_ANHANG_URL`) |
| Logbuch: «Kein PDF- oder Bild-Anhang gefunden» | die Mail hatte nur Text, einen anderen Dateityp oder nur Signaturbilder | Erlaubt sind PDF, JPG, PNG, höchstens 15 MB, höchstens 10 Anhänge je Mail; Bilder unter 20 KB gelten als Signaturlogo |
| Antworten kommen im Ticket nicht an, Rechnungen aber schon | Die Verwaltung hat ein eigenes Antwort-Postfach, das gilt vor der Plattformadresse | Unter *E-Mail-Eingang, Erweitert* Postfach abschalten oder löschen |
| Gmail-Weiterleitung lässt sich nicht bestätigen | Gmail schickt einen Bestätigungscode an die Rechnungsadresse | Der Code steht meist im Betreff dieser Mail; die Mail steht im Logbuch unter «Rechnungsmail ohne Anhang abgerufen» |
| Mail wird nicht verarbeitet, Brevo meldet «ok» (Antwort `ignored`) | Adresse mit unbekannter oder abgelaufener Kennung, Mail an mehrere Verwaltungen oder beide Adressen derselben Verwaltung zugleich, Verwaltung im Lesemodus | Bewusst ohne Begründung, damit niemand etwas über andere Verwaltungen erfährt. Prüfen, ob die Adresse aktuell ist (*E-Mail-Eingang*) |
| Antwort `spam` | Brevo bewertet die Mail mit Spam-Wert 8 oder höher | In der Regel richtig. Bei echten Rechnungen den Absender bitten, die Mail neu zu formulieren |

#### Rückweg

Wenn etwas schiefgeht und Sie zum alten Zustand zurück wollen:

1. In der `.env` die Zeile `BREVO_WEBHOOK_SECRET=…` entfernen (oder auskommentieren) und *Reload*. Ab sofort tragen
   Ticket-Mails wieder die bisherige Antwortadresse, und der Webhook weist alles ab.
2. Optional bei Brevo den Webhook löschen: Liste mit
   `curl -sS "https://api.brevo.com/v3/webhooks?type=inbound" -H "api-key: <BREVO_API_KEY>"`,
   löschen mit `curl -sS -X DELETE "https://api.brevo.com/v3/webhooks/<NUMMER>" -H "api-key: <BREVO_API_KEY>"`.
3. Optional die beiden MX-Einträge von `antwort` beim DNS-Anbieter entfernen.

Die Verwaltungen verlieren dabei nichts: Bereits angelegte Rechnungen und Ticket-Antworten bleiben. Mails, die
zwischen Schritt 1 und der Wiederherstellung an die Plattformadressen gehen, werden nicht abgeholt. Sagen Sie den
Verwaltungen, die eine Weiterleitung eingerichtet haben, dass sie sie vorübergehend ausschalten sollen. Eigene
Postfächer unter «Erweitert» sind vom Rückweg nicht betroffen.

### Anhang: wie die Anwendung die Mails behandelt (für die Technik)

#### Adressen und Zuordnung

* Jede Verwaltung hat eine zufällige **Kennung** (`Organisation.antwort_kennung`, Präfix aus dem Firmennamen plus
  10 Zufallszeichen). Antwortadresse `<kennung>@<ANTWORT_DOMAIN>`, Rechnungsadresse
  `<kennung>-rechnungen@<ANTWORT_DOMAIN>`. Der Zusatz `-rechnungen` ist öffentlich, der nicht erratbare Teil ist die
  Kennung. Eine Kennung kann nie auf `-rechnungen` enden, damit die beiden Adressformen nicht verwechselt werden.
* Der Webhook ordnet über die **Empfängeradresse** (`Recipients`, sonst `To`) Verwaltung und Zweck zu. Unbekannte
  Kennung auf der Antwortdomain: verworfen (`ignored`), nicht über die Ticketnummer geraten. Mail an mehrere
  Verwaltungen oder an beide Adressen derselben Verwaltung: verworfen.
* **Adresse erneuern** (nur Inhaber, Einstellungen): neue Kennung für beide Adressen; die bisherige gilt 30 Tage
  weiter, auch für Rechnungen. Danach müssen Weiterleitungen auf die neue Rechnungsadresse umgestellt werden.
* Gleiche `MessageId` wird je Verwaltung nur einmal verarbeitet (Tabelle `tickets_eingegangenemail`, speichert nur
  die ID, den Zweck und den Zeitpunkt).

#### Antworten

Es wird nur Text gespeichert (`ExtractedMarkdownMessage`, sonst `RawTextBody` ohne Zitat); HTML wird nie
ungefiltert übernommen, Anhänge von Antworten werden ignoriert. Hat eine Verwaltung ein eigenes, aktives Antwort-
Postfach und lassen sich dessen Zugangsdaten lesen, gilt weiter dieses als «Antwort an»; sonst gilt (bei gesetztem
`BREVO_WEBHOOK_SECRET`) die Plattformadresse. Ein Postfach, dessen Zugangsdaten sich nicht entschlüsseln lassen
(`IMAP_SCHLUESSEL` gewechselt), gilt nicht als aktiv; die Seite *E-Mail-Eingang* weist darauf hin («Neu eingeben»
oder «Löschen»).

#### Rechnungen

Pro Mail an die Rechnungsadresse (`core/services/rechnungseingang.py`):

* **Spam:** `Spam.Score` ab 8 wird nicht verarbeitet (nur im Serverprotokoll).
* **Anhänge:** nur PDF, JPG, PNG; Typ **und** Dateikopf müssen übereinstimmen; höchstens 15 MB; höchstens 10 je
  Mail; Bilder unter 20 KB und Inline-Bilder ohne Dateiendung (Signaturlogos) zählen nicht.
* **Download:** von `https://api.brevo.com/v3/inbound/attachments/<Token>` mit dem Schlüssel, Zeitlimit, Umleitungen
  nur innerhalb von `api.brevo.com`. Der Pfad stammt aus der Brevo-Dokumentation und wurde in dieser Fassung nicht
  gegen das echte Brevo getestet: Prüfen Sie mit der ersten Test-Rechnung (Schritt 10).
* **Verarbeitung:** dieselbe wie beim Hochladen und beim IMAP-Abruf (`core.services.belegimport.anhang_importieren`:
  Beleg speichern, KI-Scanner, Kreditorenrechnung «Neu», Logbucheintrag). Herkunft: «Per E-Mail von Absender ·
  Betreff · eingegangen Datum».
* **Ohne `BREVO_API_KEY`:** Antwort 200 (ein Fehler brächte Brevo zum Wiederholen, was ohne Schlüssel nichts nützt);
  im Logbuch der Verwaltung steht «Rechnungsmail ohne Anhang abgerufen» mit Absender und Betreff, damit der Eingang
  nicht still verschwindet.
* **Vorübergehende Fehler** beim Herunterladen (Netz, Zeitüberschreitung, 5xx): Antwort 500, Brevo wiederholt; es
  entsteht nichts doppelt, weil alles in einer Transaktion läuft.

#### Umgebungsvariablen

| Variable | Bedeutung |
|---|---|
| `ANTWORT_DOMAIN` | Domain der Plattformadressen. Variante A: `immoswiss.app` (Vorgabe). Variante B: `antwort.immoswiss.app`. |
| `BREVO_WEBHOOK_SECRET` | Geheimwort des Webhooks. Ohne Wert: Webhook gesperrt (403) und Ticket-Mails bleiben beim bisherigen Reply-To. |
| `BREVO_API_KEY` | Brevo-Schlüssel zum Laden der Anhänge. Ohne Wert kommen Rechnungsmails ohne Anhang an (Logbuch). |
| `IMAP_SCHLUESSEL` | nur für eigene Postfächer («Erweitert»). |
| `PLATTFORM_IMAP_HOST`, `_PORT` (993), `_BENUTZER`, `_PASSWORT`, `_ORDNER` (`INBOX`) | Variante A: Zugang zum Sammelpostfach. Nur in der `.env`, nie in der Datenbank. Eingerichtet, wenn Host, Benutzer und Passwort gesetzt sind. |

#### Test ohne Brevo (curl)

Eine Rechnungsmail ohne Anhang prüft Zuordnung und Geheimwort; mit Anhang braucht es einen echten Token von Brevo.

```bash
curl -sS -X POST "https://<IHRE-INSTANZ>/webhooks/brevo/inbound/" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $BREVO_WEBHOOK_SECRET" \
  -d '{"items": [{
        "MessageId": "<test-0001@example.ch>",
        "From": {"Name": "Hans Muster", "Address": "hans@example.ch"},
        "To": [{"Address": "muster-k3x9a2b7qz@antwort.immoswiss.app"}],
        "Subject": "Re: Wasserhahn tropft (Ticket #12)",
        "ExtractedMarkdownMessage": "Der Handwerker kann am Dienstag.",
        "RawTextBody": "Der Handwerker kann am Dienstag.",
        "Headers": {}
      }]}'
```

Antworten: `{"status": "ok, saved"}` (im Ticket abgelegt), `{"status": "ok, chat"}` (Chat zwischen Mieter und Handwerker),
`{"status": "ok, 1 invoice(s)"}` (Rechnung angelegt), `{"status": "no attachment"}`, `{"status": "attachments not
loaded"}`, `{"status": "spam"}`, `{"status": "duplicate"}`, `{"status": "ignored"}`. Fehlendes oder falsches
Geheimwort ergibt 403.

#### Ohne Konfiguration

* Kein `BREVO_WEBHOOK_SECRET` und kein vollständiges `PLATTFORM_IMAP_*`: Webhook gesperrt (403), Reply-To wie
  bisher (eigenes Postfach, sonst E-Mail der Verwaltung, sonst `reply@immoswiss.app`). Die Seite *E-Mail-Eingang* zeigt
  «Empfang noch nicht eingerichtet». Es genügt ein Weg (Variante A oder B), damit die Plattformadresse gilt.
* MX nicht gesetzt: Mails an die Plattformadressen kommen nicht an. Erst MX und Webhook einrichten, dann das
  Geheimwort setzen.
* Lassen Sie den Dienst `fetch_replies` (`python manage.py fetch_replies --einmal` als geplante Aufgabe) und den
  Rechnungsabruf `fetch_rechnungen` weiterlaufen. Beide holen Mails aus eigenen Postfächern (nur Verwaltungen
  unter «Erweitert»); `fetch_replies` stellt ausserdem gebündelte Chat-Nachrichten zu, auch für Verwaltungen
  ohne eigenes Postfach. Für alle anderen holt `fetch_rechnungen` nichts.
