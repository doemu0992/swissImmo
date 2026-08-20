# core/views/fw/regelwerk.py
#
# Der Fristenwächter — die Bedienung zu einem Regelwerk, das seit Phase 4a
# vollständig gebaut war und von nichts aufgerufen wurde.
#
# WAS VORLAG UND WAS FEHLTE
#
#   faelle/regelwerk.py         rechnet: kuendigungstermin(), pruefen(), sperrt()
#   faelle/regelwerk_models.py  Regelsatz je Kanton, Regel mit Parametern,
#                               Regelanwendung als Protokoll mit Regelstand
#   Aufrufer                    keiner. Nicht einer.
#
# Die Kündigungserfassung rechnete stattdessen mit
# `rentals.services.berechne_kuendigungstermin` — richtig gerechnet, aber ohne
# Protokoll, ohne kantonale Fassung, ohne die Unterscheidung zwischen einer
# geprüften und einer ungeprüften Regel. Und sie prüfte nur die eine Hälfte:
# ein zu FRÜHER Termin wurde geklemmt, ein Datum, das gar kein zulässiger
# Termin ist (der 15. eines Monats), lief durch.
#
# WARUM BEIDES BLEIBT
#
# `berechne_kuendigungstermin` **berechnet** aus dem Vertrag den nächsten
# Termin — Einstellplatz nach Art. 266e, `erstmals_kuendbar_auf`, Freitextfeld.
# Das Regelwerk **prüft** einen genannten Termin gegen eine versionierte Regel
# und schreibt mit, unter welcher Fassung es das getan hat. Das eine ersetzt
# das andere nicht; die Berechnung liefert den Vorschlag, die Prüfung das
# Protokoll. Zusammengeführt sind sie in `pruefung_zum_vertrag()`.
#
# DER STAND DER REGELN
#
# Ausgeliefert wird **ungeprüft**. Das ist kein Versäumnis, sondern der
# Entscheid vom 19.08.2026, festgehalten im Kopf von `faelle/regelwerk.py`:
# bauen, protokollieren, nachträglich berichtigen lassen. `sperrt()` sorgt
# dafür, dass eine ungeprüfte Regel nie den Betrieb anhält — sie warnt. Erst
# wer den Regelsatz als geprüft kennzeichnet, schaltet die Sperre scharf.

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.auth import (log_aktion, rolle_erforderlich, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)

from ._basis import _global_filter


#: Was eine Regelart an Parametern erwartet, als Bauplan für das Formular.
#: Steht hier und nicht im Modell, weil `Regel.parameter` bewusst ein freies
#: JSON-Feld ist — die Form der Eingabe ist eine Frage der Bedienung, nicht
#: der Ablage. Jeder Eintrag: (Schlüssel, Beschriftung, Typ, Hilfetext).
PARAMETERFELDER = {
    'kuendigungstermin': [
        ('frist_monate', 'Kündigungsfrist (Monate)', 'zahl',
         'Gesetzliche Mindestfrist für Wohnräume: drei Monate (Art. 266c OR). '
         'Ein längerer vertraglicher Wert überschreibt diesen Vorgabewert.'),
        ('termine', 'Zulässige Termine', 'termine',
         'Als TT.MM, mit Komma getrennt — etwa 31.03, 30.06, 30.09. Leer '
         'bedeutet: es gilt, was im einzelnen Vertrag steht.'),
    ],
    # Die übrigen drei Arten sind als Datenmodell vorhanden, aber in
    # `faelle.regelwerk.pruefen` noch nicht gerechnet. Sie erscheinen deshalb
    # in der Verwaltung, tragen dort aber den Hinweis, dass sie nichts prüfen.
    'zahlungsfrist': [
        ('tage', 'Zahlungsfrist (Tage)', 'zahl',
         'Art. 257d OR: mindestens 30 Tage bei Wohn- und Geschäftsräumen.'),
    ],
    'mietzins_zustellung': [
        ('vorlauf_tage', 'Vorlauf vor Fristbeginn (Tage)', 'zahl',
         'Art. 269d OR: die Mitteilung muss mindestens zehn Tage vor Beginn '
         'der Kündigungsfrist zugehen.'),
    ],
    'kaution_hoechstbetrag': [
        ('monatsmieten', 'Höchstbetrag (Monatsmieten)', 'zahl',
         'Art. 257e OR: höchstens drei Monatszinse bei Wohnräumen.'),
    ],
}

#: Welche Arten `faelle.regelwerk.pruefen` tatsächlich rechnet. Alles andere
#: wirft dort `NotImplementedError` — die Verwaltung muss das anzeigen können,
#: sonst legt jemand eine Regel an, die nie etwas tut.
GERECHNETE_ARTEN = ('kuendigungstermin',)


# ============================================================
# DIE PRÜFUNG AM VERTRAG
# ============================================================

def pruefung_zum_vertrag(vertrag, zugang, gewuenschter_termin=None,
                         fall=None, protokollieren=True):
    """Prüft eine Kündigung gegen das Regelwerk der Organisation.

    Führt die beiden Wege zusammen: Die Termine und die Frist kommen aus dem
    **Vertrag**, sofern die Regel sie nicht ausdrücklich vorgibt. Damit gilt
    weiterhin, was vereinbart wurde, und die Regel ergänzt nur, was der
    Vertrag offenlässt.

    Gibt `(Befund, Regelanwendung | None, Regel | None)` zurück. Fehlt eine
    Regel, ist der Befund in Ordnung mit Hinweis — eine fehlende Regel darf
    nicht wie eine verletzte aussehen.
    """
    from faelle.regelwerk import pruefen, regel_holen
    from rentals.services import termine_aus_vertrag

    organisation = vertrag.organisation
    kanton = _kanton_zum_vertrag(vertrag)
    regel = regel_holen(organisation, 'kuendigungstermin', kanton)

    parameter = dict(getattr(regel, 'parameter', None) or {})
    # Der Vertrag hat Vorrang vor dem Vorgabewert der Regel: Eine vereinbarte
    # längere Frist ist gültig, eine kürzere wäre nichtig — Letzteres prüft die
    # Regel nicht, das leistet die Vertragserfassung.
    frist = int(vertrag.kuendigungsfrist_monate or 0) or parameter.get('frist_monate') or 3
    termine = termine_aus_vertrag(vertrag) or list(parameter.get('termine') or [])

    befund, anwendung = pruefen(
        'kuendigungstermin', organisation, fall=fall, kanton=kanton,
        protokollieren=protokollieren,
        zugang=zugang, gewuenschter_termin=gewuenschter_termin,
        termine=termine, frist_monate=frist)
    return befund, anwendung, regel


def _kanton_zum_vertrag(vertrag):
    """Der Kanton der Liegenschaft, sofern erfasst.

    Ortsübliche Kündigungstermine sind kantonal verschieden; ohne Kanton
    greift `regel_holen` auf den allgemeinen Regelsatz zurück.
    """
    einheit = getattr(vertrag, 'einheit', None)
    lg = getattr(einheit, 'liegenschaft', None)
    return (getattr(lg, 'kanton', '') or '').strip().upper()[:2]


def folgekosten(befund, vertrag):
    """Was ein falscher Termin kostet, in Monatszinsen und Franken.

    Der Prototyp führt diese Zahl («Differenz 6 Monate Mietzins») als
    eigentliche Begründung des Fristenwächters: Eine Fristenliste warnt nicht,
    eine Zahl schon. Sie steht nur bei einer Beanstandung und nur, wenn beide
    Daten vorliegen — geraten wird nichts.
    """
    from faelle.regelwerk import _monate_zwischen
    rechnung = befund.rechnung or {}
    gewuenscht = rechnung.get('gewuenscht')
    naechster = rechnung.get('naechster_moeglicher')
    if befund.ok or not gewuenscht or not naechster:
        return None
    g, n = parse_date(gewuenscht), parse_date(naechster)
    if not g or not n or n <= g:
        return None
    monate = _monate_zwischen(g, n)
    # Bruttomietzins, nicht netto: Was ausfällt, ist der Betrag, der dem Mieter
    # in Rechnung gestellt worden wäre. Ob die Wohnung in dieser Zeit
    # weitervermietet wird, weiss niemand — die Zahl ist die Aussetzung, nicht
    # der sichere Verlust, und die Anzeige sagt das auch so.
    miete = getattr(vertrag, 'brutto_mietzins', None)
    return {'monate': monate,
            'betrag': (miete * monate) if miete else None,
            'miete': miete}


# ============================================================
# DIE SEITEN
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_regelwerk(request):
    """Übersicht: welche Regelsätze gelten, welche sind geprüft, was rechnet."""
    from faelle.regelwerk_models import Regel, Regelanwendung, Regelsatz

    basis = _global_filter(request)
    saetze = []
    for satz in Regelsatz.objects.prefetch_related('regeln').order_by(
            'kanton', 'bezeichnung'):
        regeln = [{
            'regel': r,
            'rechnet': r.art in GERECHNETE_ARTEN,
            'sperrt': r.verbindlichkeit == Regel.SPERRE and satz.geprueft,
        } for r in satz.regeln.all()]
        saetze.append({'satz': satz, 'regeln': regeln,
                       'offene_arten': [
                           (a, bez) for a, bez in Regel.ARTEN
                           if not any(r['regel'].art == a for r in regeln)]})

    letzte = Regelanwendung.objects.select_related('fall')[:8]
    return render(request, 'fw/regelwerk.html', {
        **basis, 'nav': 'regelwerk', 'saetze': saetze, 'letzte': letzte,
        'beanstandet': Regelanwendung.objects.filter(
            befund=Regelanwendung.BEANSTANDET, uebersteuert=False).count(),
        'arten': Regel.ARTEN, 'gerechnete': GERECHNETE_ARTEN,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_regelsatz_form(request, pk=None):
    """Regelsatz anlegen oder ändern — samt seiner Regeln auf einer Seite.

    Regelsatz und Regeln in einem Formular, weil ein Regelsatz ohne Regeln
    nichts tut und die getrennte Erfassung genau diesen leeren Zwischenstand
    erzeugt hätte.
    """
    from faelle.regelwerk_models import Regel, Regelsatz

    basis = _global_filter(request)
    satz = get_object_or_404(Regelsatz.objects, pk=pk) if pk else None

    if request.method == 'POST':
        P = request.POST
        bezeichnung = P.get('bezeichnung', '').strip()
        if not bezeichnung:
            messages.error(request, 'Der Regelsatz braucht eine Bezeichnung.')
            return redirect(request.path)

        kanton = P.get('kanton', '').strip().upper()[:2]

        # `Regelsatz` trägt eine Eindeutigkeit über (organisation, kanton):
        # **ein** Satz je Kanton, und **ein** allgemeiner ohne Kanton. Das ist
        # Absicht — zwei gleichzeitig geltende Fassungen wären die Frage,
        # welche gilt, ohne Antwort. Ohne diese Prüfung endet der zweite
        # Versuch als IntegrityError, also als 500 statt als Satz Text.
        from faelle.regelwerk_models import Regelsatz as _RS
        kollision = _RS.objects.filter(kanton=kanton)
        if satz is not None:
            kollision = kollision.exclude(pk=satz.pk)
        if kollision.exists():
            bereich = f'den Kanton {kanton}' if kanton else 'alle Kantone'
            messages.error(
                request, f'Für {bereich} besteht bereits der Regelsatz '
                         f'«{kollision.first()}». Es gilt ein Satz je Kanton — '
                         f'bearbeite den bestehenden, statt einen zweiten anzulegen.')
            return redirect(request.path)

        war_geprueft = satz.geprueft if satz else False
        if satz is None:
            # Ohne `organisation`: `Regelsatz.save()` holt sie aus dem Kontext.
            # Sie hier zu setzen hiesse, den Weg zu verdoppeln, den es schon gibt.
            satz = Regelsatz()
        satz.bezeichnung = bezeichnung
        satz.kanton = kanton
        satz.geprueft = P.get('geprueft') == 'on'
        satz.hinweis = P.get('hinweis', '').strip()
        satz.aktiv = P.get('aktiv') == 'on'
        # Der Stand ist der Schlüssel für spätere Berichtigungen: Er muss sich
        # bei jeder inhaltlichen Änderung bewegen, sonst lässt sich die Menge
        # der unter der alten Fassung geprüften Fälle nicht abgrenzen.
        satz.stand = timezone.localdate()
        satz.save()

        for art, _bez in Regel.ARTEN:
            if P.get(f'aktiv_{art}') != 'on':
                Regel.objects.filter(regelsatz=satz, art=art).delete()
                continue
            regel, _neu = Regel.objects.get_or_create(regelsatz=satz, art=art)
            regel.verbindlichkeit = (Regel.SPERRE if P.get(f'sperre_{art}') == 'on'
                                     else Regel.WARNUNG)
            regel.begruendung = P.get(f'begruendung_{art}', '').strip()
            regel.parameter = _parameter_lesen(art, P)
            regel.aktiv = True
            regel.save()

        if satz.geprueft and not war_geprueft:
            messages.warning(
                request, 'Der Regelsatz gilt jetzt als juristisch geprüft. '
                         'Regeln mit Verbindlichkeit «Sperre» verhindern ab '
                         'sofort das Speichern.')
        log_aktion(request, 'Regelsatz gespeichert', str(satz),
                   f'Stand {satz.stand:%d.%m.%Y}, '
                   f'{"geprüft" if satz.geprueft else "ungeprüft"}', ziel=satz)
        messages.success(request, f'Regelsatz «{satz}» gespeichert.')
        return redirect('/neu/regelwerk/')

    regeln = {r.art: r for r in satz.regeln.all()} if satz else {}
    return render(request, 'fw/regelsatz_form.html', {
        **basis, 'nav': 'regelwerk', 'satz': satz,
        'zeilen': [{
            'art': art, 'bezeichnung': bez, 'regel': regeln.get(art),
            'felder': _felder_mit_werten(art, regeln.get(art)),
            'rechnet': art in GERECHNETE_ARTEN,
        } for art, bez in _arten()],
    })


def _arten():
    from faelle.regelwerk_models import Regel
    return Regel.ARTEN


def _parameter_lesen(art, P):
    """Liest die Parameter einer Regelart aus dem Formular.

    Leere Felder werden **weggelassen** und nicht als 0 oder '' abgelegt: Ein
    fehlender Parameter bedeutet «es gilt, was im Vertrag steht», eine Null
    bedeutet «keine Frist». Die beiden zu verwechseln hiesse, eine Kündigung
    ohne Frist durchzulassen.
    """
    werte = {}
    for schluessel, _bez, typ, _hilfe in PARAMETERFELDER.get(art, []):
        roh = (P.get(f'{art}__{schluessel}') or '').strip()
        if not roh:
            continue
        if typ == 'zahl':
            try:
                werte[schluessel] = int(roh)
            except ValueError:
                continue
        elif typ == 'termine':
            eintraege = [t.strip() for t in roh.replace(';', ',').split(',')]
            werte[schluessel] = [t for t in eintraege if _ist_termin(t)]
        else:
            werte[schluessel] = roh
    return werte


def _ist_termin(text):
    """'31.03' ja, '31.3.' ja, 'Ende März' nein."""
    teile = text.replace(' ', '').rstrip('.').split('.')
    if len(teile) != 2:
        return False
    try:
        tag, monat = int(teile[0]), int(teile[1])
    except ValueError:
        return False
    return 1 <= tag <= 31 and 1 <= monat <= 12


def _felder_mit_werten(art, regel):
    werte = dict(getattr(regel, 'parameter', None) or {})
    felder = []
    for schluessel, bez, typ, hilfe in PARAMETERFELDER.get(art, []):
        wert = werte.get(schluessel)
        if typ == 'termine' and isinstance(wert, list):
            wert = ', '.join(wert)
        felder.append({'name': f'{art}__{schluessel}', 'bezeichnung': bez,
                       'typ': typ, 'hilfe': hilfe,
                       'wert': '' if wert is None else wert})
    return felder


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
@require_POST
def fw_regelsatz_loeschen(request, pk):
    from faelle.regelwerk_models import Regelsatz
    satz = get_object_or_404(Regelsatz.objects, pk=pk)
    name = str(satz)
    satz.delete()
    log_aktion(request, 'Regelsatz gelöscht', name, '')
    messages.success(request, f'Regelsatz «{name}» gelöscht. Das Protokoll der '
                              f'bisherigen Anwendungen bleibt erhalten.')
    return redirect('/neu/regelwerk/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_regelwerk_protokoll(request):
    """Das Anwendungsprotokoll — welche Regel hat wann was gesagt.

    Der Filter nach **Stand** ist der eigentliche Zweck der Seite: Wird eine
    Regel später berichtigt, ist das die Abfrage, die alle unter der alten
    Fassung entschiedenen Fälle findet.
    """
    from faelle.regelwerk_models import Regel, Regelanwendung

    basis = _global_filter(request)
    zeilen = Regelanwendung.objects.select_related('fall', 'uebersteuert_von')

    art = request.GET.get('art', '')
    if art:
        zeilen = zeilen.filter(art=art)
    befund = request.GET.get('befund', '')
    if befund in (Regelanwendung.OK, Regelanwendung.BEANSTANDET):
        zeilen = zeilen.filter(befund=befund)
    stand = parse_date(request.GET.get('stand', '') or '')
    if stand:
        zeilen = zeilen.filter(regel_stand=stand)
    if request.GET.get('nur_ungeprueft') == '1':
        zeilen = zeilen.filter(geprueft_war=False)

    staende = list(Regelanwendung.objects.values_list('regel_stand', flat=True)
                   .distinct().order_by('-regel_stand')[:20])
    return render(request, 'fw/regelwerk_protokoll.html', {
        **basis, 'nav': 'regelwerk', 'zeilen': zeilen[:200],
        'gesamt': zeilen.count(), 'arten': Regel.ARTEN, 'staende': staende,
        'f_art': art, 'f_befund': befund, 'f_stand': stand,
        'f_ungeprueft': request.GET.get('nur_ungeprueft') == '1',
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def fw_regelanwendung_uebersteuern(request, pk):
    """Eine Beanstandung bewusst überstimmen — nur mit Begründung.

    Das Modell erzwingt die Begründung bereits (`uebersteuern()` wirft ohne
    sie). Hier wird der Fehler in eine Meldung übersetzt, statt als 500 zu
    enden.
    """
    from faelle.regelwerk_models import Regelanwendung
    anwendung = get_object_or_404(Regelanwendung.objects, pk=pk)
    try:
        anwendung.uebersteuern(request.user, request.POST.get('begruendung', ''))
    except ValueError as fehler:
        messages.error(request, str(fehler))
        return redirect(request.POST.get('zurueck') or '/neu/regelwerk/protokoll/')
    log_aktion(request, 'Regelbefund übersteuert', anwendung.art,
               anwendung.uebersteuert_begruendung, ziel=anwendung)
    messages.success(request, 'Übersteuerung mit Begründung protokolliert.')
    return redirect(request.POST.get('zurueck') or '/neu/regelwerk/protokoll/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kuendigung_pruefen(request, vertrag_id):
    """Die Prüfung als Bruchstück, für die laufende Anzeige im Formular.

    OHNE PROTOKOLL. Das ist der Unterschied zur Prüfung beim Speichern: Wer
    ein Datum tippt und wieder verwirft, hat keine Regel angewendet. Würde
    jeder Tastendruck protokolliert, wäre das Protokoll unlesbar und die Frage
    «unter welcher Fassung wurde entschieden» nicht mehr beantwortbar.
    """
    from rentals.models import Mietvertrag
    v = get_object_or_404(Mietvertrag.objects, id=vertrag_id)
    zugang = parse_date(request.GET.get('zugang', '') or '') or timezone.localdate()
    gewuenscht = parse_date(request.GET.get('termin', '') or '')

    befund, _anwendung, regel = pruefung_zum_vertrag(
        v, zugang, gewuenscht, protokollieren=False)
    from faelle.regelwerk import sperrt
    return render(request, 'fw/_regel_befund.html', {
        'befund': befund, 'regel': regel, 'v': v,
        'sperrt': bool(regel) and sperrt(regel, befund),
        'kosten': folgekosten(befund, v),
    })
