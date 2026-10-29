"""Datenimport für Wechselkunden (Audit FUNK-09).

Belegt wird, was der Auftrag verlangt:

* Lesen von CSV und XLSX (ohne Fremdbibliothek), Fehlerliste mit Zeile und Spalte
* Trockenlauf schreibt nichts, Ausführung ist alles oder nichts (eine Transaktion)
* die Regeln des Bestands greifen (Mietzinsmodell, Kündigungsfrist, Kaution)
* Zugriff nur Inhaber/Verwalter, Protokoll im Audit-Log
* Mandantentrennung: ein fremder Lauf ist ein 404, ein Schlüssel der anderen Organisation ist
  nicht auflösbar, angelegt wird nur in der eigenen Organisation

Gegenprobe zu jedem Block: siehe Bericht (Fehler eingebaut, Test rot, zurückgebaut).
"""
import io
import zipfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.services import datenimport
from core.services.datenimport_lesen import DateiFehler, lese_tabelle
from core.tenancy import organisation_kontext

from ._rollen import RollenBasis

EIGENTUEMER = 'schluessel;name;email;iban\nE1;Muster Immobilien AG;eig@example.ch;CH93 0076 2011 6238 5295 7\n'
LIEGENSCHAFTEN = ('schluessel;strasse;plz;ort;eigentuemer;kanton;baujahr\n'
                  'L1;Seestrasse 12;8002;Zürich;E1;ZH;1975\n')
OBJEKTE = ('schluessel;liegenschaft;bezeichnung;typ;zimmer;flaeche_m2;nettomiete;nebenkosten\n'
           'O1;L1;3.5 Zi 2. OG;whg;3.5;82.5;1850;220\n'
           'O2;L1;Büro EG;gew;;120;3000;400\n')
MIETER = ('schluessel;typ;vorname;nachname;firmenname;email\n'
          'M1;person;Beat;Muster;;beat@example.ch\n'
          'M2;firma;;;Muster AG;info@muster-ag.example.ch\n')
VERTRAEGE = ('schluessel;objekt;mieter;beginn;netto_mietzins;nebenkosten;kaution;kautionsart\n'
             'V1;O1;M1;2019-04-01;1850.00;220.00;5550;sperrkonto\n')


def _alle(**ueberschreibe):
    d = {'eigentuemer': EIGENTUEMER, 'liegenschaften': LIEGENSCHAFTEN, 'objekte': OBJEKTE,
         'mieter': MIETER, 'vertraege': VERTRAEGE}
    d.update(ueberschreibe)
    return {a: (f'{a}.csv', t.encode('utf-8')) for a, t in d.items() if t is not None}


def _xlsx(zeilen, datum_spalten=()):
    """Eine minimale .xlsx: Texte als Shared Strings, Zahlen als Zahl, Datumsspalten mit Datumsformat."""
    texte, xml_zeilen = [], []
    for r, zeile in enumerate(zeilen, start=1):
        zellen = []
        for c, wert in enumerate(zeile):
            ref = f'{chr(65 + c)}{r}'
            if isinstance(wert, (int, float)):
                stil = ' s="1"' if (r > 1 and c in datum_spalten) else ''
                zellen.append(f'<c r="{ref}"{stil}><v>{wert}</v></c>')
            else:
                texte.append(wert)
                zellen.append(f'<c r="{ref}" t="s"><v>{len(texte) - 1}</v></c>')
        xml_zeilen.append(f'<row r="{r}">{"".join(zellen)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    teile = {
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        'xl/workbook.xml': (f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                            '<sheets><sheet name="Tabelle1" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        'xl/_rels/workbook.xml.rels': ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                       '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'),
        'xl/sharedStrings.xml': f'<sst {ns}>' + ''.join(f'<si><t>{t}</t></si>' for t in texte) + '</sst>',
        'xl/styles.xml': (f'<styleSheet {ns}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'),
        'xl/worksheets/sheet1.xml': f'<worksheet {ns}><sheetData>{"".join(xml_zeilen)}</sheetData></worksheet>',
    }
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, 'w') as zf:
        for name, inhalt in teile.items():
            zf.writestr(name, inhalt)
    return puffer.getvalue()


def _zaehle(org):
    from crm.models import Eigentuemer, Mieter
    from portfolio.models import Einheit, Liegenschaft
    from rentals.models import Mietvertrag
    with organisation_kontext(org):
        return (Eigentuemer.objects.count(), Liegenschaft.objects.count(), Einheit.objects.count(),
                Mieter.objects.count(), Mietvertrag.objects.count())


class LesenTests(TestCase):
    """CSV und XLSX werden ohne Fremdbibliothek gelesen; Zeilennummern sind die von Excel."""

    def test_csv_semikolon_mit_zeilennummern(self):
        kopf, zeilen = lese_tabelle('a.csv', 'Straße;PLZ Ort\nSeeweg 1;8000\n\nBergweg 2;3000\n'.encode())
        self.assertEqual(kopf, ['strasse', 'plz_ort'])
        self.assertEqual([(n, z['strasse']) for n, z in zeilen], [(2, 'Seeweg 1'), (4, 'Bergweg 2')])

    def test_csv_komma_und_windows_1252(self):
        kopf, zeilen = lese_tabelle('a.csv', 'name,ort\nMüller,Zürich\n'.encode('cp1252'))
        self.assertEqual(zeilen[0][1], {'name': 'Müller', 'ort': 'Zürich'})

    def test_csv_mit_bom_und_tabulator(self):
        kopf, zeilen = lese_tabelle('a.csv', '﻿name\tort\nA\tB\n'.encode('utf-8'))
        self.assertEqual(kopf, ['name', 'ort'])

    def test_xlsx_text_zahl_und_datum(self):
        # Excel-Seriennummer 43556 = 01.04.2019
        daten = _xlsx([['schluessel', 'beginn', 'netto'], ['V1', 43556, 1850.5]], datum_spalten=(1,))
        kopf, zeilen = lese_tabelle('v.xlsx', daten)
        self.assertEqual(kopf, ['schluessel', 'beginn', 'netto'])
        self.assertEqual(zeilen[0], (2, {'schluessel': 'V1', 'beginn': '2019-04-01', 'netto': '1850.5'}))

    def test_xlsx_ganze_zahl_ohne_nachkomma(self):
        kopf, zeilen = lese_tabelle('v.xlsx', _xlsx([['a'], [1850.0]]))
        self.assertEqual(zeilen[0][1]['a'], '1850')

    def test_defekte_xlsx_ist_ein_dateifehler(self):
        with self.assertRaises(DateiFehler):
            lese_tabelle('v.xlsx', b'PK\x03\x04kaputt')

    def test_xlsx_mit_entitaeten_wird_abgelehnt(self):
        daten = _xlsx([['a'], ['b']])
        puffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(daten)) as quelle, zipfile.ZipFile(puffer, 'w') as ziel:
            for info in quelle.infolist():
                inhalt = quelle.read(info)
                if info.filename == 'xl/sharedStrings.xml':
                    inhalt = b'<!DOCTYPE x [<!ENTITY a "aaaa">]>' + inhalt
                ziel.writestr(info.filename, inhalt)
        with self.assertRaises(DateiFehler):
            lese_tabelle('v.xlsx', puffer.getvalue())

    def test_altes_xls_wird_erklaert(self):
        with self.assertRaises(DateiFehler) as e:
            lese_tabelle('alt.xls', b'\xd0\xcf\x11\xe0abc')
        self.assertIn('.xlsx', str(e.exception))

    def test_doppelte_spalte_und_leere_datei(self):
        with self.assertRaises(DateiFehler):
            lese_tabelle('a.csv', b'a;a\n1;2\n')
        with self.assertRaises(DateiFehler):
            lese_tabelle('a.csv', b'')

    def test_zu_viele_zeilen(self):
        text = 'a\n' + '1\n' * 5001
        with self.assertRaises(DateiFehler):
            lese_tabelle('a.csv', text.encode())


class ImportDienstTests(RollenBasis):
    """Die Verarbeitung: Trockenlauf, Ausführung, Atomarität, Regeln des Bestands."""

    def _lauf(self, ausfuehren, **ueberschreibe):
        return datenimport.verarbeite(self.org, _alle(**ueberschreibe), ausfuehren=ausfuehren)

    def _fehler(self, e):
        return [(m['art'], m['zeile'], m['feld']) for m in e.meldungen if m['stufe'] == 'fehler']

    def test_trockenlauf_schreibt_nichts(self):
        vorher = _zaehle(self.org)
        e = self._lauf(False)
        self.assertTrue(e.ok, e.meldungen)
        self.assertEqual(e.zaehler['vertraege']['neu'], 1)       # gezählt, aber zurückgerollt
        self.assertEqual(_zaehle(self.org), vorher)

    def test_ausfuehren_legt_alles_an_und_verknuepft(self):
        from core.models import DatenImportReferenz
        from crm.models import Eigentuemer, Mieter
        from portfolio.models import Einheit, Liegenschaft, Sollmietzins
        from rentals.models import Mietvertrag
        e = self._lauf(True)
        self.assertTrue(e.ok, e.meldungen)
        with organisation_kontext(self.org):
            eig = Eigentuemer.objects.get(firma_oder_name='Muster Immobilien AG')
            lg = Liegenschaft.objects.get(strasse='Seestrasse 12')
            self.assertEqual((lg.eigentuemer_id, lg.kanton, lg.baujahr, lg.typ, lg.status),
                             (eig.pk, 'ZH', 1975, 'MIETE', 'aktiv'))
            o1 = Einheit.objects.get(liegenschaft=lg, bezeichnung='3.5 Zi 2. OG')
            self.assertEqual(o1.typ, 'whg')
            self.assertEqual(Sollmietzins.objects.get(einheit=o1).netto_mietzins, 1850)
            m = Mieter.objects.get(nachname='Muster', typ='person')
            self.assertEqual(Mieter.objects.get(typ='firma').display_name, 'Muster AG')
            v = Mietvertrag.objects.get(einheit=o1)
            self.assertEqual((v.mieter_id, v.status, v.aktiv, v.beginn, str(v.netto_mietzins), str(v.kautions_betrag)),
                             (m.pk, 'aktiv', True, date(2019, 4, 1), '1850.00', '5550.00'))
            self.assertEqual(v.kuendigungsfrist_monate, 3)
            self.assertEqual(v.organisation_id, self.org.pk)
            self.assertEqual(DatenImportReferenz.objects.count(), 1 + 1 + 2 + 2 + 1)

    def test_zweiter_lauf_legt_nichts_doppelt_an(self):
        self._lauf(True)
        nach_erstem = _zaehle(self.org)
        e = self._lauf(True)
        self.assertTrue(e.ok, e.meldungen)
        self.assertEqual(_zaehle(self.org), nach_erstem)
        self.assertEqual(e.zaehler['vertraege'], {'zeilen': 1, 'neu': 0, 'vorhanden': 1, 'fehler': 0})

    def test_etappen_vertraege_spaeter_ueber_referenzen(self):
        self._lauf(True, mieter=None, vertraege=None)
        e = datenimport.verarbeite(
            self.org, {a: v for a, v in _alle().items() if a in ('mieter', 'vertraege')}, ausfuehren=True)
        self.assertTrue(e.ok, e.meldungen)

    def test_ein_fehler_macht_alles_rueckgaengig(self):
        """Gute Zeilen in Eigentümer, Liegenschaft, Objekt und Mieter bleiben NICHT stehen,
        wenn eine Vertragszeile fehlerhaft ist."""
        vorher = _zaehle(self.org)
        schlecht = VERTRAEGE + 'V2;O2;M2;2019-13-45;3000;400;;\n'
        e = self._lauf(True, vertraege=schlecht)
        self.assertFalse(e.ok)
        self.assertEqual(self._fehler(e), [('vertraege', 3, 'beginn')])
        self.assertEqual(_zaehle(self.org), vorher)
        from core.models import DatenImportReferenz
        with organisation_kontext(self.org):
            self.assertEqual(DatenImportReferenz.objects.count(), 0)

    def test_fehlerliste_nennt_zeile_und_spalte(self):
        e = self._lauf(False, liegenschaften=LIEGENSCHAFTEN + 'L2;Bergweg 3;80;Bern;;BE;\n'
                                                              'L3;;3000;Bern;;XX;\n')
        self.assertEqual(self._fehler(e), [('liegenschaften', 3, 'plz'), ('liegenschaften', 4, 'strasse'),
                                           ('liegenschaften', 4, 'kanton')])
        zeile3 = [m for m in e.meldungen if m['zeile'] == 3 and m['stufe'] == 'fehler'][0]
        self.assertIn('vier Ziffern', zeile3['text'])

    def test_pflichtspalte_fehlt_in_der_datei(self):
        e = self._lauf(False, liegenschaften='schluessel;strasse;ort\nL1;Seeweg 1;Zürich\n')
        self.assertFalse(e.ok)
        self.assertIn('plz', e.meldungen[0]['text'])

    def test_doppelter_schluessel_in_der_datei(self):
        e = self._lauf(False, mieter=MIETER + 'M1;person;Anna;Muster;;\n')
        self.assertEqual(self._fehler(e), [('mieter', 4, 'schluessel')])

    def test_unbekannter_verweis(self):
        e = self._lauf(False, vertraege=VERTRAEGE.replace(';O1;M1;', ';O9;M1;'))
        self.assertEqual(self._fehler(e), [('vertraege', 2, 'objekt')])

    def test_zahlen_werden_nicht_gerundet(self):
        e = self._lauf(False, vertraege=VERTRAEGE.replace('1850.00;220.00', '1850.005;220.00'))
        self.assertEqual(self._fehler(e), [('vertraege', 2, 'netto_mietzins')])

    def test_schweizer_zahlformat(self):
        e = self._lauf(True, vertraege=VERTRAEGE.replace('1850.00;220.00;5550', "1'850,00;220,00;5550"))
        self.assertTrue(e.ok, e.meldungen)

    def test_stweg_wird_nicht_importiert(self):
        e = self._lauf(False, liegenschaften=LIEGENSCHAFTEN.replace('1975', '1975') + 'L2;Bergweg 3;3000;Bern;E1;BE;1990;;;STWEG\n'
                       if False else 'schluessel;strasse;plz;ort;typ\nL1;Seeweg 1;8000;Zürich;STWEG\n',
                       objekte=None, vertraege=None, mieter=None)
        self.assertEqual(self._fehler(e), [('liegenschaften', 2, 'typ')])

    # ── Regeln des Bestands ────────────────────────────────────────────────
    def test_kuendigungsfrist_unter_dem_gesetzlichen_minimum(self):
        """Wohnung: mindestens 3 Monate (Art. 266c OR), Geschäftsraum 6 (Art. 266d OR) — wie die Erfassung."""
        v = ('schluessel;objekt;mieter;beginn;netto_mietzins;nebenkosten;kuendigungsfrist_monate\n'
             'V1;O1;M1;2019-04-01;1850;220;2\n')
        e = self._lauf(False, vertraege=v)
        self.assertEqual(self._fehler(e), [('vertraege', 2, 'kuendigungsfrist_monate')])
        v = v.replace('V1;O1;M1', 'V1;O2;M2').replace(';220;2', ';400;3')
        e = self._lauf(False, vertraege=v)
        self.assertEqual(self._fehler(e), [('vertraege', 2, 'kuendigungsfrist_monate')])

    def test_gewerbe_vorgabe_sechs_monate(self):
        from rentals.models import Mietvertrag
        v = 'schluessel;objekt;mieter;beginn;netto_mietzins;nebenkosten\nV1;O2;M2;2019-04-01;3000;400\n'
        self.assertTrue(self._lauf(True, vertraege=v).ok)
        with organisation_kontext(self.org):
            self.assertEqual(Mietvertrag.objects.get(einheit__bezeichnung='Büro EG').kuendigungsfrist_monate, 6)

    def test_kaution_ueber_drei_monatsmieten_wird_gemeldet_nicht_gekuerzt(self):
        """`Mietvertrag.save()` würde still kürzen; der Import meldet es stattdessen (Art. 257e OR)."""
        e = self._lauf(False, vertraege=VERTRAEGE.replace(';5550;', ';9000;'))
        self.assertEqual(self._fehler(e), [('vertraege', 2, 'kaution')])
        self.assertIn('257e', [m for m in e.meldungen if m['stufe'] == 'fehler'][0]['text'])

    def test_indexmiete_unter_fuenf_jahren_ist_ein_fehler(self):
        """Regelquelle `core/services/mietzinsmodell.py` (Art. 269b OR): Index braucht 5 Jahre fest."""
        v = ('schluessel;objekt;mieter;beginn;ende;befristet;netto_mietzins;nebenkosten;mietzinsmodell;'
             'basis_lik_punkte;basis_lik_stand\n'
             'V1;O2;M2;2026-01-01;2028-12-31;ja;3000;400;index;100.0;2025-12\n')
        e = self._lauf(False, vertraege=v)
        self.assertFalse(e.ok)
        self.assertTrue(any('269b' in m['text'] for m in e.meldungen if m['stufe'] == 'fehler'), e.meldungen)

    def test_indexmiete_ueber_fuenf_jahre_wird_importiert(self):
        from rentals.models import Mietvertrag
        v = ('schluessel;objekt;mieter;beginn;ende;befristet;netto_mietzins;nebenkosten;mietzinsmodell;'
             'basis_lik_punkte;basis_lik_stand\n'
             'V1;O2;M2;2026-01-01;2031-12-31;ja;3000;400;index;100.0;2025-12\n')
        e = self._lauf(True, vertraege=v)
        self.assertTrue(e.ok, e.meldungen)
        with organisation_kontext(self.org):
            self.assertEqual(Mietvertrag.objects.get(einheit__bezeichnung='Büro EG').mietzins_modell, 'index')

    def test_indexmiete_ohne_basis_ist_ein_fehler(self):
        v = ('schluessel;objekt;mieter;beginn;ende;befristet;netto_mietzins;nebenkosten;mietzinsmodell\n'
             'V1;O2;M2;2026-01-01;2031-12-31;ja;3000;400;index\n')
        e = self._lauf(False, vertraege=v)
        self.assertEqual({f for _a, _z, f in self._fehler(e)}, {'basis_lik_punkte', 'basis_lik_stand'})

    def test_staffelmiete_wird_nicht_importiert(self):
        v = 'schluessel;objekt;mieter;beginn;netto_mietzins;nebenkosten;mietzinsmodell\nV1;O1;M1;2019-04-01;1850;220;staffel\n'
        e = self._lauf(False, vertraege=v)
        self.assertEqual(self._fehler(e), [('vertraege', 2, 'mietzinsmodell')])

    def test_enddatum_braucht_klarheit_ueber_befristung(self):
        v = 'schluessel;objekt;mieter;beginn;ende;netto_mietzins;nebenkosten\nV1;O1;M1;2019-04-01;2030-03-31;1850;220\n'
        self.assertEqual(self._fehler(self._lauf(False, vertraege=v)), [('vertraege', 2, 'befristet')])

    def test_gekuendigter_vertrag_braucht_enddatum(self):
        v = 'schluessel;objekt;mieter;beginn;status;netto_mietzins;nebenkosten\nV1;O1;M1;2019-04-01;gekuendigt;1850;220\n'
        self.assertEqual(self._fehler(self._lauf(False, vertraege=v)), [('vertraege', 2, 'ende')])

    def test_gekuendigter_vertrag_wird_importiert(self):
        from rentals.models import Mietvertrag
        v = ('schluessel;objekt;mieter;beginn;ende;befristet;status;netto_mietzins;nebenkosten\n'
             'V1;O1;M1;2019-04-01;2027-03-31;nein;gekuendigt;1850;220\n')
        self.assertTrue(self._lauf(True, vertraege=v).ok)
        with organisation_kontext(self.org):
            vertrag = Mietvertrag.objects.get(einheit__bezeichnung='3.5 Zi 2. OG')
            self.assertEqual((vertrag.status, vertrag.ist_befristet, vertrag.ende), ('gekuendigt', False, date(2027, 3, 31)))

    def test_ueberschneidung_am_selben_objekt(self):
        v = VERTRAEGE + 'V2;O1;M2;2020-01-01;1900;220;;\n'
        e = self._lauf(False, vertraege=v)
        self.assertEqual(self._fehler(e), [('vertraege', 3, 'objekt')])

    def test_mwst_option_nicht_fuer_wohnraum(self):
        v = 'schluessel;objekt;mieter;beginn;netto_mietzins;nebenkosten;mwst_pflichtig;mwst_satz\nV1;O1;M1;2019-04-01;1850;220;ja;8.1\n'
        self.assertEqual(self._fehler(self._lauf(False, vertraege=v)), [('vertraege', 2, 'mwst_pflichtig')])

    def test_mwst_satz_wird_nicht_vorgegeben(self):
        v = 'schluessel;objekt;mieter;beginn;netto_mietzins;nebenkosten;mwst_pflichtig\nV1;O2;M2;2019-04-01;3000;400;ja\n'
        self.assertEqual(self._fehler(self._lauf(False, vertraege=v)), [('vertraege', 2, 'mwst_satz')])

    def test_mieter_pflichten_je_typ(self):
        m = 'schluessel;typ;vorname;nachname;firmenname\nM1;person;Beat;;\nM2;firma;;;\n'
        e = self._lauf(False, mieter=m, vertraege=None)
        self.assertEqual(self._fehler(e), [('mieter', 2, 'nachname'), ('mieter', 3, 'firmenname')])

    def test_bestehende_liegenschaft_wird_zugeordnet_nicht_doppelt(self):
        """Eine von Hand angelegte Liegenschaft mit gleicher Adresse wird übernommen, nichts verändert."""
        from portfolio.models import Liegenschaft
        with organisation_kontext(self.org):
            vorhanden = Liegenschaft.objects.create(strasse='Seestrasse 12', plz='8002', ort='Zürich', kanton='ZH')
            anzahl = Liegenschaft.objects.count()
        e = self._lauf(True)
        self.assertTrue(e.ok, e.meldungen)
        with organisation_kontext(self.org):
            self.assertEqual(Liegenschaft.objects.count(), anzahl)
            self.assertEqual(Liegenschaft.objects.get(strasse='Seestrasse 12').pk, vorhanden.pk)

    def test_xlsx_wird_importiert(self):
        liegenschaften = _xlsx([['schluessel', 'strasse', 'plz', 'ort'], ['L1', 'Seestrasse 12', 8002, 'Zürich']])
        e = datenimport.verarbeite(self.org, {'liegenschaften': ('l.xlsx', liegenschaften)}, ausfuehren=True)
        self.assertTrue(e.ok, e.meldungen)
        from portfolio.models import Liegenschaft
        with organisation_kontext(self.org):
            self.assertTrue(Liegenschaft.objects.filter(strasse='Seestrasse 12', plz='8002').exists())

    def test_feldlaenge_wird_gemeldet_statt_datenbankfehler(self):
        e = self._lauf(False, liegenschaften=LIEGENSCHAFTEN + 'L2;' + 'x' * 201 + ';3000;Bern;;BE;\n')
        self.assertEqual(self._fehler(e), [('liegenschaften', 3, 'strasse')])


class LaufTests(RollenBasis):
    """Vorschau -> Ausführung mit Protokoll; Sperre gegen Doppelausführung."""

    def test_vorschau_dann_ausfuehren(self):
        from core.models import DatenImportLauf
        lauf = datenimport.vorschau_erstellen(self.org, self.benutzer['verwalter'], _alle())
        self.assertEqual(lauf.status, DatenImportLauf.STATUS_VORSCHAU)
        self.assertTrue(lauf.daten)
        vorher = _zaehle(self.org)
        lauf = datenimport.lauf_ausfuehren(self.org, lauf.pk, self.benutzer['verwalter'])
        self.assertEqual(lauf.status, DatenImportLauf.STATUS_IMPORTIERT)
        self.assertEqual(bytes(lauf.daten), b'')                       # Dateien nach dem Import gelöscht
        self.assertIsNotNone(lauf.ausgefuehrt_am)
        self.assertEqual([x - y for x, y in zip(_zaehle(self.org), vorher)], [1, 1, 2, 2, 1])

    def test_vorschau_mit_fehlern_ist_nicht_ausfuehrbar(self):
        from core.models import DatenImportLauf
        lauf = datenimport.vorschau_erstellen(self.org, None, _alle(liegenschaften='schluessel;strasse;plz;ort\nL1;;8002;Zürich\n'))
        self.assertEqual(lauf.status, DatenImportLauf.STATUS_FEHLERHAFT)
        with self.assertRaises(datenimport.AusfuehrungsFehler):
            datenimport.lauf_ausfuehren(self.org, lauf.pk, None)

    def test_zweite_ausfuehrung_wird_abgewiesen(self):
        lauf = datenimport.vorschau_erstellen(self.org, None, _alle())
        datenimport.lauf_ausfuehren(self.org, lauf.pk, None)
        nach = _zaehle(self.org)
        with self.assertRaises(datenimport.AusfuehrungsFehler):
            datenimport.lauf_ausfuehren(self.org, lauf.pk, None)
        self.assertEqual(_zaehle(self.org), nach)

    def test_ausfuehrung_prueft_neu_und_bricht_ab(self):
        """Wurde zwischen Vorschau und Ausführung etwas Unvereinbares angelegt, bleibt der Bestand unberührt."""
        from core.models import DatenImportLauf
        lauf = datenimport.vorschau_erstellen(self.org, None, _alle())
        self.assertEqual(lauf.status, DatenImportLauf.STATUS_VORSCHAU)
        # Zwischenzeitlich vermietet jemand das Objekt von Hand
        with organisation_kontext(self.org):
            from crm.models import Mieter
            from portfolio.models import Einheit, Liegenschaft
            from rentals.models import Mietvertrag
            lg = Liegenschaft.objects.create(strasse='Seestrasse 12', plz='8002', ort='Zürich')
            o = Einheit.objects.create(liegenschaft=lg, bezeichnung='3.5 Zi 2. OG', typ='whg')
            m = Mieter.objects.create(typ='person', nachname='Zwischen')
            Mietvertrag.objects.create(mieter=m, einheit=o, beginn=date(2018, 1, 1), netto_mietzins=1000, nebenkosten=100, status='aktiv')
        vorher = _zaehle(self.org)
        lauf = datenimport.lauf_ausfuehren(self.org, lauf.pk, None)
        self.assertEqual(lauf.status, DatenImportLauf.STATUS_ABGEBROCHEN)
        self.assertGreater(lauf.anzahl_fehler, 0)
        self.assertEqual(_zaehle(self.org), vorher)

    def test_verwerfen_loescht_die_dateien(self):
        from core.models import DatenImportLauf
        lauf = datenimport.vorschau_erstellen(self.org, None, _alle())
        lauf = datenimport.lauf_verwerfen(self.org, lauf.pk)
        self.assertEqual((lauf.status, bytes(lauf.daten)), (DatenImportLauf.STATUS_VERWORFEN, b''))
        with self.assertRaises(datenimport.AusfuehrungsFehler):
            datenimport.lauf_ausfuehren(self.org, lauf.pk, None)

    def test_keine_datei_ist_kein_importierbarer_lauf(self):
        from core.models import DatenImportLauf
        lauf = datenimport.vorschau_erstellen(self.org, None, {})
        self.assertEqual(lauf.status, DatenImportLauf.STATUS_FEHLERHAFT)


class ImportOberflaecheTests(RollenBasis):
    """Zugriff, Upload, Protokoll im Audit-Log."""

    SEITEN = ('/neu/einstellungen/daten/import/', '/neu/einstellungen/daten/import/vorlage/liegenschaften/')

    def _hoch(self, c, **dateien):
        daten = {f'datei_{a}': SimpleUploadedFile(f'{a}.csv', t.encode('utf-8'), content_type='text/csv')
                 for a, t in dateien.items()}
        return c.post('/neu/einstellungen/daten/import/', daten)

    def test_nur_inhaber_und_verwalter(self):
        for rolle in ('inhaber', 'verwalter'):
            for url in self.SEITEN:
                self.assertEqual(self.client_von(rolle).get(url).status_code, 200, (rolle, url))
        for rolle in ('sachbearbeiter', 'buchhaltung', 'lesezugriff', 'hauswart'):
            for url in self.SEITEN + ('/neu/einstellungen/daten/import/%d/' % self.a.datenimport.pk,):
                self.assertEqual(self.client_von(rolle).get(url).status_code, 403, (rolle, url))
            c = self.client_von(rolle)
            self.assertEqual(self._hoch(c, liegenschaften=LIEGENSCHAFTEN).status_code, 403, rolle)

    def test_anonym_wird_zur_anmeldung_geleitet(self):
        from django.test import Client
        antwort = Client().get('/neu/einstellungen/daten/import/')
        self.assertEqual(antwort.status_code, 302)
        self.assertIn('/login/', antwort['Location'])

    def test_kein_zugriff_fuer_lesende_auf_ausfuehren_und_verwerfen(self):
        lauf = datenimport.vorschau_erstellen(self.org, None, _alle())
        for rolle in ('sachbearbeiter', 'lesezugriff', 'buchhaltung'):
            for aktion in ('ausfuehren', 'verwerfen'):
                antwort = self.client_von(rolle).post(f'/neu/einstellungen/daten/import/{lauf.pk}/{aktion}/')
                self.assertEqual(antwort.status_code, 403, (rolle, aktion))
        from core.models import DatenImportLauf
        with organisation_kontext(self.org):
            self.assertEqual(DatenImportLauf.objects.get(pk=lauf.pk).status, 'vorschau')

    def test_upload_vorschau_ausfuehren_mit_protokoll(self):
        from core.models import AktivitaetsLog
        c = self.client_von('verwalter')
        vorher = _zaehle(self.org)
        antwort = self._hoch(c, eigentuemer=EIGENTUEMER, liegenschaften=LIEGENSCHAFTEN, objekte=OBJEKTE,
                             mieter=MIETER, vertraege=VERTRAEGE)
        self.assertEqual(antwort.status_code, 302)
        seite = c.get(antwort['Location'])
        self.assertContains(seite, 'Jetzt importieren')
        self.assertEqual(_zaehle(self.org), vorher)                 # Vorschau: nichts angelegt
        antwort = c.post(antwort['Location'] + 'ausfuehren/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual([x - y for x, y in zip(_zaehle(self.org), vorher)], [1, 1, 2, 2, 1])
        seite = c.get(antwort['Location'])
        self.assertContains(seite, 'Importiert')
        self.assertNotContains(seite, 'Jetzt importieren')
        with organisation_kontext(self.org):
            aktionen = list(AktivitaetsLog.objects.filter(aktion__startswith='Datenimport').values_list('aktion', flat=True))
        self.assertIn('Datenimport geprüft (Trockenlauf)', aktionen)
        self.assertIn('Datenimport ausgeführt', aktionen)

    def test_fehlerliste_wird_angezeigt_und_nichts_angelegt(self):
        c = self.client_von('inhaber')
        vorher = _zaehle(self.org)
        antwort = self._hoch(c, liegenschaften='schluessel;strasse;plz;ort\nL1;Seeweg 1;80;Zürich\n')
        seite = c.get(antwort['Location'])
        self.assertContains(seite, 'Zeile 2')
        self.assertContains(seite, 'vier Ziffern')
        self.assertNotContains(seite, 'Jetzt importieren')
        self.assertEqual(_zaehle(self.org), vorher)
        # Ausführen eines fehlerhaften Laufs per POST legt trotzdem nichts an.
        c.post(antwort['Location'] + 'ausfuehren/')
        self.assertEqual(_zaehle(self.org), vorher)

    def test_ohne_datei_und_zu_grosse_datei(self):
        c = self.client_von('verwalter')
        self.assertEqual(c.post('/neu/einstellungen/daten/import/', {}).status_code, 302)
        gross = SimpleUploadedFile('l.csv', b'a;b\n' + b'x' * (5 * 1024 * 1024 + 1))
        antwort = c.post('/neu/einstellungen/daten/import/', {'datei_liegenschaften': gross}, follow=True)
        self.assertContains(antwort, 'grösser als 5 MB')

    def test_vorlage_ist_nur_die_kopfzeile(self):
        c = self.client_von('verwalter')
        for art in datenimport.ARTEN:
            antwort = c.get(f'/neu/einstellungen/daten/import/vorlage/{art}/')
            self.assertEqual(antwort.status_code, 200)
            text = antwort.content.decode('utf-8-sig')
            self.assertEqual(text.count('\n'), 1, art)
            self.assertEqual(text.strip().split(';'), [s['name'] for s in datenimport.SPALTEN[art]])
            # Die Vorlage ist selbst importierbar (nur Kopf: keine Zeilen, keine Fehler).
            e = datenimport.verarbeite(self.org, {art: (f'{art}.csv', antwort.content)}, ausfuehren=False)
            self.assertTrue(e.ok, (art, e.meldungen))
        self.assertEqual(c.get('/neu/einstellungen/daten/import/vorlage/unbekannt/').status_code, 404)

    def test_get_auf_ausfuehren_aendert_nichts(self):
        lauf = datenimport.vorschau_erstellen(self.org, None, _alle())
        vorher = _zaehle(self.org)
        self.client_von('verwalter').get(f'/neu/einstellungen/daten/import/{lauf.pk}/ausfuehren/')
        self.assertEqual(_zaehle(self.org), vorher)


class ImportMandantentrennungTests(RollenBasis):
    """Fremde Organisation: nie sichtbar, nie importierbar."""

    def test_fremder_lauf_ist_404(self):
        b_lauf = self.b.datenimport
        c = self.client_von('inhaber')
        self.assertEqual(c.get(f'/neu/einstellungen/daten/import/{b_lauf.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/neu/einstellungen/daten/import/{b_lauf.pk}/ausfuehren/').status_code, 404)
        self.assertEqual(c.post(f'/neu/einstellungen/daten/import/{b_lauf.pk}/verwerfen/').status_code, 404)

    def test_protokoll_zeigt_nur_eigene_laeufe(self):
        c = self.client_von('inhaber')
        seite = c.get('/neu/einstellungen/daten/import/')
        self.assertEqual(seite.status_code, 200)
        self.assertEqual([l.pk for l in seite.context['laeufe']], [self.a.datenimport.pk])

    def test_ausfuehren_eines_fremden_laufs_legt_nirgends_etwas_an(self):
        """Auch direkt über den Dienst: Der Lauf von B ist für A nicht auffindbar."""
        from core.models import DatenImportLauf
        with organisation_kontext(self.b.organisation):
            b_lauf = datenimport.vorschau_erstellen(self.b.organisation, None, _alle())
        vorher_a, vorher_b = _zaehle(self.org), _zaehle(self.b.organisation)
        with self.assertRaises(DatenImportLauf.DoesNotExist):
            datenimport.lauf_ausfuehren(self.org, b_lauf.pk, None)
        self.assertEqual((_zaehle(self.org), _zaehle(self.b.organisation)), (vorher_a, vorher_b))

    def test_schluessel_der_anderen_organisation_sind_nicht_aufloesbar(self):
        """B importiert Liegenschaft «L1». A verweist in seinen Objekten auf «L1» und findet sie NICHT."""
        e = datenimport.verarbeite(self.b.organisation, {'liegenschaften': ('l.csv', LIEGENSCHAFTEN.replace('E1', '').encode())},
                                   ausfuehren=True)
        self.assertTrue(e.ok, e.meldungen)
        e = datenimport.verarbeite(self.org, {'objekte': ('o.csv', 'schluessel;liegenschaft;bezeichnung;typ\nO1;L1;Whg;whg\n'.encode())},
                                   ausfuehren=True)
        self.assertFalse(e.ok)
        self.assertEqual([(m['feld']) for m in e.meldungen if m['stufe'] == 'fehler'], ['liegenschaft'])
        from portfolio.models import Einheit
        with organisation_kontext(self.org):
            self.assertFalse(Einheit.objects.filter(bezeichnung='Whg').exists())
        with organisation_kontext(self.b.organisation):
            self.assertFalse(Einheit.objects.filter(bezeichnung='Whg').exists())

    def test_gleiche_schluessel_in_beiden_organisationen(self):
        """Jede Organisation führt ihr eigenes «L1» (Eindeutigkeit je Organisation, nicht global)."""
        from portfolio.models import Liegenschaft
        e = datenimport.verarbeite(self.org, {'liegenschaften': ('l.csv', LIEGENSCHAFTEN.replace('E1', '').encode())}, ausfuehren=True)
        self.assertTrue(e.ok, e.meldungen)
        e = datenimport.verarbeite(self.b.organisation, {'liegenschaften': ('l.csv', 'schluessel;strasse;plz;ort\nL1;Aarestrasse 5;3000;Bern\n'.encode())},
                                   ausfuehren=True)
        self.assertTrue(e.ok, e.meldungen)
        with organisation_kontext(self.org):
            self.assertEqual(Liegenschaft.objects.get(strasse__in=['Seestrasse 12', 'Aarestrasse 5']).strasse, 'Seestrasse 12')
        with organisation_kontext(self.b.organisation):
            self.assertTrue(Liegenschaft.objects.filter(strasse='Aarestrasse 5').exists())
            self.assertFalse(Liegenschaft.objects.filter(strasse='Seestrasse 12').exists())

    def test_angelegtes_gehoert_der_eigenen_organisation(self):
        from crm.models import Eigentuemer, Mieter
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        datenimport.verarbeite(self.org, _alle(), ausfuehren=True)
        for modell in (Eigentuemer, Liegenschaft, Einheit, Mieter, Mietvertrag):
            for org_id in modell.alle_organisationen.filter(organisation_id=self.org.pk).values_list('organisation_id', flat=True):
                self.assertEqual(org_id, self.org.pk)
        self.assertEqual(Liegenschaft.alle_organisationen.filter(strasse='Seestrasse 12').count(), 1)
        self.assertFalse(Liegenschaft.alle_organisationen.filter(strasse='Seestrasse 12', organisation=self.b.organisation).exists())

    def test_dublettenerkennung_geht_nicht_ueber_die_grenze(self):
        """Gleiche Adresse in B zählt für A nicht als „besteht schon“."""
        from portfolio.models import Liegenschaft
        with organisation_kontext(self.b.organisation):
            Liegenschaft.objects.create(strasse='Seestrasse 12', plz='8002', ort='Zürich')
        e = datenimport.verarbeite(self.org, {'liegenschaften': ('l.csv', LIEGENSCHAFTEN.replace('E1', '').encode())}, ausfuehren=True)
        self.assertTrue(e.ok, e.meldungen)
        self.assertEqual(e.zaehler['liegenschaften']['neu'], 1)

    def test_superuser_ohne_mitgliedschaft_importiert_nirgends(self):
        """Auch ein Superuser braucht eine aktive Organisation: ohne Mitgliedschaft gibt es keinen Kontext,
        und es wird in KEINE Organisation importiert (403 statt Raten)."""
        from django.contrib.auth import get_user_model
        from django.test import Client
        from portfolio.models import Liegenschaft
        su = get_user_model().objects.create_superuser('root', 'root@example.ch', 'x')
        c = Client(raise_request_exception=False)
        c.force_login(su)
        antwort = c.post('/neu/einstellungen/daten/import/',
                         {'datei_liegenschaften': SimpleUploadedFile('l.csv', LIEGENSCHAFTEN.replace('E1', '').encode())})
        self.assertEqual(antwort.status_code, 403)
        self.assertFalse(Liegenschaft.alle_organisationen.filter(strasse='Seestrasse 12').exists())


class ImportKommandoTests(RollenBasis):
    def _dateien(self, tmp):
        import pathlib
        pfade = {}
        for art, text in (('liegenschaften', LIEGENSCHAFTEN.replace('E1', '')), ('objekte', OBJEKTE)):
            p = pathlib.Path(tmp) / f'{art}.csv'
            p.write_text(text, encoding='utf-8')
            pfade[art] = str(p)
        return pfade

    def test_trockenlauf_und_import(self):
        import tempfile
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with tempfile.TemporaryDirectory() as tmp:
            p = self._dateien(tmp)
            vorher = _zaehle(self.org)
            call_command('daten_importieren', organisation=self.org.pk, trockenlauf=True,
                         liegenschaften=p['liegenschaften'], objekte=p['objekte'], stdout=io.StringIO())
            self.assertEqual(_zaehle(self.org), vorher)
            call_command('daten_importieren', organisation=self.org.pk,
                         liegenschaften=p['liegenschaften'], objekte=p['objekte'], stdout=io.StringIO())
            self.assertEqual([x - y for x, y in zip(_zaehle(self.org), vorher)], [0, 1, 2, 0, 0])
            with self.assertRaises(CommandError):               # ohne Organisation geht nichts
                call_command('daten_importieren', organisation=999999, liegenschaften=p['liegenschaften'], stdout=io.StringIO())

    def test_fehler_ergibt_commanderror_und_nichts_angelegt(self):
        import pathlib
        import tempfile
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / 'l.csv'
            p.write_text('schluessel;strasse;plz;ort\nL1;Seeweg 1;80;Zürich\n', encoding='utf-8')
            vorher = _zaehle(self.org)
            with self.assertRaises(CommandError):
                call_command('daten_importieren', organisation=self.org.pk, liegenschaften=str(p), stdout=io.StringIO())
            self.assertEqual(_zaehle(self.org), vorher)
