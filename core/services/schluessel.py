"""Schlüssel und Schliessanlage (Modul 2, 27.10.2026).

Die Fachlogik hinter dem Abschnitt «Schliessanlage» der Liegenschaft, der
Ausgabe- und Rücknahmeseite, den Schlüssellisten der Akten und der Buchung aus
der Wohnungsabnahme. Die Views (core/views/fw/schluessel.py) rufen nur hierher.

BESTAND EINES SCHLÜSSELS

`Schluessel.anzahl` ist die Zahl der Exemplare. Davon sind `ausgegeben`
(offene Ausgaben), `verloren` (Ausgaben mit Status «verloren») und der Rest
liegt im Büro. Ein verlorenes Exemplar zählt nicht mehr als verfügbar: Es ist
nicht mehr da.

VERLUST (Entscheid E9)

Ein Verlust erzeugt eine Pendenz «Zylinder ersetzen». Die Kosten werden NICHT
automatisch weiterverrechnet; die Pendenz führt zur Debitorenrechnung, die
eine Person auslöst. In der Abnahme bleibt der Ersatz je fehlendem Schlüssel
(`AbnahmeSchluessel.kosten_je_stueck`) wie bisher.

ABNAHME

Der Abschluss der Einzugsabnahme bucht die Ausgabe der gezählten Schlüssel an
den Vertrag, der Abschluss der Auszugsabnahme nimmt die offenen Ausgaben des
Vertrags zurück; was fehlt, wird «verloren». Die Zeilen des Protokolls haben
keinen Fremdschlüssel zum Register — sie entstehen aus Typ und Nummer
(`schluessel_anlegen`) und werden über genau diese beiden Texte wieder
zugeordnet. Eine Zeile, die sich nicht zuordnen lässt, bucht nichts und wird
gemeldet (`abnahme_buchen` gibt sie zurück).
"""
import logging
from collections import OrderedDict
from datetime import date

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.translation import gettext

log = logging.getLogger(__name__)

ART_KUERZEL = {'haupt': 'HS', 'gruppe': 'GS', 'einzel': 'ES'}
#: Quelle der Verlust-Pendenz. «intern»: Verlust durch einen Hauswart (Benutzer)
#: — dort gibt es niemanden, dem eine Debitorenrechnung ginge.
VERLUST_QUELLE = 'schluessel:verlust:'
VERLUST_INTERN_QUELLE = 'schluessel:verlust-intern:'
VERLUST_TITEL = 'Zylinder ersetzen'
MAX_POSTEN = 30


def _modelle():
    from portfolio.models import Schluessel, SchluesselAusgabe
    return Schluessel, SchluesselAusgabe


def kuerzel(schluessel):
    return ART_KUERZEL.get(schluessel.art, 'ES')


def _norm(text):
    return ' '.join((text or '').split()).casefold()


# ---------------------------------------------------------------------------
# Empfänger
# ---------------------------------------------------------------------------

def empfaenger_code(a):
    """Der Schlüssel des Empfängers einer Ausgabe für `?an=` (Rücknahmeseite)."""
    if a.vertrag_id:
        return f'vertrag:{a.vertrag_id}'
    if a.mieter_id:
        return f'mieter:{a.mieter_id}'
    if a.handwerker_id:
        return f'handwerker:{a.handwerker_id}'
    if a.benutzer_id:
        return f'benutzer:{a.benutzer_id}'
    return ''


def hauswarte(liegenschaft, organisation):
    """Benutzer, die als Hauswart Schlüssel erhalten können.

    `Benutzer` trägt KEINEN Mandantenfilter (Skill bekannte-fallen, Nr. 4).
    Zur Auswahl stehen deshalb nur Mitglieder DIESER Organisation: die
    Hauswarte der Liegenschaft und die Mitglieder mit der Rolle «Hauswart»."""
    from benutzer.models import Benutzer
    from crm.models import Mitgliedschaft
    if organisation is None:
        return Benutzer.objects.none()
    mitglieder = Mitgliedschaft.objects.filter(organisation=organisation)
    alle = mitglieder.values_list('benutzer_id', flat=True)
    rolle = mitglieder.filter(rolle=Mitgliedschaft.ROLLE_HAUSWART).values_list('benutzer_id', flat=True)
    return (Benutzer.objects.filter(Q(id__in=list(rolle))
                                    | Q(id__in=list(alle), hauswart_liegenschaften=liegenschaft))
            .distinct().order_by('last_name', 'first_name', 'username'))


def empfaenger_auswahl(liegenschaft, organisation):
    """Was die Ausgabeseite zur Wahl stellt: Verträge der Liegenschaft,
    Dienstleister und Hauswarte."""
    from crm.models import Handwerker
    from rentals.models import Mietvertrag
    auswahl = {
        'vertraege': list(Mietvertrag.objects.filter(einheit__liegenschaft=liegenschaft,
                                                     status__in=('entwurf', 'aktiv', 'gekuendigt'))
                          .select_related('mieter', 'einheit').order_by('einheit__bezeichnung', '-beginn')),
        'handwerker': list(Handwerker.objects.order_by('firma')),
        'hauswarte': list(hauswarte(liegenschaft, organisation)),
    }
    # Der Wert der Auswahl (`sk_code`) — dieselbe Schreibweise wie `empfaenger_lesen`.
    for art, liste in (('vertrag', auswahl['vertraege']), ('handwerker', auswahl['handwerker']),
                       ('benutzer', auswahl['hauswarte'])):
        for obj in liste:
            obj.sk_code = f'{art}:{obj.pk}'
    return auswahl


def empfaenger_lesen(wert, liegenschaft, organisation):
    """Liest `vertrag:<id>`, `mieter:<id>`, `handwerker:<id>` oder
    `benutzer:<id>`. Fremde oder unpassende IDs ergeben None — die Auswahl
    wird nicht geglaubt, sondern gegen den eigenen Bestand nachgeschlagen."""
    from crm.models import Handwerker, Mieter
    from rentals.models import Mietvertrag
    art, _sep, nr = (wert or '').partition(':')
    if not nr.isdigit():
        return None
    nr = int(nr)
    leer = {'vertrag': None, 'mieter': None, 'handwerker': None, 'benutzer': None}
    if art == 'vertrag':
        v = (Mietvertrag.objects.filter(pk=nr, einheit__liegenschaft=liegenschaft)
             .select_related('mieter', 'einheit').first())
        if v is None:
            return None
        return {**leer, 'vertrag': v, 'mieter': v.mieter, 'name': v.mieter.display_name,
                'code': f'vertrag:{v.pk}', 'art': 'mieter'}
    if art == 'mieter':
        m = Mieter.objects.filter(pk=nr).first()
        if m is None:
            return None
        v = (Mietvertrag.objects.filter(mieter=m, einheit__liegenschaft=liegenschaft,
                                        status__in=('aktiv', 'gekuendigt')).order_by('-beginn').first())
        return {**leer, 'vertrag': v, 'mieter': m, 'name': m.display_name,
                'code': f'mieter:{m.pk}', 'art': 'mieter'}
    if art == 'handwerker':
        h = Handwerker.objects.filter(pk=nr).first()
        if h is None:
            return None
        return {**leer, 'handwerker': h, 'name': h.firma, 'code': f'handwerker:{h.pk}', 'art': 'handwerker'}
    if art == 'benutzer':
        u = hauswarte(liegenschaft, organisation).filter(pk=nr).first()
        if u is None:
            return None
        return {**leer, 'benutzer': u, 'name': u.get_full_name() or u.username,
                'code': f'benutzer:{u.pk}', 'art': 'hauswart'}
    return None


def ausgaben_von(empf, liegenschaft=None):
    """Die Ausgaben eines Empfängers (alle Status). Beim Vertrag zählen die
    Ausgaben aus der Zeit vor Modul 2 mit, die nur den Mieter tragen."""
    _S, SchluesselAusgabe = _modelle()
    if empf.get('vertrag') is not None:
        v = empf['vertrag']
        f = Q(vertrag=v) | Q(vertrag__isnull=True, mieter_id=v.mieter_id,
                             schluessel__liegenschaft_id=v.einheit.liegenschaft_id)
    elif empf.get('mieter') is not None:
        f = Q(mieter=empf['mieter'])
    elif empf.get('handwerker') is not None:
        f = Q(handwerker=empf['handwerker'])
    elif empf.get('benutzer') is not None:
        f = Q(benutzer=empf['benutzer'])
    else:
        return SchluesselAusgabe.objects.none()
    qs = SchluesselAusgabe.objects.filter(f)
    if liegenschaft is not None:
        qs = qs.filter(schluessel__liegenschaft=liegenschaft)
    return qs


# ---------------------------------------------------------------------------
# Register und Bestand
# ---------------------------------------------------------------------------

def _ausgaben_prefetch():
    _S, SchluesselAusgabe = _modelle()
    return Prefetch('ausgaben', queryset=SchluesselAusgabe.objects
                    .select_related('mieter', 'handwerker', 'benutzer', 'vertrag', 'quittung')
                    .order_by('-ausgegeben_am', '-id'))


def tueren_text(schluessel, tueren=None):
    if schluessel.art == 'haupt' and not (tueren if tueren is not None else list(schluessel.oeffnet.all())):
        return 'alle Türen'
    tueren = tueren if tueren is not None else list(schluessel.oeffnet.all())
    return ', '.join(t.bezeichnung for t in tueren)


def karten(schluessel_qs, heute=None):
    """Je Schlüssel eine Karte: Kürzel, Türen, offene Ausgaben, Bestand.

    Eine Abfrage für die Schlüssel, je eine für Türen und Ausgaben — keine
    je Karte (Skill bekannte-fallen, Nr. 10)."""
    heute = heute or timezone.localdate()
    liste = []
    for sch in (schluessel_qs.select_related('einheit', 'schliessanlage')
                .prefetch_related('oeffnet', _ausgaben_prefetch())
                .order_by('archiviert', 'art', 'typ', 'schluessel_nummer', 'id')):
        ausgaben = list(sch.ausgaben.all())
        offene = [a for a in ausgaben if a.status == 'ausgegeben']
        for a in offene:
            a.ueberfaellig = bool(a.rueckgabe_bis and a.rueckgabe_bis < heute)
            a.code = empfaenger_code(a)
        n_offen = sum(a.anzahl for a in offene)
        n_verloren = sum(a.anzahl for a in ausgaben if a.status == 'verloren')
        tueren = list(sch.oeffnet.all())
        liste.append({
            's': sch, 'kuerzel': kuerzel(sch), 'tueren': tueren,
            'alle_tueren': sch.art == 'haupt' and not tueren,
            'offene': offene, 'n_offen': n_offen, 'n_verloren': n_verloren,
            'verfuegbar': max(0, sch.anzahl - n_offen - n_verloren),
            'hat_ausgaben': bool(ausgaben),
        })
    return liste


def bestand(karten_liste):
    """Die Zahlen der Bestand-Kachel aus den Karten (ohne Archiv)."""
    aktiv = [k for k in karten_liste if not k['s'].archiviert]
    return {
        'total': sum(k['s'].anzahl for k in aktiv),
        'ausgegeben': sum(k['n_offen'] for k in aktiv),
        'verloren': sum(k['n_verloren'] for k in aktiv),
        'im_buero': sum(k['verfuegbar'] for k in aktiv),
        'schluessel': len(aktiv),
    }


def verfuegbar(schluessel):
    _S, SchluesselAusgabe = _modelle()
    belegt = sum(SchluesselAusgabe.objects.filter(schluessel=schluessel, status__in=('ausgegeben', 'verloren'))
                 .values_list('anzahl', flat=True))
    return max(0, schluessel.anzahl - belegt)


def oeffnet_tuer(karte, punkt):
    """Kommt dieser Schlüssel durch diese Tür? Ein Hauptschlüssel ohne
    eigene Zuordnung öffnet alle Türen seiner Anlage (ohne Anlage: alle der
    Liegenschaft)."""
    if karte['alle_tueren']:
        anlage_id = karte['s'].schliessanlage_id
        return anlage_id is None or punkt.anlage_id in (None, anlage_id)
    return any(t.pk == punkt.pk for t in karte['tueren'])


def faellige(heute=None, liegenschaft=None, nur_ueberfaellig=False):
    """Offene Ausgaben mit Rückgabefrist bis heute (bzw. vor heute)."""
    _S, SchluesselAusgabe = _modelle()
    heute = heute or timezone.localdate()
    qs = SchluesselAusgabe.objects.filter(status='ausgegeben', rueckgabe_bis__isnull=False)
    qs = qs.filter(rueckgabe_bis__lt=heute) if nur_ueberfaellig else qs.filter(rueckgabe_bis__lte=heute)
    if liegenschaft is not None:
        qs = qs.filter(schluessel__liegenschaft=liegenschaft)
    return qs.select_related('schluessel__liegenschaft', 'mieter', 'handwerker', 'benutzer', 'vertrag') \
             .order_by('rueckgabe_bis', 'id')


def ruecknahme_url(a):
    return f'/neu/liegenschaften/{a.schluessel.liegenschaft_id}/schluessel/ruecknahme/?an={empfaenger_code(a)}'


def offene_verluste(liegenschaft=None):
    from core.models import Pendenz
    qs = Pendenz.objects.filter(erledigt=False).filter(
        Q(quelle__startswith=VERLUST_QUELLE) | Q(quelle__startswith=VERLUST_INTERN_QUELLE))
    if liegenschaft is not None:
        qs = qs.filter(liegenschaft=liegenschaft)
    return qs.order_by('-erstellt_am')


# ---------------------------------------------------------------------------
# Akten (Person, Vertrag, Dienstleister)
# ---------------------------------------------------------------------------

def akte(ausgaben_qs):
    """Liste «Schlüssel» einer Akte: was die Person jetzt hat, und der Verlauf.

    Der Verlauf ist eine Zeitleiste aus zwei Ereignissen je Ausgabe —
    Ausgabe und, falls schon geschehen, Rücknahme oder Verlust — mit der
    Quittung bzw. dem Abnahmeprotokoll als Beleg."""
    ausgaben = list(ausgaben_qs.select_related('schluessel__liegenschaft', 'schluessel__einheit',
                                               'quittung', 'quittung_rueckgabe', 'abnahme')
                    .order_by('-ausgegeben_am', '-id'))
    offen = []
    verlauf = []
    for a in ausgaben:
        a.kuerzel = kuerzel(a.schluessel)
        a.code = empfaenger_code(a)
        if a.status == 'ausgegeben':
            a.ueberfaellig = bool(a.rueckgabe_bis and a.rueckgabe_bis < timezone.localdate())
            a.ruecknahme_url = ruecknahme_url(a)
            offen.append(a)
        # Beleg der Ausgabe: die Quittung, bei einer Buchung aus der Abnahme das Protokoll.
        verlauf.append({'datum': a.ausgegeben_am, 'art': 'ausgabe', 'a': a,
                        'beleg': a.quittung, 'abnahme': a.abnahme})
        if a.status != 'ausgegeben' and a.rueckgabe_am:
            verlauf.append({'datum': a.rueckgabe_am, 'art': a.status, 'a': a,
                            'beleg': a.quittung_rueckgabe, 'abnahme': None})
    verlauf.sort(key=lambda e: (e['datum'] or date.min, e['a'].pk), reverse=True)
    return {'offen': offen, 'verlauf': verlauf, 'stueck': sum(a.anzahl for a in offen),
            'ueberfaellig': sum(1 for a in offen if a.ueberfaellig)}


# ---------------------------------------------------------------------------
# Ausgabe und Rücknahme mit Quittung
# ---------------------------------------------------------------------------

def unterschrift_lesen(data_url):
    """Die Unterschrift aus dem Zeichenfeld — dieselbe Prüfung wie bei der
    Abnahme (`abnahme_schluessel.unterschrift_pruefen`), dazu: Ein leeres
    Feld ist keine Unterschrift. None bei allem, was nicht taugt."""
    import io

    from core.services.abnahme_schluessel import unterschrift_pruefen
    from core.services.unterschrift import hat_sichtbare_tinte
    roh = unterschrift_pruefen(data_url)
    if roh is None:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(roh)) as bild:
            if not hat_sichtbare_tinte(bild):
                return None
    except Exception:
        log.exception('Schlüssel: Unterschrift nicht prüfbar')
        return None
    return roh


def _zeile(a_oder_sch, anzahl, status=''):
    sch = getattr(a_oder_sch, 'schluessel', a_oder_sch)
    return {'anzahl': anzahl, 'art': sch.art, 'typ': sch.typ, 'nummer': sch.schluessel_nummer,
            'tueren': tueren_text(sch), 'status': status}


def _ablegen(pdf, titel, empf, liegenschaft, schluessel_liste):
    """Quittung in die Ablage: am Vertrag, sonst am Objekt, sonst an der
    Liegenschaft. `ablegen` schluckt Fehler und liefert dann None — das wird
    hier protokolliert, statt still zu verschwinden."""
    from core.services.ablage import ablegen
    einheiten = {s.einheit_id for s in schluessel_liste}
    einheit = None
    if len(einheiten) == 1 and None not in einheiten:
        einheit = schluessel_liste[0].einheit
    dok = ablegen(pdf, titel, 'protokoll', vertrag=empf.get('vertrag'), mieter=empf.get('mieter'),
                  einheit=None if empf.get('vertrag') else einheit, liegenschaft=liegenschaft,
                  dateiname=titel)
    if dok is None:
        log.error('Schlüsselquittung nicht abgelegt: %s (Liegenschaft %s)', titel, liegenschaft.pk)
    return dok


def ausgabe_pruefen(liegenschaft, posten, empf, rueckgabe_bis, unterschrift, heute=None):
    """Fehlermeldungen der Ausgabe, leer heisst: geht. `posten`: [(Schlüssel, Stück)]."""
    heute = heute or timezone.localdate()
    fehler = []
    if empf is None:
        fehler.append(gettext('Bitte den Empfänger wählen.'))
    if not posten:
        fehler.append(gettext('Bitte mindestens einen Schlüssel wählen.'))
    for sch, n in posten:
        if sch.liegenschaft_id != liegenschaft.pk or sch.archiviert:
            fehler.append(gettext('Schlüssel %(nr)s gehört nicht zu dieser Liegenschaft.') % {'nr': sch.schluessel_nummer})
            continue
        frei = verfuegbar(sch)
        if n < 1 or n > frei:
            fehler.append(gettext('Von Schlüssel %(nr)s sind %(frei)s Stück im Büro.')
                          % {'nr': sch.schluessel_nummer, 'frei': frei})
    if rueckgabe_bis is not None and rueckgabe_bis < heute:
        fehler.append(gettext('«Zurück bis» liegt in der Vergangenheit.'))
    if unterschrift is None:
        fehler.append(gettext('Die Unterschrift des Empfängers fehlt oder ist nicht lesbar.'))
    return fehler


def ausgeben(liegenschaft, posten, empf, *, rueckgabe_bis=None, unterschrift=None,
             unterschrift_name='', notiz='', datum=None, user=None):
    """Bucht die Ausgabe, legt die Quittung ab und gibt (Ausgaben, Dokument) zurück.

    Alle Ausgaben eines Vorgangs teilen Unterschrift und Quittung: Die Datei
    der Unterschrift wird einmal gespeichert und von allen referenziert."""
    from core.services.schluessel_quittung import quittung_pdf
    _S, SchluesselAusgabe = _modelle()
    datum = datum or timezone.localdate()
    notiz = (notiz or '').strip()[:500]
    with transaction.atomic():
        neu = []
        for sch, n in posten:
            neu.append(SchluesselAusgabe.objects.create(
                schluessel=sch, vertrag=empf.get('vertrag'), mieter=empf.get('mieter'),
                handwerker=empf.get('handwerker'), benutzer=empf.get('benutzer'), anzahl=n,
                ausgegeben_am=datum, rueckgabe_bis=rueckgabe_bis, status='ausgegeben', notiz=notiz))
        if unterschrift and neu:
            neu[0].unterschrift.save('unterschrift_schluessel.png', ContentFile(unterschrift), save=True)
            SchluesselAusgabe.objects.filter(pk__in=[a.pk for a in neu[1:]]) \
                .update(unterschrift=neu[0].unterschrift.name)
    pdf = quittung_pdf(art='ausgabe', liegenschaft=liegenschaft, empfaenger=empf['name'], datum=datum,
                       zeilen=[_zeile(sch, n) for sch, n in posten], rueckgabe_bis=rueckgabe_bis,
                       unterschrift_png=unterschrift, unterschrift_name=unterschrift_name, notiz=notiz)
    titel = f"Schlüsselquittung Ausgabe {datum:%d.%m.%Y} – {empf['name']}"[:200]
    dok = _ablegen(pdf, titel, empf, liegenschaft, [sch for sch, _n in posten])
    if dok is not None:
        SchluesselAusgabe.objects.filter(pk__in=[a.pk for a in neu]).update(quittung=dok)
        for a in neu:
            a.quittung = dok
    return neu, dok


def _abspalten(a, anzahl, **felder):
    """Ein Teil einer Ausgabe als eigene Zeile (gleiche Herkunft, eigener Stand)."""
    _S, SchluesselAusgabe = _modelle()
    kopie = SchluesselAusgabe(
        schluessel=a.schluessel, mieter=a.mieter, handwerker=a.handwerker, benutzer=a.benutzer,
        vertrag=a.vertrag, ausgegeben_am=a.ausgegeben_am, rueckgabe_bis=a.rueckgabe_bis,
        quittung=a.quittung, abnahme=a.abnahme, notiz=a.notiz, anzahl=anzahl, status=a.status)
    if a.unterschrift:
        kopie.unterschrift = a.unterschrift.name
    for k, v in felder.items():
        setattr(kopie, k, v)
    kopie.save()
    return kopie


def _verbuchen(a, zurueck, verloren, datum, **felder):
    """Setzt `zurueck` Stück auf «zurück» und `verloren` Stück auf «verloren»;
    was übrig bleibt, bleibt ausgegeben. Gibt die verlorenen Zeilen zurück."""
    rest = a.anzahl - zurueck - verloren
    if rest < 0 or (zurueck == 0 and verloren == 0):
        return []
    if rest:
        _abspalten(a, rest)
    verluste = []
    if zurueck and verloren:
        verluste.append(_abspalten(a, verloren, status='verloren', rueckgabe_am=datum, **felder))
        a.anzahl, a.status = zurueck, 'zurueck'
    elif verloren:
        a.anzahl, a.status = verloren, 'verloren'
        verluste.append(a)
    else:
        a.anzahl, a.status = zurueck, 'zurueck'
    a.rueckgabe_am = datum
    for k, v in felder.items():
        setattr(a, k, v)
    a.save()
    return verluste


def ruecknahme_pruefen(posten, unterschrift):
    """`posten`: [(Ausgabe, zurück, verloren)]."""
    fehler = []
    if not posten:
        fehler.append(gettext('Bitte mindestens einen Schlüssel als zurück oder verloren markieren.'))
    for a, z, v in posten:
        if a.status != 'ausgegeben' or z < 0 or v < 0 or z + v > a.anzahl or z + v == 0:
            fehler.append(gettext('Die Stückzahl bei Schlüssel %(nr)s stimmt nicht.')
                          % {'nr': a.schluessel.schluessel_nummer})
    if unterschrift is None:
        fehler.append(gettext('Die Unterschrift fehlt oder ist nicht lesbar.'))
    return fehler


def zuruecknehmen(liegenschaft, posten, empf, *, unterschrift=None, unterschrift_name='', notiz='',
                  datum=None, user=None):
    """Bucht Rücknahme und Verlust, legt die Quittung ab, erzeugt je Verlust
    die Pendenz. Gibt (Verluste, Dokument) zurück."""
    from core.services.schluessel_quittung import quittung_pdf
    datum = datum or timezone.localdate()
    notiz = (notiz or '').strip()[:500]
    zeilen = []
    for a, z, v in posten:
        if z:
            zeilen.append(_zeile(a, z, 'zurueck'))
        if v:
            zeilen.append(_zeile(a, v, 'verloren'))
    pdf = quittung_pdf(art='ruecknahme', liegenschaft=liegenschaft, empfaenger=empf['name'], datum=datum,
                       zeilen=zeilen, unterschrift_png=unterschrift, unterschrift_name=unterschrift_name,
                       notiz=notiz)
    titel = f"Schlüsselquittung Rücknahme {datum:%d.%m.%Y} – {empf['name']}"[:200]
    dok = _ablegen(pdf, titel, empf, liegenschaft, [a.schluessel for a, _z, _v in posten])
    verluste = []
    with transaction.atomic():
        bild_name = ''
        if unterschrift and posten:
            erste = posten[0][0]
            erste.unterschrift_rueckgabe.save('unterschrift_ruecknahme.png', ContentFile(unterschrift), save=False)
            bild_name = erste.unterschrift_rueckgabe.name
        for a, z, v in posten:
            felder = {'quittung_rueckgabe': dok}
            if bild_name:
                felder['unterschrift_rueckgabe'] = bild_name
            if notiz:
                felder['notiz'] = (f'{a.notiz}\n' if a.notiz else '') + notiz
            verluste += _verbuchen(a, z, v, datum, **felder)
        for a in verluste:
            verlust_pendenz(a, user=user)
    return verluste, dok


def verlust_pendenz(a, user=None):
    """Die Pendenz «Zylinder ersetzen» zu einem Verlust — einmal je Ausgabe."""
    from core.models import Pendenz
    sch = a.schluessel
    intern = not (a.mieter_id or a.handwerker_id or a.vertrag_id)
    quelle = f'{VERLUST_INTERN_QUELLE if intern else VERLUST_QUELLE}{a.pk}'
    tueren = tueren_text(sch) or 'keine Türen zugeordnet'
    wer = a.empfaenger_name or 'unbekannt'
    datum = a.rueckgabe_am or timezone.localdate()
    beschreibung = (f"{a.anzahl} × {sch.typ} Nr. {sch.schluessel_nummer} verloren am {datum:%d.%m.%Y} "
                    f"({wer}). Türen: {tueren}. Die Kosten werden nicht automatisch weiterverrechnet; "
                    f"eine Debitorenrechnung erfasst bei Bedarf eine Person.")
    p, _neu = Pendenz.objects.get_or_create(quelle=quelle, defaults=dict(
        titel=f'{VERLUST_TITEL}: {sch.typ} Nr. {sch.schluessel_nummer}'[:200], kategorie='unterhalt',
        liegenschaft=sch.liegenschaft, vertrag=a.vertrag, beschreibung=beschreibung, erstellt_von=user))
    return p


# ---------------------------------------------------------------------------
# Abnahme
# ---------------------------------------------------------------------------

def register_fuer_abnahme(prot):
    """Die Schlüssel, die für dieses Protokoll in Frage kommen: die der
    Einheit, dann die allgemeinen der Liegenschaft. Ohne Archiv; ohne
    Hauptschlüssel, die gehen nicht an Mieter."""
    Schluessel, _A = _modelle()
    einheit = prot.vertrag.einheit
    basis = Schluessel.objects.filter(archiviert=False).exclude(art='haupt')
    return (list(basis.filter(einheit=einheit).order_by('id'))
            + list(basis.filter(liegenschaft=einheit.liegenschaft, einheit__isnull=True).order_by('id')))


def _passt(zeile, sch):
    return _norm(zeile.bezeichnung) == _norm(sch.typ) and _norm(zeile.anlage) == _norm(sch.schluessel_nummer)


def _treffer(zeile, kandidaten):
    for sch in kandidaten:
        if _passt(zeile, sch):
            return sch
    # Die Bezeichnung wurde im Protokoll geändert, die Nummer nicht: eindeutige Nummer genügt.
    if _norm(zeile.anlage):
        gleich = [s for s in kandidaten if _norm(s.schluessel_nummer) == _norm(zeile.anlage)]
        if len(gleich) == 1:
            return gleich[0]
    return None


def offene_des_vertrags(vertrag):
    """Offene Ausgaben eines Vertrags (mit den Altausgaben nur am Mieter)."""
    return ausgaben_von({'vertrag': vertrag}).filter(status='ausgegeben') \
        .select_related('schluessel').order_by('schluessel__einheit_id', 'schluessel_id', 'id')


def soll_aus_ausgaben(prot):
    """Zeilen des Schlüsselverzeichnisses beim Auszug aus den offenen
    Ausgaben des Vertrags: [(bezeichnung, anlage, soll)]. Leer, wenn es keine
    gibt — dann gilt das Register wie bisher."""
    je = OrderedDict()
    for a in offene_des_vertrags(prot.vertrag):
        sch = a.schluessel
        eintrag = je.setdefault(sch.pk, [sch.typ, sch.schluessel_nummer, 0])
        eintrag[2] += a.anzahl
    return [tuple(z) for z in je.values()]


def abnahme_buchen(prot, user=None):
    """Bucht die Schlüssel eines abgeschlossenen Protokolls. Gibt die
    Bezeichnungen der Zeilen zurück, die sich keinem Schlüssel zuordnen
    liessen. Ein zweiter Aufruf bucht nichts doppelt."""
    if not prot.abgeschlossen:
        return []
    with transaction.atomic():
        if prot.typ == 'einzug':
            return _einzug_buchen(prot)
        return _auszug_buchen(prot, user)


def _einzug_buchen(prot):
    _S, SchluesselAusgabe = _modelle()
    if SchluesselAusgabe.objects.filter(abnahme=prot).exists():
        return []
    v = prot.vertrag
    register = register_fuer_abnahme(prot)
    ohne = []
    for z in prot.schluessel.all():
        if not z.ist:
            continue                    # nicht gezählt oder keiner übergeben
        sch = _treffer(z, register)
        if sch is None:
            ohne.append(z.bezeichnung)
            continue
        SchluesselAusgabe.objects.create(
            schluessel=sch, vertrag=v, mieter=v.mieter, anzahl=z.ist, ausgegeben_am=prot.datum,
            status='ausgegeben', abnahme=prot,
            notiz=f'Ausgabe mit der Einzugsabnahme vom {prot.datum:%d.%m.%Y}')
    return ohne


def _auszug_buchen(prot, user):
    _S, SchluesselAusgabe = _modelle()
    v = prot.vertrag
    offen = list(offene_des_vertrags(v))
    zeilen = list(prot.schluessel.all())
    notiz = f'Rücknahme mit der Auszugsabnahme vom {prot.datum:%d.%m.%Y}'
    ohne = []
    if not offen:
        # Rückfall wie beim Soll: Gab es für diesen Vertrag nie eine Ausgabe,
        # kam das Soll aus dem Register. Was fehlt, wird als Verlust geführt.
        # Gab es Ausgaben, sind sie alle schon zurück — dann ist nichts zu tun.
        if ausgaben_von({'vertrag': v}).exists():
            return []
        register = register_fuer_abnahme(prot)
        for z in zeilen:
            if not z.fehlend:
                continue
            sch = _treffer(z, register)
            if sch is None:
                ohne.append(z.bezeichnung)
                continue
            a = SchluesselAusgabe.objects.create(
                schluessel=sch, vertrag=v, mieter=v.mieter, anzahl=z.fehlend,
                ausgegeben_am=v.beginn or prot.datum, rueckgabe_am=prot.datum, status='verloren',
                abnahme=prot, notiz=f'Beim Auszug fehlend (Abnahme vom {prot.datum:%d.%m.%Y}); '
                                    f'Soll aus dem Register')
            verlust_pendenz(a, user=user)
        return ohne
    for z in zeilen:
        if z.ist is None:
            continue                    # nicht gezählt: bleibt ausgegeben
        kandidaten = [a for a in offen if _passt(z, a.schluessel)]
        if not kandidaten:
            sch = _treffer(z, [a.schluessel for a in offen])
            kandidaten = [a for a in offen if sch is not None and a.schluessel_id == sch.pk]
        if not kandidaten:
            ohne.append(z.bezeichnung)
            continue
        offen = [a for a in offen if a not in kandidaten]
        total = sum(a.anzahl for a in kandidaten)
        rest_verloren = min(total, z.fehlend or 0)
        for a in kandidaten:
            verloren = min(a.anzahl, rest_verloren)
            rest_verloren -= verloren
            felder = {'notiz': (f'{a.notiz}\n' if a.notiz else '') + notiz}
            for verlust in _verbuchen(a, a.anzahl - verloren, verloren, prot.datum, **felder):
                verlust_pendenz(verlust, user=user)
    return ohne
