# core/views/fw/abnahme.py
#
# Wohnungsabnahme-Protokoll (Einzug/Auszug, fuer das Handy gebaut), dazu
# Vertragsstatus und Vertrag loeschen. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.
#
# Enthaelt die Maengelruege nach Art. 267a OR — eine Frist, an der nichts
# geraten werden darf (Skill schweizer-fachlogik). Der Umzug aendert daran
# nichts: Der Blockinhalt ist gegen HEAD Zeile fuer Zeile geprueft.

from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN, TEAM_ROLLEN
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num, _parse_adresse


# ============================================================
# WOHNUNGSABNAHME-PROTOKOLL (Einzug/Auszug, mobil)
# ============================================================
ABNAHME_RAEUME = ['Eingang/Korridor', 'Wohnzimmer', 'Küche', 'Bad/WC', 'Zimmer 1',
                  'Zimmer 2', 'Zimmer 3', 'Balkon/Terrasse', 'Keller', 'Estrich', 'Allgemein']


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_neu(request, vertrag_id):
    """Wohnungsabnahme erfassen (mobil): Zustand, Mängel je Raum mit Verursacher,
    Fotos, Zählerstände, Unterschriften."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll, AbnahmeMangel
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST

        def _dec(x):
            try:
                return Decimal(_num(x)) if str(x).strip() else None
            except Exception:
                return None
        try:
            datum = date.fromisoformat(P.get('datum') or '')
        except Exception:
            datum = timezone.localdate()
        prot = Abnahmeprotokoll.objects.create(
            vertrag=v, typ=P.get('typ', 'auszug'), datum=datum,
            mieter_anwesend=P.get('mieter_anwesend') == 'on',
            verwalter_name=P.get('verwalter_name', '').strip(),
            allgemein_zustand=P.get('allgemein_zustand', 'gut'),
            schluessel_anzahl=int(P.get('schluessel_anzahl')) if (P.get('schluessel_anzahl') or '').isdigit() else None,
            zaehler_strom=P.get('zaehler_strom', '').strip(),
            zaehler_wasser=P.get('zaehler_wasser', '').strip(),
            zaehler_gas=P.get('zaehler_gas', '').strip(),
            neue_adresse=P.get('neue_adresse', '').strip(),
            bemerkungen=P.get('bemerkungen', '').strip(),
            unterschrift_mieter=P.get('unterschrift_mieter', '').strip(),
            unterschrift_verwalter=P.get('unterschrift_verwalter', '').strip(),
            abgeschlossen=P.get('abgeschlossen') == 'on',
        )
        # Mängel-Zeilen (parallele Listen). Fotos werden in Reihenfolge zugeordnet
        # (leere Datei-Inputs liefert der Browser nicht mit).
        raeume = P.getlist('m_raum')
        beschr = P.getlist('m_beschreibung')
        verurs = P.getlist('m_verursacher')
        kosten = P.getlist('m_kosten')
        assets = P.getlist('m_ausstattung')
        neuwerte = P.getlist('m_neuwert')
        fotos = list(request.FILES.getlist('m_foto'))
        from portfolio.models import Ausstattung as _Ausstattung
        for i, b in enumerate(beschr):
            b = (b or '').strip()
            if not b:
                continue
            aid = (assets[i] if i < len(assets) else '').strip()
            element = None
            if aid.isdigit():
                element = _Ausstattung.objects.filter(id=int(aid), einheit=v.einheit).first()
            nw = _dec(neuwerte[i] if i < len(neuwerte) else '')
            if nw is None and element is not None:
                nw = element.neuwert
            mangel = AbnahmeMangel(
                protokoll=prot,
                raum=(raeume[i] if i < len(raeume) else '').strip(),
                beschreibung=b,
                verursacher=(verurs[i] if i < len(verurs) else 'abnutzung'),
                kostenschaetzung=_dec(kosten[i] if i < len(kosten) else ''),
                ausstattung=element,
                neuwert=nw,
                foto=(fotos.pop(0) if fotos else None),
            )
            # Mieteranteil nach Lebensdauertabelle berechnen und einfrieren
            mangel.mieteranteil = mangel.berechne_mieteranteil(stichtag=datum)
            mangel.save()
        # Passende Auszugs-Pendenzen automatisch abhaken
        if prot.typ == 'auszug':
            from core.services.automation import erledige_pendenzen_fuer
            kw = ['Wohnungsabnahme', 'Abnahmetermin']
            if prot.zaehler_strom or prot.zaehler_wasser or prot.zaehler_gas:
                kw.append('Zählerstände')
            if prot.schluessel_anzahl is not None:
                kw.append('Schlüssel')
            # Ohne dem Mieter zugeordnete Mängel gibt es nichts zu rügen — die
            # 267a-Frist-Pendenz ist dann gegenstandslos. Mit Mieter-Mängeln
            # bleibt sie offen, bis die Rüge (fw_abnahme_ruege_267a) erzeugt ist.
            if not prot.maengel.filter(verursacher='mieter').exists():
                kw.append('Mängelrüge Art. 267a')
            erledige_pendenzen_fuer(v, kw, user=request.user)
            # Neue Wohnadresse ab Auszugsdatum als datierte Adress-Zeile hinterlegen
            # (Wegzug-Adresse) — für Haupt- und Mitmieter. Wird zum Stichtag zur
            # effektiven Zustelladresse (Nachsendung an die neue Adresse).
            neue_adr = (prot.neue_adresse or '').strip()
            if neue_adr:
                from crm.models import MieterAdresse
                strasse, plz, ort = _parse_adresse(neue_adr)
                for person in (v.mieter, v.mitmieter):
                    if not person:
                        continue
                    MieterAdresse.objects.get_or_create(
                        mieter=person, art='wohn', gueltig_ab=datum,
                        defaults=dict(strasse=strasse, plz=plz, ort=ort,
                                      quelle=f'auszug:{prot.id}',
                                      notiz='Wegzug gemäss Abnahmeprotokoll'))
                    person.sync_effektive_adresse()
        log_aktion(request, "Wohnungsabnahme erfasst", str(v.mieter), f"{prot.get_typ_display()} {datum}", ziel=v)
        if P.get('embed'):
            typ_txt = prot.get_typ_display()
            return render(request, 'fw/_modal_done.html', {'msg': f"{typ_txt} erfasst ({prot.maengel.count()} Mängel)"})
        messages.success(request, f"✅ Abnahmeprotokoll erfasst ({prot.maengel.count()} Mängel).")
        return redirect(f'/neu/abnahme/{prot.id}/')

    embed = request.GET.get('embed') == '1'
    from portfolio.models import Ausstattung
    elemente = list(Ausstattung.objects.filter(einheit=v.einheit))
    return render(request, 'fw/abnahme_neu.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'raeume': ABNAHME_RAEUME,
        'elemente': elemente,
        'heute': timezone.localdate().isoformat(),
        'verwalter_default': (request.user.get_full_name() or request.user.username),
        'typ_default': (request.GET.get('typ') if request.GET.get('typ') in ('auszug', 'einzug')
                        else ('auszug' if v.status in ('gekuendigt', 'archiviert') else 'einzug')),
        'embed_base': ('fw/base_embed.html' if embed else None),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_detail(request, pk):
    from rentals.models import Abnahmeprotokoll
    basis = _global_filter(request)
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    return render(request, 'fw/abnahme_detail.html', {
        **basis, 'nav': 'vertraege', 'p': prot, 'v': prot.vertrag,
        'maengel': prot.maengel.all(),
        'hat_mieter_maengel': any(m.verursacher == 'mieter' for m in prot.maengel.all()),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_ruege_267a(request, pk):
    """Sofortige Mängelrüge nach Rückgabe (Art. 267a OR) aus dem Auszugs-
    Abnahmeprotokoll: rügt alle dem Mieter zugeordneten Mängel schriftlich —
    muss SOFORT nach der Abnahme versendet werden, sonst verwirken die
    Ersatzansprüche. Legt das PDF ab und hakt die Checklisten-Pendenz ab."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from crm.models import Organisation
    from core.services.mietprozess_briefe import rueckgabe_maengelruege_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    v = prot.vertrag
    maengel = [{'raum': m.raum, 'beschreibung': m.beschreibung,
                'betrag': (m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung)}
               for m in prot.maengel.all() if m.verursacher == 'mieter']
    if not maengel:
        messages.info(request, "Keine dem Mieter zugeordneten Mängel im Protokoll — keine Rüge nötig.")
        return redirect(f'/neu/abnahme/{prot.id}/')
    pdf = rueckgabe_maengelruege_pdf(v, maengel, verwaltung=v.organisation,
                                     abnahme_datum=prot.datum)
    ablegen(pdf, f"Mängelrüge Art. 267a {prot.datum:%d.%m.%Y}",
            kategorie='vertrag', vertrag=v, dedup=True)
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(v, ['Mängelrüge Art. 267a'], user=request.user)
    log_aktion(request, "Mängelrüge Art. 267a erstellt", str(v.mieter),
               f"{len(maengel)} Mängel", ziel=v)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Maengelruege_267a_{v.mieter.nachname}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_loeschen(request, pk):
    """Abnahmeprotokoll löschen (inkl. Mängel-Positionen)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag'), id=pk)
    vid = prot.vertrag_id
    if request.method == 'POST':
        log_aktion(request, "Abnahmeprotokoll gelöscht", str(prot.vertrag) if vid else '', '')
        prot.delete()
        messages.success(request, "🗑️ Abnahmeprotokoll gelöscht.")
    return redirect(f'/neu/vertraege/{vid}/' if vid else '/neu/vertraege/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_pdf(request, pk):
    from django.http import HttpResponse
    from rentals.models import Abnahmeprotokoll
    from crm.models import Organisation
    from core.services.abnahme_pdf import generate_abnahme_pdf
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    pdf = generate_abnahme_pdf(prot, verwaltung=prot.organisation)
    # Auto-Ablage in die Vertrags-Akte (abgeschlossene Protokolle)
    if getattr(prot, 'abgeschlossen', False):
        from core.services.ablage import ablegen
        ablegen(pdf, f"Abnahmeprotokoll ({prot.get_typ_display()}) {prot.datum:%d.%m.%Y}",
                kategorie='protokoll', vertrag=prot.vertrag, dedup=True)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Abnahmeprotokoll_{prot.vertrag.mieter.nachname}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_status(request, pk):
    """Setzt den Vertragsstatus: entwurf / aktiv / archiviert (inaktiv)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    if request.method == 'POST':
        neu = request.POST.get('status', '')
        erlaubt = {'entwurf': 'Entwurf', 'aktiv': 'Aktiv', 'archiviert': 'Inaktiv / Archiviert'}
        if neu in erlaubt:
            v.status = neu
            v.aktiv = (neu == 'aktiv')
            v.save(update_fields=['status', 'aktiv'])
            # Aktives Mietverhältnis → Objekt aus der Vermarktung/Feed nehmen.
            if neu == 'aktiv' and v.einheit_id and v.einheit.zur_ausschreibung:
                v.einheit.zur_ausschreibung = False
                v.einheit.save(update_fields=['zur_ausschreibung'])
            log_aktion(request, "Vertragsstatus geändert", str(v.mieter), erlaubt[neu], ziel=v)
            messages.success(request, f"✅ Vertrag ist jetzt: {erlaubt[neu]}.")
        else:
            messages.error(request, "Unbekannter Status.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_vertrag_loeschen(request, pk):
    """Löscht einen Mietvertrag. Verknüpfte Rechnungen/Zahlungen bleiben erhalten
    (FK on_delete=SET_NULL) — die revisionssichere Buchhaltung wird nicht zerstört."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    if request.method == 'POST':
        name = str(v.mieter)
        einheit = v.einheit.bezeichnung
        log_aktion(request, "Mietvertrag gelöscht", name, einheit)
        # Bereinigung der verwaisten Vertragspaket-Dokumente passiert zentral in
        # Mietvertrag.delete() (greift auch auf dem API-Löschpfad).
        v.delete()
        messages.success(request, f"🗑️ Vertrag ({name} · {einheit}) wurde gelöscht.")
        return redirect('/neu/vertraege/')
    return redirect(f'/neu/vertraege/{v.id}/')
