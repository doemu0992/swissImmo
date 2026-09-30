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
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Kennung der Fristen-Pendenz aus `fw_verzug_257d`. Früher angelegte Fristen
#: tragen keine Quelle; sie werden am Titel erkannt (`_ALT_TITEL`).
QUELLE_PRAEFIX = '257d:'
_ALT_TITEL = 'Art. 257d: Zahlungsfrist'

#: Schlüssel der Fallart aus `faelle/management/commands/fallarten_anlegen.py`.
FALLART_SCHLUESSEL = 'zahlungsverzug'
SCHRITT_FRISTANSETZUNG = 'Zahlungsfrist mit Kündigungsandrohung'
SCHRITT_UEBERWACHEN = 'Fristablauf überwachen'

_OFFENE_STATUS = ('offen', 'teilbezahlt', 'abgeschrieben')
VERMERK_LATE = 'Nach Fristablauf bezahlt'
#: Steht in jeder durch Zahlung erledigten Frist — daran erkennt
#: `kuendigung_sperre()` sie wieder, auch nach einem Neustart.
VERMERK_GEWAHRT = ('Eine Kündigung nach Art. 257d Abs. 2 OR gestützt auf '
                   'diese Fristansetzung ist ausgeschlossen.')


def quelle_fuer(vertrag):
    return f'{QUELLE_PRAEFIX}{vertrag.pk}'


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


def gedeckte_forderungen(pendenz):
    """Die Forderungen, deren Zahlung die Frist wahrt (siehe Modulkopf)."""
    stichtag = _stichtag(pendenz)
    return [r for r in (pendenz.vertrag.debitoren_rechnungen
                        .exclude(status='storniert')
                        .filter(stammrechnung__isnull=True)
                        .prefetch_related('zahlungseingaenge'))
            if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= stichtag]


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


def pruefe_nach_zahlung(vertrag):
    """Schliesst gewahrte 257d-Fristen und den Fall, wenn der Rückstand bezahlt ist.

    Idempotent und billig, wenn keine Frist läuft (eine Abfrage). Gibt die
    Anzahl geschlossener Fristen zurück.
    """
    if vertrag is None or not vertrag.pk:
        return 0
    from core.tenancy import organisation_kontext

    with organisation_kontext(vertrag.organisation):
        geschlossen = 0
        for p in aktive_fristen(vertrag):
            forderungen = gedeckte_forderungen(p)
            offen = sum((r.offener_betrag for r in forderungen
                         if r.status in _OFFENE_STATUS), Decimal('0.00'))
            if offen > 0:
                continue
            bezahlt_am = _zahltag(forderungen)
            if p.faellig_am and bezahlt_am > p.faellig_am:
                # Kündigungsrecht besteht weiter — nur vermerken, einmal.
                if VERMERK_LATE not in (p.beschreibung or ''):
                    p.beschreibung = (
                        f'{VERMERK_LATE} ({bezahlt_am:%d.%m.%Y}, Frist bis '
                        f'{p.faellig_am:%d.%m.%Y}). Das Kündigungsrecht nach '
                        f'Art. 257d Abs. 2 OR besteht grundsätzlich weiter — '
                        f'Entscheid der Verwaltung erforderlich.\n\n'
                        f'{p.beschreibung}').strip()
                    p.save(update_fields=['beschreibung'])
                continue
            frist_erledigen(p, (
                f'Erledigt am {timezone.localdate():%d.%m.%Y}: Rückstand am '
                f'{bezahlt_am:%d.%m.%Y} vollständig bezahlt, innert Frist'
                + (f' (bis {p.faellig_am:%d.%m.%Y})' if p.faellig_am else '')
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
    """Offener Betrag der heute fälligen Mietforderungen (ohne Mahngebühr/Zins)."""
    stichtag = stichtag or timezone.localdate()
    total = Decimal('0.00')
    for r in (vertrag.debitoren_rechnungen.filter(status__in=('offen', 'teilbezahlt'),
                                                  stammrechnung__isnull=True)
              .prefetch_related('zahlungseingaenge')):
        if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= stichtag:
            total += r.offener_betrag
    return total


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


def vorschlaege_erledigen(vertrag, grund):
    """Schliesst die Vorschlags-Pendenzen des Vertrags. Gibt die Anzahl zurück."""
    n = 0
    for p in vertrag.pendenzen.filter(quelle__startswith=VORSCHLAG_PRAEFIX, erledigt=False):
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

    · Eine Frist läuft noch (Fristende ≥ Stichtag). Gekündigt werden darf erst
      nach unbenütztem Ablauf; vorher ist die Kündigung unwirksam.
    · Die jüngste Fristansetzung wurde durch rechtzeitige Zahlung erledigt,
      und keine neue läuft. Dann gibt es keine Grundlage mehr.

    Ohne jede Frist im System wird nicht gesperrt: Eine Androhung kann auch
    ausserhalb der Anwendung verschickt worden sein.
    """
    aktiv = list(aktive_fristen(vertrag).order_by('faellig_am'))
    laufend = [p for p in aktiv if p.faellig_am and p.faellig_am >= stichtag]
    if laufend:
        p = laufend[-1]
        return (f'Die Zahlungsfrist nach Art. 257d OR läuft noch bis '
                f'{p.faellig_am:%d.%m.%Y}. Eine Kündigung wegen Zahlungsverzugs '
                f'ist erst nach unbenütztem Ablauf zulässig.')
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
