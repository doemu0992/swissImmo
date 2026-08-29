# core/views/fw/dashboard.py
#
# Die Einstiegsseiten der Oberflaeche: das Dashboard mit der Inbox und die
# Finanzuebersicht. Sie standen im KOPFBEREICH der urspruenglichen fw.py,
# vor dem ersten Blockkommentar — deshalb kommen sie zuletzt, als 34. und
# letzter Umzug der Etappe 1 (siehe docs/ETAPPE-1-ZERLEGEN.md).
#
# Damit ist _rest.py leer und faellt weg: Es gibt keine "noch nicht
# aufgeteilte" Restdatei mehr.

import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN
# Die Ansichten stehen weiterhin in arbeit.py — dort liegen auch die uebrigen
# Arbeitsflaechen. Eine zweite Definition hier waere die klassische Stelle, an
# der zwei Listen auseinanderlaufen.
from core.views.fw.arbeit import ANSICHTEN
from finance.models import DebitorenRechnung

from ._basis import _global_filter, _pendenz_ziel

# Elf Importe sind mit der alten Startseite weggefallen (Einheit, Liegenschaft,
# Mietvertrag, defaultdict, date, STATUS_PILL, _pendenz_ziel, _num, die beiden
# Mahnstufen-Helfer). Sie standen fuer den Portfolio-Donut, das Ertragsdiagramm
# und die Leerstandsliste; `fw_finanzen` darunter braucht keinen davon.

logger = logging.getLogger(__name__)


def _kopf_filter(request):
    """Die zwei Filter aus Konzept v7: Zustaendigkeit und Mandat.

    WARUM SIE HIER STEHEN UND NICHT IN `_global_filter`

    Der Liegenschaftsfilter gilt fuer die ganze Anwendung — er steht in der
    Seitenleiste und wirkt auf jeder Seite. Diese zwei gelten NUR fuer den
    Arbeitsvorrat: «Was liegt bei mir?» ist eine Frage an die Faelle, nicht an
    die Liegenschaften.

    DIE ZWEI SEITEN LAUFEN NICHT UEBER DENSELBEN WEG — DAS IST DER KERN HIER

    `Eigentuemer.objects` ist ein `TenantManager`; eine fremde ID findet dort
    schlicht nichts, und eine eigene Besitzpruefung waere tautologisch.

    `Benutzer` IST ANDERS. Das Modell ist ein schlichter `AbstractUser`, sein
    `objects` ist Djangos `UserManager` — NICHT mandantengetrennt. Die
    Zugehoerigkeit haengt an `Mitgliedschaft`, weil eine Treuhaenderin fuer
    zwei Verwaltungen arbeiten kann. Ohne `mitgliedschaften__organisation`
    stuende im Auswahlfeld das VOLLSTAENDIGE Team jeder anderen Verwaltung,
    mit Namen. Genau dieser Fund steht seit dem 17.08.2026 in
    `core/views/fw/profil.py` — dort fiel er durchs Raster, weil die URL
    keinen ID-Parameter traegt. Ein Auswahlfeld traegt auch keinen.

    «Alle» IST KEIN WERT, SONDERN DAS FEHLEN EINES WERTES. `None` heisst
    «nicht eingeschraenkt»; ein leerer Filter waere etwas anderes als «keine
    Zustaendigkeit gesetzt».
    """
    from crm.models import Eigentuemer

    User = get_user_model()
    organisation = getattr(request, 'organisation', None)
    team = User.objects.filter(is_active=True,
                               mitgliedschaften__organisation=organisation).distinct()

    wer_id = request.GET.get('wer') or None
    mandat_id = request.GET.get('mandat') or None

    wer = mandat = None
    if wer_id and str(wer_id).isdigit():
        wer = team.filter(pk=wer_id).first()
    if mandat_id and str(mandat_id).isdigit():
        mandat = Eigentuemer.objects.filter(pk=mandat_id).first()

    return {
        'f_wer': wer,
        'f_mandat': mandat,
        'f_wer_auswahl': list(team.order_by('first_name', 'username')[:50]),
        'f_mandat_auswahl': list(Eigentuemer.objects.order_by('firma_oder_name')[:50]),
        # Beide Filter in der Adresse behalten, damit ein Reiterwechsel sie
        # nicht verliert. Die Reiter sind einfache `<a href="?…">` — sie
        # ersetzen die ganze Abfragezeichenfolge, also muss alles mit, was
        # gelten soll.
        'f_query': ''.join([f'&wer={wer.pk}' if wer else '',
                            f'&mandat={mandat.pk}' if mandat else '']),
    }


def _vertretung_fuer(request, heute):
    """Wen vertritt der angemeldete Benutzer gerade?

    Gibt eine Liste von `(Name, bis)` zurueck — meist leer, gelegentlich eine,
    selten mehrere.

    `Abwesenheit.laufend()` prueft `von <= heute <= bis`, beide INKLUSIV: Wer
    «bis 25.08.» abwesend ist, ist am 25. noch weg. Das steht im Modell
    begruendet und ist die haeufigste Fehlerquelle bei Zeitraeumen.

    WARUM NICHT AUS `av_vertretung` ABGELEITET

    Der Arbeitsvorrat laedt die laufenden Abwesenheiten ohnehin, und die Zeile
    hier daraus zu filtern haette keine Abfrage gekostet. Aber `vertretung()`
    schneidet bei ZEHN ab (`[:10]`) — bei mehr gleichzeitigen Abwesenheiten
    fiele ausgerechnet die eigene Vertretung stillschweigend aus dem Kopf,
    und zwar genau in der Ferienwoche, in der der Hinweis am meisten zaehlt.
    Eine eigene, auf `vertreten_durch` gefilterte Abfrage liefert praktisch
    immer null Zeilen und ist immer vollstaendig.

    Der Mandantenbezug kommt vom `TenantManager` auf `Abwesenheit.objects` —
    eine Abwesenheit aus einer fremden Organisation darf hier nie auftauchen,
    auch dann nicht, wenn dort jemand denselben Benutzer als Vertretung
    eingetragen hat.
    """
    try:
        from faelle.termin_models import Abwesenheit
        return [
            (a.benutzer.get_short_name() or a.benutzer.get_username(), a.bis)
            for a in Abwesenheit.objects.laufend(heute)
                              .filter(vertreten_durch=request.user)
                              .select_related('benutzer')
        ]
    except Exception:
        # Eine fehlende Vertretungsangabe darf die Startseite nicht kosten.
        logger.exception('Vertretungshinweis nicht ladbar')
        return []


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dashboard(request):
    """Die Startseite: Arbeitsvorrat mit Ansichten, Lage, Mandate.

    ZUSAMMENFUEHRUNG. Vorher gab es zwei Startflaechen: diese hier mit
    «Was reisst», «Zulauf» und vier Kennzahlkacheln aus der Vorgaengerzeit —
    und `/neu/arbeit/` mit denselben zwei Abschnitten plus Ansichten. Beide
    taten dasselbe, und die aeltere gewann, weil sie unter `/neu/` lag.
    `fw_arbeit` leitet jetzt hierher um.

    Die vier alten Kacheln (Mietertrag-Diagramm, Portfolio-Donut, Belegung,
    Leerstandsliste) sind ersatzlos entfallen. Sie zeigten den Bestand; an
    ihre Stelle tritt der Lage-Streifen mit Vormonatsvergleich und «Was
    abweicht». Wer die alten Auswertungen sucht, findet sie unter
    /neu/berichte/ — sie waren dort schon immer.
    """
    from faelle.arbeitsvorrat import arbeitsvorrat, was_reisst
    from faelle.lage import lage
    from faelle.models import Fall

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    ansicht = request.GET.get('ansicht', 'heute')
    if ansicht not in dict(ANSICHTEN):
        ansicht = 'heute'

    # Die gemeinsamen Abschnitte kommen aus dem Sammler — Zulauf, Termine,
    # Freigaben, Liegezeit, Vertretung unter den `av_*`-Namen, die der
    # eingebundene Baustein erwartet. Sie hier ein zweites Mal
    # zusammenzusuchen, war der erste Entwurf; damit haette `arbeitsvorrat()`
    # ausser Tests keinen Aufrufer mehr gehabt — genau die Waise, die in
    # dieser Phase schon dreimal aufgetaucht ist.
    # Die zwei Kopf-Filter aus v7 (E2.60). Sie greifen in die Abfrage der
    # Fallschritte, nicht auf die fertige Liste — sonst zaehlte die Kopfzeile
    # weiter alles.
    kf = _kopf_filter(request)
    av = arbeitsvorrat(request, aktive_lg,
                       wer=kf['f_wer'], mandat=kf['f_mandat'])

    # EIN Durchgang fuer alle Fenster. `was_reisst(365)` ist die Obermenge;
    # «Diese Woche» und «Heute» sind daraus gefiltert, statt die Sammelarbeit
    # ueber alle vier Quellen zwei- oder dreimal zu leisten.
    alle = was_reisst(heute, grenze=365, aktive_lg=aktive_lg)
    woche = [e for e in alle if e['tage'] <= 7]
    heute_faellig = [e for e in woche if e['tage'] <= 0]

    # Die Zahlen an den Reitern sind die eigentliche Aussage — «3
    # liegengeblieben» sieht man, ohne die Ansicht zu wechseln.
    zaehler = {
        'heute': len(heute_faellig),
        'woche': len(woche),
        'liegen': Fall.objects.liegengeblieben().count(),
        'wartet': Fall.objects.filter(status=Fall.WARTET).count(),
        'alle': len(alle),
    }

    faelle = []
    vorrat = []
    if ansicht == 'heute':
        vorrat = heute_faellig
    elif ansicht == 'woche':
        vorrat = woche
    elif ansicht == 'wartet':
        faelle = list(Fall.objects.filter(status=Fall.WARTET)
                      .select_related('fallart', 'zustaendig')
                      .order_by('letzte_bewegung'))
    elif ansicht == 'liegen':
        faelle = list(Fall.objects.liegengeblieben()
                      .select_related('fallart', 'zustaendig')
                      .order_by('letzte_bewegung'))
    else:
        # «Alle» heisst alle — ohne Fenster. Ein Jahr ist die Obergrenze,
        # damit eine versehentlich auf 2099 datierte Frist die Seite nicht
        # allein fuellt.
        vorrat = alle

    # DIE INBOX BLEIBT. Sie stand auf der alten Startseite und waere beim
    # Zusammenlegen fast verschwunden — nichts anderes rendert sie. Seit 4b.5
    # fuehrt sie nur noch die Sammelposten: die Pendenzen und Wartungsfristen
    # sind in den Arbeitsvorrat gewandert (G2, «ein Arbeitsvorrat, nicht zwei
    # Listen»), was bleibt, sind vor allem die **undatierten** Aufgaben. Genau
    # die haben sonst keinen Ort: Der Arbeitsvorrat nimmt nur, was eine Frist
    # traegt.
    from core.services.inbox import sammle_inbox
    inbox, inbox_mehr, _typen = sammle_inbox(
        aktive_lg=aktive_lg, lg_query=basis['lg_query'],
        pendenz_ziel=_pendenz_ziel)

    return render(request, 'fw/dashboard.html', {
        **basis, 'nav': 'dashboard',
        'heute': heute,
        'ansicht': ansicht,
        'ansicht_titel': dict(ANSICHTEN).get(ansicht, 'Heute'),
        'ansichten': [(k, b, k == ansicht, zaehler.get(k))
                      for k, b in ANSICHTEN],
        'vorrat': vorrat,
        'faelle': faelle,
        # Zulauf, Termine, Freigaben, Liegezeit und Vertretung — aus dem
        # Sammler. Ohne sie bliebe der eingebundene Baustein stumm: er ist da,
        # zeigt aber nichts.
        **av,
        'inbox': inbox,
        'inbox_mehr': inbox_mehr,
        # Kopfzeile nach Konzept v7 — Begruendung in `_vertretung_fuer` und in
        # der Vorlage. `isocalendar()[1]` ist die ISO-Woche: Montag als erster
        # Tag, und die Woche mit dem ersten Donnerstag ist die erste des Jahres.
        # Das ist die Zaehlung, die auf Schweizer Kalendern steht.
        **kf,
        'kw': heute.isocalendar()[1],
        'vertretung_fuer': _vertretung_fuer(request, heute),
        **lage(heute, aktive_lg),
    })


def _lauf_url(ziel_ansicht):
    """Die Adresse zu einem Laufart-Ziel — oder die Laufliste.

    `Laufart.ziel_ansicht` traegt den NAMEN einer View («fw_bankabgleich»),
    nicht ihre Adresse. Wer ihn direkt in ein `href` schreibt, erzeugt einen
    relativen Verweis, der ins Leere fuehrt.

    Ist der Name (noch) nicht verdrahtet, faellt der Verweis auf die
    Laufliste zurueck — dort ist der Lauf in jedem Fall zu finden.
    """
    from django.urls import NoReverseMatch, reverse

    if not ziel_ansicht:
        return '/neu/laeufe/'
    try:
        return reverse(ziel_ansicht)
    except NoReverseMatch:
        return '/neu/laeufe/'


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_finanzen(request):
    """Finanz-Cockpit — die Zahlen hinter den Finanzaufgaben.

    NICHT DER ARBEITSVORRAT (G2)

    Diese Seite hiess bis E2.29 «EIN Arbeitskorb statt 11 Menues einzeln
    abzuklappern». Der Nutzen stimmt — elf Listen an einem Ort —, die
    Bezeichnung nicht: «Ein Arbeitsvorrat, nicht zwei Listen» ist G2, und
    dieser Vorrat steht auf «Heute».

    Die Arbeitsteilung ist bereits umgesetzt: EINZELNE datierte Vorgaenge
    gehen in den Arbeitsvorrat, SAMMELPOSTEN («12 Rechnungen pruefen») in
    die Inbox. Die vier Eintraege hier sind Sammelposten und stehen dort
    bereits — `core/services/inbox.py` holt dieselben Aggregate.

    Wer die Seite als zweiten Arbeitskorb beschreibt, laedt genau den
    Fehler ein, vor dem das Konzept in Abschnitt 1 warnt: einen zweiten
    Posteingang, den man ebenfalls ignoriert.

    Die Reihenfolge der Abschnitte bildet den realen Buchhalter-Ablauf ab:
    Eingänge klären (Bank) → Eingangsrechnungen freigeben → Zahllauf →
    weiterverrechnen → mahnen → Perioden abschliessen (Sollstellung, MWST).
    Jede Kachel zeigt Anzahl + CHF + Direktlink auf die bestehende Funktion.
    """
    from finance.models import KreditorenRechnung, Buchungskonto, Buchung
    from core.models import Pendenz
    import calendar as _cal

    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # ---------- Debitoren (offene Forderungen) ----------
    deb = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
    if aktive_lg:
        deb = deb.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    deb = [r for r in deb.select_related('vertrag').prefetch_related('zahlungseingaenge') if r.offener_betrag > 0]
    deb_offen_chf = sum((r.offener_betrag for r in deb), Decimal('0.00'))
    deb_ueberf = [r for r in deb if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute]
    deb_ueberf_chf = sum((r.offener_betrag for r in deb_ueberf), Decimal('0.00'))

    # ---------- Kreditoren (Eingangsrechnungen) ----------
    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)
    kred = list(kred.prefetch_related('zahlungen', 'weiterverrechnungen'))
    zur_freigabe = [k for k in kred if k.status == 'neu']
    zur_zahlung = [k for k in kred if k.status in ('freigegeben', 'teilbezahlt') and k.offener_betrag > 0]
    in_zahlung = [k for k in kred if k.status == 'in_zahlung']
    # Weiterverrechnung: nur *angefangene* (bereits teilweise weiterverrechnete) Rechnungen
    # als Todo führen — sonst würde jede Lieferantenrechnung fälschlich als "zu
    # verrechnen" markiert (Weiterverrechnung ist ein bewusster Einzelentscheid).
    offen_wv = [k for k in kred if k.weiterverrechnet_betrag > 0 and k.offen_weiterzuverrechnen > 0]

    def _chf(items, attr='offener_betrag'):
        return sum((getattr(k, attr) or Decimal('0.00') for k in items), Decimal('0.00'))

    # ---------- Kaution-Freigabefristen (fällige Pendenzen) ----------
    kaut = Pendenz.objects.filter(erledigt=False, quelle__startswith='auto:kautionfreigabe:')
    if aktive_lg:
        kaut = kaut.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    kaut_faellig = kaut.filter(faellig_am__lte=heute).count()
    kaut_offen = kaut.count()

    # ---------- Durchlaufkonto 1190: ungeklärte/geparkte Positionen ----------
    durchlauf_saldo = Decimal('0.00')
    k1190 = Buchungskonto.objects.filter(nummer='1190').first()
    if k1190:
        bq = Buchung.objects.all()
        if aktive_lg:
            bq = bq.filter(liegenschaft=aktive_lg)
        soll = bq.filter(soll_konto=k1190).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        haben = bq.filter(haben_konto=k1190).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        durchlauf_saldo = soll - haben

    # ---------- Arbeitskorb (Reihenfolge = Prozess) ----------
    # Volle Tailwind-Klassen (CDN-sicher, keine dynamisch zusammengesetzten Namen).
    P = {
        'sky':    ('fw-info-flaeche fw-info',       'fw-info-voll hover:fw-info-voll'),
        'amber':  ('fw-warn-flaeche fw-warnton',   'fw-warn-voll hover:fw-warn-voll'),
        'indigo': ('fw-markenflaeche fw-marke', 'fw-btn fw-primary'),
        'violet': ('fw-info-flaeche fw-info', 'fw-btn fw-primary'),
        'rose':   ('fw-krit-flaeche fw-kritisch',     'fw-btn fw-gefahr'),
        'teal':   ('fw-markenflaeche fw-marke',     'fw-btn fw-primary'),
    }
    _korb = [
        # gewandert in den Periodenabschluss (E2.30, Plan: «Handlungen springen in den zugehörigen Lauf»)
        ('freigabe', 'freigeben', 'amber', 'Eingangsrechnungen freigeben',
         'Neu erfasste Kreditoren prüfen & freigeben',
         len(zur_freigabe), _chf(zur_freigabe, 'betrag'), '/neu/kreditoren/', 'Freigeben', False),
        # DER ZAHLLAUF STEHT NICHT MEHR HIER.
        #
        # Er ist ein LAUF (`laeufe_planen` legt ihn als `zahllauf` an,
        # monatlich, Stichtag 25.) und stand damit zweimal auf DERSELBEN
        # Seite: als Aufgabe im Korb und als Zeile im Periodenabschluss
        # darunter. Dazu ein drittes Mal auf «Heute» aus derselben Quelle.
        #
        # 4b.5 hat für denselben Fall die Regel gesetzt: Die Blöcke WANDERN,
        # sie werden nicht kopiert. Der Korb behält die Handlungen, die keine
        # Läufe sind (freigeben, weiterverrechnen, Kautionen); die Läufe
        # stehen im Periodenabschluss und im Bereich «Läufe».
        ('weiterverrechnung', 'weiterverrechnen', 'violet', 'Weiterverrechnungen abschliessen',
         'Angefangene Weiterverrechnungen an Mieter fertigstellen',
         len(offen_wv), _chf(offen_wv, 'offen_weiterzuverrechnen'), '/neu/kreditoren/', 'Weiterverrechnen', False),
        # gewandert in den Periodenabschluss (E2.30, Plan: «Handlungen springen in den zugehörigen Lauf»)
        ('kaution', 'gesperrt', 'teal', 'Kautionen freigeben',
         'Rückzahlungsfristen nach Auszug (Art. 257e)',
         kaut_offen, None, '/neu/kautionen/', 'Kautionen', kaut_faellig > 0),
    ]
    arbeitskorb = [{
        'key': k, 'icon': ic, 'icon_cls': P[f][0], 'btn_cls': P[f][1],
        'titel': t, 'sub': s, 'anzahl': n, 'chf': c,
        'url': u + basis['lg_query'], 'cta': cta, 'dringend': d,
    } for (k, ic, f, t, s, n, c, u, cta, d) in _korb]
    offene_posten = sum(1 for i in arbeitskorb if i['anzahl'])
    # `dringend_n` wird ERST NACH der Checkliste berechnet — sie entsteht
    # weiter unten. Ein erster Entwurf zaehlte hier und traf eine leere Liste:
    # Die Zahl im Kopf haette die dringenden Laeufe verschwiegen.
    dringend_korb = sum(1 for i in arbeitskorb if i['dringend'])

    # ---------- Periodenabschluss: die Läufe selbst ----------
    #
    # G7 — REGELN STATT LISTEN, ALS DATEN STATT ALS CODE
    #
    # Bis E2.29 stand hier eine Checkliste, die den Zustand ERRIET:
    # `DebitorenRechnung.objects.filter(titel=f"Miete & NK {m:02d}/{j}")` —
    # eine Regel als Zeichenkette. Sie konnte nur «gibt es solche Rechnungen?»
    # beantworten, nicht «ist der Lauf abgeschlossen, von wem, und was
    # blockiert ihn».
    #
    # `faelle.Lauf` trägt genau das: Status, `abgeschlossen_am`,
    # `abgeschlossen_durch`, den Rhythmus (monatlich/quartalsweise/jährlich)
    # und BLOCKADEN MIT GRUND. Das ist G7s eigentlicher Punkt: Die alte Ampel
    # zeigte ein rotes Häkchen, der Lauf zeigt «Verbrauchsablesung Techem
    # fehlt» — das eine führt zu einer Rückfrage, das andere zu einer
    # Handlung.
    #
    # DER RHYTHMUS WAR MITGEMESSEN FALSCH: Die MWST-Zeile stand monatlich in
    # der Liste, obwohl sie quartalsweise fällig ist. Ein Abschluss, der
    # jeden Monat «noch offen» meldet, wird nach zwei Monaten ignoriert.
    #
    # Angelegt werden die Laufarten von `manage.py laeufe_planen`
    # (6 Standardarten). Ohne sie bleibt der Abschnitt leer — und das ist
    # richtig so: Eine leere Liste ist ehrlicher als eine erratene.
    from faelle.lauf_models import Lauf

    # `faellig_am`, nicht `periode_bis` — nachgesehen, nicht geraten. Ein
    # erster Entwurf nahm ein Feld an, das es nicht gibt; `periode` ist ein
    # Textfeld («2026-08»), das Datum steht in `faellig_am`.
    #
    # Gezeigt werden die Laeufe, deren Stichtag erreicht ist — der Abschluss
    # einer Periode ist erst dann eine Aufgabe.
    laeufe_qs = (Lauf.objects.filter(faellig_am__lte=heute)
                 .select_related('laufart')
                 .order_by('laufart__reihenfolge', '-faellig_am')[:8])

    # WAS OFFEN IST, GEHOERT AN DEN LAUF (E2.30)
    #
    # Der Plan zur Zeile «Finanzen»: «Register und Konten. HANDLUNGEN
    # (abgleichen, mahnen, zahlen) SPRINGEN IN DEN ZUGEHOERIGEN LAUF.»
    #
    # E2.29 hat das fuer den Zahllauf getan, aber nur fuer ihn: Der Test
    # verglich BEZEICHNUNGEN, und «Zahllauf» stand in beiden Texten. Bank und
    # Mahnwesen fielen nicht auf, weil sie verschieden heissen — dabei zeigten
    # sie auf DASSELBE ZIEL, was die haertere Doppelung ist.
    #
    # Beim Wandern droht ein Verlust: Der Korb zeigte Anzahl und CHF-Summe,
    # der Abschluss nur Status und Blockade. `Lauf.kennzahlen` traegt sie
    # zwar, aber erst `abschliessen()` fuellt sie — vorher stehen sie nicht
    # zur Verfuegung.
    #
    # Deshalb rechnet die Ansicht sie hier aus, wo die Zahlen ohnehin schon
    # stehen. Sie gehen also nicht verloren; sie stehen nur nicht mehr an
    # zwei Orten.
    OFFENE_ZAHLEN = {
        'bankabgleich': (len(deb), deb_offen_chf),
        'mahnlauf': (len(deb_ueberf), deb_ueberf_chf),
        'zahllauf': (len(zur_zahlung), _chf(zur_zahlung)),
    }

    checkliste = []
    for lauf in laeufe_qs:
        blockaden = list(lauf.offene_blockaden)
        anzahl, summe = OFFENE_ZAHLEN.get(lauf.laufart.schluessel, (None, None))
        checkliste.append({
            'titel': f'{lauf.laufart.bezeichnung} {lauf.periode}',
            'ok': lauf.status == Lauf.ABGESCHLOSSEN,
            # `ziel_ansicht` ist ein VIEW-NAME, keine Adresse — das Feld
            # sagt es selbst: «Name der bestehenden View, die den Lauf
            # tatsaechlich ausfuehrt». Ohne `reverse()` stand
            # `href="fw_bankabgleich"` im HTML; der Browser loest das relativ
            # auf und landet auf `/neu/fw_bankabgleich` — ein 404 auf JEDER
            # Zeile des Abschlusses.
            #
            # Gefunden wurde das nicht vom Test, sondern beim Nachsehen, was
            # in der Zeile wirklich steht. Ein Verweis, der ins Leere zeigt,
            # sieht im HTML aus wie einer, der funktioniert.
            'url': _lauf_url(lauf.laufart.ziel_ansicht) + basis['lg_query'],
            'anzahl': anzahl, 'chf': summe,
            # DRINGEND hing bis E2.30 an den Korb-Eintraegen. Mit ihnen waere
            # die Aussage verlorengegangen — dabei ist sie am Lauf besser
            # aufgehoben: Dringend ist, was den Stichtag ueberschritten hat
            # oder blockiert ist. Das ist eine Tatsache aus den Daten, nicht
            # eine Einschaetzung im Code.
            'dringend': (lauf.status != Lauf.ABGESCHLOSSEN
                         and (bool(blockaden) or lauf.faellig_am < heute)),
            'hinweis': (', '.join(b.grund for b in blockaden) if blockaden
                        else (f'abgeschlossen am '
                              f'{lauf.abgeschlossen_am:%d.%m.%Y}'
                              if lauf.abgeschlossen_am
                              else f'Stichtag {lauf.faellig_am:%d.%m.%Y}')),
        })

    erledigt_n = sum(1 for c in checkliste if c['ok'] is True)
    pflicht_n = sum(1 for c in checkliste if c['ok'] is not None)

    # OFFEN UND DRINGEND ZAEHLEN BEIDE QUELLEN.
    #
    # Ein erster Entwurf zaehlte `offene_posten` weiter nur ueber den Korb.
    # Im Browser sah man sofort, was das anrichtet: «0 offene Aufgaben ·
    # 3 dringend» im Kopf und «Alle Finanzaufgaben erledigt» darunter,
    # waehrend rechts drei ueberfaellige Laeufe standen.
    #
    # Ein Widerspruch auf einem Bildschirm ist genau das, was B3 der Analyse
    # meint: «Ein 10k-Werkzeug darf sich nicht widersprechen.»
    offene_laeufe = sum(1 for c in checkliste if c['ok'] is not True)
    offene_posten = offene_posten + offene_laeufe
    dringend_n = dringend_korb + sum(1 for c in checkliste if c.get('dringend'))

    return render(request, 'fw/finanzen.html', {
        **basis, 'nav': 'finanzen',
        'arbeitskorb': arbeitskorb,
        'offene_posten': offene_posten, 'dringend_n': dringend_n,
        'deb_offen_chf': deb_offen_chf, 'deb_ueberf_chf': deb_ueberf_chf,
        'kred_zahllauf_chf': _chf(zur_zahlung), 'in_zahlung_n': len(in_zahlung),
        'durchlauf_saldo': durchlauf_saldo,
        'checkliste': checkliste, 'erledigt_n': erledigt_n, 'pflicht_n': pflicht_n,
        'heute': heute,
    })
