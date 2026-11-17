"""Der unterzeichnete Vertrag landet auch dann in der Akte, wenn der Webhook ohne Mandantenkontext speichert.

Audit 17.11.2026 (K1): `Mietvertrag.save()` legt das signierte PDF über `ablage_signierter_vertrag` ab. Der DocuSeal-
Webhook ruft `save()` ohne Anmeldung auf, also ohne Verwaltung im Kontext; `Dokument.objects` warf einen
`OrganisationsFehler`, den `save()` still verschluckte. Der Webhook meldete «archiviert», die Akte blieb leer.
"""
from django.core.files.base import ContentFile
from django.test import TestCase

from core.tenancy import aktuelle_organisation, loesche_organisation, setze_organisation

from ._helfer import _basis_objekte

PDF = b'%PDF-1.4\n% unterzeichnet\n%%EOF'


class UnterzeichnetOhneKontextTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.org = aktuelle_organisation()

    def _ohne_kontext(self, fn):
        """Führt `fn` ohne Mandantenkontext aus (wie ein Webhook) und stellt ihn danach wieder her."""
        loesche_organisation()
        try:
            return fn()
        finally:
            setze_organisation(self.org)

    def _signierte(self):
        from rentals.models import Dokument
        return Dokument.alle_organisationen.filter(vertrag=self.v, kategorie='vertrag')

    def test_signiertes_pdf_wird_ohne_kontext_abgelegt(self):
        def speichern():
            from rentals.models import Mietvertrag
            v = Mietvertrag.alle_organisationen.get(pk=self.v.pk)
            v.pdf_datei.save('Unterschrieben.pdf', ContentFile(PDF), save=False)
            v.sign_status = 'unterzeichnet'
            v.save()
        self._ohne_kontext(speichern)
        dok = self._signierte()
        self.assertEqual(dok.count(), 1, 'Der signierte Vertrag steht nicht in der Akte')
        self.assertEqual(dok.first().organisation_id, self.org.pk, 'Das Dokument gehört einer fremden Verwaltung')

    def test_gegenprobe_ohne_unterschrift_wird_nichts_abgelegt(self):
        def speichern():
            from rentals.models import Mietvertrag
            v = Mietvertrag.alle_organisationen.get(pk=self.v.pk)
            v.pdf_datei.save('Entwurf.pdf', ContentFile(PDF), save=False)
            v.save()
        self._ohne_kontext(speichern)
        self.assertEqual(self._signierte().count(), 0)
