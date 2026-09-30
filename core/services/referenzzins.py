"""Referenzzins-Änderungen festhalten und ihre Folgen für die Verträge benennen.

Jede Änderung des Satzes schreibt eine Zeile in die Historie (`ReferenzzinsStand`:
Stichtag, Quelle, alter und neuer Satz) und legt EINE Pendenz an, die sagt, wie
viele Verträge betroffen sind: Bei einer Senkung kann jeder Mieter eine
Herabsetzung verlangen (Art. 270a OR), bei einer Erhöhung hat der Vermieter eine
Anpassungsmöglichkeit (Art. 269a OR). Die Verwaltung muss das wissen, bevor der
Mieter fragt — die Pendenz führt zur Liste der Mietzinsanpassungen.
"""
from decimal import Decimal

from django.utils import timezone


def aenderung_festhalten(organisation, alt, neu, quelle='manuell'):
    """Schreibt die Historie und die Pendenz. Gibt den Stand zurück oder None,
    wenn sich nichts geändert hat."""
    from core.models import Pendenz
    from core.tenancy import organisation_kontext
    from crm.models import ReferenzzinsStand
    from rentals.models import Mietvertrag

    alt = Decimal(str(alt)) if alt is not None else None
    neu = Decimal(str(neu))
    if alt is not None and alt == neu:
        return None
    heute = timezone.localdate()
    with organisation_kontext(organisation):
        senkung = erhoehung = 0
        if alt is not None:
            for v in (Mietvertrag.objects.filter(status__in=('aktiv', 'gekuendigt'))
                      .select_related('einheit__liegenschaft')):
                # Bewertung gegen den NEUEN Satz, unabhängig davon, ob `organisation`
                # schon gespeichert ist: der Vergleich ist Basis des Vertrags ↔ neu.
                basis_zins, _basis_lik = v.effektive_basis()
                if neu < basis_zins:
                    senkung += 1
                elif neu > basis_zins:
                    erhoehung += 1
        stand = ReferenzzinsStand.objects.create(
            organisation=organisation, stichtag=heute, satz=neu, vorher=alt, quelle=quelle,
            betroffene_senkung=senkung, betroffene_erhoehung=erhoehung)
        if alt is not None:
            Pendenz.objects.get_or_create(
                quelle=f'auto:refzins:{organisation.pk}:{neu}:{heute.isoformat()}',
                defaults={
                    'titel': f'Referenzzins {alt} % → {neu} %: {senkung} Senkung, {erhoehung} Erhöhung',
                    'beschreibung': (
                        f'Der Referenzzinssatz hat sich am {heute:%d.%m.%Y} von {alt} % auf {neu} % '
                        f'geändert ({stand.get_quelle_display()}). {senkung} Verträge haben Anspruch auf '
                        f'Herabsetzung (Art. 270a OR), bei {erhoehung} ist eine Erhöhung möglich '
                        f'(Art. 269a OR). Mietzinsanpassungen prüfen.'),
                    'kategorie': 'finanzen', 'faellig_am': heute})
        return stand
