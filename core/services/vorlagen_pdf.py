"""Eine Vorlage samt Kontext als PDF mit Briefkopf (Modul 5).

xhtml2pdf über `core/templates/core/dok_vorlage.html`, das auf `dok_base.html`
aufbaut — dieselbe Hülle wie Begleitbrief und Hausordnung, also derselbe
Briefkopf (Logo, Farbe, Fusszeile, Unterschrift; `core/services/briefkopf.py`).

FORMAT
- `text`: Der Text wird maskiert, Leerzeilen trennen Absätze.
- `html`: Erlaubt ist eine kleine Auswahl von Auszeichnungen (Absatz, fett,
  Liste, Tabelle …). Alles andere fällt weg — Skripte und Stile samt Inhalt,
  Bilder und Verweise ganz. Der Grund ist doppelt: Die Vorschau zeigt das
  HTML in der Oberfläche anderer Benutzer derselben Verwaltung, und
  xhtml2pdf lädt, was ein `<img src>` nennt — auch von fremden Rechnern oder
  aus fremden Medienordnern.

SPRACHE
Das Dokument entsteht in der Sprache der Vorlage (`Vorlage.sprache`), nicht
in der Sprache der Sachbearbeitung (Entscheid D11).
"""
import io
from html.parser import HTMLParser

from django.template.loader import get_template
from django.utils import timezone
from django.utils.html import escape, linebreaks
from xhtml2pdf import pisa

from core.services.briefkopf import briefkopf_kontext
from core.services.dokumentsprache import in_sprache
from core.services.platzhalter import ersetze

#: Auszeichnungen, die eine HTML-Vorlage tragen darf.
ERLAUBT = frozenset({'p', 'br', 'b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'h1', 'h2', 'h3',
                     'table', 'thead', 'tbody', 'tr', 'td', 'th', 'span', 'div', 'hr',
                     'blockquote', 'small'})
#: Attribute, die bleiben dürfen — nur Tabellenspannen, keine Stile, keine Verweise.
ATTRIBUTE = {'td': {'colspan', 'rowspan'}, 'th': {'colspan', 'rowspan'}}
#: Diese fallen samt Inhalt weg.
OHNE_INHALT = frozenset({'script', 'style', 'iframe', 'object', 'embed', 'head', 'title',
                         'template', 'svg', 'math', 'noscript', 'textarea', 'select'})
_LEER = frozenset({'br', 'hr'})


class _Bereiniger(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile = []
        self._weg = 0

    def handle_starttag(self, tag, attrs):
        if tag in OHNE_INHALT:
            self._weg += 1
            return
        if self._weg or tag not in ERLAUBT:
            return
        erlaubt = ATTRIBUTE.get(tag, set())
        attr = ''.join(f' {k}="{escape(v or "")}"' for k, v in attrs
                       if k in erlaubt and (v or '').isdigit())
        self.teile.append(f'<{tag}{attr}>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in OHNE_INHALT and self._weg:
            self._weg -= 1

    def handle_endtag(self, tag):
        if tag in OHNE_INHALT:
            self._weg = max(0, self._weg - 1)
            return
        if self._weg or tag not in ERLAUBT or tag in _LEER:
            return
        self.teile.append(f'</{tag}>')

    def handle_data(self, data):
        if not self._weg:
            self.teile.append(escape(data))


def bereinige_html(html):
    """Nur die erlaubten Auszeichnungen, Text maskiert."""
    p = _Bereiniger()
    p.feed(html or '')
    p.close()
    return ''.join(p.teile)


def text_als_html(inhalt, format, kontext):
    """Der Inhalt einer Vorlage, ersetzt und als sicheres HTML."""
    if format == 'html':
        return ersetze(bereinige_html(inhalt), kontext, html=True)
    return linebreaks(ersetze(inhalt, kontext), autoescape=True)


def dokument_kontext(*, betreff, inhalt, format, sprache, kontext, organisation):
    """Der Vorlagen-Kontext für `dok_vorlage.html` (PDF) und die Vorschau."""
    bk = briefkopf_kontext(organisation)
    ort_zeile = f"{kontext.get('mieter.plz', '')} {kontext.get('mieter.ort', '')}".strip()
    return {
        'briefkopf': bk,
        'mit_unterschrift': True,
        'dokumentsprache': sprache or 'de',
        'heute': timezone.localdate(),
        'vermieter_name': bk.get('firma', ''),
        'vermieter_strasse': bk.get('strasse', ''),
        'vermieter_plz': (organisation.plz if organisation else ''),
        'vermieter_ort': (organisation.ort if organisation else ''),
        'ort': (organisation.ort if organisation else ''),
        'empfaenger': {'name': kontext.get('mieter.name', ''),
                       'strasse': kontext.get('mieter.strasse', ''),
                       'plz_ort': ort_zeile},
        'betreff': ersetze(betreff or '', kontext),
        'text_html': text_als_html(inhalt, format, kontext),
    }


def vorlage_pdf(vorlage, kontext, organisation):
    """PDF-Bytes einer Vorlage (gespeichert oder nur im Formular) mit Kontext.

    `vorlage` braucht `betreff`, `inhalt`, `format` und `sprache` — eine
    ungespeicherte `crm.Vorlage` genügt (Probe-PDF im Editor).
    """
    sprache = getattr(vorlage, 'sprache', '') or 'de'
    ctx = dokument_kontext(betreff=vorlage.betreff, inhalt=vorlage.inhalt,
                           format=getattr(vorlage, 'format', 'text'), sprache=sprache,
                           kontext=kontext, organisation=organisation)
    from core.services.pdf_service import link_callback
    with in_sprache(sprache):
        html = get_template('core/dok_vorlage.html').render(ctx)
    puffer = io.BytesIO()
    status = pisa.CreatePDF(html, dest=puffer, link_callback=link_callback, encoding='utf-8')
    if status.err:
        raise RuntimeError(f'PDF aus Vorlage nicht erzeugt: {status.err}')
    return puffer.getvalue()
