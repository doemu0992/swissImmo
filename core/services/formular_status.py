"""Welches amtliche Formular für eine Liegenschaft vorliegt — und die Warnung,
wenn keines vorliegt (Befunde G und J des Audits vom 26.10.2026).

Ausgelagert aus `formular_fill.py`, weil diese Texte übersetzt werden: Die
Erzeuger dort bleiben fest deutsch und damit im Wächter `test_nur_deutsch`.

Kein Formular ohne erfassten Kanton (`kantone.formular_kanton`, nie aus der
PLZ); ohne Kantonsoriginal eine sperrende Warnung mit der Rechtsfolge.
"""


def _folge(typ):
    """Die Folge je Formulartyp, mit der Fundstelle aus dem Gesetzesregister
    (`core/services/gesetzestexte.py`: 269d «sonst nichtig», 266o «nichtig»)."""
    from django.utils.translation import gettext
    if typ == 'kuendigung':
        return gettext('ohne amtliches Formular ist die Kündigung nichtig (Art. 266l/266o OR)')
    if typ == 'anfangsmietzins':
        return gettext('ohne amtliches Formular ist die Mitteilung mangelhaft (Art. 270 Abs. 2 OR)')
    return gettext('ohne amtliches Formular ist die Anpassung nichtig (Art. 269d OR)')


def formular_status(lg, typ):
    """Was für das amtliche Formular `typ` dieser Liegenschaft vorliegt.

    `kanton` — nur aus dem Feld der Liegenschaft (`kantone.formular_kanton`);
    `kanton_fehlt` — dann wird KEIN Formular erzeugt, auch keine Nachbildung;
    `original` — ein Kantonsoriginal ist hinterlegt;
    `warnung` — der Satz, der ohne Original vor jedem Herunterladen steht.
    """
    from django.utils.translation import gettext
    from core.services.formular_fill import hat_original
    from core.services.kantone import KANTON_NAMEN, formular_kanton, plz_kantone
    kt = formular_kanton(lg)
    original = bool(kt) and hat_original(kt, typ)
    warnung = ''
    if kt and not original:
        warnung = gettext(
            'Für Kanton %(kanton)s ist kein amtliches Originalformular hinterlegt — verwenden '
            'Sie das Formular der kantonalen Behörde; %(folge)s.') % {
                'kanton': KANTON_NAMEN.get(kt, kt), 'folge': _folge(typ)}
    return {
        'kanton': kt, 'kanton_name': KANTON_NAMEN.get(kt, '') if kt else '',
        'kanton_fehlt': kt is None, 'original': original, 'warnung': warnung,
        'plz_kandidaten': plz_kantone(getattr(lg, 'plz', '')) if kt is None else [],
    }


def kanton_fehlt_meldung(lg):
    """Klartext, wenn der Kanton der Liegenschaft nicht erfasst ist."""
    from django.utils.translation import gettext
    from core.services.kantone import plz_kantone
    kandidaten = plz_kantone(getattr(lg, 'plz', ''))
    satz = gettext('Für das amtliche Formular muss der Kanton der Liegenschaft erfasst sein — '
                   'die Postleitzahl allein bestimmt ihn nicht sicher.')
    if len(kandidaten) > 1:
        satz += ' ' + gettext('PLZ %(plz)s liegt in Bereichen von: %(kantone)s.') % {
            'plz': getattr(lg, 'plz', ''), 'kantone': ', '.join(kandidaten)}
    return satz
