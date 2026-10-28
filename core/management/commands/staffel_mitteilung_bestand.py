"""Bestandsbericht Staffelmiete: Stufen ohne belegte, rechtzeitige Mitteilung (nur lesen).

    python manage.py staffel_mitteilung_bestand [--json] [--organisation ID]

Seit 1.10.2025 verlangt Art. 269d Abs. 5 OR die schriftliche Mitteilung jeder Staffelerhöhung. Die
Sollstellung verrechnet eine Stufe ab 1.10.2025 nur noch mit belegter, rechtzeitiger Mitteilung
(`core/services/staffel_mitteilung.stufe_wirkt`). Dieser Bericht listet, wo das schon eingetretene
Stufen betrifft, und nennt die bereits gestellten Monatsrechnungen ab dem Eintritt.

Es wird NICHTS verändert: weder Stufen noch gebuchte Rechnungen. Ob eine zu viel gestellte Miete
korrigiert, gutgeschrieben oder nachträglich mitgeteilt wird, entscheidet ein Mensch (Fachperson).

JE ORGANISATION EIN DURCHGANG (Skill mandantentrennung).
"""
import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services.staffel_mitteilung import INKRAFT_MITTEILUNG, stufe_wirkt
from core.tenancy import organisation_kontext
from crm.models import Organisation
from rentals.models import Mietvertrag


class Command(BaseCommand):
    help = ('Listet eingetretene Staffelstufen ab 1.10.2025 ohne belegte, rechtzeitige Mitteilung '
            '(verändert nichts).')

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Ausgabe als JSON statt Tabelle')
        parser.add_argument('--organisation', type=int, default=None, help='Nur diese Organisation (ID)')

    def handle(self, *args, **opts):
        organisationen = Organisation.objects.order_by('pk')
        if opts['organisation']:
            organisationen = organisationen.filter(pk=opts['organisation'])
        heute = timezone.localdate()
        ergebnis = [self._organisation(org, heute) for org in organisationen]
        if opts['json']:
            self.stdout.write(json.dumps({'organisationen': ergebnis}, ensure_ascii=False, indent=2))
            return
        for o in ergebnis:
            self.stdout.write(f"\n{o['organisation']} (Organisation {o['organisation_id']}): "
                              f"{len(o['stufen'])} Stufe(n) ohne belegte, rechtzeitige Mitteilung")
            for x in o['stufen']:
                self.stdout.write(
                    f"  MV-{x['vertrag_id']} {x['mieter']} · {x['objekt']}: Stufe ab {x['ab']} "
                    f"(Netto CHF {x['netto']}), {x['grund']}; gestellte Monatsrechnungen seit dem Eintritt: "
                    f"{x['rechnungen_seit_eintritt']}")

    def _organisation(self, org, heute):
        from finance.models import DebitorenRechnung
        stufen = []
        with organisation_kontext(org):
            vertraege = (Mietvertrag.objects.filter(mietzins_modell='staffel')
                         .exclude(status__in=('entwurf', 'archiviert'))
                         .select_related('mieter', 'einheit__liegenschaft').prefetch_related('staffelstufen')
                         .order_by('pk'))
            for v in vertraege:
                for st in v.staffelstufen.all():
                    if st.ab_datum < INKRAFT_MITTEILUNG or st.ab_datum > heute or stufe_wirkt(st):
                        continue
                    rechnungen = (DebitorenRechnung.objects.filter(vertrag=v, titel__startswith='Miete & NK',
                                                                   faellig_am__gte=st.ab_datum)
                                  .exclude(status='storniert').count())
                    stufen.append({
                        'vertrag_id': v.pk, 'mieter': v.mieter.display_name,
                        'objekt': f'{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}',
                        'ab': st.ab_datum.strftime('%d.%m.%Y'), 'netto': str(st.netto_mietzins),
                        'grund': ('Mitteilung nicht rechtzeitig versandt (%s)' % st.mitteilung_versandt_am.strftime('%d.%m.%Y')
                                  if st.mitteilung_versandt_am else 'keine Mitteilung als versandt erfasst'),
                        'rechnungen_seit_eintritt': rechnungen,
                    })
        return {'organisation_id': org.pk, 'organisation': org.firma, 'stufen': stufen}
