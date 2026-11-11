# core/views/fw/dokument_zustellung.py
#
# Zustellnachweis zu Dokumenten.
# Aus kuendigung.py herausgeloest (reiner Umzug ohne Aenderung am Code).

import re
from datetime import date

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.auth import (rolle_erforderlich, SCHREIB_ROLLEN)

from core.services.zahlungsverzug import ABHOLFRIST_TAGE, FRIST_TAGE, POSTWEG_TAGE
from .verzug_257d import _zugang_aus_formular, _zugang_setzen


def _datum_oder_none(wert):
    try:
        return date.fromisoformat(wert) if wert else None
    except ValueError:
        return None


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_zustellung(request, pk):
    """Sendungsnummer, Versanddatum und Zugang eines 257d-Schreibens erfassen — direkt am Dokument.

    Für das Schreiben, das aus dem Mahnwesen («Erfassen» der Stufe mit Kündigungsandrohung)
    abgelegt wurde und noch keine Fristen-Pendenz hat: Die Pendenz wird hier angelegt (Frist
    PROVISORISCH ab Versand, definitiv ab bestätigtem Zugang), die Vorschlags-Pendenz
    «Fristansetzung prüfen» wird erledigt, der Fall «Zahlungsverzug» führt die Frist nach.
    Hat das Schreiben schon eine Pendenz (Weg über die Vertragsakte), wird sie ergänzt.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from datetime import timedelta
    from core.models import Pendenz
    from core.auth import log_aktion
    from core.services.zahlungsverzug import (aktive_fristen, fall_eroeffnen, quelle_fuer,
                                              vorschlaege_erledigen, fall_frist_nachfuehren)
    from rentals.models import Dokument

    d = get_object_or_404(Dokument.objects.select_related('vertrag__mieter', 'vertrag__einheit'), pk=pk)
    v = d.vertrag
    nxt = request.POST.get('next') or ''
    ziel = nxt if nxt.startswith('/neu/') and '//' not in nxt[1:] else (
        f'/neu/vertraege/{v.pk}/' if v else '/neu/dokumente/')
    if request.method != 'POST' or v is None:
        return redirect(ziel)
    if not d.zugang_pflichtig:
        # Älteres Mahnschreiben mit Kündigungsandrohung, abgelegt vor den Zustellnachweisen:
        # Es wird beim Erfassen als Schreiben mit nachzuweisendem Zugang geführt.
        titel = d.titel or ''
        if not (re.match(r'\d+\. Mahnung', titel) or '257d' in titel):
            return redirect(ziel)
        d.zugang_pflichtig = True      # gespeichert erst nach der Eingabeprüfung

    heute = timezone.localdate()
    sendungsnummer = (request.POST.get('sendungsnummer') or '').strip()[:40]
    versand_am = _datum_oder_none(request.POST.get('versand_am'))
    zugang_am = _datum_oder_none(request.POST.get('zugang_am'))
    if (versand_am and versand_am > heute) or (zugang_am and zugang_am > heute):
        messages.error(request, gettext('Versand- und Zugangsdatum können nicht in der Zukunft liegen.'))
        return redirect(ziel)

    p = d.zustell_pendenz() or aktive_fristen(v).first()
    if not (sendungsnummer or versand_am or zugang_am or (p and (p.sendungsnummer or p.versand_am))):
        messages.error(request, gettext('Bitte Sendungsnummer, Versand- oder Zugangsdatum angeben.'))
        return redirect(ziel)
    # Zugang: Abholung/Zustellung, oder Abholeinladung eines nicht abgeholten Einschreibens (dann fingiert auf
    # den letzten Tag der Abholfrist, BGE 119 II 147 E. 2).
    zugang_fingiert = False
    if zugang_am:
        zugang_am, zugang_fingiert, fehler = _zugang_aus_formular(
            request.POST, versand_am or (p.versand_am if p else None), heute)
        if fehler:
            messages.error(request, '⛔ ' + fehler)
            return redirect(ziel)

    if d.zugang_pflichtig and not Dokument.objects.filter(pk=d.pk, zugang_pflichtig=True).exists():
        d.save(update_fields=['zugang_pflichtig'])
    from core.services.zahlungsverzug import definitives_fristende, provisorisches_fristende
    benutzer = request.user if request.user.is_authenticated else None
    neu = p is None
    if neu:
        lg = v.einheit.liegenschaft if v.einheit_id else None
        frist = (definitives_fristende(zugang_am, FRIST_TAGE) if zugang_am
                 else provisorisches_fristende(versand_am or heute, FRIST_TAGE))
        p = Pendenz.objects.create(
            titel=f"Art. 257d: Zahlungsfrist läuft ab – {v.mieter.display_name}",
            beschreibung="Mahnung mit Kündigungsandrohung (Art. 257d OR) per Einschreiben.",
            quelle=quelle_fuer(v), kategorie='frist', faellig_am=frist, vertrag=v, liegenschaft=lg,
            frist_tage=FRIST_TAGE, erstellt_von=benutzer)
    if sendungsnummer:
        p.sendungsnummer = sendungsnummer
    if versand_am and not p.zugang_am:
        p.versand_am = versand_am
    if not p.zugang_am:
        # Frist bleibt PROVISORISCH, bis der Zugang bestätigt ist.
        vs = p.versand_am or heute
        p.faellig_am = provisorisches_fristende(vs, p.frist_tage)
        p.beschreibung = (
            f"Einschreiben {p.sendungsnummer or '—'}"
            + (f", versandt {p.versand_am:%d.%m.%Y}" if p.versand_am else "")
            + f". PROVISORISCH bis {p.faellig_am:%d.%m.%Y} — gerechnet vom spätestmöglichen Zugang (Versand + "
              f"{POSTWEG_TAGE} Tag Postweg + {ABHOLFRIST_TAGE} Tage Abholfrist + {p.frist_tage or FRIST_TAGE} Tage). "
              f"Die definitive {p.frist_tage or FRIST_TAGE}-Tage-Frist läuft ab bestätigtem Zugang (Abholung, bei "
              "Nichtabholung letzter Tag der Abholfrist; BGE 119 II 147). Nach fruchtlosem Ablauf: "
              "ausserordentliche Kündigung mit 30 Tagen auf Monatsende (Art. 257d Abs. 2 OR).")
    p.save()
    if zugang_am:
        _zugang_setzen(p, zugang_am, fingiert=zugang_fingiert)
    if d.frist_pendenz_id != p.pk:
        d.frist_pendenz_id = p.pk
        d.save(update_fields=['frist_pendenz_id'])
    if neu:
        vorschlaege_erledigen(v, 'Mahnung mit Kündigungsandrohung per Einschreiben versandt.')
        fall_eroeffnen(v, benutzer=benutzer, frist=p.faellig_am,
                       betreff=f"Zahlungsverzug {v.mieter.display_name}")
    else:
        fall_frist_nachfuehren(v, p.faellig_am)
    log_aktion(request, "257d-Zustellung erfasst", str(v.mieter),
               f"Einschreiben {p.sendungsnummer or '—'}"
               + (f", Zugang {zugang_am:%d.%m.%Y}{' (fingiert, nicht abgeholt)' if zugang_fingiert else ''}"
                  if zugang_am else ", Zugang offen")
               + f", Frist bis {p.faellig_am:%d.%m.%Y}", ziel=v)
    if zugang_am:
        messages.success(request, '✅ ' + gettext('Zugang bestätigt (%(d)s) — Zahlungsfrist läuft bis %(f)s (Art. 257d Abs. 1 OR).')
                         % {'d': f'{zugang_am:%d.%m.%Y}', 'f': f'{p.faellig_am:%d.%m.%Y}'})
    else:
        messages.success(request, '✅ ' + gettext('Einschreiben erfasst — Frist provisorisch bis %(f)s. Zugang bestätigen, sobald die Zustellung feststeht.')
                         % {'f': f'{p.faellig_am:%d.%m.%Y}'})
    return redirect(ziel)
