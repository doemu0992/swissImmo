# core/views/fw/kommunikation.py
#
# Mitteilungs-Assistent mit Live-Vorschau. Etappe 1, siehe
# docs/ETAPPE-1-ZERLEGEN.md.

from django.shortcuts import render

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from rentals.models import Mietvertrag

from ._basis import _global_filter


# ============================================================
# ETAPPE D: KOMMUNIKATION (Mitteilungs-Assistent mit Live-Vorschau)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kommunikation(request):
    from crm.models import Verwaltung, Vorlage
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = Verwaltung.objects.first()
    absender = {
        'firma': vw.firma if vw else 'Meine Verwaltung',
        'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }
    logo_url = ''
    if vw and getattr(vw, 'logo', None):
        try:
            logo_url = vw.logo.url
        except Exception:
            logo_url = ''

    vorlagen = [{'id': v.id, 'name': v.name, 'betreff': v.betreff, 'inhalt': v.inhalt,
                 'kategorie': v.get_kategorie_display()} for v in Vorlage.objects.all()]

    # Empfänger = Mieter mit aktivem Vertrag (im Filter-Scope)
    vertraege = (Mietvertrag.objects.filter(status='aktiv')
                 .select_related('mieter', 'einheit__liegenschaft'))
    if aktive_lg:
        vertraege = vertraege.filter(einheit__liegenschaft=aktive_lg)

    empfaenger = []
    gesehen = set()
    lg_map = {}
    for v in vertraege:
        m = v.mieter
        if m.id in gesehen:
            continue
        gesehen.add(m.id)
        lg = v.einheit.liegenschaft
        lg_label = f"{lg.strasse}, {lg.ort}"
        lg_map[lg.id] = lg_label
        empfaenger.append({
            'id': m.id, 'name': m.display_name,
            'anrede': m.anrede or '',
            'strasse': m.strasse or lg.strasse,
            'plz': m.plz or lg.plz, 'ort': m.ort or lg.ort,
            'email': m.email or '',
            'objekt': f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}",
            'lg_id': lg.id, 'lg_label': lg_label,
        })
        # Mitmieter (Ehe-/Wohnpartner mit eigenem Mieter-Datensatz) separat
        # adressieren — er ist Vertragspartei und muss z. B. bei Familienwohnungen
        # eigene Post erhalten; bisher fiel er aus dem Serienbrief.
        if v.mitmieter_id and v.mitmieter_id not in gesehen:
            gesehen.add(v.mitmieter_id)
            mm = v.mitmieter
            empfaenger.append({
                'id': mm.id, 'name': mm.display_name,
                'anrede': mm.anrede or '',
                'strasse': mm.strasse or lg.strasse,
                'plz': mm.plz or lg.plz, 'ort': mm.ort or lg.ort,
                'email': mm.email or '',
                'objekt': f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}",
                'lg_id': lg.id, 'lg_label': lg_label,
            })
    empfaenger.sort(key=lambda e: e['name'])
    liegenschaften_wahl = [{'id': k, 'label': lbl} for k, lbl in sorted(lg_map.items(), key=lambda kv: kv[1])]

    # ?mieter=<id>: Empfänger vorauswählen (E-Mail-Button auf der Personenseite)
    try:
        vorwahl_mieter = int(request.GET.get('mieter') or 0)
    except (TypeError, ValueError):
        vorwahl_mieter = 0

    return render(request, 'fw/kommunikation.html', {
        **basis, 'nav': 'kommunikation',
        'absender': absender, 'empfaenger': empfaenger,
        'anzahl_empfaenger': len(empfaenger),
        'liegenschaften_wahl': liegenschaften_wahl,
        'vorlagen': vorlagen, 'logo_url': logo_url,
        'vorwahl_mieter': vorwahl_mieter,
    })
