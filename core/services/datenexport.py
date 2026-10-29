"""Exporte für den Ausstieg und die Buchhaltung (Audit FUNK-13).

Zwei Dinge:

1. **Mandatsexport**: Alle Daten EINER Organisation als ZIP, je Tabelle eine CSV- und eine
   JSON-Datei, dazu die Dokumente. Gedacht für den Wechsel zu einem anderen System und für
   die Datenübertragung (Art. 28 DSG). Eine Auskunft über eine einzelne Person ist
   `core/services/auskunft.py`.
2. **Buchungsjournal** als CSV für ein Buchhaltungsprogramm (Banana, Abacus u. a.). Welche
   Überschriften und Kontonummern das Zielprogramm erwartet, ist eine Einstellung der
   Organisation (`DatenExportEinstellung`), nicht im Code geraten.

Beides liest nur. Mandantentrennung: Es werden ausschliesslich die Standard-Manager (`objects`,
gefiltert auf den Kontext) benutzt, und der Aufrufer setzt den Kontext der eigenen Organisation.
`alle_organisationen` kommt hier nicht vor; auch ein Superuser exportiert nur seine aktive
Organisation.
"""
import csv
import io
import json
import logging
import re
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.apps import apps
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

logger = logging.getLogger(__name__)

EIGENE_APPS = ('core', 'crm', 'portfolio', 'rentals', 'finance', 'tickets', 'mietprozess', 'faelle', 'stweg')

#: Modelle, die nie in den Export gehören (Zugangsdaten Dritter, Konto-Sicherheit).
AUSGENOMMEN_MODELLE = {
    'core.Postfach': 'enthält Zugangsdaten zum E-Mail-Server',
}
#: Spalten, die nie exportiert werden: Geheimnisse und Prüfsummen von Geheimnissen.
#: AHV-Nummern liegen verschlüsselt in der Datenbank; ein Klartext in einer ZIP-Datei wäre
#: ein neuer Abfluss (Datenminimierung). Die Auskunft über eine Person enthält sie.
_GEHEIM = re.compile(r'passw|token|secret|geheim|hash|api_key|ahv_nummer', re.IGNORECASE)

DOKUMENT_FELD_TYPEN = ('FileField', 'ImageField')

SPALTEN_VORGABE = {
    'datum': 'Buchungsdatum', 'beleg': 'Belegnummer', 'soll': 'Soll', 'haben': 'Haben',
    'betrag': 'Betrag', 'text': 'Text', 'mwst': 'MWST-Code',
}
SPALTEN_REIHENFOLGE = ('datum', 'beleg', 'soll', 'haben', 'betrag', 'text', 'mwst')
TRENNER = {';': gettext_lazy('Semikolon'), ',': gettext_lazy('Komma'), '\t': gettext_lazy('Tabulator')}


# ── Wert -> Text / JSON ───────────────────────────────────────────────────────
def _wert(wert):
    if isinstance(wert, (datetime, date, time)):
        return wert.isoformat()
    if isinstance(wert, Decimal):
        return str(wert)
    if isinstance(wert, timedelta):
        return str(wert)
    if isinstance(wert, (bytes, bytearray, memoryview)):
        return None
    if hasattr(wert, 'name') and hasattr(wert, 'storage'):          # FieldFile
        return wert.name or ''
    if hasattr(wert, 'hex') and not isinstance(wert, (str, int, float)):   # UUID
        return str(wert)
    return wert


def _csv_zelle(wert):
    wert = _wert(wert)
    if wert is None:
        return ''
    if isinstance(wert, bool):
        return 'ja' if wert else 'nein'
    if isinstance(wert, (dict, list)):
        return json.dumps(wert, ensure_ascii=False)
    text = str(wert)
    # Formelinjektion in Excel/LibreOffice: Zellen, die mit = + - @ beginnen, werden als Formel gelesen.
    if text[:1] in ('=', '+', '@') or (text[:1] == '-' and not re.fullmatch(r'-\d+([.,]\d+)?', text)):
        return "'" + text
    return text


def exportierbare_modelle():
    """Die Modelle des Exports: alle Fachmodelle mit eigener Spalte `organisation`.

    Folgt dem Modellbestand (wie der Datenreset): Ein neues Modell mit Organisationsbezug ist
    automatisch dabei. Ohne die Spalte gibt es keine Grenze, an der sich schneiden liesse."""
    modelle = []
    for modell in apps.get_models():
        meta = modell._meta
        if meta.app_label not in EIGENE_APPS or meta.proxy or not meta.managed:
            continue
        if meta.label in AUSGENOMMEN_MODELLE:
            continue
        if not any(f.name == 'organisation' for f in meta.concrete_fields):
            continue
        modelle.append(modell)
    return sorted(modelle, key=lambda m: m._meta.label)


def _felder(modell):
    return [f for f in modell._meta.concrete_fields
            if f.name != 'organisation' and not _GEHEIM.search(f.name)]


def _queryset(modell):
    # Der Standard-Manager filtert auf die Organisation des Kontexts. `_default_manager` ist bei
    # allen diesen Modellen ein TenantManager (Wächter: test_daten_export).
    return modell._default_manager.all().order_by('pk')


# ── Mandatsexport ─────────────────────────────────────────────────────────────
def mandat_zip(organisation, ziel, *, mit_dokumenten=True, erstellt_von='', medien_wurzel=None):
    """Schreibt den Mandatsexport als ZIP nach `ziel` (Datei oder Puffer). Gibt die Zusammenfassung zurück.

    Der Aufrufer hält den Mandantenkontext der `organisation` (`organisation_kontext`)."""
    from core.tenancy import aktuelle_organisation
    if aktuelle_organisation() is None or aktuelle_organisation().pk != organisation.pk:
        raise RuntimeError('Der Mandantenkontext ist nicht der der exportierten Organisation.')
    zusammenfassung = {'tabellen': {}, 'dokumente': 0, 'fehlende_dokumente': 0, 'zeilen': 0}
    dokumente = []              # (modell-label, pk, feld, FieldFile)
    with zipfile.ZipFile(ziel, 'w', zipfile.ZIP_DEFLATED) as zf:
        for modell in exportierbare_modelle():
            felder = _felder(modell)
            label = modell._meta.label
            datei_felder = [f for f in felder if f.get_internal_type() in DOKUMENT_FELD_TYPEN]
            n = _tabelle_schreiben(zf, modell, felder, label, dokumente if mit_dokumenten else None, datei_felder)
            if n:
                zusammenfassung['tabellen'][label] = n
                zusammenfassung['zeilen'] += n
        _team_schreiben(zf, zusammenfassung)
        _organisation_schreiben(zf, organisation)
        if mit_dokumenten:
            _dokumente_schreiben(zf, dokumente, zusammenfassung)
        zf.writestr('LIESMICH.txt', _liesmich(organisation, zusammenfassung, mit_dokumenten, erstellt_von))
    return zusammenfassung


def _tabelle_schreiben(zf, modell, felder, label, dokumente, datei_felder):
    """Eine Tabelle als CSV und JSON. Gibt die Zeilenzahl zurück (0 = leer, nichts geschrieben)."""
    qs = _queryset(modell)
    namen = [f.name for f in felder]
    attnamen = [f.attname for f in felder]
    n = 0
    csv_puffer = io.StringIO()
    schreiber = csv.writer(csv_puffer, delimiter=';', lineterminator='\r\n')
    schreiber.writerow(namen)
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+', encoding='utf-8') as json_puffer:
        json_puffer.write('[')
        for obj in qs.iterator(chunk_size=1000):
            zeile = {name: _wert(getattr(obj, att)) for name, att in zip(namen, attnamen)}
            schreiber.writerow([_csv_zelle(zeile[name]) for name in namen])
            json_puffer.write(('' if n == 0 else ',') + '\n  ' + json.dumps(zeile, ensure_ascii=False, default=str))
            n += 1
            if dokumente is not None:
                for f in datei_felder:
                    ff = getattr(obj, f.name)
                    if ff and ff.name:
                        dokumente.append((label, obj.pk, f.name, ff))
        if n == 0:
            return 0
        json_puffer.write('\n]\n')
        json_puffer.seek(0)
        pfad = label.replace('.', '_')
        zf.writestr(f'daten/{pfad}.csv', '﻿' + csv_puffer.getvalue())
        with zf.open(f'daten/{pfad}.json', 'w') as ziel_json:
            while True:
                block = json_puffer.read(1024 * 1024)
                if not block:
                    break
                ziel_json.write(block.encode('utf-8'))
    return n


def _team_schreiben(zf, zusammenfassung):
    """Wer in der Organisation arbeitet (ohne Passwörter): aus den Mitgliedschaften."""
    from crm.models import Mitgliedschaft
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=';', lineterminator='\r\n')
    w.writerow(['benutzername', 'vorname', 'nachname', 'email', 'rolle'])
    n = 0
    for m in Mitgliedschaft.objects.select_related('benutzer').order_by('pk'):
        b = m.benutzer
        w.writerow([_csv_zelle(b.username), _csv_zelle(b.first_name), _csv_zelle(b.last_name),
                    _csv_zelle(b.email), _csv_zelle(m.rolle)])
        n += 1
    zf.writestr('daten/team.csv', '﻿' + puffer.getvalue())
    zusammenfassung['tabellen']['team'] = n


def _organisation_schreiben(zf, organisation):
    daten = {}
    for f in organisation._meta.concrete_fields:
        if _GEHEIM.search(f.name) or f.get_internal_type() in DOKUMENT_FELD_TYPEN:
            continue
        daten[f.name] = _wert(getattr(organisation, f.attname))
    zf.writestr('daten/organisation.json', json.dumps(daten, ensure_ascii=False, indent=2, default=str))


def _sicherer_name(name):
    name = re.sub(r'[^\w.\-]+', '_', (name or '').split('/')[-1], flags=re.UNICODE).strip('._') or 'datei'
    return name[:120]


def _dokumente_schreiben(zf, dokumente, zusammenfassung):
    index = io.StringIO()
    w = csv.writer(index, delimiter=';', lineterminator='\r\n')
    w.writerow(['tabelle', 'id', 'feld', 'datei_im_zip', 'ursprungspfad', 'status'])
    for label, pk, feld, ff in dokumente:
        ziel = f"dokumente/{label.replace('.', '_')}/{pk}_{feld}_{_sicherer_name(ff.name)}"
        status = 'ok'
        try:
            with ff.storage.open(ff.name, 'rb') as quelle:
                with zf.open(ziel, 'w') as ausgabe:
                    while True:
                        block = quelle.read(1024 * 1024)
                        if not block:
                            break
                        ausgabe.write(block)
            zusammenfassung['dokumente'] += 1
        except Exception:                                      # noqa: BLE001
            # Eine fehlende Datei bricht den Export nicht ab, steht aber im Index (und im Protokoll).
            logger.warning('Mandatsexport: Datei nicht lesbar: %s', ff.name, exc_info=True)
            status = 'fehlt'
            ziel = ''
            zusammenfassung['fehlende_dokumente'] += 1
        w.writerow([_csv_zelle(label), pk, _csv_zelle(feld), _csv_zelle(ziel), _csv_zelle(ff.name), status])
    zf.writestr('dokumente/index.csv', '﻿' + index.getvalue())


def _liesmich(organisation, z, mit_dokumenten, erstellt_von):
    zeilen = [
        f'Mandatsexport {organisation.firma}',
        f'Erstellt: {datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")}'
        + (f' von {erstellt_von}' if erstellt_von else ''),
        '',
        'Inhalt',
        '  daten/<App>_<Modell>.csv   eine Tabelle je Datei (UTF-8, Semikolon, Kopfzeile mit Feldnamen)',
        '  daten/<App>_<Modell>.json  dieselben Zeilen als JSON',
        '  daten/team.csv             Teammitglieder und Rollen (ohne Passwörter)',
        '  daten/organisation.json    Stammdaten der Verwaltung',
        '  dokumente/                 hochgeladene und erzeugte Dateien; dokumente/index.csv ordnet sie den Zeilen zu'
        if mit_dokumenten else '  (ohne Dokumente erstellt)',
        '',
        'Fremdschlüssel stehen als ID (Spalte «<feld>_id»); die Tabellen verweisen über diese IDs aufeinander.',
        'Nicht enthalten: Passwörter, Zugangsdaten und Geheimnisse, AHV-Nummern, Zugangsdaten zu Postfächern.',
        'Leere Tabellen werden nicht geschrieben.',
        '',
        f'Tabellen: {len(z["tabellen"])}, Zeilen: {z["zeilen"]}'
        + (f', Dokumente: {z["dokumente"]}, nicht lesbare Dokumente: {z["fehlende_dokumente"]}' if mit_dokumenten else ''),
        '',
        'Zeilen je Tabelle',
    ]
    zeilen += [f'  {name}: {n}' for name, n in sorted(z['tabellen'].items())]
    return '\r\n'.join(zeilen) + '\r\n'


# ── Buchungsjournal ───────────────────────────────────────────────────────────
def einstellung_holen(erstellen=False):
    """Die Export-Einstellung der aktiven Organisation (`TenantManager`), notfalls mit Vorgaben (ungespeichert)."""
    from core.models import DatenExportEinstellung
    e = DatenExportEinstellung.objects.first()
    if e is None:
        e = DatenExportEinstellung()
        if erstellen:
            e.save()
    return e


def spalten_aus(eigene):
    """{'datum': 'Buchungsdatum', …} mit Vorgaben für alles, was nicht gesetzt ist."""
    eigene = eigene if isinstance(eigene, dict) else {}
    return {k: (str(eigene.get(k) or '').strip() or SPALTEN_VORGABE[k]) for k in SPALTEN_REIHENFOLGE}


def spalten_von(einstellung):
    return spalten_aus(einstellung.spalten)


def konten_text(einstellung):
    """Die Kontenzuordnung als Text für das Formular: eine Zeile «intern;extern» bzw. «intern;extern;MWST-Code»."""
    konten = einstellung.konten if isinstance(einstellung.konten, dict) else {}
    zeilen = []
    for k, v in sorted(konten.items()):
        teile = [k, v.get('konto', '')] + ([v['mwst']] if v.get('mwst') else [])
        zeilen.append(';'.join(teile))
    return '\n'.join(zeilen)


class ZuordnungsFehler(ValueError):
    pass


def konten_parsen(text):
    """Text -> {'1020': {'konto': '1000', 'mwst': ''}}. Wirft `ZuordnungsFehler` mit der Zeile."""
    konten = {}
    for nr, zeile in enumerate((text or '').splitlines(), start=1):
        zeile = zeile.strip()
        if not zeile:
            continue
        teile = [t.strip() for t in re.split(r'[;\t]', zeile)]
        if len(teile) < 2 or len(teile) > 3 or not teile[0] or not teile[1]:
            raise ZuordnungsFehler(_('Zeile %(n)s: erwartet «eigenes Konto;Konto im Zielsystem» '
                                     'und optional «;MWST-Code».') % {'n': nr})
        intern, extern, mwst = teile[0], teile[1], (teile[2] if len(teile) == 3 else '')
        if len(intern) > 10 or len(extern) > 30 or len(mwst) > 20:
            raise ZuordnungsFehler(_('Zeile %(n)s: Eintrag zu lang.') % {'n': nr})
        if intern in konten:
            raise ZuordnungsFehler(_('Zeile %(n)s: das Konto %(k)s ist schon zugeordnet.') % {'n': nr, 'k': intern})
        konten[intern] = {'konto': extern, 'mwst': mwst}
    return konten


def journal_csv(von, bis, einstellung=None):
    """Das Buchungsjournal von `von` bis `bis` (beide eingeschlossen) als (Text, Statistik).

    Liest nur. Stornobuchungen stehen als eigene Zeilen (Gegenbuchung mit vertauschtem Soll/Haben
    und positivem Betrag), damit die Summe im Zielprogramm stimmt. Die MWST-Code-Spalte
    füllt die Zuordnung der Organisation: Eine Buchung trägt in swissImmo keinen Steuercode (die MWST
    wird auf eigene Konten gebucht), der Code ergibt sich also nur über das Konto, dem er in der Zuordnung
    zugewiesen ist (zuerst das Soll-, dann das Habenkonto)."""
    from finance.models import Buchung
    einstellung = einstellung or einstellung_holen()
    spalten = spalten_von(einstellung)
    konten = einstellung.konten if isinstance(einstellung.konten, dict) else {}
    trenner = einstellung.trenner if einstellung.trenner in TRENNER else ';'
    dezimal = einstellung.dezimal if einstellung.dezimal in ('.', ',') else '.'
    datumsformat = '%Y-%m-%d' if einstellung.datumsformat == 'iso' else '%d.%m.%Y'

    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=trenner, lineterminator='\r\n')
    w.writerow([spalten[k] for k in SPALTEN_REIHENFOLGE])
    statistik = {'zeilen': 0, 'ohne_zuordnung': set(), 'summe': Decimal('0.00')}
    qs = (Buchung.objects.filter(datum__gte=von, datum__lte=bis)
          .select_related('soll_konto', 'haben_konto').order_by('datum', 'beleg_nr', 'pk'))

    def konto(k):
        z = konten.get(k.nummer)
        if z and z.get('konto'):
            return z['konto'], z.get('mwst', '')
        statistik['ohne_zuordnung'].add(k.nummer)
        return k.nummer, ''

    for b in qs.iterator(chunk_size=2000):
        soll, mwst_s = konto(b.soll_konto)
        haben, mwst_h = konto(b.haben_konto)
        betrag = f'{b.betrag:.2f}'.replace('.', dezimal)
        w.writerow([_csv_zelle(x) for x in (
            b.datum.strftime(datumsformat), b.beleg_nr if b.beleg_nr is not None else b.pk,
            soll, haben, betrag, b.beleg_text, mwst_s or mwst_h)])
        statistik['zeilen'] += 1
        statistik['summe'] += b.betrag
    statistik['ohne_zuordnung'] = sorted(statistik['ohne_zuordnung'])
    return '﻿' + puffer.getvalue(), statistik
