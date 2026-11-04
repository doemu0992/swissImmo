# tickets/termin_pendenz.py
"""Pendenz «Termin offen»: Mieter und Handwerker finden keinen Termin.

Die Terminabstimmung läuft direkt zwischen Mieter und Handwerker
(``tickets/termin_abstimmung.py``); die Verwaltung wird dabei bewusst nicht bei
jeder Chat-Nachricht benachrichtigt. Kommt nach ``TERMIN_OFFEN_TAGE`` Tagen kein
Termin zustande, entsteht EINE Pendenz je Auftrag — kein Mail, nur die Pendenz.

* **Wartet** ein Auftrag, wenn er nicht abgeschlossen ist (Status weder
  «erledigt» noch «storniert»), das Ticket nicht erledigt ist und nicht auf die
  Rechnung wartet, keine Eigentümerfreigabe aussteht oder abgelehnt wurde und der
  Terminstatus nicht «vereinbart» ist (also «offen», «vorgeschlagen»
  = Vorschlag unbeantwortet, oder «abgesagt»).
* **Seit wann**: ab Auftragserteilung (``beauftragt_am``), bei einem unbeantworteten
  Vorschlag ab dem letzten Terminvorschlag (Zeitpunkt der Chat-Nachricht
  «Terminvorschlag: …»; ``termin_vorschlag_am`` ist der vorgeschlagene Termin,
  nicht der Zeitpunkt des Vorschlags). Ein Gegenvorschlag setzt die Frist neu an.
* **Schluss**: Die Pendenz schliesst sich im selben Lauf, sobald der Auftrag nicht
  mehr wartet (Termin vereinbart, Auftrag erledigt/storniert, Ticket erledigt).
  Eine von Hand abgehakte Pendenz bleibt abgehakt; es entsteht keine zweite.

Läuft im Kontext genau einer Verwaltung (``generate_auto_pendenzen``); die
Auftragsabfrage ist über das Ticket mandantengefiltert.
"""
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

#: Tage ohne vereinbarten Termin, bevor die Verwaltung eine Pendenz bekommt.
#: Eine Konstante für alle Verwaltungen: Es gibt (noch) keine Einstellung je Organisation.
TERMIN_OFFEN_TAGE = 5

QUELLE = 'auto:termin:'
VORSCHLAG_MARKE = 'Terminvorschlag:'      # Beginn der Chat-Nachricht in termin_abstimmung.vorschlagen


def _quelle(auftrag):
    return f"{QUELLE}{auftrag.pk}:{auftrag.ticket_id}"


def wartende_auftraege():
    """Aktive Aufträge ohne vereinbarten Termin, mit dem Beginn des Wartens: ``[(auftrag, seit)]``."""
    from .handwerker_zugang import ABGESCHLOSSEN
    from .models import HandwerkerAuftrag, TicketNachricht
    auftraege = list(
        HandwerkerAuftrag.objects
        .exclude(status__in=ABGESCHLOSSEN)
        .exclude(ticket__status__in=('erledigt', 'wartet_auf_rechnung'))
        .exclude(freigabe_status__in=('ausstehend', 'abgelehnt'))
        .exclude(termin_status='vereinbart')
        .select_related('ticket', 'handwerker'))
    letzter_vorschlag = dict(
        TicketNachricht.objects
        .filter(auftrag_id__in=[a.pk for a in auftraege], typ='direkt',
                nachricht__startswith=VORSCHLAG_MARKE)
        .values_list('auftrag_id').annotate(zuletzt=Max('erstellt_am')))
    ergebnis = []
    for a in auftraege:
        seit = a.beauftragt_am
        if a.termin_status == 'vorgeschlagen':
            seit = letzter_vorschlag.get(a.pk) or seit
        ergebnis.append((a, seit))
    return ergebnis


def termin_offen_pendenzen(heute, ensure):
    """Pendenzen anlegen bzw. nachführen und erledigte schliessen.

    ``ensure(quelle, titel, faellig, kategorie, beschreibung, liegenschaft=…)`` ist die
    idempotente Anlage aus ``generate_auto_pendenzen``. Gibt die Zahl der Aufträge
    zurück, für die eine Pendenz offen ist."""
    from core.models import Pendenz
    wartend = wartende_auftraege()
    wartende_ids = {a.pk for a, _ in wartend}
    offen = 0
    for a, seit in wartend:
        seit_tag = timezone.localtime(seit).date()
        tage = (heute - seit_tag).days
        if tage < TERMIN_OFFEN_TAGE:
            continue
        offen += 1
        t = a.ticket
        firma = a.handwerker.firma
        schluss = f" – {firma} (seit {tage} Tagen)"
        kopf = f"Termin offen: #{t.pk} "
        titel = kopf + t.titel[:max(0, 200 - len(kopf) - len(schluss))] + schluss
        vorschlag = a.termin_status == 'vorgeschlagen'
        ensure(_quelle(a), titel, seit_tag + timedelta(days=TERMIN_OFFEN_TAGE), 'unterhalt',
               (f"Mieter und {firma} haben seit {tage} Tagen keinen Termin für Auftrag #{a.pk} gefunden"
                + (" (der letzte Terminvorschlag ist unbeantwortet)" if vorschlag else "")
                + ". Die Abstimmung läuft direkt zwischen den beiden — bei Bedarf nachfassen "
                  "oder selbst einen Termin festlegen."),
               liegenschaft=t.liegenschaft)
    for p in Pendenz.objects.filter(erledigt=False, quelle__startswith=QUELLE):
        try:
            auftrag_id = int(p.quelle[len(QUELLE):].split(':')[0])
        except ValueError:
            continue
        if auftrag_id not in wartende_ids:
            p.erledigt = True
            p.erledigt_am = heute
            p.save(update_fields=['erledigt', 'erledigt_am'])
    return offen
