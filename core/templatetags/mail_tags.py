"""Filter für die Mail-Vorlagen (templates/emails)."""
from django import template
from django.utils.html import escape, format_html
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
