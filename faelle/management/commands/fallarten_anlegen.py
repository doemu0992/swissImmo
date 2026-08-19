"""Legt die Standard-Fallarten mit ihren Schritten an — je Organisation.

Idempotent: Ein zweiter Lauf ändert nichts. Bestehende Schritte werden **nicht**
überschrieben, denn eine Verwaltung darf ihre Vorlagen anpassen, ohne dass der
nächste Lauf sie zurücksetzt. Neue Schritte einer Vorlage kommen dazu.

    manage.py fallarten_anlegen                 alle Organisationen
    manage.py fallarten_anlegen --organisation 3
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import Organisation
from faelle.models import Fallart, SchrittVorlage

# (etappe_nr, etappe, bezeichnung, pflicht, frist_regel, hinweis)
VORLAGEN = {
    'mieterwechsel': ('Mieterwechsel', 'faelle', [
        (1, 'Kündigung', 'Kündigung erfassen, Termin prüfen', True, '', ''),
        (1, 'Kündigung', 'Kündigungsbestätigung versenden', True, 'zugang+5', ''),
        (2, 'Ausschreibung', 'Exposé erstellen', True, '', ''),
        (2, 'Ausschreibung', 'Auf Kanälen publizieren', True, '', ''),
        (2, 'Ausschreibung', 'Besichtigung durchführen', True, '', ''),
        (2, 'Ausschreibung', 'Bewerbungen prüfen und vergleichen', True, '', ''),
        (3, 'Neuer Vertrag', 'Zuschlag erteilen, Absagen versenden', True, '', ''),
        (3, 'Neuer Vertrag', 'Anfangsmietzins prüfen', True, '',
         'Erhöhung gegenüber dem Vormieter kann formularpflichtig sein.'),
        (3, 'Neuer Vertrag', 'Vertrag erstellen und signieren lassen', True, '', ''),
        (3, 'Neuer Vertrag', 'Kaution einfordern, Sperrkonto eröffnen', True, '', ''),
        (4, 'Abnahme', 'Rückgabetermin vereinbaren', True, 'vertragsende-14', ''),
        (4, 'Abnahme', 'Protokoll erfassen, Mängel rügen', True, 'vertragsende-0',
         'Die Rüge muss bei der Rückgabe erfolgen.'),
        (4, 'Abnahme', 'Zählerstände und Schlüssel aufnehmen', True, 'vertragsende-0', ''),
        (5, 'Endabrechnung', 'Mängel bewerten, Lebensdauer anrechnen', True, '', ''),
        (5, 'Endabrechnung', 'Nebenkosten anteilig abrechnen', True, '', ''),
        (5, 'Endabrechnung', 'Kaution abrechnen und freigeben', True, 'rueckgabe+30', ''),
    ]),
    'zahlungsverzug': ('Zahlungsverzug', 'faelle', [
        (1, 'Mahnung', 'Zahlungserinnerung', True, '', ''),
        (1, 'Mahnung', 'Mahnung Stufe 1', True, '', ''),
        (1, 'Mahnung', 'Mahnung Stufe 2', True, '', ''),
        (2, 'Fristansetzung', 'Zahlungsfrist mit Kündigungsandrohung', True, '',
         'Fristlänge und Folgen prüfen — siehe Regelwerk.'),
        (2, 'Fristansetzung', 'Fristablauf überwachen', True, '', ''),
        (3, 'Folge', 'Kündigung oder Verrechnung entscheiden', True, '',
         'Bei bereits gekündigtem Verhältnis ist eine weitere Kündigung gegenstandslos.'),
        (3, 'Folge', 'Betreibung einleiten', False, '', ''),
    ]),
    'schaden': ('Schaden', 'faelle', [
        (1, 'Aufnahme', 'Meldung erfassen, Fotos sichern', True, '', ''),
        (1, 'Aufnahme', 'Triage: Ursache und Kostenträger bestimmen', True, '',
         'Eigentümer, Versicherung, Mieter oder Hausrat des Mieters.'),
        (2, 'Offerte', 'Offerten einholen', True, '', ''),
        (2, 'Offerte', 'Versicherung melden', False, '', ''),
        (3, 'Freigabe', 'Freigabe einholen', True, '',
         'Über der Kompetenzsumme entscheidet die Eigentümerschaft.'),
        (4, 'Ausführung', 'Auftrag erteilen', True, '', ''),
        (4, 'Ausführung', 'Ausführung kontrollieren', True, '', ''),
        (5, 'Abschluss', 'Rechnung prüfen und verbuchen', True, '', ''),
    ]),
    'mietzinsanpassung': ('Mietzinsanpassung', 'faelle', [
        (1, 'Berechnung', 'Anpassung je Vertrag berechnen', True, '',
         'Referenzzins, Teuerung und Kostensteigerung einzeln ausweisen.'),
        (2, 'Freigabe', 'Eigentümerschaft vorlegen', True, '', ''),
        (3, 'Zustellung', 'Formulare und Schreiben erstellen', True, '',
         'Erhöhungen brauchen das amtliche kantonale Formular.'),
        (3, 'Zustellung', 'Zustellung fristgerecht veranlassen', True, '', ''),
        (4, 'Wirksamkeit', 'Anfechtungsfrist überwachen', True, '', ''),
        (4, 'Wirksamkeit', 'Sollstellung anpassen', True, '', ''),
    ]),
    'erstvermietung': ('Erstvermietung', 'faelle', [
        (1, 'Ausschreibung', 'Exposé erstellen', True, '', ''),
        (1, 'Ausschreibung', 'Auf Kanälen publizieren', True, '', ''),
        (2, 'Auswahl', 'Besichtigungen durchführen', True, '', ''),
        (2, 'Auswahl', 'Bewerbungen vergleichen', True, '',
         'Kriterien vor der ersten Sichtung festlegen und datieren.'),
        (3, 'Vertrag', 'Zuschlag und Absagen', True, '', ''),
        (3, 'Vertrag', 'Vertrag erstellen und signieren lassen', True, '', ''),
        (3, 'Vertrag', 'Kaution einfordern', True, '', ''),
        (4, 'Übergabe', 'Antrittsprotokoll erfassen', True, '',
         'Ohne Antrittsprotokoll ist der Zustand bei Einzug später nicht belegbar.'),
    ]),
}


class Command(BaseCommand):
    help = 'Legt die Standard-Fallarten je Organisation an (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Organisation (ID).')

    @transaction.atomic
    def handle(self, *args, **opt):
        # `verbosity` wird beachtet, weil dieser Befehl in Tests aufgerufen
        # wird: Ohne diese Prüfung schreibt er auch bei `verbosity=0` zwei
        # Zeilen je Organisation in die Testausgabe und verdeckt dort, worauf
        # es ankommt.
        laut = opt.get('verbosity', 1) >= 1
        organisationen = Organisation.objects.all()
        if opt['organisation']:
            organisationen = organisationen.filter(pk=opt['organisation'])
        if not organisationen:
            if laut:
                self.stdout.write('Keine Organisation gefunden — nichts zu tun.')
            return

        for org in organisationen:
            neu_arten = neu_schritte = 0
            for schluessel, (bez, ent, schritte) in VORLAGEN.items():
                art, erzeugt = Fallart.alle_organisationen.get_or_create(
                    organisation=org, schluessel=schluessel,
                    defaults={'bezeichnung': bez, 'entitlement': ent})
                neu_arten += int(erzeugt)
                vorhanden = set(
                    SchrittVorlage.alle_organisationen
                    .filter(fallart=art).values_list('nr', flat=True))
                for nr, (etnr, etappe, bez_s, pflicht, regel, hinweis) in enumerate(
                        schritte, start=1):
                    if nr in vorhanden:
                        continue
                    SchrittVorlage(
                        fallart=art, nr=nr, etappe_nr=etnr, etappe=etappe,
                        bezeichnung=bez_s, pflicht=pflicht,
                        frist_regel=regel, hinweis=hinweis).save()
                    neu_schritte += 1
            if laut:
                self.stdout.write(
                    f'  {org}: {neu_arten} Fallarten, {neu_schritte} Schritte neu')
        if laut:
            self.stdout.write(self.style.SUCCESS('Fertig.'))
