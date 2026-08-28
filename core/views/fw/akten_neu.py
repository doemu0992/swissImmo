# core/views/fw/akten_neu.py
#
# Die beiden Aktentypen, die im Register stehen und keine Detailseite hatten:
# **Mandat** und **Dienstleister**.
#
# WAS VORLAG
#
# `faelle/akten.py` führt sieben Aktentypen. Fünf davon haben seit 4b.3 bis
# 4b.11 einen Aktenkopf und den einheitlichen Reitersatz. Zwei hatten
# überhaupt keine Seite:
#
#   mandat          nur Liste, Formular und drei Spezialseiten (Abrechnung,
#                   Kontokorrent, Auszahlung). Wer wissen wollte, was zu einem
#                   Eigentümer gehört, musste vier Seiten zusammensuchen.
#   dienstleister   nur Liste und Formular. Die Aufträge eines Handwerkers
#                   waren nirgends zusammen zu sehen — sie hingen einzeln an
#                   ihren Schadensmeldungen.
#
# Das ist derselbe Befund wie beim Regelwerk in 4b.10, eine Ebene höher: Das
# Register beschreibt eine Akte, die es in der Oberfläche nicht gibt.
#
# WAS HIER BEWUSST NICHT ENTSTEHT
#
# **Mandatsrentabilität — seit E2.56 gebaut, mit Hinweis auf die Datenbasis.**
#
# Bis hierher stand hier: «Dafür fehlt die Zeiterfassung pro Fall.» Das galt
# bis E2.46; seither gibt es `faelle.Zeiteintrag` mit Fallbezug und
# Stundensatz. Die Notiz war überholt und stand an der Stelle, wo man sie am
# ehesten glaubt.
#
# DIE FACHLICHE SORGE BLEIBT RICHTIG. Der Prototyp notierte: «Das ist eine
# Zumutung an den Alltag … Ob deine Leute das mitmachen, kann nur jemand
# entscheiden, der das Büro kennt.» Und: Eine Kennzahl aus geschätzten Stunden
# wäre schlimmer als keine.
#
# DESHALB SAGT DIE KARTE, WORAUF SIE BERUHT. Sie zeigt, wie viele Fälle des
# Mandats überhaupt Zeit erfasst haben. Sind es wenige, steht das dort — statt
# einer Zahl, die nach Aussage aussieht. Ohne Stundensatz oder ohne erfasste
# Zeit erscheint «Keine Datenbasis», nicht «CHF 0.00».

from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN

from ._basis import _global_filter


def _als_datum(wert):
    """Ein DateTimeField als lokales Datum.

    `HandwerkerAuftrag.beauftragt_am` ist ein DateTimeField mit `auto_now_add`.
    Wer es wie ein Datum behandelt, bekommt einen TypeError — oder, schlimmer,
    bei aktivierter Zeitzone einen Tag Abweichung an der Tagesgrenze.
    """
    return timezone.localtime(wert).date() if hasattr(wert, 'hour') else wert


def _mandat_kopf(md, liegenschaften, soll_monat, offene_auszahlungen, faelle):
    """Der Aktenkopf des Mandats — gerechnete Zustaende, keine Felder."""
    chips = []
    if liegenschaften:
        einheiten = sum(l['einheiten'] for l in liegenschaften)
        chips.append({'text': f'{len(liegenschaften)} Liegenschaft'
                              f'{"en" if len(liegenschaften) != 1 else ""} · '
                              f'{einheiten} Objekte', 'ton': 'fw-brand'})
    else:
        chips.append({'text': 'keine Liegenschaft zugeordnet', 'ton': 'fw-warn'})
    if md.honorar_prozent:
        chips.append({'text': f'Honorar {md.honorar_prozent} %', 'ton': 'fw-mut'})
    if not md.iban:
        chips.append({'text': 'keine IBAN', 'ton': 'fw-warn'})
    if md.benutzer_id:
        chips.append({'text': 'Portalzugang aktiv', 'ton': 'fw-good'})
    offene_faelle = [f for f in faelle if f.status not in ('abgeschlossen', 'abgebrochen')]
    if offene_faelle:
        chips.append({'text': f'{len(offene_faelle)} offen', 'ton': 'fw-warn'})

    hinweise = []
    if not md.iban:
        hinweise.append({
            'ton': 'warn', 'symbol': 'bank',
            'titel': 'Keine IBAN erfasst',
            'text': 'Ohne IBAN lässt sich keine Auszahlung ausführen — der '
                    'Ertragsüberschuss bleibt auf dem Verwaltungskonto liegen.',
            'url': f'/neu/mandate/{md.id}/bearbeiten/', 'knopf': 'IBAN erfassen'})
    if not liegenschaften:
        hinweise.append({
            'ton': 'info', 'symbol': 'liegenschaft',
            'titel': 'Keine Liegenschaft zugeordnet',
            'text': 'Ein Mandat ohne Liegenschaft erzeugt keine Abrechnung und '
                    'kein Honorar — vermutlich fehlt die Zuordnung.',
            'url': '/neu/liegenschaften/', 'knopf': 'Liegenschaft zuordnen'})
    if not md.honorar_prozent:
        hinweise.append({
            'ton': 'info', 'symbol': 'bericht',
            'titel': 'Kein Honorarsatz hinterlegt',
            'text': 'Die Mandatsabrechnung rechnet dann mit dem Vorgabewert der '
                    'Verwaltung statt mit dem vereinbarten Satz.',
            'url': f'/neu/mandate/{md.id}/honorar/', 'knopf': 'Honorar festlegen'})

    return {
        'mandat_nummer': f'M-{md.id:06d}',
        'mandat_chips': chips,
        'mandat_hinweise': hinweise,
        'mandat_soll': soll_monat,
        'mandat_auszahlungen': offene_auszahlungen,
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mandat_detail(request, pk):
    """Die Mandatsakte — alles zu einem Eigentümer an einer Stelle."""
    from django.contrib.contenttypes.models import ContentType

    from core.models import AktivitaetsLog
    from core.tenancy import aktuelle_organisation as _akt_org
    from crm.models import Eigentuemer
    from faelle.akten import aus_alt as _reiter_aus_alt
    from faelle.models import Fall
    from portfolio.models import Liegenschaft
    from rentals.models import Mietvertrag

    md = get_object_or_404(Eigentuemer.objects, pk=pk)
    basis = _global_filter(request)

    liegenschaften = []
    soll_monat = Decimal('0.00')
    for lg in Liegenschaft.objects.filter(eigentuemer=md).order_by('strasse'):
        einheiten = list(lg.einheiten.all())
        vermietet = 0
        lg_soll = Decimal('0.00')
        for e in einheiten:
            v = (Mietvertrag.objects.filter(einheit=e, status='aktiv')
                 .order_by('-beginn').first())
            if v:
                vermietet += 1
                lg_soll += v.brutto_mietzins
        soll_monat += lg_soll
        liegenschaften.append({
            'lg': lg, 'einheiten': len(einheiten), 'vermietet': vermietet,
            'leer': len(einheiten) - vermietet, 'soll': lg_soll})

    auszahlungen = list(md.auszahlungen.order_by('-datum')[:20])
    offene_auszahlungen = sum(
        1 for a in auszahlungen if getattr(a, 'ausgefuehrt_am', None) is None)

    faelle = list(
        Fall.objects.filter(akte_typ=ContentType.objects.get_for_model(Eigentuemer),
                            akte_id=md.id)
        .select_related('fallart', 'zustaendig').order_by('-eroeffnet_am'))

    dokumente = list(md.dokument.order_by('-datum')[:50]) if hasattr(md, 'dokument') else []

    # Chronik ueber die Vertraege der verwalteten Liegenschaften — derselbe
    # belastbare Weg wie bei Liegenschaft und Objekt. `AktivitaetsLog` kennt
    # keinen Ziel-Typ fuer einen Eigentuemer.
    _vids = list(Mietvertrag.objects
                 .filter(einheit__liegenschaft__eigentuemer=md)
                 .values_list('id', flat=True))
    verlauf = list(AktivitaetsLog.objects
                   .filter(ziel_typ='vertrag', ziel_id__in=_vids)
                   .select_related('benutzer')[:50]) if _vids else []

    tab_liste = _reiter_aus_alt('mandat', [
        ('uebersicht', 'Übersicht', None),
        ('abrechnung', 'Abrechnung', None),
        ('kontokorrent', 'Kontokorrent', len(auszahlungen) or None),
        ('dokumente', 'Dokumente', len(dokumente) or None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())
    # «Liegenschaften» ist der typeigene Reiter und wird von `aus_alt` von
    # selbst angehaengt — der erste Entwurf stellte ihn zusaetzlich von Hand
    # voran und sortierte danach zurueck. Beides war ueberfluessig. Nachgesehen
    # in `faelle/akten.py`, nicht vermutet.
    tab_liste = [(s, b, len(liegenschaften) or None) if s == 'liegenschaften'
                 else (s, b, z) for s, b, z in tab_liste]

    # RENTABILITAET — nur was gemessen ist (E2.56)
    #
    # Honorarertrag: Sollmiete des Mandats mal Honorarsatz. Aufwand: erfasste
    # Minuten auf Faellen dieses Mandats. Beides sind IST-Werte, keine
    # Schaetzungen.
    #
    # `abdeckung` ist der ehrlichste Teil der Karte: Wie viele Faelle haben
    # ueberhaupt Zeit erfasst? Bei zwei von neunzehn ist «CHF 340 pro Stunde»
    # keine Aussage, sondern ein Zufall. Die Karte sagt das, statt die Zahl
    # allein stehen zu lassen.
    from faelle.models import Zeiteintrag

    ident = [f.id for f in faelle] if faelle else []
    minuten = 0
    mit_zeit = 0
    if ident:
        from django.db.models import Sum, Count
        zs = (Zeiteintrag.objects.filter(fall_id__in=ident)
              .aggregate(s=Sum('minuten'), n=Count('fall_id', distinct=True)))
        minuten = zs['s'] or 0
        mit_zeit = zs['n'] or 0

    # `quantize(Decimal('0.01'))`, NICHT `0.05` — DAS ARGUMENT IST DER
    # EXPONENT, KEINE RUNDUNGSSTUFE.
    #
    # `Decimal('0.05')` liest sich wie Fuenfrappen-Rundung und ist keine:
    # Beide Schreibweisen liefern Ziffer fuer Ziffer dasselbe (nachgerechnet an
    # 1020.004 / 1020.02 / 1020.07 / 291.428). Derselbe Fund wie in E2.46.
    #
    # Hier waere Fuenfrappen-Rundung ohnehin falsch: Das ist eine Kennzahl zum
    # Lesen, kein Betrag, der bezahlt wird.
    honorar_jahr = None
    if md.honorar_prozent:
        honorar_jahr = (soll_monat * Decimal(12)
                        * Decimal(md.honorar_prozent) / Decimal(100)
                        ).quantize(Decimal('0.01'))

    chf_pro_stunde = None
    if honorar_jahr is not None and minuten >= 60:
        chf_pro_stunde = (honorar_jahr / (Decimal(minuten) / Decimal(60))
                          ).quantize(Decimal('0.01'))

    rentabilitaet = {
        'honorar_jahr': honorar_jahr,
        'minuten': minuten,
        'stunden': (Decimal(minuten) / Decimal(60)).quantize(Decimal('0.1')) if minuten else None,
        'chf_pro_stunde': chf_pro_stunde,
        'faelle_gesamt': len(ident),
        'faelle_mit_zeit': mit_zeit,
        # Warum die Zahl fehlt — als Text, nicht als Leerstelle.
        'fehlt': (None if chf_pro_stunde is not None else
                  'Kein Honorarsatz hinterlegt' if not md.honorar_prozent else
                  'Noch keine Stunde erfasst'),
    }

    return render(request, 'fw/mandat_detail.html', {
        **basis, 'nav': 'mandate', 'md': md,
        'rentabilitaet': rentabilitaet,
        **_mandat_kopf(md, liegenschaften, soll_monat, offene_auszahlungen, faelle),
        'liegenschaften': liegenschaften,
        'soll_monat': soll_monat,
        'auszahlungen': auszahlungen,
        'mandat_faelle': faelle,
        'dokumente': dokumente,
        'verlauf': verlauf,
        'tab_liste': tab_liste,
        'heute': timezone.localdate(),
    })


def _dienstleister_kopf(h, auftraege, offen, kosten_jahr, faelle):
    """Der Aktenkopf des Dienstleisters."""
    chips = [{'text': h.get_branche_display(), 'ton': 'fw-brand'}]
    if offen:
        chips.append({'text': f'{len(offen)} offener Auftrag' if len(offen) == 1
                              else f'{len(offen)} offene Aufträge', 'ton': 'fw-warn'})
    else:
        chips.append({'text': 'kein offener Auftrag', 'ton': 'fw-good'})
    if not h.telefon and not h.email:
        chips.append({'text': 'keine Kontaktangabe', 'ton': 'fw-crit'})

    hinweise = []
    if not h.telefon:
        hinweise.append({
            'ton': 'warn', 'symbol': 'senden',
            'titel': 'Keine Telefonnummer',
            'text': 'Bei einem Wasserschaden ausserhalb der Bürozeit ist eine '
                    'E-Mail-Adresse wertlos.',
            'url': f'/neu/dienstleister/{h.id}/bearbeiten/', 'knopf': 'Nummer erfassen'})
    # Aufträge, die seit über 30 Tagen als «ausstehend» stehen — das ist keine
    # Vermutung, sondern ein Datum im Bestand.
    heute = timezone.localdate()
    liegen = [a for a in offen
              if a.beauftragt_am and (heute - _als_datum(a.beauftragt_am)).days > 30]
    if liegen:
        hinweise.append({
            'ton': 'crit', 'symbol': 'wartet',
            'titel': f'{len(liegen)} Auftrag{"" if len(liegen) == 1 else "s"} '
                     f'älter als 30 Tage',
            'text': 'Beauftragt, aber nicht als erledigt gemeldet. Entweder '
                    'wurde nicht gearbeitet, oder die Rückmeldung fehlt.',
            'url': '?tab=auftraege', 'knopf': 'Aufträge ansehen'})

    return {
        'dl_nummer': f'H-{h.id:06d}',
        'dl_chips': chips,
        'dl_hinweise': hinweise,
        'dl_offen': len(offen),
        'dl_kosten_jahr': kosten_jahr,
        'dl_liegen': len(liegen),
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dienstleister_detail(request, pk):
    """Die Dienstleisterakte — die Aufträge eines Handwerkers an einer Stelle.

    Bis 4b.12 gab es sie nicht: Aufträge hingen einzeln an ihren
    Schadensmeldungen. Wer wissen wollte, was ein Handwerker im laufenden Jahr
    gekostet hat oder was bei ihm liegt, musste die Schadensliste durchgehen.
    """
    from django.contrib.contenttypes.models import ContentType

    from core.tenancy import aktuelle_organisation as _akt_org
    from crm.models import Handwerker
    from faelle.akten import aus_alt as _reiter_aus_alt
    from faelle.models import Fall
    from tickets.models import HandwerkerAuftrag

    h = get_object_or_404(Handwerker.objects, pk=pk)
    basis = _global_filter(request)
    heute = timezone.localdate()

    auftraege = list(HandwerkerAuftrag.objects.filter(handwerker=h)
                     .select_related('ticket', 'kreditoren_rechnung')
                     .order_by('-beauftragt_am'))
    offen = [a for a in auftraege if a.status != 'erledigt']
    # `liegt` wird HIER gesetzt, nicht in der Vorlage: Ein Datumsvergleich in
    # einem `{% if %}` ist in Django-Vorlagen nicht ausdrueckbar, und ein
    # Modellfeld `tage_offen` gibt es nicht — der erste Entwurf hat es
    # erfunden und waere in der Vorlage still zu leer ausgewertet worden.
    #
    # `beauftragt_am` ist ein DateTimeField, kein DateField. Die erste Fassung
    # rechnete `heute - beauftragt_am` und warf einen TypeError — sichtbar nur,
    # weil ein Test die Seite wirklich aufrief.
    for a in auftraege:
        a.liegt = bool(a.status != 'erledigt' and a.beauftragt_am
                       and (heute - _als_datum(a.beauftragt_am)).days > 30)

    # Kosten des laufenden Jahres: **effektiv** wo vorhanden, sonst geschätzt.
    # Die Unterscheidung steht in der Anzeige — eine Summe, die beides still
    # vermischt, sähe genauer aus, als sie ist.
    kosten_jahr = Decimal('0.00')
    kosten_geschaetzt_anteil = Decimal('0.00')
    for a in auftraege:
        if not a.beauftragt_am or _als_datum(a.beauftragt_am).year != heute.year:
            continue
        if a.kosten_effektiv:
            kosten_jahr += a.kosten_effektiv
        elif a.kosten_geschaetzt:
            kosten_jahr += a.kosten_geschaetzt
            kosten_geschaetzt_anteil += a.kosten_geschaetzt

    faelle = list(
        Fall.objects.filter(akte_typ=ContentType.objects.get_for_model(Handwerker),
                            akte_id=h.id)
        .select_related('fallart', 'zustaendig').order_by('-eroeffnet_am'))

    from portfolio.models import Schluessel  # noqa: F401  (nur fuer die Beziehung)
    schluessel = list(h.schluesselausgabe.select_related('schluessel')
                      .filter(rueckgabe_am__isnull=True)) \
        if hasattr(h, 'schluesselausgabe') else []

    tab_liste = _reiter_aus_alt('dienstleister', [
        ('uebersicht', 'Übersicht', None),
        ('auftraege', 'Aufträge', len(auftraege) or None),
        ('finanzen', 'Finanzen', None),
        ('dokumente', 'Dokumente', None),
        ('verlauf', 'Verlauf', None),
    ], organisation=getattr(request, 'organisation', None) or _akt_org())

    return render(request, 'fw/dienstleister_detail.html', {
        **basis, 'nav': 'dienstleister', 'h': h,
        **_dienstleister_kopf(h, auftraege, offen, kosten_jahr, faelle),
        'auftraege': auftraege,
        'offene_auftraege': offen,
        'kosten_geschaetzt_anteil': kosten_geschaetzt_anteil,
        'dl_faelle': faelle,
        'schluessel': schluessel,
        'tab_liste': tab_liste,
        'heute': heute,
    })
