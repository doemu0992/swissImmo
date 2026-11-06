"""Ein Brief aus einer Vorlage: Platzhalter, Einschreiben und Frist.

Eine Vorlage (``crm.Vorlage``, Kategorie Brief, Kündigung, Mahnung …) kann zwei Dinge festlegen, die über den Text
hinausgehen:

* **Einschreiben.** Der Brief trägt über der Adresse den Zustellvermerk. Nach dem Versand erfasst man an der
  Pendenz die Sendungsnummer (Track & Trace) und bestätigt den Zugang — derselbe Weg wie bei der Fristansetzung
  nach Art. 257d OR (``fw_verzug_sendung`` / ``fw_verzug_zugang``).
* **Frist.** Der Brief setzt eine Frist, die im Text steht und als Pendenz in der Fristenübersicht erscheint.

  - ``datum``: ein festes Datum. Vorgabe: Versand plus ``frist_tage`` (bei Einschreiben dazu Postweg und Abholfrist,
    damit das Datum nach dem spätest möglichen Zugang liegt); beim Erstellen änderbar. Im Text ``{frist}``.
  - ``zugang``: ``frist_tage`` Tage ab Erhalt des Schreibens. Das Datum steht erst fest, wenn der Zugang bestätigt
    ist (Empfangstheorie, BGE 119 II 147); bis dahin ist die Pendenz provisorisch und nie zu kurz. Im Text
    ``{frist.tage}``.

Eine Pendenz entsteht je Empfänger, sobald Einschreiben oder Frist gelten. Sie gehört zum Vertrag des Empfängers und
trägt die Quelle ``brief:<Dokument-ID>`` — daran erkennen die Zugangs-Schritte, dass es kein 257d-Verfahren ist.
"""
import datetime
import io
import logging
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from core.services.platzhalter import MUSTER, bekannt, ersetze, kontext_fuer
from core.services.zahlungsverzug import definitives_fristende, provisorisches_fristende

logger = logging.getLogger(__name__)

#: Quellpräfix der Pendenz zu einem Brief mit Einschreiben oder Frist.
QUELLE_PRAEFIX = 'brief:'
#: Tage bis zur Kontrolle, ob die Sendungsnummer erfasst ist (Einschreiben ohne Frist).
KONTROLLE_TAGE = 3
FRIST_MAX_TAGE = 365


def ist_brief_pendenz(pendenz):
    return (pendenz.quelle or '').startswith(QUELLE_PRAEFIX)


def frist_vorgabe(vorlage, einschreiben=None, heute=None):
    """Was die Oberfläche beim Erstellen vorbelegt: ``{'art', 'tage', 'datum', 'einschreiben'}``.

    ``datum`` nur bei Frist-Art ``datum``: Versand plus Tage; bei Einschreiben zusätzlich Postweg und Abholfrist."""
    heute = heute or timezone.localdate()
    art = vorlage.frist_art or ''
    tage = vorlage.frist_tage or None
    einschreiben = vorlage.einschreiben if einschreiben is None else bool(einschreiben)
    datum = None
    if art == 'datum' and tage:
        datum = (provisorisches_fristende(heute, tage) if einschreiben
                 else definitives_fristende(heute, tage))
    return {'art': art, 'tage': tage, 'datum': datum, 'einschreiben': einschreiben}


def offene_platzhalter(vorlage, kontext):
    """Bekannte Platzhalter in Betreff und Text, für die der Kontext keinen Wert hat (z. B. ``{frist}`` ohne Frist).

    Im Brief stünde sonst die geschweifte Klammer. Unbekannte Platzhalter (Freitext in Klammern) bleiben unberührt."""
    from core.services.platzhalter import _wert
    offen = []
    for name in MUSTER.findall(f"{vorlage.betreff or ''}\n{vorlage.inhalt or ''}"):
        if not bekannt(name) or '{' + name + '}' in offen:
            continue
        try:
            _wert(name, kontext)
        except KeyError:
            offen.append('{' + name + '}')
    return offen


def _aktiver_vertrag(mieter):
    from django.db.models import Q
    from rentals.models import Mietvertrag
    return (Mietvertrag.objects.filter(Q(mieter=mieter) | Q(mitmieter=mieter), status='aktiv')
            .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').order_by('-beginn').first())


def _pdf_zusammenfuegen(teile):
    if len(teile) == 1:
        return teile[0]
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for t in teile:
        for seite in PdfReader(io.BytesIO(t)).pages:
            w.add_page(seite)
    puffer = io.BytesIO()
    w.write(puffer)
    return puffer.getvalue()


def brief_erzeugen(vorlage, mieter_ids, organisation, benutzer=None, **optionen):
    """Siehe ``_brief_erzeugen``; läuft im Kontext der Verwaltung, damit nur deren Mieter und Verträge sichtbar sind."""
    from core.tenancy import organisation_kontext
    with organisation_kontext(organisation):
        return _brief_erzeugen(vorlage, mieter_ids, organisation, benutzer, **optionen)


def _brief_erzeugen(vorlage, mieter_ids, organisation, benutzer=None, *, einschreiben=False, frist_art='',
                    frist_datum=None, frist_tage=None, heute=None):
    """Erzeugt je Empfänger einen Brief aus der Vorlage, legt ihn in der Akte ab und setzt die Pendenz.

    Gibt ``{'pdf': Bytes aller Briefe, 'briefe': [{'mieter', 'vertrag', 'dokument', 'pendenz'}, …]}`` zurück.
    Wirft ``ValidationError`` bei fehlenden Angaben (Frist ohne Datum, Platzhalter ohne Wert, kein Empfänger);
    dann ist nichts abgelegt."""
    from crm.models import Mieter
    from core.models import Pendenz
    from core.services.ablage import ablegen
    from core.services.vorlagen_pdf import vorlage_pdf

    heute = heute or timezone.localdate()
    if frist_art not in ('', 'datum', 'zugang'):
        raise ValidationError(gettext('Unbekannte Fristart.'))
    if frist_art == 'datum':
        if frist_datum is None:
            raise ValidationError(gettext('Bitte das Fristdatum angeben.'))
        if frist_datum <= heute:
            raise ValidationError(gettext('Das Fristdatum muss in der Zukunft liegen.'))
    if frist_art == 'zugang' and not (frist_tage and 0 < frist_tage <= FRIST_MAX_TAGE):
        raise ValidationError(gettext('Bitte die Fristdauer in Tagen angeben (1 bis %(max)s).') % {'max': FRIST_MAX_TAGE})
    if frist_art == 'datum' and frist_tage:
        frist_tage = None if frist_tage > FRIST_MAX_TAGE else frist_tage

    # Empfänger: eine Person je aktivem Vertrag (zwei Personen desselben Vertrags: ein Brief, beide Namen).
    empfaenger, gesehen = [], set()
    for mid in mieter_ids:
        m = Mieter.objects.filter(id=mid).first()
        if m is None:
            continue
        v = _aktiver_vertrag(m)
        if v is not None:
            if v.id in gesehen:
                continue
            gesehen.add(v.id)
            m = v.mieter or m
        empfaenger.append((m, v))
    if not empfaenger:
        raise ValidationError(gettext('Keine gültigen Empfänger gefunden.'))

    teile, briefe = [], []
    # Erst alle Briefe prüfen und rendern, dann ablegen: Ein Fehler beim dritten Empfänger legt nichts ab.
    kontexte = []
    for m, v in empfaenger:
        k = kontext_fuer(vertrag=v, mieter=m, organisation=organisation, sprache=vorlage.sprache,
                         frist_datum=frist_datum if frist_art == 'datum' else None,
                         frist_tage=frist_tage if frist_art in ('datum', 'zugang') else None)
        offen = offene_platzhalter(vorlage, k)
        if offen:
            raise ValidationError(gettext('Im Brief stehen Platzhalter ohne Wert: %(liste)s. Bitte die Frist in der Vorlage '
                                          'oder beim Erstellen angeben.') % {'liste': ', '.join(offen)})
        kontexte.append(k)
        teile.append(vorlage_pdf(vorlage, k, organisation, einschreiben=einschreiben))

    with transaction.atomic():
        for (m, v), k, pdf in zip(empfaenger, kontexte, teile):
            betreff = ersetze(vorlage.betreff or vorlage.name, k) or vorlage.name
            dok = ablegen(pdf, f"Brief: {betreff}", kategorie='korrespondenz', vertrag=v, mieter=m,
                          im_portal_sichtbar=True, vorlage=vorlage)
            if dok is None:
                raise RuntimeError('Ablage gescheitert')
            pendenz = None
            if einschreiben or frist_art:
                pendenz = _pendenz_anlegen(Pendenz, dok, m, v, betreff, einschreiben, frist_art, frist_datum,
                                           frist_tage, heute, benutzer)
            briefe.append({'mieter': m, 'vertrag': v, 'dokument': dok, 'pendenz': pendenz})
    return {'pdf': _pdf_zusammenfuegen(teile), 'briefe': briefe}


def _pendenz_anlegen(Pendenz, dok, mieter, vertrag, betreff, einschreiben, frist_art, frist_datum, frist_tage, heute,
                     benutzer):
    from core.services.fristen import naechster_werktag
    name = mieter.display_name
    teile = []
    if frist_art == 'datum':
        faellig = frist_datum
        teile.append(gettext('Frist bis %(datum)s.') % {'datum': f'{frist_datum:%d.%m.%Y}'})
    elif frist_art == 'zugang':
        # Provisorisch: der späteste Zugang, mit dem zu rechnen ist; nach «Zugang bestätigen» gilt Zugang + Tage.
        faellig = provisorisches_fristende(heute, frist_tage)
        teile.append(gettext('Frist: %(tage)s Tage ab Zugang des Schreibens. Provisorisch bis %(datum)s; mit der '
                             'Bestätigung des Zugangs steht das Fristende fest.') % {'tage': frist_tage,
                                                                                    'datum': f'{faellig:%d.%m.%Y}'})
    else:
        faellig = naechster_werktag(heute + datetime.timedelta(days=KONTROLLE_TAGE))
    if einschreiben:
        teile.append(gettext('Einschreiben: nach dem Versand die Sendungsnummer erfassen, danach den Zugang bestätigen.'))
        titel = (gettext('Einschreiben an %(name)s: %(betreff)s') if not frist_art
                 else gettext('Frist (Einschreiben) %(name)s: %(betreff)s')) % {'name': name, 'betreff': betreff}
    else:
        titel = gettext('Frist %(name)s: %(betreff)s') % {'name': name, 'betreff': betreff}
    return Pendenz.objects.create(
        titel=titel[:200], beschreibung=' '.join(teile), kategorie='frist', faellig_am=faellig,
        quelle=f'{QUELLE_PRAEFIX}{dok.pk}', vertrag=vertrag, einschreiben=bool(einschreiben),
        versand_am=heute if einschreiben else None,
        frist_tage=frist_tage if frist_art == 'zugang' else None, erstellt_von=benutzer)


_NUR_ZIFFERN = re.compile(r'[^0-9A-Za-z .\-/]')


def sendungsnummer_bereinigt(roh):
    """Die Sendungsnummer ohne Steuerzeichen, auf 40 Zeichen."""
    return _NUR_ZIFFERN.sub('', (roh or '')).strip()[:40]
