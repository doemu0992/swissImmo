"""Die Oberfläche bietet einer Rolle nur an, was sie öffnen darf (ROUTE-02, DESIGN-01).

WARUM ES DIESEN WÄCHTER GIBT

`test_rbac` erwartet bei Rollen ohne Recht exakt 403 und kann deshalb nicht
sehen, dass die Seite die Aktion trotzdem anbietet. Das Audit vom 28.10.2026
zählte 169 tote Schreibaktionen auf 48 Seiten (Lesezugriff); die Hauswartung
stiess auf `/neu/schaeden/<id>/` auf 13 Formulare, von denen 10 mit «Keine
Berechtigung» endeten, dazu Links und die Kopfzeile.

WAS GEPRÜFT WIRD

Ausgehend von den Seiten, die die Rolle öffnen darf, wird jede erreichbare Seite
abgerufen; jedes `<a href>` und jedes `<form method=post action>` einer Seite
muss auf eine Ansicht zeigen, deren Dekorator (`benoetigte_rollen`) die Rolle
nennt. Der Dekorator ist die einzige Quelle der Wahrheit: Es gibt keine zweite,
von Hand gepflegte Liste (`core.auth.darf_oeffnen` liest ebenso).

Für die Hauswartung gilt die Zusage ohne Ausnahme. Für Lesezugriff und
Sachbearbeiter ist der Bestand noch nicht bereinigt; ihre Zahl steht als
Obergrenze in `BEKANNT_OFFEN` und darf nur sinken.
"""
import html
import re
from urllib.parse import urlsplit

from django.urls import Resolver404, resolve

from core.auth import _mit_inhaber

from ._rollen import RollenBasis

HREF = re.compile(r'<a\b[^>]*?\bhref=["\']([^"\']+)["\']', re.I)
FORM = re.compile(r'<form\b([^>]*)>', re.I)
ACTION = re.compile(r'\baction=["\']([^"\']*)["\']', re.I)
POST = re.compile(r'\bmethod=["\']post["\']', re.I)

#: Adressen, die kein Ziel einer Rolle sind: Anmeldung, Wechsel des Mandanten, Abmeldung.
UEBERSPRINGEN = ('/logout', '/abmelden', '/mandant', '/login')


def _rolle_erlaubt(rolle, pfad):
    """True/False, wenn die Ansicht ihre Rollen nennt; None, wenn sie keinen Dekorator trägt."""
    try:
        ansicht = resolve(pfad).func
    except Resolver404:
        return None
    rollen = getattr(ansicht, 'benoetigte_rollen', None)
    if rollen is None:
        return None
    return rolle in _mit_inhaber(rollen)


def tote_ziele(client, rolle, starts, hoechstens=60):
    """Kriecht ab `starts` und liefert {(seite, art, ziel)} der Ziele, die `rolle` nicht öffnen darf."""
    besucht, warteschlange, tot, seiten = set(), list(starts), set(), 0
    while warteschlange and seiten < hoechstens:
        pfad = warteschlange.pop(0)
        if pfad in besucht:
            continue
        besucht.add(pfad)
        antwort = client.get(pfad)
        if antwort.status_code in (301, 302) and antwort['Location'].startswith('/neu/'):
            warteschlange.append(antwort['Location'])
            continue
        if antwort.status_code != 200 or 'text/html' not in antwort.get('Content-Type', ''):
            continue
        seiten += 1
        text = antwort.content.decode('utf-8', 'replace')
        ziele = [('Link', html.unescape(h)) for h in HREF.findall(text)]
        for attribute in FORM.findall(text):
            if POST.search(attribute):
                treffer = ACTION.search(attribute)
                ziele.append(('Formular', html.unescape(treffer.group(1)) if treffer else pfad))
        for art, ziel in ziele:
            if not ziel.startswith('/neu') and not ziel.startswith('/konto'):
                continue
            ziel_pfad = urlsplit(ziel).path
            if any(ziel_pfad.startswith(u) for u in UEBERSPRINGEN):
                continue
            erlaubt = _rolle_erlaubt(rolle, ziel_pfad)
            if erlaubt is False:
                tot.add((pfad, art, ziel_pfad))
            elif art == 'Link' and erlaubt is not False and ziel_pfad not in besucht:
                warteschlange.append(ziel)
    return tot, besucht


class HauswartSiehtNurErlaubtesTests(RollenBasis):
    """Die Hauswartung: Schadenliste, Board und Schadenakte ohne tote Knöpfe."""

    def setUp(self):
        from core.tenancy import organisation_kontext
        from tickets.models import SchadenFoto, TicketNachricht
        self.hw = self.client_von('hauswart')
        with organisation_kontext(self.org):
            self.a.liegenschaft.hauswarte.add(self.benutzer['hauswart'])
            # Alle Zweige der Akte rendern: ein Foto (Löschknopf), eine Nachricht, ein Auftrag.
            SchadenFoto.objects.create(schaden=self.a.schaden, bild='schaden/x.jpg')
            TicketNachricht.objects.create(ticket=self.a.schaden, absender_name='Melder', nachricht='Tropft')
            self.a.auftrag.termin_status = 'vereinbart'
            self.a.auftrag.save()

    def _starts(self):
        s = self.a.schaden.pk
        return ['/neu/schaeden/', '/neu/schaeden/board/', f'/neu/schaeden/{s}/']

    def test_kein_link_und_kein_formular_fuehrt_in_die_403(self):
        tot, besucht = tote_ziele(self.hw, 'Hauswart', self._starts())
        self.assertGreaterEqual(len(besucht), 3, 'die Schadenseiten wurden nicht erreicht')
        self.assertEqual(sorted(tot), [], f'{len(tot)} Ziele, die die Hauswartung nicht öffnen darf')

    def test_die_schadenakte_bietet_den_statuswechsel_an(self):
        """Gegenprobe zur Gegenprobe: Die Seite ist nicht einfach leergeräumt."""
        antwort = self.hw.get(f'/neu/schaeden/{self.a.schaden.pk}/')
        self.assertContains(antwort, f'/neu/schaeden/{self.a.schaden.pk}/status/')
        self.assertNotContains(antwort, '/auftrag/')

    def test_der_sucher_findet_tote_ziele_wenn_es_welche_gibt(self):
        """Selbstprüfung des Suchers: Die Sachbearbeitung sieht auf der Schadenakte Aktionen, die
        die Hauswartung nicht öffnen darf. Misst er die Seite der Sachbearbeitung mit dem Mass der
        Hauswartung, muss er sie finden — sonst wäre die Zusage oben ohne Aussage."""
        tot, _ = tote_ziele(self.client_von('sachbearbeiter'), 'Hauswart',
                            [f'/neu/schaeden/{self.a.schaden.pk}/'])
        ziele = {ziel for _seite, _art, ziel in tot}
        self.assertIn(f'/neu/schaeden/{self.a.schaden.pk}/auftrag/', ziele)
        self.assertIn(f'/neu/schaeden/{self.a.schaden.pk}/foto/', ziele)
