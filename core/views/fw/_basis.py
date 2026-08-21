# core/views/fw/_basis.py
#
# Die Helfer, die MEHR ALS EIN Block braucht. Sie stehen hier, weil sie sonst
# beim Umzug ihres Heimatblocks mitwandern und den anderen Bloecken fehlen —
# das ist der wahrscheinlichste Weg, Etappe 1 zu brechen
# (siehe docs/ETAPPE-1-ZERLEGEN.md).
#
# Sechs der acht lagen bis hierher MITTEN in einem Block:
#   _kaution_bilanziert   Block 1    ·  _mwst_beleg/_bereits_verbucht/_periode  Block 27
#   _pendenz_ziel         Block 29   ·  _vermietung_pipeline                    Block 32
# Nur _global_filter und _num standen schon im Kopfbereich.
#
# `_global_filter` ist der Einstiegspunkt jeder /neu/-View und zugleich der
# Ansatzpunkt fuer Etappe 4 (Mandantentrennung) — er steht deshalb bewusst
# sichtbar und allein, nicht verstreut.
#
# UNVERAENDERT UEBERNOMMEN, Zeile fuer Zeile. Die funktionslokalen Importe
# bleiben, wo sie sind: Sie umgehen bestehende Importzyklen; wer sie
# hochzieht, holt die Zyklen zurueck und merkt es erst zur Laufzeit.

import calendar as _calendar
import re
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from core.auth import SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag
from core.tenancy import aktuelle_organisation


def _num(wert):
    """Normalisiert eine im Formular eingegebene Zahl zu einem Decimal-tauglichen
    String: Schweizer Tausender-Apostroph (' und ’) raus, Komma → Punkt, CHF/
    Leerzeichen raus.

    Nötig, weil Beträge über den `chf`-Filter mit Apostroph angezeigt werden
    (CHF 12'500.00) und exakt so wieder ins Formular zurückkommen — `Decimal()`
    warf darauf eine InvalidOperation und die Aktion brach ab bzw. fiel still auf
    den Standardwert zurück (Praxis-Audit).
    """
    t = str(wert or '').strip()
    for weg in ("'", "\u2019", "\u00a0", " ", "CHF", "chf"):
        t = t.replace(weg, '')
    return t.replace(',', '.')


def _global_filter(request):
    """Liest den globalen Liegenschafts-Filter (?lg=) und liefert Basis-Kontext.

    BESITZPRÜFUNG (Etappe 4.2)
    --------------------------
    Bis hierher nahm diese Funktion jede `?lg=`-ID entgegen und lieferte die
    Liegenschaft dazu — auch eine fremde. Gemessen mit Bauform E: Von 107
    parameterlosen `fw_`-URLs übernahmen **61** die Liegenschaft eines fremden
    Mandanten. Und `alle_liegenschaften` gab ungefiltert ALLE zurück, also
    stand jede fremde Adresse im Auswahlmenü, ohne dass jemand eine ID raten
    musste.

    Beides wurde damals auf `request.organisation` eingeschränkt — mit dem
    ausdrücklichen Vermerk, dass dies die Bequemlichkeit sei und nicht die
    Sicherheit, und dass der `TenantManager` unabhängig davon filtern müsse.

    SEIT ETAPPE 6.2 TUT ER DAS, UND DIE ZEILE IST WEG (17.08.2026)
    --------------------------------------------------------------
    `Liegenschaft.objects` läuft jetzt durch den `TenantManager` und ist damit
    bereits auf die Organisation des Kontexts eingeschränkt. Die zusätzliche
    Zeile `if organisation is not None: …filter(organisation=organisation)` war
    danach tautologisch — gemessen: Sie auszubauen macht **keinen einzigen**
    Test rot, vor der Manager-Anbindung waren es drei.

    Entfernt statt behalten, und der Grund ist nicht Sparsamkeit: Die Zeile war
    in einem Punkt SCHWÄCHER als der Manager und sah trotzdem wie die
    tragende Prüfung aus. Ohne Kontext übersprang sie den Filter kommentarlos
    (`if organisation is not None`), während der Manager in derselben Lage
    einen `OrganisationsFehler` wirft. Zwei Prüfungen mit unterschiedlicher
    Strenge nebeneinander laden dazu ein, die schwächere für die Zusage zu
    halten — der Skill `mandantentrennung` verlangt genau deshalb die zentrale
    Erzwingung.

    Wer hier wieder von Hand filtern will, sollte vorher wissen, warum der
    Manager nicht reicht — und es hinschreiben.
    """
    eigene = Liegenschaft.objects.all()

    lg_id = request.GET.get('lg') or None
    aktive_lg = None
    if lg_id:
        # Die Einschränkung steht IM Filter, nicht in einer Prüfung danach:
        # Eine fremde ID findet damit schlicht nichts und ergibt `None`, statt
        # dass irgendwo ein `if fremd: ...` vergessen werden könnte.
        aktive_lg = eigene.filter(id=lg_id).first()
    from core.auth import hat_rolle
    return {
        'alle_liegenschaften': eigene.order_by('strasse'),
        'aktive_lg': aktive_lg,
        'lg_query': f"?lg={aktive_lg.id}" if aktive_lg else "",
        # Rolle für die Vorlagen: Wer nicht schreiben darf, soll die Knöpfe gar
        # nicht erst sehen. Sonst landet die Rolle «Lesend» beim Klick auf der
        # Anmeldeseite, obwohl sie angemeldet ist — das sieht nach Defekt aus.
        # Ersetzt keine Prüfung im View, blendet nur die Sackgasse aus.
        'kann_schreiben': hat_rolle(request.user, SCHREIB_ROLLEN),
        'ist_verwaltung': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
    }


def _kaution_bilanziert(vertrag):
    """Wie viel Kaution dieses Vertrags steht noch als Verbindlichkeit (2010) in
    der Bilanz?

    Massgebend für jede Freigabe/Rückzahlung ist dieser Betrag — NICHT das
    Vertragsfeld `kautions_betrag`, das nur den vereinbarten Betrag festhält.
    Ohne die Unterscheidung wird eine nie einbezahlte Kaution «zurückbezahlt»
    (Audit, kritisch). Eine bereits erfolgte Auflösung hat 2010 belastet und
    senkt den Wert automatisch — das verhindert zugleich eine zweite Auflösung
    über einen anderen Weg.
    """
    from django.db.models import Sum, Q as _Q
    from finance.models import Buchung

    def _saldo_2010(qs):
        h = qs.filter(haben_konto__nummer='2010').aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        s = qs.filter(soll_konto__nummer='2010').aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        return (h - s).quantize(Decimal('0.01'))

    offen = Buchung.objects.filter(ist_storno=False, storniert_am__isnull=True)
    # 1) Bevorzugt die vertragsgetaggten Buchungen (`Mietkaution [V<pk>] …`) —
    #    präzise auch bei mehreren Verträgen desselben Mieters.
    getaggt = offen.filter(beleg_text__contains=f"[V{vertrag.pk}]")
    if getaggt.filter(_Q(soll_konto__nummer='2010') | _Q(haben_konto__nummer='2010')).exists():
        return _saldo_2010(getaggt)
    # 2) Fallback für manuell journalisierte Kautionen ohne Vertrags-Tag: nur wenn
    #    eine Einzahlung dokumentiert ist UND das Konto sie überhaupt trägt.
    if not vertrag.kautions_einbezahlt_am:
        return Decimal('0.00')
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    gesamt = _saldo_2010(offen.filter(liegenschaft=lg) if lg else offen)
    return max(min(vertrag.kautions_betrag or Decimal('0.00'), gesamt), Decimal('0.00'))


def _mwst_beleg(jahr, quartal):
    return f"MWST-Abrechnung {jahr}" + (f" Q{quartal}" if quartal in ('1', '2', '3', '4') else "")


def _mwst_bereits_verbucht(jahr, quartal, liegenschaft=None):
    """True, wenn für diese Periode ODER eine sie überlappende Periode desselben
    Jahres bereits abgerechnet wurde.

    Audit-Befund: Der Check verglich nur den eigenen Belegtext. Wer zuerst das
    ganze Jahr verbuchte und danach die vier Quartale, bekam eine fünffache
    Ausbuchung — «MWST-Abrechnung 2024 Q1» beginnt nicht mit dem Jahresbeleg,
    also schlug die Prüfung nie an. Jahr und Quartal überlappen sich immer, ein
    Treffer auf einer der beiden Ebenen blockiert daher die andere.
    """
    from django.db.models import Q as _Q
    from finance.models import Buchung
    # `storniert_am` mitprüfen: Eine stornierte Abrechnung behält ist_storno=False
    # (das Flag trägt die Gegenbuchung). Ohne diese Bedingung blieb die Periode
    # nach einem Storno dauerhaft gesperrt und liess sich nie neu verbuchen (Audit).
    qs = Buchung.objects.filter(beleg_text__startswith=f"MWST-Abrechnung {jahr}",
                                ist_storno=False, storniert_am__isnull=True)
    if liegenschaft:
        qs = qs.filter(liegenschaft=liegenschaft)
    if quartal not in ('1', '2', '3', '4'):
        return qs.exists()                      # Jahr: jede Quartalsabrechnung zählt
    # Quartal: nur das EIGENE Quartal oder eine Jahresabrechnung blockiert.
    # Der Jahresbeleg ist ein Präfix der Quartalsbelege, deshalb wird er über
    # den Trenner « — » abgegrenzt — sonst würde Q1 auch Q2 blockieren.
    return qs.filter(_Q(beleg_text__startswith=f"{_mwst_beleg(jahr, quartal)} ")
                     | _Q(beleg_text__startswith=f"{_mwst_beleg(jahr, '')} —")).exists()


def _mwst_periode(jahr, quartal, liegenschaft=None):
    """Rechnet eine MWST-Periode aus dem Hauptbuch — EINE Quelle für Anzeige,
    Verbuchung und ESTV-Export.

    Audit-Befund: Anzeige, Verbuchung und CSV-Export rechneten vorher jeweils
    eigenständig. Die Verbuchung übernahm die Beträge sogar ungeprüft aus dem
    POST (manipulierbar) und dem Export fehlte die Brutto-Rückrechnung des
    Saldosteuersatzes — die eingereichte Abrechnung wich damit von der
    angezeigten ab.
    """
    from finance.models import Buchungskonto, Buchung
    from django.db.models import Sum
    from crm.models import Organisation
    from core.services.mwst_estv import berechne_estv, MWST_NORMALSATZ

    if quartal in ('1', '2', '3', '4'):
        q = int(quartal)
        von = date(jahr, (q - 1) * 3 + 1, 1)
        m_end = q * 3
        bis = date(jahr, m_end, _calendar.monthrange(jahr, m_end)[1])
    else:
        von, bis = date(jahr, 1, 1), date(jahr, 12, 31)

    qs = Buchung.objects.filter(datum__gte=von, datum__lte=bis, ist_storno=False,
                                storniert_am__isnull=True)
    if liegenschaft:
        qs = qs.filter(liegenschaft=liegenschaft)
    # Die eigenen Abrechnungsbuchungen dürfen die Basis der nächsten Periode
    # nicht verfälschen (sonst frisst sich die Ausbuchung selbst).
    qs = qs.exclude(beleg_text__startswith=f"MWST-Abrechnung {jahr}")

    def saldo(nummer, soll_positiv):
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00')
        soll = qs.filter(soll_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        haben = qs.filter(haben_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        return (soll - haben) if soll_positiv else (haben - soll)

    umsatzsteuer = saldo('2200', soll_positiv=False)   # geschuldete MWST (Haben-Saldo)
    vorsteuer = saldo('1170', soll_positiv=True)        # Vorsteuer-Guthaben (Soll-Saldo)
    zahllast = umsatzsteuer - vorsteuer

    vw = aktuelle_organisation()
    methode = getattr(vw, 'mwst_methode', 'effektiv') if vw else 'effektiv'
    # Nettoumsatz aus der geschuldeten Steuer zurückrechnen — erfasst NK (3020),
    # optierte Wohnverhältnisse (3000) und Zuschläge (3600) gleichermassen.
    # Konto 3010 allein verfehlte diese (Audit K4).
    if umsatzsteuer > 0:
        umsatz_steuerbar = (umsatzsteuer / (MWST_NORMALSATZ / Decimal('100'))).quantize(Decimal('0.01'))
    else:
        umsatz_steuerbar = saldo('3010', soll_positiv=False)
    # Saldosteuersatz wird auf das BRUTTO-Entgelt (inkl. MWST) angewendet (ESTV-Regel).
    umsatz_brutto = (umsatz_steuerbar + umsatzsteuer).quantize(Decimal('0.01'))
    saldosatz = getattr(vw, 'saldosteuersatz', Decimal('0')) if vw else Decimal('0')
    estv = berechne_estv(
        umsatz_steuerbar=umsatz_steuerbar, umsatzsteuer=umsatzsteuer,
        vorsteuer_material=vorsteuer, vorsteuer_invest=Decimal('0'),
        methode=methode, saldosteuersatz=saldosatz, umsatz_brutto=umsatz_brutto)
    if methode == 'saldo':
        zahllast = estv['z500']

    return {
        'von': von, 'bis': bis,
        'umsatzsteuer': umsatzsteuer, 'vorsteuer': vorsteuer, 'zahllast': zahllast,
        'umsatz_steuerbar': umsatz_steuerbar, 'umsatz_brutto': umsatz_brutto,
        'estv': estv, 'methode': methode, 'saldosteuersatz': saldosatz,
        'saldo_vorteil': ((umsatzsteuer - zahllast).quantize(Decimal('0.01'))
                          if methode == 'saldo' else Decimal('0.00')),
        'verwaltung': vw,
    }


def _pendenz_ziel(p):
    """Verknüpft eine Pendenz mit dem passenden Objekt/Schritt.
    Rückgabe: (url, label, wide, modal). `modal=True` → im Iframe-Popup öffnen
    (nur für Aktions-/Schritt-Formulare, deren Chrome im Embed ausgeblendet wird);
    `modal=False` → volle Seiten-Navigation. Eine Detailseite (Vertrag/Liegenschaft)
    gehört NICHT ins Popup — ihr Hero + Tabs + Tabellen werden im engen Iframe
    (v.a. mobil) abgeschnitten und kollidieren mit dem Pendenz-Titel."""
    q = p.quelle or ''
    if p.vertrag_id:
        if q.startswith('auto:ruecknahme:'):
            return (f'/neu/vertraege/{p.vertrag_id}/abnahme/neu/?typ=auszug', 'Rücknahme starten', False, True)
        return (f'/neu/vertraege/{p.vertrag_id}/', 'Vertrag öffnen', False, False)
    if p.liegenschaft_id:
        return (f'/neu/liegenschaften/{p.liegenschaft_id}/', 'Liegenschaft öffnen', False, False)
    return (None, None, False, False)


def _vermietung_pipeline(aktiv, lg_query=''):
    """Kontext für die Vermietungs-Pipeline-Leiste (Vermarktung → Bewerbung →
    Vertrag → Mieterwechsel) — auf allen vier Stufen-Seiten eingeblendet, damit
    der Prozess als EIN Ablauf erlebbar ist statt als vier Menüpunkte."""
    from mietprozess.models import Mietbewerbung
    from rentals.models import Kuendigung
    stufen = [
        {'key': 'vermarktung', 'label': 'Vermarktung', 'icon': 'fa-bullhorn',
         'url': '/neu/vermarktung/' + lg_query,
         'n': Einheit.objects.filter(zur_ausschreibung=True).count()},
        {'key': 'bewerbungen', 'label': 'Bewerbungen', 'icon': 'fa-user-check',
         'url': '/neu/bewerbungen/' + lg_query,
         'n': Mietbewerbung.objects.filter(status__in=['neu', 'geprueft']).count()},
        {'key': 'vertraege', 'label': 'Verträge', 'icon': 'fa-file-lines',
         'url': '/neu/vertraege/' + lg_query,
         'n': Mietvertrag.objects.filter(status='entwurf').count()},
        {'key': 'mieterwechsel', 'label': 'Mieterwechsel', 'icon': 'fa-right-left',
         'url': '/neu/mieterwechsel/' + lg_query,
         'n': Kuendigung.objects.filter(status__in=['erfasst', 'bestaetigt']).count()},
    ]
    for s in stufen:
        s['aktiv'] = (s['key'] == aktiv)
    return {'pipeline_stufen': stufen}


# Nachgezogen, als der Abnahme-Block auszog: _parse_adresse stand im
# Kopfbereich und wurde nur von ihm gebraucht. Statt den Block auf _rest.py
# zeigen zu lassen — eine Abhaengigkeit, die beim Verschwinden von _rest.py
# wieder aufzuloesen waere — steht der Helfer jetzt hier.
def _parse_adresse(text):
    """Grobe Zerlegung eines freien Adress-Strings in (strasse, plz, ort).
    Erkennt Formate wie «Musterstrasse 1, 8000 Zürich» oder «Musterstrasse 1
    8000 Zürich». Bei Unklarheit wandert der ganze Rest nach `ort`."""
    text = (text or '').strip()
    if not text:
        return '', '', ''
    teile = [t.strip() for t in text.split(',') if t.strip()]
    if len(teile) >= 2:
        strasse = teile[0]
        rest = teile[1]
    else:
        # kein Komma → letzten «PLZ Ort»-Block vom Strassenteil trennen
        m = re.search(r'(.*?)(\b\d{4}\b.*)$', text)
        if m and m.group(1).strip():
            strasse, rest = m.group(1).strip(), m.group(2).strip()
        else:
            return text, '', ''
    m = re.match(r'^\s*(\d{4,6})\s+(.*)$', rest)
    if m:
        return strasse, m.group(1), m.group(2).strip()
    return strasse, '', rest


# Der Sonderfall, den docs/ETAPPE-1-ZERLEGEN.md ausdruecklich benennt:
# _park_konto stand im Profil-Menue-Block und wurde AUSSCHLIESSLICH vom
# Bankabgleich benutzt — rund 10'000 Zeilen entfernt. Beim Umzug des
# Bankabgleichs faellt genau das auf. Statt den Helfer dem einen oder dem
# anderen Modul zuzuschlagen, steht er hier.
def _park_konto(nummer):
    from finance.booking import konto as _k
    return _k(nummer)


# Die Status-Beschriftungen der Vertraege. Kein Helfer, sondern eine
# Konstante — aber dieselbe Lage: Sie stand im Listen-Block und wird auch
# von der Personen-Detailseite gebraucht. Eine Kopie waere schlimmer als
# ein gemeinsamer Ort: Zwei Fassungen driften auseinander, und dann heisst
# derselbe Vertragsstatus auf zwei Seiten verschieden.
VERTRAG_PILL = {
    'entwurf':    ('Entwurf',    'bg-slate-100 text-slate-600'),
    'aktiv':      ('Aktiv',      'bg-emerald-50 text-emerald-700'),
    'gekuendigt': ('Gekündigt',  'bg-rose-50 text-rose-600'),
    # «Beendet» ist kein gespeicherter Status, sondern der ANZEIGE-Status aus
    # `Mietvertrag.anzeige_status`: archiviert, oder gekuendigt mit
    # abgelaufenem Ende. Vorher zeigte die Liste einen solchen Vertrag
    # weiterhin als «gekuendigt» — und der Filter «Gekuendigt» lieferte ihn mit.
    'beendet':    ('Beendet',    'bg-slate-100 text-slate-500'),
    'archiviert': ('Archiviert', 'bg-slate-100 text-slate-500'),
}


# Wie VERTRAG_PILL: Status-Beschriftungen, die mehrere Module brauchen.
# Herausgeloest mit KLAMMERBILANZ, nicht mit der Einrueckungsregel — bei
# VERTRAG_PILL hatte letztere die schliessende Klammer abgeschnitten, weil
# sie bei einem mehrzeiligen Literal selbst in Spalte 0 steht.
STATUS_PILL = {
    'offen':       ('Offen',       'bg-amber-50 text-amber-700'),
    'teilbezahlt': ('Teilbezahlt', 'bg-sky-50 text-sky-700'),
    'bezahlt':     ('Bezahlt',     'bg-emerald-50 text-emerald-700'),
    'storniert':   ('Storniert',   'bg-slate-100 text-slate-500'),
    'abgeschrieben': ('Abgeschrieben', 'bg-slate-100 text-slate-500'),
}
