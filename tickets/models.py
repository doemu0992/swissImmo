# tickets/models.py
import uuid
from django.conf import settings
from django.db import models
from core.organisation_kette import OrganisationAusKette
from core.utils import get_smart_upload_path
from django.utils.translation import gettext_lazy as _

class SchadenMeldung(OrganisationAusKette):
    ORGANISATION_PFAD = 'liegenschaft'
    STATUS_CHOICES = [
        ('neu', _('Neu')),
        ('in_bearbeitung', _('In Bearbeitung')),
        ('warte_auf_mieter', _('Warte auf Mieter')),
        ('warte_auf_handwerker', _('Warte auf Handwerker')),
        ('wartet_auf_rechnung', _('Wartet auf Rechnung')),
        ('erledigt', _('Erledigt'))
    ]
    ZUTRITT_CHOICES = [
        ('telefon', _('Termin via Telefon')),
        ('passpartout', _('Passpartout (Schlüssel vorhanden)'))
    ]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    liegenschaft = models.ForeignKey('portfolio.Liegenschaft', on_delete=models.CASCADE, related_name='schaeden')
    betroffene_einheit = models.ForeignKey('portfolio.Einheit', on_delete=models.SET_NULL, null=True, blank=True, related_name='schaeden')

    gemeldet_von = models.ForeignKey('crm.Mieter', on_delete=models.SET_NULL, null=True, blank=True, related_name='gemeldete_schaeden')

    # Raumbuch: betroffenes Ausstattungselement (Reparaturhistorie/Lebenszykluskosten)
    ausstattung = models.ForeignKey('portfolio.Ausstattung', on_delete=models.SET_NULL, null=True, blank=True, related_name='schaeden')

    # Sektionsfelder aus dem Multi-Step-Formular
    kategorie = models.CharField("Kategorie", max_length=100, blank=True, null=True)
    raum = models.CharField("Raum", max_length=100, blank=True, null=True)
    objekt = models.CharField("Objekt", max_length=100, blank=True, null=True)

    melder_vorname = models.CharField("Vorname Melder", max_length=100, blank=True, null=True)
    melder_nachname = models.CharField("Nachname Melder", max_length=100, blank=True, null=True)

    titel = models.CharField("Titel / Schaden", max_length=200)
    beschreibung = models.TextField("Beschreibung")
    foto = models.ImageField(upload_to=get_smart_upload_path, blank=True, null=True)

    email_melder = models.EmailField("E-Mail Melder", blank=True, null=True)
    tel_melder = models.CharField("Telefon Melder", max_length=50, blank=True, null=True)

    zutritt = models.CharField("Zutritt / Termin", max_length=20, choices=ZUTRITT_CHOICES, default='telefon')

    # Legacy-Felder
    mieter_email = models.EmailField("Mieter E-Mail (Legacy)", blank=True)
    mieter_telefon = models.CharField("Mieter Telefon (Legacy)", max_length=30, blank=True)

    #: STWEG: Was ist betroffen, und wer trägt die Kosten? (`stweg.bauteile`; Art. 712b ZGB). Leer ausserhalb einer STWEG.
    bauteil = models.CharField("Betroffenes Bauteil", max_length=20, blank=True, default='')
    kostentraeger = models.CharField("Kostenträger (STWEG)", max_length=20, blank=True, default='')
    prioritaet = models.CharField("Priorität", max_length=20, default='mittel')
    # Interne Zuständigkeit und Zielzeit (Phase-1-Audit): bisher gab es nur die
    # Zuweisung an Handwerker. `faellig_bis` wird beim Anlegen aus der Priorität
    # vorbelegt (tickets/sla.py), kann aber überschrieben werden.
    zugewiesen_an = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='zugewiesene_tickets', verbose_name="Zuständig (intern)")
    faellig_bis = models.DateField("Erledigen bis (SLA)", null=True, blank=True)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default='neu')
    gelesen = models.BooleanField(default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)

    def _sonderrecht_sperre(self):
        """Sonderrecht auf zwingend gemeinschaftlichem Bauteil (STWEG, Art. 712b ZGB) wird nie gespeichert."""
        if self.kostentraeger and self.bauteil and self.liegenschaft_id and self.liegenschaft.ist_stweg:
            from stweg.bauteile import sperre
            fehler = sperre(self.bauteil, self.kostentraeger)
            if fehler:
                from django.core.exceptions import ValidationError
                raise ValidationError(fehler, code='sonderrecht_gesperrt')

    def clean(self):
        # Admin-/ModelForm-Weg: Fehler am Formular statt 500.
        self._sonderrecht_sperre()
        if self.status == 'erledigt' and self.pk:
            from .workflow import abschluss_pruefen
            abschluss_pruefen(self)

    def save(self, *args, **kwargs):
        # Sicherheitssperre (tickets/workflow.py): ein Ticket mit Handwerker-
        # auftrag wird nicht «erledigt», solange eine Handwerkerrechnung fehlt.
        # Sie sitzt im Modell, nicht in der Ansicht — sonst umgeht sie die
        # Admin-Aktion, ein Skript oder die nächste Ansicht.
        self._sonderrecht_sperre()
        if self.status == 'erledigt' and self.pk:
            from .workflow import abschluss_pruefen
            abschluss_pruefen(self)
        if not self.pk and not self.faellig_bis:
            from .sla import faellig_bis_fuer
            self.faellig_bis = faellig_bis_fuer(self.prioritaet)
        super().save(*args, **kwargs)
        # Ein erledigtes Ticket schliesst seine Handwerkeraufträge. Der Status
        # des Auftrags änderte sich nie («offen» auch bei erledigtem Ticket und
        # bezahlter Rechnung, Stresstest 30.09.2026, Punkt 15) und hielt die
        # Liste «liegt» der Akten dauerhaft rot.
        if self.status == 'erledigt' and self.pk:
            self.handwerker_auftraege.exclude(status='erledigt').update(status='erledigt')

    class Meta:
        verbose_name = "Ticket / Schaden"
        verbose_name_plural = "Tickets / Schäden"
        ordering = ['-erstellt_am']
        db_table = 'core_schadenmeldung'

    def __str__(self):
        return f"Ticket #{self.id}: {self.titel}"


class SchadenFoto(OrganisationAusKette):
    ORGANISATION_PFAD = 'schaden'
    """Mehrere Fotos pro Schadenmeldung (Dokumentation). Das Legacy-Einzelfeld
    SchadenMeldung.foto bleibt bestehen und wird zusätzlich angezeigt."""
    schaden = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='fotos')
    bild = models.ImageField(upload_to=get_smart_upload_path)
    beschreibung = models.CharField(max_length=200, blank=True, default='')
    hochgeladen_am = models.DateTimeField(auto_now_add=True)
    hochgeladen_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Schaden-Foto"
        verbose_name_plural = "Schaden-Fotos"
        ordering = ['hochgeladen_am']
        db_table = 'core_schadenfoto'

    def __str__(self):
        return f"Foto zu Ticket #{self.schaden_id}"


class HandwerkerAuftrag(OrganisationAusKette):
    ORGANISATION_PFAD = 'ticket'
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='handwerker_auftraege')
    # 🔥 WIEDER ZURÜCK: Verweist auf den CRM Handwerker
    handwerker = models.ForeignKey('crm.Handwerker', on_delete=models.CASCADE, related_name='auftraege')
    status = models.CharField(max_length=20, default='offen')
    beauftragt_am = models.DateTimeField(auto_now_add=True)
    bemerkung = models.TextField(blank=True)

    # 🔥 Kostenkontrolle (Reparatur-Budget)
    kosten_geschaetzt = models.DecimalField("Kostenschätzung (CHF)", max_digits=10, decimal_places=2, null=True, blank=True)
    kosten_effektiv = models.DecimalField("Effektive Kosten (CHF)", max_digits=10, decimal_places=2, null=True, blank=True)
    kreditoren_rechnung = models.ForeignKey('finance.KreditorenRechnung', on_delete=models.SET_NULL, null=True, blank=True, related_name='handwerker_auftraege')

    # Terminvereinbarung Handwerker <-> Mieter (tickets/workflow.py: termin_festlegen)
    TERMIN_CHOICES = [
        ('offen', _('Kein Termin')),
        ('vereinbart', _('Termin vereinbart')),
        ('abgesagt', _('Termin abgesagt')),
    ]
    termin_am = models.DateTimeField("Termin", null=True, blank=True)
    termin_status = models.CharField("Terminstatus", max_length=12, choices=TERMIN_CHOICES, default='offen')

    # 🔥 Reparaturfreigabe durch den Eigentümer (Portal)
    FREIGABE_CHOICES = [
        ('nicht_noetig', _('Keine Freigabe nötig')),
        ('ausstehend', _('Freigabe ausstehend')),
        ('freigegeben', _('Freigegeben')),
        ('abgelehnt', _('Abgelehnt')),
    ]
    freigabe_status = models.CharField("Freigabe-Status", max_length=20, choices=FREIGABE_CHOICES, default='nicht_noetig')
    freigabe_datum = models.DateTimeField("Freigabe am", null=True, blank=True)
    freigabe_kommentar = models.TextField("Kommentar Eigentümer", blank=True, default='')

    class Meta:
        verbose_name = "Handwerker-Auftrag"
        db_table = 'core_handwerkerauftrag'

    @property
    def freigabe_ausstehend(self):
        return self.freigabe_status == 'ausstehend'


class TicketNachricht(OrganisationAusKette):
    ORGANISATION_PFAD = 'ticket'
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='nachrichten')
    absender_name = models.CharField(max_length=100)
    TYP_CHOICES = [
        ('chat', _('Chat')),
        ('system', _('System')),
        ('mail_antwort', _('Mail Antwort')),
        ('antwort_senden', _('Antwort Senden')),
        ('handwerker_mail', _('Handwerker Mail')),
        ('email', _('Ausgehende E-Mail'))
    ]
    typ = models.CharField(max_length=20, choices=TYP_CHOICES, default='chat')
    nachricht = models.TextField()
    datei = models.FileField(upload_to='ticket_anhang/', blank=True, null=True)
    cc_email = models.CharField("CC (Optional)", max_length=200, blank=True)
    # 🔥 WIEDER ZURÜCK: Verweist auf den CRM Handwerker
    empfaenger_handwerker = models.ForeignKey('crm.Handwerker', on_delete=models.SET_NULL, null=True, blank=True)
    gelesen = models.BooleanField(default=False)
    is_intern = models.BooleanField(default=False)
    is_von_verwaltung = models.BooleanField(default=False)
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-erstellt_am']
        verbose_name = "Historie / Nachricht"
        db_table = 'core_ticketnachricht'


class Versicherungsfall(OrganisationAusKette):
    """Ein Schaden, der bei der Gebäudeversicherung gemeldet ist.

    Hält fest, was bei einem Wasserschaden bisher nirgends stand (Stresstest
    30.09.2026): Police, Schadennummer, Meldedatum, Selbstbehalt, wer ihn trägt, und
    was die Versicherung zahlt. Die Rechnung liegt bei den Handwerkeraufträgen des
    Tickets; hier stehen die Beträge zwischen Eigentümer, Mieter und Versicherung.
    """
    ORGANISATION_PFAD = 'ticket'
    STATUS = [
        ('gemeldet', _('Gemeldet')),
        ('abklaerung', _('In Abklärung')),
        ('entschaedigt', _('Entschädigt')),
        ('abgelehnt', _('Abgelehnt')),
    ]
    TRAEGER = [
        ('eigentuemer', _('Eigentümer')),
        ('mieter', _('Mieter (Überwälzung)')),
    ]
    ticket = models.ForeignKey(SchadenMeldung, on_delete=models.CASCADE, related_name='versicherungsfaelle')
    police = models.ForeignKey('portfolio.Versicherung', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='faelle')
    schadennummer = models.CharField("Schadennummer", max_length=60, blank=True, default='')
    gemeldet_am = models.DateField("Gemeldet am")
    schadensumme = models.DecimalField("Schadensumme (CHF)", max_digits=10, decimal_places=2,
                                       null=True, blank=True)
    selbstbehalt = models.DecimalField("Selbstbehalt (CHF)", max_digits=10, decimal_places=2,
                                       default=0)
    selbstbehalt_traeger = models.CharField("Selbstbehalt trägt", max_length=12, choices=TRAEGER,
                                            default='eigentuemer')
    selbstbehalt_rechnung = models.ForeignKey('finance.DebitorenRechnung', on_delete=models.SET_NULL,
                                              null=True, blank=True, related_name='+')
    entschaedigung_erhalten = models.DecimalField("Entschädigung erhalten (CHF)", max_digits=10,
                                                  decimal_places=2, null=True, blank=True)
    entschaedigung_am = models.DateField("Entschädigung eingegangen am", null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='gemeldet')
    bemerkung = models.CharField(max_length=255, blank=True, default='')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Versicherungsfall"
        verbose_name_plural = "Versicherungsfälle"
        ordering = ['-gemeldet_am', '-id']

    def __str__(self):
        return f"Versicherungsfall Ticket #{self.ticket_id} ({self.get_status_display()})"

    @property
    def erwartete_entschaedigung(self):
        """Schadensumme abzüglich Selbstbehalt — was die Versicherung voraussichtlich zahlt."""
        from decimal import Decimal
        if self.schadensumme is None:
            return None
        return max(self.schadensumme - (self.selbstbehalt or Decimal('0')), Decimal('0.00'))
