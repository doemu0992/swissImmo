"""Die Vermieter-Unterschrift auf dem Mietvertrag (27.10.2026).

Bis dahin las `build_vertrag_context` das Feld `verwaltung.unterschrift`, das
es nicht gibt: Die Unterschrift der Verwaltung erschien nie. Ohne
Eigentümer-Unterschrift kam stattdessen ein Muster-Gekritzel
(`unterschrift_dummy`) auf den Vertrag — es sah aus wie eine echte
Unterschrift. Geprüft wird:

- Die Verwaltung unterschreibt zuerst, sonst der Eigentümer.
- Ohne Bild bleibt die Linie leer: kein Ersatzbild.
- PDF, Vorschau und DocuSeal nehmen dieselbe Quelle.
"""
import io
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture

MEDIA = tempfile.mkdtemp(prefix='unterschrift-')


def _png():
    puffer = io.BytesIO()
    Image.new('RGB', (40, 12), (20, 20, 20)).save(puffer, format='PNG')
    return ContentFile(puffer.getvalue(), name='sig.png')


@override_settings(MEDIA_ROOT=MEDIA)
class VermieterUnterschriftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def kontext(self):
        from core.services.pdf_service import build_vertrag_context
        with mandant(self.a.organisation):
            from rentals.models import Mietvertrag
            v = Mietvertrag.objects.get(pk=self.a.vertrag.pk)
            return build_vertrag_context(v)[1]

    def unterschreibt(self, wer):
        wer.unterschrift_bild.save('sig.png', _png(), save=False)
        with mandant(self.a.organisation):
            wer.save()
        wer.refresh_from_db()

    def test_ohne_unterschrift_bleibt_die_linie_leer(self):
        self.assertIsNone(self.kontext()['unterschrift_path'])

    def test_verwaltung_unterschreibt(self):
        self.unterschreibt(self.a.organisation)
        pfad = self.kontext()['unterschrift_path']
        self.assertIsNotNone(pfad)
        self.assertIn('unterschriften', pfad)
        self.assertNotIn('dummy', pfad)

    def test_eigentuemer_wenn_die_verwaltung_keine_hat(self):
        self.unterschreibt(self.a.eigentuemer)
        pfad = self.kontext()['unterschrift_path']
        self.assertIsNotNone(pfad)
        self.assertIn('sig_man_', pfad)

    def test_verwaltung_vor_eigentuemer(self):
        self.unterschreibt(self.a.eigentuemer)
        self.unterschreibt(self.a.organisation)
        self.assertIn('sig_vw_', self.kontext()['unterschrift_path'])

    def test_ohne_unterschrift_kein_bild_im_pdf(self):
        from django.template.loader import get_template
        html = get_template('core/mietvertrag_pdf.html').render(self.kontext())
        self.assertNotIn('class="sigimg"', html)

    def test_eine_quelle_fuer_pdf_und_docuseal(self):
        """DocuSeal und die alte Ansicht holen das Bild über denselben Helfer."""
        import inspect

        from core.services import docuseal_service
        from core.views import docuseal
        for modul in (docuseal_service, docuseal):
            quelle = inspect.getsource(modul)
            with self.subTest(modul=modul.__name__):
                self.assertIn('vermieter_unterschrift_pfad', quelle)
                self.assertNotIn('unterschrift_dummy', quelle)
