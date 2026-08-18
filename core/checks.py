"""Startprüfungen — was beim Hochfahren auffallen soll, statt nachts um vier.

Bisher gab es hier nichts; `core/wartung.py` prüft den Migrationsstand, das war
alles. Mit den Postfächern kommt ein Zustand dazu, den man **vorher** merken
will: hinterlegte Zugangsdaten, aber kein `IMAP_SCHLUESSEL`. Ohne ihn scheitert
jeder Abruf — und zwar zur Abrufzeit, also in der Nacht, in einem
Scheduler-Protokoll, das niemand liest.

WARUM WARNUNG UND NICHT FEHLER

Ein `checks.Error` lässt `manage.py migrate` abbrechen. Das Deploy läuft
unbeaufsichtigt; ein Abbruch dort nähme die ganze Anwendung vom Netz — wegen
eines Postfachs. Die Rangfolge ist klar: Ein nicht abgeholtes E-Mail ist ein
Ärgernis, eine tote Website ein Ausfall.
"""
from django.core.checks import Warning, register


@register()
def postfaecher_brauchen_einen_schluessel(app_configs, **kwargs):
    """Zugangsdaten hinterlegt, aber kein Schlüssel gesetzt?"""
    from core.services.geheimnis import UMGEBUNGSNAME, schluessel_vorhanden

    if schluessel_vorhanden():
        return []

    from core.models import Postfach

    try:
        betroffen = Postfach.alle_organisationen.exclude(
            passwort_geheim='', refresh_token_geheim='').count()
    except Exception:                                          # noqa: BLE001
        # Die Tabelle gibt es noch nicht. Genau dieser Fall tritt bei jedem
        # `migrate` auf einer frischen Datenbank ein — die Prüfung läuft VOR
        # den Migrationen. Hier zu werfen hiesse, dass sich die Anwendung
        # nicht mehr aufsetzen lässt.
        return []

    if not betroffen:
        # Nichts hinterlegt, nichts zu warnen. Ein Hinweis «Schlüssel fehlt»
        # auf einer Installation ohne Postfächer wäre Lärm — und Lärm ist der
        # sicherste Weg, dass später auch die echte Warnung überlesen wird.
        return []

    return [Warning(
        f'{betroffen} Postfach/Postfächer haben hinterlegte Zugangsdaten, aber '
        f'{UMGEBUNGSNAME} ist nicht gesetzt. Die Zugangsdaten lassen sich damit '
        'nicht entschlüsseln — jeder E-Mail-Abruf wird scheitern.',
        hint=f'{UMGEBUNGSNAME}=… in die .env eintragen und die Web-App neu laden. '
             'Ist der Schlüssel verloren, müssen die Zugangsdaten in den '
             'Einstellungen neu eingegeben werden.',
        id='core.W001')]
