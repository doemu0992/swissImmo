"""Raumbuch anlegen: Raumnamen vergeben und der Assistent «aus der Wohnungsgrösse».

Bis hierher hiess ein Raum aus dem Katalog immer wie sein Typ — «Zimmer» liess sich nur einmal laden, und eine
3.5-Zimmer-Wohnung bekam ein Zimmer. Jetzt sind Raumtyp (aus dem Katalog: welche Bauteile) und Raumname (wie der
Raum in der Wohnung heisst) getrennt:

* Typen mit mehreren Räumen (``NUMMERIERT``: Zimmer, Schlafzimmer) werden durchnummeriert, «Schlafzimmer 1», «Schlafzimmer 2».
* Alle anderen Typen gibt es einmal je Wohnung; ein zweites Laden ändert nichts («bereits vollständig»).
* Wer einen Namen vorgibt («Büro», «Gästezimmer»), bekommt genau diesen.

Der Name ist, was die Abnahme später übernimmt (``abnahme_bauteile.raumtyp`` erkennt den Typ am Namen), und was im
Raumbuch gruppiert. Er muss deshalb eindeutig je Wohnung sein.

Der Assistent schlägt aus der Zimmerzahl vor, welche Räume die Wohnung hat — als Zahlen je Typ, die der Mensch
ändert, bevor etwas angelegt wird. Das halbe Zimmer ist in der Schweiz uneinheitlich (Essnische, Büro, Entrée) und
wird deshalb nur als ein weiteres «Zimmer» vorgeschlagen.
"""
import re
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from core.utils.betrag import betrag_oder_none

from .raumkatalog import NUMMERIERT, RAUM_KATALOG

MAX_NAME = 60
#: Obergrenze je Typ im Assistenten (Schutz gegen Tippfehler wie 40 Zimmer).
MAX_JE_TYP = 10

#: Die Räume des Assistenten in der Reihenfolge der Anzeige: (Typ, Beschriftung).
ASSISTENT_TYPEN = [
    ('Küche', _('Küche')),
    ('Wohnzimmer', _('Wohnzimmer / Essen')),
    ('Schlafzimmer', _('Schlafzimmer')),
    ('Zimmer', _('Weitere Zimmer')),
    ('Bad / WC', _('Bad / WC')),
    ('Gäste-WC', _('Gäste-WC')),
    ('Korridor / Entrée', _('Korridor / Entrée')),
    ('Balkon / Terrasse', _('Balkon / Terrasse')),
    ('Reduit', _('Reduit')),
    ('Waschküche', _('Waschküche')),
    ('Kellerabteil', _('Kellerabteil')),
    ('Estrich / Dachabteil', _('Estrich / Dachabteil')),
]
ZIMMER_MIN, ZIMMER_MAX = Decimal('1'), Decimal('8')


def _zahl(wert):
    """Die Zimmerzahl als Decimal (> 0), sonst None. Gelesen wird über `core.utils.betrag` wie jede Zahl im Programm."""
    z = betrag_oder_none(wert)
    return z if z is not None and z > 0 else None


def vorschlag(zimmer):
    """Zahl der Räume je Typ für eine Wohnung mit ``zimmer`` Zimmern (3.5 → Wohnzimmer, 2 Schlafzimmer, 1 weiteres).

    Ein Wohnzimmer ist immer dabei; die übrigen ganzen Zimmer sind Schlafzimmer, ein halbes Zimmer ein weiteres
    «Zimmer». Gäste-WC erst ab 4.5 Zimmern. Ohne gültige Zahl: 3 Zimmer."""
    z = _zahl(zimmer) or Decimal('3')
    z = min(max(z, ZIMMER_MIN), ZIMMER_MAX)
    ganz = int(z)
    halb = 1 if z - ganz >= Decimal('0.5') else 0
    return {
        'Küche': 1, 'Wohnzimmer': 1,
        'Schlafzimmer': max(ganz - 1, 0), 'Zimmer': halb,
        'Bad / WC': 1, 'Gäste-WC': 1 if z >= Decimal('4.5') else 0,
        'Korridor / Entrée': 1, 'Balkon / Terrasse': 1, 'Reduit': 0, 'Waschküche': 0,
        'Kellerabteil': 1, 'Estrich / Dachabteil': 0,
    }


def vorschlaege_je_zimmerzahl():
    """Für die Seite: der Vorschlag zu jeder wählbaren Zimmerzahl (1, 1.5 … 8), damit der Browser nichts rechnen muss."""
    ergebnis, z = {}, ZIMMER_MIN
    while z <= ZIMMER_MAX:
        ergebnis[f'{z.normalize():f}'] = vorschlag(z)
        z += Decimal('0.5')
    return ergebnis


def _nummer(name, typ):
    """Die Nummer eines Raumnamens wie «Zimmer 2» (ohne Zahl: 1, kein Treffer: 0)."""
    m = re.fullmatch(rf'{re.escape(typ)}(?:\s+(\d+))?', name.strip(), flags=re.IGNORECASE)
    if not m:
        return 0
    return int(m.group(1)) if m.group(1) else 1


def bereinigt(name):
    return ' '.join((name or '').split())[:MAX_NAME]


def neue_namen(typ, anzahl, vorhandene):
    """Die Raumnamen für ``anzahl`` neue Räume des Typs, gegeben die ``vorhandene`` Raumnamen der Wohnung.

    Nummerierte Typen zählen ab dem höchsten vorhandenen weiter, die übrigen gibt es nur einmal: existiert der Raum
    schon, kommt nichts dazu."""
    vorhandene = list(vorhandene)
    if typ in NUMMERIERT:
        start = max((_nummer(v, typ) for v in vorhandene), default=0)
        return [f'{typ} {i}' for i in range(start + 1, start + 1 + max(anzahl, 0))]
    vorhandene_klein = {v.casefold() for v in vorhandene}
    return [typ] if anzahl > 0 and typ.casefold() not in vorhandene_klein else []


def raum_anlegen(einheit, typ, name):
    """Legt die Katalog-Ausstattung des Typs unter dem Raumnamen an (vorhandene Kategorien bleiben).
    Gibt die Zahl neuer Elemente zurück."""
    from portfolio.models import Ausstattung
    elemente = RAUM_KATALOG[typ]
    vorhanden = set(Ausstattung.objects.filter(einheit=einheit, raum=name).values_list('kategorie', flat=True))
    neu = 0
    for i, (kat, jahre) in enumerate(elemente):
        if kat in vorhanden:
            continue
        Ausstattung.objects.create(einheit=einheit, raum=name, kategorie=kat,
                                   lebensdauer_jahre=jahre, zustand='gut', sortierung=i)
        neu += 1
    return neu


def plan_aus_formular(post):
    """Die Zahl je Typ aus dem Formular des Assistenten: nur bekannte Typen, ganze Zahlen 0…MAX_JE_TYP."""
    plan = {}
    for typ, _beschriftung in ASSISTENT_TYPEN:
        roh = (post.get(f'anzahl_{typ}') or '0').strip()
        n = int(roh) if roh.isdigit() else 0
        plan[typ] = min(n, MAX_JE_TYP)
    return plan


def anlegen(einheit, plan):
    """Legt die Räume des Plans an. Gibt ``(angelegte Raumnamen, übersprungene Typen)`` zurück.

    «Übersprungen»: ein einmaliger Typ (Küche, Bad …), der in der Wohnung schon vorkommt."""
    from portfolio.models import Ausstattung
    vorhandene = list(dict.fromkeys(Ausstattung.objects.filter(einheit=einheit).values_list('raum', flat=True)))
    angelegt, uebersprungen = [], []
    for typ, _beschriftung in ASSISTENT_TYPEN:
        anzahl = plan.get(typ, 0)
        if anzahl <= 0:
            continue
        namen = neue_namen(typ, anzahl if typ in NUMMERIERT else 1, vorhandene)
        if not namen:
            uebersprungen.append(typ)
            continue
        for name in namen:
            raum_anlegen(einheit, typ, name)
            vorhandene.append(name)
            angelegt.append(name)
    return angelegt, uebersprungen
