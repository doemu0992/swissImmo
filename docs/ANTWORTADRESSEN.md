# E-Mail-Eingang der Plattform einrichten (Anleitung für den Betreiber)

Stand 4.11.2026. Diese Anleitung ist für Sie als Betreiber der Plattform, nicht für die Verwaltungen. Sie brauchen
keine Programmierkenntnisse; Sie klicken bei Brevo, tragen ein paar Zeilen beim Anbieter Ihrer Domain ein und
ergänzen eine Textdatei auf dem Server.

## Worum es geht

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

## Was Sie am Ende haben

* eine Empfangsdomain `antwort.immoswiss.app` (**nicht** `immoswiss.app` selbst: dort empfängt Hoststar Ihre
  Büro-Post, und die bleibt unangetastet),
* einen API-Schlüssel von Brevo (damit wir Anhänge herunterladen dürfen),
* ein Geheimwort (`BREVO_WEBHOOK_SECRET`), mit dem sich Brevo bei uns ausweist,
* einen Webhook bei Brevo, der eingehende Mails an die Anwendung schickt.

## Schritt für Schritt

Halten Sie einen Notizzettel bereit: Sie erzeugen zwei geheime Werte (API-Schlüssel, Geheimwort) und brauchen sie
mehrmals.

### Schritt 1: Brevo-Konto

Falls Sie noch kein Konto haben, legen Sie unter <https://www.brevo.com> eines an (die Anmeldung läuft über
<https://app.brevo.com>). Prüfen Sie dort Ihren Tarif auf «Inbound Parsing» bzw. «Eingehende E-Mails» (siehe «Kosten»
oben). Der Versand der Plattform bleibt bei Ihrem bisherigen Mailanbieter; Brevo empfängt nur.

### Schritt 2: Empfangsdomain bei Brevo hinzufügen

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

### Schritt 3: DNS-Einträge setzen

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

### Schritt 4: API-Schlüssel erstellen (`BREVO_API_KEY`)

In Brevo unter dem Kontomenü (Ihr Name oben rechts), *SMTP & API* bzw. *API Keys*: neuen Schlüssel erzeugen (Name
zum Beispiel «immoswiss Anhänge»), kopieren, notieren. Brevo zeigt ihn nur einmal. Dieser Schlüssel erlaubt der
Anwendung, Anhänge eingehender Mails abzuholen. Behandeln Sie ihn wie ein Passwort.

### Schritt 5: Geheimwort erzeugen (`BREVO_WEBHOOK_SECRET`)

Auf Ihrem Rechner mit Python (oder in der Konsole auf dem Server):

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

Die ausgegebene Zeichenfolge ist das Geheimwort. Notieren Sie es. Es besteht nur aus Buchstaben, Ziffern, `-` und
`_` und lässt sich darum ohne Umkodierung in eine Internetadresse einsetzen.

### Schritt 6: Umgebungsvariablen auf dem Server (ohne Geheimwort!)

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

### Schritt 7: Webhook bei Brevo registrieren

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

### Schritt 8: Kurz prüfen, dass noch nichts passiert

Bis jetzt ist im Betrieb nichts anders: Ticket-Mails tragen weiter die bisherige Antwortadresse, weil das Geheimwort
auf dem Server noch fehlt. Das ist Absicht (siehe nächster Schritt).

### Schritt 9: Geheimwort eintragen (ZULETZT) und neu laden

Ergänzen Sie in der `.env`:

```
BREVO_WEBHOOK_SECRET=<das Geheimwort aus Schritt 5>
```

Dann *Reload* (PythonAnywhere: Reiter *Web*).

**Warum zuletzt?** Solange das Geheimwort fehlt, lässt die Anwendung die Ticket-Mails unverändert und weist den Webhook
ab (403). Erst mit dem Geheimwort tragen Ticket-Mails die neue Antwortadresse und der Webhook nimmt Mails an. Hätten
Sie es früher gesetzt, könnten Antworten an eine Adresse gehen, die noch nichts empfängt, und gingen verloren.

### Schritt 10: Test

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

### Fehlersuche

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

### Rückweg

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

## Anhang: wie die Anwendung die Mails behandelt (für die Technik)

### Adressen und Zuordnung

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

### Antworten

Es wird nur Text gespeichert (`ExtractedMarkdownMessage`, sonst `RawTextBody` ohne Zitat); HTML wird nie
ungefiltert übernommen, Anhänge von Antworten werden ignoriert. Hat eine Verwaltung ein eigenes, aktives Antwort-
Postfach und lassen sich dessen Zugangsdaten lesen, gilt weiter dieses als «Antwort an»; sonst gilt (bei gesetztem
`BREVO_WEBHOOK_SECRET`) die Plattformadresse. Ein Postfach, dessen Zugangsdaten sich nicht entschlüsseln lassen
(`IMAP_SCHLUESSEL` gewechselt), gilt nicht als aktiv; die Seite *E-Mail-Eingang* weist darauf hin («Neu eingeben»
oder «Löschen»).

### Rechnungen

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

### Umgebungsvariablen

| Variable | Bedeutung |
|---|---|
| `ANTWORT_DOMAIN` | Domain der Plattformadressen, zum Beispiel `antwort.immoswiss.app`. Vorgabe `immoswiss.app`. |
| `BREVO_WEBHOOK_SECRET` | Geheimwort des Webhooks. Ohne Wert: Webhook gesperrt (403) und Ticket-Mails bleiben beim bisherigen Reply-To. |
| `BREVO_API_KEY` | Brevo-Schlüssel zum Laden der Anhänge. Ohne Wert kommen Rechnungsmails ohne Anhang an (Logbuch). |
| `IMAP_SCHLUESSEL` | nur für eigene Postfächer («Erweitert»). |

### Test ohne Brevo (curl)

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

### Ohne Konfiguration

* Kein `BREVO_WEBHOOK_SECRET`: Webhook gesperrt (403), Reply-To wie bisher (eigenes Postfach, sonst E-Mail der
  Verwaltung, sonst `reply@immoswiss.app`). Die Seite *E-Mail-Eingang* zeigt «Empfang noch nicht eingerichtet».
* MX nicht gesetzt: Mails an die Plattformadressen kommen nicht an. Erst MX und Webhook einrichten, dann das
  Geheimwort setzen.
* Lassen Sie den Dienst `fetch_replies` (`python manage.py fetch_replies --einmal` als geplante Aufgabe) und den
  Rechnungsabruf `fetch_rechnungen` weiterlaufen. Beide holen Mails aus eigenen Postfächern (nur Verwaltungen
  unter «Erweitert»); `fetch_replies` stellt ausserdem gebündelte Chat-Nachrichten zu, auch für Verwaltungen
  ohne eigenes Postfach. Für alle anderen holt `fetch_rechnungen` nichts.
