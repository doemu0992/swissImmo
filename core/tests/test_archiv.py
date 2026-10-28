"""Archiv und Mandatsende statt hartes Löschen (Etappe 2; FUNK-03, FIN-16, FUNK-10).

Geprüft: archivieren/wiederherstellen für die Typen, Aufbewahrungsfrist
(31.12. des zehnten Jahres), Löschsperre während der Frist, endgültiges Löschen
erst danach, Ausblenden aus den Arbeitslisten, Schliessen der harten Löschwege
(Dokument, Schadenmeldung, STWEG-Dokument), Mandantentrennung und Rollen.

GEGENPROBEN (28.10.2026): siehe Schlussbericht, je Test eine Zeile.
"""
from datetime import date, timedelta

from django.test import Client
from django.utils import timezone

from core.models import Archiveintrag
from core.services import archiv
from core.services.loeschschutz import hindernisse

from .test_loeschschutz import LoeschBasis


class ArchivDienstTests(LoeschBasis):

    def test_liegenschaft_archivieren_und_wiederherstellen(self):
        lg = self.neue_liegenschaft()
        e = archiv.archivieren(lg, user=self.a.benutzer, grund='Verkauf')
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'archiviert')
        self.assertEqual(e.aufbewahren_bis, date(timezone.localdate().year + 10, 12, 31))
        self.assertEqual(e.grund, 'Verkauf')
        self.assertTrue(archiv.ist_archiviert(lg))
        archiv.wiederherstellen(lg)
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'aktiv')
        self.assertFalse(archiv.ist_archiviert(lg))

    def test_laufender_vertrag_verhindert_das_archivieren(self):
        v = self.neuer_vertrag(status='aktiv')
        for objekt in (v.einheit.liegenschaft, v.einheit, v.mieter):
            with self.subTest(typ=objekt._meta.label), self.assertRaises(archiv.ArchivFehler):
                archiv.archivieren(objekt)
            self.assertFalse(archiv.ist_archiviert(objekt))

    def test_beendete_person_und_objekt_lassen_sich_archivieren(self):
        v = self.neuer_vertrag(status='archiviert')
        archiv.archivieren(v.mieter)
        archiv.archivieren(v.einheit)
        self.assertEqual(Archiveintrag.objects.count(), 2)

    def test_doppelt_archivieren_und_nicht_archiviertes_wiederherstellen_scheitern(self):
        lg = self.neue_liegenschaft()
        with self.assertRaises(archiv.ArchivFehler):
            archiv.wiederherstellen(lg)
        archiv.archivieren(lg)
        with self.assertRaises(archiv.ArchivFehler):
            archiv.archivieren(lg)

    def test_mandat_beenden_braucht_archivierte_liegenschaften(self):
        from portfolio.models import Liegenschaft
        md = self.a.eigentuemer
        Liegenschaft.objects.filter(eigentuemer=md).exclude(pk=self.a.liegenschaft.pk).delete()
        with self.assertRaises(archiv.ArchivFehler) as ctx:
            archiv.archivieren(md)
        self.assertIn('Liegenschaften', str(ctx.exception))

    def test_vertrag_archiv_wiederherstellen_geht_auf_gekuendigt_nie_auf_aktiv(self):
        v = self.neuer_vertrag(status='gekuendigt')
        archiv.archivieren(v)
        v.refresh_from_db()
        self.assertEqual((v.status, v.aktiv), ('archiviert', False))
        archiv.wiederherstellen(v)
        v.refresh_from_db()
        self.assertEqual((v.status, v.aktiv), ('gekuendigt', False))


class LoeschsperreFristTests(LoeschBasis):

    def test_archiviertes_objekt_ist_bis_zum_fristende_nicht_loeschbar(self):
        lg = self.neue_liegenschaft()
        archiv.archivieren(lg)
        h = dict(hindernisse(lg))
        self.assertTrue(any('Aufbewahrungsfrist' in name for name in h))
        antwort = self.loeschen('liegenschaften', lg)
        self.assertTrue(self.gibt_es(lg))
        self.assertIn('Aufbewahrungsfrist', self.text(antwort))

    def test_endgueltig_loeschen_erst_nach_der_frist(self):
        m = self.neuer_mieter()
        archiv.archivieren(m)
        with self.assertRaises(archiv.ArchivFehler):
            archiv.endgueltig_loeschen(m)
        self.assertTrue(self.gibt_es(m))
        Archiveintrag.objects.filter(objekt_id=m.pk).update(aufbewahren_bis=timezone.localdate() - timedelta(days=1))
        archiv.endgueltig_loeschen(m)
        self.assertFalse(self.gibt_es(m))
        self.assertFalse(Archiveintrag.objects.filter(objekt_id=m.pk, typ='crm.Mieter').exists())

    def test_endgueltig_loeschen_haelt_an_hängenden_geschaeftsunterlagen(self):
        from core.services.loeschschutz import LoeschSperre
        v = self.neuer_vertrag(status='archiviert')
        archiv.archivieren(v.mieter)
        Archiveintrag.objects.update(aufbewahren_bis=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(LoeschSperre):
            archiv.endgueltig_loeschen(v.mieter)       # der Vertrag hängt noch daran
        self.assertTrue(self.gibt_es(v.mieter))

    def test_nicht_archiviertes_endgueltig_loeschen_scheitert(self):
        with self.assertRaises(archiv.ArchivFehler):
            archiv.endgueltig_loeschen(self.neuer_mieter())


class HarteLoeschwegeTests(LoeschBasis):

    def test_dokument_loeschen_archiviert_nur(self):
        from rentals.models import Dokument
        d = Dokument.objects.create(mieter=self.a.mieter, datei='dok/x.pdf', kategorie='sonstiges')
        self.c.post(f'/neu/dokument/{d.pk}/loeschen/')
        self.assertTrue(self.gibt_es(d), 'Das Dokument wurde hart gelöscht.')
        self.assertTrue(archiv.ist_archiviert(d))

    def test_ablage_dokument_loeschen_archiviert_nur(self):
        from portfolio.models import Dokument
        d = Dokument.objects.create(titel='Plan', kategorie='sonstiges', liegenschaft=self.a.liegenschaft,
                                    datei='dok/p.pdf')
        self.c.post(f'/neu/dokumente/{d.pk}/loeschen/')
        self.assertTrue(self.gibt_es(d))
        self.assertTrue(archiv.ist_archiviert(d))

    def test_schaden_loeschen_archiviert_nur_und_blendet_aus(self):
        from tickets.models import SchadenMeldung
        s = SchadenMeldung.objects.filter(liegenschaft=self.a.liegenschaft).first()
        self.assertIsNotNone(s)
        self.c.post(f'/neu/schaeden/{s.pk}/loeschen/')
        self.assertTrue(self.gibt_es(s))
        self.assertTrue(archiv.ist_archiviert(s))
        self.assertNotIn(s.pk, [t.pk for t in archiv.ausblenden(SchadenMeldung.objects.all())])

    def test_stweg_dokument_loeschen_archiviert_nur(self):
        from datetime import date as _d

        from stweg.models import StwegDokument
        d = StwegDokument.objects.create(liegenschaft=self.a.liegenschaft, titel='Reglement',
                                         kategorie=StwegDokument.KATEGORIE_CHOICES[0][0],
                                         gueltig_ab=_d(2025, 1, 1), datei='dok/r.pdf')
        antwort = self.c.post(f'/neu/stweg/dokument/{d.pk}/loeschen/')
        self.assertIn(antwort.status_code, (302, 200))
        self.assertTrue(self.gibt_es(d))
        self.assertTrue(archiv.ist_archiviert(d))


class ArchivAnsichtTests(LoeschBasis):

    def test_archivieren_und_wiederherstellen_ueber_die_oberflaeche(self):
        lg = self.neue_liegenschaft()
        antwort = self.c.post(f'/neu/archiv/liegenschaft/{lg.pk}/archivieren/', {'grund': 'Test'}, follow=True)
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(archiv.ist_archiviert(lg))
        seite = self.c.get('/neu/archiv/')
        self.assertContains(seite, lg.strasse)
        self.c.post(f'/neu/archiv/liegenschaft/{lg.pk}/wiederherstellen/')
        self.assertFalse(archiv.ist_archiviert(lg))

    def test_leeres_archiv_zeigt_den_leeren_zustand(self):
        self.assertContains(self.c.get('/neu/archiv/'), 'Das Archiv ist leer')

    def test_mandat_beenden_setzt_das_mandatsende(self):
        from portfolio.models import Liegenschaft
        md = self.a.eigentuemer
        from rentals.models import Mietvertrag
        Mietvertrag.objects.update(status='archiviert')
        for lg in Liegenschaft.objects.filter(eigentuemer=md):
            archiv.archivieren(lg)
        self.c.post(f'/neu/archiv/mandat/{md.pk}/archivieren/', {'mandatsende': '2026-12-31'})
        e = Archiveintrag.objects.get(typ='crm.Eigentuemer', objekt_id=md.pk)
        self.assertEqual(e.mandatsende, date(2026, 12, 31))

    def test_archivierte_person_verschwindet_aus_der_personenliste(self):
        m = self.neuer_mieter()
        self.assertContains(self.c.get('/neu/personen/'), 'Leer')
        archiv.archivieren(m)
        self.assertNotContains(self.c.get('/neu/personen/'), f'/neu/personen/{m.pk}/')

    def test_vertragsstatus_archiviert_legt_den_eintrag_an_und_aktiv_nimmt_ihn_zurueck(self):
        v = self.neuer_vertrag(status='gekuendigt')
        self.c.post(f'/neu/vertraege/{v.pk}/status/', {'status': 'archiviert'})
        self.assertTrue(archiv.ist_archiviert(v))
        v.refresh_from_db()
        self.assertEqual(v.status, 'archiviert')
        self.c.post(f'/neu/vertraege/{v.pk}/status/', {'status': 'entwurf'})
        self.assertFalse(archiv.ist_archiviert(v))

    def test_fremde_id_ergibt_404(self):
        for aktion in ('archivieren', 'wiederherstellen', 'loeschen'):
            with self.subTest(aktion=aktion):
                antwort = self.c.post(f'/neu/archiv/liegenschaft/{self.b.liegenschaft.pk}/{aktion}/')
                self.assertEqual(antwort.status_code, 404)
        self.assertFalse(Archiveintrag.alle_organisationen.filter(organisation=self.b.organisation).exists())

    def test_get_archiviert_nichts(self):
        lg = self.neue_liegenschaft()
        self.assertEqual(self.c.get(f'/neu/archiv/liegenschaft/{lg.pk}/archivieren/').status_code, 405)
        self.assertFalse(archiv.ist_archiviert(lg))

    def test_rollen(self):
        from core.tests._helfer import _team_user
        lg = self.neue_liegenschaft()
        lesend = Client()
        lesend.force_login(_team_user('Lesend'))
        self.assertEqual(lesend.post(f'/neu/archiv/liegenschaft/{lg.pk}/archivieren/').status_code, 403)
        sach = Client()
        sach.force_login(_team_user('Sachbearbeitung'))
        # Sachbearbeitung archiviert Dokumente (wie vorher löschen), aber keine Liegenschaften.
        self.assertEqual(sach.post(f'/neu/archiv/liegenschaft/{lg.pk}/archivieren/').status_code, 403)
        self.assertFalse(archiv.ist_archiviert(lg))
