"""Legal Health Check einer STWEG: Ohne Begründungsakt und Reglement ist die Verwaltung rechtlich handlungsunfähig.

Geprüft wird, ob im Dokumenten-Repository (`stweg.dokumente`) für die Liegenschaft
  · der BEGRÜNDUNGSAKT,
  · das STWEG-REGLEMENT und
  · der AKTUELLE GEBÄUDEVERSICHERUNGSNACHWEIS
hochgeladen UND mit der Liegenschaft verknüpft sind, heute gelten (gültig ab ≤ heute, nicht abgelaufen) und die Datei
im Speicher auch wirklich vorhanden ist. Fehlt eines davon, ist die Gemeinschaft «Nicht Compliance-Konform».

Was dieser Check NICHT beurteilt: ob das Dokument inhaltlich das richtige ist, ob der Begründungsakt im Grundbuch
eingetragen ist, ob die Versicherungssumme genügt. Er prüft das Vorhandensein, nicht die Richtigkeit.
Ein Nachweis ohne Ablaufdatum gilt als aktuell, wird aber als Hinweis genannt.
"""
from datetime import date

from django.utils.translation import gettext

from stweg import dokumente
from stweg.models import StwegDokument as K

PFLICHT = (K.BEGRUENDUNGSAKT, K.REGLEMENT, K.GEBAEUDEVERSICHERUNG)


def _datei_vorhanden(d):
    try:
        return bool(d.datei) and d.datei.storage.exists(d.datei.name)
    except Exception:       # ein nicht lesbarer Speicher ist «nicht vorhanden», nie «in Ordnung»
        return False


def health_check(liegenschaft, heute=None):
    """{'konform': bool, 'punkte': [{'kategorie', 'name', 'status', 'dokument', 'hinweis'}], 'gruende': [str]}.
    Status: ok | fehlt | abgelaufen | noch_nicht_gueltig | datei_fehlt."""
    heute = heute or date.today()
    namen = dict(K.KATEGORIE_CHOICES)
    punkte, gruende = [], []
    for kat in PFLICHT:
        aktuell = dokumente.aktuell(liegenschaft, kat, heute)
        dok = aktuell[0] if aktuell else None
        hinweis = ''
        if dok is None:
            vorhanden = list(K.objects.filter(liegenschaft=liegenschaft, kategorie=kat))
            if not vorhanden:
                status = 'fehlt'
                gruende.append(gettext('«%(name)s» ist nicht hochgeladen.') % {'name': namen[kat]})
            elif all(d.gueltig_ab > heute for d in vorhanden):
                status = 'noch_nicht_gueltig'
                gruende.append(gettext('«%(name)s» gilt erst ab %(datum)s — bis dahin fehlt ein gültiges Dokument.')
                               % {'name': namen[kat], 'datum': f'{min(d.gueltig_ab for d in vorhanden):%d.%m.%Y}'})
            else:
                status = 'abgelaufen'
                gruende.append(gettext('«%(name)s» ist abgelaufen — bitte die aktuelle Fassung hochladen.')
                               % {'name': namen[kat]})
        elif not _datei_vorhanden(dok):
            status = 'datei_fehlt'
            gruende.append(gettext('«%(name)s»: Die Datei fehlt im Speicher — bitte neu hochladen.') % {'name': namen[kat]})
        else:
            status = 'ok'
            if kat == K.GEBAEUDEVERSICHERUNG and dok.gueltig_bis is None:
                hinweis = gettext('kein Ablaufdatum erfasst')
        punkte.append({'kategorie': kat, 'name': namen[kat], 'status': status, 'dokument': dok, 'hinweis': hinweis})
    return {'konform': not gruende, 'punkte': punkte, 'gruende': gruende}
