# Auditbericht — Mandantentrennung, Phase 2

**Datum:** 18.08.2026
**Bereich:** `d0b5d39..HEAD` — 20 Commits, 102 Dateien, +5'753 / −556 Zeilen
**Agent:** `mandanten-auditor`, Auftrag in `docs/AUFTRAG-AUDIT.md`

---

## Warum am Stück gelesen wurde — und was das gebracht hat

Jeder einzelne PR der Etappe 6 war für sich geprüft. Der Auftrag verlangte trotzdem den Blick aufs Ganze, mit der Begründung: **Lücken entstehen an den Nahtstellen, nicht in der Mitte.**

Die Begründung hat getragen. Von den Funden unten war **kein einziger** in einem der PRs sichtbar, in dem er entstand. Der schwerste — der Datenreset, der alle Verwaltungen löscht — steckte in einer Zeile, die **am Vortag angefasst** worden war, ohne dass jemand die fehlende Einschränkung bemerkte: Der Blick galt der Frage „welche Tabellen gibt es", nicht der Frage „wessen Daten".

---

## Zusammenfassung

| Stufe | Anzahl | Status |
|---|---|---|
| **Leck** — fremde Daten erreichbar oder veränderbar | 3 | alle behoben |
| **Lücke** — noch kein Leck, aber die Isolation hängt an einer Stelle | 4 | 3 behoben, 1 begründet offen |
| **Hinweis** | 5 | 3 behoben, 1 bewusst verworfen, 1 offen |

Dazu aus der Vorbereitung des Audits, gleiche Wurzel, ebenfalls behoben: sechs anonyme Einstiegspunkte, die seit Etappe 6.2 mit einem Serverfehler antworteten.

---

## LECK

### L1 — «Meine Daten zurücksetzen» löschte den Bestand **aller** Verwaltungen

`core/views/fw/profil.py`, `fw_datenreset`

Die View sammelte alle Tabellen der eigenen Apps und führte `DELETE FROM "<tabelle>"` aus — **ohne jede Einschränkung auf die Organisation**. Zugang: Rolle Verwalter, kein Superuser nötig, ein Bestätigungswort.

Gemessen (zwei Verwaltungen, Mitgliedschaft nur in A):

```
vorher   A(LG, Mieter) = (12, 49)   B(LG, Mieter) = (1, 1)
POST /neu/datenreset/ {'bestaetigung': 'LÖSCHEN'}  →  302
nachher  A(LG, Mieter) = (0, 0)     B(LG, Mieter) = (0, 0)
```

Für B war es unsichtbar: Mitgliedschaft und Verwaltungsdaten blieben stehen, die Anmeldung funktionierte weiter, die Anwendung war einfach leer. Nicht wiederherstellbar ausser aus der Sicherung.

**Behoben.** Gelöscht wird jetzt über die **Modelle** statt über die Tabelle: Im gesetzten Kontext schränkt der `TenantManager` bereits ein, Modelle ohne Mandantenfilter werden übersprungen. Der bestehende `test_reset_loescht_alles` prüfte, *dass* gelöscht wird — nicht, für wen; `DatenresetTests` prüft jetzt beides.

### L2 — Vier überlebende `Organisation.objects.first()`, versteckt hinter einem Alias

```
core/utils/billing.py:269              Verwaltungshonorar auf der NK-Abrechnung
core/views/fw/listen.py:450            Absenderblock inkl. IBAN (Weiterverrechnung)
core/views/fw/detailseiten.py:389      Referenzzins + LIK als Basis nach OR 269a
core/views/fw/vertragserstellung.py    toter `or`-Rückfall
```

Das Muster war `from crm.models import Organisation as _Vw` … `_Vw.objects.first()`. `Organisation` trägt bewusst keinen `TenantManager` — die Aufrufe ignorierten den Kontext also vollständig und lieferten immer die erste Verwaltung der Installation.

Wirkung, je Stelle: Das **Honorar** ist ein Geldbetrag auf einer Abrechnung, die dem Mieter zugestellt wird. Die **IBAN** im Absender kann heissen, dass der Mieter an die falsche Bankverbindung zahlt. **Referenzzins und LIK** sind die Begründung einer Mietzinsanpassung nach OR 269a.

**Der eigentliche Fund ist die Zählung.** `grep "Organisation.objects.first()"` liefert im Produktivcode null Treffer — der Alias machte sie blind. Der geplante Abschlussvermerk *„von 76 auf 0"* wäre **falsch** gewesen; er war 4. Dieselbe Fehlerform wie beim Suite-Skript, das grün meldete für die Module, an die es gedacht hatte.

**Behoben**, alle vier auf den Bezug des Datensatzes umgestellt. Und die Zählung ersetzt: `KeinRatenDerVerwaltungTests` prüft per AST auf das **Muster**, löst dabei Import-Aliase auf und hat eine Gegenprobe, dass es den Alias wirklich sieht.

### L3 — Anonyme Schadenmeldung fiel auf `Liegenschaft.objects.first()` zurück

`core/views/ticket_public.py`

Liess sich die Adresse eines anonymen Melders nicht zuordnen, wurde die Meldung der **ersten Liegenschaft der Installation** angehängt — mit Vor- und Nachname, E-Mail, Telefon, Adressfreitext und Foto. Bei zwei Verwaltungen landet die Meldung eines Mieters von B in der Ticketliste von A.

Zum Fundzeitpunkt nicht auslösbar, weil dieselbe View elf Zeilen früher an `Mieter.objects` abbrach (Lü1) — also latent, und beim Beheben von Lü1 scharf geworden.

**Behoben, ohne Rückfall.** Eine Meldung ohne zuordenbare Liegenschaft wird **nicht** angelegt; der Melder bekommt die Rückfrage, seine Liegenschaft zu wählen. Eine erfundene Zuordnung ist schlechter als eine ehrliche Rückfrage.

---

## LÜCKE

### Lü1 — Die öffentlichen Schadenmelde-Endpunkte antworteten mit 500

`core/views/ticket_public.py` — QR-Aushang `/report/<id>/` und allgemeines Formular

```
GET  /report/1/        → 500   OrganisationsFehler: portfolio.Liegenschaft.objects …
POST /schaden/melden/  → 500   OrganisationsFehler: crm.Mieter.objects …
```

Kein Leck — fail-closed, die beabsichtigte Wirkung des Managers. Aufgeführt, weil es **exakt die Klasse** der sechs bereits behobenen anonymen Einstiegspunkte ist und auf keiner Liste stand: Wer die anderen repariert und diesen übersieht, hält die Reihe für abgeschlossen.

**Behoben** nach demselben Muster: Objekt über `alle_organisationen` finden, dann `kontext_des_objekts(...)` — sonst läuft alles danach (Einheitenliste, Ticket, Foto-Ablage) weiter ohne Kontext.

### Lü2 — Fehlgeschlagene Anmeldungen wurden nicht mehr protokolliert

`core/signals.py`, `core/auth.py`

Eine anonyme Anmeldeseite hat keinen Mandantenkontext, `AktivitaetsLog` verlangt aber eine Organisation. Ohne Benutzer fand `log_aktion` keine, das Schreiben warf, und die Ausnahme wurde geschluckt — bewusst, damit ein misslungener Protokolleintrag die eigentliche Aktion nicht abbricht.

Gemessen, gleiche Datenbank, kein Kontext:

```
d0b5d39 :  AktivitaetsLog 546 → 547   (Eintrag geschrieben)
HEAD    :  AktivitaetsLog 546 → 546   (kein Eintrag)
```

Brute-Force-Versuche hinterliessen keine Spur, obwohl die Kategorie `sicherheit` als revisionsrelevant gilt. Der zugehörige Test blieb grün, weil `_helfer._test_organisation()` beiläufig einen Kontext setzt — er prüfte den Fehlversuch in einer Welt, die es bei einer anonymen Anfrage nie gibt.

**Behoben für den wichtigen Fall:** Der Angriff gilt fast immer einem **bestehenden** Konto. Der Fehlversuch löst den Benutzer jetzt am versuchten Namen auf; über seine Mitgliedschaft steht die Verwaltung fest, und der Eintrag wird geschrieben.

**Offen und bewusst so:** Ein Versuch mit einem völlig **unbekannten** Namen gehört keiner Verwaltung. Er geht jetzt mit `WARNING` ins Server-Log statt spurlos zu verschwinden — eine Spur ausserhalb der Datenbank ist unendlich viel mehr als keine. Die saubere Lösung wäre ein mandantenfreies Sicherheitslog oder eine für diese Kategorie nullbare Spalte; **das ist eine Modellentscheidung und gehört vorgelegt, nicht nebenbei getroffen.**

### Lü3 — `User.delete()` an fünf weiteren Stellen riss geteilte Konten mit

`core/views/fw/eigentuemer.py` (2×), `core/views/fw/person.py` (2×), `core/services/dsg.py`

Dieselbe Wurzel wie in `fw_benutzer_loeschen`, nur an den Portalpfaden: `Mitgliedschaft.benutzer` ist `CASCADE`, die Profilverknüpfungen sind `SET_NULL`. Ein `delete()` in Verwaltung A entfernte den Menschen **überall**.

Wie real: Die Anlage-Pfade erzeugen neue Konten mit Suffix, verknüpfen also nicht automatisch. Ein geteiltes Konto entsteht nur, wenn jemand es bewusst anlegt — was das Modell ausdrücklich vorsieht und was die **einzige Begründung** dafür ist, dass `Benutzer` keinen Organisationsbezug trägt.

**Behoben** über einen gemeinsamen Helfer `core.auth.konto_freigeben(benutzer, organisation)`: Mitgliedschaft dieser Verwaltung lösen, Konto nur fallen lassen, wenn danach **weder** Mitgliedschaft **noch** Mieter- oder Eigentümerprofil daran hängt. Der bereits korrigierte `benutzer.py`-Pfad prüfte nur die Mitgliedschaft — der Helfer prüft beides.

### Lü4 — Die Rückbezugs-Ausnahme trägt, ist aber nicht durch einen Test gesichert

`core/tenancy.py`: `if getattr(self, 'instance', None) is not None: return qs`

Die Begründung hält, soweit prüfbar: Ein Rückbezug geht immer von einem geladenen Objekt aus, und dessen Kinder leiten ihre Organisation aus dieser Kette ab. Für alle im Diff berührten Pfade nachvollzogen, kein Gegenbeispiel gefunden.

Was die Zusage trägt, ist aber eine **unausgesprochene zweite Bedingung**: Sie gilt nur, solange niemand ein Objekt der beiden ungefilterten Modelle (`benutzer.Benutzer`, `crm.Organisation`) aus einer Benutzereingabe holt und dann traversiert. Heute sauber — geprüft: genau eine request-gespeiste Organisations-ID (der signierte iCal-Token) und ein `get_object_or_404(User, …)` (hinter `_team_benutzer_oder_404`).

**Bewusst offen gelassen.** Die Isolation hängt hier an Aufmerksamkeit statt an einer Schranke, und das ist die Definition einer Lücke. Ein Registry-Test in der Art der bestehenden wäre der richtige Schluss — er gehört in denselben Zug wie die Modellentscheidung aus Lü2 und nicht in diesen Bericht.

---

## HINWEIS

**H1 — Ein Drittel des Leck-Detektors konnte nie feuern.** `test_isolation.VERRAETERISCH` enthielt `'Testgasse'` — die Zeichenkette kommt im ganzen Projekt nur in dieser Zeile vor; das Fixture legt B's Mieter unter `B-Gasse 2` an. Ein Marker, der nichts findet, sieht aus wie einer, der nichts zu finden hat. **Behoben** (`'B-Gasse'`, `'B-Weg'`). Der zweite Teil des Hinweises bleibt offen: Bei den `*_pdf`-Routen steht der Text komprimiert im Datenstrom, eine Rohsuche findet ihn nie — `AbsenderInDokumentenTests` löst das für seinen Fall mit `pdfplumber`, der Registrylauf noch nicht.

**H2 — Alt-Objektfotos waren anonym nicht mehr abrufbar.** `ist_objektfoto()` lief ohne Kontext, warf, und das `except Exception: return False` verschluckte es — die Funktion sagte für jedes Alt-Bild `False`. Damit lief genau die Zusage ins Leere, die ihr Docstring gibt („damit bereits veröffentlichte Inserate nicht ins Leere laufen"). Fail-closed, also kein Leck, aber still. **Behoben** über `alle_organisationen`; das breite `except` ist entfernt.

**H3 — `/bewerben/<id>/datenschutz/` nennt für jede Objektnummer die zuständige Verwaltung.** Der Vorschlag war dieselbe 410-Schranke wie im Bewerbungsformular. **Bewusst verworfen**, und der Versuch hat gezeigt warum: Er machte `test_mit_objekt_nennt_die_verwaltung_des_objekts` rot. Preisgegeben werden Geschäftsdaten der Verwaltung, keine Mieterdaten, und sie stehen ohnehin in jedem Inserat. Dagegen steht: Wer sich beworben hat, muss **später** nachlesen können, wer die Daten erhoben hat — daran hängen Auskunfts- und Löschbegehren nach revDSG. Eine Wohnung ist Tage nach der Bewerbung nicht mehr ausgeschrieben; die Erklärung dann wegzunehmen kehrte den Zweck der Vorschrift um. Die Begründung steht jetzt im Code.

**H4 — Namensraum-Orakel beim Anlegen eines Team-Benutzers.** `„Benutzername '…' ist bereits vergeben"` verrät, ob eine E-Mail-Adresse irgendwo in der Installation als Mieter, Eigentümer oder Teammitglied existiert (Portalkonten tragen die Adresse als Benutzernamen). Dem geteilten `auth_user.username`-Unique inhärent, nicht durch diesen Diff entstanden; auflösbar nur über mandantenpräfixierte oder nicht rückschliessbare Benutzernamen. **Offen**, als Entscheidung vermerkt.

**H5 — `core.tenancy.cache_key()` ist gebaut, aber nirgends verwendet.** Die beiden realen Cache-Nutzer sind der LIK-Cache (nationale Zahl — geteilt ist dort richtig) und die Ratenbremse (Schlüssel je IP; kein Datenleck, aber ein gemeinsames Kontingent). Regel 4 des Skills ist erfüllt, die Funktion selbst ist Vorrat. **Offen**, bewusst.

---

## Prüfpunkt 3 des Auftrags — die drei handgeschriebenen `organisation=`-Filter

Kriterium: **Was passiert ohne Kontext?**

| Stelle | Filterwert | Ohne Kontext | Urteil |
|---|---|---|---|
| `check_rents.py` | aus der eigenen Schleife | `Mietvertrag.objects` wirft, bevor der Filter greift | redundant, **nicht schwächer** ✔ |
| `fristen_digest.py` | aus der eigenen Schleife | `Pendenz.objects` wirft | redundant, **nicht schwächer** ✔ |
| `detailseiten.py` | `request.organisation` | `Lebensdauer.objects.filter(...)` ruft `get_queryset()` sofort auf → wirft | redundant, **nicht schwächer** ✔ |

Der entfernte vierte (`_global_filter`) war tatsächlich schwächer: Er übersprang den Filter bei `organisation is None` kommentarlos. Bei den drei verbliebenen kann das nicht passieren, weil der Manager **vor** dem Filter wirft.

**Eine Einschränkung, die genannt gehört:** Bei `detailseiten.py` speist derselbe `request.organisation`-Wert auch die Schreibpfade. Er ist heute deckungsgleich mit dem Kontext, weil die Middleware beide aus derselben Quelle setzt. Käme eine Organisationsauswahl in der Sitzung oder ein verschachtelter `organisation_kontext()` innerhalb einer Anfrage dazu, könnten die beiden auseinanderlaufen — dann schriebe die View gegen einen anderen Mandanten, als sie liest.

---

## Was geprüft und in Ordnung befunden wurde

- **`TenantManager` an den Modellen.** Über die Registry gemessen: **63 von 65** Modellen haben einen filternden `_default_manager`. Ungefiltert sind nur `benutzer.Benutzer` und `crm.Organisation` — die beiden dokumentierten Ausnahmen.
- **Schreib- und Stornopfade.** Debitoren-, Kreditoren-, Eigentümer-, Vorlagen- und Schadenpfade holen ihr Objekt über den gefilterten Manager. Der Systemvorlagen-Schutz ist der richtige Schnitt.
- **Hintergrundläufe.** Alle zehn laufen je Organisation mit gesetztem Kontext; `je_organisation` fängt je Verwaltung und setzt den Exitcode.
- **Exporte.** Logbuch-CSV/PDF, Journal-CSV, MWST-CSV, Vermarktungs-Feed — alle auf eine Organisation begrenzt. **Die Frage des Auftrags — bekommt ein Superuser einen Gesamtexport? — lautet: nein**, er bekommt einen `OrganisationsFehler`. Besonders: `sicherung.py` gibt `dumpdata` ausdrücklich `all=True` mit; ohne das wäre die Sicherung stillschweigend einmandantig geworden.
- **Dateiablage.** `organisation/<id>/`-Präfix greift, `ohne_organisationspraefix` verhindert die Sensibilitäts-Falle, `gehoert_zur_eigenen_organisation` verweigert bei nicht bestimmbarer Zugehörigkeit. Der stärkste Teil dieses Diffs.
- **Absender.** Durchweg vom Objekt genommen; an einem echten PDF mit Textextraktion geprüft.
- **Unique-Constraints.** Konto, Belegnummer und Lebensdauer je Organisation — belegt.
- **`alle_organisationen`.** 20 Fundstellen durchgesehen; jede trägt eine Begründung, und keine ist breiter als nötig.

---

## Was **nicht** geprüft wurde

Damit dieser Bericht keine Tiefe suggeriert, die es nicht gab:

- **Keine Mutationsprüfung durch den Auditor.** Ausser den ausdrücklich belegten Vorher/Nachher-Messungen ist seine Aussage zur Wirksamkeit der Tests *gelesen, nicht gemessen*. (Die elf Gegenproben zu den Behebungen sind separat ausgeführt und unten protokolliert.)
- **Elf Testdateien ungelesen**, darunter `test_scheduler_organisation.py`, `test_tenant_manager.py`, `test_vorlagen_isolation.py`, `tests_perf*.py`. Von `test_isolation.py` etwa die Hälfte.
- **Der PostgreSQL-Umzug ist nicht auditiert** — `umzug_postgres.sh`, `postgres_anlegen.py`, `sequenzen_richten.py`, `deploy.sh` und die Dokumente wurden nicht gelesen. Insbesondere offen: ob `sequenzen_richten` je Organisation etwas anfasst.
- **Die Portale nur auf Mandantenebene.** Nicht systematisch geprüft: Darf Mieter X das Dokument von Mieter Y *derselben* Verwaltung laden? Das ist eine andere Grenze als die auditierte — sie liegt aber nah.
- **Der Django-Admin.** `AdminUmgehungTests` behauptet, dass nichts Fremdes erscheint; der Bestand selbst wurde nicht durchgesehen.

---

## Gegenproben zu den Behebungen (18.08.2026)

Je Sicherung einzeln ausgehebelt, zugehöriger Test muss rot werden. Alle elf bestanden:

| Ausgehebelt | Test wird rot |
|---|---|
| Datenreset wieder über alle Mandanten | `DatenresetTests` |
| Honorar wieder aus der ersten Verwaltung | `test_kein_objects_first_auf_der_organisation` |
| Fehlversuch wieder ohne Benutzer melden | `FehlversuchProtokollTests` |
| Konto wieder immer ganz löschen | `GeteiltesKontoPortalTests` |
| Bewerbung wieder über `objects` | `BewerbungsformularTests` |
| DocuSeal wieder über `objects` | `DocusealWebhookTests` |
| Brevo wieder über `objects` | `BrevoWebhookTests` |
| iCal-Token wieder ohne Verwaltung | `IcalFeedTests` |
| Vorlagen-Seed wieder mit Kontext | `VorlagenSeedTests` |
| `None` bedeutet wieder „alle" | `MarktdatenBedeutungTests` |
| Konto wieder ganz löschen (Team) | `GeteiltesKontoTests` |

---

## Offen nach diesem Audit

1. **Modellentscheidung Sicherheitslog** (Lü2): mandantenfreies Log oder für die Kategorie `sicherheit` nullbare Spalte.
2. **Registry-Wächter für die zwei ungefilterten Modelle** (Lü4).
3. **PDF-Textextraktion im Registrylauf** (H1, zweiter Teil).
4. **Namensraum-Orakel** (H4) — braucht ein anderes Benutzernamen-Schema.
5. **`cache_key` anwenden oder als Vorrat kennzeichnen** (H5).
6. **Der PostgreSQL-Umzug ist nicht auditiert** — vor dem Umzug nachholen.
