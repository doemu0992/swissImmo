"""Das Regelwerk — Fristen und Termine als Daten, nicht als Code.

WARUM DATEN UND NICHT CODE

Die Regeln sind bei Auslieferung **nicht juristisch geprüft** (Entscheid vom
19.08.2026: nachträglich anpassen lassen). Eine Korrektur muss deshalb eine
Datenänderung sein und kein Deployment. Ausserdem gelten ortsübliche Termine
kantonal verschieden und vertraglich abweichend — das liesse sich in Code nur
als wachsende Sammlung von Sonderfällen abbilden.

WARUM JEDE ANWENDUNG PROTOKOLLIERT WIRD

Das ist die eigentliche Bedingung dafür, dass «nachträglich anpassen»
funktioniert. Wird eine Regel später berichtigt, muss auffindbar sein, welche
Fälle unter der alten Fassung entschieden wurden. Ohne `Regelanwendung` wäre
die Antwort auf «welche Kündigungen haben wir falsch bestätigt» eine
Handdurchsicht aller Akten.

Deshalb hält jeder Eintrag den **Stand** der Regel fest, nicht nur ihre ID: Der
Stand ändert sich bei jeder inhaltlichen Korrektur, und damit lässt sich eine
Menge betroffener Fälle exakt abgrenzen.

WARUM WARNUNG UND NICHT SPERRE

Voreinstellung ist `warnung`. Eine Regel, die nicht geprüft ist, darf den
Betrieb nicht anhalten — und selbst eine geprüfte Regel kennt den Sonderfall
nicht, den die Bewirtschafterin vor sich hat. Wer übersteuert, muss begründen,
und die Begründung steht im Protokoll.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.organisation_kette import OrganisationAusKette, organisation_aus_kontext
from core.tenancy import AlleOrganisationenManager, TenantManager


class Regelsatz(models.Model):
    """Ein zusammengehörender Satz Regeln, je Organisation und Geltungsbereich.

    `stand` ist das Datum der letzten inhaltlichen Änderung. Es wandert in jedes
    Protokoll und ist der Schlüssel für eine spätere Berichtigung.
    """

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='regelsaetze', verbose_name='Organisation')
    bezeichnung = models.CharField('Bezeichnung', max_length=120)
    kanton = models.CharField(
        'Kanton', max_length=2, blank=True,
        help_text='Leer bedeutet: gilt für alle Kantone dieser Verwaltung.')
    stand = models.DateField('Stand', default=timezone.localdate)
    geprueft = models.BooleanField(
        'Juristisch geprüft', default=False,
        help_text='Ungeprüfte Regeln warnen, sie sperren nicht.')
    hinweis = models.TextField('Hinweis', blank=True)
    aktiv = models.BooleanField('Aktiv', default=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Regelsatz'
        verbose_name_plural = 'Regelsätze'
        ordering = ('bezeichnung',)
        constraints = [
            models.UniqueConstraint(
                fields=('organisation', 'kanton'),
                name='regelsatz_je_organisation_und_kanton'),
        ]

    def __str__(self):
        return f'{self.bezeichnung}{f" ({self.kanton})" if self.kanton else ""}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_aus_kontext()
        super().save(*args, **kwargs)


class Regel(OrganisationAusKette):
    """Eine einzelne Regel mit ihren Parametern.

    `parameter` ist bewusst ein freies Feld: Jede Regelart braucht andere
    Angaben, und eine Spalte je Regelart wäre eine Tabelle, die mit jeder neuen
    Regel wächst. Was eine Regelart erwartet, steht in `faelle.regelwerk`.
    """

    ORGANISATION_PFAD = 'regelsatz'

    KUENDIGUNGSTERMIN = 'kuendigungstermin'
    ZAHLUNGSFRIST = 'zahlungsfrist'
    MIETZINS_ZUSTELLUNG = 'mietzins_zustellung'
    KAUTION_HOECHSTBETRAG = 'kaution_hoechstbetrag'
    ARTEN = [
        (KUENDIGUNGSTERMIN, 'Kündigungstermin und -frist'),
        (ZAHLUNGSFRIST, 'Zahlungsfrist bei Verzug'),
        (MIETZINS_ZUSTELLUNG, 'Zustellfrist Mietzinsänderung'),
        (KAUTION_HOECHSTBETRAG, 'Höchstbetrag der Kaution'),
    ]

    WARNUNG, SPERRE = 'warnung', 'sperre'
    VERBINDLICHKEIT = [
        (WARNUNG, 'Warnt, lässt aber weiterarbeiten'),
        (SPERRE, 'Verhindert das Speichern'),
    ]

    regelsatz = models.ForeignKey(
        Regelsatz, on_delete=models.CASCADE, related_name='regeln')
    art = models.CharField('Regelart', max_length=40, choices=ARTEN)
    verbindlichkeit = models.CharField(
        'Verbindlichkeit', max_length=10, choices=VERBINDLICHKEIT, default=WARNUNG)
    parameter = models.JSONField('Parameter', default=dict, blank=True)
    begruendung = models.TextField(
        'Begründung', blank=True,
        help_text='Woher die Regel stammt. Steht im Hinweistext für die Bearbeitung.')
    aktiv = models.BooleanField('Aktiv', default=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Regel'
        verbose_name_plural = 'Regeln'
        ordering = ('regelsatz', 'art')
        constraints = [
            models.UniqueConstraint(
                fields=('regelsatz', 'art'), name='regel_je_satz_und_art'),
        ]

    def __str__(self):
        return f'{self.get_art_display()} · {self.regelsatz}'


class Regelanwendung(models.Model):
    """Protokoll: welche Regel hat wann was zu welcher Eingabe gesagt.

    ENTSTEHT AUCH DANN, WENN ALLES IN ORDNUNG WAR. Ein Protokoll, das nur
    Beanstandungen aufnimmt, beantwortet die entscheidende Frage nicht: «Welche
    Kündigungen wurden unter der alten Fassung geprüft?» Auch ein Befund ohne
    Beanstandung ist eine Prüfung unter einer bestimmten Regelfassung.
    """

    OK, BEANSTANDET = 'ok', 'beanstandet'
    BEFUNDE = [(OK, 'Ohne Beanstandung'), (BEANSTANDET, 'Beanstandet')]

    organisation = models.ForeignKey(
        'crm.Organisation', on_delete=models.CASCADE,
        related_name='regelanwendungen', editable=False)
    art = models.CharField('Regelart', max_length=40)
    regel_stand = models.DateField(
        'Stand der Regel',
        help_text='Fassung, unter der geprüft wurde — Schlüssel für Berichtigungen.')
    geprueft_war = models.BooleanField('Regel war juristisch geprüft', default=False)

    fall = models.ForeignKey(
        'faelle.Fall', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='regelanwendungen')

    eingabe = models.JSONField('Eingabe', default=dict)
    ergebnis = models.JSONField('Ergebnis', default=dict)
    befund = models.CharField('Befund', max_length=15, choices=BEFUNDE)
    meldung = models.TextField('Meldung', blank=True)

    uebersteuert = models.BooleanField('Übersteuert', default=False)
    uebersteuert_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='regeluebersteuerungen')
    uebersteuert_begruendung = models.TextField('Begründung', blank=True)

    zeitpunkt = models.DateTimeField('Zeitpunkt', default=timezone.now)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Regelanwendung'
        verbose_name_plural = 'Regelanwendungen'
        ordering = ('-zeitpunkt',)
        indexes = [
            models.Index(fields=('organisation', 'art', 'regel_stand')),
        ]

    def __str__(self):
        return f'{self.art} · {self.zeitpunkt:%d.%m.%Y} · {self.befund}'

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = (
                getattr(self.fall, 'organisation_id', None)
                or organisation_aus_kontext())
        super().save(*args, **kwargs)

    def uebersteuern(self, benutzer, begruendung):
        """Die Beanstandung wird bewusst überstimmt.

        Ohne Begründung geht das nicht — sonst wäre das Protokoll eine Liste
        von Klicks statt von Entscheidungen.
        """
        if not begruendung or not begruendung.strip():
            raise ValueError('Ein Übersteuern ohne Begründung wird nicht gespeichert.')
        self.uebersteuert = True
        self.uebersteuert_von = benutzer
        self.uebersteuert_begruendung = begruendung.strip()
        self.save(update_fields=['uebersteuert', 'uebersteuert_von',
                                 'uebersteuert_begruendung'])
        return self
