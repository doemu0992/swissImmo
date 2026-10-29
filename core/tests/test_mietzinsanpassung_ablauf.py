"""Mietzinsanpassung bis zur Produktionsreife (Audit 26.10.2026, Befunde A–D, G–J, N).

Jede Klasse nennt den Befund, den sie festhält. Gegenproben sind im Bericht
zur Etappe protokolliert: Code zurückgebaut → rot, wiederhergestellt → grün.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone
from pypdf import PdfReader

from ._helfer import _basis_objekte, _team_user, _test_organisation

D = Decimal


def _vertrag(kanton='ZH', **felder):
    _test_organisation(aktueller_referenzzinssatz=D('1.75'), aktueller_lik_punkte=D('100'))
    lg, e, m, v = _basis_objekte()      # netto 1500, NK 200, Beginn 01.01.2024
    if kanton is not None:
        lg.kanton = kanton
        lg.save()
    v.basis_referenzzinssatz = D('1.50')
    v.basis_lik_punkte = D('100')
    for k, w in felder.items():
        setattr(v, k, w)
    v.save()
    return lg, e, v


def _anpassung(v, status='wirksam', wirksam_ab=date(2025, 1, 1), neu='1545.00', **felder):
    from rentals.models import MietzinsAnpassung
    werte = dict(vertrag=v, wirksam_ab=wirksam_ab, neuer_netto_mietzins=D(neu),
                 alter_netto_mietzins=D('1500.00'), alter_referenzzinssatz=D('1.50'),
                 neuer_referenzzinssatz=D('1.75'), alter_lik_index=D('100'),
                 neuer_lik_index=D('100'), status=status)
    werte.update(felder)
    return MietzinsAnpassung.objects.create(**werte)


def _text(pdf):
    return ' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages)


class VorrangVorZeitplanTests(TestCase):
    """Befund B: Ein Gratismonat-Zeitplan oder eine Komponente sperrte die Anpassung."""

    def test_sollmietzins_zeitplan_ueberdeckt_anpassung_nicht(self):
        from portfolio.models import Sollmietzins
        _lg, e, v = _vertrag()
        for ab, rabatt in ((date(2024, 1, 1), D('0')), (date(2024, 2, 1), D('1500')),
                           (date(2024, 3, 1), D('0'))):
            Sollmietzins.objects.create(einheit=e, gueltig_ab=ab, netto_mietzins=D('1500'),
                                        nebenkosten=D('200'), rabatt_netto=rabatt)
        _anpassung(v)
        v = type(v).objects.get(pk=v.pk)
        self.assertEqual(v.verrechneter_netto_mietzins(date(2025, 6, 1)), D('1545.00'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), D('1545.00'))
        # Vor dem Wirksamwerden gilt der Zeitplan weiter, samt Gratismonat.
        self.assertEqual(v.verrechneter_netto_mietzins(date(2024, 2, 15)), D('0.00'))

    def test_juengere_komponente_geht_der_anpassung_vor(self):
        from rentals.models import VertragMietzins
        _lg, _e, v = _vertrag()
        _anpassung(v)
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2025, 7, 1),
                                       netto_mietzins=D('1545'), nebenkosten=D('200'),
                                       rabatt_netto=D('1545'))
        v = type(v).objects.get(pk=v.pk)
        self.assertEqual(v.verrechneter_netto_mietzins(date(2025, 6, 1)), D('1545.00'))
        self.assertEqual(v.verrechneter_netto_mietzins(date(2025, 7, 15)), D('0.00'))


class EntwurfBuchtNichtsTests(TestCase):
    """Befund C: Ein Entwurf zählt nirgends; erst der Versand bucht."""

    def test_entwurf_wirkt_nicht(self):
        from portfolio.models import Sollmietzins
        _lg, e, v = _vertrag()
        anp = _anpassung(v, status='entwurf')
        v = type(v).objects.get(pk=v.pk)
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 6, 1)), D('1500.00'))
        self.assertEqual(v.effektive_basis(date(2025, 6, 1))[0], D('1.50'))
        self.assertFalse(Sollmietzins.objects.filter(quelle_anpassung=anp).exists())

    def test_versand_bucht_und_setzt_frist_ab_zugang(self):
        from core.models import Pendenz
        from core.services import mietzinsanpassung as ablauf
        from portfolio.models import Sollmietzins
        from rentals.services import naechster_anpassungstermin
        _lg, e, v = _vertrag()
        heute = timezone.localdate()
        anp = _anpassung(v, status='entwurf', wirksam_ab=naechster_anpassungstermin(v, heute))
        ablauf.versand_erfassen(anp, heute)
        self.assertTrue(Sollmietzins.objects.filter(quelle_anpassung=anp).exists())
        p = Pendenz.objects.get(vertrag=v, quelle=f'270b:{anp.pk}')
        # Zugang nicht bestätigt → Versand + Zustellpuffer (7) + 30 Tage.
        self.assertEqual(p.faellig_am, heute + timedelta(days=37))
        ablauf.zugang_nachtragen(anp, heute)
        p.refresh_from_db()
        self.assertEqual(p.faellig_am, heute + timedelta(days=30))
        self.assertEqual(Pendenz.objects.filter(vertrag=v, quelle=f'270b:{anp.pk}').count(), 1)

    def test_versand_prueft_269d_mit_dem_zugang(self):
        from core.services import mietzinsanpassung as ablauf
        from rentals.services import naechster_anpassungstermin
        _lg, _e, v = _vertrag()
        heute = timezone.localdate()
        anp = _anpassung(v, status='entwurf', wirksam_ab=naechster_anpassungstermin(v, heute))
        # Versand heute, Zugang vermutet: genau der früheste Termin — zulässig.
        self.assertEqual(ablauf.fristfehler(anp, heute), '')
        # Kommt der bestätigte Zugang zwei Monate später, ist derselbe Termin zu früh.
        self.assertTrue(ablauf.fristfehler(anp, heute, zugang_am=heute + timedelta(days=60)))
        # Ein Termin, der nur bei einem Versand vor vier Monaten gereicht hätte, wird abgewiesen.
        frueher = naechster_anpassungstermin(v, heute - timedelta(days=120))
        self.assertLess(frueher, anp.wirksam_ab)
        zu_frueh = _anpassung(v, status='entwurf', wirksam_ab=frueher, neu='1546.00')
        with self.assertRaises(ValueError):
            ablauf.versand_erfassen(zu_frueh, heute)
        zu_frueh.refresh_from_db()
        self.assertEqual(zu_frueh.status, 'entwurf')

    def test_vorschau_bucht_nicht_und_entwurf_wird_fortgeschrieben(self):
        from rentals.models import MietzinsAnpassung
        from rentals.services import naechster_anpassungstermin
        _lg, _e, v = _vertrag()
        w = naechster_anpassungstermin(v, timezone.localdate())
        c = Client(); c.force_login(_team_user())
        for neu in ('1540', '1550'):
            r = c.post(f'/neu/mietzins/{v.id}/anpassung/', {
                'aktion': 'pdf', 'neu_netto': neu, 'neu_zins': '1.75', 'neu_lik': '100',
                'wirksam_ab': w.isoformat()})
            self.assertEqual(r['Content-Type'], 'application/pdf')
        anp = MietzinsAnpassung.objects.get(vertrag=v)
        self.assertEqual((anp.status, anp.neuer_netto_mietzins), ('entwurf', D('1550')))
        # Bisheriger Mietzins im Entwurf ist der EFFEKTIVE (Befund A).
        self.assertEqual(anp.alter_netto_mietzins, D('1500.00'))

    def test_statuswechsel(self):
        from core.models import Pendenz
        from core.services import mietzinsanpassung as ablauf
        from rentals.services import naechster_anpassungstermin
        _lg, _e, v = _vertrag()
        heute = timezone.localdate()
        anp = _anpassung(v, status='entwurf', wirksam_ab=naechster_anpassungstermin(v, heute))
        with self.assertRaises(ValueError):
            ablauf.status_setzen(anp, 'wirksam')            # Entwurf → wirksam: nein
        ablauf.versand_erfassen(anp, heute)
        ablauf.status_setzen(anp, 'angefochten')
        self.assertTrue(Pendenz.objects.filter(vertrag=v, quelle=f'270b-verfahren:{anp.pk}').exists())
        ablauf.status_setzen(anp, 'wirksam')
        self.assertFalse(Pendenz.objects.filter(vertrag=v, quelle__startswith='270b', erledigt=False).exists())


class BasisFortschreibenTests(TestCase):
    """Befund I: Kosten ausgeglichen bis, letzte Indexanpassung, Vorbehalt."""

    def test_versand_schreibt_vertragsbasis_fort(self):
        from core.services import mietzinsanpassung as ablauf
        from rentals.services import naechster_anpassungstermin
        _lg, _e, v = _vertrag()
        heute = timezone.localdate()
        anp = _anpassung(v, status='entwurf', wirksam_ab=naechster_anpassungstermin(v, heute),
                         kosten_prozent=D('1.00'), kosten_ausgeglichen_bis=heute,
                         vorbehalt_betrag=D('40.00'))
        ablauf.versand_erfassen(anp, heute)
        v.refresh_from_db()
        self.assertEqual(v.kostensteigerung_datum, heute)
        self.assertEqual(v.mietzinsreserve_betrag, D('40.00'))

    def test_indexmiete_setzt_letzte_indexanpassung(self):
        from core.services import mietzinsanpassung as ablauf
        from rentals.services import naechster_anpassungstermin
        _lg, _e, v = _vertrag(mietzins_modell='index', ist_befristet=True, ende=date(2032, 12, 31))
        heute = timezone.localdate()
        w = naechster_anpassungstermin(v, heute)
        ablauf.versand_erfassen(_anpassung(v, status='entwurf', wirksam_ab=w), heute)
        v.refresh_from_db()
        self.assertEqual(v.index_letzte_anpassung, w)

    def test_ohne_kostenanteil_bleibt_das_datum(self):
        from core.services import mietzinsanpassung as ablauf
        from rentals.services import naechster_anpassungstermin
        _lg, _e, v = _vertrag(kostensteigerung_datum=date(2024, 6, 1))
        heute = timezone.localdate()
        ablauf.versand_erfassen(_anpassung(v, status='entwurf', kosten_prozent=D('0'),
                                           wirksam_ab=naechster_anpassungstermin(v, heute)), heute)
        v.refresh_from_db()
        self.assertEqual(v.kostensteigerung_datum, date(2024, 6, 1))


class MassenlaufTests(TestCase):
    """Befund D: Index- und Staffelmieten gehören nicht in den Referenzzins-Lauf."""

    def test_index_und_staffel_ausgenommen(self):
        from rentals.models import MietzinsAnpassung
        _lg, _e, v = _vertrag(mietzins_modell='index')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/mietzins/massenanpassung/', {'aktion': 'ausfuehren', 'vertrag_id': [str(v.id)]})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(MietzinsAnpassung.objects.filter(vertrag=v).exists())

    def test_liste_bietet_index_nicht_zur_auswahl(self):
        _lg, _e, v = _vertrag(mietzins_modell='staffel')
        c = Client(); c.force_login(_team_user())
        body = c.get('/neu/mietzins/').content.decode()
        self.assertNotIn(f'name="vertrag_id" value="{v.id}"', body)
        self.assertIn('Staffelmiete', body)


class PlzKantonTests(SimpleTestCase):
    """Befund G: Überlappende PLZ-Bereiche ergeben KEINEN Kanton statt des ersten."""

    def test_mehrdeutige_plz_ergibt_none(self):
        from core.services.kantone import plz_to_kanton
        for plz in ('1201', '8200', '3920', '8750', '6460', '6370', '6050', '9050'):
            self.assertIsNone(plz_to_kanton(plz), plz)

    def test_eindeutige_plz_bleibt(self):
        from core.services.kantone import plz_kantone, plz_to_kanton
        self.assertEqual(plz_to_kanton('8004'), 'ZH')
        self.assertEqual(plz_to_kanton('3011'), 'BE')
        self.assertEqual(plz_kantone('1201'), ['GE', 'VD'])

    def test_formular_kanton_nur_aus_dem_feld(self):
        from types import SimpleNamespace
        from core.services.kantone import formular_kanton
        self.assertIsNone(formular_kanton(SimpleNamespace(kanton='', plz='8004')))
        self.assertEqual(formular_kanton(SimpleNamespace(kanton='zh', plz='')), 'ZH')


class FormularOhneOriginalTests(TestCase):
    """Befund J: Ohne Kantonsoriginal nur nach Bestätigung, mit Wasserzeichen, nicht in der Akte."""

    def _post(self, c, v, **extra):
        from rentals.services import naechster_anpassungstermin
        daten = {'aktion': 'pdf', 'neu_netto': '1545', 'neu_zins': '1.75', 'neu_lik': '100',
                 'wirksam_ab': naechster_anpassungstermin(v, timezone.localdate()).isoformat()}
        daten.update(extra)
        return c.post(f'/neu/mietzins/{v.id}/anpassung/', daten)

    def test_ohne_kanton_kein_formular(self):
        _lg, _e, v = _vertrag(kanton=None)
        c = Client(); c.force_login(_team_user())
        r = self._post(c, v)
        self.assertEqual(r.status_code, 302)

    def test_nachbildung_nur_mit_bestaetigung_und_wasserzeichen(self):
        _lg, _e, v = _vertrag(kanton='GE')
        c = Client(); c.force_login(_team_user())
        r = self._post(c, v)
        self.assertEqual(r.status_code, 302)                      # gesperrt ohne Bestätigung
        r = self._post(c, v, nachbildung_bestaetigt='on')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('Entwurf', _text(r.content))
        self.assertIn('nicht amtlich', _text(r.content))

    def test_seite_warnt_vor_nichtigkeit(self):
        _lg, _e, v = _vertrag(kanton='GE')
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/mietzins/{v.id}/anpassung/').content.decode()
        self.assertIn('Für Kanton Genf ist kein amtliches Originalformular hinterlegt', body)
        self.assertIn('nichtig (Art. 269d OR)', body)

    def test_kuendigungsformular_zwischenseite_und_keine_ablage(self):
        from rentals.models import Dokument, Kuendigung
        _lg, _e, v = _vertrag(kanton='GE')
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2027, 3, 31))
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/kuendigung/{k.id}/formular/')
        self.assertContains(r, 'nichtig (Art. 266l/266o OR)')
        r = c.get(f'/neu/kuendigung/{k.id}/formular/?nachbildung=bestaetigt')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('nicht amtlich', _text(r.content))
        self.assertFalse(Dokument.objects.filter(vertrag=v, bezeichnung__startswith='Kündigung').exists())

    def test_kein_automatisches_anfangsmietzins_ohne_original(self):
        from core.views.fw import anfangsmietzins_auto_ablegen
        _lg, _e, v = _vertrag(kanton='GE')               # Formularpflicht ja, kein Original
        erzeugt, grund = anfangsmietzins_auto_ablegen(v)
        self.assertEqual((erzeugt, grund), (False, 'kein_original'))


class HerabsetzungsPendenzTests(TestCase):
    """Befund H: Die Senkungs-Pendenz vergleicht mit der effektiven Basis."""

    def test_weitergegebene_senkung_meldet_nichts_mehr(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        org = _test_organisation(aktueller_referenzzinssatz=D('1.25'))
        _lg, _e, v = _vertrag()
        org.aktueller_referenzzinssatz = D('1.25')
        org.save(update_fields=['aktueller_referenzzinssatz'])
        v.basis_referenzzinssatz = D('1.75')
        v.save()
        _anpassung(v, wirksam_ab=date(2025, 1, 1), neu='1418.80', neuer_referenzzinssatz=D('1.25'))
        generate_auto_pendenzen(organisation=org)
        self.assertFalse(Pendenz.objects.filter(vertrag=v, quelle__startswith='auto:refsenkung').exists())

    def test_nicht_weitergegebene_senkung_meldet(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        org = _test_organisation()
        _lg, _e, v = _vertrag()
        org.aktueller_referenzzinssatz = D('1.25')
        org.save(update_fields=['aktueller_referenzzinssatz'])
        generate_auto_pendenzen(organisation=org)
        self.assertTrue(Pendenz.objects.filter(vertrag=v, quelle__startswith='auto:refsenkung').exists())


class GesetzesregisterTests(SimpleTestCase):
    """Befund N: Kostensteigerungen stehen in Art. 12 VMWG, die Teuerung in Art. 16."""

    def test_kostensteigerung_ist_art_12(self):
        from core.services.gesetzestexte import REGISTER
        eintraege = {(g, a): t for g, a, t, _k, _s in REGISTER}
        self.assertEqual(eintraege[('VMWG', '12')], 'Kostensteigerungen')
        self.assertNotEqual(eintraege.get(('VMWG', '16')), 'Kostensteigerungen')


class SammelversandIsolationTests(TestCase):
    """Der Sammelversand nimmt IDs aus dem Formular — fremde dürfen nichts bewirken."""

    def test_fremder_entwurf_bleibt_unberuehrt(self):
        from rentals.models import MietzinsAnpassung
        from ._isolation import MandantenFixture
        from core.tenancy import organisation_kontext
        a = MandantenFixture('A', '8000', 'Zürich')
        b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(b.organisation):
            # Kanton mit Original: Sonst bliebe der Entwurf schon am fehlenden
            # Kanton hängen, und der Test wäre auch ohne Mandantengrenze grün.
            b.liegenschaft.kanton = 'BE'
            b.liegenschaft.save()
            fremd = MietzinsAnpassung.objects.create(
                vertrag=b.vertrag, wirksam_ab=date(2030, 4, 1), neuer_netto_mietzins=D('1600'),
                status='entwurf')
        c = Client(); c.force_login(a.benutzer)
        c.post('/neu/mietzins/versand/', {'anpassung': [str(fremd.pk)],
                                          'versand_am': timezone.localdate().isoformat()})
        fremd = MietzinsAnpassung.alle_organisationen.get(pk=fremd.pk)
        self.assertEqual(fremd.status, 'entwurf')

    def test_fremder_status_wechsel_404(self):
        from rentals.models import MietzinsAnpassung
        from ._isolation import MandantenFixture
        from core.tenancy import organisation_kontext
        a = MandantenFixture('A', '8000', 'Zürich')
        b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(b.organisation):
            fremd = MietzinsAnpassung.objects.create(
                vertrag=b.vertrag, wirksam_ab=date(2030, 4, 1), neuer_netto_mietzins=D('1600'),
                status='versandt')
        c = Client(); c.force_login(a.benutzer)
        r = c.post(f'/neu/anpassung/{fremd.pk}/status/', {'aktion': 'wirksam'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(MietzinsAnpassung.alle_organisationen.get(pk=fremd.pk).status, 'versandt')


class EntwurfInListeTests(TestCase):
    """Befund C, auch ausserhalb des Assistenten: Ein Entwurf ist keine Anpassung,
    die gegolten hat — nicht als «letzte Anpassung» der Mietzinsliste. (Das
    Vertragsdossier, das dasselbe für die Aussenansicht zeigte, ist in Etappe 3
    entfallen; die Akte führt Entwürfe bewusst mit Status auf.)"""

    def test_liste_zeigt_entwurf_nicht_als_letzte_anpassung(self):
        _lg, _e, v = _vertrag()
        _anpassung(v, status='entwurf', wirksam_ab=date(2031, 4, 1))
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/mietzins/')
        zeile = next(z for z in r.context['rows'] if z['v'].pk == v.pk)
        self.assertIsNone(zeile['letzte_anpassung'])
        self.assertEqual(zeile['anpassungen'], 0)
        _anpassung(v, status='versandt', wirksam_ab=date(2025, 1, 1))
        r = c.get('/neu/mietzins/')
        zeile = next(z for z in r.context['rows'] if z['v'].pk == v.pk)
        self.assertEqual(zeile['letzte_anpassung'], date(2025, 1, 1))


class RechnenIsolationTests(TestCase):
    """Die Live-Neuberechnung liefert Mietzins und Basis eines Vertrags als JSON —
    für einen fremden Vertrag 404, nicht dessen Zahlen."""

    def test_fremder_vertrag_404(self):
        from ._isolation import MandantenFixture
        a = MandantenFixture('A', '8000', 'Zürich')
        b = MandantenFixture('B', '3000', 'Bern')
        c = Client(); c.force_login(a.benutzer)
        eigen = c.get(f'/neu/mietzins/{a.vertrag.pk}/anpassung/rechnen/', {'neu_zins': '1.75'})
        self.assertEqual(eigen.status_code, 200)
        self.assertIn('alt_netto', eigen.json())
        fremd = c.get(f'/neu/mietzins/{b.vertrag.pk}/anpassung/rechnen/', {'neu_zins': '1.75'})
        self.assertEqual(fremd.status_code, 404)
