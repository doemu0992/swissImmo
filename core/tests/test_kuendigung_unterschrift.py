"""Kündigung und 257d-Brief tragen kein Unterschriftsbild; die Hinweise stehen im Versandschritt (MIET-03).

DIE RECHTSLAGE

* Art. 266l Abs. 1 OR: Vermieter und Mieter von Wohn- und Geschäftsräumen müssen **schriftlich** kündigen.
* Art. 266o OR: Eine Kündigung, die den Art. 266l–266n nicht entspricht, ist **nichtig**.
* Art. 14 Abs. 1 OR: Die Unterschrift ist eigenhändig zu schreiben; Abs. 2: eine mechanische Nachbildung genügt nur, wo
  sie im Verkehr üblich ist; Abs. 2bis: gleichgestellt ist die qualifizierte elektronische Signatur.
* Art. 269d Abs. 4 OR (neu seit 1.10.2025): Für die Mitteilung einer Mietzinserhöhung genügt eine mechanisch
  nachgebildete Unterschrift. Das gilt NICHT für die Kündigung. Im Bestand steht an keiner Stelle, dass das Faksimile
  bei der Kündigung zulässig sei — darum wird es nicht gesetzt.

Die Mietzins-Formulare behalten ihr Unterschriftsbild (Art. 269d Abs. 4); das ist hier nicht berührt.
"""
import io
import tempfile
from datetime import date

from django.contrib.messages import get_messages
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from pypdf import PdfReader

from ._helfer import _basis_objekte, _sig_bytes, _team_user


def _bilder(pdf_bytes):
    """Anzahl Bilder je Seite."""
    return [len(list(seite.images)) for seite in PdfReader(io.BytesIO(pdf_bytes)).pages]


class _MitUnterschrift(TestCase):
    """Eigentümer und Verwaltung haben ein Unterschriftsbild; verglichen wird mit demselben PDF ohne."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._ov = override_settings(MEDIA_ROOT=self._tmp.name)
        self._ov.enable()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._ov.disable)
        self.lg, self.e, self.m, self.v = _basis_objekte()
        from crm.models import Eigentuemer
        self.eig = Eigentuemer.objects.create(firma_oder_name='Eigentümer AG', strasse='Weg 1', plz='4500',
                                              ort='Solothurn')
        self.lg.eigentuemer = self.eig
        self.lg.kanton = 'SO'
        self.lg.save()

    def _signatur(self, an):
        from crm.models import Eigentuemer, Organisation
        if an:
            self.eig.unterschrift_bild.save('sig.png', ContentFile(_sig_bytes()), save=True)
            self.v.organisation.unterschrift_bild.save('sig.png', ContentFile(_sig_bytes()), save=True)
        else:
            Eigentuemer.objects.filter(pk=self.eig.pk).update(unterschrift_bild='')
            Organisation.objects.filter(pk=self.v.organisation.pk).update(unterschrift_bild='')
        self.lg.refresh_from_db()
        self.v.refresh_from_db()
        self.v.organisation.refresh_from_db()

    def _kuendigung(self):
        from rentals.models import Kuendigung
        return Kuendigung.objects.create(vertrag=self.v, absender='vermieter', ausserordentlich=False,
                                         eingang_datum=date(2026, 11, 4), per_datum=date(2027, 3, 31))


class KuendigungsPdfTests(_MitUnterschrift):
    def test_so_original_traegt_kein_unterschriftsbild(self):
        from core.services.formular_fill import fill_kuendigung_so
        k = self._kuendigung()
        self._signatur(False)
        ohne = fill_kuendigung_so(self.v, k, verwaltung=self.v.organisation)
        self._signatur(True)
        mit = fill_kuendigung_so(self.v, k, verwaltung=self.v.organisation)
        self.assertEqual(_bilder(mit), _bilder(ohne),
                         'Das SO-Kündigungsformular trägt ein Unterschriftsbild (Art. 266l/266o OR).')

    def test_nachbildung_traegt_kein_unterschriftsbild_und_nennt_die_eigenhaendige_unterschrift(self):
        from core.services.amtliche_formulare_so import kuendigung_so_pdf
        k = self._kuendigung()
        self._signatur(False)
        ohne = kuendigung_so_pdf(self.v, k, verwaltung=self.v.organisation)
        self._signatur(True)
        mit = kuendigung_so_pdf(self.v, k, verwaltung=self.v.organisation)
        self.assertEqual(_bilder(mit), _bilder(ohne))
        text = PdfReader(io.BytesIO(mit)).pages[0].extract_text()
        self.assertIn('Unterschrift (eigenhändig)', text)

    def test_zh_und_be_originale_tragen_nie_ein_bild(self):
        from core.services.formular_fill import fill_kuendigung_be, fill_kuendigung_zh
        k = self._kuendigung()
        self._signatur(False)
        ohne = [fill_kuendigung_zh(self.v, k, verwaltung=self.v.organisation),
                fill_kuendigung_be(self.v, k, verwaltung=self.v.organisation)]
        self._signatur(True)
        mit = [fill_kuendigung_zh(self.v, k, verwaltung=self.v.organisation),
               fill_kuendigung_be(self.v, k, verwaltung=self.v.organisation)]
        for a, b in zip(ohne, mit):
            self.assertEqual(_bilder(b), _bilder(a))

    def test_mietzins_formular_behaelt_sein_unterschriftsbild(self):
        """Gegenprobe zur Abgrenzung: Für die Mietzinserhöhung ist das Faksimile ausdrücklich zulässig
        (Art. 269d Abs. 4 OR) — die Änderung betrifft nur die Kündigung."""
        from core.services.formular_fill import fill_mietzins_so
        daten = {'alt_netto': 1500, 'neu_netto': 1550, 'wirksam_ab': date(2027, 4, 1), 'gruende': ['Teuerung']}
        self._signatur(False)
        ohne = fill_mietzins_so(self.v, daten, verwaltung=self.v.organisation)
        self._signatur(True)
        mit = fill_mietzins_so(self.v, daten, verwaltung=self.v.organisation)
        self.assertGreater(sum(_bilder(mit)), sum(_bilder(ohne)))


class Fristansetzungs257dPdfTests(_MitUnterschrift):
    def test_brief_ohne_bild_mit_beschrifteter_linie(self):
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        self._signatur(False)
        ohne = generate_mahnung_combined_pdf_bytes(self.v, self.v.organisation, '10/2026', '1700.00',
                                                   date(2026, 11, 4))
        self._signatur(True)
        mit = generate_mahnung_combined_pdf_bytes(self.v, self.v.organisation, '10/2026', '1700.00',
                                                  date(2026, 11, 4))
        self.assertEqual(_bilder(mit), _bilder(ohne))
        text = PdfReader(io.BytesIO(mit)).pages[0].extract_text()
        self.assertIn('Eigenhändige Unterschrift', text)


class VersandschrittTests(_MitUnterschrift):
    """Der Hinweis «eigenhändig unterschreiben» steht dort, wo versandt wird."""

    def setUp(self):
        super().setUp()
        self.c = Client()
        self.c.force_login(_team_user())

    def _meldungen(self, antwort):
        return ' '.join(str(m) for m in get_messages(antwort.wsgi_request))

    def test_vermieterkuendigung_erfassen_nennt_die_eigenhaendige_unterschrift(self):
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', {
            'absender': 'vermieter', 'eingang_datum': date.today().isoformat()})
        self.assertEqual(antwort.status_code, 302)
        text = self._meldungen(antwort)
        self.assertIn('eigenhändig unterschreiben', text)
        self.assertIn('Art. 266l Abs. 1 OR', text)
        self.assertIn('Art. 266o OR', text)
        # Gegenprobe: bei der Kündigung durch den Mieter gibt es keinen Hinweis (die Mieterin unterschreibt selbst).
        from rentals.models import Kuendigung
        Kuendigung.objects.all().delete()
        self.v.status, self.v.ende = 'aktiv', None
        self.v.save()
        self.c = Client()                      # neue Sitzung: keine Meldungen der ersten Anfrage
        self.c.force_login(_team_user('Verwalter'))
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', {
            'absender': 'mieter', 'eingang_datum': date.today().isoformat()})
        self.assertNotIn('eigenhändig unterschreiben', self._meldungen(antwort))

    def test_formular_pdf_antwortet_mit_dem_hinweis(self):
        k = self._kuendigung()
        self._signatur(True)
        antwort = self.c.post(f'/neu/kuendigung/{k.id}/formular/', {'nachbildung': 'bestaetigt'},
                              follow=False)
        # Kanton SO hat ein Original: Die Antwort ist das PDF.
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        self.assertIn('eigenhändig unterschreiben', self._meldungen(antwort))

    def test_vertragsakte_zeigt_den_hinweis_bei_vermieterkuendigungen(self):
        k = self._kuendigung()
        antwort = self.c.get(f'/neu/vertraege/{self.v.id}/')
        self.assertContains(antwort, 'Vor dem Versand eigenhändig unterschreiben')
        # Gegenprobe: bei einer Mieterkündigung steht er nicht da.
        k.absender = 'mieter'
        k.save(update_fields=['absender'])
        self.assertNotContains(self.c.get(f'/neu/vertraege/{self.v.id}/'),
                               'Vor dem Versand eigenhändig unterschreiben')

    def test_fristansetzungsseite_und_erfolgsmeldung(self):
        from finance.models import DebitorenRechnung
        DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel='Miete & NK 10/2026',
            datum=date(2026, 10, 1), faellig_am=date(2026, 10, 1), betrag=1700, status='offen',
            forderungsart='miete')
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/verzug/')
        self.assertContains(seite, 'Eigenhändig unterschreiben.')
        antwort = self.c.post(f'/neu/vertraege/{self.v.id}/verzug/', {'frist_bis': '2027-03-01'})
        self.assertIn('eigenhändig unterschreiben', self._meldungen(antwort))
        self.assertIn('Art. 257d Abs. 1 OR', self._meldungen(antwort))

    def test_hinweise_sind_uebersetzt(self):
        from django.utils import translation

        from core.services.unterschrift import UNTERSCHRIFT_HINWEIS_257D, UNTERSCHRIFT_HINWEIS_KUENDIGUNG
        for sprache in ('fr', 'it', 'en'):
            with self.subTest(sprache=sprache), translation.override(sprache):
                for hinweis in (UNTERSCHRIFT_HINWEIS_257D, UNTERSCHRIFT_HINWEIS_KUENDIGUNG):
                    self.assertNotIn('eigenhändig', str(hinweis))
                    self.assertNotIn('Unterschriftsbild', str(hinweis))
