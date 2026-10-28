"""Wohnungsabnahme produktionsreif (Audit 26.10.2026): die zwölf Befunde.

Je Befund eine Klasse, benannt nach dem, was sie sichert. Gegenproben stehen
am Test, wo der Fehler sich nicht von selbst erklärt.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _team_user, abschluss_daten, png_data_url
from ._isolation import MandantenFixture
from ._uhr import bei_stichtag
from .test_abnahme_kette import _protokoll


def _jpeg(farbe='red'):
    from PIL import Image
    buf = io.BytesIO(); Image.new('RGB', (40, 30), farbe).save(buf, 'JPEG')
    return buf.getvalue()


def _pdf(prot):
    import pdfplumber
    from core.services.abnahme_pdf import generate_abnahme_pdf
    with pdfplumber.open(io.BytesIO(generate_abnahme_pdf(prot))) as d:
        return [(s.extract_text() or '', len(s.images)) for s in d.pages]


# Die Tests rechnen mit absoluten Daten (Abnahme 01.10.2026, Rüge fällig 27.10.2026): Die Uhr steht
# auf dem Tag, für den sie geschrieben wurden — sonst sind sie nur an diesem Tag richtig (SICH-45).
@bei_stichtag(date(2026, 10, 28))
class Basis(TestCase):
    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v = _basis_objekte()
        self.c = Client(); self.c.force_login(_team_user())

    def _vorort(self, typ='auszug', raeume=('Keller',), datum=None):
        from rentals.models import Abnahmeprotokoll
        daten = {'typ': typ, 'raum': list(raeume)}
        if datum:
            daten['datum'] = datum.isoformat()
        self.c.post(f'/neu/vertraege/{self.v.id}/abnahme/vorort/', daten)
        return Abnahmeprotokoll.objects.filter(vertrag=self.v).latest('id')

    def _setze(self, prot, pos, **d):
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/position/', {'position': pos.id, **d})

    def _abschliessen(self, prot, follow=False, **daten):
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', daten, follow=follow)

    def _alle_io(self, prot):
        for pos in prot.positionen.all():
            self._setze(prot, pos, zustand='io')


# --- 1. Mieterschaden ohne Lebensdauer -------------------------------------

class OhneLebensdauerTests(Basis):

    def _schaden_ohne_element(self):
        prot = self._vorort()
        self._alle_io(prot)
        pos = prot.positionen.get(bezeichnung='Boden')
        r = self._setze(prot, pos, zustand='uebermaessig', kosten='300')
        return prot, pos, r

    def test_vor_ort_zeigt_grundlage_und_anteil(self):
        prot, pos, r = self._schaden_ohne_element()
        self.assertEqual((r.json()['grundlage'], r.json()['mieteranteil']), ('ohne_lebensdauer', '300.00'))
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=0')
        # Gegenprobe: das Attribut aus abnahme_vorort.html entfernen → rot.
        self.assertContains(seite, 'data-grundlage="ohne_lebensdauer"')
        self.assertContains(seite, 'data-betrag="300.00"')
        self.assertContains(seite, 'Voller Betrag: Alter/Lebensdauer fehlt')     # Text für das Skript

    def test_abschluss_listet_und_verlangt_bestaetigung(self):
        prot, pos, _ = self._schaden_ohne_element()
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1')
        self.assertContains(seite, 'name="ohne_lebensdauer_ok"')
        self.assertContains(seite, 'Boden')
        r = self._abschliessen(prot, follow=True, **abschluss_daten(ohne_lebensdauer_ok=''))
        self.assertContains(r, 'ohne Alter oder Lebensdauer')
        prot.refresh_from_db()
        self.assertFalse(prot.abgeschlossen)
        self._abschliessen(prot, **abschluss_daten())
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)

    def test_mit_lebensdauer_keine_bestaetigung_noetig(self):
        from portfolio.models import Ausstattung
        el = Ausstattung.objects.create(einheit=self.einheit, raum='Keller', kategorie='Boden',
                                        einbau_datum=date(2020, 1, 1), lebensdauer_jahre=10,
                                        neuwert=Decimal('1000'))
        prot = self._vorort()
        self._alle_io(prot)
        pos = prot.positionen.get(ausstattung=el)
        self.assertEqual(self._setze(prot, pos, zustand='uebermaessig', kosten='300').json()['grundlage'], 'zeitwert')
        self._abschliessen(prot, **abschluss_daten(ohne_lebensdauer_ok=''))
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)


# --- 2. Unterschriften, Anwesenheit, Unbewertetes --------------------------

class UnterschriftRegelnTests(Basis):

    def test_nichts_vorbelegt(self):
        prot = self._vorort()
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1').content.decode()
        self.assertNotIn(f'value="{self.mieter.display_name}"', seite)
        self.assertIn('name="mieter_anwesend" value="ja" required>', seite)       # nicht angekreuzt
        self.assertNotIn('name="mieter_anwesend" checked', seite)

    def test_ohne_unterschrift_der_verwaltung_kein_abschluss(self):
        prot = self._vorort(); self._alle_io(prot)
        r = self._abschliessen(prot, follow=True, **abschluss_daten(unterschrift_verwalter_bild=''))
        self.assertContains(r, 'Die Unterschrift der Verwaltung fehlt')
        prot.refresh_from_db()
        self.assertFalse(prot.abgeschlossen)

    def test_anwesender_mieter_muss_unterschreiben(self):
        prot = self._vorort(); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten(mieter_anwesend='ja', unterschrift_mieter='Hans Muster'))
        prot.refresh_from_db()
        self.assertFalse(prot.abgeschlossen)
        self._abschliessen(prot, **abschluss_daten(unterschrift_mieter_bild=png_data_url()))
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        self.assertTrue(prot.mieter_anwesend)

    def test_abwesend_nur_mit_grund(self):
        prot = self._vorort(); self._alle_io(prot)
        r = self._abschliessen(prot, follow=True, **abschluss_daten(mieter_abwesend_grund=' '))
        self.assertContains(r, 'bitte den Grund angeben')
        prot.refresh_from_db()
        self.assertFalse(prot.abgeschlossen)
        self._abschliessen(prot, **abschluss_daten(mieter_abwesend_grund='Im Spital'))
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        self.assertEqual((prot.mieter_anwesend, prot.mieter_abwesend_grund), (False, 'Im Spital'))
        self.assertFalse(prot.unterschrift_mieter_bild)

    def test_anwesenheit_muss_gewaehlt_sein(self):
        prot = self._vorort(); self._alle_io(prot)
        r = self._abschliessen(prot, follow=True, **abschluss_daten(mieter_anwesend=''))
        self.assertContains(r, 'ob der Mieter anwesend war')

    def test_unbewertete_bauteile_brauchen_bestaetigung(self):
        prot = self._vorort()                                        # Keller: 5 Bauteile, alle offen
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1')
        self.assertContains(seite, 'Noch nicht bewertet: 5')
        self.assertContains(seite, 'Keller – Türrahmen')            # aufgelistet, nicht nur gezählt
        self._abschliessen(prot, **abschluss_daten(unbewertet_ok=''))
        prot.refresh_from_db()
        self.assertFalse(prot.abgeschlossen)
        self._abschliessen(prot, **abschluss_daten())
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)

    def test_pdf_druckt_nicht_unterzeichnet(self):
        prot = self._vorort(); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten())
        prot.refresh_from_db()
        text = '\n'.join(t for t, _ in _pdf(prot))
        self.assertIn('Mieter: nicht unterzeichnet', text)
        self.assertIn('Mieter abwesend: Im Ausland', text)
        self.assertNotIn('Verwaltung: nicht unterzeichnet', text)   # die Verwaltung hat unterschrieben


# --- 3. Mängelrüge Art. 267a -----------------------------------------------

class RuegeTests(Basis):

    FREITAG = date(2026, 10, 23)

    def _mit_mieterschaden(self, datum=FREITAG):
        prot = self._vorort(datum=datum); self._alle_io(prot)
        self._setze(prot, prot.positionen.get(bezeichnung='Boden'), zustand='uebermaessig', kosten='300')
        return prot

    def _ruege_pendenzen(self):
        from core.models import Pendenz
        return Pendenz.objects.filter(vertrag=self.v, titel__icontains='Mängelrüge Art. 267a')

    def test_frist_zaehlt_arbeitstage(self):
        from core.services.abnahme_abschluss import arbeitstage_nach
        self.assertEqual(arbeitstage_nach(self.FREITAG, 2), date(2026, 10, 27))          # Fr → Di
        self.assertEqual(arbeitstage_nach(date(2026, 10, 21), 2), date(2026, 10, 23))    # Mi → Fr
        self.assertEqual(arbeitstage_nach(date(2026, 10, 24), 2), date(2026, 10, 27))    # Sa → Di

    def test_pendenz_entsteht_beim_abschluss_auch_ohne_kuendigung(self):
        prot = self._mit_mieterschaden()
        self.assertFalse(self._ruege_pendenzen().exists())
        self._abschliessen(prot, **abschluss_daten())
        p = self._ruege_pendenzen().get()
        self.assertEqual((p.faellig_am, p.kategorie, p.erledigt), (date(2026, 10, 27), 'frist', False))
        self.assertIn('eingeschrieben', p.beschreibung)               # Mieter war abwesend

    def test_pendenz_der_kuendigung_wird_auf_die_abnahme_umdatiert(self):
        from core.models import Pendenz
        from core.services.abnahme_abschluss import RUEGE_TITEL
        Pendenz.objects.create(titel=RUEGE_TITEL, kategorie='frist', vertrag=self.v,
                               faellig_am=date(2027, 3, 31))
        prot = self._mit_mieterschaden()
        self._abschliessen(prot, **abschluss_daten(unterschrift_mieter_bild=png_data_url()))
        p = self._ruege_pendenzen().get()                             # keine zweite
        self.assertEqual(p.faellig_am, date(2026, 10, 27))
        self.assertNotIn('eingeschrieben', p.beschreibung)            # Mieter war da

    def test_pdf_erledigt_nichts_erst_der_versand(self):
        prot = self._mit_mieterschaden()
        self._abschliessen(prot, **abschluss_daten())
        r = self.c.post(f'/neu/abnahme/{prot.id}/ruege-267a/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertFalse(self._ruege_pendenzen().get().erledigt)
        heute = timezone.localdate()
        self.c.post(f'/neu/abnahme/{prot.id}/ruege-versandt/', {'datum': heute.isoformat(),
                                                                 'sendungsnummer': '98.00.123456.12345678'})
        p = self._ruege_pendenzen().get()
        prot.refresh_from_db()
        self.assertTrue(p.erledigt)
        self.assertEqual((p.versand_am, prot.ruege_versandt_am), (heute, heute))
        self.assertEqual(prot.ruege_sendungsnummer, '98.00.123456.12345678')

    def test_versanddatum_in_der_zukunft_oder_vor_der_abnahme_abgelehnt(self):
        prot = self._mit_mieterschaden()
        self._abschliessen(prot, **abschluss_daten())
        for datum in (timezone.localdate() + timedelta(days=1), self.FREITAG - timedelta(days=1)):
            self.c.post(f'/neu/abnahme/{prot.id}/ruege-versandt/', {'datum': datum.isoformat()})
            prot.refresh_from_db()
            self.assertIsNone(prot.ruege_versandt_am, datum)

    def test_detailseite_zeigt_frist_und_einschreiben_hinweis(self):
        prot = self._mit_mieterschaden()
        self._abschliessen(prot, **abschluss_daten())
        r = self.c.get(f'/neu/abnahme/{prot.id}/')
        self.assertContains(r, '27.10.2026')
        self.assertContains(r, 'Rüge eingeschrieben versenden')
        self.assertContains(r, 'action="/neu/abnahme/%s/ruege-versandt/"' % prot.id)

    def test_ohne_mieterschaden_ist_die_pendenz_gegenstandslos(self):
        from core.models import Pendenz
        from core.services.abnahme_abschluss import RUEGE_TITEL
        Pendenz.objects.create(titel=RUEGE_TITEL, kategorie='frist', vertrag=self.v, faellig_am=self.FREITAG)
        prot = self._vorort(datum=self.FREITAG); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten())
        self.assertTrue(self._ruege_pendenzen().get().erledigt)


# --- 4. Allgemeinzustand und neue Adresse ----------------------------------

class AbschlussFelderTests(Basis):

    def test_allgemeinzustand_wird_gefragt_und_gespeichert(self):
        prot = self._vorort(); self._alle_io(prot)
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1').content.decode()
        self.assertIn('name="allgemein_zustand" required', seite)
        self.assertNotIn('value="gut" selected', seite)              # nicht still auf «gut»
        r = self._abschliessen(prot, follow=True, **abschluss_daten(allgemein_zustand=''))
        self.assertContains(r, 'Allgemeinzustand wählen')
        self._abschliessen(prot, **abschluss_daten(allgemein_zustand='renovationsbeduerftig'))
        prot.refresh_from_db()
        self.assertEqual(prot.allgemein_zustand, 'renovationsbeduerftig')

    def test_neue_adresse_wird_zur_wohnadresse_ab_abnahme(self):
        from crm.models import MieterAdresse
        prot = self._vorort(); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten(neue_adresse='Bergweg 7, 3000 Bern'))
        prot.refresh_from_db()
        self.assertEqual(prot.neue_adresse, 'Bergweg 7, 3000 Bern')
        a = MieterAdresse.objects.get(mieter=self.mieter, quelle=f'auszug:{prot.id}')
        self.assertEqual((a.plz, a.ort, a.gueltig_ab), ('3000', 'Bern', prot.datum))

    def test_gescheiterter_abschluss_behaelt_die_eingaben(self):
        prot = self._vorort(); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten(unterschrift_verwalter_bild='', zaehler_strom='4711',
                                                   neue_adresse='Bergweg 7, 3000 Bern'))
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1')
        self.assertContains(seite, 'value="4711"')
        self.assertContains(seite, 'value="Bergweg 7, 3000 Bern"')


# --- 5. Fotos im klassischen Formular --------------------------------------

class KlassischesFormularFotoTests(Basis):

    def test_foto_bleibt_an_seiner_zeile(self):
        """Zeile 0 ohne Foto, Zeile 1 mit: Das Foto gehört zu Zeile 1.

        Gegenprobe: in fw_abnahme_neu wieder `fotos.pop(0)` über
        `request.FILES.getlist(...)` zuordnen — dann landet es an Zeile 0."""
        from rentals.models import AbnahmeMangel
        r = self.c.post(f'/neu/vertraege/{self.v.id}/abnahme/neu/', {
            'typ': 'auszug', 'datum': '2026-06-30',
            'm_zeile': ['0', '1'], 'm_raum': ['Küche', 'Bad'], 'm_beschreibung': ['Ohne Foto', 'Mit Foto'],
            'm_verursacher': ['mieter', 'mieter'], 'm_kosten': ['10', '20'],
            'm_ausstattung': ['', ''], 'm_neuwert': ['', ''], 'm_vorsatz': ['', ''],
            'm_foto_1': SimpleUploadedFile('b.jpg', _jpeg(), content_type='image/jpeg')})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AbnahmeMangel.objects.get(beschreibung='Ohne Foto').foto)
        self.assertTrue(AbnahmeMangel.objects.get(beschreibung='Mit Foto').foto)

    def test_formular_schliesst_nicht_mehr_ab_und_fuehrt_zum_abschluss(self):
        from rentals.models import Abnahmeprotokoll
        r = self.c.post(f'/neu/vertraege/{self.v.id}/abnahme/neu/', {
            'typ': 'auszug', 'datum': '2026-06-30', 'abgeschlossen': 'on'})
        prot = Abnahmeprotokoll.objects.get(vertrag=self.v)
        self.assertFalse(prot.abgeschlossen)
        self.assertRedirects(r, f'/neu/abnahme/{prot.id}/vorort/', fetch_redirect_response=False)
        self._abschliessen(prot, **abschluss_daten())
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)


# --- 6. Löschen ------------------------------------------------------------

class LoeschenTests(Basis):

    def test_abgeschlossenes_protokoll_bleibt(self):
        from rentals.models import Abnahmeprotokoll
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        self.c.post(f'/neu/abnahme/{prot.id}/loeschen/')
        self.assertTrue(Abnahmeprotokoll.objects.filter(id=prot.id).exists())

    def test_offenes_nur_durch_verwalter(self):
        from rentals.models import Abnahmeprotokoll
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [], abgeschlossen=False)
        sb = Client(); sb.force_login(_team_user('Sachbearbeitung'))
        self.assertEqual(sb.post(f'/neu/abnahme/{prot.id}/loeschen/').status_code, 403)
        self.assertTrue(Abnahmeprotokoll.objects.filter(id=prot.id).exists())
        self.c.post(f'/neu/abnahme/{prot.id}/loeschen/')                     # Verwalter
        self.assertFalse(Abnahmeprotokoll.objects.filter(id=prot.id).exists())

    def test_knopf_nur_bei_offenem_protokoll(self):
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        self.assertNotContains(self.c.get(f'/neu/abnahme/{prot.id}/'), '/loeschen/')
        prot.abgeschlossen = False; prot.save()
        self.assertContains(self.c.get(f'/neu/abnahme/{prot.id}/'), f'/neu/abnahme/{prot.id}/loeschen/')


# --- 7. PDF ----------------------------------------------------------------

class PdfTests(Basis):

    def test_langer_mangeltext_steht_vollstaendig_da(self):
        from rentals.models import AbnahmeMangel
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        lang = ('Glaskeramikfeld links hinten gesprungen, Riss etwa fünfzehn Zentimeter lang, '
                'zusätzlich Brandfleck auf der Arbeitsplatte rechts')
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung=lang, verursacher='mieter',
                                     kostenschaetzung=Decimal('900'))
        text = ' '.join('\n'.join(t for t, _ in _pdf(prot)).split())
        self.assertIn('Arbeitsplatte rechts', text)       # vorher nach 44 Zeichen abgeschnitten
        self.assertIn('Alter/Lebensdauer des Bauteils nicht erfasst', text)

    def test_foto_aus_dem_klassischen_formular_im_bildteil(self):
        from rentals.models import AbnahmeMangel
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        m = AbnahmeMangel(protokoll=prot, raum='Bad', beschreibung='Spiegel', verursacher='mieter')
        m.foto.save('s.jpg', SimpleUploadedFile('s.jpg', _jpeg()), save=False)
        m.save()
        seiten = _pdf(prot)
        self.assertEqual(sum(b for _, b in seiten), 1)
        self.assertIn('M1 Spiegel', seiten[-1][0])

    def test_seitenzahlen(self):
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30),
                          [('Raum', f'Bauteil {i:03d}', 'io', '') for i in range(120)])
        seiten = _pdf(prot)
        self.assertGreater(len(seiten), 1)
        for nr, (text, _) in enumerate(seiten, start=1):
            self.assertIn(f'Seite {nr} von {len(seiten)}', text)


# --- 8. Vertragsseite führt in die Abnahme vor Ort -------------------------

class VertragsseiteTests(Basis):

    def test_hauptweg_ist_vor_ort(self):
        body = self.c.get(f'/neu/vertraege/{self.v.id}/').content.decode()
        vorort = body.find(f'/neu/vertraege/{self.v.id}/abnahme/vorort/')
        formular = body.find(f'/neu/vertraege/{self.v.id}/abnahme/neu/')
        self.assertGreater(vorort, -1)
        self.assertTrue(formular == -1 or vorort < formular)

    def test_aktionsliste_fuehrt_vor_ort(self):
        from core.views.fw.detailseiten import _formulare_prozesse
        urls = [it['url'] for g in _formulare_prozesse(self.v) for it in g['items'] if it['titel'] == 'Wohnungsabnahme']
        self.assertEqual(urls, [f'/neu/vertraege/{self.v.id}/abnahme/vorort/'])


# --- 9. Später entdeckter Mangel -------------------------------------------

class NachmangelTests(Basis):

    def _abgeschlossen(self):
        prot = self._vorort(datum=date(2026, 10, 1)); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten())
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        return prot

    def _erfassen(self, prot, **d):
        daten = {'raum': 'Bad', 'beschreibung': 'Wasserschaden unter der Wanne',
                 'entdeckt_am': '2026-10-20', 'kosten': '1200', **d}
        return self.c.post(f'/neu/abnahme/{prot.id}/nachmangel/', daten)

    def test_erfassen_ruegen_versenden(self):
        from core.models import Pendenz
        from rentals.models import Dokument
        prot = self._abgeschlossen()
        self._erfassen(prot)
        m = prot.maengel.get(entdeckt_am=date(2026, 10, 20))
        self.assertEqual((m.verursacher, m.mieteranteil), ('mieter', Decimal('1200.00')))
        p = Pendenz.objects.get(quelle=f'abnahme:nachruege:{m.id}')
        self.assertEqual((p.faellig_am, p.erledigt), (date(2026, 10, 22), False))
        r = self.c.post(f'/neu/abnahme/{prot.id}/ruege-267a/', {'mangel': m.id})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(Dokument.objects.filter(vertrag=self.v, bezeichnung__startswith='Mängelrüge Art. 267a Abs. 3').exists())
        self.c.post(f'/neu/abnahme/{prot.id}/ruege-versandt/', {'mangel': m.id, 'datum': '2026-10-21'})
        p.refresh_from_db(); m.refresh_from_db()
        self.assertTrue(p.erledigt)
        self.assertEqual(m.ruege_versandt_am, date(2026, 10, 21))

    def test_getrennt_vom_unterzeichneten_protokoll(self):
        from core.services import abnahme_abschluss as ab, abnahme_texte as T
        prot = self._abgeschlossen()
        self._erfassen(prot)
        self.assertEqual(ab.ruege_posten(prot), [])                       # nicht in der Rüge nach der Abnahme
        self.assertNotIn('Kostenübernahme', dict(T.schlussbestimmungen(prot)))
        self.assertEqual(prot.kosten_mieter_total, Decimal('1200.00'))    # aber in der Schlussabrechnung
        text = '\n'.join(t for t, _ in _pdf(prot))
        self.assertIn('Nach der Abnahme entdeckte Mängel', text)
        self.assertIn('[entdeckt 20.10.2026]', text)

    def test_nur_am_abgeschlossenen_auszug_und_mit_gueltigem_datum(self):
        # Abnahme VOR dem Entdeckungsdatum: Sonst fiele der Versuch schon am
        # Datum durch, und die Sperre für offene Protokolle bliebe ungeprüft
        # (so geschehen in der ersten Fassung — Gegenprobe blieb grün).
        offen = self._vorort(datum=date(2026, 10, 1))
        self._erfassen(offen)
        self.assertFalse(offen.maengel.exists())
        prot = self._abgeschlossen()
        self._erfassen(prot, entdeckt_am='2026-09-30')                    # vor der Abnahme
        self._erfassen(prot, entdeckt_am=(timezone.localdate() + timedelta(days=1)).isoformat())
        self.assertFalse(prot.maengel.exists())


# --- 10. Schlüsselersatz und Handwerker ------------------------------------

class SchluesselUndHandwerkerTests(Basis):

    def test_fehlender_schluessel_kostet_den_mieter(self):
        prot = self._vorort(); self._alle_io(prot)
        self._abschliessen(prot, **abschluss_daten(s_bezeichnung=['Wohnung', 'Briefkasten'], s_anlage=['', ''],
                                                   s_soll=['3', '2'], s_ist=['2', '2'], s_kosten=['85.50', '40']))
        prot.refresh_from_db()
        self.assertEqual(prot.schluessel_kosten_total, Decimal('85.50'))
        self.assertEqual(prot.kosten_mieter_total, Decimal('85.50'))
        from core.services.abnahme_abschluss import ruege_noetig, ruege_posten
        self.assertTrue(ruege_noetig(prot))
        self.assertIn('Fehlende Schlüssel: 1 × Wohnung', ruege_posten(prot)[0]['beschreibung'])
        r = self.c.get(f'/neu/vertraege/{self.v.id}/schlussabrechnung/')
        self.assertIn({'text': 'Fehlende Schlüssel: 1 × Wohnung', 'betrag': Decimal('85.50')},
                      r.context['prefill_positionen'])
        self.assertIn('85.50', ' '.join(t for t, _ in _pdf(prot)))

    def test_handwerker_beauftragen_legt_ein_ticket_an(self):
        from tickets.models import SchadenMeldung
        prot = self._vorort(); self._alle_io(prot)
        pos = prot.positionen.get(bezeichnung='Boden')
        self._setze(prot, pos, zustand='uebermaessig', kosten='300', kommentar='Fliese gesprungen')
        pos.refresh_from_db()
        r = self.c.post(f'/neu/abnahme/{prot.id}/handwerker/', {'mangel': pos.mangel_id})
        t = SchadenMeldung.objects.get()
        self.assertRedirects(r, f'/neu/schaeden/{t.id}/', fetch_redirect_response=False)
        self.assertEqual((t.betroffene_einheit_id, t.liegenschaft_id), (self.einheit.id, self.lg.id))
        self.assertIn('Fliese gesprungen', t.titel)
        pos.mangel.refresh_from_db()
        self.assertEqual(pos.mangel.ticket_id, t.id)
        self.c.post(f'/neu/abnahme/{prot.id}/handwerker/', {'mangel': pos.mangel_id})
        self.assertEqual(SchadenMeldung.objects.count(), 1)               # kein zweites Ticket
        self.assertContains(self.c.get(f'/neu/abnahme/{prot.id}/'), f'/neu/schaeden/{t.id}/')

    def test_mangel_eines_anderen_protokolls_ist_404(self):
        from rentals.models import AbnahmeMangel
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        anderes = _protokoll(self.v, 'einzug', date(2024, 1, 1), [])
        m = AbnahmeMangel.objects.create(protokoll=anderes, beschreibung='x', verursacher='vermieter')
        self.assertEqual(self.c.post(f'/neu/abnahme/{prot.id}/handwerker/', {'mangel': m.id}).status_code, 404)


# --- 11. Mietzinsdepot nur bei Bankdepot -----------------------------------

class DepotTextTests(Basis):

    def _titel(self):
        from core.services.abnahme_texte import schlussbestimmungen
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        return [t for t, _ in schlussbestimmungen(prot)]

    def test_nur_mit_sperrkonto_und_betrag(self):
        self.assertIn('Mietzinsdepot', self._titel())                    # Sperrkonto, CHF 4500
        self.v.kautions_art = 'versicherung'; self.v.save()
        self.assertNotIn('Mietzinsdepot', self._titel())
        self.v.kautions_art = 'sperrkonto'; self.v.kautions_betrag = None; self.v.save()
        self.assertNotIn('Mietzinsdepot', self._titel())


# --- 12. Fotoablage je Organisation ----------------------------------------

class FotoablageTests(Basis):

    def test_neues_mangelfoto_liegt_unter_der_organisation(self):
        from core.views.media_protected import ist_oeffentlich
        from rentals.models import AbnahmeMangel
        prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [])
        m = AbnahmeMangel(protokoll=prot, beschreibung='x')
        m.foto.save('f.jpg', SimpleUploadedFile('f.jpg', _jpeg()), save=False)
        m.save()
        self.assertTrue(m.foto.name.startswith(f'organisation/{prot.organisation_id}/abnahme_fotos/'), m.foto.name)
        self.assertFalse(ist_oeffentlich(m.foto.name))


# --- Mandantentrennung der neuen Aktionen ----------------------------------

class NeueAktionenMandantenTests(TestCase):
    """A greift mit gültigen Daten auf das Protokoll von B zu: 404, nichts ändert sich."""

    @classmethod
    def setUpTestData(cls):
        from core.tenancy import organisation_kontext
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(cls.b.organisation):
            cls.prot_b = Abnahmeprotokoll.objects.create(vertrag=cls.b.vertrag, typ='auszug',
                                                         datum=date(2026, 6, 30), abgeschlossen=True)
            cls.mangel_b = AbnahmeMangel.objects.create(protokoll=cls.prot_b, beschreibung='Kratzer',
                                                        verursacher='mieter', kostenschaetzung=Decimal('50'))

    def setUp(self):
        self.c = Client(); self.c.force_login(self.a.benutzer)

    def _stand_b(self):
        from core.tenancy import organisation_kontext
        from rentals.models import Abnahmeprotokoll
        with organisation_kontext(self.b.organisation):
            p = Abnahmeprotokoll.objects.get(id=self.prot_b.id)
            return (p.ruege_versandt_am, p.maengel.count(), p.maengel.get(id=self.mangel_b.id).ticket_id)

    def test_fremdes_protokoll_ist_404(self):
        vorher = self._stand_b()
        heute = timezone.localdate().isoformat()
        for url, daten in ((f'/neu/abnahme/{self.prot_b.id}/ruege-versandt/', {'datum': heute}),
                           (f'/neu/abnahme/{self.prot_b.id}/nachmangel/',
                            {'beschreibung': 'x', 'entdeckt_am': heute}),
                           (f'/neu/abnahme/{self.prot_b.id}/handwerker/', {'mangel': self.mangel_b.id})):
            self.assertEqual(self.c.post(url, daten).status_code, 404, url)
        self.assertEqual(self._stand_b(), vorher)


# --- Bestandsschutz (Migration rentals.0047) --------------------------------

class AltbestandTests(Basis):
    """Offene Protokolle aus dem klassischen Formular galten bis 10/2026 als
    durchgeführt. Die Datenmigration übernimmt das für den Bestand — neue
    Protokolle brauchen den Abschluss."""

    def test_migration_uebernimmt_offene_klassische_als_durchgefuehrt(self):
        import importlib
        from django.apps import apps
        from core.services.abnahme_vorgaenger import durchgefuehrt
        from rentals.models import Abnahmeprotokoll
        klassisch = _protokoll(self.v, 'auszug', date(2026, 9, 30), [], abgeschlossen=False)
        vorort = _protokoll(self.v, 'auszug', date(2026, 9, 30), [('Küche', 'Boden', 'io', '')],
                            abgeschlossen=False)
        alle = Abnahmeprotokoll.objects.filter(pk__in=[klassisch.pk, vorort.pk])
        self.assertEqual(list(durchgefuehrt(alle)), [], 'Ohne Abschluss zählt nach neuer Regel nichts')
        mig = importlib.import_module('rentals.migrations.0047_abnahme_altbestand')
        mig.altbestand_markieren(apps, None)
        self.assertEqual(list(durchgefuehrt(alle)), [klassisch],
                         'Bestand aus dem klassischen Formular bleibt durchgeführt, ein offener Vor-Ort-Entwurf nicht')
        # Ein neues klassisches Protokoll nach der Migration bekommt die Markierung nicht.
        neu = _protokoll(self.v, 'auszug', date(2026, 10, 27), [], abgeschlossen=False)
        self.assertNotIn(neu, list(durchgefuehrt(Abnahmeprotokoll.objects.filter(pk=neu.pk))))
