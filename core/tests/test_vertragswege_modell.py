"""Weitere Wege zum aktiven Vertrag prüfen das Mietzinsmodell hart (28.10.2026).

Der Assistent und «Entwurf aktivieren» prüften schon. Offen waren drei Umwege:

* **Archiviert -> aktiv** in `fw_vertrag_status`: Ein Entwurf liess sich über «Inaktiv» archivieren und
  von dort ohne Prüfung aktivieren.
* **DocuSeal-Rücklauf** (`rentals.services.verarbeite_docuseal_event`): Die Unterschrift setzte einen
  Entwurf ohne Prüfung auf «aktiv».
* **Versand zur Unterschrift** (`docuseal_senden`): Ein Entwurf mit unzulässigem Modell ging hinaus.

Jeder Test hat seine Gegenprobe im selben Test: derselbe Weg mit zulässigem Modell (oder festem Mietzins)
läuft durch. Wege, die immer `fest` anlegen (Bewerbung -> Vertrag), sind unten mit einem Test belegt.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase, override_settings

from core.models import Pendenz
from rentals.models import Mietvertrag

from ._helfer import Einheit, Liegenschaft, Mieter, _team_user, _test_organisation


class Basis(TestCase):
    def setUp(self):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Wegeweg 1', plz='8000',
                                         ort='Zürich', versicherungswert=Decimal('1000000'))
        self.e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg',
                                        nettomiete_aktuell=Decimal('2000'))
        self.m = Mieter.objects.create(typ='person', vorname='Wega', nachname='Weg', email='wega@example.ch')
        self.c = Client()
        self.c.force_login(_team_user(rolle='Verwaltung'))

    def vertrag(self, gueltig=False, **felder):
        """Ein Indexvertrag; `gueltig=False`: ein Tag zu kurz (Ende 30.12.2029 bei Beginn 1.1.2025)."""
        daten = dict(mieter=self.m, einheit=self.e, beginn=date(2025, 1, 1), netto_mietzins=Decimal('2000'),
                     nebenkosten=Decimal('200'), status='entwurf', mietzins_modell='index', ist_befristet=True,
                     ende=date(2029, 12, 31) if gueltig else date(2029, 12, 30),
                     basis_lik_punkte=Decimal('106.9'), basis_lik_stand=date(2024, 12, 1))
        daten.update(felder)
        return Mietvertrag.objects.create(**daten)


class ArchiviertZuAktivTests(Basis):
    def aktivieren(self, v):
        return self.c.post(f'/neu/vertraege/{v.id}/status/', {'status': 'aktiv'}, follow=True)

    def test_archivierter_entwurf_mit_sperre_wird_nicht_aktiv(self):
        v = self.vertrag(status='archiviert')
        r = self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')
        text = ' '.join(str(m) for m in r.context['messages'])
        self.assertIn('Art. 269b OR', text)
        self.assertIn('bleibt archiviert', text)
        # Gegenprobe: ein Tag mehr, und derselbe Weg aktiviert.
        v.ende = date(2029, 12, 31)
        v.save()
        self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_der_umweg_ueber_inaktiv_ist_zu(self):
        """Entwurf -> archiviert -> aktiv: dieselbe Sperre wie Entwurf -> aktiv."""
        v = self.vertrag()
        self.c.post(f'/neu/vertraege/{v.id}/status/', {'status': 'archiviert'})
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')
        self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')

    def test_archivierter_fester_vertrag_und_gekuendigter_altvertrag_bleiben_unberuehrt(self):
        fest = self.vertrag(status='archiviert', mietzins_modell='fest', ende=None, ist_befristet=False)
        self.aktivieren(fest)
        fest.refresh_from_db()
        self.assertEqual(fest.status, 'aktiv')
        # Ein gekündigter Vertrag war aktiv: nicht neu geprüft, auch mit altem Verstoss.
        alt = self.vertrag(status='gekuendigt')
        self.aktivieren(alt)
        alt.refresh_from_db()
        self.assertEqual(alt.status, 'aktiv')


class DocuSealRuecklaufTests(Basis):
    def ereignis(self, v):
        from rentals.services import verarbeite_docuseal_event
        antwort = MagicMock(status_code=200, content=b'%PDF-signed')
        payload = {'event_type': 'submission.completed',
                   'data': {'name': f'Mietvertrag {v.id}', 'combined_document_url': 'https://api.docuseal.com/y.pdf'}}
        with patch('rentals.services.requests.get', return_value=antwort):
            return verarbeite_docuseal_event(payload)

    def test_unterzeichneter_entwurf_mit_sperre_bleibt_entwurf_und_hinterlaesst_eine_pendenz(self):
        v = self.vertrag()
        self.assertTrue(self.ereignis(v))
        v.refresh_from_db()
        self.assertEqual(v.sign_status, 'unterzeichnet', 'Die Unterschrift ist eine Tatsache und bleibt erfasst.')
        self.assertEqual(v.status, 'entwurf')
        p = Pendenz.objects.get(quelle=f'auto:modellsperre:{v.pk}')
        self.assertIn('Art. 269b OR', p.beschreibung)
        self.assertEqual(p.vertrag_id, v.pk)
        # Zweites Ereignis legt keine zweite Pendenz an.
        self.ereignis(v)
        self.assertEqual(Pendenz.objects.filter(quelle=f'auto:modellsperre:{v.pk}').count(), 1)

    def test_gueltiges_modell_wird_aktiv_ohne_pendenz(self):
        """Gegenprobe zum vorigen Test."""
        v = self.vertrag(gueltig=True)
        self.assertTrue(self.ereignis(v))
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='auto:modellsperre:').exists())

    def test_fester_mietzins_wird_aktiv(self):
        v = self.vertrag(mietzins_modell='fest', ende=None, ist_befristet=False)
        self.ereignis(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_ohne_mandantenkontext(self):
        """Der Webhook läuft ohne Anmeldung: Auch die Staffelstufen müssen lesbar sein."""
        from core.tenancy import ohne_organisation
        v = self.vertrag(mietzins_modell='staffel', ende=date(2027, 12, 31))   # Staffel ohne Stufe: Sperre
        with ohne_organisation():
            self.assertTrue(self.ereignis(v))
        v.refresh_from_db()
        self.assertEqual(v.status, 'entwurf')


@override_settings(DOCUSEAL_API_KEY='test')
class VersandTests(Basis):
    def senden(self, v):
        from core.services.docuseal_service import docuseal_senden
        antwort = MagicMock(status_code=201)
        with patch('requests.post', return_value=antwort) as post, \
                patch('xhtml2pdf.pisa.CreatePDF', return_value=MagicMock(err=0)):
            ergebnis = docuseal_senden(v)
        return ergebnis, post

    def test_entwurf_mit_sperre_geht_nicht_zur_unterschrift(self):
        v = self.vertrag()
        (ok, meldung), post = self.senden(v)
        self.assertFalse(ok)
        self.assertIn('Mietzinsmodell', meldung)
        self.assertIn('Art. 269b OR', meldung)
        post.assert_not_called()
        # Gegenprobe: gültiges Modell geht hinaus.
        v.ende = date(2029, 12, 31)
        v.save()
        (ok, meldung), post = self.senden(v)
        self.assertTrue(ok, meldung)
        post.assert_called_once()

    def test_aktiver_altvertrag_wird_nicht_geprueft(self):
        v = self.vertrag(status='aktiv')
        (ok, meldung), post = self.senden(v)
        self.assertTrue(ok, meldung)


class BewerbungZuVertragTests(Basis):
    def test_der_weg_legt_immer_einen_festen_entwurf_an(self):
        """Belegt, dass dieser Weg kein Index-/Staffelmodell erzeugen kann (nur notiert, nicht geschützt):
        Er setzt kein Mietzinsmodell, der Vorgabewert des Feldes ist 'fest'. Wird das je anders, wird der Test rot."""
        from mietprozess.models import Mietbewerbung
        b = Mietbewerbung.objects.create(
            einheit=self.e, vorname='Bea', nachname='Bewerb', geburtsdatum=date(1990, 1, 1),
            mobilnummer='079 000 00 00', email='bea@example.ch', beruf='Kauffrau', einkommen_jahr="90'000",
            status='zugesagt')
        r = self.c.post(f'/neu/bewerbungen/{b.id}/vertrag/')
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertIsNotNone(b.vertrag_id)
        self.assertEqual(b.vertrag.mietzins_modell, 'fest')
        self.assertEqual(b.vertrag.status, 'entwurf')
        self.assertEqual(Mietvertrag._meta.get_field('mietzins_modell').default, 'fest')
