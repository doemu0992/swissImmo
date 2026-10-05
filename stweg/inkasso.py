"""STWEG-Inkasso: Mahnstufen, Retentionsrecht (Art. 712k ZGB), Gemeinschaftspfandrecht (Art. 712i ZGB).

WARUM NICHT DAS MIETRECHT
  Ein Stockwerkeigentümer ist Eigentümer, nicht Mieter. Eine Kündigungsandrohung nach Art. 257d OR gibt es gegen ihn
  nicht — weder in der Mahnung noch als Pendenz. Jeder Text, der an einen Eigentümer geht, läuft durch
  `ohne_kuendigung`; das Wort «Kündigung» oder «257d» im Text bricht den Versand ab (fail closed). Die Mahnungen des
  Mietmodells (`core.services.mahnstufen`) gelten für Mieter und werden hier nicht berührt.

ABLAUF
  Mahnung 1 → 2 → 3 (`mahnung_erstellen`, `mahnung_versenden`) → Retentionsrecht geltend machen → Gemeinschaftspfandrecht
  anmelden. Die Stufen sind eine Richtlinie der Verwaltung, keine gesetzliche Voraussetzung; wer ohne sie anmelden will,
  sagt das ausdrücklich (`ohne_mahnungen=True`).

FORDERUNGEN (`forderungen`)
  Aus den Fachtabellen, nicht aus dem Hauptbuch: Akonto-Raten (Vorschreibungen) und die Kostenanteile abgeschlossener
  Jahresabrechnungen — für ein Jahr mit Abrechnung zählt nur diese, nicht mehr die Raten — sowie Einlagen in den
  Erneuerungsfonds.

  TILGUNG. Hat der Eigentümer eine Rate angegeben (`StwegAkonto.vorschreibung`, Bestimmung des Schuldners nach
  Art. 86 OR), tilgt die Zahlung diese Rate (bei einem Jahr mit Abrechnung: dessen Abrechnung). Ohne Angabe — und für den
  Überschuss — wird die ÄLTESTE offene Forderung getilgt. Das ist eine Annahme, keine geprüfte Rechtsauslegung: Nach
  Art. 87 OR gelten ohne Bestimmung andere Kriterien, und die Wirkung auf die Pfandsumme ist gegensätzlich — wer die
  ältesten tilgt, lässt die jüngeren (pfandberechtigten) offen und erhöht die Pfandsumme. Deshalb: Zahlungen mit der
  bezahlten Rate erfassen, und die Tilgungsreihenfolge vor der Anmeldung rechtlich bestätigen.

DIE DREI JAHRE (Art. 712i ZGB, wie im Auftrag vorgegeben)
  Pfandberechtigt sind nur offene Beitragsforderungen der letzten 36 Monate vor dem Stichtag. Massgebend ist das
  Forderungsdatum: das Fälligkeitsdatum der Rate, bei einer Jahresabrechnung der 31.12. des Abrechnungsjahres (das
  ist das frühere und damit vorsichtigere Datum). Eine Forderung, die genau 36 Monate zurückliegt, zählt NICHT
  (strikt neuer als der Stichtag minus 36 Monate). Ältere Forderungen bleiben geschuldet, werden aber getrennt
  ausgewiesen und gehen nicht in die Pfandsumme ein. Verzugszinsen: nur wenn die Gemeinschaft den Satz eingetragen hat
  (`verzugszins`), nie in der Pfandsumme. Nicht abgebildet: Mahnkosten, Anteil eines
  Jahres, der in das Fenster ragt (die Forderung gilt ganz oder gar nicht). Ob die Auslegung «Forderungsdatum» der
  Rechtsprechung entspricht, ist nicht geprüft — vor der Anmeldung juristisch bestätigen.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from core.models import Pendenz
from finance.models import ErneuerungsfondsBewegung
from stweg.budget import _plus_monate
from stweg.eigentuemer import eigentuemer_am
from stweg.zins import KAPITAL_ARTEN, oldest_first, zinsforderungen
from stweg.zins import satz as zins_satz
from stweg.models import (StwegAbrechnung, StwegAbrechnungPosition, StwegAkonto, StwegInkassoFall,
                          StwegInkassoPosition, StwegMahnung, StwegPfandrecht, StwegVorschreibung)

NULL = Decimal('0.00')
PFANDRECHT_MONATE = 36
MAX_STUFE = 3
MAHNFRIST_TAGE = 10            # Vorgabe der Verwaltung, keine gesetzliche Frist
VERBOTEN = ('kündig', 'kuendig', '257d')


class InkassoFehler(ValueError):
    pass


def _chf(betrag):
    return f'{betrag:,.2f}'.replace(',', "'")


def ohne_kuendigung(text):
    """Wirft, wenn der Text eine Kündigung oder Art. 257d OR erwähnt — beides gehört nicht an einen Eigentümer."""
    t = (text or '').lower()
    for w in VERBOTEN:
        if w in t:
            raise InkassoFehler(f'Ein Text an einen Stockwerkeigentümer darf keine Kündigung androhen '
                                f'(Art. 257d OR gilt nur für Mieter): «{w}».')
    return text


# ── Forderungen ──────────────────────────────────────────────────────────

def _tilgen(claims, zahlungen):
    """Rechnet Kapitalzahlungen an. `zahlungen`: [(datum, betrag, ziel)]; `ziel` ist der Schlüssel der Forderung, für
    die der Schuldner bezahlt hat (Bestimmung des Schuldners, Art. 86 OR), oder None. Erst werden die bestimmten
    Zahlungen ihrer Forderung zugerechnet (ein Überschuss fällt in den allgemeinen Topf), dann der Topf der ÄLTESTEN
    offenen Forderung zuerst. Gibt die Forderungen mit `bezahlt`, `offen` und `anrechnungen` ([(Datum, Betrag)], für
    den Verzugszins), nach Datum sortiert."""
    claims = [{**c, 'bezahlt': NULL, 'anrechnungen': []} for c in sorted(claims, key=lambda c: (c['datum'], c['text']))]
    nach_schluessel = {c['schluessel']: c for c in claims if c.get('schluessel') is not None}
    pool = []
    for datum, betrag, ziel in sorted(zahlungen, key=lambda z: z[0]):
        c = nach_schluessel.get(ziel) if ziel is not None else None
        if c is None:
            pool.append((datum, betrag))
            continue
        frei = c['betrag'] - c['bezahlt']
        anrechnen = min(betrag, frei) if frei > 0 else NULL
        if anrechnen:
            c['bezahlt'] += anrechnen
            c['anrechnungen'].append((datum, anrechnen))
        if betrag - anrechnen:
            pool.append((datum, betrag - anrechnen))
    for datum, betrag in pool:                              # in zeitlicher Reihenfolge: die älteste Forderung zuerst
        for c in claims:
            if betrag <= 0:
                break
            anrechnen = min(betrag, c['betrag'] - c['bezahlt']) if c['betrag'] > c['bezahlt'] else NULL
            if anrechnen:
                c['bezahlt'] += anrechnen
                c['anrechnungen'].append((datum, anrechnen))
                betrag -= anrechnen
    for c in claims:
        c['offen'] = c['betrag'] - c['bezahlt']
    return claims


def _kosten_forderungen(einheit, stichtag):
    """Mahnspesen und Betreibungskosten als Forderungen (ohne Zahlung angerechnet); stornierte nicht."""
    return [{'datum': p.datum, 'text': p.text, 'betrag': p.betrag, 'art': p.art, 'schluessel': None,
             'schuldner': eigentuemer_am(einheit, p.datum)}
            for p in StwegInkassoPosition.objects.filter(einheit=einheit, datum__lte=stichtag,
                                                         storniert_am__isnull=True)]


def forderungen(einheit, stichtag=None):
    """Alle Forderungen der Einheit bis zum Stichtag mit bezahltem und offenem Betrag, älteste zuerst: die
    Kapitalforderungen (Raten, Abrechnungen, Fondseinlagen), dazu — wenn die Gemeinschaft einen bestätigten Satz hat —
    die Zinsschuld (`art` «zins») und die Kosten (`art` «mahnspesen», «betreibungskosten»). Siehe `stweg.zins`."""
    stichtag = stichtag or timezone.localdate()
    abr = {p.abrechnung.jahr: p for p in StwegAbrechnungPosition.objects
           .filter(einheit=einheit, abrechnung__status=StwegAbrechnung.STATUS_ABGESCHLOSSEN)
           .select_related('abrechnung')}
    akonto = []
    for jahr, p in abr.items():
        akonto.append({'datum': date(jahr, 12, 31), 'text': f'Abrechnung {jahr}', 'betrag': p.kostenanteil,
                       'art': 'abrechnung', 'schluessel': ('j', jahr),
                       'schuldner': p.eigentuemer_id or eigentuemer_am(einheit, date(jahr, 12, 31))})
    for v in StwegVorschreibung.objects.filter(einheit=einheit).select_related('budget'):
        if v.budget.jahr in abr:
            continue                               # für dieses Jahr gilt die Abrechnung
        akonto.append({'datum': v.faellig_am, 'text': f'Akonto {v.budget.jahr}, Rate {v.rate_nr}/{v.rate_total}',
                       'betrag': v.betrag, 'art': 'akonto', 'schluessel': ('v', v.pk),
                       'schuldner': eigentuemer_am(einheit, v.faellig_am)})
    akonto = [c for c in akonto if c['datum'] <= stichtag]
    vorschr_jahr = {v.pk: v.budget.jahr for v in StwegVorschreibung.objects.filter(einheit=einheit)
                    .select_related('budget')}
    zahlungen = list(StwegAkonto.objects.filter(einheit=einheit, datum__lte=stichtag).order_by('datum', 'id'))
    zahl, zahl_f = [], []
    for z in zahlungen:
        if z.zweck == StwegAkonto.AKONTO:
            ziel = None
            if z.vorschreibung_id is not None:
                # Für ein Jahr mit Abrechnung gibt es die Raten nicht mehr: die Zahlung tilgt die Abrechnung dieses Jahres.
                ziel = ('j', vorschr_jahr[z.vorschreibung_id]) if vorschr_jahr.get(z.vorschreibung_id) in abr \
                    else ('v', z.vorschreibung_id)
            zahl.append((z.datum, z.kapital, ziel))
        else:
            zahl_f.append((z.datum, z.kapital, None))
    fonds = [{'datum': b.datum, 'text': f'Einlage Erneuerungsfonds {b.jahr}', 'betrag': b.betrag, 'art': 'fonds',
              'schuldner': eigentuemer_am(einheit, b.datum)}
             for b in ErneuerungsfondsBewegung.objects.filter(einheit=einheit, art='einlage', datum__lte=stichtag)]
    kapital = _tilgen(akonto, zahl) + _tilgen(fonds, zahl_f)
    alle = list(kapital)
    prozent = zins_satz(einheit.liegenschaft)
    if prozent is not None:
        zins = zinsforderungen(kapital, stichtag, prozent)
        alle += oldest_first(zins, sum((z.an_zins for z in zahlungen), NULL))
    kosten = _kosten_forderungen(einheit, stichtag)
    alle += oldest_first(kosten, sum((z.an_kosten for z in zahlungen), NULL))
    return sorted(alle, key=lambda c: (c['datum'], c['text']))


def offener_betrag(einheit, stichtag=None):
    return sum((c['offen'] for c in forderungen(einheit, stichtag)), NULL)


def _gegen_aktuellen(einheit, c):
    """Schuldet der heutige Eigentümer diese Forderung persönlich? (Unbekannter Schuldner: ja.)"""
    return c.get('schuldner') in (None, einheit.stockwerkeigentuemer_id)


def offener_betrag_eigentuemer(einheit, stichtag=None):
    """Der Teil, den der heutige Eigentümer persönlich schuldet (ohne Forderungen gegen frühere Eigentümer)."""
    return sum((c['offen'] for c in forderungen(einheit, stichtag) if _gegen_aktuellen(einheit, c)), NULL)



def pfandberechtigt(einheit, stichtag=None, monate=PFANDRECHT_MONATE):
    """Teilt die offenen Forderungen in pfandberechtigt (jünger als `monate` vor dem Stichtag) und ausgeschlossen."""
    stichtag = stichtag or timezone.localdate()
    grenze = _plus_monate(stichtag, -monate)
    alle = [c for c in forderungen(einheit, stichtag) if c['offen'] > 0]
    offen = [c for c in alle if c['art'] in KAPITAL_ARTEN]           # Zinsen und Kosten sind nicht in der Pfandsumme
    drin = [{**c, 'pfandberechtigt': True} for c in offen if c['datum'] > grenze]
    draussen = [{**c, 'pfandberechtigt': False} for c in offen if c['datum'] <= grenze]
    return {
        'stichtag': stichtag, 'grenze': grenze,
        'gesamt': sum((c['offen'] for c in offen), NULL),
        'pfandberechtigt': sum((c['offen'] for c in drin), NULL),
        'ausgeschlossen': sum((c['offen'] for c in draussen), NULL),
        'zinsen_kosten': sum((c['offen'] for c in alle if c['art'] not in KAPITAL_ARTEN), NULL),
        'zeilen': drin + draussen,
    }


# ── Fall und Mahnstufen ──────────────────────────────────────────────────

def offener_fall(einheit):
    return StwegInkassoFall.objects.filter(einheit=einheit, status=StwegInkassoFall.OFFEN).first()


def fall_pruefen(einheit, heute=None):
    """Schliesst den offenen Fall, sobald nichts mehr offen ist."""
    heute = heute or timezone.localdate()
    fall = offener_fall(einheit)
    if fall is not None and offener_betrag(einheit, heute) <= 0:
        fall.status, fall.erledigt_am = StwegInkassoFall.ERLEDIGT, heute
        fall.save(update_fields=['status', 'erledigt_am'])
        Pendenz.objects.filter(liegenschaft=einheit.liegenschaft, quelle__startswith=f'stweg:inkasso:{fall.pk}:',
                               erledigt=False).update(erledigt=True, erledigt_am=heute)
    return fall


def mahnstufe(fall):
    return fall.mahnungen.count() if fall else 0


@transaction.atomic
def mahnung_erstellen(einheit, *, heute=None, frist_tage=MAHNFRIST_TAGE, user=None):
    """Legt die nächste Mahnung an (Fall wird bei Bedarf eröffnet). Betrag = alles Fällige, das offen ist."""
    heute = heute or timezone.localdate()
    if not einheit.liegenschaft.ist_stweg:
        raise InkassoFehler(gettext('«%(liegenschaft)s» ist keine STWEG-Liegenschaft.')
                            % {'liegenschaft': einheit.liegenschaft})
    betrag = offener_betrag_eigentuemer(einheit, heute)
    if betrag <= 0:
        if offener_betrag(einheit, heute) > 0:
            raise InkassoFehler(gettext('Offen sind nur Forderungen gegen einen früheren Eigentümer. Eine Mahnung an '
                                        'den heutigen Eigentümer ist nicht möglich; das Gemeinschaftspfandrecht '
                                        'haftet am Anteil.'))
        raise InkassoFehler('Es ist nichts fällig und offen — keine Mahnung.')
    fall = offener_fall(einheit) or StwegInkassoFall.objects.create(
        einheit=einheit, eigentuemer=einheit.stockwerkeigentuemer, eroeffnet_am=heute)
    stufe = mahnstufe(fall) + 1
    if stufe > MAX_STUFE:
        raise InkassoFehler('Die dritte Mahnung ist bereits erfasst. Weiter mit Retentionsrecht und Pfandrecht.')
    letzte = fall.mahnungen.order_by('-stufe').first()
    if letzte is not None and letzte.versendet_am is None:
        raise InkassoFehler(f'Die {letzte.stufe}. Mahnung ist noch nicht versendet.')
    if frist_tage < 1:
        raise InkassoFehler('Die Zahlungsfrist muss mindestens einen Tag betragen.')
    m = StwegMahnung.objects.create(fall=fall, stufe=stufe, datum=heute, betrag=betrag,
                                    frist_bis=heute + timedelta(days=frist_tage))
    gebuehr = mahngebuehr(einheit.liegenschaft, stufe)
    if gebuehr is not None:                                  # echte Sollstellung: gebucht und Teil der Gesamtschuld
        _position_buchen(einheit, StwegInkassoPosition.MAHNSPESEN, gebuehr, heute, f'Mahngebühr {stufe}. Mahnung',
                         soll_haben=('1110', '3110'), fall=fall, mahnung=m, user=user)
        m.betrag = offener_betrag_eigentuemer(einheit, heute)
        m.save(update_fields=['betrag'])
    return m


def mahngebuehr(liegenschaft, stufe):
    """Die Mahngebühr für diese Mahnstufe — oder None. Nur aus bestätigten Vorgaben; sonst keine Gebühr."""
    from stweg.vorgaben import vorgaben_von
    v = vorgaben_von(liegenschaft)
    if v is None or v.mahngebuehr_chf is None or not v.bestaetigt_am or Decimal(v.mahngebuehr_chf) <= 0:
        return None
    return Decimal(v.mahngebuehr_chf) if stufe >= (v.mahngebuehr_ab_stufe or 2) else None


def _position_buchen(einheit, art, betrag, datum, text, *, soll_haben, fall=None, mahnung=None, amt='', user=None):
    from finance.booking import buche
    try:
        b = buche(soll_haben[0], soll_haben[1], betrag, f'{text}: {einheit.bezeichnung}', datum=datum,
                  liegenschaft=einheit.liegenschaft, user=user)
    except PermissionError as fehler:
        raise InkassoFehler(gettext('Die Buchung ist nicht möglich — Periode abgeschlossen? (%(fehler)s)')
                            % {'fehler': fehler})
    return StwegInkassoPosition.objects.create(einheit=einheit, fall=fall, mahnung=mahnung, art=art, datum=datum,
                                               betrag=betrag, text=text, amt=amt, buchung=b, erfasst_von=user)


@transaction.atomic
def position_stornieren(position, *, user=None, heute=None):
    """Nimmt eine Nebenforderung zurück (Gegenbuchung); sie ist danach nicht mehr Teil der Gesamtschuld. Eine bereits
    angerechnete Zahlung bleibt, wie sie war — der Betrag wird dann zum Kapital-Überschuss der nächsten Forderung."""
    from finance.booking import storniere_buchung
    if position.storniert_am is not None:
        raise InkassoFehler(gettext('Diese Position ist schon storniert.'))
    try:
        if position.buchung_id and position.buchung.storniert_am is None:
            storniere_buchung(position.buchung, user=user)
    except PermissionError as fehler:
        raise InkassoFehler(gettext('Die Buchung ist nicht möglich — Periode abgeschlossen? (%(fehler)s)')
                            % {'fehler': fehler})
    position.storniert_am = heute or timezone.localdate()
    position.save(update_fields=['storniert_am'])
    return position


@transaction.atomic
def kostenvorschuss_erfassen(fall, betrag, datum=None, *, amt='', user=None):
    """Erfasst den Vorschuss an das Betreibungsamt (SchKG), den die Verwaltung für die Betreibung bezahlt hat. Er wird
    der Gesamtschuld des Eigentümers zugeschlagen (Sollstellung Soll 1110 / Haben 1020) und ist Teil der Anrechnung
    nach Art. 85 OR; in der Pfandsumme steht er nicht. Hält zugleich fest, dass die Betreibung eingeleitet ist."""
    datum = datum or timezone.localdate()
    betrag = Decimal(betrag or 0)
    if fall.status != StwegInkassoFall.OFFEN:
        raise InkassoFehler(gettext('Der Inkassofall ist erledigt.'))
    if betrag <= 0:
        raise InkassoFehler(gettext('Der Kostenvorschuss muss grösser als 0 sein.'))
    p = _position_buchen(fall.einheit, StwegInkassoPosition.BETREIBUNGSKOSTEN, betrag, datum,
                         'Kostenvorschuss Betreibung' + (f' ({amt})' if amt else ''), soll_haben=('1110', '1020'),
                         fall=fall, amt=amt, user=user)
    if fall.betreibung_eingeleitet_am is None:
        fall.betreibung_eingeleitet_am, fall.betreibungsamt = datum, amt
        fall.save(update_fields=['betreibung_eingeleitet_am', 'betreibungsamt'])
    return p


def mahntext(mahnung):
    """Die Textzeilen der Mahnung (PDF und Mail). Gehen durch `ohne_kuendigung`."""
    fall = mahnung.fall
    e = fall.einheit
    zeilen = [
        f'{mahnung.stufe}. Mahnung',
        f'Stockwerkeigentümergemeinschaft {e.liegenschaft}',
        f'Einheit {e.bezeichnung}',
        '',
        'Gemäss unseren Unterlagen sind folgende Forderungen der Gemeinschaft (Beiträge, Zinsen, Kosten) offen:',
    ]
    for c in forderungen(e, mahnung.datum):
        if c['offen'] > 0 and _gegen_aktuellen(e, c):
            zeilen.append(f"{c['datum']:%d.%m.%Y}  {c['text']}  CHF {_chf(c['offen'])}")
    zeilen += ['', f"Total offen: CHF {_chf(mahnung.betrag)}"]
    zeilen += ['',
               f'Wir bitten Sie, den Betrag bis {mahnung.frist_bis:%d.%m.%Y} auf das Konto der Gemeinschaft zu bezahlen.']
    if mahnung.stufe == 2:
        zeilen.append('Bleibt die Zahlung aus, wird die Gemeinschaft ihre Rechte nach Gesetz und Reglement wahrnehmen.')
    if mahnung.stufe >= 3:
        zeilen.append('Dies ist die letzte Mahnung. Bleibt die Zahlung aus, wird die Gemeinschaft das Retentionsrecht '
                      'an beweglichen Sachen (Art. 712k ZGB) geltend machen und die Eintragung eines '
                      'Gemeinschaftspfandrechts an Ihrem Stockwerkeigentumsanteil (Art. 712i ZGB) verlangen.')
    zeilen.append('Sind Sie mit der Forderung nicht einverstanden oder haben Sie bereits bezahlt, melden Sie sich bitte umgehend.')
    ohne_kuendigung('\n'.join(zeilen))
    return zeilen


def mahnung_versenden(mahnung):
    """Schickt die Mahnung (PDF) an den Eigentümer, Miteigentümer in Kopie. Ohne E-Mail-Adresse: «post».
    Gibt 'email', 'post' oder 'fehler' zurück; nur bei 'email' ist sie als versendet vermerkt, bei 'post' als
    zu Post zugestellt (die Verwaltung versendet das PDF selbst)."""
    from core.utils.email_service import send_via_hoststar
    from stweg.pdf import mahnung_pdf
    from tickets.workflow import reply_to
    fall = mahnung.fall
    e = fall.einheit
    eig = fall.eigentuemer or e.stockwerkeigentuemer
    if eig is None:
        raise InkassoFehler(f'Die Einheit «{e.bezeichnung}» hat keinen Eigentümer.')
    pdf = mahnung_pdf(mahnung)
    if not eig.email:
        mahnung.kanal, mahnung.versendet_am = 'post', timezone.now()
        mahnung.save(update_fields=['kanal', 'versendet_am'])
        return 'post'
    zeilen = mahntext(mahnung)
    org = e.liegenschaft.organisation
    html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
            f"<p>Guten Tag {eig.firma_oder_name}</p><p>{zeilen[0]} — Einheit {e.bezeichnung}, Total offen "
            f"CHF {_chf(mahnung.betrag)}, zahlbar bis {mahnung.frist_bis:%d.%m.%Y}. Einzelheiten in der Beilage.</p>"
            f"<p>Freundliche Grüsse<br>{org.firma}</p></body></html>")
    ohne_kuendigung(html)
    cc = [m.email for m in e.miteigentuemer.all() if m.email and m.email != eig.email]
    ok = send_via_hoststar(eig.email, f'{mahnung.stufe}. Mahnung: Einheit {e.bezeichnung}', html,
                           f'Mahnung_{mahnung.stufe}.pdf', pdf, cc_list=cc, reply_to=reply_to(mahnung))
    if not ok:
        return 'fehler'
    mahnung.kanal, mahnung.versendet_am = 'email', timezone.now()
    mahnung.save(update_fields=['kanal', 'versendet_am'])
    return 'email'


# ── Retentionsrecht und Pfandrecht ───────────────────────────────────────

def _bedingung_mahnungen(fall, ohne_mahnungen):
    if ohne_mahnungen:
        return
    letzte = fall.mahnungen.filter(stufe=MAX_STUFE, versendet_am__isnull=False).first()
    if letzte is None:
        raise InkassoFehler('Die dritte Mahnung ist noch nicht versendet. (Die Mahnstufen sind eine Richtlinie der '
                            'Verwaltung, keine gesetzliche Voraussetzung — «ohne Mahnungen» übersteuert sie.)')


@transaction.atomic
def retention_geltend_machen(fall, gegenstaende, *, heute=None, ohne_mahnungen=False, user=None):
    """Hält fest, dass die Gemeinschaft das Retentionsrecht (Art. 712k ZGB) ausübt, und an welchen Sachen."""
    heute = heute or timezone.localdate()
    if fall.status != StwegInkassoFall.OFFEN:
        raise InkassoFehler('Der Inkassofall ist erledigt.')
    if not (gegenstaende or '').strip():
        raise InkassoFehler('Bitte die Sachen nennen, an denen das Retentionsrecht geltend gemacht wird.')
    _bedingung_mahnungen(fall, ohne_mahnungen)
    if fall.retention_erklaert_am:
        raise InkassoFehler('Das Retentionsrecht ist bereits geltend gemacht.')
    fall.retention_erklaert_am, fall.retention_gegenstaende = heute, gegenstaende.strip()
    fall.save(update_fields=['retention_erklaert_am', 'retention_gegenstaende'])
    return fall


@transaction.atomic
def pfandrecht_anmelden(fall, *, stichtag=None, ohne_mahnungen=False, user=None):
    """Meldet das Gemeinschaftspfandrecht (Art. 712i ZGB) an: summiert NUR die offenen Beitragsforderungen der
    letzten 36 Monate vor dem Stichtag und hält Pfandsumme, Ausgeschlossenes und die Einzelposten fest."""
    stichtag = stichtag or timezone.localdate()
    if fall.status != StwegInkassoFall.OFFEN:
        raise InkassoFehler('Der Inkassofall ist erledigt.')
    _bedingung_mahnungen(fall, ohne_mahnungen)
    p = pfandberechtigt(fall.einheit, stichtag)
    if p['pfandberechtigt'] <= 0:
        raise InkassoFehler(f'Keine pfandberechtigte Forderung: offen sind nur Beträge, die älter als '
                            f'{PFANDRECHT_MONATE} Monate sind (CHF {p["ausgeschlossen"]}).')
    zeilen = [{'datum': c['datum'].isoformat(), 'text': c['text'], 'art': c['art'], 'betrag': str(c['betrag']),
               'offen': str(c['offen']), 'pfandberechtigt': c['pfandberechtigt']} for c in p['zeilen']]
    pf = StwegPfandrecht.objects.create(
        fall=fall, stichtag=stichtag, betrag_gesamt=p['gesamt'], betrag_pfandberechtigt=p['pfandberechtigt'],
        betrag_ausgeschlossen=p['ausgeschlossen'], zeilen=zeilen, angemeldet_von=user)
    e = fall.einheit
    Pendenz.objects.create(
        liegenschaft=e.liegenschaft, kategorie='aufgabe', quelle=f'stweg:inkasso:{fall.pk}:pfandrecht',
        titel=f'Pfandrecht einreichen: Einheit {e.bezeichnung} (CHF {p["pfandberechtigt"]})'[:200],
        beschreibung='Antrag auf Eintragung des Gemeinschaftspfandrechts (PDF) unterschreiben und dem Grundbuchamt '
                     'einreichen; Reglement/Beschluss und Mahnungen beilegen. Pfandsumme nur die Beitragsforderungen '
                     f'der letzten {PFANDRECHT_MONATE} Monate.', erstellt_von=user)
    return pf


def pfandrecht_eingetragen(pfandrecht, datum=None):
    pfandrecht.eingetragen_am = datum or timezone.localdate()
    pfandrecht.save(update_fields=['eingetragen_am'])
    return pfandrecht
