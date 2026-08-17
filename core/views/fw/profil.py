# core/views/fw/profil.py
#
# Profil-Menue: Account, Benutzerliste, Logbuch, Rechtsgrundlagen,
# Eigentuemerliste, Mieterwechsel, Vermarktung samt Portal-Feed, Vorlagen,
# Integrationen, Abonnemente. Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# OFFENER POSTEN, hier bewusst NICHT geloest: fw_benutzer (die Liste) steht
# in diesem Block, waehrend fw_benutzer_form und fw_benutzer_loeschen aus
# einem eigenen Block stammen und in benutzer.py liegen. Drei Views eines
# Features in zwei Modulen. Sie zusammenzufuehren hiesse, eine View ueber
# eine Blockgrenze zu tragen — genau die Sorte Urteil, die der Auftrag im
# Umzugs-PR untersagt ("die Blockgrenze ist die Kante"). Gehoert in einen
# eigenen PR nach Etappe 1.

import logging
import os
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter, Organisation
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num, _vermietung_pipeline
from core.tenancy import aktuelle_organisation


# ============================================================
# PROFIL-MENÜ: Account, Benutzer, Mandate, Vorlagen, Integrationen
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_account(request):
    """Firmen-/Verwaltungs-Stammdaten + Marktdaten (Referenzzins/LIK)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Organisation
    from core.auth import log_aktion, hat_rolle, snapshot_model, diff_model
    vw = aktuelle_organisation()
    basis = _global_filter(request)

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        P = request.POST
        alt_snap = snapshot_model(Organisation.objects.get(pk=vw.pk))
        vw.firma = P.get('firma', '').strip() or vw.firma
        vw.strasse = P.get('strasse', '').strip()
        vw.plz = P.get('plz', '').strip()
        vw.ort = P.get('ort', '').strip()
        vw.telefon = P.get('telefon', '').strip()
        vw.email = P.get('email', '').strip()
        vw.iban = P.get('iban', '').strip()

        def dec(key, fallback):
            try:
                return Decimal((_num(P.get(key)) or str(fallback)))
            except Exception:
                return fallback
        vw.aktueller_referenzzinssatz = dec('aktueller_referenzzinssatz', vw.aktueller_referenzzinssatz)
        vw.aktueller_lik_punkte = dec('aktueller_lik_punkte', vw.aktueller_lik_punkte)
        vw.nk_honorar_prozent = dec('nk_honorar_prozent', vw.nk_honorar_prozent)
        # LIK-Basis + Stand-Monat
        vw.lik_basis = (P.get('lik_basis') or vw.lik_basis or 'Dezember 2020').strip()
        stand_raw = (P.get('aktueller_lik_stand') or '').strip()  # 'YYYY-MM' aus <input type=month>
        if stand_raw:
            try:
                jahr, monat = stand_raw.split('-')[:2]
                vw.aktueller_lik_stand = date(int(jahr), int(monat), 1)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        # Logo hochladen oder entfernen
        if P.get('logo_entfernen') == '1' and vw.logo:
            vw.logo.delete(save=False)
            vw.logo = None
        elif request.FILES.get('logo'):
            vw.logo = request.FILES['logo']
        # Digitale Unterschrift: direkt gezeichnet ODER hochgeladen. Bisher nur
        # im Django-Admin hinterlegbar, obwohl jeder Brief sie braucht.
        # Verwaltung.save() macht den weissen Hintergrund automatisch transparent.
        from core.services.unterschrift import uebernehme_aus_formular
        uebernehme_aus_formular(vw, request)
        vw.save()
        log_aktion(request, "Account/Stammdaten bearbeitet", vw.firma,
                   diff_model(alt_snap, snapshot_model(vw), vw))
        messages.success(request, "✅ Stammdaten gespeichert.")
        return redirect('/neu/account/')

    def _url(feld):
        f = getattr(vw, feld, None)
        try:
            return f.url if f else ''
        except Exception:
            return ''
    from core.services.unterschrift import unterschrift_url as _sig_url
    sig_url = _sig_url(vw)
    return render(request, 'fw/account.html', {
        **basis, 'nav': 'account', 'vw': vw,
        'logo_url': _url('logo'), 'unterschrift_url': sig_url,
        'unterschrift_verwaist': bool(getattr(vw, 'unterschrift_bild', None)) and not sig_url,
        'kann_reset': hat_rolle(request.user, [ROLLE_VERWALTER]),
    })


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_datenreset(request):
    """GEFAHRENZONE: löscht ALLE operativen Daten (Liegenschaften, Objekte,
    Verträge, Personen, Buchungen, Rechnungen, Schäden, Vorlagen, Mandate,
    Verwaltungs-Stammdaten …) und startet mit einer leeren, frisch geseedeten
    Datenbank. Benutzerkonten/Rollen bleiben erhalten (Login bleibt gültig).
    Erfordert Bestätigungstext 'LÖSCHEN'."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.db import connection
    from django.apps import apps
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('/neu/account/')
    if (request.POST.get('bestaetigung') or '').strip().upper() != 'LÖSCHEN':
        messages.error(request, "Zum Zurücksetzen bitte «LÖSCHEN» eingeben.")
        return redirect('/neu/account/#gefahrenzone')

    # Eigene App-Daten (Framework/Benutzer bleiben erhalten)
    OWN_APPS = {'core', 'crm', 'finance', 'mietprozess', 'portfolio', 'rentals', 'tickets'}
    # Auth-Tabellen NIE anfassen (Login/Rollen bleiben), auch wenn ein Modell
    # im 'core'-App-Label darauf zeigen sollte.
    # Zwei Tabellen kamen mit Etappe 4 dazu, beide im App-Label 'crm' und
    # deshalb ohne diesen Eintrag mitgeloescht:
    #
    # `crm_mitgliedschaft` traegt seit 4.3 die Rolle. Ohne sie haette nach dem
    # Reset KEIN Benutzer mehr eine Rolle, und jede View antwortete mit 403 —
    # gefunden von test_reset_behaelt_benutzer.
    #
    # `core_verwaltung` ist die Organisation. Sie IST der Mandant, nicht
    # dessen Daten: Firmenname, IBAN, Logo, Referenzzins, MWST-Einstellungen.
    # Sie zu loeschen und die Mitgliedschaft zu behalten hinterliess einen
    # Fremdschluessel ins Leere (IntegrityError). Und fachlich ist «meine
    # Daten zuruecksetzen» nicht «meine Firma abmelden».
    KEEP = {'auth_user', 'auth_group', 'auth_user_groups', 'auth_group_permissions',
            'auth_permission', 'auth_user_user_permissions', 'django_admin_log',
            'django_content_type', 'django_session', 'django_migrations',
            'crm_mitgliedschaft', 'core_verwaltung'}
    # Nur Tabellen, die es wirklich gibt. Ein `DELETE FROM` auf eine fehlende
    # Tabelle bricht den GANZEN Reset ab — der Nutzer sieht einen Serverfehler
    # und weiss nicht, ob halb gelöscht wurde. Ein Modell ohne Tabelle ist
    # nicht erfunden: eine nicht angewandte Migration reicht, und im Testlauf
    # stehen die Modelle aus `test_tenant_manager.py` in der Registry.
    vorhanden = set(connection.introspection.table_names())
    tabellen = sorted({m._meta.db_table for m in apps.get_models()
                       if m._meta.app_label in OWN_APPS and m._meta.db_table not in KEEP
                       and m._meta.db_table in vorhanden})

    with connection.constraint_checks_disabled():
        with connection.cursor() as cur:
            for t in tabellen:
                cur.execute(f'DELETE FROM "{t}"')

    # Referenz-/Stammdaten frisch aufsetzen
    from finance.booking import ensure_kontenplan
    from core.services.raumkatalog import seed_lebensdauer
    try:
        ensure_kontenplan()
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)
    try:
        seed_lebensdauer()
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)

    log_aktion(request, "Datenbank zurückgesetzt", f"{len(tabellen)} Tabellen geleert")
    messages.success(request, "✅ Alle Daten wurden gelöscht — du startest mit einer leeren Datenbank.")
    return redirect('/neu/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_marktdaten_aktualisieren(request):
    """Holt Referenzzins + LIK aus dem Internet und speichert sie in Verwaltung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.utils.market_data import update_verwaltung_rates
    if request.method == 'POST':
        try:
            # Nur die eigene Verwaltung: Ein Knopfdruck darf keinen fremden
            # Frischestempel zuruecksetzen (siehe update_verwaltung_rates).
            msg, errors = update_verwaltung_rates(aktuelle_organisation())
            messages.success(request, f"📡 {msg}")
            if errors:
                messages.warning(request, "Hinweis: " + " | ".join(errors[:2]) +
                                 " — Falls das Netzwerk (PythonAnywhere-Whitelist) die Abfrage blockiert, "
                                 "kannst du die Werte oben manuell eintragen.")
        except Exception as e:
            messages.error(request, f"Marktdaten konnten nicht geladen werden: {e}. Werte bitte manuell eintragen.")
    return redirect('/neu/account/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_marktdaten_live(request):
    """JSON-Endpoint für den 'Aktuelle Werte'-Button im Vertragsassistenten.
    Versucht ein Live-Update, gibt aber immer die aktuell gespeicherten Werte zurück."""
    from django.http import JsonResponse
    from crm.models import Organisation
    from core.auth import hat_rolle
    quelle = 'gespeichert'
    vw = aktuelle_organisation()
    # Nur nachladen, wenn der gespeicherte Stand wirklich alt ist. Der Aufruf
    # holt zwei externe Seiten (je timeout=10) und war mit gut einer Sekunde
    # die langsamste Route der Anwendung — bei nicht erreichbaren Quellen bis
    # zu 20 s, in denen der Arbeitsprozess blockiert. Der tägliche Lauf
    # aktualisiert die Werte ohnehin; dieser Weg ist nur die Handnachholung,
    # wenn der Lauf ausgefallen ist.
    stand = getattr(vw, 'letztes_update_marktdaten', None) if vw else None
    veraltet = stand is None or (timezone.now() - stand).days >= 1
    if veraltet and hat_rolle(request.user, SCHREIB_ROLLEN):
        try:
            from core.utils.market_data import update_verwaltung_rates
            # Nur die eigene Verwaltung — `vw` ist sie bereits.
            update_verwaltung_rates(vw)
            quelle = 'internet'
            vw.refresh_from_db()
        except Exception:
            logger.warning("Marktdaten-Livenachladen fehlgeschlagen", exc_info=True)
            quelle = 'gespeichert'
    return JsonResponse({
        'ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.25,
        'lik': float(vw.aktueller_lik_punkte) if vw else 107.8,
        'stand': vw.letztes_update_marktdaten.strftime('%d.%m.%Y %H:%M') if vw and vw.letztes_update_marktdaten else None,
        'quelle': quelle,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_benutzer(request):
    """Team-Mitglieder (Django-User + Rolle). Portal-Konten (Mieter/Eigentümer)
    werden hier NICHT angezeigt — die werden über Person bzw. Eigentuemer verwaltet."""
    from django.contrib.auth import get_user_model
    from core.auth import ROLLE_EIGENTUEMER

    User = get_user_model()
    basis = _global_filter(request)
    # Die drei Dinge, die unten je Benutzer geprüft werden, gleich mitladen —
    # sonst sind es drei Abfragen pro Zeile (gemessen: 103 für 33 Benutzer).
    # NUR das eigene Team. `Benutzer` trägt keine Organisationsspalte (ein
    # Mensch kann in mehreren Verwaltungen Mitglied sein), der TenantManager
    # greift hier also nicht — gefiltert wird über `Mitgliedschaft`.
    #
    # Ohne diesen Filter zeigte die gewöhnliche Benutzerseite jeder Verwaltung
    # das VOLLSTÄNDIGE Team aller anderen: Name, Anmeldename, E-Mail, Rolle.
    # Kein Registrylauf fand das, weil diese URL keinen ID-Parameter hat und
    # damit durch das Raster der Bauform A fiel (gemessen 17.08.2026).
    organisation = getattr(request, 'organisation', None)
    users = (User.objects.filter(is_active=True, mitgliedschaften__organisation=organisation)
             .select_related('mieter_profil', 'eigentuemer_profil')
             .prefetch_related('groups').order_by('username').distinct())
    rows = []
    for u in users:
        # Reine Portal-Zugänge ausblenden (Mieter- oder Eigentümer-Portal)
        if getattr(u, 'mieter_profil', None) is not None:
            continue
        if getattr(u, 'eigentuemer_profil', None) is not None:
            continue
        # `.values_list()` umgeht prefetch_related und fragt je Benutzer nach —
        # über `.all()` gehen wollen wir genau das nicht (gemessen: 32 Abfragen).
        rollen = [g.name for g in u.groups.all()]
        if ROLLE_EIGENTUEMER in rollen and len(rollen) == 1:
            continue  # reiner Eigentümer (per Rolle) — auch ausblenden
        rows.append({'u': u, 'rolle': ', '.join(rollen) or ('Superuser' if u.is_superuser else '—'),
                     'name': (u.get_full_name() or u.username)})
    return render(request, 'fw/benutzer.html', {**basis, 'nav': 'benutzer', 'rows': rows})


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_logbuch(request):
    """Logbuch / Audit-Trail: wer hat wann was getan (Verträge, Personen,
    Dokumente, Buchungen, Löschungen …). Nur für die Verwaltung einsehbar,
    rein lesend. Filter: Freitext, Benutzer, Aktionsart, Zeitraum · seitenweise.
    Optionaler CSV-Export mit denselben Filtern (?export=csv)."""
    from django.contrib.auth import get_user_model
    from django.core.paginator import Paginator
    from core.models import AktivitaetsLog

    User = get_user_model()
    basis = _global_filter(request)

    qs = AktivitaetsLog.objects.select_related('benutzer').all()

    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(aktion__icontains=q) | Q(objekt__icontains=q) | Q(details__icontains=q))

    benutzer_id = (request.GET.get('benutzer') or '').strip()
    if benutzer_id == 'system':
        qs = qs.filter(benutzer__isnull=True)
    elif benutzer_id.isdigit():
        qs = qs.filter(benutzer_id=int(benutzer_id))

    # Aktionsart: strukturierte Kategorie (zuverlässig, am Eintrag gespeichert).
    art = (request.GET.get('art') or '').strip()
    if art == 'kritisch':
        qs = qs.filter(kategorie__in=AktivitaetsLog.KRITISCH)
    elif art in dict(AktivitaetsLog.KATEGORIE_CHOICES):
        qs = qs.filter(kategorie=art)

    tage = (request.GET.get('tage') or '30').strip()
    if tage.isdigit() and int(tage) > 0:
        von = timezone.now() - _timedelta(days=int(tage))
        qs = qs.filter(zeitpunkt__gte=von)

    # CSV-Export (gleiche Filter) — revisionssicher für die Ablage
    if request.GET.get('export') == 'csv':
        import csv
        from django.http import HttpResponse
        resp = HttpResponse(content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="logbuch.csv"'
        resp.write('﻿')  # BOM → Excel erkennt UTF-8
        w = csv.writer(resp, delimiter=';')
        w.writerow(['Zeitpunkt', 'Benutzer', 'Aktion', 'Objekt', 'Details'])
        for e in qs[:10000]:
            w.writerow([timezone.localtime(e.zeitpunkt).strftime('%d.%m.%Y %H:%M'),
                        e.benutzer.get_full_name() or e.benutzer.username if e.benutzer else 'System',
                        e.aktion, e.objekt, e.details])
        return resp

    # PDF-Auditbericht (revisionssicher, gleiche Filter)
    if request.GET.get('export') == 'pdf':
        from django.http import HttpResponse
        from core.services.logbuch_pdf import logbuch_pdf
        pdf = logbuch_pdf(list(qs[:2000]), erstellt_von=(request.user.get_full_name() or request.user.username))
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = 'inline; filename="Logbuch-Auditbericht.pdf"'
        return resp

    # Kennzahlen für den Statistik-Kopf (auf der gefilterten Menge)
    from django.db.models import Count
    kat_counts = {k: n for k, n in qs.values_list('kategorie').annotate(n=Count('id'))}
    stat = {
        'kritisch': qs.filter(kategorie__in=AktivitaetsLog.KRITISCH).count(),
        'sicherheit': kat_counts.get('sicherheit', 0),
        'geloescht': kat_counts.get('geloescht', 0),
    }
    top_user = list(qs.exclude(benutzer__isnull=True)
                    .values('benutzer__username', 'benutzer__first_name', 'benutzer__last_name')
                    .annotate(n=Count('id')).order_by('-n')[:5])

    paginator = Paginator(qs, 50)
    seite = paginator.get_page(request.GET.get('page'))

    # Benutzer-Dropdown: nur, wer tatsächlich Einträge hat
    aktive_ids = list(AktivitaetsLog.objects.exclude(benutzer__isnull=True)
                      .values_list('benutzer_id', flat=True).distinct())
    benutzer = User.objects.filter(id__in=aktive_ids).order_by('username')

    return render(request, 'fw/logbuch.html', {
        **basis, 'nav': 'logbuch', 'seite': seite, 'total': paginator.count,
        'benutzer': benutzer, 'stat': stat, 'top_user': top_user,
        'f_q': q, 'f_benutzer': benutzer_id, 'f_art': art, 'f_tage': tage,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_rechtsgrundlagen(request):
    """Verzeichnis der mietrechtlichen Gesetzesartikel (OR/VMWG/ZGB) mit
    Kurzfassung, Stichworten, amtlichem Volltext-Link (Fedlex) und Suche.
    Wo ein Artikel in der Software angewandt wird, steht es als Overlay dabei."""
    from core.services import gesetzestexte, mietrecht
    basis = _global_filter(request)
    q = (request.GET.get('q') or '').strip()

    # "Im Programm angewandt"-Overlay: Zitat ('Art. 257e OR') → Anwendungstext
    anwendung = {}
    for key, text in mietrecht.ANWENDUNG.items():
        ref = mietrecht.ref(key)
        if ref:
            anwendung[ref] = text

    gruppen = gesetzestexte.gesetze_uebersicht(q)
    treffer = 0
    for g in gruppen:
        for a in g['artikel']:
            a['anwendung'] = anwendung.get(f"Art. {a['art']} {a['gesetz']}", '')
            treffer += 1

    return render(request, 'fw/rechtsgrundlagen.html', {
        **basis, 'nav': 'rechtsgrundlagen', 'gruppen': gruppen, 'q': q,
        'treffer': treffer, 'gesamt': len(gesetzestexte.REGISTER),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_eigentuemer_liste(request):
    """Eigentümer (Eigentümer, für die verwaltet wird)."""
    from crm.models import Eigentuemer
    basis = _global_filter(request)
    eigentuemer = Eigentuemer.objects.all().order_by('firma_oder_name')
    rows = []
    for md in eigentuemer:
        anzahl_lg = Liegenschaft.objects.filter(eigentuemer=md).count()
        rows.append({'md': md, 'anzahl_lg': anzahl_lg})
    return render(request, 'fw/mandate.html', {**basis, 'nav': 'mandate', 'rows': rows})


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterwechsel(request):
    """Mieterwechsel-Cockpit: EINE Übersicht über alle Vertragswechsel — gekündigte
    UND auslaufende (befristete) Verträge — als Pipeline von Gekündigt/Läuft aus →
    Rücknahme → Nachmieter → neuer Vertrag → Übergabe → Abrechnung."""
    from rentals.models import Kuendigung
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        monate = int(request.GET.get('monate', '12'))
    except ValueError:
        monate = 12
    grenze = None if monate == 0 else heute + _timedelta(days=int(monate * 30.44))

    def _row(v, ende, gekuendigt, k=None):
        e = v.einheit if v else None
        lg = e.liegenschaft if e else None
        tage = (ende - heute).days if ende else None
        nachmieter_v = None
        if e:
            nachmieter_v = (Mietvertrag.objects.filter(einheit=e)
                            .exclude(id=v.id)
                            .filter(beginn__gte=(ende or v.beginn) if ende else v.beginn)
                            .exclude(status='inaktiv')
                            .select_related('mieter').order_by('beginn').first())
        bewerbungen = Mietbewerbung.objects.filter(einheit=e).exclude(status='abgelehnt').count() if e else 0
        auszug_prot = v.abnahmen.filter(typ='auszug').order_by('-datum').first() if v else None
        auszug = auszug_prot is not None
        einzug = nachmieter_v.abnahmen.filter(typ='einzug').exists() if nachmieter_v else False

        kaution_status = v.kautions_status if v else 'keine'
        kaution_offen = kaution_status in ('erwartet', 'einbezahlt')
        kaution_erledigt = kaution_status in ('zurueckbezahlt', 'keine')
        offene_forderungen = (DebitorenRechnung.objects
                              .filter(vertrag=v, status__in=['offen', 'teilbezahlt']).count()) if v else 0
        schluss_offen = bool(auszug and (kaution_offen or offene_forderungen > 0))

        if schluss_offen:
            stufe, farbe, aktion = 'Schlussabrechnung', 'amber', 'Schlussabrechnung erstellen (Kaution + offene Forderungen)'
        elif einzug and kaution_erledigt and offene_forderungen == 0:
            stufe, farbe, aktion = 'Abgeschlossen', 'emerald', '—'
        elif nachmieter_v:
            stufe, farbe, aktion = 'Nachmieter-Vertrag', 'sky', 'Übergabe / Einzug planen'
        elif bewerbungen:
            stufe, farbe, aktion = 'Bewerbungen', 'indigo', 'Bewerbung prüfen & Vertrag erstellen'
        elif auszug:
            stufe, farbe, aktion = 'Rücknahme erfolgt', 'amber', 'Nachmieter suchen'
        elif gekuendigt:
            stufe, farbe, aktion = 'Gekündigt', 'rose', 'Objekt ausschreiben / Rücknahme planen'
        else:
            stufe, farbe, aktion = 'Läuft aus', 'slate', 'Ausschreiben oder Kündigung erfassen'

        return {
            'k': k, 'v': v, 'einheit': e, 'liegenschaft': lg, 'gekuendigt': gekuendigt,
            'objekt': (f"{lg.strasse}, {lg.ort} · {e.bezeichnung}" if lg and e else (e.bezeichnung if e else '—')),
            'mieter': v.mieter.display_name if v and v.mieter_id else '—',
            'ende': ende, 'tage': tage,
            'nachmieter': nachmieter_v.mieter.display_name if nachmieter_v and nachmieter_v.mieter_id else None,
            'nachmieter_vid': nachmieter_v.id if nachmieter_v else None,
            'bewerbungen': bewerbungen, 'auszug': auszug, 'einzug': einzug,
            'auszug_prot_id': (auszug_prot.id if auszug_prot else None),
            'kaution_offen': kaution_offen, 'kaution_erledigt': kaution_erledigt,
            'kaution_betrag': (v.kautions_betrag if v else None),
            'offene_forderungen': offene_forderungen, 'schluss_offen': schluss_offen,
            'ausgeschrieben': (e.zur_ausschreibung if e else False),
            'einheit_id': (e.id if e else None),
            'stufe': stufe, 'farbe': farbe, 'aktion': aktion,
        }

    rows = []
    behandelte_vids = set()

    # 1) Gekündigte Verträge (laufende Kündigungen) — immer relevant, kein Horizont
    kq = (Kuendigung.objects.filter(status__in=['erfasst', 'bestaetigt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
          .order_by('per_datum', 'berechneter_termin'))
    if aktive_lg:
        kq = kq.filter(vertrag__einheit__liegenschaft=aktive_lg)
    for k in kq:
        v = k.vertrag
        if not v or v.id in behandelte_vids:
            continue
        behandelte_vids.add(v.id)
        rows.append(_row(v, k.per_datum or k.berechneter_termin, gekuendigt=True, k=k))

    # 2) Auslaufende befristete Verträge (aktiv, befristet mit Ende, ohne laufende
    #    Kündigung). `ist_befristet` grenzt sauber gegen unbefristete Verträge ab,
    #    bei denen ein gesetztes `ende` aus einer Kündigung stammt.
    vq = (Mietvertrag.objects.filter(status='aktiv', ist_befristet=True, ende__isnull=False)
          .select_related('mieter', 'einheit__liegenschaft'))
    if aktive_lg:
        vq = vq.filter(einheit__liegenschaft=aktive_lg)
    if grenze:
        vq = vq.filter(ende__lte=grenze)
    for v in vq.order_by('ende'):
        if v.id in behandelte_vids:
            continue
        behandelte_vids.add(v.id)
        rows.append(_row(v, v.ende, gekuendigt=False))

    rows.sort(key=lambda r: (r['ende'] or heute))
    offen = [r for r in rows if r['stufe'] != 'Abgeschlossen']
    return render(request, 'fw/mieterwechsel.html', {
        **basis, **_vermietung_pipeline('mieterwechsel', basis['lg_query']), 'nav': 'mieterwechsel', 'rows': rows,
        'anzahl': len(rows), 'offen': len(offen), 'monate': monate,
        'gekuendigt_n': sum(1 for r in rows if r['gekuendigt']),
        'auslaufend_n': sum(1 for r in rows if not r['gekuendigt']),
        'dringend': len([r for r in offen if r['tage'] is not None and r['tage'] <= 60]),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_ausschreiben(request, einheit_id):
    """Objekt zur Nachmietersuche ausschreiben (bzw. Ausschreibung beenden).
    Setzt `zur_ausschreibung` und übernimmt das Verfügbarkeitsdatum aus der
    laufenden Kündigung, falls noch keins gesetzt ist."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    basis = _global_filter(request)
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=einheit_id)

    def _kuendigung_ende():
        k = (Kuendigung.objects.filter(vertrag__einheit=e, status__in=['erfasst', 'bestaetigt'])
             .order_by('per_datum', 'berechneter_termin').first())
        return (k.per_datum or k.berechneter_termin) if k else None

    if request.method != 'POST':
        # GET: Ausschreibungs-Formular (v.a. für das Cockpit-Modal)
        embed = request.GET.get('embed') == '1'
        return render(request, 'fw/objekt_ausschreiben.html', {
            **basis, 'nav': 'mieterwechsel', 'e': e,
            'verfuegbar_default': (e.verfuegbar_ab or _kuendigung_ende() or timezone.localdate()).isoformat(),
            'embed_base': ('fw/base_embed.html' if embed else None),
        })

    ziel = request.POST.get('ziel', 'an')
    weiter = request.POST.get('weiter') or '/neu/mieterwechsel/'
    if ziel == 'aus':
        e.zur_ausschreibung = False
        e.save(update_fields=['zur_ausschreibung'])
        log_aktion(request, "Ausschreibung beendet", str(e), '')
        messages.success(request, "Ausschreibung beendet.")
        return redirect(weiter)

    # Verfügbarkeitsdatum: aus Formular, sonst aus der Kündigung
    try:
        vd = date.fromisoformat(request.POST.get('verfuegbar_ab') or '')
    except Exception:
        vd = None
    e.verfuegbar_ab = vd or e.verfuegbar_ab or _kuendigung_ende()
    notiz = request.POST.get('notiz', '').strip()
    if notiz:
        e.ausschreibung_notiz = notiz
    e.zur_ausschreibung = True
    e.save(update_fields=['zur_ausschreibung', 'verfuegbar_ab', 'ausschreibung_notiz'])
    # 'Nachmieter suchen'-Pendenz des ausziehenden Vertrags automatisch abhaken
    k = (Kuendigung.objects.filter(vertrag__einheit=e, status__in=['erfasst', 'bestaetigt'])
         .select_related('vertrag').order_by('per_datum', 'berechneter_termin').first())
    if k and k.vertrag_id:
        from core.services.automation import erledige_pendenzen_fuer
        erledige_pendenzen_fuer(k.vertrag, ['Nachmieter', 'Inserat'], user=request.user)
    log_aktion(request, "Objekt ausgeschrieben", str(e),
               f"verfügbar ab {e.verfuegbar_ab or '—'}")
    if request.POST.get('embed'):
        return render(request, 'fw/_modal_done.html', {'msg': 'Objekt ausgeschrieben'})
    messages.success(request, "✅ Objekt zur Nachmietersuche ausgeschrieben — erscheint jetzt in der Vermarktung.")
    return redirect(weiter)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vermarktung(request):
    """Vermarktungsliste: alle ausgeschriebenen Objekte mit Eckdaten, Verfügbarkeit
    und Bewerbungsstand — die Nachmietersuche auf einen Blick."""
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    qs = (Einheit.objects.filter(zur_ausschreibung=True)
          .select_related('liegenschaft').prefetch_related('fotos')
          .order_by('verfuegbar_ab', 'liegenschaft__strasse'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    heute = timezone.localdate()
    rows = []
    for e in qs:
        lg = e.liegenschaft
        bew = list(Mietbewerbung.objects.filter(einheit=e).exclude(status='abgelehnt'))
        _fotos = list(e.fotos.all())
        rows.append({
            'e': e, 'liegenschaft': lg,
            'titelbild': _fotos[0].bild.url if _fotos else None,
            'fotos_n': len(_fotos),
            'objekt': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else e.bezeichnung),
            'bezeichnung': e.bezeichnung,
            'zimmer': e.zimmer, 'flaeche': e.flaeche_m2,
            'miete': (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0')),
            'netto': e.nettomiete_aktuell, 'nk': e.nebenkosten_aktuell,
            'verfuegbar_ab': e.verfuegbar_ab,
            'frei': (e.verfuegbar_ab is None or e.verfuegbar_ab <= heute),
            'bewerbungen': len(bew),
            'notiz': e.ausschreibung_notiz,
        })
    return render(request, 'fw/vermarktung.html', {
        **basis, **_vermietung_pipeline('vermarktung', basis['lg_query']), 'nav': 'vermarktung', 'rows': rows, 'anzahl': len(rows),
        'summe_bewerbungen': sum(r['bewerbungen'] for r in rows),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_expose_pdf(request, pk):
    """Exposé/Inserat (PDF) für ein Mietobjekt — Eckdaten, Mietzins, Kontakt."""
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.expose import generate_expose_pdf, objekt_titel
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=pk)
    pdf = generate_expose_pdf(e, e.liegenschaft.organisation)
    resp = HttpResponse(pdf, content_type='application/pdf')
    lg = e.liegenschaft
    fname = f"Expose_{(lg.strasse if lg else e.bezeichnung)}".replace(' ', '_').replace('/', '-')
    resp['Content-Disposition'] = f'inline; filename="{fname}.pdf"'
    return resp


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_stub(request, titel, icon, text, nav=''):
    basis = _global_filter(request)
    return render(request, 'fw/stub.html', {**basis, 'nav': nav, 'titel': titel, 'icon': icon, 'text': text})


PLATZHALTER_HILFE = [
    ('{mieter_name}', 'Name des Mieters'),
    ('{mieter_adresse}', 'Adresse des Mieters'),
    ('{objekt}', 'Objektbezeichnung'),
    ('{liegenschaft}', 'Strasse der Liegenschaft'),
    ('{vermieter}', 'Name der Verwaltung / des Vermieters'),
    ('{datum}', 'Heutiges Datum'),
    ('{miete}', 'Bruttomietzins'),
    # Schadensfall-/Ticket-Vorlagen
    ('{handwerker}', 'Beauftragte Handwerkerfirma (Schaden)'),
    ('{melder_name}', 'Name des Melders (Schaden)'),
    ('{melder_tel}', 'Telefon des Melders (Schaden)'),
    ('{schaden}', 'Titel des Schadens'),
    ('{ticket_id}', 'Ticket-Nummer'),
    ('{status}', 'Aktueller Ticket-Status'),
]

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vorlagen(request):
    from crm.models import Vorlage
    basis = _global_filter(request)
    vorlagen = Vorlage.objects.all()
    return render(request, 'fw/vorlagen.html', {**basis, 'nav': 'vorlagen', 'vorlagen': vorlagen})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlagen_standard(request):
    """Legt die vorbelegten Standardvorlagen an (fehlende), die dann editierbar sind."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.vorlagen_defaults import seed_standard_vorlagen
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_vorlagen')
    n = seed_standard_vorlagen()
    log_aktion(request, "Standardvorlagen erstellt", f"{n} neu", '')
    if n:
        messages.success(request, f"✅ {n} Standardvorlage(n) erstellt — jederzeit unter 'Bearbeiten' anpassbar.")
    else:
        messages.success(request, "Alle Standardvorlagen sind bereits vorhanden.")
    return redirect('fw_vorlagen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_form(request, pk=None):
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Vorlage
    from core.auth import log_aktion, snapshot_model, diff_model
    vl = get_object_or_404(Vorlage, id=pk) if pk else None
    basis = _global_filter(request)
    if request.method == 'POST':
        alt_snap = snapshot_model(Vorlage.objects.get(pk=pk)) if pk else {}

        # KOPIE STATT UEBERSCHREIBEN BEI SYSTEMVORLAGEN (Etappe 6.4).
        #
        # Eine Vorlage mit `organisation IS NULL` ist mitgeliefert und gilt fuer
        # ALLE Verwaltungen. Sie hier zu speichern hiesse, den Text bei jeder
        # anderen Verwaltung mitzuaendern — ein Schreibzugriff ueber die
        # Mandantengrenze, ausgeloest durch ein gewoehnliches Bearbeiten-Formular.
        # Stattdessen entsteht eine eigene Fassung; das Original bleibt, wie es
        # ist, und kuenftige Korrekturen daran erreichen weiterhin alle, die
        # keine eigene angelegt haben.
        if vl is not None and vl.organisation_id is None:
            obj = Vorlage()
            alt_snap = {}
        else:
            obj = vl or Vorlage()
        # Die Zuordnung zur eigenen Verwaltung macht `Vorlage.save()` — dort
        # gilt sie fuer JEDEN Aufrufer, nicht nur fuer dieses Formular.
        obj.name = request.POST.get('name', '').strip()
        obj.kategorie = request.POST.get('kategorie', 'brief')
        obj.betreff = request.POST.get('betreff', '').strip()
        obj.inhalt = request.POST.get('inhalt', '')
        if not obj.name:
            messages.error(request, "Bezeichnung ist erforderlich.")
            return redirect(request.path)
        obj.save()
        kopiert = pk and (vl is not None and vl.organisation_id is None)
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if (pk and not kopiert) else ''
        log_aktion(request, "Vorlage bearbeitet" if (pk and not kopiert) else "Vorlage erstellt",
                   obj.name, _diff)
        if kopiert:
            messages.success(
                request, f"✅ Eigene Fassung von '{obj.name}' angelegt. "
                         f"Die mitgelieferte Vorlage bleibt unverändert.")
        else:
            messages.success(request, f"✅ Vorlage '{obj.name}' gespeichert.")
        return redirect('/neu/vorlagen/')
    return render(request, 'fw/vorlage_form.html', {
        **basis, 'nav': 'vorlagen', 'vl': vl, 'ist_neu': vl is None,
        'kategorien': Vorlage.KATEGORIE_CHOICES, 'platzhalter': PLATZHALTER_HILFE,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_loeschen(request, pk):
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Vorlage
    from core.auth import log_aktion
    vl = get_object_or_404(Vorlage, id=pk)
    if vl.organisation_id is None:
        # Eine mitgelieferte Vorlage gehoert keiner Verwaltung — sie zu loeschen
        # naehme sie allen weg. Wer sie nicht mag, legt eine eigene Fassung an.
        messages.error(request, "Mitgelieferte Vorlagen lassen sich nicht löschen. "
                                "Sie können sie bearbeiten — dabei entsteht eine eigene Fassung.")
        return redirect('/neu/vorlagen/')
    if request.method == 'POST':
        name = vl.name
        log_aktion(request, "Vorlage gelöscht", name, '')
        vl.delete()
        messages.success(request, f"🗑️ Vorlage '{name}' gelöscht.")
    return redirect('/neu/vorlagen/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_integrationen(request):
    from django.conf import settings as dj_settings
    basis = _global_filter(request)

    def gesetzt(key):
        return bool(getattr(dj_settings, key, None))

    email_ok = gesetzt('EMAIL_HOST_USER') and gesetzt('EMAIL_HOST_PASSWORD')
    integrationen = [
        {'key': 'email', 'name': 'E-Mail-Versand', 'icon': 'fa-envelope', 'farbe': 'indigo',
         'aktiv': email_ok, 'status': 'Verbunden' if email_ok else 'Nicht konfiguriert',
         'beschreibung': 'Versende Mahnungen, Abrechnungen und Anschreiben direkt aus swissImmo über deinen SMTP-Server.',
         'detail': (getattr(dj_settings, 'EMAIL_HOST', '') or '') if email_ok else 'E-Mail-Zugangsdaten in den Servereinstellungen hinterlegen.',
         'aktion': 'test_email' if email_ok else None},
        {'key': 'docuseal', 'name': 'DocuSeal — digitale Signatur', 'icon': 'fa-file-signature', 'farbe': 'emerald',
         'aktiv': gesetzt('DOCUSEAL_API_KEY'), 'status': 'Verbunden' if gesetzt('DOCUSEAL_API_KEY') else 'Nicht konfiguriert',
         'beschreibung': 'Sende Mietverträge zur rechtsgültigen elektronischen Unterschrift. Der Rücklauf wird automatisch als unterzeichnetes PDF abgelegt.',
         'detail': 'Nutzbar über „An DocuSeal senden" auf der Vertrags-Detailseite.' if gesetzt('DOCUSEAL_API_KEY') else 'DOCUSEAL_API_KEY hinterlegen.',
         'aktion': None},
        {'key': 'ki', 'name': 'KI-Rechnungsscanner', 'icon': 'fa-robot', 'farbe': 'violet',
         'aktiv': gesetzt('GROQ_API_KEY'), 'status': 'Verbunden' if gesetzt('GROQ_API_KEY') else 'Nicht konfiguriert',
         'beschreibung': 'Kreditoren-Belege beim Hochladen automatisch auslesen (Lieferant, Betrag, IBAN, QR-Referenz) — inkl. Foto-Belegen via Bild-KI und E-Mail-Eingang für Handwerker-Rechnungen.',
         'detail': (('Nutzbar unter Kreditoren → «Beleg scannen (KI)» (Mehrfach-Upload). '
                     + (f"E-Mail-Eingang aktiv: {os.environ.get('RECHNUNGS_IMAP_USER')} (fetch_rechnungen)."
                        if os.environ.get('RECHNUNGS_IMAP_USER')
                        else 'E-Mail-Eingang: RECHNUNGS_IMAP_USER/PASSWORD setzen + Scheduled Task «manage.py fetch_rechnungen --einmal».'))
                    if gesetzt('GROQ_API_KEY')
                    else 'GROQ_API_KEY hinterlegen — ohne Key läuft nur die regelbasierte Erkennung aus Text-PDFs.'),
         'aktion': None},
        {'key': 'bank', 'name': 'Banken-Abgleich (camt.053 / QR)', 'icon': 'fa-building-columns', 'farbe': 'sky',
         'aktiv': True, 'status': 'Aktiv',
         'beschreibung': 'Importiere camt.053-Kontoauszüge und ordne Zahlungseingänge automatisch per QR-Referenz den Debitoren zu.',
         'detail': 'Nutzbar im Bereich Bankabgleich.',
         'aktion': 'bank_link'},
    ]
    # Vermarktungs-Portale (Objekt-Feed)
    from crm.models import Organisation
    from portfolio.models import Einheit
    vw = aktuelle_organisation()
    token = (vw.portal_feed_token if vw else '') or ''
    feed_pfad = f"/neu/vermarktung/feed.json?token={token}" if token else ''
    ausgeschrieben_n = Einheit.objects.filter(zur_ausschreibung=True).count()
    return render(request, 'fw/integrationen.html', {
        **basis, 'nav': 'integrationen', 'integrationen': integrationen,
        'portal_token': token, 'portal_feed_pfad': feed_pfad,
        'portal_ausgeschrieben_n': ausgeschrieben_n,
    })


def fw_vermarktung_feed(request):
    """Öffentlicher, token-gesicherter Objekt-Feed für Immobilien-Portale
    (Homegate, ImmoScout24/SMG, Flatfox …). ?format=csv für CSV, sonst JSON.

    Kein Login — die Absicherung erfolgt über ?token= (Verwaltung.portal_feed_token).
    """
    from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
    from crm.models import Organisation
    from core.services.portal_feed import feed_objekte, feed_csv_rows
    import csv as _csv
    import io

    import hmac
    # DER TOKEN BESTIMMT DIE VERWALTUNG — nicht umgekehrt.
    #
    # Vorher wurde er gegen den Token der ERSTEN Organisation gehalten. Das ist
    # die falsche Richtung, und sie geht auf zwei Arten schief: Der Token der
    # zweiten Verwaltung wird abgewiesen, obwohl er gültig ist — und wer den
    # Token der ersten hat, bekam anschliessend die Ausschreibungen ALLER
    # Verwaltungen geliefert, weil `feed_objekte()` ungefiltert las.
    #
    # Die Schleife statt einer `filter(portal_feed_token=…)`-Abfrage: So bleibt
    # der konstant-zeitige Vergleich erhalten, der einen Timing-Seitenkanal
    # beim Token-Raten verhindert. Bei einer Handvoll Verwaltungen kostet das
    # nichts.
    token = request.GET.get('token', '')
    vw = None
    if token:
        for kandidat in Organisation.objects.exclude(portal_feed_token='').exclude(
                portal_feed_token__isnull=True):
            if hmac.compare_digest(str(token), str(kandidat.portal_feed_token)):
                vw = kandidat
                break
    if vw is None:
        return HttpResponseForbidden("Ungültiger oder fehlender Feed-Token.")

    base = f"{request.scheme}://{request.get_host()}"
    objekte = feed_objekte(base_url=base, organisation=vw)

    if request.GET.get('format') == 'csv':
        buf = io.StringIO()
        w = _csv.writer(buf, delimiter=';')
        for row in feed_csv_rows(objekte):
            w.writerow(row)
        resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="vermarktung_feed.csv"'
        return resp

    return JsonResponse({
        'anbieter': (vw.firma if vw else ''),
        'anzahl': len(objekte),
        'objekte': objekte,
    }, json_dumps_params={'ensure_ascii': False})


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_integration_portal_token(request):
    """Erzeugt/rotiert oder entfernt den Portal-Feed-Token."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Organisation
    from core.auth import log_aktion
    import secrets
    if request.method != 'POST':
        return redirect('/neu/integrationen/')
    vw = aktuelle_organisation()
    if request.POST.get('aktion') == 'entfernen':
        vw.portal_feed_token = ''
        vw.save(update_fields=['portal_feed_token'])
        log_aktion(request, "Portal-Feed deaktiviert", vw.firma, '')
        messages.success(request, "Portal-Feed deaktiviert (Token entfernt).")
    else:
        vw.portal_feed_token = secrets.token_urlsafe(24)
        vw.save(update_fields=['portal_feed_token'])
        log_aktion(request, "Portal-Feed-Token erzeugt", vw.firma, '')
        messages.success(request, "✅ Neuer Portal-Feed-Token erzeugt.")
    return redirect('/neu/integrationen/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_integration_test_email(request):
    """Sendet eine Test-E-Mail an die eigene Adresse."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.core.mail import EmailMessage, get_connection
    from django.conf import settings as dj_settings
    if request.method == 'POST':
        ziel = (request.user.email or getattr(dj_settings, 'EMAIL_HOST_USER', '') or '').strip()
        if not ziel:
            messages.error(request, "Keine Ziel-E-Mail hinterlegt. Bitte im Benutzerprofil eine E-Mail eintragen.")
            return redirect('/neu/integrationen/')
        try:
            # Timeout, damit ein langsamer/nicht erreichbarer SMTP den Request nie blockiert.
            conn = get_connection(timeout=15)
            EmailMessage(
                'swissImmo — Test-E-Mail',
                'Diese Test-E-Mail bestätigt, dass der E-Mail-Versand korrekt konfiguriert ist.\n\nswissImmo',
                getattr(dj_settings, 'DEFAULT_FROM_EMAIL', None),
                [ziel], connection=conn,
            ).send(fail_silently=False)
            messages.success(request, f"✅ Test-E-Mail an {ziel} gesendet.")
        except Exception as e:
            messages.error(request, f"E-Mail-Versand fehlgeschlagen: {e}")
    return redirect('/neu/integrationen/')

# Preisplan-Definition (Single Source of Truth). Preis = pro Einheit/Monat.
ABO_PLAENE = [
    {'key': 'start', 'name': 'Start', 'preis_einheit': Decimal('0.90'),
     'grund': Decimal('9'), 'gratis_bis': 3, 'farbe': 'slate',
     'zielgruppe': 'Selbstverwalter & kleine Eigentümer',
     'features': ['Objekte, Personen & Verträge', 'Vertrags-PDF & Dokumentenablage',
                  'Mieterportal (Dokumente, QR-Rechnung, Schaden, Tickets)',
                  'QR-Rechnung & Kontoauszug'],
     'nicht': ['Buchhaltung & Zahlungsverkehr', 'Nebenkosten & MWST', 'Eigentümerportal']},
    {'key': 'pro', 'name': 'Pro', 'preis_einheit': Decimal('1.90'),
     'grund': Decimal('49'), 'gratis_bis': 0, 'farbe': 'indigo', 'empfohlen': True,
     'zielgruppe': 'Liegenschaftsverwaltungen',
     'features': ['Alles aus Start', 'Buchhaltung, Sollstellung & Mahnwesen',
                  'camt.053-Import / pain.001-Export', 'Nebenkostenabrechnung & MWST',
                  'Mietzinsanpassung (amtl. Formular, LIK/Referenzzins)',
                  'Eigentümerportal & Reports', 'Serienbriefe & Schaden-/Handwerker-Flow'],
     'nicht': ['Multi-Eigentuemer (voll)', 'KI-Analysen', 'API-Zugang']},
    {'key': 'premium', 'name': 'Premium', 'preis_einheit': Decimal('2.90'),
     'grund': Decimal('149'), 'gratis_bis': 0, 'farbe': 'purple',
     'zielgruppe': 'Grössere Verwaltungen & Treuhänder',
     'features': ['Alles aus Pro', 'Multi-Eigentuemer & Mandatsabrechnung',
                  'KI-Analysen & Report-Assistent', 'DocuSeal-Vertragssignatur inkl.',
                  'API-Zugang', 'Prioritäts-Support & Onboarding'],
     'nicht': []},
]


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abonnemente(request):
    """Abo-/Preisseite: 3 Stufen, Preis pro Einheit, aktueller Plan wählbar."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Organisation
    from core.auth import log_aktion, hat_rolle
    vw = aktuelle_organisation()
    basis = _global_filter(request)

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        plan = request.POST.get('plan')
        if plan in dict(Organisation.ABO_CHOICES):
            vw.abo_plan = plan
            vw.abo_jaehrlich = request.POST.get('jaehrlich') == 'on'
            vw.save(update_fields=['abo_plan', 'abo_jaehrlich'])
            log_aktion(request, "Abo-Plan gewählt", plan, 'jährlich' if vw.abo_jaehrlich else 'monatlich')
            messages.success(request, f"✅ Plan «{dict(Organisation.ABO_CHOICES)[plan]}» aktiviert.")
        return redirect('/neu/abonnement/')

    einheiten = Einheit.objects.count()
    jaehrlich = vw.abo_jaehrlich
    plaene = []
    for p in ABO_PLAENE:
        verrechenbar = max(0, einheiten - p['gratis_bis'])
        monatlich = max(p['grund'], p['preis_einheit'] * verrechenbar)
        if jaehrlich:
            monatlich = (monatlich * Decimal('12') * Decimal('0.85') / Decimal('12'))
        plaene.append({
            **p, 'aktiv': vw.abo_plan == p['key'],
            'monatlich': monatlich.quantize(Decimal('1')),
            'jahr': (monatlich * 12).quantize(Decimal('1')),
        })

    return render(request, 'fw/abonnement.html', {
        **basis, 'nav': 'abonnement', 'plaene': plaene, 'einheiten': einheiten,
        'jaehrlich': jaehrlich, 'aktiver_plan': vw.abo_plan,
    })
