"""Zahlungseingänge wirken sofort auf laufende Fristen (Art. 257d OR).

Zahlungen entstehen an vielen Stellen — Bankabgleich (camt.053), manuelle
Erfassung auf der Vertragsakte, QR-Zuordnung, Nebenkosten, Import. Die Folge
für eine laufende Kündigungsandrohung an jede dieser Stellen zu schreiben,
hiesse: an der nächsten neuen Stelle fehlt sie, und eine gewahrte Frist steht
weiter als «Kündigung möglich» im System. Darum hier, einmal, am Modell.

Auch der Storno einer Rechnung zählt: Eine stornierte Forderung ist keine,
deren Nichtzahlung eine Kündigung trüge.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from finance.models import DebitorenRechnung, Zahlungseingang

logger = logging.getLogger(__name__)


def _pruefen(vertrag_id):
    if not vertrag_id:
        return
    from core.services.zahlungsverzug import pruefe_nach_zahlung
    from rentals.models import Mietvertrag
    # `alle_organisationen`: Der Vertrag wird über den Fremdschlüssel eines
    # soeben gespeicherten Datensatzes geholt, der ihn schon besitzt — keine
    # Suche über die Mandantengrenze. Die eigentliche Prüfung läuft danach im
    # Kontext der Organisation dieses Vertrags (`pruefe_nach_zahlung`).
    vertrag = Mietvertrag.alle_organisationen.filter(pk=vertrag_id).first()
    try:
        pruefe_nach_zahlung(vertrag)
    except Exception:
        # Eine Zahlung darf nie daran scheitern, dass die Fristprüfung
        # scheitert — aber laut, damit es auffällt.
        logger.exception('257d-Prüfung nach Zahlung für Vertrag %s fehlgeschlagen',
                         vertrag_id)


def _guthaben_pendenz(z):
    """Ein neues Mieterguthaben (Konto 2030) braucht einen Entscheid: verrechnen
    oder zurückerstatten. Ohne Pendenz liegt es monatelang auf 2030 (Stresstest
    30.09.2026: Überzahlung und Doppelzahlung waren als Vorgang nicht vorgesehen).
    Erledigt sich im täglichen Lauf, sobald das Guthaben nicht mehr auf 2030 steht."""
    from core.models import Pendenz
    from core.tenancy import organisation_kontext
    from rentals.models import Mietvertrag

    vertrag = Mietvertrag.alle_organisationen.filter(pk=z.vertrag_id).select_related(
        'mieter', 'einheit__liegenschaft').first()
    if vertrag is None:
        return
    with organisation_kontext(vertrag.organisation):
        Pendenz.objects.get_or_create(
            quelle=f'auto:guthaben:{z.pk}',
            defaults={
                'titel': f'Mieterguthaben CHF {z.betrag:.2f}: verrechnen oder zurückerstatten – '
                         f'{vertrag.mieter.display_name}',
                'beschreibung': 'Überzahlung oder Doppelzahlung liegt als Guthaben auf Konto 2030. '
                                'Mit einer offenen Forderung verrechnen («Zuordnen») oder dem Mieter '
                                'zurückzahlen («Zurückerstatten») — beides im Bankabgleich.',
                'kategorie': 'finanzen', 'faellig_am': z.datum_eingang, 'vertrag': vertrag,
                'liegenschaft': vertrag.einheit.liegenschaft if vertrag.einheit_id else None})


@receiver(post_save, sender=Zahlungseingang, dispatch_uid='zahlung_257d')
def _zahlung_gespeichert(sender, instance, raw=False, created=False, **kwargs):
    if raw:
        return
    if (created and instance.status == 'verbucht' and instance.konto_id
            and instance.vertrag_id and instance.konto.nummer == '2030'):
        try:
            _guthaben_pendenz(instance)
        except Exception:
            logger.exception('Guthaben-Pendenz für Zahlung %s nicht angelegt', instance.pk)
    vertrag_id = instance.vertrag_id
    if not vertrag_id and instance.debitoren_rechnung_id:
        vertrag_id = (DebitorenRechnung.alle_organisationen
                      .filter(pk=instance.debitoren_rechnung_id)
                      .values_list('vertrag_id', flat=True).first())
    _pruefen(vertrag_id)


@receiver(post_save, sender=DebitorenRechnung, dispatch_uid='rechnung_257d')
def _rechnung_gespeichert(sender, instance, raw=False, created=False, **kwargs):
    if raw or created:
        return
    _pruefen(instance.vertrag_id)
