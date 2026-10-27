"""Bestandsbericht Index- und Staffelmiete (nur lesen).

    python manage.py mietzinsmodell_bestand [--json] [--organisation ID] [--mit-archiviert]

Hält jeden bestehenden Index- und Staffelvertrag (und jeden Vertrag, der trotz festem Mietzins
Staffelstufen trägt) gegen `core/services/mietzinsmodell.pruefe` und listet die Verstösse mit Regel
und Artikel. Hinweise (Stufe «hinweis») gehören nicht dazu: Gemeldet wird, was heute das Speichern
verhindern würde.

Es wird nichts verändert. Altverträge werden nicht blockiert und nicht korrigiert; ob ein Vertrag
nachgebessert, neu abgeschlossen oder so belassen wird, entscheidet ein Mensch (Fachperson).

JE ORGANISATION EIN DURCHGANG (Skill mandantentrennung): Die Verträge kommen über den
Mandantenkontext der jeweiligen Organisation, nie in einer gemeinsamen Liste.
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import Q

from core.services.mietzinsmodell import pruefe_vertrag, sperren
from core.tenancy import organisation_kontext
from crm.models import Organisation
from rentals.models import Mietvertrag


class Command(BaseCommand):
    help = 'Listet Index- und Staffelverträge, die die Regeln von Art. 269b/269c OR verletzen (verändert nichts).'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Ausgabe als JSON statt Tabelle')
        parser.add_argument('--organisation', type=int, default=None, help='Nur diese Organisation (ID)')
        parser.add_argument('--mit-archiviert', action='store_true', help='Auch archivierte Verträge prüfen')

    def handle(self, *args, **opts):
        organisationen = Organisation.objects.order_by('pk')
        if opts['organisation']:
            organisationen = organisationen.filter(pk=opts['organisation'])
        ergebnis = [self._organisation(org, opts['mit_archiviert']) for org in organisationen]
        if opts['json']:
            self.stdout.write(json.dumps({
                'organisationen': ergebnis,
                'gesamt': {'geprueft': sum(o['geprueft'] for o in ergebnis),
                           'vertraege_mit_verstoss': sum(o['vertraege_mit_verstoss'] for o in ergebnis),
                           'verstoesse': sum(len(o['verstoesse']) for o in ergebnis)},
            }, ensure_ascii=False, indent=2))
            return
        self._tabelle(ergebnis)

    def _organisation(self, org, mit_archiviert):
        with organisation_kontext(org):
            vertraege = (Mietvertrag.objects
                         .filter(Q(mietzins_modell__in=('index', 'staffel')) | Q(staffelstufen__isnull=False))
                         .select_related('mieter', 'einheit__liegenschaft').prefetch_related('staffelstufen')
                         .distinct().order_by('pk'))
            if not mit_archiviert:
                vertraege = vertraege.exclude(status='archiviert')
            verstoesse, betroffen, geprueft = [], set(), 0
            for v in vertraege:
                geprueft += 1
                for b in sperren(pruefe_vertrag(v)):
                    betroffen.add(v.pk)
                    verstoesse.append({
                        'vertrag_id': v.pk, 'status': v.status, 'modell': v.mietzins_modell,
                        'objekt': f'{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}',
                        'mieter': v.mieter.display_name, 'regel': b.regel, 'artikel': b.artikel,
                        'text': b.text, 'zeile': b.zeile,
                    })
        return {'organisation_id': org.pk, 'organisation': org.firma, 'geprueft': geprueft,
                'vertraege_mit_verstoss': len(betroffen), 'verstoesse': verstoesse}

    def _tabelle(self, ergebnis):
        for o in ergebnis:
            self.stdout.write(f"\n{o['organisation']} (Organisation {o['organisation_id']}): "
                              f"{o['geprueft']} Verträge geprüft, {o['vertraege_mit_verstoss']} mit Verstoss")
            if not o['verstoesse']:
                self.stdout.write(self.style.SUCCESS('  Keine Verstösse.'))
                continue
            zeilen = [('Vertrag', 'Modell', 'Status', 'Regel', 'Artikel', 'Objekt / Mieter', 'Befund')]
            for x in o['verstoesse']:
                zeilen.append((str(x['vertrag_id']), x['modell'], x['status'], x['regel'], x['artikel'],
                               f"{x['objekt']} / {x['mieter']}", x['text']))
            breiten = [max(len(z[i]) for z in zeilen) for i in range(len(zeilen[0]) - 1)]
            for n, z in enumerate(zeilen):
                self.stdout.write('  ' + '  '.join(z[i].ljust(breiten[i]) for i in range(len(breiten))) + '  ' + z[-1])
                if n == 0:
                    self.stdout.write('  ' + '  '.join('-' * b for b in breiten) + '  ' + '-' * 7)
        gesamt = sum(len(o['verstoesse']) for o in ergebnis)
        self.stdout.write(f'\n{gesamt} Verstoss/Verstösse insgesamt. Es wurde nichts verändert.')
