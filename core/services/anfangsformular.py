"""Anfangsmietzins-Formular (Art. 270 Abs. 2 OR): Pflicht, Nachweis, Vormiete.

Zwei Dinge, die bis hierher in der Ansicht `mietzins.py` lagen und dort verloren gingen:

1. WANN ein Vertrag das amtliche Formular braucht und ob der Nachweis vorliegt (MIET-04).
   `anfangsmietzins_auto_ablegen` warf den Grund («kein_original», «kanton_fehlt») weg; in
   den Kantonen ohne hinterlegtes Original (ZH, BS, FR, GE, LU, ZG, teils NE/VD) erfuhr die
   Verwaltung nichts. Ohne Formular ist die Mietzinsvereinbarung nichtig (BGE 140 III 583).
   Es gibt hier keine Nachbildung als Ersatz — das Formular der kantonalen Behörde wird
   extern beschafft, und der Vertrag trägt den Nachweis (`Mietvertrag.anfangsformular_*`).

2. WELCHER Mietzins als «bisheriger» auf dem Formular steht (MIET-05): der letzte vor dem
   neuen Vertrag gültige, nicht der Wert zu Beginn der Vormiete.
"""
from datetime import timedelta
from decimal import Decimal

#: Das Dokument, das `anfangsmietzins_auto_ablegen` in die Akte legt; sein Vorhandensein
#: gilt als Nachweis (auch ein von Hand so benanntes Dokument).
FORMULAR_DOKUMENT_PRAEFIX = 'Anfangsmietzins-Formular'


def vormiete_fuer(vertrag):
    """Der Vormieter-Vertrag desselben Objekts: der letzte vor dem Beginn des neuen.

    Entwürfe zählen nicht — ein nie in Kraft getretener Vertrag hat keinen Mietzins
    geschuldet, also auch keinen «bisherigen»."""
    from rentals.models import Mietvertrag
    if not vertrag.einheit_id:
        return None
    from django.utils import timezone
    return (Mietvertrag.objects.filter(einheit=vertrag.einheit).exclude(id=vertrag.id)
            .exclude(status='entwurf')
            .filter(beginn__lt=vertrag.beginn or timezone.localdate())
            .order_by('-beginn', '-id').first())


def vormiete_stichtag(vertrag, vor):
    """Der letzte Tag, an dem der bisherige Mietzins galt: der Tag vor dem neuen Beginn,
    nicht später als das Ende des Vormietverhältnisses (Leerstand dazwischen) und nicht
    vor dessen Beginn."""
    from django.utils import timezone
    tag = (vertrag.beginn or timezone.localdate()) - timedelta(days=1)
    if vor.ende and vor.ende < tag:
        tag = vor.ende
    if vor.beginn and tag < vor.beginn:
        tag = vor.beginn
    return tag


def vormiete_werte(vertrag):
    """Die Angaben «bisheriger Mietzins» fürs Formular, oder None ohne Vormieter.

    Alles zum Stichtag `vormiete_stichtag`: Netto und Nebenkosten so, wie die Sollstellung
    sie damals verrechnete (Staffelstufe, gebuchte Anpassung, Zeitplan), Referenzzins und
    LIK aus der damals wirksamen Basis (Art. 19 Abs. 3 VMWG)."""
    vor = vormiete_fuer(vertrag)
    if vor is None:
        return None
    tag = vormiete_stichtag(vertrag, vor)
    ref, lik = vor.effektive_basis(tag)
    return {
        'vertrag': vor, 'stichtag': tag,
        'netto': vor.effektiver_netto_mietzins(tag) or Decimal('0'),
        'nk': vor.effektive_nebenkosten(tag) or Decimal('0'),
        'ref': ref, 'lik': lik,
    }


# ---------------------------------------------------------------------------
# Pflicht und Nachweis
# ---------------------------------------------------------------------------

def _kandidaten_mit_pflicht(lg):
    """Ist der Kanton nicht erfasst: die Kantone, die nach der PLZ in Frage kommen und
    eine (teilweise) Pflicht haben."""
    from core.services.formularpflicht import formularpflicht_fuer_kanton
    from core.services.kantone import plz_kantone
    return [k for k in plz_kantone(getattr(lg, 'plz', ''))
            if formularpflicht_fuer_kanton(k)[0] in ('ja', 'teilweise')]


def hinweis_text(kanton_name, pflicht):
    """Der Satz, der im Wizard und am Vertrag steht."""
    from django.utils.translation import gettext
    if pflicht == 'teilweise':
        return gettext(
            'Anfangsmietzins-Formular möglicherweise erforderlich (Art. 270 Abs. 2 OR, Kanton %(kanton)s: '
            'Formularpflicht nur für bestimmte Gemeinden oder Wohnungen); ohne Formular ist die '
            'Mietzinsvereinbarung nichtig (BGE 140 III 583).') % {'kanton': kanton_name}
    return gettext(
        'Anfangsmietzins-Formular erforderlich (Art. 270 Abs. 2 OR, Kanton %(kanton)s); ohne Formular '
        'ist die Mietzinsvereinbarung nichtig (BGE 140 III 583).') % {'kanton': kanton_name}


def anfangsformular_lage(einheit, vertrag=None):
    """Was für den Anfangsmietzins eines Vertrags auf dieser Einheit gilt.

    Schlüssel:
      `erforderlich` — Formularpflicht besteht (oder kann nicht ausgeschlossen werden)
      `pflicht`      — 'ja' | 'teilweise' | 'unklar' (Kanton fehlt) | 'nein'
      `grund`        — 'kein_objekt' | 'kein_wohnraum' | 'keine_pflicht' | 'kanton_fehlt'
                       | 'kein_original' | 'original'
      `original`     — das Kantonsoriginal ist hinterlegt (dann legt die Anwendung das
                       Formular selbst in die Akte)
      `nachweis`     — Dokument in der Akte oder Bestätigung am Vertrag
      `gesperrt`     — Pflicht ohne Original und ohne Nachweis: Aktivieren verlangt Nachweis
      `hinweis`      — Klartext für die Oberfläche (leer, wenn nichts zu sagen ist)
      `kanton`, `kanton_name`
    """
    from django.utils.translation import gettext
    from core.services.formular_status import formular_status
    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
    lage = {'erforderlich': False, 'pflicht': 'nein', 'grund': 'keine_pflicht', 'original': False,
            'nachweis': False, 'gesperrt': False, 'hinweis': '', 'kanton': None, 'kanton_name': ''}
    if einheit is None:
        lage['grund'] = 'kein_objekt'
        return lage
    if getattr(einheit, 'mietrecht_kategorie', '') == 'gewerbe' or getattr(einheit, 'ist_einstellplatz', False):
        lage['grund'] = 'kein_wohnraum'
        return lage
    lg = einheit.liegenschaft
    pflicht, info = formularpflicht_fuer_liegenschaft(lg)
    status = formular_status(lg, 'anfangsmietzins')
    lage['kanton'] = status['kanton'] or info.get('kanton') or None
    lage['kanton_name'] = status['kanton_name'] or info.get('kanton_name', '')
    if status['kanton_fehlt']:
        # Der Kanton steht nicht im Feld. Eine eindeutige PLZ genügt für die Frage «Pflicht?»,
        # nicht für das Formular selbst; bleibt die PLZ mehrdeutig, entscheidet die Vorsicht.
        if pflicht in ('ja', 'teilweise'):
            lage['pflicht'] = pflicht
        elif _kandidaten_mit_pflicht(lg):
            lage['pflicht'] = 'unklar'
        else:
            return lage
        lage['erforderlich'] = True
        lage['grund'] = 'kanton_fehlt'
        lage['hinweis'] = gettext(
            'Der Kanton der Liegenschaft ist nicht erfasst — ob der Anfangsmietzins das amtliche '
            'Formular braucht (Art. 270 Abs. 2 OR), lässt sich so nicht beurteilen. Ohne Formular ist die '
            'Mietzinsvereinbarung nichtig (BGE 140 III 583). Bitte den Kanton bei der Liegenschaft erfassen.')
    else:
        if pflicht not in ('ja', 'teilweise'):
            return lage
        lage['pflicht'] = pflicht
        lage['erforderlich'] = True
        lage['original'] = bool(status['original'])
        lage['grund'] = 'original' if lage['original'] else 'kein_original'
        lage['hinweis'] = hinweis_text(lage['kanton_name'] or lage['kanton'], pflicht)
        if lage['original']:
            lage['hinweis'] += ' ' + gettext(
                'Das Formular des Kantons ist hinterlegt und wird beim Aktivieren automatisch in der Akte abgelegt.')
        else:
            lage['hinweis'] += ' ' + gettext(
                'Für diesen Kanton ist kein amtliches Original hinterlegt: Das Formular der kantonalen '
                'Behörde extern verwenden und den Nachweis am Vertrag festhalten.')
    lage['nachweis'] = _hat_nachweis(vertrag)
    # Mit Original legt die Anwendung das Formular beim Aktivieren selbst ab: keine Sperre.
    lage['gesperrt'] = not lage['original'] and not lage['nachweis']
    return lage


def _hat_nachweis(vertrag):
    """Eine Bestätigung am Vertrag oder ein Formular-Dokument in der Akte."""
    if vertrag is None or not vertrag.pk:
        return False
    if getattr(vertrag, 'anfangsformular_nachweis', ''):
        return True
    from rentals.models import Dokument
    # `alle_organisationen`: gesucht wird am GENAU DIESEN Vertrag; die Grenze steht in `vertrag=`.
    # Der Webhook (DocuSeal) läuft ohne Mandantenkontext.
    return Dokument.alle_organisationen.filter(
        vertrag=vertrag, bezeichnung__startswith=FORMULAR_DOKUMENT_PRAEFIX).exists()


def sperre_beim_aktivieren(vertrag):
    """Der Satz, warum der Vertrag (noch) nicht aktiviert werden darf — oder ''.

    Gilt, wo ein Entwurf in Kraft gesetzt wird: Assistent, «Status ändern», Unterschrift."""
    from django.utils.translation import gettext
    lage = anfangsformular_lage(vertrag.einheit if vertrag.einheit_id else None, vertrag)
    if not lage['gesperrt']:
        return ''
    return gettext('%(hinweis)s Aktivieren erst, wenn der Nachweis am Vertrag festgehalten ist '
                   '(«Formular extern verwendet», mit Datum).') % {'hinweis': lage['hinweis']}


# ---------------------------------------------------------------------------
# Was ein Entwurf braucht, bevor er in Kraft tritt
# ---------------------------------------------------------------------------

def nk_liste_fehlt(vertrag):
    """Neue Verträge mit Nebenkosten (Akonto/Pauschal) müssen die Kostenarten einzeln bezeichnen
    (MIET-11, Art. 257a Abs. 2 OR, BGE 135 III 591). Altverträge ohne Liste behalten den Bestand —
    diese Prüfung gilt nur für Entwürfe, die in Kraft gesetzt werden."""
    if vertrag.nk_abrechnungsart not in ('akonto', 'pauschal'):
        return False
    if (vertrag.nebenkosten or Decimal('0')) <= 0:
        return False
    if vertrag.einheit_id and vertrag.einheit.ist_einstellplatz:
        return False
    return not (vertrag.nk_kostenarten or [])


def nk_liste_text():
    from django.utils.translation import gettext
    return gettext('Die Nebenkosten sind im Vertrag nicht einzeln bezeichnet (Art. 257a Abs. 2 OR, '
                   'BGE 135 III 591): Was nicht klar und bestimmt vereinbart ist, trägt der Vermieter. '
                   'Im Vertragsassistenten die Nebenkostenarten wählen.')


def aktivierungssperren(vertrag):
    """Die Gründe (Klartext), warum der ENTWURF noch nicht in Kraft gesetzt werden darf.

    Eine Quelle für alle Wege: «Status ändern», Versand zur Unterschrift, Unterschrift (Webhook); der
    Assistent prüft dasselbe vor dem Speichern. Leer = frei.

    Das Anfangsmietzins-Formular gilt auch für «archiviert → aktiv»: Ein Entwurf liesse sich sonst über
    «Inaktiv» an der Prüfung vorbei in Kraft setzen (wie bei der Mietzinsmodell-Prüfung). Die Liste der
    Nebenkostenarten verlangt nur der Entwurf: Ein archivierter Altvertrag hat keine, und der Assistent
    kann ihn nicht mehr bearbeiten."""
    gruende = []
    sperre = sperre_beim_aktivieren(vertrag)
    if sperre:
        gruende.append(sperre)
    if vertrag.status == 'entwurf' and nk_liste_fehlt(vertrag):
        gruende.append(nk_liste_text())
    return gruende


# ---------------------------------------------------------------------------
# Pendenz «Formular beschaffen»
# ---------------------------------------------------------------------------

def pendenz_quelle(vertrag):
    return f'auto:anfangsformular:{vertrag.pk}'


def pendenz_nachweis_anlegen(vertrag, hinweis):
    """Pendenz «Anfangsmietzins-Formular beschaffen und Nachweis erfassen» — einmal je Vertrag.

    Läuft im Kontext der Organisation des Vertrags (Ansicht). Eine erledigte Pendenz wird nicht
    wieder geöffnet."""
    from django.utils import timezone

    from core.models import Pendenz
    quelle = pendenz_quelle(vertrag)
    if Pendenz.objects.filter(vertrag=vertrag, quelle=quelle).exists():
        return None
    titel = f'Anfangsmietzins-Formular beschaffen: {vertrag.mieter.display_name}'
    return Pendenz.objects.create(
        vertrag=vertrag, quelle=quelle, kategorie='vertrag',
        liegenschaft=vertrag.einheit.liegenschaft if vertrag.einheit_id else None,
        titel=titel[:Pendenz._meta.get_field('titel').max_length],
        faellig_am=vertrag.beginn or timezone.localdate(),
        beschreibung=hinweis + ' Das Formular der kantonalen Behörde beschaffen, dem Mieter spätestens beim '
                               'Vertragsabschluss zustellen und den Nachweis am Vertrag erfassen.')


def pendenz_nachweis_erledigen(vertrag):
    """Erledigt die Pendenz, sobald der Nachweis am Vertrag steht."""
    from django.utils import timezone

    from core.models import Pendenz
    for p in Pendenz.objects.filter(vertrag=vertrag, quelle=pendenz_quelle(vertrag), erledigt=False):
        p.erledigt = True
        p.erledigt_am = timezone.localdate()
        p.save(update_fields=['erledigt', 'erledigt_am'])


def nachweis_aus_eingabe(lage, art, roh_datum, notiz):
    """Prüft die Eingabe zum Nachweis. Gibt (art, datum, notiz, fehler) zurück; `fehler` ist
    {Feldname: Text}. Eine unlesbare oder nicht erlaubte Eingabe wird nie still ersetzt."""
    from datetime import date

    from django.utils.translation import gettext
    fehler = {}
    art = (art or '').strip()
    if art not in ('extern', 'nicht_betroffen'):
        art = ''
    datum = None
    roh = (roh_datum or '').strip()
    if roh:
        try:
            datum = date.fromisoformat(roh)
        except ValueError:
            fehler['anfangsformular_datum'] = gettext('Das Datum des Formulars ist nicht lesbar.')
    notiz = (notiz or '').strip()[:200]
    if art == 'extern' and not roh:
        fehler['anfangsformular_datum'] = gettext(
            'Bitte das Datum angeben, an dem das Formular dem Mieter zugestellt wurde oder wird.')
    if art == 'nicht_betroffen':
        if lage['pflicht'] != 'teilweise':
            fehler['anfangsformular_nachweis'] = gettext(
                'Diesen Nachweis gibt es nur, wo die Formularpflicht nur teilweise gilt (Neuenburg, Waadt). '
                'Hier besteht die Pflicht: das Formular der Behörde verwenden.')
        elif not notiz:
            fehler['anfangsformular_notiz'] = gettext(
                'Bitte begründen, warum die Formularpflicht für dieses Objekt nicht zutrifft.')
    return art, datum, notiz, fehler
