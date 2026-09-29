# Marktaudit: Schweizer Software für Immobilienbewirtschaftung

**Abteilung:** Marketing & Docs
**Stand:** 29.09.2026 (alle Preisseiten an diesem Tag abgerufen)
**Ticket:** `mkt-001` Wettbewerbsanalyse & Pricing-Strategie (`agent_ops/tasks.json`)
**Baut auf:** `docs/MARKT.md` (Stand 14.08.2026). Dieses Audit ergänzt es und korrigiert es an drei Stellen (siehe Abschnitt 1).

Alle Preise verstehen sich **ohne MWST**, sofern nicht anders vermerkt.

---

## Management Summary

1. **Der Markt ist konsolidierter, als die Namensliste vermuten lässt.** Drei der fünf genannten Anbieter, nämlich **Fairwalter, ImmoTop2 und Rimo R5, gehören zu einer Firma: W&W Immo Informatik AG**. W&W deckt damit jedes Segment ab, vom privaten Vermieter (Fairwalter, CHF 29) bis zur Grossverwaltung (Rimo R5, Kauflizenz). Wer gegen Fairwalter antritt, tritt gegen das Ökosystem des Marktführers an, mit über 2'800 Kunden.
2. **ImmoTop2 hat seine Preise inzwischen veröffentlicht.** Die Cloud-Version kostet ab CHF 149 pro Monat, dazu eine einmalige Aufschaltgebühr von CHF 600. Damit ist die Lücke «Enterprise-Preise auf Anfrage» aus `docs/MARKT.md` teilweise geschlossen. Das Preisband im mittleren Segment liegt jetzt belegt zwischen **CHF 99 und CHF 650 pro Monat**, für 50 bis 400 Objekte.
3. **Tayo ist kein direkter ERP-Konkurrent.** Tayo ist eine Plattform für Tickets, Aufträge und Abnahmen, die *auf* einem ERP aufsetzt: Schnittstellen zu Abacus, Garaio REM und W&W, Beteiligung von Abacus. Tayo ist deshalb für swissImmo ein Konkurrent bei Funktionen (Tickets, Portal, Abnahme), nicht bei der Buchhaltung.
4. **swissImmo hat zwei Preismodelle, die sich widersprechen. Das im Produkt aktive ist nicht wettbewerbsfähig.** Die Preisseite im Code rechnet zwischen CHF 1.90 und 2.90 pro Einheit und Monat. Bei 400 Einheiten ergibt das CHF 760. Fairwalter verlangt dafür CHF 359, ImmoTop2 CHF 649. Der Vorschlag in `docs/MARKT.md` (CHF 39 / 119 / 329 / 749) ist marktgerecht und sollte die Preisseite im Code ersetzen.
5. **Die grösste Chance liegt zwischen 100 und 500 Objekten.** Genau dort springt Fairwalter von CHF 99 auf CHF 299, weil Basic bei 3 Nutzern endet. ImmoTop2 verlangt dort Aufpreise pro Modul und die Aufschaltgebühr. swissImmo kann hier mit **«alles Schweizerische inklusive, 5 Nutzer, ohne Einrichtungsgebühr»** angreifen.

---

## 1. Korrekturen gegenüber `docs/MARKT.md`

| Aussage in MARKT.md (14.08.) | Befund 29.09.2026 | Quelle |
|---|---|---|
| «Nicht belegt: die Preise von … ImmoTop2» | **Veröffentlicht:** Basic ab CHF 149, Professional ab CHF 399, Enterprise ab CHF 1'999 pro Monat, jeweils im Jahresabo. Aufschaltung CHF 600 einmalig. | wwimmo.ch/produkte/preise-immotop2-cloud (geändert am 25.08.2026) |
| W&W und Fairwalter erscheinen als getrennte Wettbewerber | Fairwalter wird auf wwimmo.ch als eigenes Produkt geführt. W&W bezeichnet ImmoTop2, Rimo R5 und Fairwalter als ihre Software. | wwimmo.ch/produkte/fairwalter; Stelleninserat W&W auf join.com |
| LIMMOBI: Speicher 1 / 2 / 4 / 8 GB | Speicher inzwischen **2 / 4 / 16 / 32 GB**, Preise unverändert (CHF 9 / 19 / 34 / 44 inkl. MWST) | limmobi.ch/de/preise |

---

## 2. Marktlandkarte

| Segment | Anbieter | Eigentümer | Preismodell | Betrieb | Vertrieb |
|---|---|---|---|---|---|
| Privat / Kleinst | LIMMOBI | LIMMOBI AG | Preisliste nach Einheiten, alle Funktionen | Cloud | Selbstregistrierung |
| Privat / Kleinst | immoShome | – | CHF 99 Einrichtung + CHF 25/Monat | Cloud | Selbstregistrierung |
| Klein bis mittel | **Fairwalter** | **W&W** | 5 Stufen, Preisliste, 30 Tage Test | Cloud, CH-Hosting | Selbstregistrierung + Demo |
| Klein bis mittel | **ImmoTop2 Cloud** | **W&W** | 3 Stufen + Modul-Zusatzoptionen, Jahresabo | Windows-Client + Azure-Cloud | Verkaufsgespräch |
| Klein bis mittel | AbaImmoLite | Abacus Research | Fixpreis ab CHF 480/Monat, nach Objektzahl | Cloud (Abacus-Hosting CH) | Verkauf / Partner |
| Klein bis mittel | GARAIO REM light | GARAIO REM | auf Anfrage (< 1'000 Objekte) | Web | Partner |
| Mittel bis gross | **Rimo R5** | **W&W** | Kauflizenz ab CHF 4'370 + Wartung | On-Premise oder W&W Cloud | Projekt |
| Mittel bis gross | GARAIO REM, AbaImmo | GARAIO REM, Abacus | Projekt / Offerte | On-Premise / Cloud | Projekt |
| Aufsatz auf ERP | **Tayo** | Tayo SA (Beteiligung Abacus) | 3 Pläne, Preise auf Anfrage, mengenabhängig | Cloud, CH-Hosting, ISO 27001 | Demo |

---

## 3. Anbieterprofile

### 3.1 Fairwalter (W&W-Gruppe): der direkte Referenzwettbewerber

Cloud-Software für private Vermieter bis mittlere Verwaltungen. Transparente Preisliste, 30 Tage kostenlos testen, Aufschaltgebühr inbegriffen.

| | Light | Privat | Basic | Professional | Enterprise |
|---|---|---|---|---|---|
| **Preis / Monat** | CHF 29 | CHF 69 | **CHF 99** | CHF 299 | CHF 699 |
| **Preis / Jahr** | CHF 348 | CHF 828 | CHF 1'188 | CHF 3'588 | CHF 8'388 |
| Mietobjekte | 10 | 25 | 100 | 300 | 1'000 |
| Nutzer:innen | 1 | 2 | 3 | 10 | unbegrenzt |
| Speicher | 1 GB | 10 GB | 50 GB | 100 GB | 200 GB |
| CHF / Objekt / Monat | 2.90 | 2.76 | 0.99 | 1.00 | 0.70 |

**Funktionsstaffel (aus der Paketmatrix der Preisseite):**

| Funktion | Light | Privat | Basic | Prof. | Ent. |
|---|:-:|:-:|:-:|:-:|:-:|
| Buchhaltung, Abschluss, Debitoren, Kreditoren mit Workflow, Mahnwesen | ✓ | ✓ | ✓ | ✓ | ✓ |
| Heiz- und Nebenkostenabrechnung, Import NK-Daten | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mieterein- und -auszug, Wohnungsübergabe, Verträge, Mieterspiegel, Leerstand | ✓ | ✓ | ✓ | ✓ | ✓ |
| Digitale Mietzinskaution, Hypotheken, Bankabgleich per Datei | ✓ | ✓ | ✓ | ✓ | ✓ |
| Schadenmeldung, Reparaturen, Bauteile, Dienstleister | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2FA, CH-Hosting, KI-Supportassistent «Walter» | ✓ | ✓ | ✓ | ✓ | ✓ |
| Eigenes Logo, Vorlagenverwaltung | – | – | ✓ | ✓ | ✓ |
| Pendenzen und Aufgaben, Mieterkommunikation | – | – | ✓ | ✓ | ✓ |
| Mietzinsrechner, digitale Warteliste | – | – | ✓ | ✓ | ✓ |
| Automatischer Sollstellungs-Job, **KI im Kreditorenworkflow** | – | – | ✓ | ✓ | ✓ |
| Support-Level-Agreement | – | – | ✓ | ✓ | ✓ |
| **Eigentümer-Frontend** | – | – | – | ✓ | ✓ |
| Verwaltungshonorar, individueller Kontenplan, Konsolidierung | – | – | – | ✓ | ✓ |
| Public API, Premium Service, Onboarding inklusive, 24 h Reaktionszeit | – | – | – | – | ✓ |

**Zusatzkosten:**

| Position | Preis |
|---|---|
| +50 GB Speicher (ab Basic) | CHF 9.90 / Monat |
| +100 Objekte (Professional / Enterprise) | CHF 60 / CHF 40 pro Monat |
| Abnahme-App | **CHF 9.90 pro Abnahme** |
| Personen- und Handwerkerimport | CHF 400 einmalig |
| Schulung, Ticket- und Mailsupport, Hotline, Beratung | **nach Aufwand, CHF 200 / Stunde** (ausser Enterprise) |

> **Beobachtung:** Bei Fairwalter ist auch der Support kostenpflichtig: Ticket- und Mailsupport sowie die Hotline laufen «nach Aufwand». Im Preis enthalten sind nur Helpcenter, Videos, Webinare und der KI-Assistent. Das gibt swissImmo einen klaren Hebel für die Positionierung (Abschnitt 6).

### 3.2 ImmoTop2 Cloud (W&W-Gruppe): die etablierte Standardlösung

Windows-Client-Server-Software (WPF), die W&W auf Microsoft Azure betreibt. Voraussetzung ist Windows 11 mit mindestens 16 GB RAM. Mac-Nutzer brauchen Parallels. Das Jahresabo wird jährlich verrechnet, die einmalige Aufschaltgebühr beträgt **CHF 600**. W&W empfiehlt ausdrücklich eine Schulung, die separat kostet.

| | Basic | **Professional** (Bestseller) | Enterprise |
|---|---|---|---|
| **Preis / Monat** | ab CHF 149 | ab CHF 399 | ab CHF 1'999 |
| **Preis / Jahr** | CHF 1'788 | CHF 4'788 | CHF 23'988 |
| Benutzer inkl. / max. | 1 / 5 | 3 / 20 | 10 / unbegrenzt |
| Objekte inkl. / max. | 100 / 500 | 500 / 10'000 | 5'000 / – |
| Speicher | 10 GB | 100 GB | Fair Use, 2 GB pro 100 Objekte |
| Externe User (Portal) | 25 pro 100 Objekte | 25 pro 100 Objekte | alle inklusive |
| Enthalten | Miete, STWEG, Buchhaltung, Kreditoren, e-Dossier Plus, Aufgaben, Portal Basis, Kredi Flow Basic | zusätzlich Portal, Kredi Flow Pro, Ticketing, MWST, Abnahme-App, Unterhalt/Geräte, Geschäftsmiete | alle Features, Key Account Manager, Customizing |

**Zusatzoptionen pro Monat:**

| Option | Basic | Professional | Enterprise |
|---|---|---|---|
| +1 Benutzer | CHF 50 | CHF 50 | CHF 35 |
| +100 Objekte | CHF 50 | CHF 20 | CHF 15 |
| Genossenschaft | CHF 60 | CHF 100 | inkl. |
| Mehrsprachige Korrespondenz | CHF 60 | CHF 100 | inkl. |
| Ticketing / Kredi Flow Pro | je CHF 60 | inkl. | inkl. |
| MWST / Geschäftsmiete / Unterhalt / Abnahme-App | je CHF 40 | inkl. | inkl. |
| Schnittstelle Abacus/Infoniqa | – | CHF 100 | inkl. |
| Individuelle Reports | – | CHF 100 | inkl. |
| +25 externe User pro 100 Objekte | CHF 100 | CHF 200 | inkl. |

> **Beobachtung:** Bei ImmoTop2 sind **MWST, Geschäftsmiete und mehrsprachige Korrespondenz Aufpreismodule**. Für eine Verwaltung in der Romandie oder mit Gewerbeobjekten kostet Basic schnell über CHF 300. Bei swissImmo sind genau diese Funktionen vorhanden (MWST nach beiden Methoden, Korrespondenzsprache je Mieter und Eigentümer).

### 3.3 Rimo R5 (W&W-Gruppe): für mittlere bis grosse Verwaltungen

- **Zielgruppe:** Verwaltungen ab etwa 300 Objekten, alle Sprachregionen. Deckt Miete, Stockwerkeigentum und Genossenschaften ab.
- **Preismodell:** Kauflizenz **ab CHF 4'370** (buchhaltungsprogramme.ch, Stand 2022, also veraltet) plus Wartungsvertrag. W&W selbst nennt keine Preise, die Kosten hängen von Paket, Objektzahl und Anzahl User ab.
- **Betrieb:** On-Premise (Windows Server, Sybase SQL Anywhere) oder W&W Cloud.
- **Module / Optionen:** Lohnbuchhaltung, Kreditoren, Anteilscheinverwaltung, technische Verwaltung. Dazu die kostenpflichtigen Dienste des W&W-Portals: Eigentümerportal, EasyContact, Ticketing, Kredi Flow, Abnahme-App.
- **Stärken:** über 200 Standardauswertungen, Kommunikationsassistent, CI frei gestaltbar, ausgereiftes Stockwerkeigentum.
- **Relevanz für swissImmo:** gering. Das ist Projektgeschäft mit Einführungsaufwand, der Vertriebsapparat fehlt uns.

### 3.4 Tayo: Plattform für Tickets und Abläufe

Drei Pläne, Preise nur nach einer Demo, «mengenabhängig»:

| Basecamp | **Standard** (meistgewählt) | Galaxy |
|---|---|---|
| Portal für Mieter und STWEG, Ticketverwaltung, zentrale Kommunikation, Schlüsselverwaltung, Dokumentenablage | alles aus Basecamp, dazu erweitertes Dashboard, Offerten und Arbeitsaufträge, Freigabeprozesse, Modul «Decisions» (Versammlungen), **White-Labeling**, KI-Assistent, dedizierter CSM | alles aus Standard, dazu Automatisierungen, Insights und Analysen |

- **Zusatzmodul «Checks»:** digitale Übergaben und Abnahmen mit E-Signatur und PDF. Einzeln buchbar, 10 % Rabatt in Kombination mit Standard oder Galaxy.
- **Positionierung:** Aufsatz auf ein ERP (Abacus, Garaio REM, W&W, Quorum, SAP). Hosting in der Schweiz, ISO 27001. Abacus hat sich 2021 mit CHF 1.5 Mio. beteiligt.
- **Relevanz für swissImmo:** Tayo zeigt, was Verwaltungen für **Tickets, Portal und White-Labeling** bezahlen. Das ist ein Segment, das swissImmo integriert anbietet, ohne zweites System.

### 3.5 Weitere Referenzpunkte

| Anbieter | Preis | Bemerkung |
|---|---|---|
| **LIMMOBI** | CHF 9 / 19 / 34 / 44 pro Monat **inkl. MWST** für 2 / 10 / 40 / 100 Einheiten | Alle Funktionen, unbegrenzt Nutzer, KI-Rechnungsanalyse, ZEV, STWEG. Über 100 Einheiten: Offerte. |
| **immoShome** | CHF 99 Einrichtung + CHF 25 / Monat, Dokumentenverwaltung + CHF 5 | Abrechnungswerkzeug für Private und STWEG, Objekte unbegrenzt |
| **AbaImmoLite** (Abacus) | ab CHF 480 / Monat, Fixpreis nach Objektzahl | Hosting und SaaS-Gebühren inklusive, modular ausbaubar zu AbaImmo |
| **GARAIO REM / light** | auf Anfrage | über 250 Verwaltungen, rund 2 Mio. Objekte; «light» für < 1'000 Objekte |

---

## 4. Preisvergleich nach Portfoliogrösse

Vier typische Verwaltungen, jeweils die **günstigste passende Konfiguration** laut Preisliste. Monatspreis ohne MWST, ohne einmalige Kosten.

| Szenario | Fairwalter | ImmoTop2 Cloud | LIMMOBI | **swissImmo heute** (Code) | **swissImmo Vorschlag** (MARKT.md) |
|---|---|---|---|---|---|
| **A** · 50 Objekte, 2 Nutzer | CHF 99 (Basic) | CHF 199 (Basic + 1 User) | CHF 44 inkl. MWST | CHF 95 (Pro, 1.90 × 50) | CHF 119 (Team) |
| **B** · 150 Objekte, 4 Nutzer | **CHF 299** (Prof.; Basic hat nur 3 Nutzer) | CHF 349 (Basic + 3 User + 100 Obj.)<br>CHF 449 bei gleichem Umfang (Prof. + 1 User) | Offerte | CHF 285 (Pro) | **CHF 119** (Team) |
| **C** · 400 Objekte, 8 Nutzer | CHF 359 (Prof. + 100 Obj.) | CHF 649 (Prof. + 5 User) | – | **CHF 760** (Pro) | CHF 329 (Professional) |
| **D** · 1'000 Objekte, 15 Nutzer | CHF 699 (Ent.) | CHF 1'099 (Prof. + 12 User + 500 Obj.) | – | **CHF 2'900** (Premium) / CHF 1'900 (Pro) | CHF 554 (Prof. + 500 Einh.) / CHF 749 (Ent.) |

**Einmalkosten zusätzlich:** ImmoTop2 CHF 600 Aufschaltung plus empfohlene Schulung. Fairwalter CHF 0 Aufschaltung, Import CHF 400 und CHF 200 pro Stunde für Support. immoShome CHF 99.

### Lesart

- **Das heutige Preismodell von swissImmo** (`core/views/fw/profil.py`, `ABO_PLAENE`: CHF 0.90 / 1.90 / 2.90 pro Einheit, mit Mindestpreis) ist bei kleinen Portfolios konkurrenzfähig. Ab etwa 200 Einheiten liegt es **zwei- bis viermal über Fairwalter**. Die Staffel verläuft falsch herum: Der Einheitspreis *steigt* mit der Stufe, während er im Markt mit der Menge *sinkt* (Fairwalter: CHF 2.90 → 0.70). Weil `abo_plan` heute nichts sperrt oder verrechnet, schadet das noch nicht. Die Preisseite ist aber für Kunden sichtbar.
- **Der Vorschlag aus `docs/MARKT.md`** trifft den Markt gut. Er ist in Szenario B deutlich günstiger (CHF 119 gegenüber CHF 299 bei Fairwalter) und in C und D leicht günstiger.
- **Widerspruch im Vorschlag selbst:** Mit der Zusatzposition «+100 Einheiten für CHF 45» kostet Professional bei 1'000 Einheiten **CHF 554**. Das ist günstiger als die eigene Enterprise-Stufe (CHF 749). Fairwalter löst das mit sinkenden Zusatzpreisen je Stufe (CHF 60 bzw. 40) und einem Objektdeckel. Empfehlung dazu in Abschnitt 6.2.

---

## 5. Funktionsvergleich

Legende: ✓ enthalten · ● gegen Aufpreis / höhere Stufe · ◐ teilweise · – nicht vorhanden. Der Stand von swissImmo ist aus dem Code belegt (Pfade im Anhang).

| Funktion | Fairwalter | ImmoTop2 Cloud | Tayo | LIMMOBI | **swissImmo** |
|---|:-:|:-:|:-:|:-:|:-:|
| Browser, kein Client nötig | ✓ | – (Windows-Client) | ✓ | ✓ | ✓ |
| Liegenschaftsbuchhaltung, Abschluss | ✓ | ✓ | – | ✓ | ✓ |
| Nebenkostenabrechnung | ✓ | ✓ | – | ✓ | ✓ |
| QR-Rechnung, Mahnwesen nach Art. 257d OR | ✓ | ✓ | – | ✓ | ✓ |
| camt.053-Bankabgleich / pain.001 | ◐ (Datei-Upload) | ✓ | – | ✓ (Direktanbindung 30+ Banken) | ✓ (Datei) |
| MWST | ✓ | ● (Basic +40) | – | ? | ✓ (effektiv und Saldosteuersatz) |
| Mehrsprachige Korrespondenz | ? | ● (+60 / +100) | ✓ | ? | ✓ (je Mieter/Eigentümer; Übersetzung zu ca. 90 %) |
| Mietzinsanpassung Referenzzins/LIK + amtl. Formular | ● (Rechner ab Basic) | ✓ | – | ? | ✓ (Formular für SO, ZH, BE eingebaut) |
| Kreditoren mit KI-Belegerkennung | ● (ab Basic) | ● (Kredi Flow Pro) | – | ✓ | ✓ (Groq) |
| Tickets / Schadensmeldung | ✓ | ● (Basic +60) | ✓ (Kern) | ✓ | ✓ |
| Mieterportal | – | ● (EasyContact) | ✓ | ? | ✓ (Dokumente, QR-Rechnung, Tickets) |
| Eigentümerportal | ● (ab Prof., CHF 299) | ✓ (Portal Basis) | ✓ | ? | ✓ (Report-PDF, Steuerauszug, Freigaben) |
| Wohnungsabnahme | ● (CHF 9.90 pro Abnahme) | ● (Basic +40) | ● (Modul Checks) | ? | ✓ (Raumkatalog, PDF) |
| Digitale Signatur | – | – | ✓ (Checks) | ? | ✓ (DocuSeal) |
| Mieterwechsel mit Bewerbermanagement | ◐ (Warteliste ab Basic) | ✓ (Assistent) | – | ? | ✓ (inkl. Bewerber-Scoring) |
| Verwaltungshonorar / Mandatsabrechnung | ● (ab Prof.) | ✓ | – | ? | ✓ |
| Stockwerkeigentum | ◐ | ✓ | ✓ (Decisions) | ✓ | ◐ (Wertquote, Erneuerungsfonds) |
| Genossenschaft | – | ● (+60 / +100) | – | ? | – |
| 2FA, organisationsweit erzwingbar | ✓ | ? | ✓ | ? | ✓ |
| Öffentliche API | ● (Enterprise) | ● (Schnittstellen) | ✓ (ERP-Konnektoren) | ? | – (nur Webhooks) |
| Hosting in der Schweiz | ✓ | ✓ (Azure CH) | ✓ (ISO 27001) | ✓ | **– (PythonAnywhere)** |

---

## 6. Strategische Einordnung: Wo sich swissImmo abheben kann

### 6.1 Positionierung

> **«Die vollständige Schweizer Verwaltungssoftware im Browser: Mieter- und Eigentümerportal, Abnahme, Signatur und Mehrsprachigkeit inklusive, ohne Einrichtungsgebühr und ohne Stundensatz für Support.»**

Diese Positionierung stützt sich auf vier Beobachtungen:

| Hebel | Gegenüber | Warum er trägt |
|---|---|---|
| **Portale ab der mittleren Stufe** | Fairwalter sperrt das Eigentümer-Frontend bis CHF 299; ein Mieterportal gibt es dort nicht | Das Eigentümerportal ist das sichtbarste Qualitätsmerkmal gegenüber dem Auftraggeber der Verwaltung. Bei swissImmo ist es vollständig vorhanden. |
| **Die Schweizer Pflichtfunktionen inklusive** | ImmoTop2 verlangt für MWST, Geschäftsmiete und Mehrsprachigkeit Aufpreise | Für Verwaltungen in der Romandie, im Tessin oder mit Gewerbeobjekten spart das CHF 100 bis 200 pro Monat. |
| **Abnahme und Signatur ohne Zähler** | Fairwalter verlangt CHF 9.90 pro Abnahme; Tayo und W&W verkaufen dafür eigene Module | Bei 150 Objekten und rund 15 % Mieterwechsel pro Jahr sind das etwa 23 Abnahmen, also rund CHF 225 pro Jahr allein bei Fairwalter. |
| **Kein Windows-Client, keine Einrichtung** | ImmoTop2 braucht Windows 11 mit 16 GB RAM und kostet CHF 600 Aufschaltung plus Schulung | Mac-Büros und Homeoffice können ImmoTop2 nur über Parallels bzw. VDI nutzen. |
| **Support inklusive** | Fairwalter verrechnet Ticket- und Mailsupport «nach Aufwand» (CHF 200/h) | Das ist leicht zu kommunizieren, muss aber in der Kostenrechnung gedeckt sein (siehe Risiken). |

### 6.2 Preisempfehlung

1. **Den Vorschlag aus `docs/MARKT.md` übernehmen und `ABO_PLAENE` in `core/views/fw/profil.py` ersetzen.** Die heutige Staffel pro Einheit ist ab mittlerer Portfoliogrösse nicht verkäuflich (Szenario C: CHF 760 gegenüber CHF 359). Das gehört in die Kette von PLAN-V7 D7, weil `abo_plan` durch `Abonnement` ersetzt wird.
2. **Den Widerspruch bei den Zusatzeinheiten auflösen.** Entweder den Zusatzpreis je Stufe staffeln (Team CHF 60, Professional CHF 45, Enterprise CHF 30 pro 100 Einheiten) oder Professional auf 1'000 Einheiten deckeln. Sonst kannibalisiert Professional die Enterprise-Stufe.
3. **Den Angriffspunkt Team (CHF 119, 150 Einheiten, 5 Nutzer) in den Vordergrund stellen.** Das ist die Lücke zwischen Fairwalter Basic (CHF 99, 3 Nutzer) und Professional (CHF 299). Kampagnenbotschaft: *«Ihr viertes Teammitglied kostet bei uns nicht CHF 200 im Monat.»*
4. **Das Eigentümerportal in Team aufnehmen**, nicht erst in Professional. So entsteht der klarste Funktionsvorsprung gegenüber Fairwalter.
5. **Ein Jahresabo mit Rabatt beibehalten.** Im Code sind heute 15 % hinterlegt. ImmoTop2 kennt nur das Jahresabo, Fairwalter zeigt keinen Jahresrabatt. 10 bis 15 % sind ein belastbares Argument gegenüber Fairwalter.
6. **Keinen Preiskampf mit LIMMOBI unter CHF 40.** Das bestätigt `docs/MARKT.md`: Mit dem Funktionsumfang von swissImmo und inklusive Support ist dieses Segment nicht wirtschaftlich zu bedienen.

### 6.3 Lücken, die vor dem Markteintritt geschlossen werden müssen

| Lücke | Warum sie verkaufsentscheidend ist | Priorität |
|---|---|---|
| **Hosting in der Schweiz** | Alle direkten Wettbewerber werben damit, Tayo zusätzlich mit ISO 27001. PythonAnywhere und die Groq-Belegerkennung ausserhalb der Schweiz sind in jeder Ausschreibung ein Ausschlusskriterium. | **hoch** |
| **Öffentliche Registrierung und Testphase** | Fairwalter: 30 Tage Test ohne Verkaufsgespräch. swissImmo: Organisationen nur per Management-Command. | **hoch** |
| **Amtliche Formulare für alle Pflichtkantone** | Eingebaut sind nur SO, ZH und BE. Für die Romandie (VD, GE, NE, FR) fehlt das Kernargument «Schweizer Recht eingebaut». | mittel |
| **Stockwerkeigentum** | Bei ImmoTop2, Rimo R5, Tayo und LIMMOBI ist es Standard. Viele kleine Verwaltungen betreuen Miete *und* STWEG. | mittel |
| **Öffentliche API** | Erst in der obersten Stufe relevant (Fairwalter Enterprise). Kann nachgezogen werden. | niedrig |
| **Übersetzungen** (je Sprache ca. 350 bis 425 Texte offen) | Das Argument «Mehrsprachigkeit inklusive» trägt nur, wenn die Oberfläche vollständig übersetzt ist. | mittel |

### 6.4 Risiken

- **Reaktion von W&W:** W&W kann Fairwalter jederzeit über Preis oder Bündel aufrüsten, etwa mit dem W&W-Portal. Unser Vorsprung muss auf Produkt und Bedienung beruhen, nicht allein auf dem Preis.
- **Support inklusive belastet die Marge:** Bei CHF 119 pro Monat deckt ein Kunde rund 7 Stunden Support pro Jahr, gerechnet mit dem branchenüblichen Stundensatz von CHF 200. Vor der Festlegung braucht es die Kostenrechnung pro Mandant, wie sie auch in `docs/MARKT.md` Abschnitt 9 als offener Punkt steht.
- **Fehlendes Vertrauen:** Fairwalter hat über 400 Verwaltungen, W&W über 2'800 Kunden. swissImmo braucht Referenzkunden und eine datenschutzrechtlich saubere Hosting-Aussage, bevor der Preis überhaupt zum Argument wird.

---

## 7. Grenzen dieses Audits

- **Listenpreise, keine Transaktionspreise.** Rabatte, Verbands-Konditionen (z. B. HEV) und Verhandlungsspielraum sind nicht erfasst.
- **Nicht belegt:** Preise von Tayo, GARAIO REM (light) und AbaImmo sowie aktuelle Preise von Rimo R5. Die Zahl CHF 4'370 stammt aus einer Drittquelle von 2022.
- **«?» in der Funktionsmatrix** heisst: nicht öffentlich dokumentiert, nicht «nicht vorhanden».
- **Die Funktionsmatrix von Fairwalter** wurde aus der Paketmatrix der Preisseite ausgelesen. Einzelne Zellen, etwa das Eigentümer-Frontend, erscheinen dort in mehreren Rubriken. Massgebend ist die Enterprise-Seite, die das Eigentümer-Frontend ab Professional ausweist.

---

## Anhang A: Quellen (abgerufen 29.09.2026)

| Anbieter | URL |
|---|---|
| Fairwalter Preise | https://www.fairwalter.com/preise |
| Fairwalter Enterprise | https://www.fairwalter.com/enterprise-paket |
| ImmoTop2 Cloud Preise | https://www.wwimmo.ch/produkte/preise-immotop2-cloud/ |
| ImmoTop2 Produkt / Systemvoraussetzungen | https://www.wwimmo.ch/produkte/immotop2/ |
| Rimo R5 | https://www.wwimmo.ch/produkte/rimor5/ |
| Rimo R5 Preisangabe (Drittquelle, 2022) | https://www.buchhaltungsprogramme.ch/produkt/rimo-r5/ |
| Fairwalter als W&W-Produkt | https://www.wwimmo.ch/produkte/fairwalter/ |
| Tayo Pläne | https://www.tayo-software.com/de/offers |
| Tayo / Abacus Beteiligung | https://www.organisator.ch/de/management/it/2021-09-16/abacus-research-und-tayo-software-spannen-zusammen/ |
| LIMMOBI Preise | https://limmobi.ch/de/preise/ |
| immoShome Preise | https://www.immoshome.ch/preise/ |
| AbaImmoLite | https://www.abacus.ch/abaimmolite |
| GARAIO REM light | https://www.garaio-rem.ch/de/garaio-rem-entdecken-garaio-rem-light |

## Anhang B: Belege für den Stand von swissImmo

| Aussage | Beleg |
|---|---|
| Heutige Preisstaffel pro Einheit, Jahresrabatt 15 % | `core/views/fw/profil.py` (`ABO_PLAENE`, `fw_abonnemente`) |
| Abo-Feld ohne Wirkung | `docs/ANALYSE.md` TS-11 |
| Vorschlag mit vier Stufen | `docs/MARKT.md` Abschnitt 4 |
| Nebenkosten, QR, Mahnwesen | `core/services/nk_abrechnung.py`, `core/utils/qr_code.py`, `core/services/mahnstufen.py` |
| camt.053, pain.001, MWST | `core/views/fw/bankabgleich.py`, `core/services/pain001.py`, `core/services/mwst_estv.py` |
| Mieter- und Eigentümerportal | `core/views/portal.py`, `swiss_immo/urls.py` |
| Abnahme, Signatur | `core/views/fw/abnahme.py`, `core/services/abnahme_pdf.py`, `rentals/api.py` (DocuSeal) |
| Korrespondenzsprache | `core/services/dokumentsprache.py`, `core/services/portfolio_report.py` |
| Amtliche Formulare SO, ZH, BE | `core/services/formulare/`, `docs/KANTON_FORMULARE.md` |
| 2FA | `core/services/totp.py`, `core/middleware_zweifaktor.py` |
| Hosting PythonAnywhere | `deploy.sh` |
| Organisationen nur per Command | `docs/PHASE-3-ONBOARDING.md` |
