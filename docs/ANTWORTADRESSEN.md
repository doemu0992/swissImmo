# Antwortadressen der Plattform (Betreiber-Anleitung)

Jede Verwaltung bekommt automatisch eine eigene Antwortadresse `<kennung>@<ANTWORT_DOMAIN>`, zum Beispiel
`muster-k3x9a2b7qz@immoswiss.app`. Ticket-Mails, Chat-Mails (Mieter und Handwerker) und Terminmails tragen sie als
Antwortadresse. Eine Antwort läuft über Brevo (Inbound Parsing) an die Plattform; die Adresse sagt, zu welcher
Verwaltung sie gehört. Die Verwaltung muss nichts einrichten.

Hat eine Verwaltung ein eigenes Postfach hinterlegt (Einstellungen, Postfächer, Zweck «Antworten») und ist es
aktiv, gilt weiter dieses. Das alte gemeinsame `reply@immoswiss.app` (Zuordnung über «Ticket #123» im Betreff)
bleibt als Rückfall bestehen.

## Was Sie einrichten müssen

1. **Brevo-Konto** mit der Domain als Absender-/Empfangsdomain.
2. **MX-Einträge** der Antwortdomain auf Brevo Inbound Parsing (die genauen Hostnamen und Prioritäten nennt die
   Brevo-Dokumentation: <https://developers.brevo.com/docs/inbound-parse-webhooks>). Empfängt die Hauptdomain
   `immoswiss.app` schon andere Mails (Büro-Postfächer), nehmen Sie eine **Subdomain**, zum Beispiel
   `antwort.immoswiss.app`, und setzen `ANTWORT_DOMAIN=antwort.immoswiss.app`. Ein MX-Eintrag gilt für den ganzen
   Domainnamen, die Büro-Post würde sonst bei Brevo landen.
3. **Inbound-Webhook** bei Brevo anlegen: Domain und die Webhook-URL
   `https://<ihre-instanz>/webhooks/brevo/inbound/` (das Secret gehört in den Header `X-Webhook-Secret`;
   kann Brevo keinen eigenen Header setzen, hängen Sie `?token=<secret>` an die URL).
4. **Umgebungsvariablen** auf dem Server:

   | Variable | Bedeutung |
   |---|---|
   | `BREVO_WEBHOOK_SECRET` | gemeinsames Geheimnis, zufällig und lang (zum Beispiel `openssl rand -hex 32`). Ohne Wert weist der Webhook alles ab (403). |
   | `ANTWORT_DOMAIN` | Domain der Antwortadressen. Vorgabe `immoswiss.app`. |

   **Wichtig:** Solange `BREVO_WEBHOOK_SECRET` fehlt, bleibt der bisherige Reply-To unverändert. Erst mit dem
   Secret tragen Ticket-Mails die Plattformadresse. So geht keine Antwort an eine Adresse, die noch nichts
   empfängt verloren.
5. **Dienst `fetch_replies`** weiter laufen lassen (`python manage.py fetch_replies`): Er ruft die eigenen
   Postfächer ab und stellt gebündelte Chat-Nachrichten zu, auch für Verwaltungen ohne eigenes Postfach.

## Test mit curl

Beispiel im Format von Brevo (`items[]`). Die Adresse der Verwaltung steht in den Einstellungen unter «Postfächer».

```bash
curl -sS -X POST "https://<ihre-instanz>/webhooks/brevo/inbound/" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $BREVO_WEBHOOK_SECRET" \
  -d '{"items": [{
        "MessageId": "<test-0001@example.ch>",
        "From": {"Name": "Hans Muster", "Address": "hans@example.ch"},
        "To": [{"Name": null, "Address": "muster-k3x9a2b7qz@immoswiss.app"}],
        "Recipients": ["muster-k3x9a2b7qz@immoswiss.app"],
        "Subject": "Re: Wasserhahn tropft (Ticket #12)",
        "ExtractedMarkdownMessage": "Der Handwerker kann am Dienstag.",
        "RawTextBody": "Der Handwerker kann am Dienstag.\n\nAm 01.11.2026 schrieb Verwaltung:\n> ...",
        "Headers": {}
      }]}'
```

Antworten: `{"status": "ok, saved"}` (im Ticket abgelegt), `{"status": "ok, chat"}` (Chat zwischen Mieter und
Handwerker, Gegenseite per Mail bedient), `{"status": "duplicate"}` (gleiche `MessageId` schon verarbeitet),
`{"status": "ignored"}` (Adresse unbekannt, Ticket nicht in dieser Verwaltung, Mehrfachempfänger, Lesemodus).
`ignored` sagt bewusst nicht, warum, damit niemand erfährt, ob ein Ticket in einer anderen Verwaltung existiert.
Fehlendes oder falsches Secret ergibt 403.

## Regeln der Zuordnung

* Die Empfängeradresse (`Recipients`, sonst `To`) nennt die Verwaltung. «Ticket #12» und die Auftragsmarke
  `[A7]` im Betreff gelten nur innerhalb dieser Verwaltung.
* Eine Adresse auf der Antwortdomain mit unbekannter Kennung wird verworfen, nicht über die Ticketnummer geraten.
* Gleiche `MessageId` wird je Verwaltung nur einmal verarbeitet (Tabelle `tickets_eingegangenemail`,
  speichert nur die ID).
* Automatische Mails (Abwesenheit, Weiterleitungen der Plattform) werden im Chat nie weitergeleitet.
* Es wird nur Text gespeichert (`ExtractedMarkdownMessage`, sonst `RawTextBody` ohne Zitat); HTML wird nie
  ungefiltert übernommen, Anhänge werden ignoriert.

## Adresse erneuern

Der Inhaber kann die Adresse in den Einstellungen erneuern (zum Beispiel nach Spam an die Adresse). Die bisherige
Adresse gilt danach noch 30 Tage, damit Antworten auf schon versandte Mails ankommen. Der Vorgang steht im Protokoll.

## Ohne Konfiguration

* Kein `BREVO_WEBHOOK_SECRET`: Webhook gesperrt (403), Reply-To wie bisher (eigenes Postfach, sonst E-Mail der
  Verwaltung, sonst `reply@immoswiss.app`). Die Einstellungsseite zeigt «Empfang noch nicht eingerichtet».
* MX nicht gesetzt: Mails an die Plattformadresse kommen nicht an. Erst MX und Webhook einrichten, dann das Secret
  setzen.
