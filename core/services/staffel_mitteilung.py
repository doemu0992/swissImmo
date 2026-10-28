"""Staffelmiete: schriftliche Mitteilung jeder Erhöhung (Art. 269d Abs. 5 OR, Art. 19a VMWG).

WAS GILT

* Für die Mitteilung einer in der Staffelvereinbarung vorgesehenen Erhöhung
  genügt die SCHRIFTLICHE Form — kein amtliches Formular (Art. 269d Abs. 5 OR).
* Sie darf FRÜHESTENS VIER MONATE vor Eintritt jeder Erhöhung erfolgen
  (Art. 19a VMWG). Das ist die einzige Zeitgrenze, die im Bestand belegt ist.
  Eine gesetzliche Mindestfrist VOR dem Eintritt steht nicht in der
  Rechtsgrundlage der Anwendung und wird hier nicht erfunden.

DAS FENSTER (`fenster_beginn`)

Der frühestmögliche Versandtag ist der erste Tag, von dem aus der Eintritt
höchstens vier Monate entfernt ist: das kleinste `d`, für das `d + 4 Monate >=
Eintritt` gilt. Monate werden wie im Fristenrecht gerechnet (Art. 77 Abs. 1
Ziff. 3 OR): derselbe Tag des Monats, fehlt er, der letzte Tag. Daraus folgt:

    Eintritt 1.6.   -> Fenster ab 1.2.        (genau vier Monate)
    Eintritt 31.5.  -> Fenster ab 31.1.
    Eintritt 31.3.  -> Fenster ab 1.12.       (30.11. wäre 4 Monate und 1 Tag
                                                vor dem 31.3.; der 30.11. + 4
                                                Monate ist erst der 30.3.)

Im Zweifel gilt der spätere Tag: Zu früh versandt ist riskanter als einen Tag
später. Das ist eine Annahme der Anwendung, im Schlussbericht gemeldet.

DIE ERINNERUNG (`VORLAUF_TAGE`)

Die Pendenz entsteht `VORLAUF_TAGE` Tage VOR dem Fenster und ist am ersten
Tag des Fensters fällig. Die 14 Tage sind eine interne Gewohnheit (Zeit, das
Schreiben vorzubereiten), kein Gesetzeswert. Eine Frist, bis zu der die
Mitteilung spätestens versandt sein muss, nennt die Rechtsgrundlage nicht;
die Pendenz bleibt deshalb offen, bis das Schreiben als versandt markiert ist,
und wird nach dem Eintritt nicht mehr neu angelegt.

DIE ERHÖHUNG

`Staffelstufe.erhoehung_chf` ist die Quelle der Wahrheit (Art. 269c lit. c OR:
Frankenbetrag). Stufen aus der Zeit davor tragen sie nicht; dann gilt die
Differenz zur vorigen Stufe, wenn sie positiv ist. «Bisher» ist der VEREINBARTE
Netto der Vorstufe (bzw. der Netto des Vertrags für die erste Stufe), nicht der
verrechnete: Gratismonate und Komponenten ändern nichts an dem, was mitgeteilt
wird. Stimmen `erhoehung_chf` und `netto_mietzins` nicht zusammen, entsteht
KEIN Schreiben — es würde etwas anderes mitteilen, als verrechnet wird.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext

#: Art. 19a VMWG: Die schriftliche Mitteilung darf frühestens vier Monate vor Eintritt erfolgen.
FENSTER_MONATE = 4

#: Interne Gewohnheit, kein Gesetzeswert: Die Erinnerung kommt so viele Tage vor dem Fenster.
VORLAUF_TAGE = 14

#: Art. 269d Abs. 5 OR (Mitteilung in der Staffelvereinbarung vorgesehener Erhöhungen) gilt seit dem
#: 1.10.2025. Eine Stufe, die schon davor eintrat, wirkt ohne Mitteilung wie bisher (MIET-09: «Altverträge:
#: eine Stufe, die schon vor 1.10.2025 galt, bleibt unverändert»).
INKRAFT_MITTEILUNG = date(2025, 10, 1)

STATUS_NOCH_NICHT = 'noch_nicht'
STATUS_FAELLIG = 'faellig'
STATUS_ERSTELLT = 'erstellt'
STATUS_VERSANDT = 'versandt'


# ── Das Fenster ──────────────────────────────────────────────────────────────
def plus_monate(d, monate):
    """`d` plus (oder minus) Monate; fehlt der Tag im Zielmonat, gilt dessen letzter."""
    m0 = d.month - 1 + int(monate)
    jahr, monat = d.year + m0 // 12, m0 % 12 + 1
    return date(jahr, monat, min(d.day, calendar.monthrange(jahr, monat)[1]))


def fenster_beginn(eintritt):
    """Der erste Tag, an dem die Mitteilung für `eintritt` versandt werden darf (Art. 19a VMWG)."""
    kandidat = plus_monate(eintritt, -FENSTER_MONATE)
    # Rückwärts geklemmt (31.3. - 4 Monate = 30.11.) läge der Kandidat einen Tag zu früh:
    # 30.11. + 4 Monate ist erst der 30.3. Dann gilt der Folgetag.
    if plus_monate(kandidat, FENSTER_MONATE) < eintritt:
        kandidat += timedelta(days=1)
    return kandidat


def im_fenster(eintritt, am):
    """Darf am Tag `am` die Mitteilung für `eintritt` versandt werden? (Nur die Fenstergrenze, Art. 19a VMWG.)"""
    return am >= fenster_beginn(eintritt)


def erinnerung_ab(eintritt):
    """Ab wann die Erinnerung (Pendenz) besteht: `VORLAUF_TAGE` vor dem Fenster."""
    return fenster_beginn(eintritt) - timedelta(days=VORLAUF_TAGE)


# ── Wirkt die Stufe? (MIET-09) ───────────────────────────────────────────────
def stufe_wirkt(stufe):
    """Darf die Stufe verrechnet werden? Nur mit belegter, rechtzeitiger schriftlicher Mitteilung.

    KONSERVATIVE LESART (Fachpunkt, im Schlussbericht gemeldet): Art. 269d Abs. 5 OR verlangt für die
    Mitteilung in der Staffelvereinbarung vorgesehener Erhöhungen die Schriftform; wann spätestens und
    mit welcher Folge bei Verspätung, sagt der Gesetzestext nicht. Die Anwendung verrechnet die Stufe
    deshalb nur, wenn

      * sie vor dem 1.10.2025 eintrat (Altvertrag, Übergangsrecht), oder
      * `mitteilung_versandt_am` gesetzt ist, vor dem Eintritt der Stufe liegt und nicht früher als das
        Fenster der Art. 19a VMWG (vier Monate vor Eintritt).

    Eine verspätete oder fehlende Mitteilung lässt den bisherigen Mietzins stehen; die Stufe wird nicht
    nachgeholt. Das ist vorsichtig (der Vermieter verrechnet nie zu viel), nicht ein belegter Rechtssatz."""
    if stufe.ab_datum < INKRAFT_MITTEILUNG:
        return True
    versandt = stufe.mitteilung_versandt_am
    return bool(versandt and versandt < stufe.ab_datum and versandt >= fenster_beginn(stufe.ab_datum))


def wirksame_stufe(stufen, stichtag):
    """Die am Stichtag geltende Stufe (die jüngste mit `ab_datum <= stichtag`), oder None.

    Die Stufen bauen aufeinander auf (Stand = Vorstufe + Erhöhung). Wirkt eine Stufe nicht, wirken auch
    die späteren nicht: Sonst würde mit der späteren Stufe die nie mitgeteilte Erhöhung der früheren
    mitverrechnet. Es gilt dann die letzte Stufe VOR der ersten, die nicht wirkt."""
    geltend = None
    for st in sorted((x for x in stufen if x.ab_datum and x.ab_datum <= stichtag),
                     key=lambda x: (x.ab_datum, x.pk or 0)):
        if not stufe_wirkt(st):
            break
        geltend = st
    return geltend


# ── Die Stufen eines Vertrags ────────────────────────────────────────────────
@dataclass(frozen=True)
class StufenStand:
    """Was die Vertragsakte je Staffelstufe zeigt."""
    stufe: object
    bisher: Decimal | None
    neu: Decimal
    erhoehung: Decimal | None
    eintritt: date
    fenster_ab: date
    erinnerung_ab: date
    status: str
    verstrichen: bool          # Eintritt schon erreicht, ohne dass versandt wurde
    wirkt: bool                # wird verrechnet (belegte, rechtzeitige Mitteilung bzw. Altstufe)
    verspaetet: bool           # als versandt erfasst, aber nicht rechtzeitig vor dem Eintritt
    problem: str               # '' oder der Grund, warum kein Schreiben entstehen darf
    kann_erstellen: bool
    kann_versenden: bool


def _erhoehungen(vertrag):
    """[(stufe, bisher, erhoehung)] in Reihenfolge der Stufen.

    `erhoehung` ist None, wenn weder `erhoehung_chf` noch eine positive Differenz vorliegt."""
    reihe = []
    vorher = vertrag.netto_mietzins
    for st in sorted(vertrag.staffelstufen.all(), key=lambda s: (s.ab_datum, s.pk or 0)):
        erhoehung = st.erhoehung_chf
        if erhoehung is None and vorher is not None and st.netto_mietzins is not None \
                and st.netto_mietzins > vorher:
            erhoehung = st.netto_mietzins - vorher
        reihe.append((st, vorher, erhoehung))
        vorher = st.netto_mietzins
    return reihe


def _problem(bisher, neu, erhoehung):
    """Der Grund, warum für diese Stufe kein Schreiben entstehen darf — oder ''."""
    if erhoehung is None or erhoehung <= 0:
        return gettext('Die Stufe erhöht nicht: Eine Staffelmiete verlangt eine Erhöhung in Franken (Art. 269c OR).')
    if bisher is None or bisher + erhoehung != neu:
        return gettext('Erhöhung und Netto der Stufe stimmen nicht überein — bitte die Stufe prüfen.')
    return ''


def stufen_staende(vertrag, heute):
    """Der Stand jeder Staffelstufe des Vertrags, nach Eintritt geordnet."""
    liste = []
    for st, bisher, erhoehung in _erhoehungen(vertrag):
        problem = _problem(bisher, st.netto_mietzins, erhoehung)
        fenster = fenster_beginn(st.ab_datum)
        if st.mitteilung_versandt_am:
            status = STATUS_VERSANDT
        elif st.mitteilung_erstellt_am:
            status = STATUS_ERSTELLT
        elif heute >= fenster:
            status = STATUS_FAELLIG
        else:
            status = STATUS_NOCH_NICHT
        im_fenster_heute = heute >= fenster
        liste.append(StufenStand(
            stufe=st, bisher=bisher, neu=st.netto_mietzins, erhoehung=erhoehung, eintritt=st.ab_datum,
            fenster_ab=fenster, erinnerung_ab=fenster - timedelta(days=VORLAUF_TAGE), status=status,
            verstrichen=(not st.mitteilung_versandt_am) and st.ab_datum <= heute and not stufe_wirkt(st),
            problem=problem,
            wirkt=stufe_wirkt(st),
            verspaetet=bool(st.mitteilung_versandt_am) and not stufe_wirkt(st),
            # Ein Schreiben zu einer Erhöhung, die schon gilt, wäre falsch formuliert.
            kann_erstellen=(status != STATUS_VERSANDT and im_fenster_heute and not problem
                            and st.ab_datum > heute),
            kann_versenden=(status in (STATUS_FAELLIG, STATUS_ERSTELLT) and im_fenster_heute and not problem)))
    return liste


# ── Aktionen ─────────────────────────────────────────────────────────────────
def _stand_von(stufe, heute):
    return next(s for s in stufen_staende(stufe.vertrag, heute) if s.stufe.pk == stufe.pk)


def erstellen_fehler(stufe, heute):
    """Meldung, wenn für diese Stufe heute kein Schreiben entstehen darf — sonst ''."""
    if stufe.vertrag.mietzins_modell != 'staffel':
        return gettext('Der Vertrag ist keine Staffelmiete.')
    stand = _stand_von(stufe, heute)
    if stufe.mitteilung_versandt_am:
        return gettext('Die Mitteilung ist bereits als versandt markiert.')
    if stand.problem:
        return stand.problem
    if stufe.ab_datum <= heute:
        return gettext('Die Erhöhung gilt bereits (%(datum)s): Ein Schreiben im Voraus ist nicht mehr möglich.') % {
            'datum': stufe.ab_datum.strftime('%d.%m.%Y')}
    if heute < stand.fenster_ab:
        return gettext('Zu früh: Die schriftliche Mitteilung darf frühestens vier Monate vor der Erhöhung '
                       'erfolgen, also ab dem %(datum)s (Art. 19a VMWG).') % {
                           'datum': stand.fenster_ab.strftime('%d.%m.%Y')}
    return ''


def schreiben_erstellen(stufe, heute, benutzer=None):
    """Erzeugt das Schreiben als PDF (in der Sprache des Mieters), legt es in der Akte ab
    und merkt sich `mitteilung_erstellt_am`. Gibt das abgelegte Dokument zurück.

    `ValueError` mit Klartext, wenn die Stufe heute kein Schreiben zulässt (Fenster, Problem)."""
    fehler = erstellen_fehler(stufe, heute)
    if fehler:
        raise ValueError(fehler)
    from core.services.ablage import ablegen
    pdf = schreiben_pdf(stufe, heute)
    # Der Ablagetitel bleibt deutsch (gespeicherter Text, wie bei den übrigen Dokumenten der Akte).
    titel = titel_fuer(stufe.ab_datum)
    dok = ablegen(pdf, titel, kategorie='korrespondenz', vertrag=stufe.vertrag, dedup=True)
    if dok is None:
        raise ValueError(gettext('Das Schreiben konnte nicht abgelegt werden.'))
    stufe.mitteilung_erstellt_am = heute
    stufe.save(update_fields=['mitteilung_erstellt_am'])
    return dok


def titel_fuer(ab_datum):
    """Bezeichnung des abgelegten Schreibens; über sie findet die Akte es wieder."""
    return f"Staffelmiete – Mitteilung Erhöhung ab {ab_datum:%d.%m.%Y}"


def uebersicht(vertrag, heute):
    """Je Stufe `{'s': StufenStand, 'dokument': Dokument | None}` für die Vertragsakte.

    Das Dokument ist die neueste Fassung des abgelegten Schreibens (eine Abfrage für alle Stufen)."""
    from rentals.models import Dokument
    staende = stufen_staende(vertrag, heute)
    if not staende:
        return []
    dokumente = {d.bezeichnung: d for d in Dokument.objects.neueste().filter(
        vertrag=vertrag, bezeichnung__in=[titel_fuer(s.eintritt) for s in staende]).order_by('id')}
    return [{'s': s, 'dokument': dokumente.get(titel_fuer(s.eintritt))} for s in staende]


def schreiben_pdf(stufe, heute=None):
    """Das PDF des Schreibens, in der Sprache des Mieters (`Mieter.sprache`)."""
    from django.utils import timezone
    from core.services.dokument_service import generate_dokument_pdf_bytes
    heute = heute or timezone.localdate()
    stand = _stand_von(stufe, heute)
    return generate_dokument_pdf_bytes(stufe.vertrag, 'staffel-mitteilung', extra_context={
        'stufe': stufe, 'bisher': stand.bisher, 'erhoehung': stand.erhoehung, 'neu': stand.neu,
        'eintritt': stufe.ab_datum, 'mit_unterschrift': True})


def versandt_fehler(stufe, am, heute):
    """Meldung, wenn `am` nicht als Versandtag erfasst werden darf — sonst ''."""
    if stufe.vertrag.mietzins_modell != 'staffel':
        return gettext('Der Vertrag ist keine Staffelmiete.')
    if stufe.mitteilung_versandt_am:
        return gettext('Die Mitteilung ist bereits als versandt markiert.')
    if am is None:
        return gettext('Bitte das Versanddatum angeben.')
    if am > heute:
        return gettext('Das Versanddatum kann nicht in der Zukunft liegen.')
    stand = _stand_von(stufe, heute)
    if stand.problem:
        return stand.problem
    if am < stand.fenster_ab:
        return gettext('Zu früh versandt: Die schriftliche Mitteilung darf frühestens vier Monate vor der '
                       'Erhöhung erfolgen, also ab dem %(datum)s (Art. 19a VMWG).') % {
                           'datum': stand.fenster_ab.strftime('%d.%m.%Y')}
    return ''


def als_versandt_markieren(stufe, am, heute):
    """Setzt `mitteilung_versandt_am` und erledigt die Pendenz. `ValueError` mit Klartext."""
    fehler = versandt_fehler(stufe, am, heute)
    if fehler:
        raise ValueError(fehler)
    stufe.mitteilung_versandt_am = am
    stufe.save(update_fields=['mitteilung_versandt_am'])
    pendenz_erledigen(stufe, heute)
    return stufe


# ── Pendenz (täglicher Lauf) ─────────────────────────────────────────────────
def pendenz_quelle(stufe):
    """Stabiler Schlüssel: macht die Pendenz je Stufe einmalig (idempotent)."""
    return f'staffel:{stufe.pk}'


def pendenz_erledigen(stufe, heute):
    from core.models import Pendenz
    for p in Pendenz.objects.filter(vertrag=stufe.vertrag, quelle=pendenz_quelle(stufe), erledigt=False):
        p.erledigt = True
        p.erledigt_am = heute
        p.save(update_fields=['erledigt', 'erledigt_am'])
    # Die Pendenz «Mitteilung fehlt» (MIET-09) erledigt sich, sobald die Stufe wirkt.
    if stufe_wirkt(stufe):
        for p in Pendenz.objects.filter(vertrag=stufe.vertrag, quelle=fehlt_quelle(stufe), erledigt=False):
            p.erledigt = True
            p.erledigt_am = heute
            p.save(update_fields=['erledigt', 'erledigt_am'])


def fehlt_quelle(stufe):
    """Schlüssel der Pendenz «Staffelmitteilung fehlt» (nach dem Eintritt der Stufe)."""
    return f'staffelfehlt:{stufe.pk}'


def fehlende_mitteilung_pendenzen(vertrag, stichtag):
    """Pendenz «Staffelmitteilung fehlt» für jede eingetretene Stufe, die nicht verrechnet wird (MIET-09).

    Aufrufer: der Sollstellungslauf (er verrechnet die Stufe NICHT, also muss die Verwaltung es erfahren)
    und der tägliche Lauf. Idempotent über `Pendenz.quelle`; eine erledigte Pendenz wird nicht
    wieder geöffnet. Läuft im Kontext der Organisation des Vertrags. Gibt die Zahl NEUER Pendenzen zurück."""
    from core.models import Pendenz
    if vertrag.mietzins_modell != 'staffel':
        return 0
    neu = 0
    for st in vertrag.staffelstufen.all():
        if not st.ab_datum or st.ab_datum > stichtag or stufe_wirkt(st):
            continue
        if vertrag.ende and vertrag.ende < st.ab_datum:
            continue
        quelle = fehlt_quelle(st)
        if Pendenz.objects.filter(vertrag=vertrag, quelle=quelle).exists():
            continue
        verspaetet = bool(st.mitteilung_versandt_am)
        Pendenz.objects.create(
            vertrag=vertrag, quelle=quelle, kategorie='vertrag', faellig_am=stichtag,
            liegenschaft=vertrag.einheit.liegenschaft if vertrag.einheit_id else None,
            titel=(f"Staffelmitteilung fehlt – {vertrag.mieter.display_name} "
                   f"({vertrag.einheit.bezeichnung}, Stufe ab {st.ab_datum:%d.%m.%Y})")[:200],
            beschreibung=(
                f"Die Staffelstufe ab {st.ab_datum:%d.%m.%Y} (Netto CHF {st.netto_mietzins}) wird NICHT verrechnet: "
                + ("Die Mitteilung wurde erst am %s versandt, also nicht rechtzeitig vor dem Eintritt. "
                   % st.mitteilung_versandt_am.strftime('%d.%m.%Y') if verspaetet
                   else "Es ist keine schriftliche Mitteilung als versandt erfasst. ")
                + "Seit dem 1.10.2025 verlangt Art. 269d Abs. 5 OR die schriftliche Mitteilung jeder "
                  "Staffelerhöhung; der bisherige Mietzins bleibt, bis die Rechtslage geklärt ist. "
                  "Mitteilung auf der Vertragsakte (Reiter Mietzins) prüfen oder nachholen; Rechtsfolge "
                  "einer verspäteten Mitteilung mit einer Fachperson klären."))
        neu += 1
    return neu


def fehlende_mitteilung_pendenzen_alle(heute):
    """Alle laufenden Staffelverträge der aktuellen Organisation (täglicher Lauf)."""
    from rentals.models import Mietvertrag
    neu = 0
    for v in (Mietvertrag.objects.filter(mietzins_modell='staffel', status__in=['aktiv', 'gekuendigt'])
              .select_related('mieter', 'einheit__liegenschaft').prefetch_related('staffelstufen')):
        neu += fehlende_mitteilung_pendenzen(v, heute)
    return neu


def pendenzen_erzeugen(heute, user=None):
    """Legt für jede Stufe, deren Erinnerung begonnen hat, eine Pendenz an. Gibt die Anzahl NEUER zurück.

    Läuft im Kontext EINER Organisation (`taeglicher_lauf._je_verwaltung`): `Mietvertrag.objects`
    und `Pendenz.objects` sehen nur deren Bestand. Wer keinen Kontext setzt, bekommt vom
    TenantManager einen Fehler — gewollt.

    Idempotent über `Pendenz.quelle`: ein zweiter Lauf legt nichts an, ändert eine offene Pendenz
    höchstens in Titel und Fälligkeit und öffnet eine erledigte nicht wieder."""
    from core.models import Pendenz
    from rentals.models import Mietvertrag
    neu = 0
    vertraege = (Mietvertrag.objects.filter(mietzins_modell='staffel', status__in=['aktiv', 'gekuendigt'])
                 .select_related('mieter', 'einheit__liegenschaft').prefetch_related('staffelstufen'))
    for v in vertraege:
        for stand in stufen_staende(v, heute):
            st = stand.stufe
            if stand.status == STATUS_VERSANDT or stand.problem:
                continue
            if stand.eintritt <= heute or heute < stand.erinnerung_ab:
                continue                                        # schon eingetreten / noch zu früh
            if v.ende and v.ende < stand.eintritt:
                continue                                        # der Vertrag endet vor der Erhöhung
            titel = (f"Staffelmiete: Erhöhung mitteilen – {v.mieter.display_name} "
                     f"({v.einheit.bezeichnung}, ab {stand.eintritt:%d.%m.%Y})")
            beschreibung = (f"Stufe ab {stand.eintritt:%d.%m.%Y}: Netto CHF {stand.bisher} → CHF {stand.neu} "
                            f"(+ CHF {stand.erhoehung}). Die schriftliche Mitteilung darf frühestens vier "
                            f"Monate vor der Erhöhung erfolgen, also ab {stand.fenster_ab:%d.%m.%Y} "
                            "(Art. 269d Abs. 5 OR, Art. 19a VMWG). Schreiben auf der Vertragsakte "
                            "(Reiter Mietzins) erstellen und nach dem Versand als versandt markieren.")
            p = Pendenz.objects.filter(vertrag=v, quelle=pendenz_quelle(st)).first()
            if p is None:
                Pendenz.objects.create(
                    vertrag=v, quelle=pendenz_quelle(st), titel=titel, beschreibung=beschreibung,
                    kategorie='frist', faellig_am=stand.fenster_ab, erstellt_von=user,
                    liegenschaft=v.einheit.liegenschaft if v.einheit_id else None)
                neu += 1
            elif not p.erledigt and (p.titel != titel or p.faellig_am != stand.fenster_ab):
                p.titel, p.faellig_am, p.beschreibung = titel, stand.fenster_ab, beschreibung
                p.save(update_fields=['titel', 'faellig_am', 'beschreibung'])
    return neu

