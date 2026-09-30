"""Go-Live-Härtetest, Schritt 4: extreme Eingaben dürfen nie einen 500er auslösen.

Läuft über ALLE URL-Muster (nicht nur eine handgewählte Liste): Jede Route wird
mit Sonderzeichen-/Riesen-/Falschtyp-Werten in Pfad, Query und POST-Körper
beschossen — als Verwalter angemeldet, und anonym. Erlaubt ist alles unter 500.
"""
import json

from django.db import transaction
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from ._helfer import _basis_objekte, _team_user

WERTE = {
    'int': ['0', '-1', '99999999999999999999', '1', "1' OR '1'='1"],
    'str': ['x', "'; DROP TABLE core_mieter;--", '<script>alert(1)</script>', '../../etc/passwd',
            'ä' * 300, '\x00nul', '%00', '🔥'],
    'slug': ['x', "a'b", '../x'],
    'uuid': ['00000000-0000-0000-0000-000000000000'],
}
PAYLOADS = [
    {},
    {'id': "1' OR 1=1", 'betrag': 'abc', 'datum': '31.02.2024', 'status': 'x' * 5000},
    {'betrag': '9' * 400, 'menge': '-1e999', 'beginn': '0000-00-00', 'ende': '9999-99-99',
     'netto_mietzins': 'NaN', 'nebenkosten': 'Infinity', 'einheit_id': '99999999999999999999',
     'mieter_id': '-5', 'liegenschaft_id': 'abc', 'handwerker_id': '\x00', 'titel': 'ä' * 100000},
    {'pos_text': ['a'] * 300, 'pos_betrag': ['1e400'] * 300, 'm_raum': ['x'] * 50, 'm_kosten': ['NaN']},
    {'jahr': '99999', 'monat': '13', 'lg': 'x', 'seite': '-3', 'q': '\ud800'.encode('utf-8', 'ignore').decode()},
    {'\x00': 'x', 'a[b]': 'c', 'aktion': '<b>', 'typ': '💥' * 1000},
]


def _muster(resolver=None, prefix=''):
    resolver = resolver or get_resolver()
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            yield from _muster(p, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _urls():
    import re
    for roh, p in _muster():
        if roh.startswith(('admin', '^admin')) or 'media' in roh or 'static' in roh:
            continue
        conv = re.findall(r'<(?:(\w+):)?(\w+)>', roh)
        if len(conv) > 2:
            continue
        for i in range(4):
            url = roh
            for typ, name in conv:
                vals = WERTE.get(typ or 'str', WERTE['str'])
                url = re.sub(r'<(?:\w+:)?' + name + '>', vals[i % len(vals)].replace('/', '%2F') or 'x', url, count=1)
            url = re.sub(r'\(\?P<\w+>[^)]*\)', '1', url).replace('^', '').replace('$', '')
            yield '/' + url.lstrip('/')


class FuzzTests(TestCase):

    def setUp(self):
        _basis_objekte()
        self.eingeloggt = Client(raise_request_exception=False)
        self.eingeloggt.force_login(_team_user('Verwalter'))
        self.anonym = Client(raise_request_exception=False)

    def _beschiessen(self, client, gruppe):
        fehler = []
        urls = sorted(set(_urls()))
        for url in urls:
            if url.endswith(('/logout/', '/abmelden/')) or 'loeschen' in url or 'reset' in url:
                continue      # zerstört den Testzustand, ist kein Eingabetest
            for methode in ('get', 'post'):
                for payload in ([{}] if methode == 'get' else PAYLOADS):
                    # Savepoint je Anfrage: Ein Datenbankfehler in EINER Route darf
                    # die Transaktion des Tests nicht vergiften, sonst meldet jede
                    # Folgeroute einen Scheinfehler. Zurückgerollt wird immer.
                    with transaction.atomic():
                        try:
                            r = getattr(client, methode)(url, payload, secure=True)
                        except Exception as exc:       # ungefangen bis zum Client
                            fehler.append((methode.upper(), url, repr(exc)[:120]))
                            transaction.set_rollback(True); continue
                        transaction.set_rollback(True)
                    if r.status_code >= 500:
                        ei = getattr(r, 'exc_info', None) or (None, None, None)
                        fehler.append((methode.upper(), url, f'{r.status_code} {ei[0].__name__ if ei[0] else ""}: {str(ei[1])[:100]}'))
        self.assertEqual(sorted(set(fehler), key=str)[:60], [], f'{gruppe}: {len(set(fehler))} Route(n) mit 500')

    def test_angemeldet(self):
        self._beschiessen(self.eingeloggt, 'angemeldet')

    def test_anonym(self):
        self._beschiessen(self.anonym, 'anonym')

    def test_json_und_riesige_koerper(self):
        c = self.anonym
        for url in ('/api/mietprozess/public/bewerben', '/api/rentals/webhook/docuseal',
                    '/schaden/melden/', '/bewerben/1/'):
            for body, ct in ((b'{' * 100000, 'application/json'), (b'[]', 'application/json'),
                             (json.dumps({'a': 'x' * 3_000_000}).encode(), 'application/json'),
                             (b'\xff\xfe\x00', 'application/json'), (b'--x', 'multipart/form-data; boundary=x')):
                r = c.post(url, body, content_type=ct, secure=True)
                self.assertLess(r.status_code, 500, f'{url} {ct} {body[:20]!r}')
