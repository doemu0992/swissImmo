from core.utils import get_smart_upload_path, get_current_lik, get_current_ref_zins
from django.conf import settings
from django.db import models
from django.utils import timezone
from core.verschluesselt import VerschluesseltesCharField

from core.tenancy import AlleOrganisationenManager, TenantManager, TenantQuerySet
from core.organisation_kette import OrganisationAusKette, organisation_bestimmen
from django.utils.translation import gettext_lazy as _


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


class PlattformMail(models.Model):
    """Eine Mail des Plattform-Postfachs, die der Abruf (``fetch_plattform_eingang``) schon angefasst hat.

    PLATTFORMWEIT, OHNE ORGANISATION (steht in ``OHNE_MANDANTENFILTER``): Das Sammelpostfach enthaelt auch Mails,
    die KEINER Verwaltung gehoeren (Spam an erfundene Adressen). Fuer sie gibt es keine Organisation, aber der
    Abruf muss sich merken, dass er sie ignoriert hat. Gespeichert wird nur der Schluessel (Message-ID, ersatzweise
    ein Hash der Kopfzeilen), der Ausgang und ein Zaehler — KEIN Inhalt, KEIN Absender.

    Drei Aufgaben:
    * Poison-Schutz: ``versuche`` zaehlt Fehlschlaege; ab ``MAX_VERSUCHE`` gilt die Mail als erledigt
      (``ergebnis='aufgegeben'``), damit eine kaputte Mail den Abruf nicht ewig blockiert.
    * Aufraeumen: geloescht wird im Postfach NUR, was hier mit ``erledigt_am`` vermerkt ist.
    * Wiederaufnahme: blieb ``\\Seen`` nach dem Verarbeiten aus, erkennt der naechste Lauf die Mail hieran wieder.

    Die Idempotenz je Verwaltung (nie doppelt anlegen) bleibt bei ``tickets.EingegangeneMail``.
    """
    schluessel = models.CharField("Schluessel", max_length=255, unique=True, editable=False)
    versuche = models.PositiveSmallIntegerField("Fehlversuche", default=0, editable=False)
    ergebnis = models.CharField("Ausgang", max_length=30, blank=True, default='', editable=False)
    letzter_fehler = models.CharField("Letzter Fehler", max_length=300, blank=True, default='', editable=False)
    erstellt_am = models.DateTimeField("Erstmals gesehen", auto_now_add=True)
    erledigt_am = models.DateTimeField("Erledigt am", null=True, blank=True, db_index=True, editable=False)

    class Meta:
        verbose_name = "Plattform-Mail"
        verbose_name_plural = "Plattform-Mails"

    def __str__(self):
        return f"{self.schluessel[:40]} ({self.ergebnis or 'offen'})"


class PlattformEingangStatus(models.Model):
    """Wann das Plattform-Postfach zuletzt abgerufen wurde und mit welchem Fehler — genau eine Zeile.

    Plattformweit (kein Organisationsbezug, siehe ``OHNE_MANDANTENFILTER``). Die Seite «E-Mail-Eingang» zeigt
    sie dem Inhaber. ``letzter_fehler`` ist bewusst OHNE Servername und Benutzer formuliert, weil jede
    Verwaltung ihn sieht.
    """
    letzter_abruf = models.DateTimeField("Letzter Abruf", null=True, blank=True, editable=False)
    letzter_erfolg = models.DateTimeField("Letzter Abruf ohne Fehler", null=True, blank=True, editable=False)
    letzter_fehler = models.CharField("Letzter Fehler", max_length=300, blank=True, default='', editable=False)

    class Meta:
        verbose_name = "Status Plattform-Postfach"
        verbose_name_plural = "Status Plattform-Postfach"

    @classmethod
    def holen(cls):
        eintrag, _neu = cls.objects.get_or_create(pk=1)
        return eintrag

    def __str__(self):
        return f"Plattform-Postfach, Abruf {self.letzter_abruf or 'noch nie'}"


class AbrufStatus(models.Model):
    """Wann ein Abruf bei einem externen Dienst zuletzt gelang und woran er zuletzt scheiterte.

    WARUM ES DAS GIBT: Die Abrufe (LIK, Referenzzinssatz, ...) fangen jeden Fehler ab und fallen auf eine Tabelle
    im Code zurück. Das ist richtig, hat aber dazu geführt, dass ein ausgefallener Abruf Wochen unbemerkt blieb
    (Architekturnotizen R7). Jetzt hinterlässt jeder Versuch eine Spur, und die Betreiber-Startseite zeigt sie.

    Plattformweit, ohne Organisationsbezug (siehe `OHNE_MANDANTENFILTER`): Der Dienst fällt für die Installation
    aus, nicht für eine Verwaltung. Der Fehlertext enthält keine Zugangsdaten und keine Daten einer Verwaltung.
    """
    name = models.CharField("Abruf", max_length=60, unique=True)
    letzter_versuch = models.DateTimeField("Letzter Versuch", null=True, blank=True, editable=False)
    letzter_erfolg = models.DateTimeField("Letzter Erfolg", null=True, blank=True, editable=False)
    letzter_fehler = models.CharField("Letzter Fehler", max_length=300, blank=True, default='', editable=False)
    fehler_in_folge = models.PositiveIntegerField("Fehlversuche in Folge", default=0, editable=False)

    class Meta:
        verbose_name = "Abrufstatus"
        verbose_name_plural = "Abrufstatus"

    def __str__(self):
        return f"{self.name}: {self.fehler_in_folge} Fehlversuche in Folge"


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
        (ZWECK_ANTWORTEN, _('Antworten auf Ticket-Mails')),
        (ZWECK_RECHNUNGEN, _('Eingehende Kreditorenrechnungen')),
    ]

    VERFAHREN_PASSWORT = 'passwort'
    VERFAHREN_OAUTH2 = 'oauth2'
    VERFAHREN = [
        (VERFAHREN_PASSWORT, _('Benutzername und Passwort')),
        (VERFAHREN_OAUTH2, _('OAuth2 (Microsoft 365)')),
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

    @property
    def zugang_lesbar(self) -> bool:
        """Lassen sich die hinterlegten Zugangsdaten mit dem AKTUELLEN Schlüssel entschlüsseln?

        Billiger Test ohne Netz (kein IMAP): Fernet prüft beim Entschlüsseln die Signatur. ``False`` bei
        gewechseltem oder fehlendem ``IMAP_SCHLUESSEL`` (Fehlertext «lässt sich mit dem aktuellen … nicht
        lesen»). Ein Postfach ohne gespeichertes Geheimnis ist hier ``True`` — es gibt nichts zu lesen; ob es
        vollständig ist, sagt ``ist_einsatzbereit``. Ein unlesbares Postfach gilt für ``tickets.workflow.
        reply_to`` NICHT als aktiv: dann springt die Plattformadresse ein."""
        from core.services.geheimnis import GeheimtextKaputt, SchluesselFehlt
        try:
            self.passwort
            self.refresh_token
        except (SchluesselFehlt, GeheimtextKaputt):
            return False
        return True

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
    # Verschlüsselt abgelegt (Fernet, core/verschluesselt.py): Ein Datenbankauszug gibt sonst die Codegeneratoren aller
    # Konten preis. Nie filtern; Alt-Bestand im Klartext wird nach dem nächsten `migrate` automatisch verschlüsselt.
    geheimnis = VerschluesseltesCharField("Geheimnis (Base32)", klartext_max_laenge=64)
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


class AktivitaetsLogQuerySet(TenantQuerySet):
    """Das Audit-Log ist nur anhängbar: Sammel-Änderungen und -Löschungen sind gesperrt.

    Erlaubt bleibt das Leeren des Benutzerbezugs (Konto wird gelöscht, `SET_NULL`)
    und die benannte Ausnahme `finance.db_schutz.ausnahme(grund)` — etwa die
    DSG-Anonymisierung, die Namen aus Texten schwärzt.
    """

    def update(self, **kwargs):
        from finance.db_schutz import ausnahme_aktiv
        if not ausnahme_aktiv() and set(kwargs) - {'benutzer', 'benutzer_id'}:
            raise PermissionError('Das Audit-Log ist nur anhängbar: Einträge lassen sich nicht ändern.')
        return super().update(**kwargs)

    def bulk_update(self, *args, **kwargs):
        from finance.db_schutz import ausnahme_aktiv
        if not ausnahme_aktiv():
            raise PermissionError('Das Audit-Log ist nur anhängbar: Einträge lassen sich nicht ändern.')
        return super().bulk_update(*args, **kwargs)

    def delete(self):
        from finance.db_schutz import ausnahme_aktiv
        if not ausnahme_aktiv():
            raise PermissionError('Das Audit-Log ist nur anhängbar: Einträge lassen sich nicht löschen.')
        return super().delete()


class AktivitaetsLogManager(TenantManager.from_queryset(AktivitaetsLogQuerySet)):
    """`AktivitaetsLog.objects`: Mandantenfilter plus Append-only-Sperren."""


class AktivitaetsLogAlleManager(AlleOrganisationenManager.from_queryset(AktivitaetsLogQuerySet)):
    """`AktivitaetsLog.alle_organisationen`: mit denselben Sperren."""


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
    # PROTECT statt CASCADE: Eine Organisation mit Protokoll lässt sich nicht
    # mitsamt ihrem Audit-Trail löschen (Aufbewahrung, OR 958f).
    organisation = models.ForeignKey('crm.Organisation', on_delete=models.PROTECT,
                                     editable=False, related_name='%(app_label)s_%(class)s',
                                     verbose_name='Organisation')

    #: So oft wird ein Eintrag neu gesiegelt, wenn ein gleichzeitiger Eintrag derselben Verwaltung die Nummer vor ihm belegt hat.
    KETTE_VERSUCHE = 40

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            from finance.db_schutz import ausnahme_aktiv
            if not ausnahme_aktiv():
                raise PermissionError('Das Audit-Log ist nur anhängbar: Einträge lassen sich nicht ändern.')
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        if self._state.adding and self.kette_nr is None:
            return self._siegeln_und_speichern(*args, **kwargs)
        super().save(*args, **kwargs)

    def _siegeln_und_speichern(self, *args, **kwargs):
        """Hängt den Eintrag an die Hash-Kette seiner Verwaltung (`core/log_kette.py`).

        Die Nummer ist je Verwaltung eindeutig (Constraint). Schreiben zwei Anfragen gleichzeitig, gewinnt eine; die andere
        bekommt einen Integritätsfehler, liest den neuen Kopf und versucht es erneut — ohne Sperre, die eine längere
        Geschäfts-Transaktion aufhalten würde. Der Versuch läuft in einem Sicherungspunkt, damit eine umgebende
        Transaktion nicht als abgebrochen gilt."""
        import random
        import time

        from django.db import IntegrityError, transaction

        from core.log_kette import NULLHASH, kettenhash
        letzter_fehler = None
        for _versuch in range(self.KETTE_VERSUCHE):
            kopf = (type(self).alle_organisationen.filter(organisation_id=self.organisation_id, kette_nr__isnull=False)
                    .order_by('-kette_nr').values_list('kette_nr', 'kette_hash').first())
            self.kette_nr = kopf[0] + 1 if kopf else 1
            self.kette_hash = kettenhash(self, kopf[1] if kopf else NULLHASH)
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError as fehler:
                letzter_fehler = fehler
                self.pk = None
                self._state.adding = True
                # Kleiner zufälliger Abstand, damit gleichzeitige Schreiber sich nicht im Gleichschritt erneut treffen.
                time.sleep(random.uniform(0, 0.005 * (_versuch + 1)))
        raise letzter_fehler

    def delete(self, *args, **kwargs):
        from finance.db_schutz import ausnahme_aktiv
        if not ausnahme_aktiv():
            raise PermissionError('Das Audit-Log ist nur anhängbar: Einträge lassen sich nicht löschen.')
        return super().delete(*args, **kwargs)

    # `default` statt `auto_now_add`: Der Zeitpunkt steht beim Siegeln der Hash-Kette schon fest und geht in den Hash ein.
    zeitpunkt = models.DateTimeField("Zeitpunkt", default=timezone.now, editable=False)
    # Hash-Kette (core/log_kette.py): laufende Nummer je Verwaltung und Hash über Nummer, Zeitpunkt, Aktion, Ziel und den
    # Hash des Vorgängers. Leer nur bei Einträgen aus der Zeit vor der Kette und bei solchen, die am Modell vorbei entstanden.
    kette_nr = models.PositiveIntegerField("Nr. in der Kette", null=True, blank=True, editable=False)
    kette_hash = models.CharField("Hash in der Kette", max_length=64, blank=True, default='', editable=False)
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
        ('erstellt', _('Erstellt / erfasst')),
        ('bearbeitet', _('Bearbeitet / geändert')),
        ('geloescht', _('Gelöscht / storniert')),
        ('finanzen', _('Finanzen / Buchung')),
        ('versand', _('Versand / Kommunikation')),
        ('sicherheit', _('Sicherheit / Login')),
        ('sonstiges', _('Sonstiges')),
    ]
    kategorie = models.CharField("Kategorie", max_length=20, blank=True, default='', db_index=True)
    ip_adresse = models.GenericIPAddressField("IP-Adresse", null=True, blank=True)


    objects = AktivitaetsLogManager()
    alle_organisationen = AktivitaetsLogAlleManager()

    class Meta:
        base_manager_name = 'alle_organisationen'
        verbose_name = "Aktivitätslog"
        verbose_name_plural = "Aktivitätslog"
        ordering = ['-zeitpunkt']
        indexes = [models.Index(fields=['ziel_typ', 'ziel_id'])]
        constraints = [
            models.UniqueConstraint(fields=['organisation', 'kette_nr'], condition=models.Q(kette_nr__isnull=False),
                                    name='uniq_auditlog_kette_nr_je_organisation'),
        ]

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
        ('frist', _('Frist')),
        ('aufgabe', _('Aufgabe')),
        ('vertrag', _('Vertrag')),
        ('finanzen', _('Finanzen')),
        ('unterhalt', _('Unterhalt')),
        ('sonstiges', _('Sonstiges')),
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
    # Zugangsdatum. Empfangstheorie — die Frist läuft ab ZUGANG: bei Zustellung
    # oder Abholung der Tag, an dem der Mieter das Schreiben erhält; bei
    # Nichtabholung der letzte Tag der 7-tägigen Abholfrist (BGE 119 II 147
    # E. 2), NICHT die Abholeinladung. Den Zugang bestätigt der Nutzer aus
    # Track&Trace. Bis dahin ist faellig_am provisorisch (und nie zu kurz).
    #: Die Pendenz gehört zu einem Einschreiben (auch ohne Sendungsnummer: sie wird erst nach dem Versand erfasst).
    einschreiben = models.BooleanField("Einschreiben", default=False)
    sendungsnummer = models.CharField("Sendungsnummer (Einschreiben)", max_length=40, blank=True, default='')
    versand_am = models.DateField("Versendet am", null=True, blank=True)
    zugang_am = models.DateField("Zugang bestätigt am", null=True, blank=True)
    #: Der Zugang ist nicht belegt, sondern fingiert: Das Einschreiben wurde nicht abgeholt, `zugang_am` ist der
    #: letzte Tag der siebentägigen Abholfrist (BGE 119 II 147 E. 2). Bei tatsächlicher Abholung steht hier
    #: False und `zugang_am` ist der Tag der Abholung.
    zugang_fingiert = models.BooleanField("Zugang fingiert (nicht abgeholt)", default=False)
    frist_tage = models.PositiveSmallIntegerField("Fristdauer ab Zugang (Tage)", null=True, blank=True)

    erstellt_am = models.DateTimeField(auto_now_add=True)
    erstellt_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Pendenz"
        verbose_name_plural = "Pendenzen"
        ordering = ['erledigt', 'faellig_am', '-erstellt_am']

    def __str__(self):
        return f"{self.titel} ({'erledigt' if self.erledigt else 'offen'})"

    @property
    def frist_provisorisch(self):
        """Das Fristende ist noch nicht verlässlich: Einschreiben mit Nummer, Zugang unbestätigt. Ausgenommen ein Brief aus
        einer Vorlage mit FESTEM Fristdatum: Das Datum steht im Brief und ändert sich mit dem Zugang nicht."""
        if not self.sendungsnummer or self.zugang_am:
            return False
        return not ((self.quelle or '').startswith('brief:') and not self.frist_tage)


class Archiveintrag(models.Model):
    """Archiv statt hartes Löschen (Audit FUNK-03/FIN-16, Etappe 2).

    Ein archiviertes Objekt (Liegenschaft, Objekt, Person, Vertrag, Mandat,
    Dokument, Schadenmeldung, STWEG-Dokument) bleibt vollständig erhalten, erscheint
    aber nicht mehr in den Arbeitslisten. Der Eintrag nennt, wer es wann und warum
    archiviert hat und bis wann es aufzubewahren ist; vorher gibt es kein hartes
    Löschen (`core/services/archiv.py`, `loeschschutz.py`). «Wiederherstellen»
    löscht den Eintrag.

    Eine eigene Tabelle statt einer Spalte je Modell: acht Modelle, keine
    Migration über den Produktivbestand, und die Aufbewahrungsfrist steht an
    einer Stelle. Der Bezug ist `typ` (Modell-Label) + `objekt_id`.
    """
    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE, editable=False,
                                     related_name='%(app_label)s_%(class)s', verbose_name='Organisation')
    typ = models.CharField("Typ", max_length=60, db_index=True)
    objekt_id = models.PositiveIntegerField("Objekt-ID")
    bezeichnung = models.CharField("Bezeichnung", max_length=255, blank=True, default='')
    archiviert_am = models.DateField("Archiviert am")
    archiviert_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+', verbose_name="Archiviert von")
    grund = models.CharField("Grund", max_length=255, blank=True, default='')
    # Mandatsende: das Datum, an dem das Mandat endet (nur bei Eigentümern gesetzt).
    mandatsende = models.DateField("Mandatsende", null=True, blank=True)
    # Status vor dem Archivieren (Liegenschaft, Vertrag): «Wiederherstellen» setzt ihn zurück.
    vorher_status = models.CharField("Status vorher", max_length=30, blank=True, default='')
    aufbewahren_bis = models.DateField("Aufbewahren bis")

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Archiveintrag"
        verbose_name_plural = "Archiv"
        ordering = ['-archiviert_am', '-id']
        constraints = [models.UniqueConstraint(fields=['organisation', 'typ', 'objekt_id'],
                                               name='uniq_archiv_je_objekt')]
        indexes = [models.Index(fields=['organisation', 'typ'])]

    def __str__(self):
        return f"{self.typ} #{self.objekt_id} ({self.bezeichnung})"


class DatenImportLauf(models.Model):
    """Ein Datenimport (Wechselkunden, FUNK-09): Vorschau, Ausführung und Protokoll.

    Der Ablauf hat zwei Schritte mit DERSELBEN Datei: Die Vorschau (Trockenlauf) legt
    die hochgeladenen Dateien hier ab, prüft sie vollständig und schreibt nichts in den
    Bestand. «Jetzt importieren» liest genau diese abgelegten Bytes, nicht eine zweite
    Hochladung, und führt alles in EINER Transaktion aus. Danach werden die Dateien
    gelöscht (`daten` leer); das Protokoll mit Zählern und Meldungen bleibt.
    """
    STATUS_VORSCHAU = 'vorschau'          # Trockenlauf ohne Fehler, kann ausgeführt werden
    STATUS_FEHLERHAFT = 'fehlerhaft'      # Trockenlauf mit Fehlern, nichts ausführbar
    STATUS_IMPORTIERT = 'importiert'
    STATUS_ABGEBROCHEN = 'abgebrochen'    # Ausführung hat Fehler gefunden, nichts geschrieben
    STATUS_VERWORFEN = 'verworfen'
    STATUS_CHOICES = [
        (STATUS_VORSCHAU, _('Vorschau (bereit)')),
        (STATUS_FEHLERHAFT, _('Vorschau mit Fehlern')),
        (STATUS_IMPORTIERT, _('Importiert')),
        (STATUS_ABGEBROCHEN, _('Abgebrochen (nichts importiert)')),
        (STATUS_VERWORFEN, _('Verworfen')),
    ]

    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE, editable=False,
                                     related_name='%(app_label)s_%(class)s', verbose_name='Organisation')
    benutzer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='+', verbose_name="Durchgeführt von")
    erstellt_am = models.DateTimeField("Erstellt am", auto_now_add=True)
    ausgefuehrt_am = models.DateTimeField("Importiert am", null=True, blank=True)
    status = models.CharField("Status", max_length=12, choices=STATUS_CHOICES, default=STATUS_VORSCHAU)
    #: Die hochgeladenen Dateien als ZIP (Name -> Inhalt) bis zur Ausführung; danach leer.
    daten = models.BinaryField("Hochgeladene Dateien", blank=True, default=b'', editable=False)
    #: Zähler je Art: {'liegenschaften': {'zeilen': 12, 'neu': 10, 'vorhanden': 2, 'fehler': 0}, …}
    zaehler = models.JSONField("Zähler je Art", default=dict, blank=True)
    #: Meldungen: [{'art', 'zeile', 'feld', 'stufe' ('fehler'|'hinweis'), 'text'}, …], höchstens 1000.
    meldungen = models.JSONField("Meldungen", default=list, blank=True)
    anzahl_fehler = models.PositiveIntegerField("Fehler", default=0)
    anzahl_hinweise = models.PositiveIntegerField("Hinweise", default=0)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Datenimport"
        verbose_name_plural = "Datenimporte"
        ordering = ['-erstellt_am', '-id']

    def __str__(self):
        return f"Datenimport {self.pk} ({self.status})"


class DatenImportReferenz(models.Model):
    """Der Schlüssel der Quelldatei zum angelegten Datensatz.

    Die Dateien nennen ihre Verknüpfungen mit eigenen Schlüsseln (Liegenschaft «L1»,
    Objekt «L1-3»). Diese Tabelle hält fest, welcher Datensatz hier daraus wurde. Damit
    lässt sich ein Import in Etappen machen (Verträge einen Tag nach den Objekten), und
    eine zweite Hochladung derselben Zeile legt nichts doppelt an.
    """
    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE, editable=False,
                                     related_name='%(app_label)s_%(class)s', verbose_name='Organisation')
    art = models.CharField("Art", max_length=20)
    schluessel = models.CharField("Schlüssel der Quelldatei", max_length=120)
    objekt_id = models.PositiveBigIntegerField("Datensatz-ID")
    lauf = models.ForeignKey(DatenImportLauf, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='referenzen')

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Import-Referenz"
        verbose_name_plural = "Import-Referenzen"
        constraints = [models.UniqueConstraint(fields=['organisation', 'art', 'schluessel'],
                                               name='uniq_importreferenz_je_organisation')]

    def __str__(self):
        return f"{self.art}:{self.schluessel} -> {self.objekt_id}"


class DatenExportEinstellung(models.Model):
    """Wie das Buchungsjournal für ein Buchhaltungsprogramm aussieht (FUNK-13).

    Spaltenüberschriften, Zahlen- und Datumsformat und die Zuordnung des eigenen Kontenplans
    zu dem des Zielsystems stehen NICHT im Code: Welche Überschriften Banana oder Abacus
    erwarten und wie ein Treuhänder seine Konten nummeriert, weiss die Buchhaltung der
    Verwaltung, nicht diese Anwendung. Die Vorgaben sind die allgemeinen Namen aus dem
    Auftrag (Buchungsdatum, Belegnummer, Soll, Haben, Betrag, Text, MWST-Code).
    """
    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE, editable=False,
                                     related_name='%(app_label)s_%(class)s', verbose_name='Organisation')
    #: {'datum': 'Buchungsdatum', 'beleg': 'Belegnummer', 'soll': 'Soll', 'haben': 'Haben',
    #:  'betrag': 'Betrag', 'text': 'Text', 'mwst': 'MWST-Code'}
    spalten = models.JSONField("Spaltenüberschriften", default=dict, blank=True)
    #: {'1020': {'konto': '1000', 'mwst': ''}} — eigene Kontonummer -> Konto im Zielsystem + MWST-Code
    konten = models.JSONField("Kontenzuordnung", default=dict, blank=True)
    trenner = models.CharField("Trennzeichen", max_length=1, default=';')
    datumsformat = models.CharField("Datumsformat", max_length=3, default='ch',
                                    choices=[('ch', 'TT.MM.JJJJ'), ('iso', 'JJJJ-MM-TT')])
    dezimal = models.CharField("Dezimalzeichen", max_length=1, default='.')
    aktualisiert_am = models.DateTimeField("Aktualisiert am", auto_now=True)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    def save(self, *args, **kwargs):
        if self.organisation_id is None:
            self.organisation_id = organisation_bestimmen().pk
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Export-Einstellung"
        verbose_name_plural = "Export-Einstellungen"
        constraints = [models.UniqueConstraint(fields=['organisation'],
                                               name='uniq_exporteinstellung_je_organisation')]

    def __str__(self):
        return f"Export-Einstellung {self.organisation_id}"


class ApiToken(models.Model):
    """Zugangsschlüssel für die lesende Finanz-API (`/api/v1/`), eine Verwaltung je Schlüssel.

    Gespeichert wird nur der SHA-256-Hash; der Klartext erscheint genau einmal beim Anlegen
    (`manage.py api_token_erstellen`). Der Schlüssel ist 256 Bit zufällig, ein schneller Hash reicht deshalb. Er ist reine
    Leseberechtigung auf Konten, Journal und offene Debitoren dieser einen Verwaltung und wird mit dem Konto der
    Verwaltung nicht verknüpft: Wer ihn hat, ist kein Benutzer."""
    PRAEFIX = 'imm_'

    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE, editable=False,
                                     related_name='api_token', verbose_name='Organisation')
    name = models.CharField('Bezeichnung', max_length=100, help_text='Wofür der Schlüssel dient, z. B. «Treuhand Muster AG».')
    schluessel_hash = models.CharField(max_length=64, unique=True, editable=False)
    anfang = models.CharField('Anfang', max_length=12, editable=False, help_text='Erste Zeichen, damit man ihn wiedererkennt.')
    erstellt_am = models.DateTimeField(default=timezone.now, editable=False)
    zuletzt_benutzt = models.DateTimeField(null=True, blank=True, editable=False)
    widerrufen_am = models.DateTimeField(null=True, blank=True, editable=False)

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'API-Schlüssel'
        verbose_name_plural = 'API-Schlüssel'
        ordering = ['-erstellt_am']

    def __str__(self):
        return f'{self.name} ({self.anfang}…)'

    @property
    def aktiv(self):
        return self.widerrufen_am is None


class Aenderungsanfrage(models.Model):
    """Eine Anfrage aus dem Mieter- oder Eigentümerportal, die die Verwaltung bestätigen oder ablehnen muss.

    Alles, was das Portal an Stammdaten verändern will, geht über diese Tabelle: Das Portal schreibt nie selbst in die
    Stammdaten. Erst die Bestätigung durch eine Person der Verwaltung führt die Änderung aus (`core/services/anfragen.py`)
    und steht im Logbuch. `daten` hält, was geändert werden soll (je Art andere Schlüssel), `zusammenfassung` den Text,
    den die Verwaltung liest."""
    ART_KONTAKT = 'kontakt'                  # Mieter: Mobile, Telefon, E-Mail
    ART_MITTEILUNG = 'mitteilung'            # Freitext (Adresse, Namensänderung, weitere Anliegen): zur Kenntnis
    ART_MIETBESTAETIGUNG = 'mietbestaetigung'  # Mieter: Bestätigung des Mietverhältnisses als PDF
    ART_ZAHLUNGSPLAN = 'zahlungsplan'        # Mieter: Wunsch nach Ratenzahlung
    ART_EIG_KONTAKT = 'eig_kontakt'          # Eigentümer: Telefon, E-Mail
    ART_EIG_BANK = 'eig_bank'                # Eigentümer: Bankverbindung für Auszahlungen
    ART_EIG_ANFRAGE = 'eig_anfrage'          # Eigentümer: Freitext an die Verwaltung
    ART_ZAEHLERSTAND = 'zaehlerstand'        # Mieter: abgelesener Zählerstand (daten: zaehler, datum, wert)
    ARTEN = [(ART_KONTAKT, _('Kontaktdaten ändern')), (ART_MITTEILUNG, _('Mitteilung')),
             (ART_MIETBESTAETIGUNG, _('Mietbestätigung')), (ART_ZAHLUNGSPLAN, _('Zahlungsplan')),
             (ART_EIG_KONTAKT, _('Kontaktdaten ändern')), (ART_EIG_BANK, _('Bankverbindung ändern')),
             (ART_EIG_ANFRAGE, _('Anfrage')), (ART_ZAEHLERSTAND, _('Zählerstand'))]
    #: Arten, die Geld umleiten oder Personendaten Dritter berühren: nur Inhaber und Verwalter bestätigen sie.
    SENSIBEL = (ART_EIG_BANK,)

    STATUS_OFFEN, STATUS_BESTAETIGT, STATUS_ABGELEHNT = 'offen', 'bestaetigt', 'abgelehnt'
    STATUS = [(STATUS_OFFEN, _('Offen')), (STATUS_BESTAETIGT, _('Bestätigt')), (STATUS_ABGELEHNT, _('Abgelehnt'))]

    organisation = models.ForeignKey('crm.Organisation', on_delete=models.CASCADE, editable=False,
                                     related_name='aenderungsanfragen', verbose_name='Organisation')
    mieter = models.ForeignKey('crm.Mieter', on_delete=models.CASCADE, null=True, blank=True, related_name='anfragen')
    eigentuemer = models.ForeignKey('crm.Eigentuemer', on_delete=models.CASCADE, null=True, blank=True,
                                    related_name='anfragen')
    art = models.CharField('Art', max_length=20, choices=ARTEN)
    daten = models.JSONField('Daten', default=dict, blank=True)
    zusammenfassung = models.TextField('Zusammenfassung')
    status = models.CharField('Status', max_length=12, choices=STATUS, default=STATUS_OFFEN, db_index=True)
    erstellt_am = models.DateTimeField(default=timezone.now, editable=False)
    entschieden_am = models.DateTimeField(null=True, blank=True)
    entschieden_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+')
    antwort = models.TextField('Antwort der Verwaltung', blank=True, default='',
                               help_text='Bei einer Ablehnung der Grund; die Antragsteller lesen ihn im Portal.')

    objects = TenantManager()
    alle_organisationen = AlleOrganisationenManager()

    class Meta:
        verbose_name = 'Änderungsanfrage'
        verbose_name_plural = 'Änderungsanfragen'
        ordering = ['-erstellt_am', '-pk']
        constraints = [models.CheckConstraint(
            condition=models.Q(mieter__isnull=False) | models.Q(eigentuemer__isnull=False),
            name='core_aenderungsanfrage_hat_absender')]

    def __str__(self):
        return f'{self.get_art_display()} ({self.get_status_display()})'

    @property
    def absender(self):
        return self.mieter or self.eigentuemer

    @property
    def offen(self):
        return self.status == self.STATUS_OFFEN
