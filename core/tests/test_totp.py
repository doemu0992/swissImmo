"""TOTP gegen die amtlichen Testvektoren aus RFC 6238, Anhang B.

DER GRUND, WARUM DIESE DATEI DIE WICHTIGSTE DES 2FA-UMBAUS IST

Eine selbst geschriebene Krypto-Rechnung, die nur gegen sich selbst geprüft
wird, ist wertlos: Sie stimmt dann mit ihren eigenen Fehlern überein. Ein
Einmalcode-Verfahren muss aber mit fremden Programmen übereinstimmen — mit
Google Authenticator, 1Password, Aegis. Prüfbar wird das nur über die
Vektoren, die die RFC selbst mitliefert: bekannte Zeitpunkte, bekannte Codes.

Wäre `pyotp` im Einsatz, prüfte man dasselbe — nur eben deren Umsetzung.

    RFC 6238, Anhang B: Geheimnis "12345678901234567890" (ASCII),
    HMAC-SHA-1, 8 Stellen, Schrittweite 30 s.
"""
import base64
import hashlib
import time

from django.test import SimpleTestCase

from core.services import totp

#: Das Geheimnis aus der RFC, in Base32 — so, wie es hier gespeichert würde.
RFC_GEHEIMNIS = base64.b32encode(b'12345678901234567890').decode()

#: (Unixzeit, erwarteter 8-stelliger Code) — RFC 6238, Anhang B, SHA-1-Zeilen.
RFC_VEKTOREN = [
    (59,          '94287082'),
    (1111111109,  '07081804'),
    (1111111111,  '14050471'),
    (1234567890,  '89005924'),
    (2000000000,  '69279037'),
    (20000000000, '65353130'),
]


class RFC6238Tests(SimpleTestCase):
    def test_alle_vektoren_der_rfc(self):
        for zeit, erwartet in RFC_VEKTOREN:
            with self.subTest(zeit=zeit):
                self.assertEqual(
                    totp.code(RFC_GEHEIMNIS, zeit, stellen=8, hashfunktion=hashlib.sha1),
                    erwartet,
                    f'RFC 6238 nennt für t={zeit} den Code {erwartet}.')

    def test_sechsstellig_ist_der_achtstellige_hinten(self):
        # Die Apps zeigen 6 Stellen. Dass das genau die letzten 6 des
        # RFC-Codes sind, folgt aus dem `% 10**stellen` — hier festgehalten,
        # damit ein Umbau der Kürzung auffällt.
        for zeit, erwartet in RFC_VEKTOREN:
            with self.subTest(zeit=zeit):
                self.assertEqual(totp.code(RFC_GEHEIMNIS, zeit), erwartet[-6:])


class FensterTests(SimpleTestCase):
    def test_code_gilt_im_eigenen_fenster(self):
        zeit = 1_700_000_000
        self.assertEqual(
            totp.passendes_fenster(RFC_GEHEIMNIS, totp.code(RFC_GEHEIMNIS, zeit), zeit),
            totp.zaehler_fuer(zeit))

    def test_code_des_vorherigen_fensters_gilt_noch(self):
        # Ohne diese Toleranz scheitert jeder, dessen Telefonuhr ein paar
        # Sekunden nachgeht — und niemand könnte ihm sagen, warum.
        zeit = 1_700_000_000
        vorher = totp.code(RFC_GEHEIMNIS, zeit - totp.SCHRITT)
        self.assertIsNotNone(totp.passendes_fenster(RFC_GEHEIMNIS, vorher, zeit))

    def test_code_zwei_fenster_zurueck_gilt_nicht_mehr(self):
        # Die Gegenprobe zur Toleranz: Sie darf nicht unbegrenzt sein.
        zeit = 1_700_000_000
        zu_alt = totp.code(RFC_GEHEIMNIS, zeit - 2 * totp.SCHRITT)
        self.assertIsNone(totp.passendes_fenster(RFC_GEHEIMNIS, zu_alt, zeit))

    def test_falscher_code_wird_abgewiesen(self):
        self.assertIsNone(totp.passendes_fenster(RFC_GEHEIMNIS, '000000', 1_700_000_000))

    def test_unsinn_wird_abgewiesen_ohne_zu_werfen(self):
        # Was aus einem Formular kommt, ist beliebig. Eine Ausnahme hier wäre
        # ein Fehler 500 auf der Anmeldeseite.
        for eingabe in ('', None, 'abcdef', '12345', '1234567', '12 34 56x'):
            with self.subTest(eingabe=eingabe):
                self.assertIsNone(totp.passendes_fenster(RFC_GEHEIMNIS, eingabe, 1_700_000_000))

    def test_leerzeichen_im_code_stoeren_nicht(self):
        # Manche Apps zeigen «123 456». Das gehört angenommen, nicht bemängelt.
        zeit = 1_700_000_000
        roh = totp.code(RFC_GEHEIMNIS, zeit)
        self.assertIsNotNone(
            totp.passendes_fenster(RFC_GEHEIMNIS, f'{roh[:3]} {roh[3:]}', zeit))


class GeheimnisTests(SimpleTestCase):
    def test_erzeugte_geheimnisse_sind_verschieden(self):
        self.assertNotEqual(totp.geheimnis_erzeugen(), totp.geheimnis_erzeugen())

    def test_erzeugtes_geheimnis_ist_verwendbar(self):
        g = totp.geheimnis_erzeugen()
        self.assertIsNotNone(totp.passendes_fenster(g, totp.code(g), None))

    def test_geheimnis_ohne_fuellzeichen_wird_gelesen(self):
        # Base32 von 20 Bytes ist 32 Zeichen lang und braucht keine Füllung;
        # abgetippte Geheimnisse kommen aber oft mit oder ohne '='.
        g = totp.geheimnis_erzeugen()
        zeit = 1_700_000_000
        self.assertEqual(totp.code(g, zeit), totp.code(g + '======', zeit))

    def test_kleinschreibung_und_leerzeichen_werden_angenommen(self):
        g = totp.geheimnis_erzeugen()
        zeit = 1_700_000_000
        zerlegt = ' '.join(g[i:i + 4] for i in range(0, len(g), 4)).lower()
        self.assertEqual(totp.code(g, zeit), totp.code(zerlegt, zeit))


class EinrichtungsUrlTests(SimpleTestCase):
    def test_url_enthaelt_alles_was_die_app_braucht(self):
        url = totp.einrichtungs_url('JBSWY3DPEHPK3PXP', 'anna@example.ch')
        self.assertTrue(url.startswith('otpauth://totp/'))
        self.assertIn('secret=JBSWY3DPEHPK3PXP', url)
        self.assertIn('issuer=swissImmo', url)
        self.assertIn('period=30', url)
        self.assertIn('digits=6', url)

    def test_sonderzeichen_im_konto_werden_kodiert(self):
        # Ein unkodiertes '@' oder ':' zerlegt die Adresse und die App liest
        # den falschen Kontonamen — oder gar nichts.
        url = totp.einrichtungs_url('JBSWY3DPEHPK3PXP', 'a b:c@example.ch')
        self.assertNotIn(' ', url)
        self.assertIn('swissImmo%3Aa%20b%3Ac%40example.ch', url)

    def test_qr_ist_ein_svg_und_enthaelt_keine_datei(self):
        svg = totp.qr_svg(totp.einrichtungs_url(totp.geheimnis_erzeugen(), 'a@b.ch'))
        self.assertIn('<svg', svg)
        self.assertIn('</svg>', svg)


class ZeitTests(SimpleTestCase):
    def test_ohne_zeitangabe_wird_die_gegenwart_genommen(self):
        g = totp.geheimnis_erzeugen()
        self.assertEqual(totp.code(g), totp.code(g, time.time()))

    def test_zaehler_waechst_je_schritt_um_eins(self):
        self.assertEqual(totp.zaehler_fuer(1_700_000_030) - totp.zaehler_fuer(1_700_000_000), 1)
