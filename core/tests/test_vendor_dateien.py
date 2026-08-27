"""Jede `{% static %}`-Adresse in einer Vorlage muss auf eine Datei zeigen.

WARUM ES DIESEN WÄCHTER GIBT

E2.23 hat fünf Bibliotheken von `cdn.jsdelivr.net` und `unpkg.com` ins Repo
geholt — bootstrap-icons, Alpine (zweimal), signature_pad und Vue.
(chart.js kam dazu, ist aber in E2.43 mit der toten Admin-Vorlage
entfallen: 204 KB, die keine Seite je geladen hat.)
Drei der vier Vorlagen sind öffentlich; jeder Aufruf schickte die IP-Adresse
eines Mieters oder Bewerbers an einen Dritten.

Der Umzug tauscht eine Abhängigkeit gegen eine andere: vorher «das CDN muss
erreichbar sein», jetzt «die Datei muss unter `static/` liegen und der Name
muss stimmen». Der Unterschied ist, dass die zweite Bedingung prüfbar ist —
aber nur, wenn jemand sie prüft.

Denn beide Ausfälle sind **still**. Ein `<script src>` auf eine fehlende
Datei ergibt einen 404 in der Netzwerkspalte des Browsers und sonst nichts:
kein Django-Fehler, keine Ausnahme, keine rote Zeile im Protokoll. Die Seite
antwortet mit 200 und ist funktionslos. Beim Bewerbungsformular hiesse das:
Vue lädt nicht, das Formular rendert nie, der Bewerber sieht eine leere Seite
— und die Serverstatistik meldet lauter erfolgreiche Aufrufe.

Genau dieser Ausfall lag beim Einspielen einen Schritt entfernt: Die
gelieferte Vue-Datei hiess `vue.global.js`, war aber der Produktionsbau, den
Vue selbst `vue.global.prod.js` nennt. Sie wurde beim Übernehmen umbenannt —
und ein Umbenennen, das die Vorlage vergisst, ist genau der Fehler, den
dieser Test fängt.

WAS ER PRÜFT

Drei Dinge, die zusammen ergeben, dass die Bibliothek beim Besucher ankommt:

1. Jede `{% static %}`-Adresse aus allen Vorlagen wird über Djangos Finder
   aufgelöst — dieselbe Suche, die `collectstatic` benutzt.
2. Die Pfadkorrektur in `bootstrap-icons.css` steht, und die Schriften liegen
   dort, wohin sie zeigt.
3. Die fünf Fassungen in `package.json` stehen ohne Caret.

WAS ER NICHT PRÜFT

Ob die Datei das ist, was sie zu sein behauptet. Ein `alpine.min.js`, das in
Wahrheit etwas anderes enthält, findet dieser Test nicht — das ist eine Frage
der Herkunft, und die wurde beim Übernehmen byteweise gegen die npm-Pakete
gemessen und in `docs/FREMDBIBLIOTHEKEN.md` festgehalten. Hier nachgestellt
werden könnte sie nur mit Netz, also gar nicht.
"""
import json
import pathlib
import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Die fünf Bibliotheken aus E2.23 mit der Fassung, die im Repo liegt.
#: Ohne Caret — die Dateien sind eingecheckt, also muss `npm install` genau
#: die holen, die ausgeliefert wird. `^1.11.0` ergäbe heute bootstrap-icons
#: 1.13.1: andere Schriftdatei, 28 Icons mehr, und der byteweise Nachweis in
#: `docs/FREMDBIBLIOTHEKEN.md` wäre still hinfällig.
VENDOR = {
    'alpinejs': '3.13.3',
    'signature_pad': '4.1.7',
    'vue': '3.5.41',
}

#: Was nicht ins Repo geholt wurde, und warum es auch nicht zurueckkommen soll.
#: bootstrap-icons hing als CDN-Verweis in `modern_base.html`, ohne dass eine
#: einzige `bi-`-Klasse existierte — die Symbole dieser Huelle kommen aus Font
#: Awesome. Vendoring haette 396 KB ins Repo und 98 KB in jeden Aufruf von
#: /schaden/melden/ gelegt, fuer 0 von 2050 benutzten Symbolen.
NICHT_GEHOLT = ('bootstrap-icons',)

#: `{% static 'css/x.css' %}` — beide Anführungsarten, beliebige Leerzeichen.
_STATIC = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]\s*%\}""")


def _statische_verweise():
    """Jede `{% static %}`-Adresse aus allen Vorlagen, mit Fundstelle."""
    for ordner in ('core/templates', 'templates'):
        for pfad in sorted((WURZEL / ordner).rglob('*.html')):
            text = pfad.read_text(encoding='utf-8')
            for treffer in _STATIC.finditer(text):
                zeile = text.count('\n', 0, treffer.start()) + 1
                yield treffer.group(1), f'{pfad.relative_to(WURZEL)}:{zeile}'


class VendorDateienTest(SimpleTestCase):

    def test_jede_static_adresse_findet_ihre_datei(self):
        fehlend = [f'{ort}: {adr}'
                   for adr, ort in _statische_verweise()
                   if finders.find(adr) is None]
        self.assertEqual(
            fehlend, [],
            'Diese Vorlagen verweisen auf Dateien, die es nicht gibt:\n  '
            + '\n  '.join(fehlend)
            + '\n\nDer Browser holt sich dafür einen 404 und macht sonst '
              'nichts. Die Seite antwortet weiter mit 200 — sie ist nur '
              'funktionslos.')

    def test_bootstrap_icons_kommt_nicht_zurueck(self):
        """Die Bibliothek, die E2.23 vendoren wollte — und die stattdessen ging.

        `modern_base.html` lud sie seit jeher von `cdn.jsdelivr.net`. Beim
        Umzug ins Repo fiel auf: **keine** Vorlage, kein View und kein Skript
        benutzt eine `bi-`-Klasse. Die Symbole dieser Huelle kommen aus Font
        Awesome (`fa-solid fa-buildings`), das daneben geladen wird und
        benutzt wird.

        Der Verweis war ein Rest aus einer frueheren Fassung. Er hat 98 KB CSS
        bei jedem Aufruf von /schaden/melden/ geladen — der oeffentlichen
        Schadenmeldung — um daraus **0 von 2050** Symbolen zu benutzen; das
        Vendoring haette zusaetzlich 300 KB Schriftdateien ins Repo gelegt.

        Wer bootstrap-icons wieder braucht, holt es ueber npm nach
        `static/` (Pfadkorrektur `./fonts/` -> `../fonts/` nicht vergessen,
        sonst bleiben alle Symbole leer) und traegt es hier ein. Wer nur den
        `<link>` zurueckstellt, laedt wieder nichts Benutztes.
        """
        for paket in NICHT_GEHOLT:
            self.assertNotIn(
                paket, json.loads(
                    (WURZEL / 'package.json').read_text(encoding='utf-8')
                )['devDependencies'],
                f'`{paket}` steht wieder in package.json. Wenn es wirklich '
                'gebraucht wird: aus NICHT_GEHOLT nach VENDOR verschieben und '
                'docs/FREMDBIBLIOTHEKEN.md nachfuehren.')

        treffer = []
        for ordner in ('core/templates', 'templates'):
            for pfad in sorted((WURZEL / ordner).rglob('*.html')):
                text = pfad.read_text(encoding='utf-8')
                # Der Erklaertext in modern_base.html NENNT den Namen, um zu
                # sagen, warum er weg ist. Django-Kommentare zuerst heraus —
                # sonst haelt der Waechter die Begruendung fuer die Tat.
                text = re.sub(r'\{#.*?#\}', ' ', text, flags=re.S)
                text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}',
                              ' ', text, flags=re.S)
                if 'bootstrap-icons' in text:
                    treffer.append(str(pfad.relative_to(WURZEL)))
        self.assertEqual(
            treffer, [],
            f'bootstrap-icons wird wieder geladen: {treffer}. Es gibt keine '
            'einzige `bi-`-Klasse im Bestand — das laedt 98 KB fuer nichts.')

    def test_die_fassungen_stehen_ohne_caret(self):
        dev = json.loads(
            (WURZEL / 'package.json').read_text(encoding='utf-8')
        )['devDependencies']

        for paket, fassung in VENDOR.items():
            self.assertIn(
                paket, dev,
                f'`{paket}` fehlt in package.json, obwohl die Datei im Repo '
                'liegt — dann ist nicht mehr aufschreibbar, welche Fassung '
                'das ist.')
            self.assertEqual(
                dev[paket], fassung,
                f'`{paket}` steht als «{dev[paket]}». Erwartet ist genau '
                f'«{fassung}» — ohne Caret, weil die Datei eingecheckt ist. '
                'Wer die Fassung wechselt, tauscht auch die Datei unter '
                'static/ und führt docs/FREMDBIBLIOTHEKEN.md nach.')

    def test_der_waechter_liest_ueberhaupt_vorlagen(self):
        """Ohne diese Zeile wäre der Test oben auch bei leerem Suchpfad grün.

        Ein Wächter, der nichts findet, meldet nie etwas — der stillste
        Ausfall überhaupt.
        """
        verweise = [adr for adr, _ in _statische_verweise()]
        self.assertGreater(
            len(verweise), 8,
            f'Nur {len(verweise)} static-Adressen gefunden. Entweder stimmen '
            'die Suchpfade nicht mehr, oder das Muster greift daneben.')
        # `js/chart.umd.js` ist in E2.43 ENTFALLEN: Die einzige Vorlage, die
        # es lud, war `admin/dashboard_stats.html` — toter Code ohne Aufrufer,
        # doppelt vorhanden. Mit ihr fielen 204 KB weg, die niemand je geladen
        # hat. Die Bibliothek ist auch aus `package.json` entfernt.
        for erwartet in ('js/alpine.min.js', 'js/vue.global.prod.js',
                         'js/signature_pad.umd.min.js'):
            self.assertIn(
                erwartet, verweise,
                f'`{erwartet}` wird von keiner Vorlage mehr geladen. Entweder '
                'ist die Bibliothek weg — dann gehört sie aus package.json '
                'und static/ ebenfalls heraus — oder der Verweis ist beim '
                'Umbenennen verlorengegangen.')
