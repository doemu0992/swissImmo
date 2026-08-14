# Marktanalyse Abo-Modell (Phase 3)

**Stand:** 14.08.2026
**Zweck:** Grundlage für die Abo-Stufen und den Modulzuschnitt aus Phase 3. Ersetzt Schätzungen durch veröffentlichte Preise der Wettbewerber.
**Bezug:** `docs/ANALYSE.md`, TS-11 (Abo-Feld ohne Wirkung), P3.1 bis P3.3.

---

## 0. Was diese Analyse belegt und was nicht

**Belegt:** Öffentlich publizierte Preislisten von Fairwalter und LIMMOBI, mit Stand vom 14.08.2026 vollständig abgerufen. Diese beiden sind die einzigen relevanten Schweizer Anbieter mit transparenter Preisseite.

**Nicht belegt:** Die Preise von GARAIO REM, Rimo R5, ImmoTop2 und Abacus AbaImmo. Alle vier arbeiten mit Offerten auf Anfrage. Ohne Kundenkontakt sind hier keine Zahlen zu beschaffen — Schätzungen dazu stünden in diesem Dokument nur als Vermutung und fehlen deshalb.

**Nicht belegt:** Zahlungsbereitschaft, Wechselwahrscheinlichkeit und Preiselastizität. Publizierte Listenpreise sagen, was verlangt wird, nicht was bezahlt wird. Für belastbare Aussagen bräuchte es Gespräche mit fünf bis zehn Verwaltungen — das ist Feldarbeit, keine Recherche.

**Quellenkritik:** Die aufgerufenen Vergleiche von Zahlungsanbietern stammen überwiegend von Payrexx selbst und sind entsprechend interessengeleitet. Die Zahlen zu Stripe daraus sind als Marketingaussage zu behandeln, nicht als neutrale Erhebung.

---

## 1. Marktbild

Der Schweizer Markt zerfällt in drei Segmente mit klar unterschiedlichem Vertriebsmodell:

| Segment | Anbieter | Preismodell | Vertrieb |
|---|---|---|---|
| **Selbstbedienung, privat bis klein** | LIMMOBI, immoShome | Preisliste, Selbstregistrierung | ohne Verkaufsgespräch |
| **Selbstbedienung, kleine bis mittlere Verwaltung** | **Fairwalter** | Preisliste, Testphase, optional Demo | teilweise mit Demo |
| **Enterprise** | GARAIO REM, Rimo R5, ImmoTop2, AbaImmo | Offerte, Projekt, teils On-Premise | Verkaufsprozess |

Grössenordnungen zur Einordnung: Fairwalter nennt über 400 Immobilienverwaltungen als Kunden. GARAIO REM nennt über 250 Kunden, mit denen mehr als zwei Millionen Objekte verwaltet werden, und ist seit über fünfzehn Jahren im Markt. W&W Immo Informatik (ImmoTop2, Rimo R5) nennt über 2'800 Kundenprojekte.

**Für swissImmo relevant ist das mittlere Segment.** Der Funktionsumfang aus der Bestandsanalyse — doppelte Buchhaltung, Bankabgleich, pain.001, MWST nach beiden Methoden, AfA, Erneuerungsfonds, Kautionsregister, amtliche Formulare, Eigentümer- und Mieterportal — liegt deutlich über dem Selbstbedienungssegment und erreicht funktional den Bereich, in dem Fairwalter verkauft. Der Enterprise-Bereich verlangt dagegen einen Verkaufs- und Einführungsapparat, der hier nicht existiert.

---

## 2. Fairwalter — das direkte Vorbild

Fünf Stufen, gestaffelt nach **drei** Dimensionen gleichzeitig: Mietobjekte, Nutzer, Speicherplatz.

| | Light | Privat | Basic | Professional | Enterprise |
|---|---|---|---|---|---|
| Preis/Monat | CHF 29 | CHF 69 | CHF 99 | CHF 299 | CHF 699 |
| Mietobjekte | 10 | 25 | 100 | 300 | 1'000 |
| Nutzer | 1 | 2 | 3 | 10 | unbegrenzt |
| Speicher | 1 GB | 10 GB | 50 GB | 100 GB | 200 GB |

Alle Preise ohne MWST. Aufschaltgebühr inklusive, 30 Tage kostenlos testen.

**Zusatzkosten:**

| Position | Preis |
|---|---|
| +50 GB Speicher (ab Basic) | CHF 9.90/Monat |
| +100 Objekte (Professional) | CHF 60/Monat |
| +100 Objekte (Enterprise) | CHF 40/Monat |
| Abnahme-App, **pro Abnahme** | CHF 9.90 |
| Personen- und Handwerkerimport | CHF 400 einmalig |
| Stundensatz Beratung, Schulung, Support | CHF 200 |

**Preis je Objekt und Monat** — die Kennzahl, an der ein Interessent rechnet:

| Stufe | CHF/Objekt/Monat |
|---|---|
| Light | 2.90 |
| Privat | 2.76 |
| Basic | 0.99 |
| Professional | 1.00 |
| Enterprise | 0.70 |

Bemerkenswert: Zwischen Privat und Basic fällt der Stückpreis um zwei Drittel. Die unteren beiden Stufen sind kein Mengengeschäft, sondern ein Einstiegsprodukt für private Vermieter; das eigentliche Geschäft beginnt bei CHF 99.

### Was Fairwalter tatsächlich sperrt

Das ist die wichtigste Beobachtung dieser Analyse, denn sie widerspricht der bisherigen Planung.

**In allen Stufen enthalten — auch für CHF 29:**
Buchhaltung, automatischer Abschluss mit Bilanz und Erfolgsrechnung, Debitoren, Kreditoren mit Workflow, Mahnwesen, Bankabgleich, **Heiz- und Nebenkostenabrechnung**, Hypothekenverwaltung, abweichendes Geschäftsjahr, Mietereinzug und -auszug, Wohnungsübergabe, Vertragsmanagement, Mieterspiegel, Leerstandsmanagement, digitale Mietzinskaution, Schadenmeldung, Reparaturen, Dienstleister, Dokumentenablage, Export, Zwei-Faktor-Authentifizierung, Schweizer Hosting.

**Erst ab Basic (CHF 99):**
Eigenes Logo und Vorlagenverwaltung, Pendenzen und Aufgaben, Mieterkommunikation, Mietzinsrechner, digitale Warteliste, automatischer Sollstellungs-Job, **KI im Kreditorenworkflow**, Eigentümer-Frontend, Support-Level-Agreement.

**Erst ab Professional (CHF 299):**
Konsolidierung, Verwaltungshonorar.

**Erst ab Enterprise (CHF 699):**
Premium Service, Onboardingpaket inklusive.

### Drei Schlussfolgerungen daraus

**Erstens: Nebenkostenabrechnung als zubuchbares Modul ist nicht verkäuflich.** Die Projektanweisung nennt sie als eigenständige Zusatzeinheit. Im Markt ist sie ab CHF 29 im Grundpreis enthalten — bei LIMMOBI ab CHF 9. Sie ist für eine Immobilienverwaltung kein Extra, sondern der Grund, überhaupt eine Software zu kaufen. Dasselbe gilt für Buchhaltung, Mahnwesen und Abschluss, also für den Grossteil dessen, was unter „Reporting" fallen würde.

**Zweitens: Gesperrt wird das, was Arbeit spart, nicht das, was Pflicht ist.** Automatisierung (Sollstellungs-Job, KI-Kreditoren), Zusammenarbeit (Pendenzen, Mieterkommunikation, mehr Nutzer), Aussenwirkung (eigenes Logo, Eigentümerportal) und Mandatsgeschäft (Konsolidierung, Verwaltungshonorar). Wer nur ein Haus verwaltet, braucht das nicht. Wer davon lebt, zahlt dafür.

**Drittens: Für teure Einzelaktionen gibt es ein drittes Modell.** Die Abnahme-App kostet CHF 9.90 pro Abnahme, unabhängig von der Stufe. Das ist die Antwort auf Funktionen mit variablen Fremdkosten — und genau die Struktur, die swissImmo für digitale Unterschrift und KI-Belegerkennung braucht.

---

## 3. LIMMOBI — das Gegenmodell

| | Landlord | Team-10 | Team-40 | Team-100 |
|---|---|---|---|---|
| Preis/Monat | CHF 9 | CHF 19 | CHF 34 | CHF 44 |
| Einheiten | 2 | 10 | 40 | 100 |
| Speicher | 1 GB | 2 GB | 4 GB | 8 GB |
| Nutzer | 1 | unbegrenzt | unbegrenzt | unbegrenzt |

Alle Preise **inklusive** MWST. Über 100 Einheiten: Offerte.

Zwei Eigenschaften machen dieses Modell interessant, weil sie das Gegenteil von Fairwalter sind:

- **Keine Funktionssperren.** Alle Abos bieten laut Anbieter den kompletten Funktionsumfang. Gestaffelt wird ausschliesslich über Einheiten und Speicher.
- **Nutzer unbegrenzt ab CHF 19.** Fairwalter verlangt für zehn Nutzer CHF 299.

Bei 100 Einheiten kostet LIMMOBI CHF 44 inklusive MWST, Fairwalter CHF 99 ohne — also gut das Zweieinhalbfache. Fairwalter rechtfertigt das über Funktionstiefe und Betreuung; LIMMOBI verkauft über Einfachheit und Preis.

**Für den Modulzuschnitt heisst das:** Es gibt keinen Marktzwang zu Funktionssperren. Beide Modelle funktionieren. Die Entscheidung ist strategisch, nicht durch Wettbewerb erzwungen.

Erwähnenswert für die Positionierung: LIMMOBI zeigt direkte Bankanbindungen zu über dreissig Schweizer Instituten (UBS, PostFinance, Raiffeisen, praktisch alle Kantonalbanken). swissImmo hat heute Bankabgleich per Dateiimport (camt.053/CSV) und pain.001 — funktional näher an Fairwalter, das ebenfalls „Bankabgleich per Datei-Upload" listet.

---

## 4. Vorschlag für vier Stufen

Die Projektanweisung verlangt vier Stufen, gestaffelt nach Objekten/Einheiten, Nutzerzahl und Funktionstiefe. Vorschlag, an den Marktankern ausgerichtet:

| | **Start** | **Team** | **Professional** | **Enterprise** |
|---|---|---|---|---|
| Preis/Monat, exkl. MWST | CHF 39 | CHF 119 | CHF 329 | CHF 749 |
| Einheiten | 25 | 150 | 500 | 2'000 |
| Nutzer | 2 | 5 | 15 | unbegrenzt |
| Speicher | 5 GB | 50 GB | 150 GB | 300 GB |
| CHF/Einheit/Monat | 1.56 | 0.79 | 0.66 | 0.37 |

**Begründung der Ankerpunkte:**

- **Start CHF 39** liegt zwischen Fairwalter Light (29) und Privat (69), bietet aber mehr Einheiten und Nutzer als beide. Kein Preiskampf gegen LIMMOBI im Bereich unter CHF 20 — dieses Segment ist mit dem Funktionsumfang von swissImmo nicht profitabel zu bedienen.
- **Team CHF 119** ist der Angriffspunkt auf Fairwalter Basic (CHF 99): mehr Einheiten (150 statt 100), mehr Nutzer (5 statt 3), zwanzig Franken teurer. Wer bei Fairwalter am Nutzerlimit scheitert, muss dort auf CHF 299 wechseln.
- **Professional CHF 329** entspricht Fairwalter Professional bei deutlich mehr Einheiten (500 statt 300) und Nutzern (15 statt 10).
- **Enterprise CHF 749** verdoppelt die Einheiten gegenüber Fairwalter Enterprise (2'000 statt 1'000) bei ähnlichem Preis.

Die Staffelung ist bewusst durchgängig auf „mehr Volumen zum vergleichbaren Preis" gebaut. Das ist die Position, die ein neuer Anbieter ohne Marke und ohne Referenzen einnehmen kann — Preisführerschaft nach unten überlässt man LIMMOBI, Vertrauensvorsprung hat Fairwalter.

**Zusatzpositionen** analog zum Markt: +100 Einheiten für CHF 45/Monat, +50 GB für CHF 9.90/Monat, Datenimport nach Aufwand.

**Wichtiger Vorbehalt:** Diese Zahlen sind aus Wettbewerbspreisen abgeleitet, nicht aus Kostenrechnung. Bevor sie gelten, braucht es die Gegenrechnung: Was kostet ein Mandant im Betrieb? Zu berücksichtigen sind Schweizer Hosting, Datenbank, Speicher, die Groq-Kosten pro gescanntem Beleg, DocuSeal-Kosten pro Signatur und der Supportaufwand. Bei CHF 39 im Monat ist eine einzige Supportanfrage pro Quartal bereits defizitär, wenn man den branchenüblichen Stundensatz von CHF 200 ansetzt.

---

## 5. Modulzuschnitt

Die fünf Modulkandidaten aus der Projektanweisung, geprüft am Markt:

| Kandidat | Befund | Empfehlung |
|---|---|---|
| **Nebenkostenabrechnung** | Bei Fairwalter ab CHF 29, bei LIMMOBI ab CHF 9 im Grundpreis | **Kein Modul.** In allen Stufen enthalten. Ein Verkaufshindernis, kein Zusatzertrag. |
| **Reporting** | Abschluss, Bilanz, Erfolgsrechnung, Mieterspiegel bei Fairwalter in allen Stufen | **Kein Modul.** Grundfunktion. Erweiterte Auswertungen können nach Stufe gestaffelt werden. |
| **Digitale Unterschrift** | Variable Fremdkosten je Signatur; Fairwalter rechnet Vergleichbares pro Vorgang ab | **Nutzungsabhängig.** Preis pro Signatur, unabhängig von der Stufe. |
| **OCR-/KI-Dokumentenerkennung** | Variable Groq-Kosten je Beleg; Fairwalter sperrt KI-Kreditoren erst ab CHF 99 | **Beides.** Ab Team enthalten, mit Kontingent; darüber pro Beleg. |
| **Schnittstellen** | Bei Fairwalter nicht als Preisposition sichtbar | **Nach Stufe.** Portal-Feed und iCal ab Team, pain.001 und API ab Professional. |

**Das Muster dahinter:** Funktionen mit variablen Fremdkosten werden nutzungsabhängig abgerechnet, Funktionen ohne Grenzkosten über die Stufe. Alles, was eine Verwaltung gesetzlich oder betrieblich zwingend braucht, gehört in jede Stufe.

**Was sich stattdessen zum Sperren eignet** — abgeleitet aus dem, was Fairwalter tatsächlich sperrt, und abgeglichen mit dem Bestand aus `docs/ANALYSE.md`:

| Ab Stufe | Funktion | im Bestand vorhanden |
|---|---|---|
| Team | Eigenes Logo, Vorlagenverwaltung | teilweise (`Verwaltung.logo`) |
| Team | Eigentümerportal | ja, vollständig |
| Team | Mieterportal | ja, vollständig |
| Team | Automatischer Mietenlauf, Mahnlauf | ja (`monatslauf`, `mahnlauf`) |
| Team | KI-Belegerkennung mit Kontingent | ja (`finance/utils.py`) |
| Professional | Mandatsabrechnung, Verwaltungshonorar | ja (`mandat_abrechnung.py`) |
| Professional | Konsolidierung über Mandate | ja |
| Professional | pain.001-Zahlungsaufträge | ja |
| Professional | Mandantenspezifisches Branding | Phase 4, P3.4 |
| Enterprise | SLA, Premium-Support, Onboarding inklusive | organisatorisch |

---

## 6. Zahlungsanbieter

Anforderungen: wiederkehrende Abrechnung, Schweizer MWST, Testphase, Upgrade und Downgrade mit anteiliger Verrechnung, und — für Schweizer KMU wichtiger als Kreditkarte — Rechnung mit QR-Einzahlungsschein.

| Anbieter | Für swissImmo relevant |
|---|---|
| **Stripe** | Ausgereifte Abo-Verwaltung, Testphasen, anteilige Verrechnung, gutes SDK. Kein PostFinance Pay. Rechnung mit Schweizer QR-Einzahlungsschein ist nicht Teil des Standardprodukts. |
| **Payrexx** | Schweizer Anbieter, FINMA-lizenziert, PCI DSS Level 1, in Thun. Unterstützt TWINT und PostFinance Pay ohne separaten Vertrag. **QR-Rechnungen lassen sich direkt erstellen und versenden, mit integrierten Zahlungserinnerungen** — Gebühr 0.50 % im Standard-Plan. |
| **wallee** | Schweizer Anbieter, modular, persönlicher Support, PostFinance Pay. Weniger E-Commerce-Werkzeuge. |
| **Datatrans (Planet), Worldline** | Etabliert, eher Enterprise, Konditionen auf Anfrage. |

**Einschränkung:** Die verglichenen Kostenrechnungen stammen von Payrexx selbst. Die Aussage „Payrexx ist günstiger als Stripe" ist eine Herstelleraussage, keine unabhängige Erhebung. Für eine Entscheidung braucht es Offerten mit dem tatsächlich erwarteten Transaktionsprofil — bei Abo-Software sind das wenige, regelmässige Buchungen mittlerer Höhe, ein ganz anderes Profil als der Onlinehandel, für den diese Vergleiche gerechnet sind.

**Empfehlung zum Vorgehen:** Offerten bei Payrexx und wallee einholen und gegen Stripe rechnen. Ausschlaggebend sollte weniger der Prozentsatz sein als die Frage, ob die QR-Rechnung als Zahlungsweg sauber unterstützt wird. Eine Immobilienverwaltung, die selbst mit QR-Rechnungen arbeitet, erwartet, ihre eigene Softwarerechnung genauso zu bezahlen.

**Freigabepflichtig.** Nach Projektanweisung darf hier nichts ohne ausdrückliche Zustimmung angebunden werden. Dieses Kapitel ist ein Vorschlag zur Entscheidung, keine Vorbereitung einer Umsetzung.

---

## 7. Downgrade und Zahlungsausfall

Die Projektanweisung gibt die Richtung vor: Daten bleiben erhalten, Funktionen werden gesperrt, nichts wird gelöscht. Der konkrete Fall ist heikler, als er klingt.

**Das Problem:** Eine Verwaltung mit 200 Einheiten stuft auf Team (150 Einheiten) zurück. Was passiert mit 50 Einheiten? Sie zu löschen ist ausgeschlossen — daran hängen Verträge, Buchungen und Abrechnungen, teils mit gesetzlicher Aufbewahrungspflicht.

**Vorschlag:**

| Zustand | Verhalten |
|---|---|
| Limit überschritten nach Downgrade | Alle Daten lesbar und exportierbar. Keine **neuen** Einheiten, Verträge oder Buchungen, bis das Limit eingehalten ist. Laufende Prozesse — Mietenlauf, Mahnlauf, Nebenkostenabrechnung — laufen für den Bestand weiter. |
| Zahlung überfällig, 1.–14. Tag | Voller Zugriff, Hinweis in der Oberfläche, Erinnerung per E-Mail. |
| 15.–30. Tag | Nur noch Lesen und Export. Keine Hintergrundläufe, kein Versand. |
| 31.–90. Tag | Nur noch Export. Anmeldung möglich, Oberfläche gesperrt. |
| ab 91. Tag | Nur nach ausdrücklicher schriftlicher Aufforderung. Aufbewahrungsfristen beachten. |

**Der entscheidende Punkt: Laufende Prozesse dürfen nicht mitten im Zyklus abbrechen.** Wird der Mietenlauf am 1. des Monats gesperrt, weil eine Rechnung offen ist, bekommt die Verwaltung keine Mieteinnahmen — der Schaden steht in keinem Verhältnis zum Ausstand und ist geeignet, aus einem Zahlungsverzug einen Rechtsstreit zu machen. Sperren gehören an den Anfang eines Zyklus, nicht in dessen Mitte.

**Was in `docs/ANALYSE.md` bereits vorbereitet ist:** Das Entitlement-System aus P3.1 ist die zentrale Prüfstelle für diese Regeln. Ohne sie wären sie über den Code verstreut — genau das, was die Projektanweisung ausschliesst.

---

## 8. Zwei Befunde ausserhalb des Auftrags

Beim Vergleich der Leistungsmerkmale sind zwei Lücken aufgefallen, die den Verkauf unabhängig vom Preis behindern:

**Zwei-Faktor-Authentifizierung fehlt.** Fairwalter führt 2FA in **allen** Stufen als Sicherheitsmerkmal auf. Im Bestand von swissImmo findet sich dazu keine Implementierung. Für ein Produkt, das Mietverträge, Lohnausweise und Betreibungsauszüge verwaltet, ist das kein Komfortmerkmal, sondern eine Ausschreibungsanforderung. Gehört in Phase 2 zum Rollen- und Zugangsthema, nicht in Phase 3.

**Hosting-Standort.** Fairwalter bewirbt „Sicheres Daten-Hosting in der Schweiz" prominent auf der Preisseite. swissImmo läuft laut Konfiguration auf PythonAnywhere. Bei Mieterdaten unter Schweizer Datenschutzrecht ist der Standort ein Verkaufsargument der Gegenseite, solange er nicht geklärt ist. Zusammen mit dem ohnehin anstehenden Wechsel auf PostgreSQL (P1.4) und der CDN-Abhängigkeit aus TS-9 ergibt das ein Paket, das vor dem Markteintritt entschieden sein muss.

---

## 9. Offene Punkte

| Frage | Wer klärt |
|---|---|
| Kostenrechnung je Mandant — trägt CHF 39 den Betrieb? | intern, vor Festlegung der Preise |
| Preise von GARAIO REM, Rimo R5, ImmoTop2 | nur über Kundenkontakt |
| Zahlungsbereitschaft, Wechselbereitschaft | Gespräche mit 5 bis 10 Verwaltungen |
| Angebote Payrexx, wallee, Stripe mit realem Transaktionsprofil | Offertanfrage, freigabepflichtig |
| Hosting-Standort und Datenschutzversprechen | Entscheid vor Markteintritt |
| Länge der Testphase — Fairwalter gibt 30 Tage vor | Entscheid |
| Jahresabo mit Rabatt? Bei keinem der beiden Vergleichsanbieter sichtbar | Entscheid |

---

## Quellen

- Fairwalter, Preisseite, abgerufen 14.08.2026: https://www.fairwalter.com/preise
- LIMMOBI, Startseite mit Preistabelle, abgerufen 14.08.2026: https://limmobi.ch/CH/de_CH
- GARAIO REM, Unternehmensangaben zu Kundenzahl und verwalteten Objekten: https://www.garaio-rem.ch/de/home
- W&W Immo Informatik, Produktübersicht ImmoTop2 und Rimo R5: https://www.wwimmo.ch/produkte/
- Payrexx, Anbietervergleiche und Leistungsbeschrieb (Herstellerquelle, entsprechend zu gewichten): https://payrexx.com/comparison/payrexx-vs-stripe
- StartupSchwiiz, Payrexx-Bewertung mit Angaben zu QR-Rechnung und Lizenzierung: https://www.startupschwiiz.ch/bewertungen/payrexx
