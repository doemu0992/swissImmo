# core/views/fw/buchhaltung.py
#
# Erfolgsrechnung, Kontenplan, Kontoblatt, Journal-Export und PDF.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# `_erfolg_bilanz` bleibt hier und wird von core/services/abschluss_pdf.py
# ueber core.views.fw bezogen -- das __init__.py reicht den Namen weiter,
# FwFassadeTests haelt fest, dass er erreichbar bleibt.

import logging
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from portfolio.models import Liegenschaft

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num


# ============================================================
# ETAPPE D: BUCHHALTUNG (Erfolgsrechnung + Journal)
# ============================================================

def _ist_abgeschlossen(jahr, liegenschaft=None):
    from core.services.jahresabschluss import ist_abgeschlossen
    return ist_abgeschlossen(jahr, liegenschaft)


def _erfolg_bilanz(aktive_lg, jahr):
    """Erfolgsrechnung + Bilanz für ein Geschäftsjahr (oder 'alle').

    Ausgelagert, weil die Seite /neu/buchhaltung/ UND ihr PDF-Abzug exakt
    dieselben Zahlen zeigen müssen. Zwei Kopien dieser Rechnung würden
    auseinanderdriften — und ein Abschluss, der je nach Ausgabeweg anders
    aussieht, ist wertlos.
    """
    from finance.models import Buchung, Buchungskonto
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    if jahr != 'alle':
        qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))

    # --- ZWEI SICHTEN (korrekte Rechnungslegung) ---
    # Erfolgsrechnung = NUR die Periode (Ertrags-/Aufwandskonten werden jährlich
    #   abgeschlossen → year-scoped qs).
    # Bilanz = KUMULATIV bis Jahresende (Bilanzkonten tragen Eröffnungssalden über;
    #   ohne Kumulation wäre die Jahresbilanz falsch). Das kumulierte Jahres-/
    #   Vortragsergebnis fliesst ins Eigenkapital, damit die Bilanz aufgeht.
    konten = Buchungskonto.objects.all()
    bilanz_qs = Buchung.objects.all()
    if aktive_lg:
        bilanz_qs = bilanz_qs.filter(liegenschaft=aktive_lg)
    if jahr != 'alle':
        bilanz_qs = bilanz_qs.filter(datum__lte=date(jahr, 12, 31))

    # Abschlussbuchungen aus der ERFOLGSRECHNUNG ausklammern — sie saldieren die
    # Erfolgskonten per 31.12. gegen 2970. Ohne diesen Ausschluss zeigte die
    # Erfolgsrechnung nach dem Jahresabschluss überall null, obwohl das Jahr
    # gelaufen ist (Audit). Die Bilanz braucht sie dagegen, weil erst sie das
    # Ergebnis auf 2970 stellt — bilanz_qs bleibt deshalb unangetastet.
    from core.services.jahresabschluss import abschluss_buchungen_q
    qs_periode_inkl = qs                       # Periode MIT Abschlussbuchungen (offener Erfolg)
    qs = qs.exclude(abschluss_buchungen_q())   # Periode OHNE Abschluss (Erfolgsrechnung/P&L)

    # Salden in VIER Abfragen statt zwei je Konto. Die Buchhaltungsseite lief
    # über den Kontenplan und fragte je Konto Soll und Haben einzeln ab —
    # gemessen 90 Abfragen für einen Seitenaufbau, und dieselbe Rechnung steckt
    # im PDF-Abzug. Gruppiert liefert die Datenbank dasselbe in einem Durchgang.
    def _salden(basis_qs):
        soll = {kid: betrag for kid, betrag in
                basis_qs.values_list('soll_konto').annotate(t=Sum('betrag'))}
        haben = {kid: betrag for kid, betrag in
                 basis_qs.values_list('haben_konto').annotate(t=Sum('betrag'))}
        return soll, haben

    p_soll, p_haben = _salden(qs)                        # Periode (Erfolgsrechnung, ohne Abschluss)
    k_soll, k_haben = _salden(bilanz_qs)                 # kumulativ bis Jahresende (Bilanz)
    pi_soll, pi_haben = _salden(qs_periode_inkl)         # Periode MIT Abschluss (offener Erfolg)
    _0 = Decimal('0.00')

    ertraege, aufwaende = [], []
    aktiven, passiven = [], []
    total_ertrag = total_aufwand = Decimal('0.00')
    total_aktiven = total_passiven = Decimal('0.00')
    kum_erfolg = Decimal('0.00')   # kumuliertes Ergebnis bis Jahresende (Eigenkapital)
    for k in konten:
        if k.typ == 'ertrag':
            soll = p_soll.get(k.id) or _0
            haben = p_haben.get(k.id) or _0
            saldo = haben - soll
            if saldo:
                ertraege.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_ertrag += saldo
        elif k.typ == 'aufwand':
            soll = p_soll.get(k.id) or _0
            haben = p_haben.get(k.id) or _0
            saldo = soll - haben
            if saldo:
                aufwaende.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aufwand += saldo
        else:  # bilanz / aktiv / passiv — kumulativ bis Jahresende
            soll = k_soll.get(k.id) or _0
            haben = k_haben.get(k.id) or _0
            saldo = soll - haben  # Sollsaldo: >0 tendenziell Aktivum, <0 Passivum
            if saldo == 0:
                continue
            if k.typ == 'aktiv':
                # Immer Aktivseite (Soll−Haben) — auch bei negativem Saldo sichtbar.
                aktiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aktiven += saldo
            elif k.typ == 'passiv':
                # Immer Passivseite (Haben−Soll). Ein Soll-Saldo (z.B. Ausschüttung
                # via Kontokorrent) MINDERT das Eigenkapital → negative Passivzeile.
                passiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': -saldo})
                total_passiven += -saldo
            elif saldo > 0:
                aktiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aktiven += saldo
            else:
                passiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': -saldo})
                total_passiven += -saldo
    # Kumuliertes NICHT-abgeschlossenes Ergebnis (alle Erfolgskonten bis Jahresende,
    # INKL. Abschlussbuchungen). Nach dem Jahresabschluss stehen die Erfolgskonten
    # auf null (gegen 2970 saldiert) → kum_erfolg = 0, und das Ergebnis steckt
    # bereits in der Passivzeile 2970. Vor dem Abschluss trägt kum_erfolg das noch
    # offene kumulierte Ergebnis, das die Bilanz ausgleicht.
    for k in konten:
        if k.typ == 'ertrag':
            kum_erfolg += (k_haben.get(k.id) or _0) - (k_soll.get(k.id) or _0)
        elif k.typ == 'aufwand':
            kum_erfolg -= (k_soll.get(k.id) or _0) - (k_haben.get(k.id) or _0)
    # Offener Erfolg DER PERIODE = Erfolgskontensaldo dieses Jahres INKL. Abschluss.
    # Ist das Jahr abgeschlossen, saldieren die Abschlussbuchungen dieses Jahr auf
    # null → erfolg_offen = 0 (die Zeile «Jahresgewinn» verschwindet, das Ergebnis
    # ist in 2970 gebucht). Vorher = erfolg (volles Periodenergebnis). So wird das
    # Ergebnis nach dem Abschluss NICHT doppelt gezeigt und es entsteht kein
    # erfundener «Ergebnisvortrag» in Höhe von −erfolg (Audit-Befund H5).
    erfolg_offen = _0
    for k in konten:
        if k.typ == 'ertrag':
            erfolg_offen += (pi_haben.get(k.id) or _0) - (pi_soll.get(k.id) or _0)
        elif k.typ == 'aufwand':
            erfolg_offen -= (pi_soll.get(k.id) or _0) - (pi_haben.get(k.id) or _0)
    for lst in (ertraege, aufwaende, aktiven, passiven):
        lst.sort(key=lambda x: x['nummer'])
    erfolg = total_ertrag - total_aufwand          # Ergebnis der Periode (Erfolgsrechnung/P&L)
    # Bilanz-Ausgleich: noch offenes kumuliertes Ergebnis ins Eigenkapital
    passiven_mit_erfolg = total_passiven + kum_erfolg
    bilanz_differenz = total_aktiven - passiven_mit_erfolg
    # Ergebnisvortrag = offenes kumuliertes Ergebnis MINUS offener Periodenerfolg
    # = noch offenes Ergebnis aus Vorjahren. Nach Abschluss beider = 0.
    erfolg_vortrag = kum_erfolg - erfolg_offen
    return {
        'ertraege': ertraege, 'aufwaende': aufwaende,
        'total_ertrag': total_ertrag, 'total_aufwand': total_aufwand, 'erfolg': erfolg,
        'aktiven': aktiven, 'passiven': passiven,
        'total_aktiven': total_aktiven, 'total_passiven': total_passiven,
        'passiven_mit_erfolg': passiven_mit_erfolg, 'bilanz_differenz': bilanz_differenz,
        'kum_erfolg': kum_erfolg, 'erfolg_vortrag': erfolg_vortrag, 'erfolg_offen': erfolg_offen,
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung(request):
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    # --- Jahresabschluss buchen (Erfolgskonten an 2970) — Audit W4 ---
    if request.method == 'POST' and request.POST.get('aktion') == 'jahresabschluss':
        from django.shortcuts import redirect
        from django.contrib import messages
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        from core.auth import log_aktion, hat_rolle
        # Die Seite selbst ist für alle Team-Rollen lesbar (Treuhand/Revision
        # muss die Buchhaltung ansehen können). Der Abschluss ist etwas
        # anderes: ein Buchungslauf, der die Periode versiegelt. Laut
        # Rollenkonzept gehört er allein der Verwaltung.
        if not hat_rolle(request.user, VERWALTUNGS_ROLLEN):
            messages.error(request, "❌ Den Jahresabschluss darf nur die Verwaltung buchen.")
            return redirect(f'/neu/buchhaltung/?jahr={heute.year}')
        try:
            j_ab = int(request.POST.get('jahr') or heute.year)
        except ValueError:
            j_ab = heute.year
        if not (2000 <= j_ab <= 2100):
            messages.error(request, "Ungültiges Geschäftsjahr.")
            return redirect(f'/neu/buchhaltung/?jahr={heute.year}')
        if ist_abgeschlossen(j_ab, aktive_lg):
            messages.info(request, f"Das Geschäftsjahr {j_ab} ist bereits abgeschlossen.")
            return redirect(f'/neu/buchhaltung/?jahr={j_ab}')
        try:
            n_ab, erg = buche_jahresabschluss(j_ab, liegenschaft=aktive_lg, user=request.user)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(f'/neu/buchhaltung/?jahr={j_ab}')
        except Exception as exc:
            messages.error(request, f"❌ Jahresabschluss fehlgeschlagen: {exc}")
            return redirect(f'/neu/buchhaltung/?jahr={j_ab}')
        log_aktion(request, "Jahresabschluss gebucht", str(j_ab),
                   f"{n_ab} Konten, Ergebnis CHF {erg}")
        gesperrt_hinweis = ""
        if n_ab and not aktive_lg:
            # Periode versiegeln: Ohne Sperre liessen sich nach dem Abschluss
            # weiter Erfolgsbuchungen ins geschlossene Jahr schreiben, die nie
            # mehr saldiert würden — Bilanz und Erfolgsrechnung liefen
            # auseinander (Audit). Nur beim portfolioweiten Abschluss, ein
            # Einzelabschluss sperrt die übrigen Liegenschaften nicht mit.
            from crm.models import Organisation
            vw_sperre = Organisation.objects.first()
            if vw_sperre is not None:
                stichtag = date(j_ab, 12, 31)
                if not vw_sperre.buchung_gesperrt_bis or vw_sperre.buchung_gesperrt_bis < stichtag:
                    vw_sperre.buchung_gesperrt_bis = stichtag
                    vw_sperre.save(update_fields=['buchung_gesperrt_bis'])
                    gesperrt_hinweis = (f" Die Periode bis 31.12.{j_ab} ist jetzt für "
                                        f"Buchungen gesperrt.")
        if n_ab:
            art = "Gewinn" if erg >= 0 else "Verlust"
            messages.success(request, f"✅ Jahresabschluss {j_ab} gebucht: {n_ab} Erfolgskonto/-konten "
                                      f"gegen 2970 saldiert · {art} CHF {abs(erg)}.{gesperrt_hinweis}")
        else:
            messages.info(request, f"Jahr {j_ab}: keine Erfolgsbuchungen zum Abschliessen.")
        return redirect(f'/neu/buchhaltung/?jahr={j_ab}')

    # --- Jahresabschluss ZURÜCKNEHMEN (alle Abschlussbuchungen stornieren) — H6 ---
    if request.method == 'POST' and request.POST.get('aktion') == 'abschluss_zuruecknehmen':
        from django.shortcuts import redirect
        from django.contrib import messages
        from core.services.jahresabschluss import nimm_zurueck, ist_abgeschlossen
        from core.auth import log_aktion, hat_rolle
        if not hat_rolle(request.user, VERWALTUNGS_ROLLEN):
            messages.error(request, "❌ Den Jahresabschluss darf nur die Verwaltung zurücknehmen.")
            return redirect(f'/neu/buchhaltung/?jahr={heute.year}')
        try:
            j_zr = int(request.POST.get('jahr') or heute.year)
        except ValueError:
            j_zr = heute.year
        if not (2000 <= j_zr <= 2100):
            messages.error(request, "Ungültiges Geschäftsjahr.")
            return redirect(f'/neu/buchhaltung/?jahr={heute.year}')
        if not ist_abgeschlossen(j_zr, aktive_lg):
            messages.info(request, f"Das Geschäftsjahr {j_zr} ist nicht abgeschlossen.")
            return redirect(f'/neu/buchhaltung/?jahr={j_zr}')
        # Periodensperre ZUERST lösen, sofern sie genau auf diesem Abschluss-Stichtag
        # sass (portfolioweiter Abschluss). Die Rücknahme bucht die Storni auf den
        # 31.12. des Jahres zurück — mit stehender Sperre würde Buchung.save() das
        # blockieren. Nur beim portfolioweiten Abschluss (aktive_lg=None) wurde
        # überhaupt gesperrt.
        entsperrt = ""
        if not aktive_lg:
            from crm.models import Organisation
            vw_e = Organisation.objects.first()
            if vw_e is not None and vw_e.buchung_gesperrt_bis == date(j_zr, 12, 31):
                vw_e.buchung_gesperrt_bis = date(j_zr - 1, 12, 31) if j_zr > 2000 else None
                vw_e.save(update_fields=['buchung_gesperrt_bis'])
                entsperrt = f" Die Periodensperre bis 31.12.{j_zr} wurde aufgehoben."
        try:
            n_zr = nimm_zurueck(j_zr, liegenschaft=aktive_lg, user=request.user)
        except Exception as exc:
            messages.error(request, f"❌ Rücknahme fehlgeschlagen: {exc}")
            return redirect(f'/neu/buchhaltung/?jahr={j_zr}')
        log_aktion(request, "Jahresabschluss zurückgenommen", str(j_zr), f"{n_zr} Buchungen storniert")
        if n_zr:
            messages.success(request, f"✅ Jahresabschluss {j_zr} zurückgenommen: "
                                      f"{n_zr} Abschlussbuchung(en) storniert.{entsperrt}")
        else:
            messages.info(request, f"Jahr {j_zr}: keine Abschlussbuchungen zum Zurücknehmen.")
        return redirect(f'/neu/buchhaltung/?jahr={j_zr}')

    # --- Jahresfilter (Jahresabschluss) ---
    jahr_param = request.GET.get('jahr', str(heute.year))
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    if jahr_param and jahr_param != 'alle':
        try:
            jahr = int(jahr_param)
            qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
        except ValueError:
            jahr = heute.year
    else:
        jahr = 'alle'

    # Erfolgsrechnung + Bilanz kommen aus EINER Quelle (siehe _erfolg_bilanz) —
    # die Seite und ihr PDF-Abzug dürfen nie unterschiedliche Zahlen zeigen.
    _eb = _erfolg_bilanz(aktive_lg, jahr)
    ertraege = _eb['ertraege']; aufwaende = _eb['aufwaende']
    total_ertrag = _eb['total_ertrag']; total_aufwand = _eb['total_aufwand']
    erfolg = _eb['erfolg']
    aktiven = _eb['aktiven']; passiven = _eb['passiven']
    total_aktiven = _eb['total_aktiven']; total_passiven = _eb['total_passiven']
    passiven_mit_erfolg = _eb['passiven_mit_erfolg']
    bilanz_differenz = _eb['bilanz_differenz']
    kum_erfolg = _eb['kum_erfolg']; erfolg_vortrag = _eb['erfolg_vortrag']
    erfolg_offen = _eb['erfolg_offen']

    # --- BUCHUNGSJOURNAL (durchsuch- und filterbar, seitenweise) ---
    # Vorher: hart die letzten 60 Zeilen, ohne Suche und ohne Filter. Damit war
    # der Alltag eines Buchhalters — einen Beleg wiederfinden, einen Monat
    # durchsehen, ein Konto kontrollieren — schlicht nicht möglich (Audit).
    # Die Abschlussbuchungen sind hier bewusst wieder drin: im JOURNAL müssen
    # sie sichtbar sein, nur aus der Erfolgsrechnung sind sie ausgeklammert.
    from django.db.models import Q as _QJ
    j_qs = Buchung.objects.all()
    if aktive_lg:
        j_qs = j_qs.filter(liegenschaft=aktive_lg)
    j_von = (request.GET.get('von') or '').strip()
    j_bis = (request.GET.get('bis') or '').strip()
    j_konto = (request.GET.get('konto') or '').strip()
    j_suche = (request.GET.get('q') or '').strip()
    if j_von:
        try:
            j_qs = j_qs.filter(datum__gte=date.fromisoformat(j_von))
        except ValueError:
            j_von = ''
    if j_bis:
        try:
            j_qs = j_qs.filter(datum__lte=date.fromisoformat(j_bis))
        except ValueError:
            j_bis = ''
    if not (j_von or j_bis) and jahr != 'alle':
        # Ohne eigene Datumswahl gilt der Jahresfilter der Seite.
        j_qs = j_qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
    if j_konto:
        j_qs = j_qs.filter(_QJ(soll_konto__nummer=j_konto) | _QJ(haben_konto__nummer=j_konto))
    if j_suche:
        # Belegtext ODER Beleg-Nr. Letztere ist numerisch — nur wenn die Eingabe
        # eine Zahl ist (auch mit führendem #), wird sie als Nummer gesucht.
        such_q = _QJ(beleg_text__icontains=j_suche)
        _nr = j_suche.lstrip('#').strip()
        if _nr.isdigit():
            such_q = such_q | _QJ(beleg_nr=int(_nr))
        j_qs = j_qs.filter(such_q)
    j_qs = j_qs.select_related('soll_konto', 'haben_konto', 'liegenschaft').order_by('-datum', '-id')
    j_total = j_qs.count()
    j_summe = j_qs.aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
    try:
        j_seite = max(1, int(request.GET.get('seite') or 1))
    except ValueError:
        j_seite = 1
    J_PRO_SEITE = 100
    j_seiten = max(1, (j_total + J_PRO_SEITE - 1) // J_PRO_SEITE)
    j_seite = min(j_seite, j_seiten)
    journal = j_qs[(j_seite - 1) * J_PRO_SEITE: j_seite * J_PRO_SEITE]
    # Filter beim Blättern erhalten (ohne `seite`, die wird pro Link gesetzt).
    j_query = '&'.join(
        f"{k}={v}" for k, v in (('von', j_von), ('bis', j_bis), ('konto', j_konto), ('q', j_suche))
        if v)

    tab_liste = [
        ('erfolg', 'Erfolgsrechnung', None),
        ('bilanz', 'Bilanz', None),
        ('journal', 'Journal', j_total or None),
    ]

    # Werte des zuletzt erfassten Belegs (Serienerfassung)
    _letzt = request.session.get('bu_letzt') or {}
    _letzt_datum = None
    if _letzt.get('datum'):
        try:
            _letzt_datum = date.fromisoformat(_letzt['datum'])
        except ValueError:
            _letzt_datum = None
    return render(request, 'fw/buchhaltung.html', {
        **basis, 'nav': 'buchhaltung',
        'ertraege': ertraege, 'aufwaende': aufwaende,
        'total_ertrag': total_ertrag, 'total_aufwand': total_aufwand, 'erfolg': erfolg,
        'aktiven': aktiven, 'passiven': passiven,
        'total_aktiven': total_aktiven, 'total_passiven': total_passiven,
        'passiven_mit_erfolg': passiven_mit_erfolg, 'bilanz_differenz': bilanz_differenz,
        'kum_erfolg': kum_erfolg, 'erfolg_vortrag': erfolg_vortrag, 'erfolg_offen': erfolg_offen,
        'journal': journal,
        'j_total': j_total, 'j_summe': j_summe, 'j_seite': j_seite, 'j_seiten': j_seiten,
        'j_von': j_von, 'j_bis': j_bis, 'j_konto': j_konto, 'j_suche': j_suche,
        'j_query': j_query,
        'tab_liste': tab_liste,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
        'alle_konten': Buchungskonto.objects.all().order_by('nummer'),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        # Vorbelegung der Erfassungsmaske aus dem letzten Beleg (Serienerfassung).
        'serienerfassung': bool(request.session.pop('bu_serie', False)),
        'letztes_datum': _letzt_datum, 'letztes_soll': _letzt.get('soll', ''),
        'letztes_haben': _letzt.get('haben', ''), 'letzte_lg_id': _letzt.get('lg'),
        'jahr_abgeschlossen': (_ist_abgeschlossen(jahr, aktive_lg)
                               if isinstance(jahr, int) else False),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kontenplan(request):
    """Kontenplan mit SALDENLISTE und Pflege der Konten.

    Zwei Lücken auf einmal (Audit): Es gab weder eine Saldenliste — das Werkzeug,
    mit dem ein Buchhalter jeden Abschluss beginnt — noch eine Möglichkeit, im
    neuen UI ein Konto anzulegen oder umzubenennen. Der Hinweis in der
    Buchungsmaske verwies auf einen «Kontenplan-Tab», den es nicht gab; der
    Kontenrahmen war faktisch eine Python-Liste.

    Anders als Bilanz und Erfolgsrechnung blendet die Saldenliste Konten mit
    Saldo 0 NICHT aus — sonst sind bebuchte, aber ausgeglichene Konten (z.B. ein
    geleertes Durchlaufkonto) im ganzen UI unerreichbar.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.db.models import Sum
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion, hat_rolle, VERWALTUNGS_ROLLEN

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    kann_schreiben = hat_rolle(request.user, VERWALTUNGS_ROLLEN)

    if request.method == 'POST' and kann_schreiben:
        aktion = request.POST.get('aktion')
        nr = (request.POST.get('nummer') or '').strip()
        bez = (request.POST.get('bezeichnung') or '').strip()
        typ = request.POST.get('typ') or 'bilanz'
        if aktion == 'neu':
            if not nr or not bez:
                messages.error(request, "Nummer und Bezeichnung sind Pflicht.")
            elif Buchungskonto.objects.filter(nummer=nr).exists():
                messages.error(request, f"Konto {nr} existiert bereits.")
            elif typ not in ('aufwand', 'ertrag', 'bilanz', 'aktiv', 'passiv'):
                messages.error(request, "Ungültiger Kontotyp.")
            else:
                Buchungskonto.objects.create(
                    nummer=nr, bezeichnung=bez, typ=typ,
                    is_hnk_relevant=(request.POST.get('hnk') == 'on'),
                    standard_verteilschluessel=(request.POST.get('schluessel') or 'm2'))
                log_aktion(request, "Konto angelegt", f"{nr} {bez}", typ)
                messages.success(request, f"✅ Konto {nr} «{bez}» angelegt.")
        elif aktion == 'bearbeiten':
            k = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first()
            if not k:
                messages.error(request, "Konto nicht gefunden.")
            else:
                # Die NUMMER bleibt unveränderlich: sie steckt in Belegtexten,
                # Exporten und im Buchungscode. Umbenennen ja, umnummerieren nein.
                k.bezeichnung = bez or k.bezeichnung
                if typ in ('aufwand', 'ertrag', 'bilanz', 'aktiv', 'passiv'):
                    k.typ = typ
                k.is_hnk_relevant = (request.POST.get('hnk') == 'on')
                if request.POST.get('schluessel'):
                    k.standard_verteilschluessel = request.POST['schluessel']
                k.save()
                log_aktion(request, "Konto geändert", f"{k.nummer} {k.bezeichnung}", k.typ)
                messages.success(request, f"✅ Konto {k.nummer} aktualisiert.")
        return redirect(f'/neu/kontenplan/{basis["lg_query"]}')

    # --- Saldenliste ---
    jahr_param = request.GET.get('jahr', str(heute.year))
    try:
        jahr = int(jahr_param)
    except ValueError:
        jahr = heute.year
    bqs = Buchung.objects.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
    if aktive_lg:
        bqs = bqs.filter(liegenschaft=aktive_lg)
    soll_map = {r['soll_konto']: r['t'] for r in
                bqs.values('soll_konto').annotate(t=Sum('betrag'))}
    haben_map = {r['haben_konto']: r['t'] for r in
                 bqs.values('haben_konto').annotate(t=Sum('betrag'))}

    zeilen, t_soll, t_haben = [], Decimal('0.00'), Decimal('0.00')
    for k in Buchungskonto.objects.all().order_by('nummer'):
        s = soll_map.get(k.id) or Decimal('0.00')
        h = haben_map.get(k.id) or Decimal('0.00')
        zeilen.append({'k': k, 'soll': s, 'haben': h, 'saldo': s - h,
                       'bewegt': bool(s or h)})
        t_soll += s
        t_haben += h

    return render(request, 'fw/kontenplan.html', {
        **basis, 'nav': 'buchhaltung', 'zeilen': zeilen,
        'total_soll': t_soll, 'total_haben': t_haben,
        'differenz': t_soll - t_haben,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
        'kann_schreiben': kann_schreiben,
        'typen': [('bilanz', 'Bilanz'), ('aktiv', 'Aktivum'), ('passiv', 'Passivum / Eigenkapital'),
                  ('aufwand', 'Aufwand'), ('ertrag', 'Ertrag')],
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kontoblatt(request, nummer):
    """Kontoauszug/Kontoblatt eines Kontos: alle Buchungen mit laufendem Saldo.
    Bilanzkonten kumulativ (mit Eröffnungssaldo aus Vorjahren)."""
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    konto = get_object_or_404(Buchungskonto, nummer=nummer)
    jahr_param = request.GET.get('jahr', str(heute.year))
    try:
        jahr = int(jahr_param)
    except ValueError:
        jahr = None

    alle = Buchung.objects.filter(Q(soll_konto=konto) | Q(haben_konto=konto))
    if aktive_lg:
        alle = alle.filter(liegenschaft=aktive_lg)
    alle = alle.select_related('soll_konto', 'haben_konto', 'liegenschaft').order_by('datum', 'id')

    ist_bilanz = konto.typ in ('bilanz', 'aktiv', 'passiv')
    # Eröffnungssaldo: bei Bilanzkonten kumulativ aus Vorjahren, bei Erfolg 0.
    eroeffnung = Decimal('0.00')
    if jahr and ist_bilanz:
        vor = alle.filter(datum__lt=date(jahr, 1, 1))
        s = vor.filter(soll_konto=konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        h = vor.filter(haben_konto=konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        eroeffnung = s - h
    periode = alle.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31)) if jahr else alle

    zeilen = []
    saldo = eroeffnung
    for b in periode:
        ist_soll = b.soll_konto_id == konto.id
        betrag = b.betrag if ist_soll else -b.betrag
        saldo += betrag
        gegen = b.haben_konto if ist_soll else b.soll_konto
        zeilen.append({'b': b, 'soll': b.betrag if ist_soll else None,
                       'haben': b.betrag if not ist_soll else None,
                       'gegenkonto': gegen, 'saldo': saldo})
    return render(request, 'fw/kontoblatt.html', {
        **basis, 'nav': 'buchhaltung', 'konto': konto, 'zeilen': zeilen,
        'eroeffnung': eroeffnung, 'endsaldo': saldo, 'ist_bilanz': ist_bilanz,
        'jahr': jahr or 'alle', 'jahre': list(range(heute.year, heute.year - 5, -1)),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung_pdf(request):
    """Erfolgsrechnung und Bilanz als PDF.

    Der Berichte-Hub versprach für «Erfolgsrechnung & Bilanz» ein PDF, es gab
    aber nur den CSV-Journal-Export. Für die Übergabe ans Treuhandbüro und die
    Ablage beim Eigentümer braucht es den Abschluss auf Papier.
    """
    from django.http import HttpResponse
    from core.services.abschluss_pdf import generate_abschluss_pdf
    from crm.models import Organisation

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    jahr_param = request.GET.get('jahr', str(heute.year))
    if jahr_param == 'alle':
        jahr = 'alle'
    else:
        try:
            jahr = int(jahr_param)
        except ValueError:
            jahr = heute.year

    daten = _erfolg_bilanz(aktive_lg, jahr)
    lg_name = f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg else "Gesamtes Portfolio"
    pdf = generate_abschluss_pdf(daten, jahr, lg_name,
                                 verwaltung=Organisation.objects.first(), erstellt_am=heute)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Erfolgsrechnung_Bilanz_{jahr}.pdf"'
    return resp


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung_export(request):
    """Exportiert das Buchungsjournal des Jahres als CSV (Treuhänder-Handover)."""
    import csv
    from django.http import HttpResponse
    from finance.models import Buchung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr', str(heute.year)))
    except ValueError:
        jahr = heute.year
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
    qs = qs.select_related('soll_konto', 'haben_konto', 'liegenschaft').order_by('datum', 'id')

    resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    resp['Content-Disposition'] = f'attachment; filename="Journal_{jahr}.csv"'
    resp.write('﻿')  # BOM für Excel
    w = csv.writer(resp, delimiter=';')
    w.writerow(['Beleg-Nr', 'Datum', 'Belegtext', 'Soll-Konto', 'Haben-Konto', 'Betrag CHF', 'Liegenschaft', 'Storno'])
    for b in qs:
        w.writerow([
            getattr(b, 'beleg_nr', '') or b.id,
            b.datum.strftime('%d.%m.%Y'), b.beleg_text,
            f"{b.soll_konto.nummer} {b.soll_konto.bezeichnung}",
            f"{b.haben_konto.nummer} {b.haben_konto.bezeichnung}",
            f"{b.betrag:.2f}",
            b.liegenschaft.strasse if b.liegenschaft else '',
            'ja' if b.ist_storno else '',
        ])
    return resp
