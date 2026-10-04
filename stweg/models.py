"""STWEG: Akonto-Beiträge und Jahresabrechnung.

Eine STWEG erzielt keinen Ertrag — es gibt nur Kosten, die nach Wertquoten auf
die Stockwerkeigentümer verteilt werden. Die Eigentümer zahlen Akonto-Beiträge
(monatlich oder quartalsweise); die Jahresabrechnung stellt ihren Kostenanteil
den geleisteten Akontos gegenüber: Zahllast oder Guthaben.
"""
from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.organisation_kette import OrganisationAusKette


class StwegAkonto(OrganisationAusKette):
    """Eine Akonto-Zahlung eines Stockwerkeigentümers für seine Einheit."""
    ORGANISATION_PFAD = 'einheit__liegenschaft'
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.CASCADE, related_name='stweg_akontos')
    datum = models.DateField(default=timezone.localdate)
    betrag = models.DecimalField("Betrag (CHF)", max_digits=10, decimal_places=2)
    bemerkung = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'stweg_akonto'
        ordering = ['datum', 'id']
        verbose_name = 'Akonto-Zahlung'
        verbose_name_plural = 'Akonto-Zahlungen'

    def __str__(self):
        return f"{self.einheit.bezeichnung}: CHF {self.betrag} ({self.datum})"


class StwegAbrechnung(OrganisationAusKette):
    """Jahresabrechnung einer STWEG-Gemeinschaft (ein Kopf je Liegenschaft und Jahr)."""
    ORGANISATION_PFAD = 'liegenschaft'
    STATUS_ENTWURF = 'entwurf'
    STATUS_ABGESCHLOSSEN = 'abgeschlossen'
    STATUS_CHOICES = [(STATUS_ENTWURF, 'Entwurf'), (STATUS_ABGESCHLOSSEN, 'Abgeschlossen')]

    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE,
                                     related_name='stweg_abrechnungen')
    jahr = models.PositiveIntegerField()
    gesamtkosten = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=STATUS_ENTWURF)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'stweg_abrechnung'
        ordering = ['-jahr']
        constraints = [models.UniqueConstraint(fields=['liegenschaft', 'jahr'],
                                               name='stweg_abrechnung_je_liegenschaft_und_jahr')]

    def __str__(self):
        return f"STWEG-Abrechnung {self.jahr}: {self.liegenschaft}"


class StwegAbrechnungPosition(OrganisationAusKette):
    """Anteil einer Einheit an der Jahresabrechnung."""
    ORGANISATION_PFAD = 'abrechnung'
    abrechnung = models.ForeignKey(StwegAbrechnung, on_delete=models.CASCADE, related_name='positionen')
    einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.PROTECT, related_name='stweg_positionen')
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    wertquote = models.DecimalField(max_digits=7, decimal_places=2)
    wertquote_total = models.PositiveIntegerField()
    kostenanteil = models.DecimalField(max_digits=12, decimal_places=2)
    akonto = models.DecimalField(max_digits=12, decimal_places=2)
    #: Kostenanteil − Akonto. Positiv = Nachzahlung (Zahllast), negativ = Guthaben.
    saldo = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'stweg_abrechnung_position'
        ordering = ['einheit_id']

    @property
    def ist_zahllast(self):
        return self.saldo > 0

    @property
    def guthaben(self):
        return -self.saldo if self.saldo < 0 else Decimal('0.00')

    @property
    def zahllast(self):
        return self.saldo if self.saldo > 0 else Decimal('0.00')
