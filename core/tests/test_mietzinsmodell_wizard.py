"""Mietzinsmodell im Vertragsassistenten (27.10.2026): Server-Sperren in allen Schreibwegen und Aufbau der Seite.

Die Regeln selbst prüft `test_mietzinsmodell.py`. Hier geht es um die Wege, auf denen ein Vertrag entsteht
oder sich ändert: Assistent (Speichern, Vorschau), Bearbeiten und Statuswechsel Entwurf → aktiv. Der Browser
lässt sich umgehen; jeder dieser Wege prüft deshalb selbst und speichert bei einer Sperre nichts.

Jeder Test hat seine Gegenprobe im selben Test: Der gültige Fall wird gespeichert, die Abwandlung um einen Tag
oder einen Franken nicht. Ein Test, der nur die Ablehnung prüft, bliebe auch grün, wenn immer abgelehnt würde.
"""
import json
import re
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from core.services.mietrecht import index_anpassung_vorschlag
from rentals.models import Mietvertrag, Staffelstufe

from ._helfer import Einheit, Liegenschaft, Mieter, _team_user, _test_organisation


class WizardBasis(TestCase):
    def setUp(self):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Modellweg 1', plz='8000',
                                         ort='Zürich', versicherungswert=Decimal('1000000'))
        self.e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg',
                                        nettomiete_aktuell=Decimal('2000'))
        self.m = Mieter.objects.create(typ='person', vorname='Mia', nachname='Modell')
        self.c = Client()
        self.c.force_login(_team_user(rolle='Verwaltung'))

    # Gültige Eingaben je Modell: Beginn 1.1.2025
    def daten(self, **extra):
        d = {'einheit_id': str(self.e.id), 'mieter_id': str(self.m.id), 'netto_mietzins': '2000',
             'nebenkosten': '200', 'beginn': '2025-01-01'}
        d.update(extra)
        return d

    def index(self, **extra):
        return self.daten(**{'mietzins_modell': 'index', 'ist_befristet': '1', 'ende': '2029-12-31',
                             'basis_lik_punkte': '106.9', 'basis_lik_stand': '2024-12',
                             'index_weitergabe_prozent': '100', 'index_intervall_monate': '12', **extra})

    def staffel(self, **extra):
        return self.daten(**{'mietzins_modell': 'staffel', 'ist_befristet': '1', 'ende': '2027-12-31',
                             'staffel_ab': ['2026-01-01', '2027-01-01'], 'staffel_erhoehung': ['50', '50'],
                             **extra})

    def speichern(self, daten):
        return self.c.post('/neu/vertraege/neu/speichern/', daten)

    def gespeichert(self):
        return Mietvertrag.objects.filter(einheit=self.e)

    def abgelehnt(self, daten, feld=None):
        """Ablehnung: Status 400, nichts gespeichert, die Meldung steht beim Feld."""
        r = self.speichern(daten)
        self.assertEqual(r.status_code, 400, r.content.decode()[:200])
        self.assertFalse(self.gespeichert().exists(), 'Trotz Sperre wurde ein Vertrag angelegt')
        if feld:
            self.assertIn(feld, r.context['feld_fehler'])
        return r

    def angenommen(self, daten):
        r = self.speichern(daten)
        self.assertEqual(r.status_code, 302, r.content.decode()[:300])
        return self.gespeichert().get()


class SpeichernIndexTests(WizardBasis):
    def test_genau_fuenf_jahre_ok_einen_tag_weniger_nicht(self):
        self.abgelehnt(self.index(ende='2029-12-30'), 'ende')
        v = self.angenommen(self.index(ende='2029-12-31'))
        self.assertEqual(v.mietzins_modell, 'index')
        self.assertTrue(v.ist_befristet)

    def test_kuendigungsverzicht_ist_der_zweite_weg(self):
        unbefristet = self.index(ist_befristet='0', ende='')
        self.abgelehnt(unbefristet)  # weder befristet noch Verzicht
        self.abgelehnt({**unbefristet, 'vermieter_kuendigungsverzicht_bis': '2029-12-30'},
                       'vermieter_kuendigungsverzicht_bis')
        v = self.angenommen({**unbefristet, 'vermieter_kuendigungsverzicht_bis': '2029-12-31'})
        self.assertFalse(v.ist_befristet)
        self.assertIsNone(v.ende)
        self.assertEqual(v.vermieter_kuendigungsverzicht_bis, date(2029, 12, 31))

    def test_bei_befristung_wird_kein_verzicht_gespeichert(self):
        """Bei einem befristeten Vertrag zählt das Ende; ein stehengebliebener Verzicht bleibt nicht."""
        v = self.angenommen(self.index(vermieter_kuendigungsverzicht_bis='2030-01-01'))
        self.assertIsNone(v.vermieter_kuendigungsverzicht_bis)

    def test_weitergabe_nur_ueber_null_bis_hundert(self):
        for roh in ('0', '-5', '100.1', '150'):
            with self.subTest(weitergabe=roh):
                self.abgelehnt(self.index(index_weitergabe_prozent=roh), 'index_weitergabe_prozent')
        v = self.angenommen(self.index(index_weitergabe_prozent='60.5'))
        self.assertEqual(v.index_weitergabe_prozent, Decimal('60.5'))

    def test_basis_fehlt_oder_liegt_nach_dem_mietbeginn(self):
        self.abgelehnt(self.index(basis_lik_punkte=''), 'basis_lik_punkte')
        self.abgelehnt(self.index(basis_lik_stand=''), 'basis_lik_stand')
        self.abgelehnt(self.index(basis_lik_stand='2025-02'), 'basis_lik_stand')
        v = self.angenommen(self.index(basis_lik_stand='2025-01'))   # Beginnmonat selbst ist erlaubt
        self.assertEqual(v.basis_lik_stand, date(2025, 1, 1))

    def test_basis_hat_hoechstens_eine_nachkommastelle(self):
        self.abgelehnt(self.index(basis_lik_punkte='106.95'), 'basis_lik_punkte')
        self.angenommen(self.index(basis_lik_punkte='106.9'))

    def test_staffelstufen_neben_dem_index_werden_abgelehnt(self):
        """BGE 124 III 57: Index und Staffel nicht zusammen. Der Browser sendet sie nie; der Server lehnt sie ab."""
        self.abgelehnt(self.index(staffel_ab=['2026-01-01'], staffel_erhoehung=['50']))
        v = self.angenommen(self.index(staffel_ab=[''], staffel_erhoehung=['']))   # leere Zeile zählt nicht
        self.assertEqual(v.staffelstufen.count(), 0)

    def test_unlesbarer_stand_wird_nicht_still_ersetzt(self):
        self.abgelehnt(self.index(basis_lik_stand='Juni'), 'basis_lik_stand')
        self.angenommen(self.index(basis_lik_stand='2024-12'))

    def test_ohne_mietbeginn_keine_index_oder_staffelmiete(self):
        """Ohne Beginn liesse sich die Dauer nicht beurteilen; der Server nähme sonst «heute»."""
        self.abgelehnt(self.index(beginn=''), 'beginn')
        self.angenommen(self.daten(beginn=''))   # fester Mietzins: wie bisher, Beginn = heute


class SpeichernStaffelTests(WizardBasis):
    def test_stufen_werden_mit_erhoehung_in_chf_angelegt(self):
        v = self.angenommen(self.staffel())
        stufen = list(v.staffelstufen.order_by('ab_datum'))
        self.assertEqual([(s.ab_datum, s.erhoehung_chf, s.netto_mietzins) for s in stufen],
                         [(date(2026, 1, 1), Decimal('50.00'), Decimal('2050.00')),
                          (date(2027, 1, 1), Decimal('50.00'), Decimal('2100.00'))])
        self.assertEqual(v.effektiver_netto_mietzins(date(2027, 6, 1)), Decimal('2100.00'))

    def test_dauer_drei_jahre_genau_ok_einen_tag_weniger_nicht(self):
        self.abgelehnt(self.staffel(ende='2027-12-30'), 'ende')
        self.angenommen(self.staffel(ende='2027-12-31'))

    def test_kuendigungsverzicht_ersetzt_die_befristung_auch_bei_der_staffel(self):
        unbef = self.staffel(ist_befristet='0', ende='')
        self.abgelehnt({**unbef, 'vermieter_kuendigungsverzicht_bis': '2027-12-30'})
        v = self.angenommen({**unbef, 'vermieter_kuendigungsverzicht_bis': '2027-12-31'})
        self.assertEqual(v.vermieter_kuendigungsverzicht_bis, date(2027, 12, 31))

    def test_erhoehung_null_negativ_fehlend_und_zu_viele_stellen(self):
        for roh in ('0', '-10', '', '50.555', '1000000'):
            with self.subTest(erhoehung=roh):
                self.abgelehnt(self.staffel(staffel_erhoehung=['50', roh]), 'staffel_erhoehung[1]')
        self.angenommen(self.staffel(staffel_erhoehung=['50', '0.05']))

    def test_prozent_ist_unmoeglich(self):
        """Art. 269c lit. c OR: nur Frankenbeträge. Auch ein mitgeschicktes Prozentfeld wird abgelehnt."""
        self.abgelehnt(self.staffel(staffel_prozent=['', '2.5']), 'staffel_prozent[1]')
        self.angenommen(self.staffel(staffel_prozent=['', '']))

    def test_der_alte_betrag_der_stufe_wird_nicht_mehr_angenommen(self):
        """`staffel_netto` (neuer Mietzins statt Erhöhung) gibt es nicht mehr; nichts wird geraten."""
        self.abgelehnt(self.staffel(staffel_netto=['2050', '2100']), 'staffelstufen')

    def test_zwoelf_monate_zum_beginn_und_zwischen_den_stufen(self):
        self.abgelehnt(self.staffel(staffel_ab=['2025-12-31', '2027-01-01']), 'staffel_ab[0]')
        self.abgelehnt(self.staffel(staffel_ab=['2026-01-01', '2026-12-31']), 'staffel_ab[1]')
        self.angenommen(self.staffel(staffel_ab=['2026-01-01', '2027-01-01']))

    def test_zeilenfehler_haengt_an_der_zeile_und_die_eingaben_kommen_zurueck(self):
        r = self.abgelehnt(self.staffel(staffel_ab=['2026-01-01', '2026-06-01'], staffel_erhoehung=['50', '70']))
        self.assertIn('staffel_ab[1]', r.context['feld_fehler'])
        rueck = r.context['rueckgabe']
        self.assertEqual(rueck['staffel_ab'], ['2026-01-01', '2026-06-01'])
        self.assertEqual(rueck['staffel_erhoehung'], ['50', '70'])
        self.assertContains(r, 'staffel_ab[1]', status_code=400)

    def test_ohne_stufe_keine_staffel(self):
        self.abgelehnt(self.staffel(staffel_ab=[''], staffel_erhoehung=['']), 'staffelstufen')
        self.angenommen(self.staffel(staffel_ab=['2026-01-01'], staffel_erhoehung=['50']))

    def test_unlesbares_datum_und_unlesbarer_betrag(self):
        self.abgelehnt(self.staffel(staffel_ab=['bald', '2027-01-01']), 'staffel_ab[0]')
        self.abgelehnt(self.staffel(staffel_erhoehung=['50', 'viel']), 'staffel_erhoehung[1]')

    def test_indexfelder_neben_der_staffel_werden_abgelehnt(self):
        self.abgelehnt(self.staffel(index_weitergabe_prozent='80'))
        self.angenommen(self.staffel(index_weitergabe_prozent='100', index_intervall_monate='12'))

    def test_fest_mit_indexfeldern_oder_stufen_wird_abgelehnt(self):
        """Der Wechsel räumt das andere Modell: Was der Browser nicht mehr sendet, nimmt der Server nicht an."""
        self.abgelehnt(self.daten(index_weitergabe_prozent='80'), 'index_weitergabe_prozent')
        self.abgelehnt(self.daten(staffel_ab=['2026-01-01'], staffel_erhoehung=['50']))
        v = self.angenommen(self.daten())
        self.assertEqual((v.mietzins_modell, v.index_weitergabe_prozent, v.index_intervall_monate),
                         ('fest', Decimal('100'), 12))

    def test_unbekanntes_modell_wird_abgelehnt(self):
        self.abgelehnt(self.daten(mietzins_modell='gleitend'), 'mietzins_modell')

    def test_basis_lik_ist_der_vormonat_zum_mietbeginn_nicht_der_aktuelle(self):
        v = self.angenommen(self.staffel())
        self.assertEqual(v.basis_lik_stand, date(2024, 12, 1))
        self.assertEqual(v.basis_lik_punkte, Decimal('106.9'))


class BearbeitenEntwurfTests(WizardBasis):
    """Ein Entwurf wird im Assistenten bearbeitet (`edit_id`)."""

    def entwurf(self, **felder):
        v = Mietvertrag.objects.create(
            mieter=self.m, einheit=self.e, beginn=date(2025, 1, 1), netto_mietzins=Decimal('2000'),
            nebenkosten=Decimal('200'), status='entwurf', mietzins_modell='index', ist_befristet=True,
            ende=date(2028, 12, 31), basis_lik_punkte=Decimal('106.9'), basis_lik_stand=date(2024, 12, 1),
            **felder)
        return v

    def bearbeiten(self, v, **extra):
        return self.speichern(self.index(edit_id=str(v.id), ende='2028-12-31', **extra))

    def test_unveraenderter_altentwurf_wird_nicht_blockiert_aber_gemeldet(self):
        v = self.entwurf()   # vier Jahre: nach den heutigen Regeln zu kurz
        r = self.bearbeiten(v, nebenkosten='250')
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.nebenkosten, Decimal('250'))
        meldungen = ' '.join(str(m) for m in get_messages(r.wsgi_request))
        self.assertIn('Mietzinsmodell dieses Entwurfs', meldungen)

    def test_aenderung_am_modell_wird_geprueft(self):
        v = self.entwurf()
        r = self.speichern(self.index(edit_id=str(v.id), ende='2029-01-01'))   # immer noch zu kurz
        self.assertEqual(r.status_code, 400)
        v.refresh_from_db()
        self.assertEqual(v.ende, date(2028, 12, 31))
        r = self.speichern(self.index(edit_id=str(v.id), ende='2029-12-31'))   # Gegenprobe: gültig
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.ende, date(2029, 12, 31))

    def test_wechsel_auf_fest_raeumt_die_stufen(self):
        v = self.angenommen(self.staffel())
        self.assertEqual(v.staffelstufen.count(), 2)
        r = self.speichern(self.staffel(edit_id=str(v.id)))   # bleibt Staffel: Stufen bleiben, neu angelegt
        self.assertEqual(r.status_code, 302)
        self.assertEqual(v.staffelstufen.count(), 2)
        r = self.speichern(self.daten(edit_id=str(v.id)))   # Wechsel auf fest
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual((v.mietzins_modell, v.staffelstufen.count()), ('fest', 0))

    def test_staffelstufen_eines_altentwurfs_ohne_erhoehung_bleiben_mit_ihrem_betrag(self):
        """Ältere Masken senden keine Staffelzeilen: Die Stufen mit nur einem Betrag bleiben, nichts wird geraten."""
        v = self.entwurf()
        Mietvertrag.objects.filter(pk=v.pk).update(mietzins_modell='staffel', ende=date(2027, 12, 31))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2050'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2027, 1, 1), netto_mietzins=Decimal('2100'))
        r = self.speichern(self.daten(edit_id=str(v.id), mietzins_modell='staffel', ist_befristet='1',
                                      ende='2027-12-31'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(sorted(v.staffelstufen.values_list('netto_mietzins', flat=True)),
                         [Decimal('2050.00'), Decimal('2100.00')])


class VorschauTests(WizardBasis):
    def vorschau(self, daten):
        r = self.c.post('/neu/vertraege/vorschau/', daten)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_sperre_zeigt_die_befunde_statt_des_vertrags(self):
        html = self.vorschau(self.index(ende='2029-12-30'))
        self.assertIn('Vorschau nicht möglich', html)
        self.assertIn('Art. 269b OR', html)
        self.assertNotIn('Indexklausel', html)
        ok = self.vorschau(self.index(ende='2029-12-31'))   # Gegenprobe
        self.assertNotIn('Vorschau nicht möglich', ok)
        self.assertIn('Indexklausel', ok)

    def test_staffelklausel_zeigt_die_noch_nicht_gespeicherten_stufen(self):
        html = self.vorschau(self.staffel())
        self.assertIn('Staffelmietklausel', html)
        self.assertIn('Erhöhung um CHF 50', html)
        self.assertIn('2100', html.replace("'", '').replace('’', ''))
        self.assertNotIn('Vorschau nicht möglich', html)
        schlecht = self.vorschau(self.staffel(staffel_erhoehung=['50', '0']))
        self.assertIn('Vorschau nicht möglich', schlecht)

    def test_kuendigungsverzicht_steht_in_der_vorschau(self):
        html = self.vorschau(self.index(ist_befristet='0', ende='', vermieter_kuendigungsverzicht_bis='2029-12-31'))
        self.assertIn('verzichtet bis zum 31.12.2029', html)

    def test_fester_mietzins_hat_keine_klausel(self):
        html = self.vorschau(self.daten())
        self.assertNotIn('Indexklausel', html)
        self.assertNotIn('Staffelmietklausel', html)


class StatuswechselTests(WizardBasis):
    def entwurf(self, **felder):
        daten = dict(mieter=self.m, einheit=self.e, beginn=date(2025, 1, 1), netto_mietzins=Decimal('2000'),
                     nebenkosten=Decimal('200'), status='entwurf', mietzins_modell='index', ist_befristet=True,
                     ende=date(2029, 12, 30), basis_lik_punkte=Decimal('106.9'), basis_lik_stand=date(2024, 12, 1))
        daten.update(felder)
        return Mietvertrag.objects.create(**daten)

    def aktivieren(self, v):
        return self.c.post(f'/neu/vertraege/{v.id}/status/', {'status': 'aktiv'}, follow=True)

    def test_entwurf_mit_sperre_wird_nicht_aktiv_einen_tag_mehr_schon(self):
        v = self.entwurf()
        r = self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'entwurf')
        self.assertIn('Art. 269b OR', ' '.join(str(m) for m in r.context['messages']))
        v.ende = date(2029, 12, 31); v.save()
        self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_staffel_ohne_stufe_wird_nicht_aktiv(self):
        v = self.entwurf(mietzins_modell='staffel', ende=date(2027, 12, 31))
        self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'entwurf')
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2050'),
                                    erhoehung_chf=Decimal('50'))
        self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')

    def test_fester_mietzins_und_andere_stati_bleiben_wie_bisher(self):
        v = self.entwurf(mietzins_modell='fest', ende=None, ist_befristet=False)
        self.aktivieren(v)
        v.refresh_from_db()
        self.assertEqual(v.status, 'aktiv')
        self.c.post(f'/neu/vertraege/{v.id}/status/', {'status': 'archiviert'})
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')


class BearbeitenAktivTests(WizardBasis):
    """`fw_vertrag_bearbeiten`: Ende und Kündigungsverzicht eines laufenden Vertrags."""

    def vertrag(self, **felder):
        daten = dict(mieter=self.m, einheit=self.e, beginn=date(2025, 1, 1), netto_mietzins=Decimal('2000'),
                     nebenkosten=Decimal('200'), status='aktiv', mietzins_modell='index', ist_befristet=True,
                     ende=date(2029, 12, 31), basis_lik_punkte=Decimal('106.9'), basis_lik_stand=date(2024, 12, 1))
        daten.update(felder)
        return Mietvertrag.objects.create(**daten)

    def post(self, v, **extra):
        d = {'kuendigungsfrist': '3', 'anzahl_personen': '1'}
        d.update(extra)
        return self.c.post(f'/neu/vertraege/{v.id}/bearbeiten/', d)

    def test_verkuerztes_ende_wird_abgelehnt(self):
        v = self.vertrag()
        r = self.post(v, ende='2029-12-30')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Art. 269b OR', ' '.join(r.context['formular_fehler']))
        v.refresh_from_db()
        self.assertEqual(v.ende, date(2029, 12, 31))
        r = self.post(v, ende='2030-06-30')   # Gegenprobe: länger ist gültig
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.ende, date(2030, 6, 30))

    def test_kuendigungsverzicht_wird_geprueft_und_gespeichert(self):
        v = self.vertrag(ist_befristet=False, ende=None, vermieter_kuendigungsverzicht_bis=date(2029, 12, 31))
        self.assertEqual(self.post(v, vermieter_kuendigungsverzicht_bis='2029-12-30').status_code, 400)
        v.refresh_from_db()
        self.assertEqual(v.vermieter_kuendigungsverzicht_bis, date(2029, 12, 31))
        self.assertEqual(self.post(v, vermieter_kuendigungsverzicht_bis='2031-03-31').status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.vermieter_kuendigungsverzicht_bis, date(2031, 3, 31))

    def test_fehlendes_feld_loescht_den_verzicht_nicht(self):
        v = self.vertrag(ist_befristet=False, ende=None, vermieter_kuendigungsverzicht_bis=date(2029, 12, 31))
        self.assertEqual(self.post(v).status_code, 302)   # Formular ohne das Feld
        v.refresh_from_db()
        self.assertEqual(v.vermieter_kuendigungsverzicht_bis, date(2029, 12, 31))

    def test_altvertrag_ohne_aenderung_am_modell_wird_nicht_blockiert(self):
        v = self.vertrag(ende=date(2028, 12, 31))   # vier Jahre: Altverstoss
        self.assertEqual(self.post(v, ende='2028-12-31', kuendigungsfrist='6').status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.kuendigungsfrist_monate, 6)
        self.assertEqual(self.post(v, ende='2028-12-30').status_code, 400)   # Gegenprobe: Änderung wird geprüft

    def test_indexfeld_bei_festem_mietzins_aendern_wird_nicht_wegen_staffelresten_blockiert(self):
        """Ein fester Vertrag mit übrig gebliebenen Staffelstufen (Altbestand): Eine Weitergabe zu ändern ist
        keine Änderung am Mietzinsmodell. Gegenprobe: Das Ende zu ändern ist es, und wird geprüft."""
        v = self.vertrag(mietzins_modell='fest', ist_befristet=False, ende=None)
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2026, 1, 1), netto_mietzins=Decimal('2050'))
        self.assertEqual(self.post(v, index_weitergabe_prozent='80').status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.index_weitergabe_prozent, Decimal('80'))
        self.assertEqual(self.post(v, ende='2030-01-01').status_code, 400)

class SeitenAufbauTests(WizardBasis):
    def seite(self, **query):
        r = self.c.get('/neu/vertraege/neu/', query)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_drei_kacheln_sind_eine_radiogruppe_und_kein_select(self):
        html = self.seite()
        radios = re.findall(r'<input type="radio" name="mietzins_modell" id="(\w+)" value="(\w+)"( checked)?>', html)
        self.assertEqual([(r[1]) for r in radios], ['fest', 'staffel', 'index'])
        self.assertEqual([r[2] != '' for r in radios], [True, False, False])
        self.assertNotIn('<select name="mietzins_modell"', html)
        # genau eine Gruppe: keine weitere Kontrolle mit diesem Namen
        self.assertEqual(len(re.findall(r'<(?:input|select|textarea)[^>]*name="mietzins_modell"', html)), 3)
        for _id, wert, _c in radios:   # jede Kachel mit Beschriftung zum Radio
            self.assertIn(f'for="mzm_{wert}"', html)

    def test_der_block_gilt_fuer_alle_mietarten(self):
        """Nicht mehr in der Geschäftsraum-Box: Er steht für Wohnung wie für Gewerbe auf der Seite."""
        html = self.seite(einheit=self.e.id)
        gewerbe_box = html[html.index('id="gewerbe-box"'):html.index('id="mzm"')]
        self.assertNotIn('mietzins_modell', gewerbe_box)
        self.assertIn('name="zweckbestimmung"', gewerbe_box)   # die Box behält den Nutzungszweck
        self.assertLess(html.index('id="gewerbe-box"'), html.index('id="mzm"'))

    def test_kein_prozentfeld_bei_den_stufen(self):
        html = self.seite()
        self.assertNotIn('name="staffel_prozent"', html)
        self.assertNotIn('name="staffel_netto"', html)
        # die Stufenzeilen baut das Skript: Erhöhung in CHF
        skript = open('static/js/fw-mietzinsmodell.js', encoding='utf-8').read()
        self.assertIn("'staffel_erhoehung'", skript)
        self.assertNotIn('staffel_prozent', skript)

    def test_index_felder_stehen_nur_im_index_panel(self):
        html = self.seite()
        index = html[html.index('id="mzm-panel-index"'):html.index('id="mzm-befunde"')]
        for name in ('basis_lik_punkte', 'basis_lik_stand', 'index_weitergabe_prozent', 'index_intervall_monate'):
            self.assertEqual(html.count(f'name="{name}"'), 1, name)
            self.assertIn(f'name="{name}"', index)
        self.assertIn('type="month"', index)
        self.assertIn('Landesindex der Konsumentenpreise (BFS)', index)
        self.assertNotRegex(index, r'<select')   # der Index ist fest, kein Auswahlfeld

    def test_kuendigungsverzicht_steht_im_schritt_konditionen(self):
        html = self.seite()
        konditionen = html[html.index("data-schritt=\"Konditionen\""):html.index("data-schritt=\"Mietzins\"")]
        self.assertIn('name="vermieter_kuendigungsverzicht_bis"', konditionen)
        self.assertIn('id="verzicht-box"', konditionen)

    def test_hilfe_an_kacheln_und_feldern(self):
        html = self.seite()
        for titel in ('Fester Mietzins', 'Staffelmiete', 'Indexmiete', 'Index und Staffel zusammen?',
                      'Kündigungsverzicht des Vermieters', 'Weitergabe der Teuerung', 'Mindestintervall'):
            self.assertIn(f'<b>{titel}</b>', html, titel)

    def test_konfiguration_nennt_endpunkt_und_mindestjahre_aus_der_regelquelle(self):
        html = self.seite()
        cfg = json.loads(re.search(r'<script id="mzm-config" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(cfg['url'], reverse('fw_mietzinsmodell_pruefen'))
        self.assertEqual(cfg['jahre'], {'index': 5, 'staffel': 3})

    def test_sperre_im_fuss_und_zeichenvorlagen(self):
        html = self.seite()
        fuss = html[html.index('<div class="fw-assistent-fuss">'):html.index('id="btn-back"')]
        self.assertIn('id="mzm-fuss"', fuss)
        self.assertIn('role="status"', fuss)
        for z in ('loeschen', 'kritisch', 'hinweis'):
            self.assertIn(f'data-mzm-zeichen="{z}"', html)

    def test_rueckgabe_nach_fehler_traegt_modell_und_zeilen(self):
        r = self.speichern(self.staffel(ende='2027-12-30'))
        self.assertEqual(r.status_code, 400)
        html = r.content.decode()
        rueck = json.loads(re.search(r'<script id="rueckgabe-data" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(rueck['mietzins_modell'], ['staffel'])
        self.assertEqual(rueck['staffel_erhoehung'], ['50', '50'])
        self.assertContains(r, 'fw-formfehler', status_code=400)

    def test_vorlage_der_bearbeiten_seite_hat_das_neue_feld(self):
        v = Mietvertrag.objects.create(mieter=self.m, einheit=self.e, beginn=date(2025, 1, 1),
                                       netto_mietzins=Decimal('2000'), nebenkosten=Decimal('0'), status='aktiv')
        html = self.c.get(f'/neu/vertraege/{v.id}/bearbeiten/').content.decode()
        self.assertIn('name="vermieter_kuendigungsverzicht_bis"', html)


class BeispielrechnungTests(TestCase):
    """Die Beispielrechnung im Index-Panel (JS, nur Anzeige) rechnet wie die Anpassung am Server.

    Die Zahlen stehen auch in `e2e/tests/mietzinsmodell-wizard.spec.ts`: Ändert sich die Rechnung oder die
    Rundung hier, schlägt dort die Anzeige an — und umgekehrt.
    """

    def vertrag(self, w):
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Beispielweg 1', plz='8000',
                                         ort='Zürich', versicherungswert=Decimal('1000000'))
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Whg', typ='whg')
        m = Mieter.objects.create(typ='person', nachname='Beispiel')
        return Mietvertrag.objects.create(
            mieter=m, einheit=e, beginn=date(2024, 1, 1), netto_mietzins=Decimal('2000'), nebenkosten=Decimal('0'),
            status='aktiv', mietzins_modell='index', basis_lik_punkte=Decimal('107.0'),
            index_weitergabe_prozent=w)

    def test_zahlen_der_beispielrechnung(self):
        voll = index_anpassung_vorschlag(self.vertrag(Decimal('100')), aktuell_lik=Decimal('108.3'))
        teil = index_anpassung_vorschlag(self.vertrag(Decimal('60')), aktuell_lik=Decimal('108.3'))
        self.assertEqual(voll['neu_netto'], Decimal('2024.30'))   # 2024.2991 auf 5 Rappen
        self.assertEqual(teil['neu_netto'], Decimal('2014.60'))   # 2014.5794 auf 5 Rappen
        self.assertNotEqual(voll['neu_netto'], teil['neu_netto'])
