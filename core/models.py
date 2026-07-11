from core.utils import get_smart_upload_path, get_current_lik, get_current_ref_zins
from django.conf import settings
from django.db import models


class AktivitaetsLog(models.Model):
    """
    Audit-Trail: Wer hat wann was getan (Buchungsläufe, Löschungen, Versand …).
    Einträge werden über core.auth.log_aktion() geschrieben und sind im
    Notfall-Admin einsehbar (nur lesend).
    """
    zeitpunkt = models.DateTimeField("Zeitpunkt", auto_now_add=True)
    benutzer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Benutzer"
    )
    aktion = models.CharField("Aktion", max_length=100)
    objekt = models.CharField("Objekt", max_length=200, blank=True, default='')
    details = models.TextField("Details", blank=True, default='')
    # Optionaler Verweis auf das betroffene Objekt → macht Logeinträge anklickbar
    # und erlaubt einen "Verlauf" je Vertrag/Person/Liegenschaft.
    ziel_typ = models.CharField("Ziel-Typ", max_length=20, blank=True, default='', db_index=True)
    ziel_id = models.PositiveIntegerField("Ziel-ID", null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Aktivitätslog"
        verbose_name_plural = "Aktivitätslog"
        ordering = ['-zeitpunkt']
        indexes = [models.Index(fields=['ziel_typ', 'ziel_id'])]

    def __str__(self):
        wer = self.benutzer.username if self.benutzer else "System"
        return f"{self.zeitpunkt:%d.%m.%Y %H:%M} — {wer}: {self.aktion}"

    # Ziel-Typ → Detailseite unter /neu/. Nur Typen mit sinnvoller Detailansicht.
    _ZIEL_URLS = {
        'vertrag': '/neu/vertraege/{id}/',
        'person': '/neu/personen/{id}/',
        'liegenschaft': '/neu/liegenschaften/{id}/',
    }

    @property
    def ziel_url(self):
        if self.ziel_id and self.ziel_typ in self._ZIEL_URLS:
            return self._ZIEL_URLS[self.ziel_typ].format(id=self.ziel_id)
        return ''


class Pendenz(models.Model):
    """Persistente Pendenz / Frist. Ergänzt die automatisch berechneten Fristen
    (befristete Vertragsenden, Kündigungsfristen) um manuell erfassbare, abhakbare
    Aufgaben mit Fälligkeitsdatum."""
    KATEGORIE_CHOICES = [
        ('frist', 'Frist'),
        ('aufgabe', 'Aufgabe'),
        ('vertrag', 'Vertrag'),
        ('finanzen', 'Finanzen'),
        ('unterhalt', 'Unterhalt'),
        ('sonstiges', 'Sonstiges'),
    ]
    titel = models.CharField("Titel", max_length=200)
    beschreibung = models.TextField("Beschreibung", blank=True, default='')
    kategorie = models.CharField("Kategorie", max_length=20, choices=KATEGORIE_CHOICES, default='aufgabe')
    faellig_am = models.DateField("Fällig am", null=True, blank=True)
    erledigt = models.BooleanField("Erledigt", default=False)
    # Herkunft für automatisch generierte Pendenzen (idempotenter Schlüssel, z.B.
    # "auto:garantie:12"). Leer = manuell erfasst.
    quelle = models.CharField("Quelle", max_length=80, blank=True, default='', db_index=True)
    erledigt_am = models.DateField("Erledigt am", null=True, blank=True)

    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, null=True, blank=True, related_name='pendenzen')
    vertrag = models.ForeignKey('rentals.Mietvertrag', on_delete=models.CASCADE, null=True, blank=True, related_name='pendenzen')

    erstellt_am = models.DateTimeField(auto_now_add=True)
    erstellt_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Pendenz"
        verbose_name_plural = "Pendenzen"
        ordering = ['erledigt', 'faellig_am', '-erstellt_am']

    def __str__(self):
        return f"{self.titel} ({'erledigt' if self.erledigt else 'offen'})"
