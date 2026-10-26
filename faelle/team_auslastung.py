"""Team & Auslastung (Berichte → Team) — wer trägt wie viel, und wo bleibt etwas liegen.

WARUM (UI-Audit 26.10.2026)
Eine Geschäftsleitung fragt zwei Dinge, die bis hierher keine Seite
beantwortete: Ist die Arbeit gerecht verteilt? Und: Halten wir unsere Zeiten
ein? Die Zahlen lagen verstreut — Tickets im Board, Fälle im Arbeitsvorrat,
Abwesenheiten unter Vertretung, Betreuung in der Liegenschaft. Hier stehen sie
je Person nebeneinander, dazu was NIEMANDEM zugeteilt ist.

GEZÄHLT WIRD, WAS IM SYSTEM STEHT
- Tickets: `SchadenMeldung.zugewiesen_an`, offen = jeder Zustand ausser «erledigt»,
  überfällig = `faellig_bis` vor heute.
- Fälle: `Fall.zustaendig`, offen und liegengeblieben nach den Regeln des
  Fall-Querysets (`offen()`, `liegengeblieben()`) — keine eigene Fassung.
- Termine: geplante der nächsten sieben Tage.
- Betreuung: `Liegenschaft.betreut_von`.

DURCHLAUFZEIT
Ein erledigtes Ticket trägt kein eigenes Erledigt-Datum; die letzte Änderung
(`aktualisiert_am`) ist die beste vorhandene Näherung — die Seite nennt sie so.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

#: Altersstufen offener Tickets (Tage seit Meldung).
ALTERSSTUFEN = ((0, 7, '0–7'), (8, 30, '8–30'), (31, 90, '31–90'), (91, None, '> 90'))


def team(organisation):
    """Aktive Team-Mitglieder der Organisation — ohne reine Portal-Zugänge."""
    User = get_user_model()
    from core.auth import ROLLE_EIGENTUEMER
    leute = []
    for u in (User.objects.filter(is_active=True, mitgliedschaften__organisation=organisation)
              .select_related('mieter_profil', 'eigentuemer_profil').prefetch_related('groups')
              .order_by('first_name', 'last_name', 'username').distinct()):
        if getattr(u, 'mieter_profil', None) is not None or getattr(u, 'eigentuemer_profil', None) is not None:
            continue
        rollen = [g.name for g in u.groups.all()]
        if rollen == [ROLLE_EIGENTUEMER]:
            continue
        leute.append(u)
    return leute


def auslastung(organisation, heute=None):
    from faelle.models import Abwesenheit, Fall, Termin
    from portfolio.models import Liegenschaft
    from tickets.models import SchadenMeldung

    heute = heute or timezone.localdate()
    jetzt = timezone.now()
    leute = team(organisation)
    ids = [u.id for u in leute]

    offen_t = SchadenMeldung.objects.exclude(status='erledigt')
    t_je = {r['zugewiesen_an']: r for r in offen_t.filter(zugewiesen_an__in=ids).values('zugewiesen_an').annotate(
        n=Count('id'), ueber=Count('id', filter=Q(faellig_bis__lt=heute)))}
    f_je = {r['zustaendig']: r['n'] for r in Fall.objects.offen().filter(zustaendig__in=ids)
            .values('zustaendig').annotate(n=Count('id'))}
    fl_je = {r['zustaendig']: r['n'] for r in Fall.objects.liegengeblieben(jetzt).filter(zustaendig__in=ids)
             .values('zustaendig').annotate(n=Count('id'))}
    termin_je = {r['zustaendig']: r['n'] for r in Termin.objects.filter(
        zustaendig__in=ids, status='geplant', beginn__date__gte=heute, beginn__date__lte=heute + timedelta(days=6))
        .values('zustaendig').annotate(n=Count('id'))}
    lg_je = {r['betreut_von']: r['n'] for r in Liegenschaft.objects.filter(betreut_von__in=ids)
             .values('betreut_von').annotate(n=Count('id'))}
    weg = {a.benutzer_id: a for a in Abwesenheit.objects.filter(benutzer__in=ids, von__lte=heute, bis__gte=heute)
           .select_related('vertreten_durch')}

    zeilen = []
    for u in leute:
        t = t_je.get(u.id, {})
        z = {
            'u': u, 'name': u.get_full_name() or u.username,
            'kuerzel': ''.join(w[0] for w in (u.get_full_name() or u.username).split()[:2]).upper(),
            'rolle': ', '.join(g.name for g in u.groups.all()) or ('Superuser' if u.is_superuser else '—'),
            'liegenschaften': lg_je.get(u.id, 0),
            'tickets': t.get('n', 0), 'tickets_ueber': t.get('ueber', 0),
            'faelle': f_je.get(u.id, 0), 'faelle_liegen': fl_je.get(u.id, 0),
            'termine': termin_je.get(u.id, 0),
            'abwesend': weg.get(u.id),
        }
        # Last: offene Arbeit, Überfälliges zählt doppelt — es ist schon zu spät.
        z['last'] = z['tickets'] + z['faelle'] + z['tickets_ueber'] + z['faelle_liegen']
        zeilen.append(z)
    hoechst = max((z['last'] for z in zeilen), default=0)
    for z in zeilen:
        z['anteil'] = round(z['last'] / hoechst * 100) if hoechst else 0
        z['stufe'] = ('crit' if z['tickets_ueber'] or z['faelle_liegen'] > 2
                      else 'warn' if z['faelle_liegen'] or (z['abwesend'] and z['last']) else 'good')
    zeilen.sort(key=lambda z: (-z['last'], z['name']))

    # Was niemandem gehört
    niemand = {
        'tickets': offen_t.filter(zugewiesen_an__isnull=True).count(),
        'faelle': Fall.objects.offen().filter(zustaendig__isnull=True).count(),
        'liegenschaften': Liegenschaft.objects.filter(betreut_von__isnull=True).count(),
    }

    # Tickets: Alter der offenen, Durchlaufzeit und Termintreue der erledigten
    alter = []
    for von, bis, label in ALTERSSTUFEN:
        q = offen_t.filter(erstellt_am__lte=jetzt - timedelta(days=von))
        if bis is not None:
            q = q.filter(erstellt_am__gt=jetzt - timedelta(days=bis + 1))
        alter.append({'label': label, 'n': q.count(), 'stufe': 'crit' if von > 30 else 'warn' if von > 7 else 'good'})
    alter_max = max((a['n'] for a in alter), default=0)
    for a in alter:
        a['anteil'] = round(a['n'] / alter_max * 100) if alter_max else 0

    erledigt = list(SchadenMeldung.objects.filter(status='erledigt', aktualisiert_am__gte=jetzt - timedelta(days=90))
                    .values_list('erstellt_am', 'aktualisiert_am', 'faellig_bis'))
    tage = [max(0, (b - a).days) for a, b, _f in erledigt if a and b]
    mit_ziel = [(b, f) for _a, b, f in erledigt if f and b]
    return {
        'zeilen': zeilen, 'niemand': niemand,
        'offen_tickets': offen_t.count(), 'ueber_tickets': offen_t.filter(faellig_bis__lt=heute).count(),
        'offen_faelle': Fall.objects.offen().count(), 'liegen_faelle': Fall.objects.liegengeblieben(jetzt).count(),
        'alter': alter,
        'erledigt_n': len(erledigt),
        'durchlauf': round(sum(tage) / len(tage), 1) if tage else None,
        'termintreue': round(sum(1 for b, f in mit_ziel if timezone.localtime(b).date() <= f) / len(mit_ziel) * 100) if mit_ziel else None,
        'abwesend_n': sum(1 for z in zeilen if z['abwesend']),
    }
