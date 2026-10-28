"""Zahlungsverzug nach Art. 257d OR — was eine Zahlung mit der Frist macht.

ART. 257d OR

Abs. 1: Ist der Mieter mit fälligen Mietzinsen oder Nebenkosten im Rückstand,
setzt ihm der Vermieter schriftlich eine Zahlungsfrist (Wohn- und
Geschäftsräume: mindestens dreissig Tage) und droht die Kündigung an.
Abs. 2: Bezahlt der Mieter **innert der Frist nicht**, kann der Vermieter
ausserordentlich kündigen.

Umgekehrt heisst das: Zahlt der Mieter den angemahnten Rückstand innert der
Frist vollständig, ist das Kündigungsrecht aus DIESER Fristansetzung
erloschen. Eine Frist, die danach weiter als «läuft ab» im Arbeitsvorrat, im
Fristen-Center oder auf der Vertragsakte steht, lädt zu einer Kündigung ein,
die unwirksam wäre. Deshalb schliesst ein Zahlungseingang die Frist und den
Zahlungsverzugsfall **sofort** — nicht erst beim nächsten Lauf.

WELCHE FORDERUNGEN DIE FRIST DECKT

Die Fristansetzung (`fw_verzug_257d`) mahnt alle am Tag der Ansetzung fälligen,
offenen Forderungen des Vertrags. Genau diese — fällig bis zum Tag, an dem die
Frist angelegt wurde — müssen beglichen sein. Später fällig gewordene Mieten
gehören nicht dazu: Für sie braucht es eine neue Fristansetzung, und sie dürfen
eine gewahrte Frist nicht künstlich offenhalten.

Nicht mitgezählt werden abgeleitete Forderungen (Mahngebühr, Verzugszins —
erkennbar an `stammrechnung`). Art. 257d nennt nur Mietzinse und Nebenkosten;
eine Frist, die wegen einer offenen Mahngebühr von CHF 20 aktiv bliebe,
schlüge eine Kündigung vor, die nicht zulässig ist.

WANN DIE FRIST ZU LAUFEN BEGINNT (Audit MIET-01)

Die Fristansetzung ist eine empfangsbedürftige Willenserklärung: Die Frist läuft ab **Zugang**, nicht ab Versand
und nicht ab der Abholeinladung. Wird das Einschreiben nicht zugestellt, sondern auf der Post hinterlegt
(Abholeinladung), gilt (BGE 119 II 147 E. 2):

* holt der Mieter es ab, ist der Zugang der Tag der **tatsächlichen Abholung**;
* holt er es nicht ab, wird der Zugang auf den **letzten Tag der siebentägigen Abholfrist** fingiert
  (Tag der Abholeinladung + 7).

Der Tag des Zugangs zählt nicht mit (Art. 77 Abs. 1 Ziff. 1 OR): Fristende = Zugang + 30 Tage. Bis der Zugang
bestätigt ist, ist das Fristende **vorläufig** und rechnet vom ungünstigsten Fall: Versand + 1 Tag Postweg +
7 Tage Abholfrist + 30 Tage (`provisorisches_fristende`). Die Kündigungssperre (`kuendigung_sperre`) gilt bis zu
diesem Tag, auch wenn nie ein Zugang bestätigt wurde. Eine zu früh ausgesprochene Kündigung ist nach dem
Bundesgericht anfechtbar (BGE 119 II 147 E. 4), nicht ohne Weiteres wirkungslos — gerade deshalb darf die
Anwendung sie nicht vorschlagen.

Fällt das Fristende auf einen Samstag, Sonntag oder Feiertag, ist der nächste Werktag der letzte Tag
(Art. 78 OR, `core/services/fristen.py`). Wer dann zahlt, zahlt rechtzeitig.

RECHTZEITIG HEISST: GUTSCHRIFT BIS FRISTENDE

Geldschulden sind Bringschulden; massgebend ist der Eingang beim Vermieter
(`Zahlungseingang.datum_eingang`), nicht der Zahlungsauftrag des Mieters. Der
letzte Tag der Frist (`Pendenz.faellig_am`) zählt noch mit.

Wird erst NACH Fristablauf bezahlt, besteht das Kündigungsrecht grundsätzlich
weiter. Dann wird die Frist nicht stillschweigend geschlossen, sondern mit
einem Vermerk versehen: Ob noch gekündigt wird, ist ein Entscheid der
Verwaltung, kein Automatismus.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from core.services.fristen import fristende as _fristende
from core.services.fristen import naechster_werktag

logger = logging.getLogger(__name__)

#: Kennung der Fristen-Pendenz aus `fw_verzug_257d`. Früher angelegte Fristen
#: tragen keine Quelle; sie werden am Titel erkannt (`_ALT_TITEL`).
QUELLE_PRAEFIX = '257d:'
_ALT_TITEL = 'Art. 257d: Zahlungsfrist'

#: Schlüssel der Fallart aus `faelle/management/commands/fallarten_anlegen.py`.
FALLART_SCHLUESSEL = 'zahlungsverzug'
SCHRITT_FRISTANSETZUNG = 'Zahlungsfrist mit Kündigungsandrohung'
SCHRITT_UEBERWACHEN = 'Fristablauf überwachen'

#: Zahlungsfrist in Tagen ab Zugang (Art. 257d Abs. 1 OR: bei Wohn- und Geschäftsräumen mindestens 30).
FRIST_TAGE = 30
#: Geschätzter Postweg bis zum Zustellversuch — nur für das VORLÄUFIGE Fristende.
POSTWEG_TAGE = 1
#: Abholfrist eines Einschreibens (BGE 119 II 147 E. 2): Am letzten Tag wird der Zugang fingiert.
ABHOLFRIST_TAGE = 7

_OFFENE_STATUS = ('offen', 'teilbezahlt', 'abgeschrieben')
VERMERK_LATE = 'Nach Fristablauf bezahlt'
#: Steht in jeder durch Zahlung erledigten Frist — daran erkennt
#: `kuendigung_sperre()` sie wieder, auch nach einem Neustart.
VERMERK_GEWAHRT = ('Eine Kündigung nach Art. 257d Abs. 2 OR gestützt auf '
                   'diese Fristansetzung ist ausgeschlossen.')


def quelle_fuer(vertrag):
    return f'{QUELLE_PRAEFIX}{vertrag.pk}'


def provisorisches_fristende(versand_am, frist_tage=FRIST_TAGE):
    """Vorläufiges Fristende eines versandten Einschreibens, solange der Zugang nicht bestätigt ist:
    Versand + Postweg + Abholfrist + Zahlungsfrist — der späteste Zugang, mit dem zu rechnen ist.
    Nie zu kurz (Audit MIET-01)."""
    return _fristende(versand_am, POSTWEG_TAGE + ABHOLFRIST_TAGE + (frist_tage or FRIST_TAGE))


def fiktiver_zugang(abholeinladung_am):
    """Zugang eines NICHT abgeholten Einschreibens: der letzte Tag der siebentägigen Abholfrist
    (Tag der Abholeinladung + 7). Fällt er auf einen Nicht-Werktag, gilt der nächste Werktag
    (konservativ: der Zugang liegt dann später, die Frist endet später)."""
    return naechster_werktag(abholeinladung_am + timedelta(days=ABHOLFRIST_TAGE))


def definitives_fristende(zugang, frist_tage=FRIST_TAGE):
    """Fristende ab bestätigtem Zugang: Zugang + Frist, ein Samstag, Sonntag oder Feiertag rückt auf den
    nächsten Werktag (Art. 78 OR)."""
    return _fristende(zugang, frist_tage or FRIST_TAGE)


def zugang_unbestaetigt(pendenz):
    """Die Fristansetzung ist als Einschreiben erfasst, der Zugang aber nicht bestätigt."""
    return pendenz.zugang_am is None and bool(pendenz.versand_am or pendenz.sendungsnummer)


def fristende_von(pendenz):
    """Das WIRKSAME letzte Tag der Zahlungsfrist dieser Pendenz — oder None.

    · Zugang bestätigt: gespeichertes Fristende.
    · Zugang unbestätigt mit Versanddatum: mindestens das vorläufige Fristende. Das gilt auch für Fristen,
      die vor der Korrektur mit einem kürzeren Puffer angelegt wurden.
    · In jedem Fall auf den nächsten Werktag gerückt (Art. 78 OR) — auch bei Altdaten."""
    ende = pendenz.faellig_am
    if ende is None:
        return None
    if pendenz.zugang_am is None and pendenz.versand_am:
        ende = max(ende, provisorisches_fristende(pendenz.versand_am, pendenz.frist_tage))
    return naechster_werktag(ende)


def ist_257d_frist(pendenz):
    return ((pendenz.quelle or '').startswith(QUELLE_PRAEFIX)
            or (pendenz.kategorie == 'frist'
                and (pendenz.titel or '').startswith(_ALT_TITEL)))


def aktive_fristen(vertrag):
    """Offene 257d-Fristen eines Vertrags.

    Über den Rückbezug `vertrag.pendenzen`: Er geht von einem bereits
    geladenen Vertrag aus und kann keine fremde Organisation erreichen
    (siehe `TenantManager.get_queryset`). Deshalb funktioniert das auch im
    Signal ohne Anfragekontext.
    """
    return (vertrag.pendenzen.filter(erledigt=False)
            .filter(Q(quelle__startswith=QUELLE_PRAEFIX)
                    | Q(kategorie='frist', titel__startswith=_ALT_TITEL)))


def _stichtag(pendenz):
    """Tag der Fristansetzung — bis dahin fällige Forderungen sind gemahnt."""
    if pendenz.erstellt_am:
        return timezone.localtime(pendenz.erstellt_am).date()
    return timezone.localdate()


def verzugsforderungen(vertrag, stichtag):
    """Die Forderungen, die einen Verzug nach Art. 257d OR begründen können: nicht stornierte, bis zum
    `stichtag` fällige **Mietzinse und Nebenkosten** des Vertrags (`forderungsart='miete'`).

    Nicht dazu gehören Weiterverrechnungen, Selbstbehalt, Schlussabrechnung, Schadenersatz, Betreibungskosten
    und abgeleitete Forderungen (Mahngebühr, Verzugszins — `stammrechnung`). Art. 257d Abs. 1 nennt «fällige
    Mietzinse oder Nebenkosten», und eine Androhung, die mehr verlangt, ist angreifbar (Audit MIET-02).
    Die Reihenfolge ist die der Fälligkeit, damit der Brief die Monate geordnet nennt."""
    rechnungen = [r for r in (vertrag.debitoren_rechnungen
                              .exclude(status='storniert')
                              .filter(stammrechnung__isnull=True, forderungsart='miete')
                              .prefetch_related('zahlungseingaenge'))
                  if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= stichtag]
    return sorted(rechnungen, key=lambda r: (r.faellig_am or r.datum, r.pk))


def gedeckte_forderungen(pendenz):
    """Die Forderungen, deren Zahlung die Frist wahrt (siehe Modulkopf)."""
    return verzugsforderungen(pendenz.vertrag, _stichtag(pendenz))


def rueckstand(pendenz):
    """Noch offener Betrag der von dieser Frist gedeckten Forderungen."""
    return sum((r.offener_betrag for r in gedeckte_forderungen(pendenz)
                if r.status in _OFFENE_STATUS), Decimal('0.00'))


def _zahltag(forderungen):
    """Tag der letzten verbuchten Gutschrift auf die gedeckten Forderungen."""
    tage = [z.datum_eingang for r in forderungen
            for z in r.zahlungseingaenge.all()
            if z.status == 'verbucht' and z.datum_eingang]
    return max(tage) if tage else timezone.localdate()


def frist_erledigen(pendenz, grund):
    """Setzt die Frist auf erledigt und hält den Grund in der Beschreibung fest."""
    heute = timezone.localdate()
    pendenz.erledigt = True
    pendenz.erledigt_am = heute
    pendenz.beschreibung = (f'{grund}\n\n{pendenz.beschreibung}').strip()
    pendenz.save(update_fields=['erledigt', 'erledigt_am', 'beschreibung'])


def _fall_abschliessen(vertrag, grund):
    """Schliesst die offenen Zahlungsverzugsfälle des Vertrags ab."""
    from django.contrib.contenttypes.models import ContentType

    from faelle.models import Fall

    ct = ContentType.objects.get_for_model(type(vertrag))
    jetzt = timezone.now()
    n = 0
    for fall in (Fall.objects.offen()
                 .filter(akte_typ=ct, akte_id=vertrag.pk,
                         fallart__schluessel=FALLART_SCHLUESSEL)):
        fall.status = Fall.ABGESCHLOSSEN
        fall.abgeschlossen_am = jetzt
        fall.letzte_bewegung = jetzt
        fall.notiz = (f'{grund}\n\n{fall.notiz}').strip()
        fall.save(update_fields=['status', 'abgeschlossen_am',
                                 'letzte_bewegung', 'notiz'])
        # Der Überwachungsschritt trägt die Frist als Datum. Offen gelassen,
        # stünde er weiter mit «läuft ab» im Arbeitsvorrat.
        for s in fall.schritte.filter(bezeichnung=SCHRITT_UEBERWACHEN,
                                      erledigt_am__isnull=True):
            s.erledigt_am = jetzt
            s.bemerkung = (f'{grund}\n\n{s.bemerkung}').strip()
            s.save(update_fields=['erledigt_am', 'bemerkung'])
        n += 1
    return n


VERMERK_WIEDER = 'Wieder geöffnet'


def _wieder_oeffnen(vertrag):
    """Öffnet die jüngste «durch Zahlung» erledigte Frist wieder, wenn ihr
    Rückstand wieder offen ist (Korrektur 26.10.2026).

    Das geschieht, wenn die Zahlung, die die Frist gewahrt hat, wegfällt:
    Storno, Rückbuchung der Bank, aufgehobene Fehlzuordnung (etwa die Zahlung
    eines Fremden, die auf die Miete gebucht wurde). Der Mieter hat dann nicht
    bezahlt — die Frist läuft bzw. ist abgelaufen, und der Fall gehört wieder
    in den Arbeitsvorrat. Vorher blieb sie still «erledigt», samt Vermerk, der
    eine Kündigung sperrt (`kuendigung_sperre`).

    Nur mit Status offen/teilbezahlt: Eine abgeschriebene Forderung ist ein
    Entscheid der Verwaltung, kein Rückstand, der eine Frist wiederbelebt.
    """
    from django.contrib.contenttypes.models import ContentType

    from faelle.models import Fall, Fallschritt

    if aktive_fristen(vertrag).exists():
        return 0
    p = (vertrag.pendenzen
         .filter(Q(quelle__startswith=QUELLE_PRAEFIX)
                 | Q(kategorie='frist', titel__startswith=_ALT_TITEL))
         .order_by('-erstellt_am', '-pk').first())
    if p is None or not p.erledigt or VERMERK_GEWAHRT not in (p.beschreibung or ''):
        return 0
    offen = sum((r.offener_betrag for r in gedeckte_forderungen(p)
                 if r.status in ('offen', 'teilbezahlt')), Decimal('0.00'))
    if offen <= 0:
        return 0
    heute = timezone.localdate()
    grund = (f'{VERMERK_WIEDER} am {heute:%d.%m.%Y}: Die Zahlung, die den Rückstand '
             f'beglich, ist storniert oder wurde einem anderen Posten zugeordnet — '
             f'offen sind wieder CHF {offen}.')
    # Den Absatz mit dem Sperrvermerk entfernen, sonst sperrt er die Kündigung weiter.
    rest = [a for a in (p.beschreibung or '').split('\n\n') if VERMERK_GEWAHRT not in a]
    p.erledigt = False
    p.erledigt_am = None
    p.beschreibung = '\n\n'.join([grund, *rest]).strip()
    p.save(update_fields=['erledigt', 'erledigt_am', 'beschreibung'])

    ct = ContentType.objects.get_for_model(type(vertrag))
    fall = (Fall.objects.filter(akte_typ=ct, akte_id=vertrag.pk, fallart__schluessel=FALLART_SCHLUESSEL,
                                status=Fall.ABGESCHLOSSEN, notiz__startswith='Automatisch abgeschlossen')
            .order_by('-abgeschlossen_am', '-pk').first())
    if fall is not None and not Fall.objects.offen().filter(
            akte_typ=ct, akte_id=vertrag.pk, fallart__schluessel=FALLART_SCHLUESSEL).exists():
        fall.status = Fall.OFFEN
        fall.abgeschlossen_am = None
        fall.letzte_bewegung = timezone.now()
        fall.notiz = f'{grund}\n\n{fall.notiz}'.strip()
        fall.save(update_fields=['status', 'abgeschlossen_am', 'letzte_bewegung', 'notiz'])
        for schritt in Fallschritt.objects.filter(fall=fall, bezeichnung=SCHRITT_UEBERWACHEN,
                                                  bemerkung__startswith='Automatisch abgeschlossen'):
            schritt.erledigt_am = None
            schritt.bemerkung = f'{grund}\n\n{schritt.bemerkung}'.strip()
            schritt.save(update_fields=['erledigt_am', 'bemerkung'])
    logger.warning('257d-Frist %s (Vertrag %s) wieder geöffnet: Rückstand CHF %s wieder offen',
                   p.pk, vertrag.pk, offen)
    return 1


def pruefe_nach_zahlung(vertrag):
    """Schliesst gewahrte 257d-Fristen und den Fall, wenn der Rückstand bezahlt ist
    — und öffnet sie wieder, wenn die Zahlung wegfällt (`_wieder_oeffnen`).

    Idempotent und billig, wenn keine Frist läuft (zwei Abfragen). Gibt die
    Anzahl geschlossener Fristen zurück.
    """
    if vertrag is None or not vertrag.pk:
        return 0
    from core.tenancy import organisation_kontext

    with organisation_kontext(vertrag.organisation):
        if _wieder_oeffnen(vertrag):
            return 0
        geschlossen = 0
        for p in aktive_fristen(vertrag):
            forderungen = gedeckte_forderungen(p)
            offen = sum((r.offener_betrag for r in forderungen
                         if r.status in _OFFENE_STATUS), Decimal('0.00'))
            if offen > 0:
                continue
            bezahlt_am = _zahltag(forderungen)
            # Das letzte Tag der Frist ist ein Werktag (Art. 78 OR): Eine Zahlung am Montag nach einem
            # Sonntags-Fristende ist rechtzeitig.
            ende = fristende_von(p)
            if ende and bezahlt_am > ende:
                # Kündigungsrecht besteht weiter — nur vermerken, einmal.
                if VERMERK_LATE not in (p.beschreibung or ''):
                    p.beschreibung = (
                        f'{VERMERK_LATE} ({bezahlt_am:%d.%m.%Y}, Frist bis '
                        f'{ende:%d.%m.%Y}). Das Kündigungsrecht nach '
                        f'Art. 257d Abs. 2 OR besteht grundsätzlich weiter — '
                        f'Entscheid der Verwaltung erforderlich.\n\n'
                        f'{p.beschreibung}').strip()
                    p.save(update_fields=['beschreibung'])
                continue
            frist_erledigen(p, (
                f'Erledigt am {timezone.localdate():%d.%m.%Y}: Rückstand am '
                f'{bezahlt_am:%d.%m.%Y} vollständig bezahlt, innert Frist'
                + (f' (bis {ende:%d.%m.%Y})' if ende else '')
                + '. ' + VERMERK_GEWAHRT))
            geschlossen += 1
            logger.info('257d-Frist %s (Vertrag %s) durch Zahlung erledigt',
                        p.pk, vertrag.pk)

        # Kein fälliger Rückstand mehr und keine laufende Frist: Der Vorgang ist
        # erledigt — auch wenn es nie zur Fristansetzung kam (Mieter zahlt nach
        # der 3. Mahnung). Sonst bliebe der Fall «Zahlungsverzug» offen und die
        # Vorschlags-Pendenz «Fristansetzung prüfen» stünde weiter im Arbeitsvorrat.
        if not aktive_fristen(vertrag).exists() and not faelliger_rueckstand(vertrag):
            if geschlossen:
                grund = ('Zahlungsrückstand innert der Frist nach Art. 257d OR '
                         'beglichen.')
            else:
                grund = 'Zahlungsrückstand vollständig beglichen.'
            _fall_abschliessen(vertrag, (
                f'Automatisch abgeschlossen am {timezone.localdate():%d.%m.%Y}: {grund}'))
            vorschlaege_erledigen(vertrag, 'Rückstand bezahlt — keine Fristansetzung nötig.')
        # Eine laufende Zahlungsvereinbarung sieht die Zahlung sofort (erfüllt/Raten gedeckt).
        from core.services.zahlungsvereinbarung import pruefen_vertrag
        pruefen_vertrag(vertrag)
    return geschlossen


def faelliger_rueckstand(vertrag, stichtag=None):
    """Offener Betrag der heute fälligen Mietforderungen (nur Mietzins und Nebenkosten, ohne Mahngebühr/Zins)."""
    stichtag = stichtag or timezone.localdate()
    return sum((r.offener_betrag for r in verzugsforderungen(vertrag, stichtag)
                if r.status in ('offen', 'teilbezahlt')), Decimal('0.00'))


class EigentuemerSchutz(PermissionDenied):
    """Gegen einen Stockwerkeigentümer gibt es keine Kündigungsandrohung (Art. 257d OR gilt nur für Mieter).
    Als `PermissionDenied` führt sie in einer Ansicht zu einer 403-Antwort — es entsteht nie ein Schreiben."""


def _norm(text):
    return ''.join((text or '').casefold().split())


def eigentuemer_als_mieter(vertrag):
    """Der Stockwerkeigentümer (oder Miteigentümer), der in einem Mietvertrag der STWEG als Mieter steht — oder None.

    Ein Eigentümer erscheint nur dann als Mieter, wenn er fälschlich als solcher erfasst wurde (Wohnung selbst
    bewohnt, «Mietvertrag» zur Verbuchung der Beiträge). Erkannt wird er an gleicher E-Mail-Adresse oder gleichem
    Namen. Ein Mieter einer vermieteten Eigentumswohnung ist ein echter Mieter und bleibt es."""
    einheit = vertrag.einheit if vertrag.einheit_id else None
    if einheit is None or not einheit.liegenschaft.ist_stweg:
        return None
    mieter = vertrag.mieter
    mail, name = (getattr(mieter, 'email', '') or '').casefold().strip(), _norm(mieter.display_name)
    kandidaten = [e for e in [einheit.stockwerkeigentuemer, *einheit.miteigentuemer.all()] if e is not None]
    for e in kandidaten:
        if (mail and mail == (e.email or '').casefold().strip()) or (name and name == _norm(e.firma_oder_name)):
            return e
    return None


def pruefe_kein_eigentuemer(vertrag):
    """Wirft `EigentuemerSchutz`, wenn der «Mieter» in Wahrheit Stockwerkeigentümer der Einheit ist."""
    e = eigentuemer_als_mieter(vertrag)
    if e is not None:
        raise EigentuemerSchutz(
            f'«{e.firma_oder_name}» ist Stockwerkeigentümer dieser Einheit, kein Mieter: eine Kündigungsandrohung '
            'nach Art. 257d OR ist nicht zulässig. Das Inkasso der Gemeinschaft läuft über die STWEG-Mahnungen '
            '(Retentionsrecht, Gemeinschaftspfandrecht).')


#: Quelle der Vorschlags-Pendenz «257d-Fristansetzung prüfen». Bewusst NICHT
#: `257d:` — sie ist keine Frist, sondern die Aufforderung, eine zu setzen.
VORSCHLAG_PRAEFIX = '257d-vorschlag:'


def eskalation_257d(rechnung, benutzer=None):
    """Die letzte Mahnstufe (Konfiguration `kuendigung`) führt zur Fristansetzung.

    Stresstest 30.09.2026, Punkt 7: Stufe 3 hiess «Kündigungsandrohung» und tat
    nichts — die echte 257d-Fristansetzung war ein getrennter Handprozess ohne
    Verbindung zum Mahnlauf. Jetzt entsteht hier die Pendenz, die dorthin führt,
    und der Fall «Zahlungsverzug» wird eröffnet. Die Fristansetzung selbst bleibt
    ein bewusster Schritt der Verwaltung (Einschreiben, Unterschrift, Rolle) —
    sie wird nicht automatisch versandt.

    Idempotent: Läuft bereits eine 257d-Frist oder liegt schon ein Vorschlag vor,
    geschieht nichts. Gibt die Pendenz zurück, wenn eine angelegt wurde.
    """
    from core.models import Pendenz

    v = rechnung.vertrag
    if v is None or rechnung.stammrechnung_id:
        return None
    if rechnung.forderungsart != 'miete':
        # Art. 257d OR gilt nur für Mietzinse und Nebenkosten: Eine Weiterverrechnung oder ein Selbstbehalt
        # führt nach der letzten Mahnstufe nicht zur Kündigungsandrohung (Audit MIET-02).
        return None
    if eigentuemer_als_mieter(v) is not None:       # Stockwerkeigentümer: keine Fristansetzung, keine Pendenz
        logger.warning('257d-Eskalation für Vertrag %s unterlassen: Mieter ist Stockwerkeigentümer', v.pk)
        return None
    if aktive_fristen(v).exists():
        return None
    quelle = f'{VORSCHLAG_PRAEFIX}{v.pk}'
    if v.pendenzen.filter(quelle=quelle, erledigt=False).exists():
        return None
    lg = v.einheit.liegenschaft if v.einheit_id else None
    fall_eroeffnen(v, benutzer=benutzer, frist_angesetzt=False,
                   betreff=f'Zahlungsverzug {v.mieter.display_name} – {rechnung.titel}')
    return Pendenz.objects.create(
        titel=f'Art. 257d: Fristansetzung prüfen – {v.mieter.display_name}',
        beschreibung=(
            f'Letzte Mahnstufe erreicht für «{rechnung.titel}» '
            f'(CHF {rechnung.offener_betrag:.2f} offen). Bleibt die Zahlung aus, '
            'Zahlungsfrist mit Kündigungsandrohung per Einschreiben ansetzen '
            '(Wohn-/Geschäftsräume: mindestens 30 Tage, Art. 257d Abs. 1 OR). '
            'Erst nach unbenütztem Ablauf kann gekündigt werden.'),
        kategorie='frist', faellig_am=timezone.localdate(), vertrag=v, liegenschaft=lg,
        quelle=quelle, erstellt_von=benutzer)


#: Quelle der Pendenz «Original per Einschreiben versenden» nach einer 257d-Kopie per E-Mail.
EINSCHREIBEN_PRAEFIX = '257d-einschreiben:'


def vorschlaege_erledigen(vertrag, grund):
    """Schliesst die Vorschlags- und Einschreiben-Pendenzen des Vertrags (Fristansetzung
    erfolgt oder Rückstand bezahlt). Gibt die Anzahl zurück."""
    n = 0
    for p in vertrag.pendenzen.filter(
            Q(quelle__startswith=VORSCHLAG_PRAEFIX) | Q(quelle__startswith=EINSCHREIBEN_PRAEFIX),
            erledigt=False):
        frist_erledigen(p, grund)
        n += 1
    return n


def fall_eroeffnen(vertrag, benutzer=None, betreff='', frist=None, frist_angesetzt=True):
    """Eröffnet (oder findet) den Zahlungsverzugsfall zum Vertrag.

    Nur wenn die Organisation die Fallart eingerichtet hat
    (`manage.py fallarten_anlegen`). Fehlt sie, bleibt es bei der Frist —
    eine Fallart aus dem Nichts anzulegen hiesse, der Verwaltung Schritte
    vorzuschreiben, die sie nicht gewählt hat.
    """
    from django.contrib.contenttypes.models import ContentType

    from faelle.models import Fall, Fallart

    art = Fallart.objects.filter(schluessel=FALLART_SCHLUESSEL, aktiv=True).first()
    if art is None:
        return None
    ct = ContentType.objects.get_for_model(type(vertrag))
    fall = (Fall.objects.offen()
            .filter(akte_typ=ct, akte_id=vertrag.pk, fallart=art).first())
    if fall is None:
        fall = Fall(fallart=art, akte=vertrag, zustaendig=benutzer,
                    betreff=betreff[:200])
        fall.save()
        fall.schritte_anlegen()
    schritt = fall.schritte.filter(bezeichnung=SCHRITT_FRISTANSETZUNG,
                                   erledigt_am__isnull=True).first()
    if schritt is not None and frist_angesetzt:
        schritt.erledigen(benutzer)
    if frist is not None:
        fall.schritte.filter(bezeichnung=SCHRITT_UEBERWACHEN,
                             erledigt_am__isnull=True).update(frist=frist)
    fall.bewegt()
    return fall


def fall_frist_nachfuehren(vertrag, frist):
    """Zieht die Frist im Überwachungsschritt nach (Zugang bestätigt o. ä.)."""
    from django.contrib.contenttypes.models import ContentType

    from faelle.models import Fallschritt

    ct = ContentType.objects.get_for_model(type(vertrag))
    return (Fallschritt.objects
            .filter(fall__akte_typ=ct, fall__akte_id=vertrag.pk,
                    fall__fallart__schluessel=FALLART_SCHLUESSEL,
                    bezeichnung=SCHRITT_UEBERWACHEN, erledigt_am__isnull=True)
            .exclude(fall__status__in=('abgeschlossen', 'abgebrochen'))
            .update(frist=frist))


def kuendigung_sperre(vertrag, stichtag):
    """Grund, weshalb eine Kündigung wegen Zahlungsverzugs am `stichtag` nicht
    geht — oder None.

    Zwei Fälle sperren:

    · Eine Frist läuft noch (wirksames Fristende ≥ Stichtag, `fristende_von`). Gekündigt werden darf erst
      nach unbenütztem Ablauf; vorher ist die Kündigung anfechtbar. Ist der Zugang des Einschreibens nicht
      bestätigt, gilt das VORLÄUFIGE Fristende (Versand + Postweg + Abholfrist + 30 Tage): Wer den Zugang
      nicht nachträgt, wird nicht zu früh freigegeben (Audit MIET-01).
    · Die jüngste Fristansetzung wurde durch rechtzeitige Zahlung erledigt,
      und keine neue läuft. Dann gibt es keine Grundlage mehr.

    Ohne jede Frist im System wird nicht gesperrt: Eine Androhung kann auch
    ausserhalb der Anwendung verschickt worden sein.
    """
    aktiv = list(aktive_fristen(vertrag).order_by('faellig_am'))
    laufend = sorted(((fristende_von(p), p) for p in aktiv
                      if fristende_von(p) and fristende_von(p) >= stichtag), key=lambda x: x[0])
    if laufend:
        ende, p = laufend[-1]
        text = (f'Die Zahlungsfrist nach Art. 257d OR läuft noch bis '
                f'{ende:%d.%m.%Y}. Eine Kündigung wegen Zahlungsverzugs '
                f'ist erst nach unbenütztem Ablauf zulässig.')
        if zugang_unbestaetigt(p):
            text += (' Der Zugang des Einschreibens ist nicht bestätigt — das Fristende ist vorläufig '
                     '(Versand + Postweg + 7 Tage Abholfrist + 30 Tage). Zugang aus Track & Trace '
                     'bestätigen, dann gilt das genaue Fristende.')
        return text
    if aktiv:
        return None
    juengste = (vertrag.pendenzen
                .filter(Q(quelle__startswith=QUELLE_PRAEFIX)
                        | Q(kategorie='frist', titel__startswith=_ALT_TITEL))
                .order_by('-erstellt_am', '-pk').first())
    if juengste and juengste.erledigt and VERMERK_GEWAHRT in (juengste.beschreibung or ''):
        return ('Der Rückstand wurde innert der Zahlungsfrist nach Art. 257d OR '
                'vollständig bezahlt — die Fristansetzung ist erledigt. Eine '
                'Kündigung wegen Zahlungsverzugs braucht eine neue Fristansetzung.')
    return None


def kuendigung_hinweis(vertrag, stichtag):
    """Warnung (keine Sperre), wenn die Frist zwar abgelaufen ist, der Zugang des Einschreibens aber nie
    bestätigt wurde. Das Fristende beruht dann auf der Annahme eines Postwegs von einem Tag; wurde das
    Schreiben später zugestellt, ist die Kündigung zu früh (anfechtbar). Leer, wenn nichts zu bemerken ist."""
    for p in aktive_fristen(vertrag):
        ende = fristende_von(p)
        if ende and ende < stichtag and zugang_unbestaetigt(p):
            return ('Der Zugang der Fristansetzung (Einschreiben) wurde nie bestätigt. Das Fristende '
                    f'{ende:%d.%m.%Y} rechnet mit einem Postweg von einem Tag. Vor der Kündigung den Zugang '
                    'aus Track & Trace prüfen und bestätigen: Läuft die Frist ab dem tatsächlichen Zugang '
                    'noch, ist die Kündigung zu früh (anfechtbar, BGE 119 II 147).')
    return None
