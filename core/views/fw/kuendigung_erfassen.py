# core/views/fw/kuendigung_erfassen.py
#
# Kuendigung erfassen und Auszugscheckliste.
# Aus kuendigung.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import date, timedelta as _timedelta

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, VERWALTUNGS_ROLLEN)
from rentals.models import Mietvertrag

from ._basis import _global_filter
from core.services.dokumentsprache import auf_deutsch
from core.services.unterschrift import UNTERSCHRIFT_HINWEIS_KUENDIGUNG


# ============================================================
# KÜNDIGUNGSPROZESS (Erfassung + Fristenberechnung + Bestätigung)
# ============================================================

def _auszugscheckliste_anlegen(vertrag, kuendigung, per, user, mit_leerstand=False):
    """Legt die Standard-Auszugscheckliste als Pendenzen an (mit Fälligkeit relativ
    zum Vertragsende). Gibt die Anzahl erstellter Pendenzen zurück."""
    from core.models import Pendenz
    from core.services import abnahme_abschluss as _ab
    heute = timezone.localdate()
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    ist_vermieter = getattr(kuendigung, 'absender', '') == 'vermieter'

    def tage(offset):
        return (per + _timedelta(days=offset)) if per else heute

    # Erste Aufgabe je Kündigungs-Richtung UND Objektart: das amtliche Formular ist
    # nur bei Wohn-/Geschäftsräumen Pflicht (Art. 266l), nicht bei Nebenobjekten.
    if ist_vermieter:
        erste = "Amtliches Kündigungsformular versenden" if vertrag.ist_geschuetzt \
                else "Kündigung schriftlich mitteilen"
    else:
        erste = "Kündigung schriftlich bestätigen"
    aufgaben = [
        (erste, heute, 'vertrag'),
        ("Abnahmetermin mit Mieter vereinbaren", tage(-30), 'aufgabe'),
        ("Wohnungsabnahme durchführen (Protokoll)", per or heute, 'protokoll' if False else 'aufgabe'),
        # Art. 267a Abs. 1 OR: Mängel, für die der Mieter einzustehen hat, müssen
        # SOFORT nach der Rückgabe gerügt werden — sonst sind die Ersatzansprüche
        # verwirkt (versteckte Mängel bleiben vorbehalten). Massgeblich ist der
        # Tag der Abnahme; der steht hier noch nicht fest. Vorläufig gilt das
        # Vertragsende plus zwei Arbeitstage, beim Abschluss der Abnahme datiert
        # `abnahme_abschluss.ruege_pendenz_setzen` die Pendenz auf die Abnahme um.
        (_ab.RUEGE_TITEL, _ab.ruege_frist(per) if per else heute, 'frist'),
        ("Zählerstände ablesen & Ummeldung", per or heute, 'aufgabe'),
        ("Schlüssel-Rückgabe kontrollieren", per or heute, 'aufgabe'),
        ("Schlussabrechnung erstellen", tage(7), 'finanzen'),
        ("Kaution abrechnen / freigeben", tage(14), 'finanzen'),
    ]
    if mit_leerstand:
        aufgaben.append(("Nachmieter suchen / Inserat aufschalten", heute, 'aufgabe'))
    # Sperrkonto: Die Bank gibt die Kaution nur frei, wenn beide Parteien zustimmen
    # oder ein rechtskräftiges Urteil vorliegt (Art. 257e Abs. 3 OR). Das Freigabe-
    # schreiben ist ein eigener Schritt — ohne ihn wartet der Mieter auf sein Geld.
    if vertrag.kautions_betrag and getattr(vertrag, 'kautions_art', '') == 'sperrkonto':
        aufgaben.append(("Kaution: Freigabeschreiben an die Bank (Zustimmung Mieter und Vermieter)",
                         tage(14), 'finanzen'))

    n = 0
    for titel, faellig, kat in aufgaben:
        # Duplikatschutz: gleiche Pendenz für diesen Vertrag nicht doppelt
        if Pendenz.objects.filter(vertrag=vertrag, titel=titel, erledigt=False).exists():
            continue
        Pendenz.objects.create(
            titel=titel, kategorie=(kat if kat in dict(Pendenz.KATEGORIE_CHOICES) else 'aufgabe'),
            faellig_am=faellig, liegenschaft=lg, vertrag=vertrag,
            beschreibung=f"Auszug {vertrag.mieter.display_name} · {vertrag.einheit.bezeichnung}",
            erstellt_von=user,
        )
        n += 1
    return n


# Erfassen, Bestätigen und Zurücknehmen einer Kündigung sind nach
# docs/KONZEPT-UI.md §8 Inhaber und Verwaltern vorbehalten (bis 28.09.2026 auch
# der Sachbearbeitung). Alle drei gehören zusammen: Schon das Erfassen setzt den
# Vertrag auf «gekündigt» und kann die Kündigung direkt als bestätigt anlegen —
# nur die Bestätigung zu sperren, wäre wirkungslos.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_kuendigung_erfassen(request, vertrag_id):
    """Erfasst eine Kündigung, berechnet den Termin und setzt den Vertrag auf 'gekuendigt'.

    Seit dem Audit vom 26.10.2026 (Befunde F und L):
      · Vermieterkündigung: `eingang_datum` ist der Versand (Poststempel); Frist und
        Anfechtung laufen ab dem ZUGANG — bestätigt oder vermutet (Zustellpuffer).
      · Ausserordentlich nur mit strukturiertem Grund; je Grund prüft der Server die
        Mindestfrist, soweit der Bestand sie belegt (`ausserordentlicher_termin`).
        «Ausserordentlich» beendet den Vertrag nicht mehr einfach am Wunschdatum.
      · Art. 264 OR: Vorzeitige Rückgabe befreit nur mit angenommenem Ersatzmieter;
        sonst haftet der Mieter bis zum nächsten ordentlichen Termin.
      · Art. 266m OR: Mieterkündigung einer Familienwohnung ohne Zustimmung des
        Ehegatten/Partners — erfasst, aber nicht bestätigt und ohne Folgen am Vertrag.
      · Erstreckung (Art. 272 OR) verschiebt das Vertragsende und damit Sollstellung
        und Leerstand.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from rentals.services import (AO_GRUENDE_MIETER, AO_GRUENDE_VERMIETER, ZUSTELL_PUFFER_TAGE,
                                  ausserordentlicher_termin, berechne_kuendigungstermin,
                                  gesetzliche_frist_monate, vermuteter_zugang)
    from core.services.kuendigungsverzicht import befristet_ohne_kuendigungsrecht, befristung_sperre_text
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    basis = _global_filter(request)
    zurueck = f'/neu/vertraege/{v.id}/kuendigen/'

    if request.method == 'POST':
        P = request.POST

        def d(key):
            val = P.get(key)
            if not val:
                return None
            try:
                return date.fromisoformat(val)
            except ValueError:
                return None
        heute = timezone.localdate()
        absender = P.get('absender', 'mieter')
        if absender not in ('mieter', 'vermieter'):
            absender = 'mieter'
        eingang = d('eingang_datum') or heute
        # Zugang: Beim Mieter ist der Eingang beim Vermieter der Zugang. Bei der
        # Vermieterkündigung ist `eingang_datum` der Versand — massgebend ist,
        # wann sie dem Mieter zugeht (Befund F). Unbestätigt: dieselbe Vermutung
        # wie für Art. 269d und die 257d-Fristansetzung.
        zugang_am = d('zugang_am') if absender == 'vermieter' else None
        if zugang_am and zugang_am < eingang:
            messages.error(request, gettext('Der Zugang kann nicht vor dem Versand liegen.'))
            return redirect(zurueck)
        zugang = vermuteter_zugang(eingang, zugang_am) if absender == 'vermieter' else eingang
        termin = berechne_kuendigungstermin(v, zugang)
        gewuenscht = d('gewuenschtes_ende')
        ausserord = P.get('ausserordentlich') == 'on'
        ao_art = (P.get('ausserordentlich_art') or '').strip()
        _ao_grund = (P.get('ausserordentlich_grund') or '').lower()
        if ausserord and not ao_art and ('257d' in _ao_grund or 'zahlungsverzug' in _ao_grund):
            ao_art = '257d'     # Altform: Grund nur als Freitext (Verzugsprozess, Alt-Links)
        if ausserord:
            erlaubt = AO_GRUENDE_VERMIETER if absender == 'vermieter' else AO_GRUENDE_MIETER
            if ao_art not in erlaubt:
                messages.error(request, gettext(
                    'Bitte den ausserordentlichen Grund wählen, der für diese Partei gilt.'))
                return redirect(zurueck)

        # Befristeter Vertrag ohne Kündigungsrecht (Audit MIET-07, Art. 266 Abs. 1 OR): Er endet ohne Kündigung. Der
        # «nächste ordentliche Termin» ist dann das vereinbarte Vertragsende — nicht ein errechneter Termin, den es
        # nicht gibt. Der Mieter kann nur vorzeitig zurückgeben (Art. 264 OR).
        befristet_fest = (not ausserord) and befristet_ohne_kuendigungsrecht(v)
        if befristet_fest:
            termin = v.ende

        # Art. 264 OR: vorzeitige Rückgabe durch den Mieter.
        ersatzmieter = (P.get('ersatzmieter') or '').strip()[:2000]
        ersatz_angenommen = bool(ersatzmieter) and P.get('ersatzmieter_akzeptiert') == 'on'
        vorzeitig = (absender == 'mieter' and not ausserord and gewuenscht is not None
                     and termin is not None and gewuenscht < termin)
        ersatz_befreit = vorzeitig and ersatz_angenommen
        befristung = befristung_sperre_text(v, ausserordentlich=ausserord, vorzeitige_rueckgabe=vorzeitig)
        if befristung:
            messages.error(request, '⛔ ' + befristung)
            return redirect(zurueck)

        # Art. 266a Abs. 2 / 266b–d OR (Audit MIET-08): Eine kürzere als die gesetzliche Frist gilt nicht; die
        # Kündigung gilt auf den nächstmöglichen Termin. `berechne_kuendigungstermin` rechnet schon mit der
        # gesetzlichen Mindestfrist — die Meldung sagt, dass der Vertrag etwas anderes enthält.
        if not ausserord and 0 < (v.kuendigungsfrist_monate or 0) < gesetzliche_frist_monate(v):
            messages.warning(request, '⚠️ ' + gettext(
                'Der Vertrag nennt eine Kündigungsfrist von %(vertrag)s Monat(en); gesetzlich sind mindestens %(gesetz)s '
                'Monate (Art. 266b–266d OR). Eine kürzere Frist gilt nicht, die Kündigung gilt auf den nächstmöglichen '
                'Termin (Art. 266a Abs. 2 OR) — gerechnet wurde mit %(gesetz)s Monaten.') % {
                    'vertrag': v.kuendigungsfrist_monate, 'gesetz': gesetzliche_frist_monate(v)})

        # Art. 266m OR: Familienwohnung, Kündigung durch den Mieter.
        zustimmung = P.get('zustimmung_ehegatte') == 'on'
        fehlt_zustimmung = absender == 'mieter' and v.familienwohnung and not zustimmung

        # ---- REGELWERK (Fristenwächter) ----
        # Bis 4b.10 stand hier nur die Klemmung weiter unten. Sie fängt den zu
        # FRÜHEN Termin, nicht aber ein Datum, das gar kein zulässiger Termin
        # ist (der 15. eines Monats), und sie hinterlässt keine Spur, unter
        # welcher Fassung entschieden wurde. Beides leistet das Regelwerk.
        #
        # Ausserordentliche Kündigungen laufen NICHT durch die Prüfung: Art.
        # 257d, 266g und 271a haben eigene Fristen, die diese Regelart nicht
        # rechnet. Eine Regel auf einen Fall anzuwenden, für den sie nicht
        # gemacht ist, wäre schlechter als keine Regel. Dasselbe gilt für die
        # Rückgabe mit angenommenem Ersatzmieter (Art. 264 OR): Sie ist kein
        # Kündigungstermin.
        regel_anwendung = None
        # ZAHLUNGSVERZUG (Art. 257d Abs. 2 OR): Kündigen darf nur, wer eine
        # Frist angesetzt hat, die unbenützt abgelaufen ist. Läuft sie noch
        # oder hat der Mieter innert Frist bezahlt, wäre die Kündigung
        # unwirksam — hier hält das System an, statt sie anzulegen.
        if ausserord and absender == 'vermieter' and ao_art == '257d':
            from core.services.zahlungsverzug import kuendigung_sperre
            sperre = kuendigung_sperre(v, eingang)
            if sperre:
                messages.error(request, f'⛔ {sperre}')
                return redirect(f'/neu/vertraege/{v.id}/kuendigen/?grund=verzug')
            # Frist abgelaufen, aber Zugang des Einschreibens nie bestätigt: nicht sperren, aber sagen.
            from core.services.zahlungsverzug import kuendigung_hinweis
            hinweis_zugang = kuendigung_hinweis(v, eingang)
            if hinweis_zugang:
                messages.warning(request, '⚠️ ' + hinweis_zugang)
        # KÜNDIGUNGSSCHUTZ (Audit MIET-06, Art. 271a Abs. 1 lit. d und e OR): Eine Vermieterkündigung während eines
        # Schlichtungs- oder Gerichtsverfahrens um die Mietsache und in den drei Jahren danach (Vermieter
        # unterlegen, Klage zurückgezogen, Vergleich) ist anfechtbar. Die Erfassung hält an und nennt den Grund; die
        # Ausnahmen des Abs. 3 (Eigenbedarf, Veräusserung …) erkennt sie nicht aus Daten — der Erfasser bestätigt sie.
        sperrfrist_vermerk = ''
        if absender == 'vermieter':
            from core.services.kuendigungsschutz import ausnahmen_hinweis, sperrfristen
            schutz = sperrfristen(v, {eingang, zugang}, ausserordentlich_art=ao_art if ausserord else '')
            if schutz:
                if P.get('sperrfrist_ausnahme') != 'on':
                    messages.error(request, '⛔ ' + ' '.join(sp.text for sp in schutz) + ' ' + ausnahmen_hinweis()
                                   + ' ' + gettext('Liegt eine Ausnahme vor, das Kästchen «Ausnahme nach Art. 271a '
                                                   'Abs. 3 OR liegt vor» setzen und die Kündigung erneut erfassen.'))
                    return redirect(f'{zurueck}?sperrfrist=1')
                sperrfrist_vermerk = (f'Sperrfrist Art. 271a OR: Ausnahme nach Abs. 3 bestätigt am {heute:%d.%m.%Y} '
                                      f'({request.user}). ' + ' '.join(sp.text for sp in schutz))
                messages.warning(request, '⚠️ ' + gettext(
                    'Kündigung in einer Sperrfrist nach Art. 271a OR erfasst, weil eine Ausnahme bestätigt wurde. '
                    'Der Mieter kann sie anfechten.'))
        if not ausserord and not ersatz_befreit and not befristet_fest:
            from core.views.fw.regelwerk import folgekosten, pruefung_zum_vertrag
            from faelle.regelwerk import sperrt
            befund, regel_anwendung, regel = pruefung_zum_vertrag(
                v, zugang, gewuenscht)
            if not befund.ok:
                kosten = folgekosten(befund, v)
                text = befund.meldung
                if kosten and kosten['betrag']:
                    text += (f' Zwischen den beiden Terminen liegen '
                             f'{kosten["monate"]} Monatszinse — rund CHF '
                             f'{kosten["betrag"]:,.0f}'.replace(',', "'") + '.')
                if regel and sperrt(regel, befund):
                    # Geprüfte Regel mit Verbindlichkeit «Sperre»: nicht
                    # speichern. Das ist der einzige Fall, in dem das Regelwerk
                    # den Betrieb anhält — und er setzt voraus, dass jemand den
                    # Regelsatz ausdrücklich als geprüft gekennzeichnet hat.
                    messages.error(request, f'⛔ {text}')
                    return redirect(zurueck)
                messages.warning(request, f'⚠️ {text}')

        # Wirksames Ende.
        #   Ausserordentlich: frühestens der Termin des Grundes. Ein früheres
        #   Wunschdatum wird — wie bei der ordentlichen Kündigung (Art. 266a
        #   Abs. 2 OR) — auf den frühesten zulässigen Termin geschoben. Für
        #   Gründe ohne im Bestand belegte Frist wird nichts gerechnet; das
        #   Wunschdatum ist dann Pflicht und die Seite warnt.
        #   Ordentlich: ein zu FRÜH gewünschtes Ende gilt von Gesetzes wegen auf
        #   den nächstmöglichen Termin (Art. 266a Abs. 2 OR) — ausser der Mieter
        #   wird durch einen angenommenen Ersatzmieter befreit (Art. 264 OR).
        if ausserord:
            frueh = ausserordentlicher_termin(v, ao_art, zugang)
            if frueh is None:
                if not gewuenscht:
                    messages.error(request, gettext(
                        'Für diesen Grund rechnet die Anwendung keine Frist — bitte das Vertragsende angeben.'))
                    return redirect(zurueck)
                per = gewuenscht
                messages.warning(request, '⚠️ ' + gettext(
                    'Für %(grund)s ist im Bestand keine Mindestfrist hinterlegt — der Termin wurde nicht '
                    'geprüft. Vor dem Versand rechtlich prüfen.') % {
                        'grund': dict(Kuendigung.AO_ART_CHOICES).get(ao_art, ao_art)})
            elif gewuenscht and gewuenscht >= frueh:
                per = gewuenscht
            else:
                per = frueh
                if gewuenscht:
                    messages.warning(request, '⚠️ ' + gettext(
                        'Gewünschtes Ende %(wunsch)s liegt vor dem frühesten Termin für diesen Grund — '
                        'die Kündigung gilt auf %(termin)s.') % {
                            'wunsch': gewuenscht.strftime('%d.%m.%Y'), 'termin': frueh.strftime('%d.%m.%Y')})
        elif ersatz_befreit:
            per = gewuenscht
            messages.info(request, gettext(
                'Vorzeitige Rückgabe mit angenommenem Ersatzmieter (Art. 264 OR): Der Mieter ist ab '
                '%(datum)s befreit.') % {'datum': gewuenscht.strftime('%d.%m.%Y')})
        elif gewuenscht and termin and gewuenscht < termin:
            per = termin
            if vorzeitig and befristet_fest:
                messages.warning(request, '⚠️ ' + gettext(
                    'Vorzeitige Rückgabe ohne angenommenen Ersatzmieter: Der Mieter haftet bis zum Ende der '
                    'vereinbarten Vertragsdauer am %(termin)s (Art. 264 Abs. 2 OR).') % {
                        'termin': termin.strftime('%d.%m.%Y')})
            elif vorzeitig:
                messages.warning(request, '⚠️ ' + gettext(
                    'Vorzeitige Rückgabe ohne angenommenen Ersatzmieter: Der Mieter haftet bis zum '
                    'nächsten ordentlichen Termin %(termin)s (Art. 264 OR).') % {
                        'termin': termin.strftime('%d.%m.%Y')})
            else:
                messages.warning(request, f"⚠️ Gewünschtes Ende {gewuenscht:%d.%m.%Y} liegt vor dem "
                                          f"nächsten zulässigen Termin — die Kündigung gilt auf "
                                          f"{termin:%d.%m.%Y} (Art. 266a Abs. 2 OR).")
        else:
            per = gewuenscht or termin

        # Kündigungsverzicht (Art. 17 Abs. 4 VMWG) und Befristung: Der Vermieter kann bis dahin nicht
        # ordentlich kündigen. Gesperrt ist nur diese Kündigung; die des Mieters und jede ausserordentliche
        # (257d, 257f, 266g, 266h …) bleiben möglich — die Unterscheidung steht in
        # `core/services/kuendigungsverzicht.py`.
        from core.services.kuendigungsverzicht import sperre_text
        verzicht = sperre_text(v, per, absender=absender, ausserordentlich=ausserord)
        if verzicht:
            messages.error(request, '⛔ ' + verzicht)
            return redirect(zurueck)

        # Erstreckung (Art. 272 OR): Das Mietverhältnis läuft bis dahin weiter —
        # Vertragsende, Sollstellung und Leerstand folgen ihr (Befund L).
        erstreckung = d('erstreckung_bis')
        if erstreckung and per and erstreckung <= per:
            messages.error(request, gettext('Die Erstreckung muss nach dem Vertragsende liegen.'))
            return redirect(zurueck)
        if erstreckung and per:
            # Art. 272b OR (Gesetzesregister): höchstens vier Jahre bei Wohnräumen,
            # sechs bei Geschäftsräumen. Gewarnt, nicht gesperrt — die Erstreckung
            # spricht die Behörde aus, nicht die Verwaltung.
            jahre = 6 if v.mietrecht_kategorie == 'gewerbe' else 4
            try:
                grenze = per.replace(year=per.year + jahre)
            except ValueError:
                grenze = per.replace(year=per.year + jahre, day=28)
            if erstreckung > grenze:
                messages.warning(request, '⚠️ ' + gettext(
                    'Die Erstreckung übersteigt die Höchstdauer von %(n)s Jahren (Art. 272b OR).') % {'n': jahre})
        vertragsende = erstreckung or per

        bestaetigen = P.get('bestaetigen') == 'on' and not fehlt_zustimmung
        k = Kuendigung.objects.create(
            vertrag=v, absender=absender,
            eingang_datum=eingang, zugang_am=zugang_am,
            zustellung=P.get('zustellung', 'einschreiben'),
            gewuenschtes_ende=gewuenscht, berechneter_termin=termin, per_datum=per,
            ende_vorher=v.ende,   # Snapshot der bisherigen Laufzeit (für Rücknahme)
            ausserordentlich=ausserord, ausserordentlich_art=ao_art if ausserord else '',
            ausserordentlich_grund=P.get('ausserordentlich_grund', '').strip(),
            zustimmung_ehegatte=zustimmung,
            ersatzmieter=ersatzmieter, ersatzmieter_akzeptiert=ersatz_angenommen,
            erstreckung_bis=erstreckung, status='bestaetigt' if bestaetigen else 'erfasst',
            bemerkung=(P.get('bemerkung', '').strip() + ('\n\n' if P.get('bemerkung', '').strip() and sperrfrist_vermerk else '')
                       + sperrfrist_vermerk),
        )
        benutzer = request.user if request.user.is_authenticated else None

        if fehlt_zustimmung:
            # Ohne Zustimmung ist die Kündigung nichtig (Art. 266m/266o OR): Sie
            # wird festgehalten, aber der Vertrag bleibt unverändert, und es
            # entsteht keine Auszugscheckliste. Die Bestätigung bleibt gesperrt,
            # bis die Zustimmung erfasst ist (`fw_kuendigung_bestaetigen`).
            from core.models import Pendenz
            Pendenz.objects.create(
                titel=f"Art. 266m: Zustimmung des Ehegatten/Partners einholen – {v.mieter.display_name}",
                beschreibung=("Die Mieterkündigung einer Familienwohnung braucht die ausdrückliche "
                              "Zustimmung des Ehegatten oder eingetragenen Partners (Art. 266m OR). "
                              "Ohne sie ist die Kündigung nichtig."),
                kategorie='frist', faellig_am=heute, vertrag=v,
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                quelle=f'266m:{k.pk}', erstellt_von=benutzer)
            log_aktion(request, "Kündigung erfasst (ohne Zustimmung Art. 266m)", str(v.mieter),
                       f"per {per.strftime('%d.%m.%Y') if per else '—'}", ziel=v)
            messages.error(request, '⛔ ' + gettext(
                'Familienwohnung: Ohne ausdrückliche Zustimmung des Ehegatten/Partners ist die Kündigung '
                'nichtig (Art. 266m OR). Sie ist erfasst, aber nicht bestätigt — der Vertrag bleibt '
                'unverändert, bis die Zustimmung vorliegt.'))
            return redirect(f'/neu/vertraege/{v.id}/')

        # Vertrag auf gekündigt setzen
        v.status = 'gekuendigt'
        v.aktiv = False
        v.ende = vertragsende
        v.save(update_fields=['status', 'aktiv', 'ende'])

        # Anfechtungsfrist-Pendenz bei Vermieterkündigung geschützter Räume:
        # der Mieter kann die Kündigung innert 30 Tagen ab EMPFANG anfechten
        # (Art. 271/273 OR) — ab Zugang, nicht ab Versand (Befund F).
        if k.absender == 'vermieter' and v.ist_geschuetzt:
            from core.models import Pendenz
            # Art. 273 Abs. 1 OR: 30 Tage ab Empfang; der letzte Tag ist ein Werktag (Art. 78 OR) — fällt er auf
            # einen Samstag, Sonntag oder Feiertag, kann der Mieter noch am nächsten Werktag anfechten.
            from core.services.fristen import fristende as _fristende
            frist = _fristende(zugang, 30)
            Pendenz.objects.create(
                titel=f"Anfechtungsfrist Kündigung läuft ab – {v.mieter.display_name}",
                beschreibung=("Der Mieter kann die Vermieterkündigung innert 30 Tagen ab Empfang bei der "
                              "Schlichtungsbehörde anfechten (Art. 271/271a/273 OR) und eine Erstreckung "
                              "verlangen (Art. 272). Danach wird die Kündigung grundsätzlich rechtskräftig."
                              + ("" if zugang_am else
                                 f" Zugang vermutet: Versand {eingang:%d.%m.%Y} + {ZUSTELL_PUFFER_TAGE} Tage.")),
                kategorie='frist', faellig_am=frist, vertrag=v,
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                erstellt_von=benutzer,
            )

        # Art. 264 OR: vorgeschlagene Ersatzmieter prüfen, solange keiner angenommen ist.
        if vorzeitig and ersatzmieter and not ersatz_angenommen:
            from core.models import Pendenz
            Pendenz.objects.create(
                titel=f"Art. 264: Ersatzmieter prüfen – {v.mieter.display_name}",
                beschreibung=("Vorgeschlagen: " + ersatzmieter[:400] + "\n\nIst ein Ersatzmieter "
                              "zumutbar und zahlungsfähig und übernimmt er den Vertrag zu gleichen "
                              f"Bedingungen, wird der Mieter befreit (Art. 264 OR). Bis dahin haftet er "
                              f"bis {termin:%d.%m.%Y}."),
                kategorie='aufgabe', faellig_am=heute + _timedelta(days=14), vertrag=v,
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                quelle=f'264:{k.pk}', erstellt_von=benutzer)

        # Auszugscheckliste automatisch als Pendenzen anlegen
        leerstand_gewuenscht = P.get('leerstand_anlegen') == 'on'
        n_pendenzen = _auszugscheckliste_anlegen(v, k, vertragsende, request.user, mit_leerstand=leerstand_gewuenscht)
        # Der Auszug ist EIN Vorgang: Fall «Mieterwechsel» eröffnen (wenn die Fallart
        # eingerichtet ist), bevor die Stichwort-Ereignisse unten seine Schritte abhaken.
        from core.services.mieterwechsel_fall import eroeffnen as _mw_eroeffnen
        _mw_eroeffnen(v, benutzer=benutzer)
        # Wird die Kündigung schon beim Erfassen als bestätigt angelegt, ist «Kündigung
        # schriftlich bestätigen» erledigt — gleiche Regel wie in fw_kuendigung_bestaetigen.
        # Vorher blieb die Pendenz offen, obwohl das Häkchen gesetzt war (Stresstest, Punkt 12).
        if k.status == 'bestaetigt':
            from core.services.automation import erledige_pendenzen_fuer
            erledige_pendenzen_fuer(v, ['schriftlich', 'Kündigungsformular'], user=request.user)

        # Leerstand ab Tag nach Vertragsende (opt-in)
        hinweis = ""
        if leerstand_gewuenscht and vertragsende and v.einheit_id:
            from rentals.models import Leerstand
            beginn = vertragsende + _timedelta(days=1)
            if not Leerstand.objects.filter(einheit=v.einheit, beginn=beginn, ende__isnull=True).exists():
                Leerstand.objects.create(einheit=v.einheit, beginn=beginn, grund='mietersuche',
                                         bemerkung=f"Automatisch aus Kündigung (Ende {vertragsende.strftime('%d.%m.%Y')})")
                hinweis = " · Leerstand ab " + beginn.strftime('%d.%m.%Y') + " angelegt"

        # Der Regelstand gehört in die Spur: Wird die Regel später berichtigt,
        # ist das die Angabe, über die sich die betroffenen Kündigungen finden
        # lassen, ohne jede Akte einzeln zu öffnen.
        regel_spur = ''
        if regel_anwendung is not None:
            regel_spur = (f", Regel {regel_anwendung.art} Stand "
                          f"{regel_anwendung.regel_stand:%d.%m.%Y} → "
                          f"{auf_deutsch(regel_anwendung.get_befund_display).lower()}")
        log_aktion(request, "Kündigung erfasst", str(v.mieter),
                   f"per {per.strftime('%d.%m.%Y') if per else '—'}"
                   + (f", erstreckt bis {erstreckung:%d.%m.%Y}" if erstreckung else "")
                   + f", {n_pendenzen} Pendenzen{hinweis}{regel_spur}"
                   + (", Sperrfrist Art. 271a OR: Ausnahme bestätigt" if sperrfrist_vermerk else ""), ziel=v)
        # Modul 5: Regel «Kündigung erfasst» — Begleitdokument; ein Fehler darin
        # kostet die erfasste Kündigung nicht.
        from core.services.dokument_regeln import dokument_fuer_ereignis
        dokument_fuer_ereignis('kuendigung_erfasst', organisation=v.organisation, vertrag=v)
        if P.get('embed'):
            return render(request, 'fw/_modal_done.html', {
                'msg': f"Kündigung erfasst · {n_pendenzen} Auszugs-Pendenzen"})
        messages.success(request, '✅ ' + gettext('Kündigung erfasst — Vertragsende %(wert)s · %(n_pendenzen)s Auszugs-Pendenzen erstellt%(hinweis)s.') % {'wert': vertragsende.strftime('%d.%m.%Y') if vertragsende else '—', 'n_pendenzen': n_pendenzen, 'hinweis': hinweis})
        if absender == 'vermieter':
            messages.warning(request, UNTERSCHRIFT_HINWEIS_KUENDIGUNG)
        return redirect(f'/neu/vertraege/{v.id}/')

    # Vorschau des nächsten Termins für heute — beim Mieter ab Eingang heute,
    # beim Vermieter ab dem vermuteten Zugang einer heute versandten Kündigung.
    heute = timezone.localdate()
    vorschau_termin = berechne_kuendigungstermin(v, heute)
    vorschau_termin_vermieter = berechne_kuendigungstermin(v, vermuteter_zugang(heute))
    # Aus dem Verzugsprozess kommend → ausserordentliche Kündigung wegen Zahlungsverzug vorbelegen
    verzug = request.GET.get('grund') in ('verzug', '257d')
    from rentals.services import TERMINE_FEHLEN, TERMINE_KANTON, kuendigungstermine_fuer, termin_257d
    ao_termin = termin_257d(vermuteter_zugang(heute)) if verzug else None
    # Ohne lesbare Termine im Vertrag (und ohne Kantonsregel) ist der Termin
    # oben nur der früheste DENKBARE — das muss auf der Seite stehen.
    _termine, termine_herkunft = kuendigungstermine_fuer(v)
    from core.services.kuendigungsschutz import ausnahmen_hinweis, sperrfristen
    schutz_vorschau = sperrfristen(v, {heute, vermuteter_zugang(heute)})
    return render(request, 'fw/kuendigung_form.html', {
        'schutz_vorschau': schutz_vorschau, 'schutz_ausnahmen': ausnahmen_hinweis() if schutz_vorschau else '',
        'termine_fehlen': termine_herkunft == TERMINE_FEHLEN,
        'termine_kanton': termine_herkunft == TERMINE_KANTON,
        **basis, 'nav': 'vertraege', 'v': v,
        'vorschau_termin': vorschau_termin, 'vorschau_termin_vermieter': vorschau_termin_vermieter,
        'heute_iso': heute.isoformat(), 'zustell_puffer': ZUSTELL_PUFFER_TAGE,
        'prefill_ao': verzug,
        'prefill_art': '257d' if verzug else '',
        'prefill_grund': 'Zahlungsverzug (Art. 257d OR)' if verzug else '',
        'ao_termin': ao_termin,
        'ao_choices': Kuendigung.AO_ART_CHOICES,
        'ao_vermieter': sorted(AO_GRUENDE_VERMIETER), 'ao_mieter': sorted(AO_GRUENDE_MIETER),
    })
