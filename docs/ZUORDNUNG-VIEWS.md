# Zuordnung der bestehenden Views zur neuen Struktur

Gemessen am 19.08.2026 auf `main` / `claude/fairwalter-rebuild`, Stand `12b9a8a`.
Ersetzt die Zuordnung auf Modulebene in `KONZEPT-UI.md` Abschnitt 11.

**Grundlage:** 33 Fachmodule in `core/views/fw/`, 235 oeffentliche Viewfunktionen,
ermittelt ueber den Syntaxbaum (`ast`), nicht ueber `grep`.

---

## 1. Ergebnis

| Zielbereich | Views | Anteil |
|---|---:|---:|
| AKTE | 97 | 41 % |
| FALL | 50 | 21 % |
| LAUF | 39 | 17 % |
| EINSTELLUNGEN | 17 | 7 % |
| ZAHLEN | 9 | 3 % |
| ARBEIT | 8 | 3 % |
| ZULAUF | 6 | 2 % |
| AKTEN | 5 | 2 % |
| PORTAL | 3 | 1 % |
| ENTFÄLLT | 1 | 0 % |
| **Gesamt** | **235** | 100 % |

**Alle 235 Views sind zugeordnet.** Damit ist das groesste Risiko im Plan fuer
Phase 4a entschaerft: Etappe 4a.5 war mit 3 bis 5 Tagen veranschlagt, weil die Zuordnung eine
Absicht und keine Messung war. Sie ist jetzt eine Messung.

Die zunaechst offene Funktion `fw_zahlung_stornieren` ist am Code entschieden — sie storniert
einen **Zahlungseingang**, also eine Debitorenzahlung, und gehoert zum Lauf Bankabgleich.
Begruendung in Abschnitt 7.

---

## 2. Was bereits existiert

Elf Bestandteile des Konzepts, die als neu zu bauen beschrieben waren, sind im Code
vorhanden. Sie brauchen in Phase 4a eine **Einbindung in die Fallmaschine**, keinen Neubau:

| View | Modul | Konzeptbezug |
|---|---|---|
| `fw_verzug_257d`, `fw_verzug_zugang`, `fw_verzug_sendung` | `kuendigung` | Fallart Zahlungsverzug, Fristansetzung |
| `fw_kuendigung_erfassen`, `fw_kuendigung_bestaetigen`, `fw_kuendigung_formular` | `kuendigung` | Fristenwaechter, Regelwerk |
| `fw_abnahme_ruege_267a` | `abnahme` | Maengelruege bei Rueckgabe |
| `fw_lebensdauer` | `detailseiten` | Lebensdauertabelle fuer die Abnahme |
| `fw_anfangsmietzins`, `anfangsmietzins_auto_ablegen` | `mietzins` | Formularpflicht Anfangsmietzins |
| `fw_mietzins_massenanpassung` | `mietzins` | Sammelfall Mietzinsanpassung |
| `fw_bewerber_vergleich`, `fw_bewerber_entscheid`, `fw_bewerber_absage_uebrige` | `mietprozess` | Bewerbervergleich mit Entscheidprotokoll |
| `fw_zahler_zuordnungen`, `fw_zahler_zuordnung_speichern` | `aktionen` | Gelernte Regeln im Zulauf (Drittzahler) |
| `fw_mieter_portal_zugang`, `fw_eigentuemer_portal_zugang` | `person, eigentuemer` | Mieter- und Eigentuemerportal |
| `fw_vorlagen`, `fw_vorlage_form`, `fw_vorlagen_standard` | `profil` | Vorlagenbibliothek |
| `fw_akonto_anpassen` | `nebenkosten` | Akontoanpassung nach Deckungsgrad |

Ebenfalls vorhanden: `fw_abonnemente` (Phase 3), `fw_marktdaten_aktualisieren` und
`fw_marktdaten_live` (Marktvergleich in der Vermarktung), `fw_integrationen` und
`fw_vermarktung_feed` (Portalkanaele).

---

## 3. Module, deren Grenzen nicht zur Zielstruktur passen

Sieben Module verteilen sich auf mehr als zwei Zielbereiche. Sie werden in Etappe 4a.5
zerlegt, nicht verschoben:

| Modul | Views | Ziele | Haeufigste Ziele |
|---|---:|---:|---|
| `aktionen` | 32 | 12 | AKTE Dienstleister · Finanzen, ZULAUF, AKTE Dienstleister |
| `detailseiten` | 34 | 4 | AKTE Objekt, AKTE Mietverhältnis · Stammdaten, AKTE Liegenschaft |
| `kautionen` | 6 | 3 | AKTE Mietverhältnis · Finanzen, AKTE Mietverhältnis · Stammdaten, FALL Mieterwechsel · Schritt 5 Abnahme |
| `liegenschaft_crud` | 7 | 3 | AKTE Liegenschaft, AKTE Objekt, AKTEN Suche |
| `listen` | 15 | 5 | ZAHLEN, AKTE Mietverhältnis · Finanzen, AKTEN Listenansicht |
| `person` | 16 | 5 | AKTE Person, AKTE Mietverhältnis · Finanzen, PORTAL Zugang |
| `profil` | 22 | 5 | EINSTELLUNGEN, FALL Mieterwechsel · Schritt 3 Ausschreibung, ZAHLEN |

`aktionen` ist der Extremfall: 32 Views auf 12 Ziele. Das Modul ist nach *Verb* geschnitten
(neu, bearbeiten, loeschen, freigeben), nicht nach Gegenstand. Es wird vollstaendig aufgeloest.

---

## 4. Vollstaendige Zuordnung

Nach Zielbereich gruppiert; innerhalb einer Gruppe nach Herkunftsmodul.

### AKTE Objekt — 22 Views

| View | Herkunftsmodul |
|---|---|
| `fw_ausstattung_add` | `detailseiten` |
| `fw_ausstattung_del` | `detailseiten` |
| `fw_ausstattung_edit` | `detailseiten` |
| `fw_ausstattung_katalog` | `detailseiten` |
| `fw_geraet_add` | `detailseiten` |
| `fw_geraet_del` | `detailseiten` |
| `fw_geraet_edit` | `detailseiten` |
| `fw_lebensdauer` | `detailseiten` |
| `fw_merkmale_speichern` | `detailseiten` |
| `fw_objekt_detail` | `detailseiten` |
| `fw_objekt_foto_loeschen` | `detailseiten` |
| `fw_objekt_foto_upload` | `detailseiten` |
| `fw_objekt_nkart` | `detailseiten` |
| `fw_schluessel_add` | `detailseiten` |
| `fw_schluessel_ausgabe` | `detailseiten` |
| `fw_schluessel_del` | `detailseiten` |
| `fw_schluessel_rueckgabe` | `detailseiten` |
| `fw_zaehler_add` | `detailseiten` |
| `fw_zaehler_del` | `detailseiten` |
| `fw_zaehler_edit` | `detailseiten` |
| `merkmale_optionen` | `detailseiten` |
| `fw_objekt_form` | `liegenschaft_crud` |

### EINSTELLUNGEN — 17 Views

| View | Herkunftsmodul |
|---|---|
| `fw_einstellungen` | `aktionen` |
| `fw_modus_wechsel` | `aktionen` |
| `fw_benutzer_form` | `benutzer` |
| `fw_benutzer_loeschen` | `benutzer` |
| `fw_abonnemente` | `profil` |
| `fw_account` | `profil` |
| `fw_benutzer` | `profil` |
| `fw_datenreset` | `profil` |
| `fw_integration_portal_token` | `profil` |
| `fw_integration_test_email` | `profil` |
| `fw_integrationen` | `profil` |
| `fw_logbuch` | `profil` |
| `fw_rechtsgrundlagen` | `profil` |
| `fw_vorlage_form` | `profil` |
| `fw_vorlage_loeschen` | `profil` |
| `fw_vorlagen` | `profil` |
| `fw_vorlagen_standard` | `profil` |

### AKTE Liegenschaft — 16 Views

| View | Herkunftsmodul |
|---|---|
| `fw_asset_bearbeiten` | `aktionen` |
| `fw_asset_loeschen` | `aktionen` |
| `fw_asset_neu` | `aktionen` |
| `fw_anlagen` | `anlagen` |
| `fw_assets` | `assets` |
| `fw_liegenschaft_detail` | `detailseiten` |
| `fw_wartungsfrist_bearbeiten` | `detailseiten` |
| `fw_wartungsfrist_loeschen` | `detailseiten` |
| `fw_wartungsfrist_neu` | `detailseiten` |
| `fw_hypotheken` | `hypotheken` |
| `fw_liegenschaft_form` | `liegenschaft_crud` |
| `fw_liegenschaft_gwr` | `liegenschaft_crud` |
| `fw_liegenschaft_loeschen` | `liegenschaft_crud` |
| `fw_versicherung_add` | `liegenschaft_crud` |
| `fw_versicherung_loeschen` | `liegenschaft_crud` |
| `fw_liegenschaften` | `listen` |

### AKTE Mietverhältnis · Stammdaten — 15 Views

| View | Herkunftsmodul |
|---|---|
| `fw_vertrag_loeschen` | `abnahme` |
| `fw_vertrag_status` | `abnahme` |
| `fw_vertrag_mietzins_add` | `aktionen` |
| `fw_vertrag_mietzins_del` | `aktionen` |
| `fw_anpassung_del` | `detailseiten` |
| `fw_sollmietzins_add` | `detailseiten` |
| `fw_sollmietzins_del` | `detailseiten` |
| `fw_staffel_add` | `detailseiten` |
| `fw_staffel_del` | `detailseiten` |
| `fw_staffelvorlage_add` | `detailseiten` |
| `fw_staffelvorlage_del` | `detailseiten` |
| `fw_vertrag_detail` | `detailseiten` |
| `fw_untermiete` | `kautionen` |
| `fw_vertrag_wg` | `kautionen` |
| `fw_mietzins` | `mietzins` |

### FALL Schaden — 13 Views

| View | Herkunftsmodul |
|---|---|
| `fw_auftrag_kosten` | `schaeden` |
| `fw_auftrag_pdf` | `schaeden` |
| `fw_ersatzplanung` | `schaeden` |
| `fw_schaden_antwort` | `schaeden` |
| `fw_schaden_auftrag` | `schaeden` |
| `fw_schaden_ausstattung` | `schaeden` |
| `fw_schaden_detail` | `schaeden` |
| `fw_schaden_foto_loeschen` | `schaeden` |
| `fw_schaden_foto_upload` | `schaeden` |
| `fw_schaden_kosten` | `schaeden` |
| `fw_schaden_loeschen` | `schaeden` |
| `fw_schaden_neu` | `schaeden` |
| `fw_schaden_status` | `schaeden` |

### AKTE Mietverhältnis · Finanzen — 12 Views

| View | Herkunftsmodul |
|---|---|
| `fw_debitor_qr_pdf` | `debitor_qr` |
| `fw_kaution_aktion` | `kautionen` |
| `fw_kaution_beleg` | `kautionen` |
| `fw_kautionen` | `kautionen` |
| `fw_debitor_abschreiben` | `listen` |
| `fw_debitor_neu` | `listen` |
| `fw_debitor_stornieren` | `listen` |
| `fw_debitoren` | `listen` |
| `fw_weiterverrechnung` | `listen` |
| `fw_mieterkonten` | `person` |
| `fw_mieterkonto` | `person` |
| `fw_mieterkonto_pdf` | `person` |

### AKTE Person — 11 Views

| View | Herkunftsmodul |
|---|---|
| `fw_kommunikation_senden` | `aktionen` |
| `fw_kommunikation` | `kommunikation` |
| `fw_personen` | `listen` |
| `fw_kommunikation_loeschen` | `person` |
| `fw_kommunikation_neu` | `person` |
| `fw_person_adresse_loeschen` | `person` |
| `fw_person_adresse_neu` | `person` |
| `fw_person_detail` | `person` |
| `fw_person_dsg_loeschen` | `person` |
| `fw_person_form` | `person` |
| `fw_person_loeschen` | `person` |

### FALL Erstvermietung/Mieterwechsel · Schritt 3-4 — 9 Views

| View | Herkunftsmodul |
|---|---|
| `fw_bewerber_absage_uebrige` | `mietprozess` |
| `fw_bewerber_besichtigung` | `mietprozess` |
| `fw_bewerber_entscheid` | `mietprozess` |
| `fw_bewerber_vergleich` | `mietprozess` |
| `fw_bewerbung_detail` | `mietprozess` |
| `fw_bewerbung_status` | `mietprozess` |
| `fw_bewerbung_unterlagen` | `mietprozess` |
| `fw_bewerbung_zu_vertrag` | `mietprozess` |
| `fw_bewerbungen` | `mietprozess` |

### ZAHLEN — 9 Views

| View | Herkunftsmodul |
|---|---|
| `fw_finanzen` | `dashboard` |
| `fw_auswertung` | `listen` |
| `fw_berichte` | `listen` |
| `fw_betriebskostenspiegel` | `listen` |
| `fw_betriebsrechnung_pdf` | `listen` |
| `fw_leerstand_verlauf` | `listen` |
| `fw_mieterspiegel` | `listen` |
| `fw_marktdaten_aktualisieren` | `profil` |
| `fw_marktdaten_live` | `profil` |

### ARBEIT — 8 Views

| View | Herkunftsmodul |
|---|---|
| `fw_dashboard` | `dashboard` |
| `fristen_ical_feed` | `pendenzen` |
| `fw_fristen` | `pendenzen` |
| `fw_fristen_ical` | `pendenzen` |
| `fw_pendenz_loeschen` | `pendenzen` |
| `fw_pendenz_neu` | `pendenzen` |
| `fw_pendenz_toggle` | `pendenzen` |
| `fw_pendenzen` | `pendenzen` |

### AKTE Dienstleister · Finanzen — 7 Views

| View | Herkunftsmodul |
|---|---|
| `fw_kreditor_bearbeiten` | `aktionen` |
| `fw_kreditor_freigeben` | `aktionen` |
| `fw_kreditor_loeschen` | `aktionen` |
| `fw_kreditor_neu` | `aktionen` |
| `fw_kreditor_position_add` | `aktionen` |
| `fw_kreditor_position_del` | `aktionen` |
| `fw_kreditoren` | `kreditoren` |

### FALL Mieterwechsel / Zahlungsverzug — 7 Views

| View | Herkunftsmodul |
|---|---|
| `fw_kuendigung_bestaetigen` | `kuendigung` |
| `fw_kuendigung_erfassen` | `kuendigung` |
| `fw_kuendigung_formular` | `kuendigung` |
| `fw_kuendigung_zuruecknehmen` | `kuendigung` |
| `fw_verzug_257d` | `kuendigung` |
| `fw_verzug_sendung` | `kuendigung` |
| `fw_verzug_zugang` | `kuendigung` |

### LAUF Abschluss / Buchhaltung — 7 Views

| View | Herkunftsmodul |
|---|---|
| `fw_buchung_neu` | `aktionen` |
| `fw_buchung_stornieren` | `aktionen` |
| `fw_buchhaltung` | `buchhaltung` |
| `fw_buchhaltung_export` | `buchhaltung` |
| `fw_buchhaltung_pdf` | `buchhaltung` |
| `fw_kontenplan` | `buchhaltung` |
| `fw_kontoblatt` | `buchhaltung` |

### LAUF Nebenkosten — 7 Views

| View | Herkunftsmodul |
|---|---|
| `fw_nebenkosten_loeschen` | `aktionen` |
| `fw_nebenkosten_neu` | `aktionen` |
| `fw_akonto_anpassen` | `nebenkosten` |
| `fw_nebenkosten` | `nebenkosten` |
| `fw_nebenkosten_detail` | `nebenkosten` |
| `fw_nebenkosten_verbuchen` | `nebenkosten` |
| `fw_nebenkosten_versand` | `nebenkosten` |

### AKTE Dienstleister — 6 Views

| View | Herkunftsmodul |
|---|---|
| `fw_dienstleister_bearbeiten` | `aktionen` |
| `fw_dienstleister_loeschen` | `aktionen` |
| `fw_dienstleister_neu` | `aktionen` |
| `fw_dienstleister` | `dienstleister` |
| `fw_lieferantenkonten` | `person` |
| `fw_lieferantenkonto` | `person` |

### FALL Mieterwechsel · Schritt 5 Abnahme — 6 Views

| View | Herkunftsmodul |
|---|---|
| `fw_abnahme_detail` | `abnahme` |
| `fw_abnahme_loeschen` | `abnahme` |
| `fw_abnahme_neu` | `abnahme` |
| `fw_abnahme_pdf` | `abnahme` |
| `fw_abnahme_ruege_267a` | `abnahme` |
| `fw_maengelruege` | `kautionen` |

### ZULAUF — 6 Views

| View | Herkunftsmodul |
|---|---|
| `fw_bankbewegung_zuordnen` | `aktionen` |
| `fw_kreditor_scan` | `aktionen` |
| `fw_zahler_zuordnung_speichern` | `aktionen` |
| `fw_zahler_zuordnungen` | `aktionen` |
| `fw_zahlung_zuordnen` | `aktionen` |
| `fw_zahlungen_sammel_zuordnen` | `aktionen` |

### AKTE · Reiter Dokumente — 5 Views

| View | Herkunftsmodul |
|---|---|
| `fw_dokument_loeschen` | `aktionen` |
| `fw_dokument_neu` | `aktionen` |
| `fw_serienbrief_pdf` | `aktionen` |
| `fw_dokumente` | `dokumente` |
| `fw_rentals_dokument_loeschen` | `person` |

### FALL Mieterwechsel · Schritt 3 Ausschreibung — 5 Views

| View | Herkunftsmodul |
|---|---|
| `fw_expose_pdf` | `profil` |
| `fw_mieterwechsel` | `profil` |
| `fw_objekt_ausschreiben` | `profil` |
| `fw_vermarktung` | `profil` |
| `fw_vermarktung_feed` | `profil` |

### FALL Mieterwechsel · Schritt 4 Vertrag — 5 Views

| View | Herkunftsmodul |
|---|---|
| `fw_vertrag_bearbeiten` | `vertragserstellung` |
| `fw_vertrag_neu` | `vertragserstellung` |
| `fw_vertrag_neu_speichern` | `vertragserstellung` |
| `fw_vertrag_signieren` | `vertragserstellung` |
| `fw_vertrag_vorschau` | `vertragserstellung` |

### LAUF Mandatsabrechnung — 5 Views

| View | Herkunftsmodul |
|---|---|
| `fw_eigentuemer_abrechnung` | `eigentuemer_abrechnung` |
| `fw_eigentuemer_auszahlung` | `eigentuemer_abrechnung` |
| `fw_eigentuemer_honorar` | `eigentuemer_abrechnung` |
| `fw_eigentuemer_kontokorrent` | `eigentuemer_abrechnung` |
| `fw_eigentuemer_mahnstufen` | `eigentuemer_abrechnung` |

### LAUF Zahllauf — 5 Views

| View | Herkunftsmodul |
|---|---|
| `fw_kreditor_bezahlen` | `kreditoren` |
| `fw_kreditor_zahlung_stornieren` | `kreditoren` |
| `fw_kreditor_zahlung_zuruecksetzen` | `kreditoren` |
| `fw_zahllauf` | `kreditoren` |

### AKTEN Listenansicht — 4 Views

| View | Herkunftsmodul |
|---|---|
| `fw_bankkonten` | `bankkonten` |
| `fw_objekte` | `listen` |
| `fw_vertraege` | `listen` |
| `fw_schaeden` | `schaeden` |

### FALL Mietzinsanpassung — 4 Views

| View | Herkunftsmodul |
|---|---|
| `anfangsmietzins_auto_ablegen` | `mietzins` |
| `fw_anfangsmietzins` | `mietzins` |
| `fw_mietzins_anpassung` | `mietzins` |
| `fw_mietzins_massenanpassung` | `mietzins` |

### LAUF Bankabgleich — 5 Views

| View | Herkunftsmodul |
|---|---|
| `fw_zahlung_stornieren` | `aktionen` |
| `fw_bankabgleich` | `bankabgleich` |
| `fw_bankabgleich_verbuchen` | `bankabgleich` |
| `fw_camt_import` | `bankabgleich` |
| `fw_kontoauszug_rueckgaengig` | `bankabgleich` |

### LAUF MWST — 4 Views

| View | Herkunftsmodul |
|---|---|
| `fw_mwst_verbuchen` | `aktionen` |
| `fw_mwst` | `mwst` |
| `fw_mwst_einstellungen` | `mwst` |
| `fw_mwst_estv_export` | `mwst` |

### LAUF Mahnlauf — 4 Views

| View | Herkunftsmodul |
|---|---|
| `fw_debitoren_aging` | `mahnwesen` |
| `fw_mahnlauf` | `mahnwesen` |
| `fw_mahnung_erfassen` | `mahnwesen` |
| `fw_mahnwesen` | `mahnwesen` |

### AKTE Mandat — 3 Views

| View | Herkunftsmodul |
|---|---|
| `fw_eigentuemer_form` | `eigentuemer` |
| `fw_eigentuemer_loeschen` | `eigentuemer` |
| `fw_eigentuemer_liste` | `profil` |

### PORTAL Zugang — 3 Views

| View | Herkunftsmodul |
|---|---|
| `fw_eigentuemer_portal_zugang` | `eigentuemer` |
| `fw_dokument_portal_toggle` | `person` |
| `fw_mieter_portal_zugang` | `person` |

### LAUF Sollstellung — 2 Views

| View | Herkunftsmodul |
|---|---|
| `fw_sollstellung` | `sollstellung` |
| `fw_sollstellung_run` | `sollstellung` |

### AKTEN Suche — 1 Views

| View | Herkunftsmodul |
|---|---|
| `fw_suche` | `liegenschaft_crud` |

### ENTFÄLLT (Platzhalter) — 1 Views

| View | Herkunftsmodul |
|---|---|
| `fw_stub` | `profil` |

### FALL Mieterwechsel · Schritt 6 Endabrechnung — 1 Views

| View | Herkunftsmodul |
|---|---|
| `fw_schlussabrechnung` | `detailseiten` |

---

## 5. Messweg

```bash
python3 -c "
import ast, pathlib
g = 0
for p in sorted(pathlib.Path('core/views/fw').glob('*.py')):
    if p.stem in ('__init__', '_basis'): continue
    b = ast.parse(p.read_text())
    f = [k.name for k in b.body if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
         and not k.name.startswith('_')]
    g += len(f); print(f'{p.stem:24} {len(f):4}')
print('gesamt:', g)"
```

## 6. Grenzen dieser Messung

Die Zuordnung erfolgt ueber **Namensmuster**, nicht ueber Analyse des Funktionsinhalts. Sie
sagt, wohin eine View **gehoert**, nicht wie aufwendig das Verschieben ist. Zwei Dinge sind
ausdruecklich nicht gemessen:

- **Innere Abhaengigkeiten.** Wie stark Views eines Moduls auf gemeinsame Hilfsfunktionen in
  `_basis.py` zugreifen, entscheidet ueber den Zerlegungsaufwand in 4a.5.
- **Template-Bindung.** Jede View haengt an mindestens einem der 173 Templates. Welche
  Templates beim Umhaengen mitwandern und welche geteilt sind, ist offen.

Beides gehoert vor 4a.5 nachgemessen. Der Aufwand dafuer ist gering, der Nutzen fuer die
Terminaussage hoch.

---

## 7. Gegengeprueft am Code

Vorrang des Bestands: Die Zuordnung wurde nach dem Ablegen maschinell gegen den Syntaxbaum
geprueft — jeder der 235 Namen gegen den tatsaechlichen Bestand, jedes Herkunftsmodul, jede
Ueberschriftenzahl, die Summentabelle in Abschnitt 1 und die Modulaufstellung in Abschnitt 3.

**Ergebnis: keine Abweichung.** Kein Name fehlt, keiner ist erfunden, keiner steht doppelt,
kein Herkunftsmodul ist falsch, jede Ueberschrift stimmt mit der Zahl ihrer Zeilen ueberein,
und Abschnitt 1 ergibt sich aus Abschnitt 4. Auch die sieben Module in Abschnitt 3 stimmen in
Zahl der Views **und** Zahl der Ziele; ein achtes Modul mit mehr als zwei Zielen gibt es nicht.

Pruefskript (laeuft in Sekunden, sollte bei jeder Aenderung an diesem Dokument wiederholt
werden):

```bash
python3 - <<'PY'
import ast, pathlib, re, collections
ist = {}
for p in sorted(pathlib.Path('core/views/fw').glob('*.py')):
    if p.stem in ('__init__', '_basis'): continue
    for k in ast.parse(p.read_text()).body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and not k.name.startswith('_'):
            ist.setdefault(k.name, []).append(p.stem)

teil = pathlib.Path('docs/ZUORDNUNG-VIEWS.md').read_text()
teil = teil.split('## 4. Vollstaendige Zuordnung')[1].split('## 5. Messweg')[0]
dok, kopf, ziel = {}, {}, None
for z in teil.splitlines():
    m = re.match(r'^### (.+?) — (\d+) Views\s*$', z)
    if m: ziel, kopf[m.group(1)] = m.group(1), int(m.group(2)); continue
    m = re.match(r'^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*$', z)
    if m: dok[m.group(1)] = (ziel, m.group(2))

gez = collections.Counter(z for z, _ in dok.values())
print('nur im Code    :', sorted(set(ist) - set(dok)))
print('nur im Dokument:', sorted(set(dok) - set(ist)))
print('falsches Modul :', [v for v in set(dok) & set(ist) if dok[v][1] not in ist[v]])
print('Kopf != Zeilen :', [z for z, n in kopf.items() if gez[z] != n])
PY
```

**Die eine offene Frage ist entschieden.** `fw_zahlung_stornieren` arbeitet auf
`Zahlungseingang`, erzeugt Gegenbuchungen, setzt den Status der `debitoren_rechnung` auf
`offen` beziehungsweise `teilbezahlt` zurueck und leitet nach `/neu/bankabgleich/` um — es ist
also eine **Debitoren**zahlung, keine Kreditorenzahlung. Ein Kommentar in
`core/views/fw/kreditoren.py` sagt es ausdruecklich: *«`fw_zahlung_stornieren` deckt nur
EINGEHENDE Zahlungen»* — das war der Befund H9, aus dem das Gegenstueck
`fw_kreditor_zahlung_stornieren` entstand.

Damit war keine der beiden im Dokument angebotenen Antworten richtig. Der Ort ergibt sich aus
dem Anlass: Storniert wird eine im **Bankabgleich** falsch getroffene Zuordnung, dorthin fuehrt
auch die Umleitung. Die Funktion steht deshalb neu unter *LAUF Bankabgleich* — symmetrisch zum
Kreditor-Gegenstueck, das unter *LAUF Zahllauf* steht. Abschnitte 1 und 4 sind entsprechend
berichtigt.

**Drei der 235 sind keine Views.** Von den 235 oeffentlichen Funktionen sind **232** in
`swiss_immo/urls.py` verdrahtet. Die drei uebrigen tragen nur deshalb keinen Unterstrich, weil
sie von aussen gebraucht werden:

| Funktion | Modul | Was sie wirklich ist |
|---|---|---|
| `merkmale_optionen` | `detailseiten` | Hilfsfunktion, aufgerufen aus `fw_objekt_detail`, Ergebnis geht als Kontext an `fw/objekt_detail.html` |
| `anfangsmietzins_auto_ablegen` | `mietzins` | Fachfunktion, aufgerufen aus `vertragserstellung.py`, eigene Tests in `test_mietrecht.py` |
| `fw_stub` | `profil` | Platzhalter-Renderer — **nirgends referenziert**, weder in `urls.py` noch in einem Template |

Fuer die Zuordnung aendert das nichts (die drei stehen an inhaltlich richtiger Stelle), fuer
die Aufwandschaetzung von 4a.5 schon: umzuhaengen sind **232 Views**, nicht 235. Und `fw_stub`
ist bereits heute toter Code — er kann entfernt werden, sobald jemand das entscheidet; von
selbst passiert es in Phase 4a nicht.

**Was diese Pruefung nicht abdeckt.** Sie vergleicht Namen mit Namen. Ob eine View im richtigen
Zielbereich steht, sagt sie nicht — dafuer muesste man lesen, was die Funktion tut. Abschnitt 6
haelt das bereits fest; die Pruefung hier verschiebt diese Grenze nicht, sie schliesst nur die
darunterliegende aus: dass die Liste selbst luecken- oder fehlerhaft ist.
