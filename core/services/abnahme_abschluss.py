"""Abschluss der Wohnungsabnahme und die Mängelrüge nach Art. 267a OR.

EIN ABSCHLUSS FÜR BEIDE WEGE. Das klassische Formular und die Abnahme vor Ort
schlossen bis 10/2026 je auf eigene Art ab: das Formular mit einem Häkchen, ohne
Unterschrift, die Abnahme vor Ort ohne jede Prüfung. Beides ergab Protokolle,
die als «abgeschlossen» galten, ohne dass jemand unterschrieben hatte. Jetzt
schliesst jedes Protokoll über `abschluss_pruefen` ab — der klassische Weg
erfasst, der Abschluss-Schritt der Abnahme vor Ort unterschreibt.

DIE RÜGE IST ERST MIT DEM VERSAND ERLEDIGT. Vorher hakte schon das Erzeugen des
PDFs die Fristpendenz ab; ein Brief, der in der Akte liegt, aber nie zur Post
ging, wahrt keine Frist. Die Pendenz bleibt offen, bis «Rüge versandt am»
erfasst ist (`ruege_versandt`).

FRIST. «Sofort» nach der Rückgabe (Art. 267a Abs. 1 OR) ist im Gesetz nicht in
Tagen bemessen. Hier gilt die Vorgabe des Auftrags vom 26.10.2026: Abnahme-
datum plus zwei Arbeitstage, Wochenenden übersprungen. Feiertage sind NICHT
berücksichtigt (kantonal verschieden) — die Frist kann dadurch nur kürzer,
nie länger ausfallen als gemeint.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext

#: Titel der Fristpendenz. Derselbe Wortlaut wie in der Auszugscheckliste der
#: Kündigung (core/views/fw/kuendigung.py), damit beide Wege dieselbe Pendenz
#: finden statt eine zweite anzulegen.
RUEGE_TITEL = "Mängelrüge Art. 267a: sofort nach Abnahme versenden"
#: Stichwort für `erledige_pendenzen_fuer` und den Fall «Mieterwechsel».
RUEGE_STICHWORT = 'Mängelrüge Art. 267a'
#: Später entdeckter Mangel. Bewusst OHNE das Stichwort oben: Der Versand der
#: Rüge nach der Abnahme darf diese Pendenz nicht mit abhaken.
NACHRUEGE_TITEL = "Mängelrüge versteckter Mangel (Art. 267a Abs. 3): sofort versenden"
RUEGE_ARBEITSTAGE = 2


def arbeitstage_nach(datum, tage=RUEGE_ARBEITSTAGE):
    """Das Datum `tage` Arbeitstage (Mo–Fr) nach `datum`. Feiertage zählen als
    Arbeitstage (siehe Modulkopf)."""
    d, gezaehlt = datum, 0
    while gezaehlt < tage:
        d += timedelta(days=1)
        if d.weekday() < 5:
            gezaehlt += 1
    return d


def ruege_frist(datum):
    """Bis wann die Rüge nach einer Abnahme (oder Entdeckung) hinaus muss."""
    return arbeitstage_nach(datum, RUEGE_ARBEITSTAGE)


# ---------------------------------------------------------------------------
# Was gerügt wird
# ---------------------------------------------------------------------------

def _betrag(m):
    return m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung


def ruege_posten(prot):
    """Die Posten der Rüge nach der Abnahme (Liste von dicts für den Brief):
    die bei der Abnahme festgestellten Mieter-Mängel und die fehlenden
    Schlüssel. Später entdeckte Mängel haben ihre eigene Rüge."""
    posten = [{'raum': m.raum, 'beschreibung': m.beschreibung, 'betrag': _betrag(m)}
              for m in prot.maengel_mieter_bei_abnahme]
    for z in prot.schluessel.all():
        if z.fehlend:
            anlage = f" ({z.anlage})" if z.anlage else ''
            posten.append({'raum': '', 'beschreibung': f"Fehlende Schlüssel: {z.fehlend} × {z.bezeichnung}{anlage}",
                           'betrag': z.kosten_mieter or None})
    return posten


def ruege_noetig(prot):
    """Braucht dieses Protokoll eine Rüge? Nur beim Auszug, und nur mit Posten."""
    return prot.typ == 'auszug' and bool(ruege_posten(prot))


def ohne_lebensdauer(prot):
    """Mieterschäden, die ohne Alter/Lebensdauer mit dem vollen Betrag belastet
    werden (Grundlage OHNE_LEBENSDAUER). Angreifbar: Die Beweislast für den
    Zeitwert liegt beim Vermieter — deshalb vor dem Abschluss ausdrücklich zu
    bestätigen."""
    from core.services.zeitwert import OHNE_LEBENSDAUER
    return [m for m in prot.maengel.select_related('ausstattung')
            if m.verursacher == 'mieter' and m.entdeckt_am is None
            and m.zeitwert_grundlage == OHNE_LEBENSDAUER]


def unbewertet(prot):
    """Bauteile ohne Bewertung."""
    return list(prot.positionen.filter(zustand=''))


# ---------------------------------------------------------------------------
# Abschluss
# ---------------------------------------------------------------------------

ANWESEND_JA = ('ja', 'on')          # 'on': das frühere Häkchen
ANWESEND_NEIN = ('nein',)


def abschluss_pruefen(prot, P, bilder):
    """Was dem Abschluss noch fehlt — Liste von Meldungen, leer heisst: geht.

    `P` ist das Formular, `bilder` die schon geprüften Unterschriften
    (`{feld: png_bytes}`). Eine bereits gespeicherte Unterschrift zählt mit.

    Regeln (Auftrag 26.10.2026):
    - Die Verwaltung unterschreibt immer.
    - Der Mieter unterschreibt — oder er war abwesend, und der Grund steht da.
      Ein vorbelegter Name ist keine Unterschrift; gezählt wird das Bild.
    - Allgemeinzustand und Anwesenheit sind anzugeben (sie blieben sonst still
      auf «gut» und «anwesend» stehen).
    - Unbewertete Bauteile und Mieterschäden ohne Lebensdauer: auflisten und
      ausdrücklich bestätigen lassen.
    """
    fehler = []
    anwesend = P.get('mieter_anwesend', '')
    if anwesend not in ANWESEND_JA + ANWESEND_NEIN:
        fehler.append(gettext('Bitte angeben, ob der Mieter anwesend war.'))
    if P.get('allgemein_zustand', '') not in dict(type(prot)._meta.get_field('allgemein_zustand').choices):
        fehler.append(gettext('Bitte den Allgemeinzustand wählen.'))
    if not (bilder.get('unterschrift_verwalter_bild') or prot.unterschrift_verwalter_bild):
        fehler.append(gettext('Die Unterschrift der Verwaltung fehlt.'))
    if anwesend in ANWESEND_NEIN:
        if not P.get('mieter_abwesend_grund', '').strip():
            fehler.append(gettext('Der Mieter war abwesend: bitte den Grund angeben.'))
    elif anwesend in ANWESEND_JA:
        if not (bilder.get('unterschrift_mieter_bild') or prot.unterschrift_mieter_bild):
            fehler.append(gettext('Die Unterschrift des Mieters fehlt. War er nicht da, «Mieter abwesend» '
                                  'wählen und den Grund angeben.'))
        elif not P.get('unterschrift_mieter', '').strip():
            fehler.append(gettext('Bitte den Namen der Person eintragen, die für den Mieter unterschreibt.'))
    offen = unbewertet(prot)
    if offen and P.get('unbewertet_ok') != '1':
        fehler.append(gettext('%(count)s Bauteil(e) sind nicht bewertet: bitte bewerten oder ausdrücklich '
                              'bestätigen.') % {'count': len(offen)})
    ohne = ohne_lebensdauer(prot)
    if ohne and P.get('ohne_lebensdauer_ok') != '1':
        fehler.append(gettext('%(count)s Mieterschaden ohne Alter oder Lebensdauer des Bauteils: voller Betrag. '
                              'Bitte bestätigen oder Einbaudatum und Lebensdauer im Raumbuch ergänzen.')
                      % {'count': len(ohne)})
    return fehler


def abschlussfelder_uebernehmen(prot, P):
    """Übernimmt die Felder des Abschluss-Schritts in den Entwurf — auch wenn
    der Abschluss danach noch scheitert: Was getippt war, steht beim nächsten
    Versuch wieder da. Unterschriften gehören NICHT dazu; sie gelten nur für
    den Stand, der abgeschlossen wird."""
    from core.services.abnahme_schluessel import schluessel_speichern
    anwesend = P.get('mieter_anwesend', '')
    if anwesend in ANWESEND_JA:
        prot.mieter_anwesend = True
        prot.mieter_abwesend_grund = ''
    elif anwesend in ANWESEND_NEIN:
        prot.mieter_anwesend = False
        prot.mieter_abwesend_grund = P.get('mieter_abwesend_grund', '').strip()[:200]
    if P.get('allgemein_zustand', '') in dict(type(prot)._meta.get_field('allgemein_zustand').choices):
        prot.allgemein_zustand = P['allgemein_zustand']
    for feld in ('zaehler_strom', 'zaehler_wasser', 'zaehler_gas'):
        if feld in P:
            setattr(prot, feld, P.get(feld, '').strip()[:40])
    if 'neue_adresse' in P:
        prot.neue_adresse = P.get('neue_adresse', '').strip()[:200]
    if 's_bezeichnung' in P:
        schluessel_speichern(prot, P)          # setzt schluessel_anzahl aus der Summe der gezählten
    elif 'schluessel_anzahl' in P:
        prot.schluessel_anzahl = int(P['schluessel_anzahl']) if P['schluessel_anzahl'].isdigit() else None
    if 'bemerkungen' in P:
        prot.bemerkungen = P.get('bemerkungen', '').strip()
    if 'unterschrift_mieter' in P:
        prot.unterschrift_mieter = P.get('unterschrift_mieter', '').strip()[:120]
    if 'unterschrift_verwalter' in P:
        prot.unterschrift_verwalter = P.get('unterschrift_verwalter', '').strip()[:120]


def schluessel_folgen(prot, user=None):
    """Bucht die Schlüssel des Protokolls (Ausgabe beim Einzug, Rücknahme und
    Verlust beim Auszug — core/services/schluessel.py). Gibt die Zeilen zurück,
    die sich keinem Schlüssel des Registers zuordnen liessen.

    Ein Fehler hier darf den Abschluss nicht kosten: Das Protokoll ist schon
    unterschrieben. Er wird protokolliert, und die Buchung lässt sich über die
    Ausgabeseite nachholen."""
    import logging
    from core.services.schluessel import abnahme_buchen
    try:
        return abnahme_buchen(prot, user=user)
    except Exception:
        logging.getLogger(__name__).exception('Schlüsselbuchung aus Abnahme %s fehlgeschlagen', prot.pk)
        return None


def abschluss_folgen(prot, user=None):
    """Was ein abgeschlossenes Protokoll auslöst. Beide Arten buchen die
    Schlüssel. Beim Auszug dazu: Checklisten-Pendenzen abhaken, die Rügefrist
    setzen und die neue Adresse des Mieters hinterlegen.

    Gibt die Zeilen des Schlüsselverzeichnisses zurück, die nicht gebucht
    werden konnten (None, wenn die Buchung fehlschlug)."""
    if prot.typ != 'auszug':
        return schluessel_folgen(prot, user)
    from core.services.automation import erledige_pendenzen_fuer
    v = prot.vertrag
    kw = ['Wohnungsabnahme', 'Abnahmetermin']
    if prot.zaehler_strom or prot.zaehler_wasser or prot.zaehler_gas:
        kw.append('Zählerstände')
    if prot.schluessel_anzahl is not None:
        kw.append('Schlüssel')
    if ruege_noetig(prot):
        ruege_pendenz_setzen(prot, user)
    else:
        # Ohne Mieter-Mängel und ohne fehlende Schlüssel gibt es nichts zu
        # rügen — die Fristpendenz der Checkliste ist gegenstandslos.
        kw.append(RUEGE_STICHWORT)
    erledige_pendenzen_fuer(v, kw, user=user)
    neue_adresse_hinterlegen(prot)
    # Erst NACH dem Abhaken: Das Stichwort «Schlüssel» erledigte sonst die eben
    # entstandene Pendenz «Zylinder ersetzen», wenn der Typ das Wort enthält.
    return schluessel_folgen(prot, user)


def neue_adresse_hinterlegen(prot):
    """Neue Wohnadresse ab Abnahmedatum als datierte Adresszeile (Wegzug) — für
    Haupt- und Mitmieter. Wird zum Stichtag zur Zustelladresse."""
    neue_adr = (prot.neue_adresse or '').strip()
    if not neue_adr:
        return
    from crm.models import MieterAdresse
    from core.views.fw._basis import _parse_adresse
    v = prot.vertrag
    strasse, plz, ort = _parse_adresse(neue_adr)
    for person in (v.mieter, v.mitmieter):
        if not person:
            continue
        MieterAdresse.objects.get_or_create(
            mieter=person, art='wohn', gueltig_ab=prot.datum,
            defaults=dict(strasse=strasse, plz=plz, ort=ort, quelle=f'auszug:{prot.id}',
                          notiz='Wegzug gemäss Abnahmeprotokoll'))
        person.sync_effektive_adresse()


def _einschreiben_hinweis(prot):
    if prot.mieter_anwesend:
        return ''
    return (" Der Mieter war bei der Abnahme nicht anwesend: Rüge eingeschrieben versenden "
            "(Zugangsnachweis).")


def ruege_pendenz_setzen(prot, user=None):
    """Legt die Fristpendenz der Rüge an oder datiert eine vorhandene um.

    Die Pendenz aus der Kündigungs-Checkliste rechnet vom Vertragsende aus —
    massgeblich ist aber der Tag der Abnahme. Gibt es keine (Auszug ohne
    erfasste Kündigung), entsteht sie hier."""
    from core.models import Pendenz
    if prot.ruege_versandt_am:
        return None
    v = prot.vertrag
    frist = ruege_frist(prot.datum)
    beschreibung = (f"Abnahme vom {prot.datum:%d.%m.%Y} · {v.mieter.display_name} · "
                    f"{v.einheit.bezeichnung}. Erledigt erst mit «Rüge versandt am» im Protokoll."
                    + _einschreiben_hinweis(prot))
    offene = list(Pendenz.objects.filter(vertrag=v, erledigt=False, titel__icontains=RUEGE_STICHWORT))
    for p in offene:
        p.faellig_am = frist
        p.beschreibung = beschreibung
        p.kategorie = 'frist'
        p.save(update_fields=['faellig_am', 'beschreibung', 'kategorie'])
    if offene:
        return offene[0]
    return Pendenz.objects.create(
        titel=RUEGE_TITEL, kategorie='frist', faellig_am=frist, vertrag=v,
        liegenschaft=v.einheit.liegenschaft, quelle=f'abnahme:ruege:{prot.id}',
        beschreibung=beschreibung, erstellt_von=user)


def ruege_versandt(prot, datum, sendungsnummer='', user=None):
    """Die Rüge nach der Abnahme ist versandt: Datum festhalten, Fristpendenz
    erledigen (mit Versanddatum und Sendungsnummer)."""
    from core.models import Pendenz
    from core.services.automation import erledige_pendenzen_fuer
    prot.ruege_versandt_am = datum
    prot.ruege_sendungsnummer = (sendungsnummer or '').strip()[:40]
    prot.save(update_fields=['ruege_versandt_am', 'ruege_sendungsnummer'])
    Pendenz.objects.filter(vertrag=prot.vertrag, erledigt=False, titel__icontains=RUEGE_STICHWORT) \
        .update(versand_am=datum, sendungsnummer=prot.ruege_sendungsnummer)
    erledige_pendenzen_fuer(prot.vertrag, [RUEGE_STICHWORT], user=user)


# ---------------------------------------------------------------------------
# Später entdeckter Mangel (Art. 267a Abs. 3 OR)
# ---------------------------------------------------------------------------

def nachmangel_erfassen(prot, *, raum, beschreibung, entdeckt_am, kosten=None, ausstattung=None,
                        foto=None, user=None):
    """Erfasst einen nach der Abnahme entdeckten Mangel am abgeschlossenen
    Protokoll und legt die Pendenz an, die Rüge sofort zu versenden.

    Der Mangel wird dem Mieter zugeordnet (sonst wäre er nicht zu rügen) und
    mit dem Zeitwert zum Abnahmedatum gerechnet — dem Tag der Rückgabe. Das
    unterzeichnete Protokoll bleibt, was es war: Im PDF und auf der Seite steht
    der Mangel getrennt, mit seinem Entdeckungsdatum."""
    from core.models import Pendenz
    from rentals.models import AbnahmeMangel
    m = AbnahmeMangel(protokoll=prot, raum=(raum or '').strip()[:60], beschreibung=beschreibung.strip()[:255],
                      verursacher='mieter', kostenschaetzung=kosten, ausstattung=ausstattung,
                      neuwert=(ausstattung.neuwert if ausstattung is not None else None),
                      entdeckt_am=entdeckt_am)
    if foto:
        m.foto = foto
    m.mieteranteil = m.berechne_mieteranteil(stichtag=prot.datum)
    m.save()
    v = prot.vertrag
    Pendenz.objects.create(
        titel=NACHRUEGE_TITEL, kategorie='frist', faellig_am=ruege_frist(entdeckt_am), vertrag=v,
        liegenschaft=v.einheit.liegenschaft, quelle=f'abnahme:nachruege:{m.id}',
        beschreibung=(f"Entdeckt am {entdeckt_am:%d.%m.%Y}: {m.beschreibung} · Abnahme vom "
                      f"{prot.datum:%d.%m.%Y}. Rüge eingeschrieben versenden; erledigt mit «Rüge versandt am»."),
        erstellt_von=user)
    return m


def nachruege_versandt(mangel, datum, user=None):
    """Die Rüge zu einem später entdeckten Mangel ist versandt."""
    from core.models import Pendenz
    mangel.ruege_versandt_am = datum
    mangel.save(update_fields=['ruege_versandt_am'])
    heute = timezone.localdate()
    for p in Pendenz.objects.filter(quelle=f'abnahme:nachruege:{mangel.id}', erledigt=False):
        p.erledigt, p.erledigt_am, p.versand_am = True, heute, datum
        p.save(update_fields=['erledigt', 'erledigt_am', 'versand_am'])


def nachruege_posten(mangel):
    return [{'raum': mangel.raum, 'beschreibung': mangel.beschreibung, 'betrag': _betrag(mangel)}]


# ---------------------------------------------------------------------------
# Handwerker
# ---------------------------------------------------------------------------

def ticket_fuer_mangel(mangel, user=None):
    """Legt zum Mangel ein Ticket an (oder gibt das vorhandene zurück). Über das
    Ticket läuft der Handwerkerauftrag wie bei jedem anderen Schaden — eine
    zweite Auftragsverwaltung neben `tickets` gäbe es sonst."""
    from tickets.models import SchadenFoto, SchadenMeldung
    if mangel.ticket_id:
        return mangel.ticket, False
    prot = mangel.protokoll
    e = prot.vertrag.einheit
    t = SchadenMeldung.objects.create(
        liegenschaft=e.liegenschaft, betroffene_einheit=e, ausstattung=mangel.ausstattung,
        raum=(mangel.raum or '')[:100] or None, titel=mangel.beschreibung[:200],
        beschreibung=(f"Aus Abnahmeprotokoll ({prot.get_typ_display()}) vom {prot.datum:%d.%m.%Y}, "
                      f"{prot.vertrag.mieter.display_name}. Mangel: {mangel.beschreibung}"
                      + (f" · Kostenschätzung CHF {mangel.kostenschaetzung}" if mangel.kostenschaetzung else '')),
        status='neu')
    if mangel.foto:
        # Dieselbe Datei, keine Kopie (wie Position → Mangel).
        foto = SchadenFoto(schaden=t, hochgeladen_von=user)
        foto.bild = mangel.foto.name
        foto.save()
    mangel.ticket = t
    mangel.save(update_fields=['ticket'])
    return t, True


def schluessel_positionen(prot):
    """Fehlende Schlüssel als Positionen der Schlussabrechnung."""
    return [{'text': f"Fehlende Schlüssel: {z.fehlend} × {z.bezeichnung}"[:90], 'betrag': z.kosten_mieter}
            for z in prot.schluessel.all() if z.kosten_mieter > Decimal('0')]
