# Entitlements — die zentrale Prüfstelle (P3.1)

Entwurf zur Entscheidung, kein Umbau. Stand 20.09.2026, gemessen gegen `8656b24`.

`docs/MARKT.md` hat den kaufmännischen Teil erledigt: vier Stufen, Preise,
Modulzuschnitt, Verhalten bei Downgrade und Zahlungsausfall. Diese Notiz ist
das technische Gegenstück und beantwortet genau eine Frage: **Wie wird aus
diesen Tabellen Code, ohne dass die Regeln über 329 Ansichten verstreuen?**

---

## 0. Was heute gilt — nachgemessen, nicht erinnert

| | Befund |
|---|---|
| `Organisation.abo_plan` | `CharField`, drei Stufen (`start`/`pro`/`premium`), Standard `'pro'` |
| Stellen, die ihn abfragen | **keine** — 6 Treffer im ganzen Bestand: 4 in `profil.py`, 1 Felddefinition, 1 Test |
| Planwechsel | POST auf `/neu/abonnement/` setzt das Feld. Keine Zahlung, keine Prüfung, kein Übergang |
| Speicher-Buchhaltung | **existiert nicht.** Die 5/50/150/300 GB aus MARKT.md haben heute keine Messgrundlage |
| Nutzerzählung | über `crm.Mitgliedschaft` möglich. Achtung: zählt Mitgliedschaften, nicht Menschen — eine Person kann in mehreren Verwaltungen arbeiten |
| Einheitenzählung | `Einheit.objects.count()` ist durch den `TenantManager` bereits je Organisation |

Heute hat also jede Verwaltung jede Funktion, und die Preisseite ist eine
Absichtserklärung. Für Phase 3 heisst das: **Es gibt nichts abzulösen, nur
etwas einzuziehen.** Das ist die angenehme Ausgangslage — kein Bestand an
verstreuten Prüfungen, den man erst einsammeln müsste.

---

## 1. Was diese Notiz nicht entscheidet

Der Zuschnitt der Stufen, die Preise, der Zahlungsanbieter und die Frage, was
mit dem versprochenen «API-Zugang» geschieht. Das steht in MARKT.md zur
Entscheidung und ist kaufmännisch, nicht technisch.

Ebenfalls nicht: ob zuerst 2FA oder zuerst Entitlements gebaut wird. MARKT.md
nennt beide als Marktvoraussetzung.

---

## 2. Drei Sorten Sperre, die man nicht vermischen darf

Der häufigste Entwurfsfehler wäre, alles über eine Funktion `darf(...)` zu
lösen. Die drei Sorten verhalten sich unterschiedlich, und zwar in genau dem
Punkt, auf den es ankommt: **wann** geprüft wird.

### A. Funktion — ja oder nein

«Eigentümerportal ab Team», «pain.001 ab Professional». Binär, hängt allein an
der Stufe, ändert sich nur beim Planwechsel.

Geprüft wird **beim Aufruf**, und zwar wie eine Rolle.

### B. Grenze — wie viele

«150 Einheiten», «5 Nutzer», «50 GB». Zählbar, und der entscheidende Satz aus
MARKT.md lautet: *Alle Daten lesbar und exportierbar, keine neuen dazu.*

Geprüft wird also **beim Anlegen**, nie beim Lesen. Eine Verwaltung mit 200
Einheiten auf einem 150er-Plan sieht weiterhin alle 200 — sie kann nur keine
201. anlegen. Wer hier am Lesepfad prüft, baut genau den Datenverlust, den die
Projektanweisung ausschliesst.

### C. Zustand — wie weit überhaupt

Zahlung offen seit 15 Tagen: nur noch Lesen und Export. Seit 31: nur noch
Export. Das betrifft **jede** Anfrage und keine einzelne Funktion.

Geprüft wird deshalb **vor allem anderen**, in einer Middleware — nicht an 329
Ansichten.

> **Die Vermischung ist der Fehler.** Eine Grenze als Funktion zu behandeln
> sperrt das Lesen. Einen Zustand als Funktion zu behandeln heisst, ihn 329
> Mal zu vergessen.

---

## 3. Der Entwurf

### 3.1 Eine Datei, die alles weiss

`core/entitlements.py` — die einzige Stelle, an der die Tabellen aus MARKT.md
als Code stehen:

```python
STUFEN = ('start', 'team', 'professional', 'enterprise')   # aufsteigend

#: Funktion -> ab welcher Stufe. Alles, was hier NICHT steht, ist frei.
MERKMALE = {
    'eigentuemerportal':  'team',
    'mieterportal':       'team',
    'monatslauf':         'team',
    'mahnlauf':           'team',
    'ki_belegerkennung':  'team',
    'eigenes_logo':       'team',
    'mandatsabrechnung':  'professional',
    'konsolidierung':     'professional',
    'pain001':            'professional',
    'branding':           'professional',
}

#: Grenze -> Wert je Stufe.
GRENZEN = {
    'einheiten': {'start': 25, 'team': 150, 'professional': 500, 'enterprise': 2000},
    'nutzer':    {'start': 2,  'team': 5,   'professional': 15,  'enterprise': None},
    'speicher':  {'start': 5,  'team': 50,  'professional': 150, 'enterprise': 300},  # GB
}
```

Dass diese Tabellen **wörtlich** den Tabellen in MARKT.md entsprechen, gehört
in einen Test. Zwei Quellen für dieselbe Zahl sind die Stelle, an der Preis
und Programm auseinanderlaufen.

### 3.2 Die Funktionssperre sieht aus wie eine Rolle

Der Bestand hat dafür bereits ein gutes Muster: `rolle_erforderlich` prüft
nicht nur, sondern **merkt sich die Anforderung an der View** (`benoetigte_
rollen`), damit die Oberfläche Einträge ausgrauen kann, statt den Benutzer in
eine Absage laufen zu lassen. Genau das braucht eine Abo-Sperre auch — ein
Schloss neben dem Menüeintrag verkauft, eine 403-Seite verärgert.

```python
@rolle_erforderlich(*TEAM_ROLLEN)          # läuft ZUERST
@merkmal_erforderlich('eigentuemerportal')
def fw_eigentuemerportal(request):
    ...
```

Der Dekorator setzt `view.benoetigtes_merkmal`; die Navigation liest es wie
heute schon `benoetigte_rollen`.

**Die Reihenfolge stand hier zuerst falsch herum** (Merkmal oben, Rolle
darunter). Die Absicht war richtig — wer die Rolle nicht hat, soll nicht
erfahren, welche Abo-Stufe ihm fehlte — die Schreibweise nicht: Zur Laufzeit
läuft der **äussere** Dekorator zuerst. Also gehört `rolle_erforderlich`
nach oben.

Nachgemessen beim Bauen (E2.81), zusammen mit der zweiten Frage dahinter:
`benoetigtes_merkmal` überlebt den äusseren Dekorator, weil `functools.wraps`
das `__dict__` mitnimmt. Der Sweep findet die Marke deshalb auch dann, wenn
`rolle_erforderlich` darüber steht.

### 3.3 Die Grenze greift zentral, nicht in jeder Ansicht

Eine Prüfung in jeder Anlege-Ansicht ist derselbe Fehler, den der Skill
`mandantentrennung` für Queries ausschliesst: Sie funktioniert, bis jemand
eine Ansicht vergisst.

Vorschlag: ein `pre_save`-Signal für die begrenzten Modelle, das **nur bei
neuen** Datensätzen prüft.

```python
@receiver(pre_save, sender=Einheit)
def _grenze_einheiten(sender, instance, **kw):
    if instance.pk or _grenzpruefung_aus.get():
        return
    ...
```

Und dazu — nach dem Vorbild von `alle_organisationen`, dem **benannten**
Umgehungsweg der Mandantentrennung — ein ausdrücklicher Ausstieg für
Datenimport, Migrationen und Fixtures:

```python
with ohne_grenzpruefung():        # Import, Migration, Testaufbau
    ...
```

Ein benannter Ausstieg ist ehrlicher als eine stille Ausnahme und lässt sich
im Sweep auffinden.

### 3.4 Der Zustand gehört in eine Middleware

```
voll    → alles
lesen   → GET erlaubt, POST/PUT/DELETE abgewiesen, Hintergrundläufe aus
export  → nur die Export-Endpunkte und die Anmeldung
```

Eine Middleware, die schreibende Methoden abweist, ist eine Zeile Logik und
329 Mal richtig. Der Export muss dabei **ausdrücklich** offen bleiben, sonst
sperrt man Kunden von ihren eigenen Daten aus — das ist die Stelle, an der aus
einem Zahlungsverzug ein Rechtsstreit wird.

---

## 4. Wie man beweist, dass keine Sperre fehlt

Das ist der Teil, der über Erfolg entscheidet, und der Bestand hat die Technik
bereits: Die Isolationstests laufen über `get_resolver().reverse_dict` und
gehen **jede** benannte URL an; was kein Objekt zuordnen kann, muss
ausdrücklich in `NAME_MUSTER` stehen, statt still übersprungen zu werden.

Dasselbe für Entitlements:

```python
def test_jede_ansicht_ist_zugeordnet(self):
    """Jede der 329 benannten URLs trägt entweder ein Merkmal oder steht
    ausdrücklich auf der Freiliste. Eine neue Ansicht ohne Zuordnung macht
    diesen Test rot — nicht das Produkt undicht."""
```

Eine Freiliste, die wachsen darf, ist wertlos. Eine, die nur mit Begründung
wächst, ist die halbe Miete. Vorbild ist die `NOCH_HINTEN`-Ratsche aus
`faelle/test_akten_neu.py`: eine Liste, die **nur schrumpfen** darf.

---

## 5. Die heiklen Stellen

### 5.1 Läufe dürfen nicht mitten im Zyklus abbrechen

MARKT.md sagt es deutlich, und es ist die teuerste Stelle: Wird der Mietenlauf
am Monatsersten gesperrt, weil eine Rechnung offen ist, bekommt die Verwaltung
keine Mieteinnahmen.

Technisch heisst das: Der Zustand wird **zu Beginn eines Laufs einmal**
ermittelt und mitgeführt — nicht je Datensatz neu geprüft. Sonst kippt ein
Lauf in der Mitte und hinterlässt einen halb verarbeiteten Monat.

Betroffen sind 31 Management-Commands, darunter `monatslauf`, `mahnlauf`,
`taeglicher_lauf`, `jahresabschluss_lauf`.

### 5.2 Fail-open oder fail-closed?

Bei der Mandantentrennung ist die Antwort eindeutig: Im Zweifel sperren, ein
Datenleck ist schlimmer als eine Fehlermeldung.

**Bei Entitlements ist sie es nicht.** Wenn die Stufe wegen eines Fehlers nicht
ermittelbar ist — sperrt man dann eine zahlende Verwaltung aus? Der Schaden
eines Fehlalarms ist hier grösser als der eines zu viel gewährten Monats.

Vorschlag: **Funktionssperren fail-open**, Zustandssperren fail-closed
(letztere hängen an einem Zahlungsstatus, der bekannt ist oder nicht existiert).
Das ist ein Entscheid, kein technisches Detail — er gehört ausdrücklich
getroffen und im Code begründet.

### 5.3 Drei bestehende Stufen, vier neue — kein Problem, nachgemessen

Diese Stelle stand hier zuerst als sorgfältig ausgearbeiteter Abschnitt über
Bestandskunden, Zuordnungstabelle und Übergangsfrist. **Sie war
gegenstandslos.**

Nachgemessen am 20.09.2026:

- Es gibt **eine** Organisation. `docs/AUFTRAG-ZWEITE-ORGANISATION.md` hält
  fest: «es gab bisher nur eine Organisation».
- Der **einzige** Weg, eine anzulegen, ist ein Notbehelf in
  `core/utils/market_data.py:172` — `Organisation.objects.create(firma="Meine
  Verwaltung")`.
- Eine `Mitgliedschaft` erzeugt ausserhalb von Tests und Fixtures **keine
  einzige Stelle** im Bestand.

Es gibt also keine Bestandskunden, die man umstufen müsste. Die Umstellung von
drei auf vier Stufen ist ein `ALTER`-Statement und ein bewusst gesetzter Wert
für die eine vorhandene Organisation. Keine Zuordnungstabelle, keine
Übergangsfrist, kein kaufmännischer Entscheid.

> **Warum das hier stehen bleibt statt gelöscht zu werden:** Ich hatte den
> Abschnitt geschrieben, weil «drei Stufen werden vier» nach einem
> Migrationsproblem klingt. Es klang nur so. Das ist dieselbe Falle, die
> `bekannte-fallen` unter Nummer 1 führt — eine Annahme, die plausibel ist und
> nicht nachgesehen wurde. Sobald die erste zahlende Verwaltung existiert,
> wird der Abschnitt wieder gebraucht; dann aber mit echten Zahlen.

### 5.3a Das eigentliche Hindernis: Es gibt keinen Weg, Kunde zu werden

Beim Nachmessen von 5.3 aufgefallen und wichtiger als alles andere in dieser
Notiz:

**Korrigiert am 20.09.2026 — die erste Fassung dieses Abschnitts war zu
scharf.** Sie behauptete, keine Stelle lege eine `Mitgliedschaft` an. Der
Grep dahinter suchte nur `Mitgliedschaft.objects.create` und übersah
`update_or_create`. Die genaue Lage:

| | Stand |
|---|---|
| Kollegen zu einer **bestehenden** Organisation hinzufügen | **funktioniert** — `core/views/fw/benutzer.py:121`, `update_or_create` mit Rolle |
| Eine **Organisation** anlegen | nur der Notbehelf in `core/utils/market_data.py:172` und die E2E-Fixture |
| Die **erste** Mitgliedschaft einer neuen Organisation | existiert nicht |

Das ist ein Henne-Ei-Problem, kein fehlendes Formular: `fw_benutzer_form`
liest `request.organisation` und setzt damit voraus, dass der Aufrufende
bereits Mitglied ist. Wer noch keine Organisation hat, kommt nicht hinein.

Ein Abo-System sperrt Funktionen nach Stufe. Bevor das einen Wert hat, muss
jemand eine Stufe kaufen können — und dafür braucht es eine Anmeldung, das
Anlegen einer Organisation, die erste Mitgliedschaft mit Inhaber-Rolle und
eine Testphase. Nichts davon existiert.

**Der Entwurf dazu:** `docs/PHASE-3-ONBOARDING.md`.

**Reihenfolge daraus:** Onboarding vor Entitlements. Ein gesperrtes
Eigentümerportal nützt niemandem, solange niemand ein Konto eröffnen kann.
Das ist kein Teil von P3.1, gehört aber vor P3.1 entschieden — sonst baut man
die Kasse vor dem Laden.

### 5.4 Speicher lässt sich heute nicht messen

Die Grenzen 5/50/150/300 GB stehen in MARKT.md, aber es gibt keine
Speicher-Buchhaltung. Bevor diese Grenze gilt, braucht es eine Zählung je
Organisation — und eine Entscheidung, ob sie laufend mitgeschrieben oder
periodisch ermittelt wird. Laufend ist genauer und teurer.

Vorschlag: Die Speichergrenze in der ersten Fassung **weglassen** und als
Zusatzposition führen, bis die Zählung steht. Eine Grenze, die man nicht messen
kann, ist ein Versprechen ohne Deckung — dieselbe Sorte wie der «API-Zugang».

---

## 6. Vorgeschlagene Reihenfolge

| Schritt | Inhalt | Stand |
|---|---|---|
| 1 | `core/entitlements.py` mit Tabellen + `darf()`, noch ohne Sperren. Test: Tabellen = MARKT.md | **erledigt** (E2.79) |
| 2 | Sweep-Test über alle benannten URLs (gemessen 326), alle auf der Freiliste | **erledigt** (E2.80) |
| 2b | `merkmal_erforderlich` als Mechanismus, noch nirgends angewendet | **erledigt** (E2.81) |
| 3 | Funktionssperren einziehen, Freiliste schrumpfen | wartet auf Entscheid 7 — solange `abo_plan` auf `pro` steht, lässt der Dekorator alles durch |
| 4 | Navigation zeigt Schloss statt Absage | 3 |
| 5 | Grenzen (Einheiten, Nutzer) per Signal + benannter Ausstieg | 1 |
| 6 | Zustands-Middleware | Zahlungsanbieter |
| 7 | Migration der drei Stufen auf vier | Entscheid 5.3 |

Die Schritte 1–4 sind unabhängig vom Zahlungsanbieter und können sofort
beginnen, sobald der Zuschnitt steht. Schritt 6 nicht.

---

## 7. Was entschieden werden muss, bevor gebaut wird

Fünf Punkte, jeder mit Empfehlung. Zwei davon haben sich beim Nachmessen
erledigt.

### 1. Gilt der Zuschnitt aus MARKT.md? — **Struktur ja, Preise später**

Vier Stufen `start`/`team`/`professional`/`enterprise` mit den Grenzen 25 /
150 / 500 / 2'000 Einheiten und 2 / 5 / 15 / unbegrenzt Nutzern.

**Die Entkopplung, die hier Zeit spart:** Das Entitlement-System braucht die
**Struktur**, nicht die **Preise**. Welche Funktion ab welcher Stufe gilt und
wie die Stufen heissen, entscheidet den Code. Ob Team CHF 119 oder 139 kostet,
berührt ihn nicht.

MARKT.md sagt selbst, die Preise seien aus Wettbewerbspreisen abgeleitet und
nicht aus Kostenrechnung. Diese Gegenrechnung kann laufen, während die
Struktur schon gebaut wird.

> **Empfehlung:** Struktur und Namen jetzt festlegen, Preise als vorläufig
> führen.

### 2. Zuordnung der Bestandskunden — **erledigt, gegenstandslos**

Es gibt eine Organisation und keinen Weg, eine zweite anzulegen (5.3).
Nichts zu entscheiden.

**Dafür ein anderer Punkt, der vorher kommt:** Es gibt keinen Weg, Kunde zu
werden (5.3a). Onboarding gehört vor Entitlements.

### 3. Fail-open oder fail-closed? — **gemischt, und das ist Absicht**

> **Empfehlung:** Funktionssperren **fail-open**, Zustandssperren
> **fail-closed**.

Eine Funktionssperre, die bei einem Fehler zuschlägt, sperrt eine zahlende
Verwaltung aus ihrem Eigentümerportal — für einen Ertrag, der ohnehin schon
gezahlt ist. Der Schaden ist einseitig.

Eine Zustandssperre hängt dagegen an einem Zahlungsstatus, der entweder
bekannt ist oder nicht existiert. «Nicht ermittelbar» heisst dort «keine
Zahlungsdaten», und das ist kein Grund, Schreibzugriff zu gewähren.

Der Unterschied gehört im Code begründet, nicht nur befolgt.

### 4. Speichergrenze in der ersten Fassung? — **nein**

Es gibt keine Speicher-Buchhaltung (5.4). Eine Grenze ohne Zählung ist ein
Versprechen ohne Deckung.

> **Empfehlung:** Speicher aus der ersten Fassung weglassen, als
> Zusatzposition führen, Zählung getrennt bauen.

### 5. «API-Zugang» — **aus der Merkmalsliste nehmen**

`ABO_PLAENE` verspricht ihn für Premium. Unter `/api/` liegen zwei Endpunkte,
beide `auth=None`: der DocuSeal-Webhook und das öffentliche
Bewerbungsformular. Das ist kein Zugang im Sinne des Versprechens.

> **Empfehlung:** Die Zeile streichen, bis es sie gibt. Ein Merkmal, das im
> Verkaufsgespräch genannt und dann nicht geliefert wird, kostet mehr als
> eines, das fehlt.

---

**Damit bleiben zwei echte Entscheide:** der Zuschnitt (1) und die Frage, ob
Onboarding vor Entitlements kommt (2). Die Punkte 3 bis 5 sind technisch
begründet und können mit der Empfehlung übernommen werden, wenn kein
Einspruch kommt.
