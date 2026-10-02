"""Schlüsselverzeichnis, Unterschrift als Bild, Fotos und Schlusstexte im PDF, Bauteilname.

Die fünf Punkte, die das Praxisprotokoll (Turmstrasse 5/7) über die reine
Bewertung hinaus hat.
"""
import base64
import io
from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user
from .test_abnahme_kette import _protokoll, _vertrag_nachher


def _png(farbe='black', groesse=(60, 30)):
    from PIL import Image
    buf = io.BytesIO(); Image.new('RGB', groesse, farbe).save(buf, 'PNG')
    return buf.getvalue()


def _jpeg(groesse=(40, 30)):
    from PIL import Image
    buf = io.BytesIO(); Image.new('RGB', groesse, 'red').save(buf, 'JPEG')
    return buf.getvalue()


def _data_url(roh, mime='image/png'):
    return f'data:{mime};base64,' + base64.b64encode(roh).decode()


def _pdf_seiten(prot):
    import pdfplumber
    from core.services.abnahme_pdf import generate_abnahme_pdf
    with pdfplumber.open(io.BytesIO(generate_abnahme_pdf(prot))) as d:
        return [(s.extract_text() or '', len(s.images)) for s in d.pages]


class Basis(TestCase):
    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()
        self.c = Client(); self.c.force_login(_team_user())
        self.url = f'/neu/vertraege/{self.v1.id}/abnahme/vorort/'

    def _register(self):
        from portfolio.models import Schluessel
        Schluessel.objects.create(liegenschaft=self.lg, einheit=self.einheit, typ='Haus-/Wohnungstüre',
                                  schluessel_nummer='Kaba 20 BW51703201/1,2,4', anzahl=3)
        Schluessel.objects.create(liegenschaft=self.lg, einheit=self.einheit, typ='Briefkasten',
                                  schluessel_nummer='DOM 5A 340', anzahl=2)
        Schluessel.objects.create(liegenschaft=self.lg, einheit=None, typ='Waschküche',
                                  schluessel_nummer='Karte ZUG', anzahl=1)

    def _start(self, typ='auszug', raeume=('Keller',)):
        from rentals.models import Abnahmeprotokoll
        self.c.post(self.url, {'typ': typ, 'raum': list(raeume)})
        # «beides» legt das Auszugsprotokoll an (das Einzugsprotokoll entsteht erst beim Abschluss)
        return Abnahmeprotokoll.objects.filter(vertrag=self.v1, typ='auszug' if typ == 'beides' else typ).latest('id')

    def _abschliessen(self, prot, **daten):
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', daten, follow=False)


class SchluesselTests(Basis):

    def test_vorbelegung_aus_dem_register_der_einheit_und_der_liegenschaft(self):
        self._register()
        prot = self._start()
        self.assertEqual([(z.bezeichnung, z.anlage, z.soll, z.ist) for z in prot.schluessel.all()], [
            ('Haus-/Wohnungstüre', 'Kaba 20 BW51703201/1,2,4', 3, None),
            ('Briefkasten', 'DOM 5A 340', 2, None),
            ('Waschküche', 'Karte ZUG', 1, None)])

    def test_ohne_register_ist_das_verzeichnis_leer_und_ergaenzbar(self):
        prot = self._start()
        self.assertEqual(prot.schluessel.count(), 0)
        self._abschliessen(prot, s_bezeichnung=['Wohnung'], s_anlage=[''], s_soll=['2'], s_ist=['2'])
        self.assertEqual(prot.schluessel.get().soll, 2)

    def test_abschluss_speichert_ist_und_rechnet_fehlend(self):
        self._register()
        prot = self._start()
        zeilen = list(prot.schluessel.all())
        self._abschliessen(
            prot, s_bezeichnung=[z.bezeichnung for z in zeilen], s_anlage=[z.anlage for z in zeilen],
            s_soll=['3', '2', '1'], s_ist=['3', '1', ''])
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        gespeichert = list(prot.schluessel.all())
        self.assertEqual([z.fehlend for z in gespeichert], [0, 1, None])   # None = nicht gezählt, 0 = vollständig
        self.assertEqual(prot.schluessel_anzahl, 4)                         # Summe der gezählten

    def test_schluesselpendenz_beim_auszug_bleibt_abhakbar(self):
        self._register()
        prot = self._start()
        self._abschliessen(prot, s_bezeichnung=['Wohnung'], s_anlage=[''], s_soll=['3'], s_ist=['3'])
        prot.refresh_from_db()
        self.assertEqual(prot.schluessel_anzahl, 3)      # daran hängt erledige_pendenzen_fuer(['Schlüssel'])

    def test_leere_zeilen_ungueltige_zahlen_und_zuviele_zeilen(self):
        prot = self._start()
        self._abschliessen(prot, s_bezeichnung=['  Keller  ', '', 'Estrich'], s_anlage=['', '', ''],
                           s_soll=['abc', '5', '-1'], s_ist=['x', '', '99999'])
        z = list(prot.schluessel.all())
        self.assertEqual([(a.bezeichnung, a.soll, a.ist) for a in z], [('Keller', 0, None), ('Estrich', 0, None)])
        prot2 = self._start(typ='einzug')
        self._abschliessen(prot2, s_bezeichnung=[f'S{i}' for i in range(50)], s_soll=['1'] * 50, s_ist=['1'] * 50)
        self.assertEqual(prot2.schluessel.count(), 30)

    def test_vorgaenger_liefert_soll_und_ist_wird_neu_gezaehlt(self):
        from rentals.models import AbnahmeSchluessel
        alt = _protokoll(self.v1, 'einzug', date(2021, 3, 1), [('Keller', 'Boden', 'io', '')])
        AbnahmeSchluessel.objects.create(protokoll=alt, bezeichnung='Wohnung', anlage='A1', soll=4, ist=4)
        self.c.post(self.url, {'typ': 'auszug', 'datum': '2026-06-30', 'vorlage': 'vorgaenger', 'raum': ['Keller']})
        from rentals.models import Abnahmeprotokoll
        neu = Abnahmeprotokoll.objects.get(typ='auszug')
        self.assertEqual([(z.bezeichnung, z.soll, z.ist) for z in neu.schluessel.all()], [('Wohnung', 4, None)])

    def test_einzug_aus_auszug_uebernimmt_das_verzeichnis_mit_ist(self):
        _vertrag_nachher(self.einheit)
        self._register()
        prot = self._start(typ='beides')
        zeilen = list(prot.schluessel.all())
        self._abschliessen(prot, s_bezeichnung=[z.bezeichnung for z in zeilen], s_anlage=[z.anlage for z in zeilen],
                           s_soll=['3', '2', '1'], s_ist=['3', '2', '1'])
        from rentals.models import Abnahmeprotokoll
        ein = Abnahmeprotokoll.objects.get(typ='einzug')
        self.assertEqual([(z.bezeichnung, z.soll, z.ist) for z in ein.schluessel.all()],
                         [('Haus-/Wohnungstüre', 3, 3), ('Briefkasten', 2, 2), ('Waschküche', 1, 1)])

    def test_seite_zeigt_zeilen_und_vorlage(self):
        self._register()
        prot = self._start()
        r = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1')
        self.assertContains(r, 'Kaba 20 BW51703201/1,2,4')
        self.assertContains(r, 'voSchTpl')

    def test_altes_formularfeld_schluessel_anzahl_funktioniert_weiter(self):
        prot = self._start()
        self._abschliessen(prot, schluessel_anzahl='5')
        prot.refresh_from_db()
        self.assertEqual(prot.schluessel_anzahl, 5)


class UnterschriftTests(Basis):

    def test_gueltige_unterschrift_wird_bei_der_verwaltung_abgelegt(self):
        prot = self._start()
        self._abschliessen(prot, unterschrift_mieter='Hans Muster',
                           unterschrift_mieter_bild=_data_url(_png()),
                           unterschrift_verwalter_bild=_data_url(_png('blue')))
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        for feld in (prot.unterschrift_mieter_bild, prot.unterschrift_verwalter_bild):
            self.assertTrue(feld.name.startswith(f'organisation/{prot.organisation_id}/'), feld.name)
            self.assertTrue(feld.name.endswith('.png'))
        self.assertEqual(prot.unterschrift_mieter_bild.read()[:8], b'\x89PNG\r\n\x1a\n')

    def test_ohne_unterschrift_bleibt_der_name_und_der_abschluss_geht(self):
        prot = self._start()
        self._abschliessen(prot, unterschrift_mieter='Hans Muster')
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        self.assertFalse(prot.unterschrift_mieter_bild)

    def test_ungueltige_eingaben_werden_abgelehnt_und_schliessen_nichts_ab(self):
        from rentals.models import Abnahmeprotokoll
        faelle = {
            'jpeg statt png': _data_url(_jpeg(), 'image/jpeg'),
            'png-etikett mit jpeg-inhalt': _data_url(_jpeg()),
            'kein base64': 'data:image/png;base64,@@@@',
            'kein bild': _data_url(b'<script>alert(1)</script>'),
            'svg': 'data:image/svg+xml;base64,' + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode(),
            'fremde url': 'https://example.com/x.png',
            'zu gross': _data_url(_png(groesse=(2500, 100))),
            'zu schwer': _data_url(_png() + b'0' * (800 * 1024)),
        }
        for name, eingabe in faelle.items():
            prot = self._start(typ='auszug')
            r = self._abschliessen(prot, unterschrift_mieter_bild=eingabe)
            self.assertEqual(r.status_code, 302, name)
            self.assertIn('?r=', r['Location'], name)               # zurück zum Abschluss-Schritt
            prot = Abnahmeprotokoll.objects.get(id=prot.id)
            self.assertFalse(prot.abgeschlossen, name)
            self.assertFalse(prot.unterschrift_mieter_bild, name)
            prot.delete()

    def test_meldung_bei_ungueltiger_unterschrift(self):
        prot = self._start()
        r = self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/',
                        {'unterschrift_verwalter_bild': 'nonsense'}, follow=True)
        self.assertContains(r, 'Unterschrift konnte nicht gelesen werden')

    def test_detailseite_zeigt_die_unterschrift(self):
        prot = self._start()
        self._abschliessen(prot, unterschrift_mieter='Hans Muster', unterschrift_mieter_bild=_data_url(_png()))
        r = self.c.get(f'/neu/abnahme/{prot.id}/')
        self.assertContains(r, 'ab-unterschrift')
        self.assertContains(r, 'Hans Muster')

    def test_abgeschlossenes_protokoll_nimmt_keine_zweite_unterschrift_an(self):
        prot = self._start()
        self._abschliessen(prot, unterschrift_mieter_bild=_data_url(_png()))
        prot.refresh_from_db()
        erste = prot.unterschrift_mieter_bild.name
        self._abschliessen(prot, unterschrift_mieter_bild=_data_url(_png('red')))
        prot.refresh_from_db()
        self.assertEqual(prot.unterschrift_mieter_bild.name, erste)


class BezeichnungTests(Basis):

    def _position(self, prot, name='Boden'):
        return prot.positionen.get(bezeichnung=name)

    def _speichern(self, prot, pos, **d):
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/position/', {'position': pos.id, **d})

    def test_bauteilname_aendern(self):
        prot = self._start()
        pos = self._position(prot)
        r = self._speichern(prot, pos, bezeichnung='  Boden  ( Vinyl   Steinoptik ) ')
        self.assertEqual(r.json()['bezeichnung'], 'Boden ( Vinyl Steinoptik )')
        pos.refresh_from_db()
        self.assertEqual(pos.bezeichnung, 'Boden ( Vinyl Steinoptik )')

    def test_leerer_name_wird_abgelehnt_und_zu_langer_gekuerzt(self):
        prot = self._start()
        pos = self._position(prot)
        self.assertEqual(self._speichern(prot, pos, bezeichnung='   ').status_code, 400)
        self._speichern(prot, pos, bezeichnung='x' * 300)
        pos.refresh_from_db()
        self.assertEqual(len(pos.bezeichnung), 120)

    def test_name_steht_auf_der_seite_im_mangel_und_im_pdf(self):
        prot = self._start()
        pos = self._position(prot, 'Wände')
        self._speichern(prot, pos, bezeichnung='Wände (Raufaser)', zustand='uebermaessig', kosten='100')
        self._speichern(prot, pos, bezeichnung='Wände (Raufaser, gestrichen)')
        pos.refresh_from_db()
        self.assertEqual(pos.mangel.beschreibung, 'Wände (Raufaser, gestrichen)')   # Mangel zieht nach
        self.assertContains(self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=0'), 'Wände (Raufaser, gestrichen)')
        text = '\n'.join(t for t, _ in _pdf_seiten(prot))
        self.assertIn('Raufaser, gestrichen', text)

    def test_abgeschlossen_und_fremdes_protokoll(self):
        prot = self._start()
        pos = self._position(prot)
        self._abschliessen(prot)
        self.assertEqual(self._speichern(prot, pos, bezeichnung='Neu').status_code, 409)


class PdfUnterlagenTests(Basis):

    def _mit_fotos(self, n=3):
        prot = self._start(raeume=('Küche',))
        for pos in list(prot.positionen.all())[:n]:
            pos.foto.save('f.jpg', ContentFile(_jpeg()))
            pos.save()
        return prot

    def test_bilder_abschnitt_mit_nummer_und_raum(self):
        prot = self._mit_fotos(3)
        seiten = _pdf_seiten(prot)
        text_letzte, bilder_letzte = seiten[-1]
        self.assertIn('Bilder', text_letzte)
        self.assertIn('Küche', text_letzte)
        self.assertIn('1 Boden', text_letzte)
        self.assertIn('3 Wände', text_letzte)
        self.assertEqual(bilder_letzte, 3)

    def test_ohne_fotos_kein_bilder_abschnitt(self):
        prot = self._start(raeume=('Küche',))
        self.assertFalse(any('Bilder' in t.split('\n')[0] for t, _ in _pdf_seiten(prot)))

    def test_nummern_der_tabelle_und_der_bilder_stimmen_ueberein(self):
        prot = self._start(raeume=('Küche',))
        backofen = prot.positionen.get(bezeichnung='Backofen')
        backofen.foto.save('b.jpg', ContentFile(_jpeg())); backofen.save()
        nr = list(prot.positionen.values_list('id', flat=True)).index(backofen.id) + 1
        text = '\n'.join(t for t, _ in _pdf_seiten(prot))
        self.assertIn(f'{nr} Backofen', text)                         # Bildunterschrift
        self.assertRegex(text, rf'(?m)^{nr} Küche +Backofen')          # Tabellenzeile

    def test_unlesbares_foto_verhindert_das_pdf_nicht(self):
        prot = self._mit_fotos(2)
        pos = prot.positionen.exclude(foto='').first()
        pos.foto.storage.delete(pos.foto.name)                        # Datei weg, Datenbankeintrag bleibt
        seiten = _pdf_seiten(prot)
        self.assertEqual(seiten[-1][1], 1)                            # das andere Foto ist da

    def test_viele_fotos_laufen_ueber_mehrere_seiten(self):
        prot = self._mit_fotos(22)                                   # alle 22 Bauteile der Küche
        seiten = _pdf_seiten(prot)
        self.assertEqual(sum(b for _, b in seiten), 22)
        self.assertGreaterEqual(sum(1 for _, b in seiten if b), 3)   # mehr als eine Seite voller Bilder

    def test_schluesselverzeichnis_im_pdf_mit_fortlaufender_nummer(self):
        from rentals.models import AbnahmeSchluessel
        prot = self._start(raeume=('Keller',))
        AbnahmeSchluessel.objects.create(protokoll=prot, bezeichnung='Briefkasten', anlage='DOM 5A 340', soll=2, ist=1)
        text = '\n'.join(t for t, _ in _pdf_seiten(prot))
        self.assertIn('Schlüsselverzeichnis', text)
        self.assertRegex(text, r'(?m)^6 Briefkasten DOM 5A 340 +2 +1 +1')   # Keller hat 5 Bauteile → Nr. 6

    def test_unterschrift_als_bild_im_pdf(self):
        prot = self._start(raeume=('Keller',))
        self._abschliessen(prot, unterschrift_mieter='Hans Muster', unterschrift_mieter_bild=_data_url(_png()),
                           unterschrift_verwalter_bild=_data_url(_png('blue')))
        prot.refresh_from_db()
        seiten = _pdf_seiten(prot)
        self.assertEqual(sum(b for _, b in seiten), 2)
        self.assertIn('Hans Muster', '\n'.join(t for t, _ in seiten))

    def test_schlussbestimmungen_je_art_und_nur_mit_maengeln_die_ruege(self):
        from core.services import abnahme_texte as T
        auszug = self._start(raeume=('Keller',))
        text = ' '.join('\n'.join(t for t, _ in _pdf_seiten(auszug)).split())
        self.assertIn('Schlussbestimmungen', text)
        self.assertIn(T.HAFTUNG[:60], text)
        self.assertIn('Mietzinsdepot', text)
        self.assertNotIn('Mängelrüge', text)                          # kein Mieter-Mangel → keine Rüge
        pos = auszug.positionen.first()
        self.c.post(f'/neu/abnahme/{auszug.id}/vorort/position/', {'position': pos.id, 'zustand': 'uebermaessig', 'kosten': '50'})
        text = ' '.join('\n'.join(t for t, _ in _pdf_seiten(auszug)).split())
        self.assertIn('Art. 267a OR', text)
        self.assertIn('Kostenübernahme', text)
        einzug = self._start(typ='einzug', raeume=('Keller',))
        text = ' '.join('\n'.join(t for t, _ in _pdf_seiten(einzug)).split())
        self.assertIn('innert 10 Tagen', text)
        self.assertNotIn('Mietzinsdepot', text)
        self.assertNotIn('Art. 267a', text)

    def test_ueberschriften_stehen_nie_allein_am_seitenende(self):
        """Die Tabelle endet je nach Zeilenzahl auf jeder Höhe: durch eine ganze Seitenhöhe fahren."""
        import pdfplumber
        from core.services.abnahme_pdf import generate_abnahme_pdf
        from rentals.models import AbnahmePosition, AbnahmeSchluessel
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Raum', 'Bauteil 000', 'io', '')], abgeschlossen=False)
        AbnahmeSchluessel.objects.create(protokoll=prot, bezeichnung='Schlüssel 0', soll=1, ist=1)
        for extra in range(1, 60):
            AbnahmePosition.objects.create(protokoll=prot, raum='Raum', bezeichnung=f'Extra {extra}',
                                           kommentar='Kommentar ' * (1 + (extra % 3) * 2), sortierung=extra)
            with pdfplumber.open(io.BytesIO(generate_abnahme_pdf(prot))) as d:
                for seite in d.pages:
                    zeilen = (seite.extract_text() or '').split('\n')
                    if 'Schlüsselverzeichnis' in zeilen:
                        self.assertIn('Schlüssel 0', '\n'.join(zeilen), f'{extra}: Überschrift allein am Seitenende')
                    if 'Bewertete Bauteile' in zeilen:
                        self.assertIn('Bauteil 000', '\n'.join(zeilen), f'{extra}: Überschrift allein am Seitenende')

    def test_nichts_ueberlappt_und_nichts_steht_ausserhalb_des_seitenrands(self):
        """Tabelle, Schlüssel, Bemerkungen, Schlusstexte und Unterschrift laufen im Fluss.

        Die Endhöhe der Tabelle bestimmt, wo die folgenden Abschnitte beginnen;
        deshalb werden Schlüsselzeilen und Bemerkungszeilen fein variiert, damit
        jede Seitenumbruch-Stelle einmal knapp getroffen wird. Geprüft: kein
        Wort über einem anderen, und alles liegt über dem unteren Rand."""
        import pdfplumber
        from reportlab.lib.units import mm
        from core.services.abnahme_pdf import generate_abnahme_pdf
        from rentals.models import AbnahmeSchluessel
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30),
                          [('Raum', f'Bauteil {i:03d}', 'io', 'Kommentar ' * (i % 4)) for i in range(48)],
                          abgeschlossen=False)               # offen: sonst lehnt der Endpunkt die Änderung ab
        r = self.c.post(f'/neu/abnahme/{prot.id}/vorort/position/',
                        {'position': prot.positionen.first().id, 'zustand': 'uebermaessig', 'kosten': '10'})
        self.assertEqual(r.status_code, 200)                 # → Mieter-Mangel → langer Rüge-Absatz im PDF
        self.assertTrue(prot.maengel_mieter)
        from rentals.models import AbnahmePosition
        geprueft = 0
        for extra in range(3):
            # Zeilen mit 1–3 Kommentarzeilen verschieben die Endhöhe der Tabelle in kleinen Schritten
            AbnahmePosition.objects.create(protokoll=prot, raum='Raum', bezeichnung=f'Extra {extra}',
                                           kommentar='Kommentar ' * (1 + (extra * 2) % 3 * 2), sortierung=100 + extra)
            for schluessel in (2,):
                prot.schluessel.all().delete()
                for k in range(schluessel):
                    AbnahmeSchluessel.objects.create(protokoll=prot, bezeichnung=f'Schlüssel {k}', soll=1, ist=1)
                for zeilen in range(0, 46):               # über eine volle Seitenhöhe
                    prot.bemerkungen = '\n'.join(f'Bemerkung Zeile {k}.' for k in range(zeilen))
                    prot.save()
                    with pdfplumber.open(io.BytesIO(generate_abnahme_pdf(prot))) as d:
                        for seite in d.pages:
                            text = seite.extract_text() or ''
                            # Keine Waisen: Eine Überschrift steht mit ihrer ersten Zeile auf derselben Seite
                            for ueberschrift, erste_zeile in (('Schlüsselverzeichnis', 'Schlüssel 0'),
                                                              ('Schlussbestimmungen', 'Kostenübernahme'),
                                                              ('Bewertete Bauteile', 'Bauteil 000')):
                                if ueberschrift in text.split('\n'):
                                    self.assertIn(erste_zeile, text,
                                                  f"{extra}/{schluessel}/{zeilen}: «{ueberschrift}» steht allein am Seitenende")
                            woerter = seite.extract_words()
                            for w in woerter:
                                self.assertLessEqual(w['bottom'], seite.height - 24 * mm,
                                                     f"{extra}/{schluessel}/{zeilen}: «{w['text']}» steht im unteren Rand")
                            for i, a in enumerate(woerter):
                                for b in woerter[i + 1:]:
                                    ox = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
                                    oy = min(a['bottom'], b['bottom']) - max(a['top'], b['top'])
                                    self.assertFalse(ox > 1 and oy > 1,
                                                     f"{extra}/{schluessel}/{zeilen}: «{a['text']}» überlappt «{b['text']}»")
                    geprueft += 1
        self.assertEqual(geprueft, 3 * 1 * 46)
