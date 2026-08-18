# core/views/ticket_public.py
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag
from tickets.models import SchadenMeldung
from tickets.services import process_public_ticket_form, generate_qr_poster
from crm.models import Mieter

# ==========================================
# 1. LANDING PAGE (STARTSEITE)
# ==========================================
def index_view(request):
    return render(request, 'core/index.html')


# ==========================================
# 2. NEUES ALLGEMEINES SCHADENSFORMULAR
# ==========================================
def public_schaden_melden_view(request):
    if request.method == 'POST':
        # 1. Daten aus dem POST-Request holen
        kategorie = request.POST.get('kategorie', 'unbekannt')
        raum = request.POST.get('raum', '')
        objekt = request.POST.get('objekt', '')
        beschreibung = request.POST.get('beschreibung', '')

        # Neue Strukturierte Kontaktdaten
        vorname = request.POST.get('vorname', '').strip()
        nachname = request.POST.get('nachname', '').strip()
        email = request.POST.get('email', '').strip()
        telefon = request.POST.get('telefon', '').strip()
        erreichbarkeit = request.POST.get('erreichbarkeit', 'telefon')

        # Liegenschafts-Infos aus Dropdown/Auto-Suggest
        liegenschaft_id = request.POST.get('liegenschaft_id', '')
        adresse_text = request.POST.get('adresse', '').strip()
        foto = request.FILES.get('foto')
        # Öffentlicher (anonymer) Upload → Bild-Inhalt streng validieren.
        if foto is not None:
            from core.utils.uploads import validiere_bild
            ok, _fehler = validiere_bild(foto)
            if not ok:
                foto = None

        titel_text = f"Meldung ({kategorie.capitalize()})"
        if raum and objekt:
            titel_text = f"[{raum.capitalize()}] Defekt an {objekt.capitalize()}"

        # 3. CRM ABGLEICH & ADRESS-ZUORDNUNG
        #
        # `alle_organisationen` an genau diesen drei Zeilen: Das Formular ist
        # oeffentlich, es gibt keine Anmeldung und damit keinen Mandanten-
        # kontext. Ueber `objects` warf jede der drei seit Etappe 6.2, und das
        # Formular nahm gar keine Meldung mehr an (Audit 18.08.2026). Die
        # Zuordnung IST hier die Aufgabe: Aus E-Mail bzw. gewaehlter
        # Liegenschaft ergibt sich, wem die Meldung gehoert — und ab dem Fund
        # laeuft alles Weitere in deren Kontext.
        gefundener_mieter = Mieter.alle_organisationen.filter(email__iexact=email).first()
        zugewiesene_liegenschaft = None
        zugewiesene_einheit = None

        # A) Wurde sauber via Dropdown ausgewählt (Sicherstellen, dass es eine Zahl ist)
        if liegenschaft_id and liegenschaft_id.isdigit():
            zugewiesene_liegenschaft = Liegenschaft.alle_organisationen.filter(
                pk=int(liegenschaft_id)).first()

        # B) Auto-Abgleich via E-Mail
        if gefundener_mieter and not zugewiesene_liegenschaft:
            vertrag = Mietvertrag.alle_organisationen.filter(
                mieter=gefundener_mieter, aktiv=True).first()
            if vertrag:
                zugewiesene_einheit = vertrag.einheit
                zugewiesene_liegenschaft = zugewiesene_einheit.liegenschaft

        # 4. KEIN RUECKFALL AUF "IRGENDEINE" LIEGENSCHAFT.
        #
        # Hier stand `Liegenschaft.objects.first()`: Liess sich die Adresse
        # eines anonymen Melders nicht zuordnen, wurde die Meldung der ERSTEN
        # Liegenschaft der Installation angehaengt — mit Name, E-Mail, Telefon,
        # Adressfreitext und Foto. Bei zwei Verwaltungen landet die Meldung
        # eines Mieters von B damit in der Ticketliste von A (Audit 18.08.2026).
        #
        # Eine Meldung ohne zuordenbare Liegenschaft wird deshalb NICHT
        # angelegt. Der Aufrufer erfaehrt es ueber den Rueckgabewert und kann
        # die Adresse erneut erfragen; erfundene Zuordnungen sind schlechter
        # als eine ehrliche Rueckfrage.
        if not zugewiesene_liegenschaft:
            return render(request, 'core/schaden_melden.html', {
                'fehler': 'Wir konnten die Adresse keiner Liegenschaft zuordnen. '
                          'Bitte wählen Sie Ihre Liegenschaft aus der Liste oder '
                          'melden Sie sich direkt bei Ihrer Verwaltung.',
                'liegenschaften_json': '[]'})

        # 5. Ticket erstellen (Mit den neuen getrennten Namensfeldern)
        from core.tenancy import kontext_des_objekts
        with kontext_des_objekts(zugewiesene_liegenschaft):
            SchadenMeldung.objects.create(
                liegenschaft=zugewiesene_liegenschaft,
                betroffene_einheit=zugewiesene_einheit,
                gemeldet_von=gefundener_mieter,
                melder_vorname=vorname,   # 🔥 NEU: Sicher gespeichert
                melder_nachname=nachname, # 🔥 NEU: Sicher gespeichert
                kategorie=kategorie,
                raum=raum,
                objekt=objekt,
                titel=titel_text,
                beschreibung=beschreibung, # <-- HIER IST DIE BESCHREIBUNG NUN 100% SAUBER
                email_melder=email,
                tel_melder=telefon,
                foto=foto,
                status='neu',
                prioritaet='mittel',
                zutritt='telefon' if erreichbarkeit in ['telefon', 'immer'] else 'passpartout'
            )

        # WICHTIG: Auch beim Success-Return ein leeres JSON mitgeben, damit Alpine.js nicht abstürzt!
        return render(request, 'core/schaden_melden.html', {'success': True, 'liegenschaften_json': '[]'})

    # GET-REQUEST: Das öffentliche (anonyme) Formular exponiert NICHT das gesamte
    # Portfolio (Adress-Enumeration / DSG) — der Melder trägt seine Adresse als
    # Freitext ein (Feld `adresse`, serverseitig via E-Mail/Fallback zugeordnet).
    # Der gebäudespezifische Einstieg ist der QR-Aushang /report/<liegenschaft_id>/.
    context = {
        'success': False,
        'liegenschaften_json': '[]',
    }
    return render(request, 'core/schaden_melden.html', context)


# ==========================================
# 3. QR-CODE FORMULAR (SPEZIFISCH PRO LIEGENSCHAFT)
# ==========================================
def public_ticket_view(request, liegenschaft_id):
    """QR-Aushang im Treppenhaus — ohne Login erreichbar.

    `alle_organisationen` plus Kontext: Es gibt keine Anmeldung, aus der die
    Middleware eine Verwaltung ableiten koennte. Ueber `Liegenschaft.objects`
    warf diese Zeile seit Etappe 6.2, und der Aushang antwortete
    installationsweit mit einem Serverfehler (Audit 18.08.2026). Wessen
    Liegenschaft gemeint ist, sagt die Liegenschaft selbst — und ab da laeuft
    alles Weitere in IHREM Kontext, damit das Ticket, die Einheitenliste und
    die Foto-Ablage nicht kontextlos weitermachen.
    """
    from core.tenancy import kontext_des_objekts

    liegenschaft = get_object_or_404(Liegenschaft.alle_organisationen, pk=liegenschaft_id)
    with kontext_des_objekts(liegenschaft):
        return _qr_formular(request, liegenschaft)


def _qr_formular(request, liegenschaft):
    einheiten = Einheit.objects.filter(liegenschaft=liegenschaft).order_by('etage', 'bezeichnung')
    # KEINE Mieter-Namen / "Leerstand" ausgeben — diese Seite ist ohne Login über
    # ?liegenschaft_id erreichbar (QR-Aushang). Sonst könnte jeder durch ID-Enumeration
    # den Mieterbestand (Nachnamen) + leerstehende Wohnungen des ganzen Portfolios
    # abgreifen (DSG/Datenschutz). Zur Auswahl genügt die Objektbezeichnung/Etage.

    if request.method == 'POST':
        process_public_ticket_form(liegenschaft, request.POST, request.FILES)
        return render(request, 'core/public_ticket_form.html', {'success': True, 'liegenschaft': liegenschaft})

    return render(request, 'core/public_ticket_form.html', {'liegenschaft': liegenschaft, 'einheiten': einheiten})

# ==========================================
# 4. AUSHANG GENERIEREN (ADMIN)
# ==========================================
@staff_member_required
def generate_hallway_poster(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)
    domain = request.get_host()
    buffer = generate_qr_poster(liegenschaft, domain)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Aushang_{liegenschaft.strasse}.pdf"'
    return response