from core.utils import get_smart_upload_path, get_current_lik, get_current_ref_zins
from django.conf import settings
from django.db import models

from core.tenancy import AlleOrganisationenManager, TenantManager
from core.organisation_kette import OrganisationAusKette, organisation_bestimmen


class SicherheitsEreignis(models.Model):
    """Sicherheitsereignisse OHNE bestimmbare Verwaltung — das Betreiberlog.

    WARUM ES DIESE TABELLE GIBT (Entscheid 18.08.2026, Audit Lü2)

    `AktivitaetsLog` verlangt eine Organisation, und das ist richtig: Jeder
    Eintrag dort gehört einer Verwaltung und erscheint in deren Logbuch. Nur
    gibt es eine Sorte Ereignis, die keiner gehört — der Anmeldeversuch mit
    einem Benutzernamen, den es gar nicht gibt. Er trifft die INSTALLATION,
    nicht einen Mandanten.

    Vor dieser Tabelle fiel er durch: `log_aktion` fand keine Organisation,
    das Schreiben warf, und die Ausnahme wurde geschluckt. Gemessen im Audit:
    546 → 547 Einträge vor der Etappe, 546 → 546 danach. Brute-Force-Versuche
    hinterliessen KEINE Spur, obwohl die Kategorie `sicherheit` als
    revisionsrelevant gilt.

    DIE ALTERNATIVE, UND WARUM SIE VERWORFEN WURDE. Man hätte `organisation`
    an `AktivitaetsLog` nullbar machen können. Dann wäre aber ausgerechnet in
    der revisionsrelevanten Tabelle wieder unklar, ob NULL «gehört niemandem»
    oder «wurde vergessen» heisst — genau die Zweideutigkeit, die Etappe 5 aus
    dem ganzen Datenmodell entfernt hat. Eine eigene Tabelle sagt es im Namen.

    SIE TRÄGT BEWUSST KEINEN ORGANISATIONSBEZUG und steht deshalb in
    `test_isolation.OHNE_MANDANTENFILTER` — als dritter und einziger neuer
    Eintrag seit dem Bestehen dieser Liste. Der Datenreset fasst sie nicht an
    (Eintrag in `KEEP`): Sie sind Betriebsdaten, nicht Mandantendaten.

    Gelesen wird sie über `manage.py sicherheitslog`.
    """
    zeitpunkt = models.DateTimeField("Zeitpunkt", auto_now_add=True, db_index=True)
    aktion = models.CharField("Aktion", max_length=100)
    objekt = models.CharField("Betroffen", max_length=200, blank=True, default='')
    details = models.TextField("Details", blank=True, default='')
    ip_adresse = models.GenericIPAddressField("IP-Adresse", null=True, blank=True,
                                              db_index=True)

    class Meta:
        verbose_name = "Sicherheitsereignis"
        verbose_name_plural = "Sicherheitsereignisse"
        ordering = ['-zeitpunkt']

    def __str__(self):
        return f"{self.zeitpunkt:%d.%m.%Y %H:%M} {self.aktion} — {self.objekt}"


class AktivitaetsLog(models.Model):
    """
    Audit-Trail: Wer hat wann was getan (Buchungsläufe, Löschungen, Versand …).
    Einträge werden über core.auth.log_aktion() geschrieben und sind im
    Notfall-Admin einsehbar (nur lesend).
    """
    # DER AUDIT-TRAIL — und der Grund, warum er eine eigene Spalte braucht.
    #
    # AktivitaetsLog hat genau EINEN Fremdschluessel: `benutzer`. Und der fuehrt
    # seit dem Entscheid vom 15.08.2026 bewusst nirgendwohin — `Benutzer` traegt
    # keinen Organisationsbezug, weil eine Person ueber `Mitgliedschaft` fuer
    # mehrere Verwaltungen arbeiten koennen soll. Es gibt hier also nichts
    # abzuleiten; der Bezug muss beim Schreiben gesetzt werden.
    #
    # Der Skill `phase-2-migration` nennt dieses Modell ausdruecklich als den
    # heikelsten Fall: Es waechst laufend, ist rechtlich relevant, und je
    # spaeter man es anfasst, desto mehr Zeilen sind umzuschreiben. 546 sind es
    # heute.
    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE,
                                     editable=False, related_name='%(app_label)s_%(class)s',
                                     verbose_name='Organisation')

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)

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
    # Strukturierte Kategorie (aus der Aktion abgeleitet) für zuverlässige Filter.
    KATEGORIE_CHOICES = [
        ('erstellt', 'Erstellt / erfasst'),
        ('bearbeitet', 'Bearbeitet / geändert'),
        ('geloescht', 'Gelöscht / storniert'),
        ('finanzen', 'Finanzen / Buchung'),
        ('versand', 'Versand / Kommunikation'),
        ('sicherheit', 'Sicherheit / Login'),
        ('sonstiges', 'Sonstiges'),
    ]
    kategorie = models.CharField("Kategorie", max_length=20, blank=True, default='', db_index=True)
    ip_adresse = models.GenericIPAddressField("IP-Adresse", null=True, blank=True)


    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()
    class Meta:
        verbose_name = "Aktivitätslog"
        verbose_name_plural = "Aktivitätslog"
        ordering = ['-zeitpunkt']
        indexes = [models.Index(fields=['ziel_typ', 'ziel_id'])]

    # Kategorien, die als "kritisch" gelten (Löschungen, Geldbewegungen, Sicherheit).
    KRITISCH = {'geloescht', 'finanzen', 'sicherheit'}

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


class Pendenz(OrganisationAusKette):
    # Beide Wege optional, und das ist fachlich richtig: Eine allgemeine
    # Aufgabe der Verwaltung haengt weder an einer Liegenschaft noch an
    # einem Vertrag. Deshalb Tupel plus Rueckfall statt CheckConstraint —
    # eine Bedingung wuerde genau diese legitimen Pendenzen abweisen.
    ORGANISATION_PFAD = ('vertrag', 'liegenschaft')
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

    # Einschreiben-Zustellung (v.a. 257d-Fristen): Sendungsnummer + Versand-/
    # Zugangsdatum. Strikte Empfangstheorie — die Frist läuft ab ZUGANG (Eintritt
    # in den Machtbereich = Zustellung/Abholeinladung), den der Nutzer aus
    # Track&Trace bestätigt. Bis dahin ist faellig_am provisorisch.
    sendungsnummer = models.CharField("Sendungsnummer (Einschreiben)", max_length=40, blank=True, default='')
    versand_am = models.DateField("Versendet am", null=True, blank=True)
    zugang_am = models.DateField("Zugang bestätigt am", null=True, blank=True)
    frist_tage = models.PositiveSmallIntegerField("Fristdauer ab Zugang (Tage)", null=True, blank=True)

    erstellt_am = models.DateTimeField(auto_now_add=True)
    erstellt_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Pendenz"
        verbose_name_plural = "Pendenzen"
        ordering = ['erledigt', 'faellig_am', '-erstellt_am']

    def __str__(self):
        return f"{self.titel} ({'erledigt' if self.erledigt else 'offen'})"
