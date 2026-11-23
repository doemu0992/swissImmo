"""Filter für die Mail-Vorlagen (templates/emails)."""
from django import template
from django.utils.html import escape, format_html
from django.utils.translation import gettext
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def klartext_link(text, link=''):
    """Klartext → HTML: maskiert, Zeilenumbrüche als <br>, und `link` (falls im Text) als Anker.

    Zuerst wird maskiert, danach der Link ersetzt: Titel und Beschreibung stammen von Melderinnen und Meldern
    (öffentliches Formular) und dürfen nie als HTML in die Mail gelangen."""
    sicher = escape(text or '')
    if link:
        anker = format_html('<a href="{0}">{0}</a>', link)
        sicher = mark_safe(str(sicher).replace(str(escape(link)), str(anker)))
    return mark_safe(str(sicher).replace('\n', '<br>'))


@register.simple_tag
def klartext_mit_knopf(text, link='', knopf='', stil=None):
    """Klartext → HTML wie `klartext_link`, aber der Link wird zum KNOPF; die Adresse bleibt klein darunter.

    Der Text bleibt Wort für Wort stehen. Zuerst wird maskiert, danach der Link ersetzt (Titel und Beschreibung
    stammen von Melderinnen und Meldern). Die Adresse darunter ist der Ausweichweg für Mailprogramme, die den
    Knopf nicht zeigen, und lässt die Empfängerin sehen, wohin er führt."""
    stil = stil or {}
    sicher = str(escape(text or ''))
    if link and str(escape(link)) in sicher:
        ersatz = format_html(
            '<a href="{0}" style="{1}">{2}</a><br><span style="{3}">{4} <a href="{0}" style="{5}">{0}</a></span>',
            link, stil.get('knopf', ''), knopf or gettext('Öffnen'), stil.get('klein', ''),
            gettext('Falls der Knopf nicht geht:'), stil.get('link_klein', ''))
        # Nur das erste Vorkommen wird zum Knopf; ein zweites bliebe als Text stehen.
        sicher = sicher.replace(str(escape(link)), str(ersatz), 1)
    return mark_safe(sicher.replace('\n', '<br>'))
