"""NUL-Bytes in Eingaben (PostgreSQL wirft sonst einen DataError → 500)."""
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from core.middleware_nul import NulBytesMiddleware


def _durchlauf(request):
    gesehen = {}

    def antwort(r):
        gesehen['get'] = r.GET
        gesehen['post'] = r.POST
        return HttpResponse('ok')

    NulBytesMiddleware(antwort)(request)
    return gesehen


class NulBytesTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_get_wird_bereinigt(self):
        g = _durchlauf(self.rf.get('/x/', {'q': 'a\x00b', 'sort': '\x00', 'z': 'ok'}))
        self.assertEqual(g['get']['q'], 'ab')
        self.assertEqual(g['get']['sort'], '')
        self.assertEqual(g['get']['z'], 'ok')

    def test_mehrfachwerte_und_schluessel(self):
        g = _durchlauf(self.rf.get('/x/?a=1%00&a=%002&k%00x=v'))
        self.assertEqual(g['get'].getlist('a'), ['1', '2'])
        self.assertEqual(g['get']['kx'], 'v')

    def test_post_formular_wird_bereinigt(self):
        g = _durchlauf(self.rf.post('/x/', {'name': 'Mu\x00ster'}))
        self.assertEqual(g['post']['name'], 'Muster')

    def test_json_body_bleibt_unberuehrt(self):
        r = self.rf.post('/x/', data='{"a": "b"}', content_type='application/json')
        _durchlauf(r)
        self.assertEqual(r.body, b'{"a": "b"}')

    def test_ohne_nul_bleibt_dasselbe_objekt(self):
        r = self.rf.get('/x/', {'q': 'normal'})
        vorher = r.GET
        self.assertIs(_durchlauf(r)['get'], vorher)
