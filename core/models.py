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


class Postfach(models.Model):
    """Das E-Mail-Postfach EINER Verwaltung — Antworten oder Rechnungen.

    WARUM JE VERWALTUNG EIN EIGENES (Entscheid 18.08.2026)

    Die Alternative wäre ein gemeinsamer Eingang mit Zuordnungsregeln gewesen:
    an der Empfängeradresse, an einem Präfix im Betreff. Eine solche Zuordnung
    **rät** — und rät sie falsch, landet die Rechnung einer fremden Verwaltung
    im eigenen Bestand. Auffallen würde es niemandem, weil eine
    Kreditorenrechnung nun einmal von aussen kommt.

    Getrennte Postfächer machen die Zuordnung zur **Voraussetzung** statt zum
    Ergebnis: Was in Postfach B liegt, gehört B, ohne Interpretation. Jede
    Verwaltung hinterlegt ihr eigenes — Gmail, Microsoft 365, klassischer
    Hoster, wie sie es ohnehin betreibt.

    WARUM EIN EIGENES MODELL STATT FELDER AN DER ORGANISATION

    Es sind zwei Zwecke mit demselben Feldsatz. An der `Organisation` stünden
    sie doppelt (`antwort_host`, `rechnung_host`, …) — und ein dritter Zweck
    verdreifachte sie.

    WARUM DIREKTER FREMDSCHLÜSSEL UND KEINE `OrganisationAusKette`

    Jene Basisklasse ist für Modelle mit einer geschlossenen Pflicht-**Kette**
    gedacht, wo die Organisation aus `liegenschaft.organisation` abgeleitet und
    NICHT eingegeben wird. Ein Postfach hängt an nichts dergleichen; es gehört
    unmittelbar der Verwaltung. Bauform daher wie `portfolio.Liegenschaft`:
    direkter FK plus die beiden Manager, ausdrücklich gesetzt.

    ALLE GEHEIMNISSE VERSCHLÜSSELT, nicht nur das Passwort. Ein Refresh-Token
    ist genauso wertvoll — damit liest jemand das Postfach, bis es widerrufen
    wird.
    """
    ZWECK_ANTWORTEN = 'antworten'
    ZWECK_RECHNUNGEN = 'rechnungen'
    ZWECKE = [
        (ZWECK_ANTWORTEN, 'Antworten auf Ticket-Mails'),
        (ZWECK_RECHNUNGEN, 'Eingehende Kreditorenrechnungen'),
    ]

    VERFAHREN_PASSWORT = 'passwort'
    VERFAHREN_OAUTH2 = 'oauth2'
    VERFAHREN = [
        (VERFAHREN_PASSWORT, 'Benutzername und Passwort'),
        (VERFAHREN_OAUTH2, 'OAuth2 (Microsoft 365)'),
    ]

    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE,
                                     related_name='postfaecher',
                                     verbose_name='Organisation')
    zweck = models.CharField('Zweck', max_length=20, choices=ZWECKE)
    verfahren = models.CharField('Verfahren', max_length=20, choices=VERFAHREN,
                                 default=VERFAHREN_PASSWORT)
    aktiv = models.BooleanField('Eingang aktiv', default=True)

    server = models.CharField('IMAP-Server', max_length=200, blank=True, default='')
    port = models.PositiveIntegerField('Port', default=993)
    benutzer = models.CharField('Benutzername / Adresse', max_length=200,
                                blank=True, default='')
    ordner = models.CharField('Ordner', max_length=100, default='INBOX')

    #: Verschlüsselt (Fernet). Nie direkt lesen — `passwort` benutzen.
    passwort_geheim = models.TextField('Passwort (verschlüsselt)', blank=True, default='')

    # --- OAuth2 -------------------------------------------------------
    mandant_id = models.CharField('Verzeichnis-ID (Tenant)', max_length=100,
                                  blank=True, default='')
    anwendung_id = models.CharField('Anwendungs-ID (Client)', max_length=100,
                                    blank=True, default='')
    #: Ebenfalls verschlüsselt — siehe Klassenkommentar.
    refresh_token_geheim = models.TextField('Refresh-Token (verschlüsselt)',
                                            blank=True, default='')

    # --- Status -------------------------------------------------------
    letzter_abruf = models.DateTimeField('Letzter erfolgreicher Abruf',
                                         null=True, blank=True)
    letzter_test = models.DateTimeField('Letzter Verbindungstest',
                                        null=True, blank=True)
    letzter_fehler_am = models.DateTimeField('Letzter Fehler', null=True, blank=True)
    letzter_fehler = models.TextField('Fehlertext', blank=True, default='')

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Postfach'
        verbose_name_plural = 'Postfächer'
        # Je Verwaltung EIN Postfach pro Zweck. Zwei würden bedeuten, dass
        # niemand sagen kann, aus welchem geholt wird.
        constraints = [
            models.UniqueConstraint(fields=['organisation', 'zweck'],
                                    name='ein_postfach_je_zweck_und_organisation'),
        ]

    def __str__(self):
        return f'{self.organisation} — {self.get_zweck_display()}'

    # -- Geheimnisse ---------------------------------------------------
    @property
    def passwort(self) -> str:
        from core.services.geheimnis import entschluesseln
        return entschluesseln(self.passwort_geheim)

    @passwort.setter
    def passwort(self, klartext):
        from core.services.geheimnis import verschluesseln
        self.passwort_geheim = verschluesseln(klartext)

    @property
    def refresh_token(self) -> str:
        from core.services.geheimnis import entschluesseln
        return entschluesseln(self.refresh_token_geheim)

    @refresh_token.setter
    def refresh_token(self, klartext):
        from core.services.geheimnis import verschluesseln
        self.refresh_token_geheim = verschluesseln(klartext)

    # -- Zustand -------------------------------------------------------
    @property
    def ist_einsatzbereit(self) -> bool:
        """Reicht das Hinterlegte, um überhaupt einen Abruf zu versuchen?

        Bewusst streng: Ein halb ausgefülltes Postfach wird übersprungen, statt
        einen Verbindungsversuch zu starten, der ohnehin scheitert und dabei
        nur das Fehlerprotokoll füllt.
        """
        if not self.aktiv or not self.benutzer:
            return False
        if self.verfahren == self.VERFAHREN_OAUTH2:
            return bool(self.mandant_id and self.anwendung_id and self.refresh_token_geheim)
        return bool(self.server and self.passwort_geheim)

    def fehler_vermerken(self, text: str):
        from django.utils import timezone

        self.letzter_fehler = (text or '')[:2000]
        self.letzter_fehler_am = timezone.now()
        self.save(update_fields=['letzter_fehler', 'letzter_fehler_am'])

    def erfolg_vermerken(self):
        from django.utils import timezone

        self.letzter_abruf = timezone.now()
        self.letzter_fehler = ''
        self.letzter_fehler_am = None
        self.save(update_fields=['letzter_abruf', 'letzter_fehler', 'letzter_fehler_am'])


class ZweiterFaktor(models.Model):
    """Der zweite Anmeldefaktor eines Kontos (TOTP).

    WARUM OHNE ORGANISATIONSBEZUG

    Wie `SicherheitsEreignis` trägt dieses Modell bewusst **keine**
    `organisation`. Der zweite Faktor hängt am **Konto**, nicht an der
    Verwaltung: Ein Mensch kann in mehreren Verwaltungen Mitglied sein — sein
    Telefon ist trotzdem dasselbe. Ein Faktor je Mitgliedschaft wäre nicht
    sicherer, nur lästiger, und beim Wechsel der aktiven Verwaltung müsste
    man sich erneut ausweisen, ohne dass dabei irgendetwas geprüft würde.

    Der Datensatz entsteht ausserdem **vor** dem Anmelden, also zu einem
    Zeitpunkt, an dem noch gar kein Mandantenkontext gesetzt ist. Er steht
    deshalb in `test_isolation.OHNE_MANDANTENFILTER`.

    DER WIEDERGABESCHUTZ SITZT HIER, nicht im Rechenmodul: Ein TOTP-Code gilt
    bis zu 90 Sekunden (eigenes Fenster ± eines). Ohne Gedächtnis liesse sich
    ein abgefangener Code in dieser Zeit ein zweites Mal einlösen — etwa von
    jemandem, der über die Schulter geschaut hat. `letztes_fenster` merkt das
    zuletzt verbrauchte Fenster; alles, was nicht echt danach liegt, wird
    abgewiesen.
    """
    benutzer = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name='zweiter_faktor',
                                    verbose_name="Benutzer")
    geheimnis = models.CharField("Geheimnis (Base32)", max_length=64)
    bestaetigt_am = models.DateTimeField("Bestätigt am", null=True, blank=True)
    letztes_fenster = models.BigIntegerField("Zuletzt verbrauchtes Fenster", default=0)
    erstellt_am = models.DateTimeField("Erstellt am", auto_now_add=True)
    letzte_verwendung = models.DateTimeField("Zuletzt verwendet", null=True, blank=True)

    class Meta:
        verbose_name = "Zweiter Faktor"
        verbose_name_plural = "Zweite Faktoren"

    def __str__(self):
        stand = "aktiv" if self.ist_aktiv else "eingerichtet, nicht bestätigt"
        return f"{self.benutzer} — {stand}"

    @property
    def ist_aktiv(self) -> bool:
        """Erst ein bestätigter Faktor zählt.

        Zwischen «QR-Code angezeigt» und «erster Code richtig eingegeben» darf
        der Faktor NICHT gelten — sonst sperrt sich aus, wer die Einrichtung
        abbricht oder den Code falsch abscannt.
        """
        return self.bestaetigt_am is not None

    def pruefen(self, eingabe: str, zeitpunkt: float | None = None) -> bool:
        """Code prüfen und, wenn er stimmt, sein Fenster verbrauchen."""
        from django.utils import timezone

        from core.services import totp

        fenster = totp.passendes_fenster(self.geheimnis, eingabe, zeitpunkt)
        if fenster is None or fenster <= self.letztes_fenster:
            return False
        self.letztes_fenster = fenster
        self.letzte_verwendung = timezone.now()
        self.save(update_fields=['letztes_fenster', 'letzte_verwendung'])
        return True


class Wiederherstellungscode(models.Model):
    """Einmalcodes für den Fall «Telefon weg».

    OHNE DIESE CODES IST 2FA EIN RISIKO STATT EINES SCHUTZES. swissImmo hat
    keine Hotline, die sich von einem Anrufer überzeugen lässt. Verliert die
    Inhaberin ihr Telefon, käme ohne Wiederherstellungscodes niemand mehr an
    den Bestand ihrer Verwaltung — der Schutz wäre dann selbst der Schaden.

    Gespeichert wird nur der **Hash**, mit demselben Verfahren wie bei
    Passwörtern. Ein Datenbankauszug gibt die Codes damit nicht preis, und wer
    die Liste verloren hat, kann sie nicht nachlesen, sondern nur neu erzeugen
    — das ist beabsichtigt und wird im Formular gesagt.
    """
    benutzer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='wiederherstellungscodes',
                                 verbose_name="Benutzer")
    code_hash = models.CharField("Code (Hash)", max_length=255)
    erstellt_am = models.DateTimeField("Erstellt am", auto_now_add=True)
    eingeloest_am = models.DateTimeField("Eingelöst am", null=True, blank=True)

    class Meta:
        verbose_name = "Wiederherstellungscode"
        verbose_name_plural = "Wiederherstellungscodes"
        ordering = ['erstellt_am']

    def __str__(self):
        return f"{self.benutzer} — {'eingelöst' if self.eingeloest_am else 'offen'}"


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
