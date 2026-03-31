# tickets/models.py
import uuid
from django.db import models
from core.utils import get_smart_upload_path

class SchadenMeldung(models.Model):
    STATUS_CHOICES = [('neu', 'Neu'), ('in_bearbeitung', 'In Bearbeitung'), ('warte_auf_mieter', 'Warte auf Mieter'), ('erledigt', 'Erledigt')]
    ZUTRITT_CHOICES = [('telefon', 'Termin via Telefon'), ('passpartout', 'Passpartout (Schlüssel vorhanden)')]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='schaeden')
    betroffene_einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True, related_name='schaeden')
    gemeldet_von = models.ForeignKey('crm.Mieter', on_delete=models.SET_NULL, null=True, blank=True, related_name='gemeldete_schaeden')

    titel = models.CharField("Titel / Schaden", max_length=200)
    beschreibung = models.TextField("Beschreibung")
    foto = models.ImageField(upload_to=get_smart_upload_path, blank=True, null=True)

    email_melder = models.EmailField("E-Mail Melder", blank=True, null=True)
    tel_melder = models.CharField("Telefon Melder", max_length=50, blank=True, null=True)

    zutritt = models.CharField("Zutritt / Termin", max_length=20, choices=ZUTRITT_CHOICES, default='telefon')
    mieter_email = models.EmailField("Mieter E-Mail (Legacy)", blank=True)
    mieter_telefon = models.CharField("Mieter Telefon (Legacy)", max_length=30, blank=True)

    prioritaet = models.CharField("Priorität", max_length=20, default='mittel')
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default='neu')
    gelesen = models.BooleanField(default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ticket / Schaden"
        verbose_name_plural = "Tickets / Schäden"
        ordering = ['-erstellt_am']
        db_table = 'core_schadenmeldung'

    def __str__(self): return f"Ticket #{self.id}: {self.titel}"

class HandwerkerAuftrag(models.Model):
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='handwerker_auftraege')
    handwerker = models.ForeignKey('crm.Handwerker', on_delete=models.CASCADE, related_name='auftraege')
    status = models.CharField(max_length=20, default='offen')
    beauftragt_am = models.DateTimeField(auto_now_add=True)
    bemerkung = models.TextField(blank=True)

    class Meta:
        verbose_name = "Handwerker-Auftrag"
        db_table = 'core_handwerkerauftrag'

class TicketNachricht(models.Model):
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='nachrichten')
    absender_name = models.CharField(max_length=100)
    TYP_CHOICES = [('chat', 'Chat'), ('system', 'System'), ('mail_antwort', 'Mail Antwort'), ('antwort_senden', 'Antwort Senden'), ('handwerker_mail', 'Handwerker Mail')]
    typ = models.CharField(max_length=20, choices=TYP_CHOICES, default='chat')
    nachricht = models.TextField()
    datei = models.FileField(upload_to='ticket_anhang/', blank=True, null=True)
    cc_email = models.CharField("CC (Optional)", max_length=200, blank=True)
    empfaenger_handwerker = models.ForeignKey('crm.Handwerker', on_delete=models.SET_NULL, null=True, blank=True)
    gelesen = models.BooleanField(default=False)
    is_intern = models.BooleanField(default=False)
    is_von_verwaltung = models.BooleanField(default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-erstellt_am']
        verbose_name = "Historie / Nachricht"
        db_table = 'core_ticketnachricht'