from core.tenancy import AlleOrganisationenManager, TenantManager
from django.db import models


class Abonnement(models.Model):
    """Abonnement einer Organisation — die neue Quelle fuer Stufe und Status.

    `crm.Organisation.abo_plan` entfaellt zugunsten dieses Modells
    (PLAN-V7.md D7, Arbeitspaket M8). Das Feld dort bleibt vorerst als
    Altlast; `stufe_von()` liest ab sofort von hier.

    Eine Organisation hat i.d.R. ein aktives Abonnement. Historische Aos
    (Status 'ausgelaufen') bleiben stehen, damit ein Downgrade
    nachvollziehbar bleibt.
    """

    # Dieselben Schlüssel wie in core.funktionen.STUFEN — nicht als Zahlen,
    # nicht zweitdefinieren. Die Klartextnamen kommen aus docs/MARKT.md.
    STUFE_BASIS = 'basis'
    STUFE_AUFBAU = 'aufbau'
    STUFE_VERWALTUNG = 'verwaltung'
    STUFE_PORTFOLIO = 'portfolio'

    STUFEN = [
        (STUFE_BASIS, 'Start (Basis)'),
        (STUFE_AUFBAU, 'Team (Aufbau)'),
        (STUFE_VERWALTUNG, 'Professional (Verwaltung)'),
        (STUFE_PORTFOLIO, 'Enterprise (Portfolio)'),
    ]

    INTERVALL_MONATLICH = 'monatlich'
    INTERVALL_JAEHRLICH = 'jaehrlich'

    INTERVALLE = [
        (INTERVALL_MONATLICH, 'Monatlich'),
        (INTERVALL_JAEHRLICH, 'Jährlich'),
    ]

    STATUS_AKTIV = 'aktiv'
    STATUS_TEST = 'test'
    STATUS_AUSGELAUFEN = 'ausgelaufen'

    STATUS = [
        (STATUS_AKTIV, 'Aktiv'),
        (STATUS_TEST, 'Testphase'),
        (STATUS_AUSGELAUFEN, 'Ausgelaufen'),
    ]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='abonnements', verbose_name='Organisation')
    stufe = models.CharField(
        'Stufe', max_length=20, choices=STUFEN, default=STUFE_BASIS)
    intervall = models.CharField(
        'Abrechnungsintervall', max_length=10, choices=INTERVALLE,
        default=INTERVALL_MONATLICH)
    status = models.CharField(
        'Status', max_length=12, choices=STATUS, default=STATUS_TEST)
    testphase_bis = models.DateField(
        'Testphase bis', null=True, blank=True,
        help_text='Bis zu diesem Datum laeuft die Testphase. Danach wird '
                  'entweder aktiviert oder ausgelaufen.')
    anbieter_referenz = models.CharField(
        'Anbieter-Referenz', max_length=200, blank=True, default='',
        help_text='Identifikation beim Zahlungsanbieter (z.B. Stripe '
                  'Subscription-ID). Leer = kein Anbieter hinterlegt.')
    gekuendigt_auf = models.DateField(
        'Gekuendigt auf', null=True, blank=True,
        help_text='Datum der Kuendigung. Das Abo bleibt bis zum Ablauf '
                  'der bezahlten Periode aktiv, wechselt dann auf ausgelaufen.')
    erstellt_am = models.DateTimeField('Erstellt am', auto_now_add=True)
    aktualisiert_am = models.DateTimeField('Aktualisiert am', auto_now=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Abonnement'
        verbose_name_plural = 'Abonnements'
        ordering = ['-erstellt_am']

    def __str__(self):
        return (
            f'{self.organisation} — {self.get_stufe_display()} '
            f'({self.get_status_display()})'
        )
