"""Aufbewahrung und Löschung von Bewerbungsdossiers (DSG).

Ein Bewerbungsdossier enthält die heikelsten Daten der ganzen Anwendung:
Ausweiskopie, Lohnausweis, Betreibungsauszug, dazu Geburtsdatum,
Nationalität, Zivilstand, Einkommen, Arbeitgeber, Kinder. Gesammelt werden
sie von Menschen, die zur Verwaltung in aller Regel **kein**
Vertragsverhältnis haben — die Wohnung bekommt genau eine Bewerberin, alle
übrigen Dossiers sind nach dem Entscheid zwecklos.

Das DSG verlangt, Personendaten zu vernichten oder zu anonymisieren, sobald
sie für den Zweck nicht mehr nötig sind (Art. 6 Abs. 4 DSG,
Verhältnismässigkeit und Zweckbindung). Für Bewerbungsunterlagen ist das der
Zeitpunkt des Vermietungsentscheids. Eine Aufbewahrungspflicht wie für
Buchungsbelege (Art. 958f OR) besteht hier gerade nicht — es gibt also
nichts, was dem Löschen entgegenstünde.

Zwei Stufen, weil die beiden Teile unterschiedlich dringend sind:

1. **Dokumente löschen** (Standard 7 Tage nach dem Entscheid). Die
   hochgeladenen Dateien. Der EDÖB verlangt Vernichtung «möglichst rasch»
   bzw. unmittelbar nach dem Entscheid; die wenigen Tage sind nur der
   Nachlauf für den Versand der Absagen, keine Aufbewahrung. Eine frühere
   Fassung stand hier auf 90 Tagen — das war zu lang.
2. **Dossier anonymisieren** (Standard 365 Tage). Auch die Personalien.
   Der Datensatz selbst bleibt als Hülle bestehen, damit nachvollziehbar
   bleibt, wie viele Bewerbungen ein Objekt hatte und wie entschieden wurde.

Nicht angetastet wird das Dossier der Person, die die Zusage erhalten hat
(`zugesagt`): Aus ihm entsteht das Mietverhältnis. Ihre Daten laufen über
`core.services.dsg` mit, sobald das Verhältnis beendet und die dortige Frist
abgelaufen ist.
"""
from datetime import timedelta

#: Dateifelder des Dossiers — die eigentlich heiklen Daten.
DOKUMENT_FELDER = ('betreibungsauszug', 'ausweiskopie', 'lohnausweis', 'weitere_dokumente')

#: Textfelder, die bei der Anonymisierung geleert bzw. ersetzt werden.
_LEEREN = (
    'adresse', 'plz', 'ort', 'mobilnummer', 'heimatort', 'nationalitaet',
    'beruf', 'arbeitgeber', 'einkommen_jahr', 'grund_fuer_wechsel', 'bemerkungen',
    'aktueller_vermieter', 'kontaktperson_vermieter', 'telefon_vermieter',
    'email_vermieter', 'kontaktperson_arbeitgeber', 'telefon_arbeitgeber',
    'email_arbeitgeber', 'haustiere_details', 'musikinstrumente_details',
    'schild_briefkasten', 'schild_sonnerie',
)


def entschieden_am(bewerbung):
    """Wann war diese Bewerbung erledigt? None = noch offen.

    Zwei Wege, wie eine Bewerbung ihr Ende findet:

    - Sie wurde ausdrücklich **abgelehnt** → Zeitpunkt der letzten Änderung.
    - Sie wurde nie beantwortet, das Objekt ist aber **inzwischen vermietet**
      → Zeitpunkt des Mietbeginns. In der Praxis der häufigere Fall: Wer eine
      Absage nicht verschickt, hat trotzdem entschieden, und das Dossier ist
      genauso zwecklos. Ohne diesen Weg bliebe der grösste Teil der Dossiers
      für immer liegen.
    """
    if bewerbung.status == 'zugesagt':
        return None                      # daraus entsteht das Mietverhältnis
    if bewerbung.status == 'abgelehnt':
        return bewerbung.aktualisiert_am.date()

    vertrag = (bewerbung.einheit.vertraege
               .filter(status__in=('aktiv', 'beendet'),
                       beginn__gte=bewerbung.erstellt_am.date())
               .order_by('beginn').first())
    return vertrag.beginn if vertrag else None


def loesche_dokumente(bewerbung):
    """Entfernt die hochgeladenen Dateien. Gibt die Anzahl zurück."""
    n = 0
    for feld in DOKUMENT_FELDER:
        datei = getattr(bewerbung, feld, None)
        if not datei:
            continue
        try:
            datei.delete(save=False)     # löscht Datei UND leert das Feld
        except Exception:
            setattr(bewerbung, feld, None)
        n += 1
    if n:
        bewerbung.save(update_fields=list(DOKUMENT_FELDER))
    return n


def anonymisiere_bewerbung(bewerbung):
    """Entfernt die Personalien; der Datensatz bleibt als Hülle bestehen."""
    loesche_dokumente(bewerbung)
    bewerbung.vorname = 'Anonymisiert'
    bewerbung.nachname = f'#{bewerbung.id}'
    bewerbung.email = f'anon-b{bewerbung.id}@example.invalid'
    for feld in _LEEREN:
        if hasattr(bewerbung, feld):
            setattr(bewerbung, feld, '')
    # Geburtsdatum ist ein Pflichtfeld (Datum) — auf einen neutralen Wert
    # setzen statt zu leeren, sonst liesse sich der Datensatz nicht speichern.
    bewerbung.geburtsdatum = bewerbung.geburtsdatum.replace(month=1, day=1)
    bewerbung.save()


def faellige(heute, *, dokumente_tage=7, anonym_tage=365):
    """(dokumente, anonymisieren) — was nach den Fristen ansteht.

    Eine Bewerbung erscheint nur in EINER der beiden Listen: Was ohnehin
    ganz anonymisiert wird, muss nicht zusätzlich als Dokumentenfall
    gemeldet werden."""
    from mietprozess.models import Mietbewerbung
    dok, anon = [], []
    qs = (Mietbewerbung.objects.exclude(status='zugesagt')
          .exclude(vorname='Anonymisiert')
          .select_related('einheit')
          .prefetch_related('einheit__vertraege'))
    for b in qs:
        ende = entschieden_am(b)
        if ende is None:
            continue                      # noch offen — Finger weg
        alter = (heute - ende).days
        if alter >= anonym_tage:
            anon.append(b)
        elif alter >= dokumente_tage and any(getattr(b, f, None) for f in DOKUMENT_FELDER):
            dok.append(b)
    return dok, anon


def bereinige(heute, *, dokumente_tage=7, anonym_tage=365, anwenden=False):
    """Führt die Bereinigung aus. Gibt (anzahl_dokumente, anzahl_anonym) zurück."""
    dok, anon = faellige(heute, dokumente_tage=dokumente_tage, anonym_tage=anonym_tage)
    if not anwenden:
        return len(dok), len(anon)
    n_dok = sum(loesche_dokumente(b) and 1 or 0 for b in dok)
    for b in anon:
        anonymisiere_bewerbung(b)
    return n_dok, len(anon)


def naechste_frist(bewerbung, heute, *, dokumente_tage=7, anonym_tage=365):
    """Wann wird dieses Dossier bereinigt? None = noch offen / nicht betroffen.
    Für die Anzeige im Bewerbungsdossier gedacht — Transparenz gegenüber der
    Person, die dort Auskunft verlangt."""
    ende = entschieden_am(bewerbung)
    if ende is None:
        return None
    hat_dok = any(getattr(bewerbung, f, None) for f in DOKUMENT_FELDER)
    frist = dokumente_tage if hat_dok else anonym_tage
    return ende + timedelta(days=frist)
