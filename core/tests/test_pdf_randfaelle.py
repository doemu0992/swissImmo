"""Randfälle der PDF-Erzeugung — Zeichensatz, Schweizer Betragsformat, leere Variablen.

Anlass: Prüfung der Dokumentenerzeugung vom 30.09.2026 (core/services/pdf_text.py).

Die Tests lesen den Text aus dem fertigen PDF zurück (pdfplumber). Geprüft wird
also, was der Mieter auf Papier sieht, nicht, was im Quelltext steht.

Sichtprüfung: Mit `PDF_DUMP_DIR=testpdfs python manage.py test core.tests.test_pdf_randfaelle`
schreibt `test_testpdfs_fuer_die_sichtpruefung` von jedem Dokument ein PDF in diesen Ordner.
"""
import io
import os
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from core.services.pdf_text import PdfFehler, format_chf, html_zu_pdf, pdf_sicher
from ._helfer import (_test_organisation, Mieter, Eigentuemer, Liegenschaft,
                      Einheit, Mietvertrag)


def _text(pdf):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as seiten:
        return "\n".join((s.extract_text() or '') for s in seiten.pages)


def _flach(pdf):
    """Text ohne Zeilenumbrüche/Mehrfachleerzeichen (Umbrüche trennen sonst Wörter)."""
    return ' '.join(_text(pdf).split())


class FormatChfTests(TestCase):
    def test_schweizer_format(self):
        faelle = {
            Decimal('1250.50'): "1'250.50", 1250.5: "1'250.50", '1250.5': "1'250.50",
            0: '0.00', Decimal('0'): '0.00', Decimal('1234567.891'): "1'234'567.89",
            Decimal('-1250.5'): "-1'250.50", Decimal('999.995'): "1'000.00",
            "1'250.50": "1'250.50", '12': '12.00',
        }
        for wert, erwartet in faelle.items():
            self.assertEqual(format_chf(wert), erwartet, repr(wert))

    def test_kaufmaennisch_gerundet(self):
        # format(Decimal('0.125'), '.2f') ergäbe 0.12 (HALF_EVEN)
        self.assertEqual(format_chf(Decimal('0.125')), '0.13')
        self.assertEqual(format_chf(Decimal('2.675')), '2.68')

    def test_luecke_ist_keine_null(self):
        self.assertEqual(format_chf(None), '')
        self.assertEqual(format_chf(''), '')
        self.assertEqual(format_chf('abc'), '')
        self.assertEqual(format_chf(float('nan')), '')
        self.assertEqual(format_chf(None, leer='–'), '–')
        self.assertEqual(format_chf(0), '0.00')          # 0 ist ein Wert

    def test_kein_minus_null(self):
        self.assertEqual(format_chf(Decimal('-0.001')), '0.00')

    def test_filter_in_der_vorlage(self):
        from django.template import Context, Template
        t = Template('{% load chf %}CHF {{ a|chf }}|{{ b|chf }}|{{ c|chf:0 }}|{{ d|chf }}')
        self.assertEqual(t.render(Context({'a': Decimal('1250.5'), 'b': None, 'c': 1250.5, 'd': 0})),
                         "CHF 1'250.50||1'251|0.00")


class ZeichensatzTests(TestCase):
    def test_umlaute_und_romanische_zeichen_bleiben(self):
        s = "äöüÄÖÜ éèêë àâ ç ì ò ù ñ ß œ Ø € ’ – • « »"
        self.assertEqual(pdf_sicher(s), s)

    def test_fremde_zeichen_werden_ersetzt_statt_salat(self):
        self.assertEqual(pdf_sicher('Łukasz Żółć'), 'Lukasz Zólc')      # ó ist Latin-1 und bleibt
        self.assertEqual(pdf_sicher('Şahin Őrs Čapek'), 'Sahin Ors Capek')
        self.assertEqual(pdf_sicher('Haus ☃ 😀'), 'Haus ? ?')
        self.assertEqual(pdf_sicher('a b'), 'a b')

    def test_reportlab_standardschrift_ist_geschuetzt(self):
        """Gegenprobe: OHNE den Schutz wird daraus «nukasz» (belegt 30.09.2026)."""
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.setFont('Helvetica', 12)
        c.drawString(50, 700, 'Łukasz Żółć Müller Genève')
        c.save()
        t = _text(buf.getvalue())
        self.assertIn('Lukasz Zólc Müller Genève', t)
        self.assertNotIn('nukasz', t)


class _Basis(TestCase):
    def _vertrag(self, *, name='Müller-Lefèvre Çelik', vor='François', ort='Genève',
                 strasse='Rue de l’Église 5', bez='3. OG links', typ='whg',
                 mitmieter='', eigentuemer=None):
        org = _test_organisation()
        lg = Liegenschaft.objects.create(organisation=org, strasse=strasse or 'Hauptstrasse 1', plz='1204',
                                         ort=ort or 'Bern', versicherungswert=Decimal('1000000'),
                                         eigentuemer=eigentuemer)
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung=bez, typ=typ,
                                   nettomiete_aktuell=Decimal('1250.50'))
        m = Mieter.objects.create(typ='person', vorname=vor, nachname=name, strasse=strasse,
                                  plz='6900' if ort else '', ort=ort)
        return Mietvertrag.objects.create(
            mieter=m, einheit=e, beginn=date(2024, 1, 1), netto_mietzins=Decimal('1250.50'),
            nebenkosten=Decimal('1210'), kautions_betrag=Decimal('3751.5'), status='aktiv',
            mitmieter_name=mitmieter)


class VertragTests(_Basis):
    def test_umlaute_franzoesisch_italienisch(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        v = self._vertrag(name='Müller-Lefèvre Çelik', vor='Giuseppe Ràmon', ort='Lugano',
                          strasse='Via Nassa 7 — Piano àèìòù')
        t = _flach(generate_vertrag_pdf_bytes(v))
        for s in ('Müller-Lefèvre Çelik', 'Giuseppe Ràmon', 'Piano àèìòù', 'Schlüsselübergabe'):
            self.assertIn(s, t)

    def test_betraege_schweizer_format_auch_in_zeitplan_und_staffel(self):
        """`|floatformat:2` lieferte unter @nur_deutsch «1250,50»."""
        from rentals.models import VertragMietzins, Staffelstufe
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        v = self._vertrag()
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2024, 1, 1),
                                          netto_mietzins=Decimal('1250.50'), nebenkosten=Decimal('1210'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1), netto_mietzins=Decimal('1300.50'))
        v.mietzins_modell = 'staffel'                     # Staffelklausel erscheint nur im Staffelmodell
        v.save()
        t = _flach(generate_vertrag_pdf_bytes(v))
        self.assertIn("CHF 1'250.50", t)
        self.assertIn("CHF 1'300.50", t)
        self.assertIn("CHF 2'460.50", t)                 # Brutto 1250.50 + 1210
        self.assertIn("CHF 3'751.50", t)                 # Kaution
        for falsch in ('1250,50', '1300,50', '1250.50', '1300.50', '3751.50', 'CHF None', '$'):
            self.assertNotIn(falsch, t.replace("1'250.50", '').replace("1'300.50", '').replace("3'751.50", ''),
                             falsch)

    def test_fehlender_mitmieter_und_eigentuemer(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        v = self._vertrag(mitmieter='')
        pdf = generate_vertrag_pdf_bytes(v)
        self.assertTrue(pdf.startswith(b'%PDF'))
        t = _flach(pdf)
        self.assertNotIn('None', t)
        # `{{Unterschrift …}}` sind gewollte DocuSeal-Feldmarken, keine offenen Variablen
        self.assertNotIn('{{', t.replace('{{Unterschrift', '').replace('{{Ort', '').replace('{{Datum', ''))

    def test_garage_vertrag(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        v = self._vertrag(typ='gar', bez='Garage Nr. 12 Zürich')
        t = _flach(generate_vertrag_pdf_bytes(v))
        self.assertIn('Garage Nr. 12 Zürich', t)
        self.assertIn("CHF 1'250.50", t)

    def test_fremde_zeichen_im_namen_stuerzen_nicht_ab(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        v = self._vertrag(name='Żółć Şahin ☃', vor='Łukasz 😀')
        t = _flach(generate_vertrag_pdf_bytes(v))
        self.assertIn('Lukasz ?', t)
        self.assertIn('Zólc Sahin ?', t)
        self.assertNotIn('nukasz', t)


class BegleitdokumenteTests(_Basis):
    def test_alle_dokumenttypen_mit_leeren_und_fremden_daten(self):
        from core.services.dokument_service import DOKUMENT_TYPEN, generate_dokument_pdf_bytes
        for variante in (dict(), dict(name='Żółć', vor='', ort='', strasse=''), dict(mitmieter='Żaneta ☃')):
            v = self._vertrag(**variante)
            for typ in DOKUMENT_TYPEN:
                pdf = generate_dokument_pdf_bytes(v, typ)
                self.assertTrue(pdf.startswith(b'%PDF'), (typ, variante))
                t = _flach(pdf)
                self.assertNotIn('None', t, (typ, variante))
                self.assertNotIn('nukasz', t)

    def test_betraege_im_begleitbrief_und_wohnungsausweis(self):
        from core.services.dokument_service import generate_dokument_pdf_bytes
        v = self._vertrag()
        self.assertIn("CHF 2'460.50", _flach(generate_dokument_pdf_bytes(v, 'wohnungsausweis')))
        self.assertIn("CHF 3'751.50", _flach(generate_dokument_pdf_bytes(v, 'begleitbrief')))

    def test_unbekannter_typ(self):
        from core.services.dokument_service import generate_dokument_pdf_bytes
        with self.assertRaises(ValueError):
            generate_dokument_pdf_bytes(self._vertrag(), 'gibt-es-nicht')


class BriefeUndProtokolleTests(_Basis):
    def _alle(self, v):
        from rentals.models import Kuendigung, Abnahmeprotokoll, AbnahmeMangel
        from core.services.kuendigung_brief import generate_kuendigung_mieter_pdf
        from core.services.abnahme_pdf import generate_abnahme_pdf
        from core.services import mietprozess_briefe as mb
        from core.services.mahnbrief import mahnbrief_pdf
        k = Kuendigung.objects.create(vertrag=v, per_datum=date(2025, 3, 31))
        ab = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=date(2025, 3, 31),
                                             verwalter_name='Jürg Bühler', neue_adresse='Rue du Mâconnais 3, 1700 Fribourg')
        AbnahmeMangel.objects.create(protokoll=ab, raum='Küche', beschreibung='Herdplatte défectueuse à réparer – ç',
                                     verursacher='mieter', kostenschaetzung=Decimal('12345.5'))
        return {
            'kuendigung': lambda: generate_kuendigung_mieter_pdf(v, k),
            'abnahme': lambda: generate_abnahme_pdf(ab),
            'kaution_hinterlegung': lambda: mb.kaution_hinterlegung_pdf(v),
            'kaution_freigabe': lambda: mb.kaution_freigabe_pdf(v),
            'maengelruege': lambda: mb.maengelruege_pdf(v, 'Schimmel im Bad, à réparer'),
            'untermiete': lambda: mb.untermiete_zustimmung_pdf(v, 'Andrea Società'),
            'rueckgabe_maengelruege': lambda: mb.rueckgabe_maengelruege_pdf(
                v, [{'raum': 'Bad', 'beschreibung': 'Fliese gebrochen', 'betrag': Decimal('1250.5')}]),
            'mahnbrief': lambda: mahnbrief_pdf(v, None, stufe=1, monat=date(2025, 1, 1),
                                               betrag=Decimal('1250.5'), datum=date(2025, 2, 1)),
        }

    def test_alle_briefe_normal_leer_und_fremd(self):
        for variante in (dict(), dict(name='Muster', vor='', ort='', strasse=''),
                         dict(name='Żółć Şahin ☃', vor='Łukasz')):
            v = self._vertrag(**variante)
            for name, erzeuge in self._alle(v).items():
                pdf = erzeuge()
                self.assertTrue(pdf.startswith(b'%PDF'), (name, variante))
                t = _flach(pdf)
                self.assertNotIn('None', t, (name, variante))
                self.assertNotIn('nukasz', t, (name, variante))

    def test_umlaute_in_briefen(self):
        v = self._vertrag()
        for name, erzeuge in self._alle(v).items():
            if name in ('mahnbrief',):
                continue
            self.assertIn('Müller-Lefèvre Çelik', _flach(erzeuge()), name)

    def test_abnahme_betrag(self):
        t = _flach(self._alle(self._vertrag())['abnahme']())
        self.assertIn("CHF 12'345.50", t)
        self.assertIn('défectueuse', t)

    def test_mahnbrief_betrag_und_datum_schweizer_format(self):
        """Vorher: «für 2025-01-01 noch CHF 1250.5 ausstehend»."""
        t = _flach(self._alle(self._vertrag())['mahnbrief']())
        self.assertIn("für Januar 2025 noch CHF 1'250.50 ausstehend", t)
        self.assertNotIn('2025-01-01', t)
        self.assertNotIn('1250.5 ', t)

    def test_mahnbrief_datum_ohne_verwaltung_ohne_fuehrendes_komma(self):
        t = _flach(self._alle(self._vertrag())['mahnbrief']())
        self.assertNotIn(', 01.02.2025', t)
        self.assertIn('01.02.2025', t)

    def test_mahnbrief_mit_text_betrag_und_gebuehr(self):
        from core.services.mahnbrief import mahnbrief_pdf
        v = self._vertrag()
        pdf = mahnbrief_pdf(v, None, stufe=2, monat='Februar 2025', betrag='12500.50',
                            datum=date(2025, 3, 1), gebuehr=Decimal('30'))
        t = _flach(pdf)
        self.assertIn("CHF 12'500.50", t)
        self.assertIn('Mahngebühr von CHF 30.00', t)

    def test_fehlender_betrag_wird_kein_none(self):
        from core.services import mietprozess_briefe as mb
        v = self._vertrag()
        v.kautions_betrag = None
        t = _flach(mb.kaution_hinterlegung_pdf(v))
        self.assertNotIn('None', t)


class FehlerfangTests(_Basis):
    def test_kaputtes_html_wirft_nur_pdffehler(self):
        for html in ('', '<html><body><table><tr><td>', '<<<>>> &&& {{'):
            try:
                pdf = html_zu_pdf(html, quelle='Test')
            except PdfFehler:
                continue
            self.assertTrue(pdf.startswith(b'%PDF'), repr(html))

    def test_renderer_absturz_wird_pdffehler(self):
        with mock.patch('xhtml2pdf.pisa.CreatePDF', side_effect=RuntimeError('boom')):
            with self.assertRaises(PdfFehler) as ctx:
                html_zu_pdf('<p>x</p>', quelle='Mietvertrag')
        self.assertIn('Mietvertrag', str(ctx.exception))

    def test_renderer_fehlerstatus_wird_pdffehler(self):
        status = mock.Mock(err=2)
        with mock.patch('xhtml2pdf.pisa.CreatePDF', return_value=status):
            with self.assertRaises(PdfFehler):
                html_zu_pdf('<p>x</p>')

    def test_view_liefert_saubere_500_statt_absturz(self):
        from django.test import Client
        from ._helfer import _team_user
        v = self._vertrag()
        c = Client()
        c.force_login(_team_user())
        with mock.patch('core.views.pdf.generate_vertrag_pdf_bytes', side_effect=PdfFehler('x')):
            r = c.get(f'/pdf/{v.pk}/') if False else c.get(self._url(v))
        self.assertEqual(r.status_code, 500)
        self.assertIn('Fehler beim Erstellen', r.content.decode())

    def _url(self, v):
        from django.urls import reverse
        return reverse('generate_pdf', args=[v.pk])

    def test_download_dateiname_mit_umlaut_und_zeilenumbruch(self):
        from django.test import Client
        from ._helfer import _team_user
        v = self._vertrag(name='Zürcher\nÖl "x"/y', bez='Wohnung ✓')
        c = Client()
        c.force_login(_team_user())
        r = c.get(self._url(v))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        kopf = r['Content-Disposition']
        self.assertNotIn('\n', kopf)
        self.assertTrue(kopf.startswith('attachment'))

    def test_vertragspaket_meldet_fehlende_dokumente_im_log(self):
        from core.views.pdf import erzeuge_und_ablege_vertragspaket
        v = self._vertrag()
        with mock.patch('core.views.pdf.generate_dokument_pdf_bytes', side_effect=PdfFehler('kaputt')):
            with self.assertLogs('core.views.pdf', level='ERROR') as log:
                dateien = erzeuge_und_ablege_vertragspaket(v, ueberschreiben=False)
        self.assertEqual(len(dateien), 1)                       # nur der Mietvertrag
        self.assertGreaterEqual(len(log.records), 1)


class TestPdfsFuerDieSichtpruefung(_Basis):
    """Schreibt von jedem Dokument ein PDF in $PDF_DUMP_DIR (sonst: nur Erzeugbarkeit)."""

    def test_testpdfs_fuer_die_sichtpruefung(self):
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        from core.services.dokument_service import DOKUMENT_TYPEN, generate_dokument_pdf_bytes
        from core.services.schlussabrechnung import (berechne_schlussabrechnung,
                                                      generate_schlussabrechnung_pdf)
        from rentals.models import VertragMietzins, Staffelstufe, Kuendigung
        ziel = os.environ.get('PDF_DUMP_DIR')
        if ziel:
            os.makedirs(ziel, exist_ok=True)
        org = _test_organisation()
        eig = Eigentuemer.objects.create(organisation=org, name='Immobilien Société Zürich AG',
                                         strasse='Bahnhofstrasse 10', plz='8001', ort='Zürich') \
            if 'name' in {f.name for f in Eigentuemer._meta.fields} else None
        v = self._vertrag(mitmieter='Hélène Müller-Bianchi', eigentuemer=eig)
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=date(2024, 1, 1),
                                          netto_mietzins=Decimal('1250.50'), nebenkosten=Decimal('1210'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 1, 1), netto_mietzins=Decimal('1300.50'))
        v.mietzins_modell = 'staffel'
        v.save()
        v_leer = self._vertrag(name='Muster', vor='', ort='', strasse='', mitmieter='', bez='Whg 1')
        v_fremd = self._vertrag(name='Żółć Şahin ☃', vor='Łukasz 😀')
        v_gar = self._vertrag(typ='gar', bez='Garage Nr. 12')

        dokumente = {
            '01_Mietvertrag_Wohnung_Umlaute_Franz': lambda: generate_vertrag_pdf_bytes(v),
            '02_Mietvertrag_Garage': lambda: generate_vertrag_pdf_bytes(v_gar),
            '03_Mietvertrag_leere_Felder': lambda: generate_vertrag_pdf_bytes(v_leer),
            '04_Mietvertrag_fremde_Zeichen': lambda: generate_vertrag_pdf_bytes(v_fremd),
        }
        for i, typ in enumerate(DOKUMENT_TYPEN, start=5):
            dokumente[f'{i:02d}_Begleitdokument_{typ}'] = (lambda t=typ: generate_dokument_pdf_bytes(v, t))
        dokumente['12_Begleitbrief_leere_Felder'] = lambda: generate_dokument_pdf_bytes(v_leer, 'begleitbrief')

        for name, erzeuge in BriefeUndProtokolleTests._alle(self, v).items():
            dokumente[f'13_{name}'] = erzeuge
        for name, erzeuge in BriefeUndProtokolleTests._alle(self, v_leer).items():
            if name in ('kuendigung', 'abnahme', 'mahnbrief'):
                dokumente[f'14_{name}_leere_Felder'] = erzeuge
        for name, erzeuge in BriefeUndProtokolleTests._alle(self, v_fremd).items():
            if name in ('kuendigung', 'abnahme'):
                dokumente[f'15_{name}_fremde_Zeichen'] = erzeuge

        daten = berechne_schlussabrechnung(
            v, date(2025, 3, 31),
            [{'text': 'Reinigung Küche — Schäden à réparer', 'betrag': Decimal('1250.5'), 'zulasten': True}])
        dokumente['16_Schlussabrechnung'] = lambda: generate_schlussabrechnung_pdf(v, daten)
        k = Kuendigung.objects.create(vertrag=v, absender='vermieter', per_datum=date(2025, 3, 31))
        from core.services.amtliche_formulare_so import kuendigung_so_pdf
        dokumente['17_Kuendigung_amtliches_Formular'] = lambda: kuendigung_so_pdf(v, k)

        fehler = []
        for name, erzeuge in dokumente.items():
            try:
                pdf = erzeuge()
            except Exception as exc:                 # alle Fehler sammeln, nicht beim ersten abbrechen
                fehler.append(f'{name}: {exc!r}')
                continue
            self.assertTrue(pdf.startswith(b'%PDF'), name)
            if ziel:
                with open(os.path.join(ziel, f'{name}.pdf'), 'wb') as f:
                    f.write(pdf)
        self.assertEqual(fehler, [])
