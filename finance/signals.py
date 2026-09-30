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


@receiver(post_save, sender=Zahlungseingang, dispatch_uid='zahlung_257d')
def _zahlung_gespeichert(sender, instance, raw=False, **kwargs):
    if raw:
        return
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
