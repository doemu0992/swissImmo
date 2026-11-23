"""Untere Leiste der Portale am Telefon (Mieter, Eigentümer, Betreiber) — derselbe Baustein wie `#fwTabbar` der Verwaltung.

Die Belegung steht hier an EINER Stelle und richtet sich nach dem Pfad der Anfrage; die Seiten selbst müssen nichts setzen.
Die vollständige Liste bleibt die Leiste `#pSidebar` (Knopf «Mehr»): Kein Eintrag steht nur in der unteren Leiste.
"""
from django import template
from django.urls import reverse
from django.utils.translation import gettext as _

register = template.Library()

#: Markenzeichen je Portal (wie `brand_icon` der Hüllen), für die Kopfzeile am Telefon.
_ZEICHEN = (('/mieter/', 'schluessel'), ('/betreiber/', 'gesperrt'), ('/portal/', 'liegenschaft'))


def _tabs(pfad, context):
    """Liste aus (ziel, zeichen, text, plus, zahl) für das Portal dieses Pfads; leer ausserhalb der Portale."""
    if pfad.startswith('/mieter/'):
        return [('/mieter/', 'liegenschaft', _('Übersicht'), False, 0),
                ('/mieter/rechnungen/', 'rechnung', _('Rechnungen'), False, 0),
                ('/mieter/schaden/neu/', 'neu', _('Schaden melden'), True, 0),
                ('/mieter/tickets/', 'arbeit', _('Meldungen'), False, 0)]
    if pfad.startswith('/betreiber/'):
        from core.templatetags.betreiber_tags import betreiber_fehlerzahl
        return [(reverse('betreiber'), 'liegenschaft', _('Kunden'), False, 0),
                (reverse('fw_betreiber_protokoll'), 'warnung', _('Protokoll'), False, betreiber_fehlerzahl(context)),
                (reverse('fw_betreiber_neu'), 'neu', _('Kunde anlegen'), True, 0),
                (reverse('fw_betreiber_lik'), 'trend', _('LIK-Werte'), False, 0)]
    if pfad.startswith('/portal/'):
        return [(reverse('portal'), 'trend', _('Übersicht'), False, 0),
                (reverse('portal_abrechnungen'), 'geld', _('Abrechnung'), False, 0),
                (reverse('portal_liegenschaften'), 'liegenschaft', _('Objekte'), False, 0),
                (reverse('portal_dokumente'), 'dokument', _('Dokumente'), False, 0)]
    return []


@register.inclusion_tag('core/_portal_tabbar.html', takes_context=True)
def portal_tabbar(context):
    anfrage = context.get('request')
    pfad = getattr(anfrage, 'path', '') or ''
    roh = _tabs(pfad, context)
    # Aktiv ist der Tab mit dem längsten passenden Pfad; die Übersicht (Wurzel des Portals) nur bei genauer Übereinstimmung.
    wurzel = roh[0][0] if roh else ''
    treffer = [z for z, *_rest in roh if pfad == z or (z != wurzel and pfad.startswith(z))]
    hier = max(treffer, key=len) if treffer else None
    return {'tabs': [dict(ziel=z, zeichen=i, text=t, plus=p, zahl=n, hier=(z == hier)) for z, i, t, p, n in roh],
            'mehr_hier': bool(roh) and hier is None}


@register.simple_tag(takes_context=True)
def portal_zeichen(context):
    """Name des Markenzeichens für das Portal dieser Anfrage."""
    pfad = getattr(context.get('request'), 'path', '') or ''
    return next((z for vor, z in _ZEICHEN if pfad.startswith(vor)), 'schluessel')
