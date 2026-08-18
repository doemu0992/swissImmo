"""Erzwingt die Einrichtung des zweiten Faktors, wenn eine Verwaltung ihn verlangt.

WARUM MIDDLEWARE UND NICHT NUR EINE WEICHE NACH DEM ANMELDEN

`nach_login_view` ist der Trichter unmittelbar nach der Anmeldung — aber nur
dort. Wer die Adresse einer beliebigen Seite direkt eintippt, kommt an ihm
vorbei, und Sitzungen halten zwei Wochen (`SESSION_COOKIE_AGE`). Ein Schalter,
der erst beim nächsten Anmelden greift, greift bei einem angemeldeten Team also
über Tage gar nicht.

Die Middleware prüft dagegen jede Anfrage. Das kostet eine Abfrage pro Anfrage
für angemeldete Konten — und nur eine, weil sie zuerst am Sitzungsmerker
abbiegt, sobald die Einrichtung erledigt ist.

WAS SIE NICHT SPERRT

Abmelden, die Einrichtungsseiten selbst, statische Dateien und die
Anmeldeseiten. Ohne diese Ausnahmen bliebe der Benutzer in einer Schleife:
umgeleitet auf die Einrichtung, die selbst wieder umgeleitet wird.
"""
from django.shortcuts import redirect
from django.urls import reverse

#: Namen der URL-Muster, die immer erreichbar bleiben müssen.
FREI = {
    'zweifaktor_einrichten', 'zweifaktor_uebersicht', 'zweifaktor_codes_neu',
    'zweifaktor_bestaetigen', 'zweifaktor_aus',
    'login', 'portal_login', 'logout',
}

#: Präfixe, die nie umgeleitet werden (Dateien, Gesundheitsprüfungen).
FREIE_PFADE = ('/static/', '/media/', '/favicon')


class ZweiFaktorPflichtMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Erst NACH der URL-Auflösung prüfen.

        In `__call__` ist `request.resolver_match` noch `None` — die Auflösung
        geschieht erst danach. Die Ausnahmeliste unten arbeitet aber mit
        URL-Namen; in `__call__` wäre sie wirkungslos gewesen und hätte die
        Einrichtungsseite auf sich selbst umgeleitet.
        """
        return self._pruefen(request)

    def _pruefen(self, request):
        benutzer = getattr(request, 'user', None)
        if benutzer is None or not benutzer.is_authenticated:
            return None
        if request.session.get('zf_erledigt'):
            # Einmal geprüft, dann nicht mehr — die Sitzung endet spätestens
            # mit dem Abmelden, und der Faktor lässt sich unter Pflicht nicht
            # entfernen (siehe `zweifaktor_aus`).
            return None
        if request.path.startswith(FREIE_PFADE):
            return None
        muster = getattr(request.resolver_match, 'url_name', None)
        if muster in FREI:
            return None

        from core.models import ZweiterFaktor
        from core.views.zweifaktor import _pflicht_fuer

        if not _pflicht_fuer(benutzer):
            request.session['zf_erledigt'] = True
            return None
        faktor = ZweiterFaktor.objects.filter(benutzer=benutzer).first()
        if faktor is not None and faktor.ist_aktiv:
            request.session['zf_erledigt'] = True
            return None
        return redirect(reverse('zweifaktor_einrichten'))
