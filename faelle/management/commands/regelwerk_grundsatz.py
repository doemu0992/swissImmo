"""Legt je Organisation einen Grund-Regelsatz an — ausdrücklich ungeprüft.

WARUM ALS BEFEHL UND NICHT BEIM ANLEGEN DER ORGANISATION

Ein Regelsatz, der von selbst entsteht, sieht aus wie eine Zusicherung. Er ist
aber ein **Entwurf**: die gesetzliche Grundregel für Wohnräume, ohne
ortsübliche Termine, ohne kantonale Besonderheit, ohne Geschäftsräume. Wer ihn
will, ruft ihn ab; dann ist es eine Entscheidung und kein Nebeneffekt.

WAS ANGELEGT WIRD

    Frist       drei Monate (Art. 266c OR — Mindestfrist für Wohnräume)
    Termine     KEINE. Das Feld bleibt leer, und das ist die wichtigste
                Entscheidung dieses Befehls: Ortsübliche Termine sind kantonal
                verschieden. Ein hier eingetragenes 31.03/30.06/30.09 wäre für
                einen Teil der Schweiz schlicht falsch und würde als geprüfte
                Regel aussehen. Ohne Termine greift die Prüfung auf das zurück,
                was im einzelnen Vertrag steht — die einzige Angabe, die für
                diesen Vertrag mit Sicherheit gilt.
    geprueft    False. Der Satz warnt, er sperrt nicht.

Der Befehl ist wiederholbar: Ein bestehender Regelsatz wird nicht angefasst.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = ('Legt je Organisation einen ungeprüften Grund-Regelsatz an '
            '(Kündigungsfrist drei Monate, Termine aus dem Vertrag).')

    def add_arguments(self, parser):
        parser.add_argument(
            '--organisation', type=int, default=None,
            help='Nur für diese Organisations-ID. Ohne Angabe: für alle.')
        parser.add_argument(
            '--probe', action='store_true',
            help='Nur zeigen, was geschähe — nichts schreiben.')

    def handle(self, *args, **optionen):
        from crm.models import Organisation
        from faelle.regelwerk_models import Regel, Regelsatz

        organisationen = Organisation.objects.all()
        if optionen['organisation']:
            organisationen = organisationen.filter(pk=optionen['organisation'])

        angelegt = uebersprungen = 0
        for organisation in organisationen:
            # `alle_organisationen`, weil dieser Befehl bewusst über alle
            # Mandanten läuft — der ausdrücklich benannte Weg, nicht eine
            # stille Umgehung des Standardmanagers.
            bestand = Regelsatz.alle_organisationen.filter(
                organisation=organisation, kanton='')
            if bestand.exists():
                self.stdout.write(
                    f'  · {organisation.firma}: hat bereits '
                    f'«{bestand.first()}» — unverändert.')
                uebersprungen += 1
                continue

            if optionen['probe']:
                self.stdout.write(f'  + {organisation.firma}: würde angelegt.')
                angelegt += 1
                continue

            satz = Regelsatz.alle_organisationen.create(
                organisation=organisation,
                bezeichnung='Grundsatz Wohnräume (Entwurf)',
                kanton='', stand=timezone.localdate(), geprueft=False,
                hinweis=('Angelegt von `manage.py regelwerk_grundsatz`. Gibt die '
                         'gesetzliche Mindestfrist nach Art. 266c OR wieder. '
                         'Ortsübliche Kündigungstermine sind NICHT hinterlegt — '
                         'es gilt, was im jeweiligen Vertrag steht. Vor dem '
                         'Kennzeichen «geprüft» juristisch gegenlesen lassen.'),
                aktiv=True)
            Regel.alle_organisationen.create(
                organisation=organisation, regelsatz=satz,
                art=Regel.KUENDIGUNGSTERMIN,
                verbindlichkeit=Regel.WARNUNG,
                parameter={'frist_monate': 3},
                begruendung='Art. 266c OR: drei Monate bei Wohnräumen.',
                aktiv=True)
            # KAUTIONSHOECHSTBETRAG — und warum er NUR fuer Wohnraeume gilt
            #
            # Art. 257e Abs. 2 OR: Bei Wohnraeumen darf die Sicherheit drei
            # Monatszinse nicht uebersteigen. Bei GESCHAEFTSRAEUMEN gilt die
            # Grenze NICHT — dort ist sie frei vereinbar.
            #
            # Das steht bereits im Modell (`Mietvertrag.kaution_max_monate`
            # gibt 3 bei `mietrecht_kategorie == 'wohnen'` und sonst None).
            # Die Regel wiederholt es nicht, sie macht es pruefbar: Der
            # Parameter nennt die Grenze UND den Geltungsbereich, damit eine
            # Verwaltung mit Gewerbebestand nicht faelschlich gewarnt wird.
            #
            # Eine zu hohe Kaution ist nicht bloss unschoen: Die Vereinbarung
            # ist insoweit nichtig, und der Mieter kann den Ueberschuss
            # jederzeit zurueckfordern. Deshalb gehoert sie zu den Regeln, die
            # nach juristischer Pruefung SPERREN sollten — bis dahin warnt sie,
            # wie alle anderen auch.
            Regel.alle_organisationen.create(
                organisation=organisation, regelsatz=satz,
                art=Regel.KAUTION_HOECHSTBETRAG,
                verbindlichkeit=Regel.WARNUNG,
                parameter={'hoechst_monate': 3, 'gilt_fuer': ['wohnen']},
                begruendung=('Art. 257e Abs. 2 OR: hoechstens drei '
                             'Monatszinse bei Wohnraeumen. Bei '
                             'Geschaeftsraeumen frei vereinbar.'),
                aktiv=True)
            self.stdout.write(self.style.SUCCESS(
                f'  + {organisation.firma}: «{satz}» angelegt.'))
            angelegt += 1

        self.stdout.write('')
        self.stdout.write(f'{angelegt} angelegt, {uebersprungen} unverändert.')
        if angelegt and not optionen['probe']:
            self.stdout.write(self.style.WARNING(
                'Die Regeln sind NICHT juristisch geprüft und warnen deshalb '
                'nur. Sie sperren erst, wenn jemand den Regelsatz unter '
                '/neu/regelwerk/ als geprüft kennzeichnet.'))
