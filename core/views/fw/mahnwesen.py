# core/views/fw/mahnwesen.py
#
# Erster aus core/views/fw/_rest.py herausgeloester Block (Etappe 1,
# siehe docs/ETAPPE-1-ZERLEGEN.md). Block 3 der 33: Mahnstufen aus
# ueberfaelligen Debitoren, dazu die Altersstruktur (Aging).
#
# Unveraendert uebernommen -- der Blockinhalt ab dem Kommentarbanner ist
# Zeile fuer Zeile derselbe. Neu sind ausschliesslich die Importe hier oben,
# die vorher aus dem Dateikopf der alten fw.py kamen.
#
# Erreichbar bleibt alles ueber `core.views.fw` -- das __init__.py des Pakets
# re-exportiert; swiss_immo/urls.py und die Tests aendern sich nicht.

from collections import defaultdict
from datetime import timedelta as _timedelta
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.tenancy import organisation_der_anfrage
from core.auth import rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN, TEAM_ROLLEN
from crm.models import Mieter
from finance.models import DebitorenRechnung

from ._basis import _global_filter, _num


# ============================================================
# ETAPPE D: MAHNWESEN (Mahnstufen aus überfälligen Debitoren)
# ============================================================

# Die Mahnstufen liegen je Organisation in der Datenbank (crm.MahnStufe) —
# EINE Quelle der Wahrheit in core.services.mahnstufen. Hier steht keine Frist.
from core.services.mahnstufen import (  # noqa: E402
    mahnstufen_config as _mahnstufen_config,
    Mahnstufen,
    eigentuemer_von_rechnung as _eigentuemer_von_rechnung,
)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mahnwesen(request):
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft__eigentuemer',
                          'liegenschaft__eigentuemer')
          .prefetch_related('zahlungseingaenge'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    stufe_filter = request.GET.get('stufe', '')
    # Effektive Mahnstufen-Legende: die Stufen der Organisation, bei gewählter
    # Liegenschaft mit der Übersteuerung ihres Eigentümers.
    legende = _mahnstufen_config(getattr(aktive_lg, 'eigentuemer', None) if aktive_lg else None)

    rows = []
    total = Decimal('0.00')
    counts = defaultdict(int)
    summe = defaultdict(lambda: Decimal('0.00'))
    stufen_laden = Mahnstufen()
    for r in qs:
        faellig = r.faellig_am or r.datum
        if not faellig:
            continue
        # Der Fälligkeitstag ist Tag 0; wann der Verzug beginnt, stellt die Verwaltung ein.
        tage = stufen_laden.tage_im_verzug(faellig, heute, _eigentuemer_von_rechnung(r),
                                           organisation=r.organisation)
        if tage is None:
            continue
        stufe = stufen_laden.stufe_fuer_tage(tage, _eigentuemer_von_rechnung(r),
                                             organisation=r.organisation)
        if not stufe:
            continue  # unter der ersten aktiven Stufe: noch kein Mahnfall
        offen = r.offener_betrag
        if offen <= 0:
            continue
        counts[stufe['stufe']] += 1
        summe[stufe['stufe']] += offen
        total += offen
        if stufe_filter and str(stufe['stufe']) != stufe_filter:
            continue
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        monat = faellig.strftime('%m/%Y')
        rows.append({
            'r': r, 'stufe': stufe, 'tage': tage, 'offen': offen,
            'mieter': r.vertrag.mieter.display_name if r.vertrag_id else '—',
            'objekt': (f"{lg.strasse}, {lg.ort}" if lg else '—'),
            'faellig': faellig,
            'vertrag_id': r.vertrag_id,
            'hat_email': bool(r.vertrag and r.vertrag.mieter.email),
            'monat': monat,
            'mahn_url': (f"/vertrag/{r.vertrag_id}/mahnung/?rechnung={r.id}&stufe={stufe['stufe']}"
                         if r.vertrag_id else None),
        })
    rows.sort(key=lambda x: (-x['stufe']['stufe'], -x['tage']))

    stufe_chips = [('', _('Alle Stufen'))] + [(str(s['stufe']), s['label']) for s in legende]

    # Letzte erfasste Mahnung je Rechnung + Historie
    from finance.models import Mahnung
    letzte_je_rechnung = {}
    for mn in Mahnung.objects.all().order_by('datum'):
        letzte_je_rechnung[mn.debitoren_rechnung_id] = mn
    for row in rows:
        row['letzte_mahnung'] = letzte_je_rechnung.get(row['r'].id)

    historie_qs = (Mahnung.objects.select_related('vertrag__mieter', 'debitoren_rechnung')
                   .order_by('-datum', '-id'))
    if aktive_lg:
        historie_qs = historie_qs.filter(vertrag__einheit__liegenschaft=aktive_lg)
    historie = list(historie_qs[:30])

    legende = [dict(s, anzahl=counts.get(s['stufe'], 0)) for s in legende]
    context = {
        **basis, 'nav': 'mahnwesen', 'rows': rows,
        'stufe_filter': stufe_filter, 'stufe_chips': stufe_chips,
        'total': total,
        'mahnstufen': legende,
        'verzugszins': organisation_der_anfrage(request).verzugszins_prozent.normalize(),
        'counts': counts, 'summe': summe,
        'anzahl_total': sum(counts.values()),
        'historie': historie,
    }
    return render(request, 'fw/mahnwesen.html', context)


AGING_BUCKETS = ['nicht_faellig', 'd30', 'd60', 'd90', 'd90plus']


def aging_gruppen(qs, heute):
    """Offene Rechnungen je Mieter nach Faelligkeitsalter — (rows, total).

    Aus `fw_debitoren_aging` herausgeloest, damit die Finanzseite
    (konzept-v8, «Ausstaende nach Alter») DIESELBE Einteilung zeigt statt
    einer zweiten. Erwartet ein QuerySet mit `select_related(
    'vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')`
    und `prefetch_related('zahlungseingaenge')`.

    Zusaetzlich zur Aging-Seite traegt jede Zeile `mieter_id`,
    `vertrag_ids`, `rechnung_ids` und `lg` (fuer den Verweis zur Akte und
    die Mahnstufe) — rein lesend, ohne weitere Abfrage.
    """
    BUCKETS = AGING_BUCKETS

    def bucket(tage):
        if tage <= 0:
            return 'nicht_faellig'
        if tage <= 30:
            return 'd30'
        if tage <= 60:
            return 'd60'
        if tage <= 90:
            return 'd90'
        return 'd90plus'

    gruppen = {}
    total = {b: Decimal('0.00') for b in BUCKETS}
    total['summe'] = Decimal('0.00')
    for r in qs:
        offen = r.offener_betrag
        if offen <= 0:
            continue
        faellig = r.faellig_am or r.datum
        tage = (heute - faellig).days if faellig else 0
        b = bucket(tage)
        if r.vertrag_id and r.vertrag.mieter_id:
            key = ('m', r.vertrag.mieter_id)
            name = r.vertrag.mieter.display_name
            lg = r.vertrag.einheit.liegenschaft if r.vertrag.einheit_id else None
            objekt = (f"{lg.strasse}" if lg else '')
        else:
            key = ('t', (r.titel or 'Diverse'))
            name = r.titel or 'Diverse'
            objekt = r.liegenschaft.strasse if r.liegenschaft_id else ''
        g = gruppen.setdefault(key, {'name': name, 'objekt': objekt,
                                     **{b: Decimal('0.00') for b in BUCKETS},
                                     'summe': Decimal('0.00'), 'aeltester': 0,
                                     'mieter_id': key[1] if key[0] == 'm' else None,
                                     'vertrag_ids': set(), 'rechnung_ids': [],
                                     'lg': None})
        if r.vertrag_id:
            g['vertrag_ids'].add(r.vertrag_id)
        g['rechnung_ids'].append(r.id)
        if g['lg'] is None:
            g['lg'] = (r.vertrag.einheit.liegenschaft
                       if r.vertrag_id and r.vertrag.einheit_id else
                       (r.liegenschaft if r.liegenschaft_id else None))
        g[b] += offen
        g['summe'] += offen
        g['aeltester'] = max(g['aeltester'], tage)
        total[b] += offen
        total['summe'] += offen

    rows = sorted(gruppen.values(), key=lambda g: (-g['aeltester'], -float(g['summe'])))
    return rows, total


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitoren_aging(request):
    """Debitoren-Altersstruktur (OP-Aging): offene Forderungen nach
    Fälligkeitsalter (nicht fällig / 1–30 / 31–60 / 61–90 / >90 Tage),
    gruppiert je Mieter — die Risikosicht fürs Mahnwesen."""
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # `offener_betrag` summiert die verbuchten Zahlungseingänge. Ohne Prefetch
    # ist das EINE Abfrage je offener Rechnung — gemessen 88 Posten → 93
    # Abfragen, 176 → 181. Ausgerechnet diese Seite öffnet man dann, wenn viel
    # offen ist. Der Prefetch-Zweig in `offener_betrag` greift nur, wenn die
    # Zahlungen hier auch vorgeladen werden; die übrigen Debitoren-Listen tun
    # das seit dem N+1-Hotfix, diese Seite war nicht nachgezogen worden.
    qs = (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
          .prefetch_related('zahlungseingaenge'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    rows, total = aging_gruppen(qs, heute)
    ueberfaellig_summe = total['d30'] + total['d60'] + total['d90'] + total['d90plus']

    return render(request, 'fw/debitoren_aging.html', {
        **basis, 'nav': 'mahnwesen', 'rows': rows, 'total': total,
        'ueberfaellig_summe': ueberfaellig_summe, 'anzahl': len(rows), 'heute': heute,
    })


# ---------------------------------------------------------------------------
# Block 28 der 33, hier ANGEHAENGT statt in ein eigenes Modul gelegt: Es ist
# derselbe Fachbereich wie oben (Block 3). Zwei Dateien mahnwesen.py und
# mahn_historie.py nebeneinander waeren eine Grenze, die es fachlich nicht
# gibt — die Zielstruktur benennt die Module nach Thema, nicht nach
# Blocknummer. Der Blockinhalt ist unveraendert.
#
# Zusaetzlich gebraucht: transaction, get_object_or_404, SCHREIB_ROLLEN,
# _timedelta (siehe Importe am Dateikopf).
# ---------------------------------------------------------------------------

# ============================================================
# MAHN-HISTORIE (revisionssicher) + Mahngebühren
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_mahnung_erfassen(request):
    """Erfasst einen revisionssicheren Mahnschritt in der Historie und legt
    optional eine Mahngebühr als Debitorenrechnung an."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Mahnung, DebitorenRechnung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_mahnwesen')

    rechnung = get_object_or_404(DebitorenRechnung.objects.select_related('vertrag__mieter'),
                                 id=request.POST.get('rechnung_id'))
    try:
        stufe = int(request.POST.get('stufe') or 1)
    except ValueError:
        stufe = 1
    # Die Stufe muss es in der Organisation geben — wie viele es sind und wie sie
    # heissen, bestimmt die Verwaltung (crm.MahnStufe), nicht der Code.
    from core.services.mahnstufen import stufen_der_organisation
    if stufe not in {s['stufe'] for s in stufen_der_organisation(rechnung.organisation)}:
        messages.error(request, gettext('Diese Mahnstufe gibt es nicht.'))
        return redirect('fw_mahnwesen')

    # Eine bezahlte, stornierte oder abgeschriebene Forderung darf nicht (mehr)
    # gemahnt werden — sonst wird eine Mahngebühr auf eine Forderung gestellt, die
    # gar nicht mehr offen ist (Live-Test E). offener_betrag deckt den
    # (teil-)bezahlten Fall mit ab.
    # Mahngebühren und Zinsen werden mit der Hauptforderung eingefordert, nicht
    # selbst gemahnt (Gebühr auf Gebühr, Art. 105 Abs. 3 OR).
    if rechnung.stammrechnung_id:
        messages.error(request, gettext('Eine Mahngebühr bzw. Zinsrechnung wird nicht selbst gemahnt — mahnen Sie die Hauptforderung.'))
        return redirect('fw_mahnwesen')
    if rechnung.status in ('bezahlt', 'storniert', 'abgeschrieben') or rechnung.offener_betrag <= 0:
        messages.error(request, gettext('Diese Forderung ist nicht (mehr) offen und kann nicht gemahnt werden.'))
        return redirect('fw_mahnwesen')

    # Doppelerfassung UND Mahnstufen-Rückschritt verhindern: existiert bereits eine
    # Mahnung dieser ODER höherer Stufe, wird nichts erfasst. Sonst entstünde ein
    # zweiter Historien-Eintrag + doppelte Mahngebühr, oder man könnte nach der
    # 2. Mahnung wieder eine 1. erfassen (Live-Test E).
    hoechste = Mahnung.objects.filter(debitoren_rechnung=rechnung).order_by('-stufe').first()
    if hoechste and hoechste.stufe >= stufe:
        messages.info(request, gettext('Für diese Rechnung ist bereits die %(stufe)s. Mahnung erfasst — eine %(stufe2)s. Mahnung wäre ein Rückschritt.') % {'stufe': hoechste.stufe, 'stufe2': stufe})
        return redirect('fw_mahnwesen')

    # Mahngebühr aus der Eigentümer-Konfig (crm.Eigentuemer.mahn_konfig) — NICHT mehr
    # hartcodiert (fw.MAHN_GEBUEHR). Ein aus dem Formular übermittelter Wert
    # überschreibt sie (manuelle Anpassung); fehlt er, gilt die konfigurierte
    # Gebühr (z.B. 0 → dann wird KEINE 40.- geschrieben, Nutzer-Bug behoben).
    from core.services.mahnstufen import gebuehr_fuer_stufe, eigentuemer_von_rechnung
    _cfg_geb = gebuehr_fuer_stufe(stufe, eigentuemer_von_rechnung(rechnung))
    _posted = _num(request.POST.get('gebuehr'))
    try:
        gebuehr = Decimal(str(_posted)) if _posted not in (None, '') else _cfg_geb
    except Exception:
        gebuehr = _cfg_geb
    if gebuehr < 0:
        gebuehr = Decimal('0.00')

    heute = timezone.localdate()
    # Mahnung + Mahngebühr-Rechnung + Hauptbuchbuchung in EINER Transaktion —
    # scheitert die Buchung (Periodensperre), bleibt keine Mahnung/Gebühr ohne
    # Gegenbuchung stehen. Das DB-Unique (debitoren_rechnung, stufe) fängt zudem
    # den Doppelklick-Race ab (der exists()-Check oben ist ohne Lock).
    from django.db import IntegrityError
    try:
        with transaction.atomic():
            Mahnung.objects.create(
                debitoren_rechnung=rechnung, vertrag=rechnung.vertrag, stufe=stufe,
                datum=heute, betrag_offen=rechnung.offener_betrag, gebuehr=gebuehr,
                versandart=request.POST.get('versandart', 'manuell'),
                erstellt_von=request.user,
            )
            # Mahngebühr als separate Debitorenrechnung (falls > 0) — inkl. Hauptbuch-
            # Buchung (Forderung an übrigen Ertrag), sonst driften Neben-/Hauptbuch.
            if gebuehr > 0 and rechnung.vertrag_id:
                lg_geb = rechnung.liegenschaft or (rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None)
                geb_rechnung = DebitorenRechnung.objects.create(
                    vertrag=rechnung.vertrag,
                    liegenschaft=lg_geb,
                    titel=f"Mahngebühr {stufe}. Mahnung",
                    beschreibung=f"Mahngebühr zu: {rechnung.titel}",
                    datum=heute, faellig_am=heute + _timedelta(days=30),
                    betrag=gebuehr, status='offen',
                    stammrechnung=rechnung,   # für Storno-Kaskade (Live-Test E)
                )
                from finance.booking import buche
                buche("1100", "3600", gebuehr, f"Mahngebühr {stufe}. Mahnung {rechnung.vertrag.mieter}",
                      datum=heute, liegenschaft=lg_geb, debitor=geb_rechnung, user=request.user)
    except IntegrityError:
        messages.info(request, gettext('Die %(stufe)s. Mahnung wurde für diese Rechnung bereits erfasst.') % {'stufe': stufe})
        return redirect('fw_mahnwesen')
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect('fw_mahnwesen')
    except Exception as exc:
        messages.error(request, '❌ ' + gettext('Mahnung konnte nicht gebucht werden: %(exc)s') % {'exc': exc})
        return redirect('fw_mahnwesen')

    # Beleg in die Vertrags-Akte. Ausserhalb der Transaktion und bewusst
    # fehlertolerant: Historie und Gebühr sind bereits gebucht, ein misslungenes
    # PDF darf den erfassten Mahnschritt nicht zurückrollen.
    if rechnung.vertrag_id:
        from core.services.ablage import ablage_mahnung
        from core.services.mahnstufen import mahnstufen_config
        _cfg = next((x for x in mahnstufen_config(eigentuemer_von_rechnung(rechnung))
                     if x['stufe'] == stufe), None)
        _letzte = bool(_cfg and _cfg['kuendigung'])
        ablage_mahnung(rechnung.vertrag, stufe=stufe, datum=heute,
                       betrag=f"{rechnung.offener_betrag:.2f}", rechnung=rechnung,
                       gebuehr=gebuehr, letzte_stufe=_letzte)
        if _letzte:
            from core.services.zahlungsverzug import eskalation_257d
            eskalation_257d(rechnung, benutzer=request.user)

    log_aktion(request, f"{stufe}. Mahnung erfasst",
               rechnung.vertrag.mieter.display_name if rechnung.vertrag_id else rechnung.titel,
               f"offen CHF {rechnung.offener_betrag}, Gebühr CHF {gebuehr}")
    if gebuehr > 0:
        meldung = gettext('%(stufe)s. Mahnung erfasst · Mahngebühr CHF %(gebuehr)s gestellt.') % {
            'stufe': stufe, 'gebuehr': gebuehr}
    else:
        meldung = gettext('%(stufe)s. Mahnung erfasst.') % {'stufe': stufe}
    messages.success(request, '✅ ' + meldung)
    ziel = '/neu/mahnwesen/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mahnlauf_trockenlauf(request):
    """Was der Mahnlauf JETZT täte — ohne etwas zu buchen oder zu versenden."""
    from django.shortcuts import render
    from core.services.automation import run_mahnlauf
    basis = _global_filter(request)
    mit_zins = request.GET.get('mit_zins') == 'on'
    send_email = request.GET.get('kein_versand') != 'on'
    erzwingen = request.GET.get('erzwingen') == '1'
    res = run_mahnlauf(aktive_lg=basis['aktive_lg'], send_email=send_email,
                       mit_zins=mit_zins, dry_run=True, erzwingen=erzwingen)
    return render(request, 'fw/mahnlauf_trockenlauf.html', {
        **basis, 'nav': 'mahnwesen', 'res': res, 'plan': res['plan'],
        'mit_zins': mit_zins, 'send_email': send_email, 'erzwingen': erzwingen})


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mahnlauf(request):
    """Sammel-Mahnlauf über ALLE fälligen offenen Debitoren (statt einzeln).
    Erzeugt Mahnungen je Stufe (idempotent), stellt Mahngebühr + optional
    Verzugszins und verschickt Zahlungserinnerungen per E-Mail."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from core.services.automation import run_mahnlauf
    if request.method != 'POST':
        return redirect('fw_mahnwesen')
    basis = _global_filter(request)
    mit_zins = request.POST.get('mit_zins') == 'on'
    send_email = request.POST.get('kein_versand') != 'on'
    erzwingen = request.POST.get('erzwingen') == '1'
    res = run_mahnlauf(aktive_lg=basis['aktive_lg'], send_email=send_email,
                       mit_zins=mit_zins, user=request.user, erzwingen=erzwingen)
    # Ein erzwungener Lauf ist ein Zusatzlauf — er schliesst den regulären Monatslauf nicht ab.
    if not basis['aktive_lg'] and not erzwingen:
        from faelle.lauf_dienst import lauf_erledigt, periode_von
        lauf_erledigt('mahnlauf', periode_von(timezone.localdate()),
                      benutzer=request.user, auch_aeltere=True,
                      gemahnt=res['gemahnt'])
    log_aktion(request, "Mahnlauf erzwungen" if erzwingen else "Mahnlauf ausgeführt", "Sammellauf",
               f"{res['gemahnt']} gemahnt, {res['emails']} E-Mails, Gebühren CHF {res['gebuehren']}, Zins CHF {res['zins']}")
    if res['gemahnt']:
        teile = [gettext('%(n)s Mahnung(en) erstellt') % {'n': res['gemahnt']}]
        if send_email:
            teile.append(gettext('%(n)s E-Mail(s) versandt') % {'n': res['emails']})
        if res['gebuehren'] > 0:
            teile.append(gettext('Gebühren CHF %(betrag)s') % {'betrag': res['gebuehren']})
        if res['zins'] > 0:
            teile.append(gettext('Verzugszins CHF %(betrag)s') % {'betrag': res['zins']})
        messages.success(request, '✅ ' + gettext('Mahnlauf: %(teile)s.') % {'teile': ', '.join(teile)})
    else:
        messages.success(request, gettext('Mahnlauf: keine neuen Mahnungen fällig — alles aktuell.'))
    ziel = '/neu/mahnwesen/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)
