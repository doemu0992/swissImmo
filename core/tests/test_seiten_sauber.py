"""Keine Reste auf ausgelieferten Seiten: unaufgelöste Vorlagenmarken, «None», «undefined», Blindtext.

WARUM
Ein `{{ wert }}`, das als Text ausgeliefert wird, ein «None» statt eines leeren Felds oder ein
Blindtext fallen keinem Test auf, der nur auf Statuscode 200 und ein Stichwort prüft (siehe
`bekannte-fallen` 8 und 9: Django schweigt bei unbekannten Feldern). Dieser Lauf holt jede
parameterlose Seite der Anwendung mit einem vollständigen Bestand (Inhaber) und die
öffentlichen Seiten und sucht im SICHTBAREN Text nach Resten.

Gegenprobe: in einer Vorlage `{{ kaputt|default:None }}` oder ein `{% trans 'x' %` einbauen und
den Test laufen lassen (Protokoll im Commit).
"""
import re

from django.test import Client
from django.urls import NoReverseMatch, reverse

from portfolio.models import Einheit
from core.tests.test_isolation import AUSNAHMEN, IsolationsBasis, _parameterlose_fw_urls

#: Was im sichtbaren Text nichts verloren hat.
RESTE = (
    (re.compile(r'\{%|%\}|\{#|#\}'), 'unaufgelöste Vorlagenmarke'),
    (re.compile(r'\{\{|\}\}'), 'unaufgelöste Variable'),
    (re.compile(r'(?<![\w.-])None(?![\w-])'), '«None» als Wert'),
    (re.compile(r'(?<![\w.-])undefined(?![\w-])'), '«undefined»'),
    (re.compile(r'(?<![\w.-])NaN(?![\w-])'), '«NaN»'),
    (re.compile(r'lorem ipsum|dolor sit amet', re.I), 'Blindtext'),
    (re.compile(r'%\([a-z_]+\)[sd]'), 'unersetzter Formatplatz'),
)

#: Seiten, die absichtlich solche Zeichen zeigen (Anleitungen zu Platzhaltern o. ä.) — mit Grund.
ERLAUBT = {
    # Der Vorlagen-Editor erklärt die Platzhalter {mieter_name} — das sind einfache Klammern, keine
    # Django-Marken; hier trotzdem aufgeführt, falls eine Seite die Syntax wörtlich erklärt.
}


def sichtbarer_text(html):
    """Text ohne `<script>`, `<style>`, Kommentare, `<template>` und Attribute."""
    html = re.sub(r'<(script|style|template|textarea)\b.*?</\1>', ' ', html, flags=re.S | re.I)
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.S)
    return re.sub(r'<[^>]*>', ' ', html)


def reste_in(html):
    text = sichtbarer_text(html)
    funde = []
    # Alpine/Vue schreiben `{{ wert }}` selbst in den Text: Dort ist die Klammer Absicht.
    clientseitig = re.search(r'\bx-data\b|createApp|\bv-(?:if|for|model|text)\b', html)
    for muster, name in RESTE:
        if clientseitig and name == 'unaufgelöste Variable':
            continue
        treffer = muster.search(text)
        if treffer:
            ausschnitt = text[max(0, treffer.start() - 30):treffer.end() + 30]
            funde.append(f'{name}: …{" ".join(ausschnitt.split())}…')
    return funde


class SeitenSauberTests(IsolationsBasis):

    def test_keine_reste_auf_den_seiten_der_anwendung(self):
        gepr = 0
        probleme = {}
        for name in _parameterlose_fw_urls():
            if name in AUSNAHMEN or name in ERLAUBT:
                continue
            try:
                pfad = reverse(name)
            except NoReverseMatch:
                continue
            antwort = self.client.get(pfad)
            ctype = antwort.headers.get('Content-Type', '')
            if antwort.status_code != 200 or 'text/html' not in ctype:
                continue
            gepr += 1
            funde = reste_in(antwort.content.decode('utf-8', 'replace'))
            if funde:
                probleme[pfad] = funde
        self.assertGreater(gepr, 60, 'auffällig wenige Seiten geprüft')
        self.assertEqual(probleme, {}, 'Reste auf Seiten:\n' + '\n'.join(
            f'  {p}: {f}' for p, f in sorted(probleme.items())))

    def test_keine_reste_auf_den_oeffentlichen_seiten(self):
        anonym = Client()
        gepr = 0
        probleme = {}
        eid, lid = self.a.einheit.pk, self.a.liegenschaft.pk
        # Das Bewerbungsformular gibt es nur für ausgeschriebene Objekte (sonst 410).
        Einheit.alle_organisationen.filter(pk=eid).update(zur_ausschreibung=True)
        seiten = (reverse('public_datenschutz_objekt', args=[eid]), reverse('public_bewerbung', args=[eid]),
                  reverse('public_report', args=[lid]), reverse('schaden_melden'),
                  reverse('public_datenschutz'))
        for pfad in seiten:
            antwort = anonym.get(pfad, HTTP_HOST='localhost')
            if antwort.status_code != 200:
                probleme[pfad] = [f'Status {antwort.status_code}']
                continue
            gepr += 1
            funde = reste_in(antwort.content.decode('utf-8', 'replace'))
            if funde:
                probleme[pfad] = funde
        self.assertEqual(probleme, {}, f'Reste auf öffentlichen Seiten: {probleme}')

    def test_der_scan_erkennt_reste(self):
        """Selbstprüfung: ohne sie wäre ein Scan, der nichts findet, nicht von einem blinden zu unterscheiden."""
        self.assertTrue(reste_in('<p>Miete: {{ betrag }}</p>'))
        self.assertTrue(reste_in('<p>{% trans </p>'))
        self.assertEqual(reste_in('<div x-data="{}"><p>{{ schritt }}</p></div>'), [])
        self.assertTrue(reste_in('<p>Ort: None</p>'))
        self.assertTrue(reste_in('<p>Lorem ipsum dolor</p>'))
        self.assertEqual(reste_in('<script>var x = undefined; {{ a }}</script><p>Sauber, Nonne</p>'), [])
