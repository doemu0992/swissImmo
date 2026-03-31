from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

# Deine Modelle
from .models import Mietvertrag, MietzinsAnpassung, Leerstand, Dokument
from crm.models import Verwaltung # Für Referenzzinssatz-Logik
from core.mietrecht_logic import berechne_mietpotenzial # Falls vorhanden

# ==========================================
# 0. SICHERHEITS-CHECK (Bereinigung für PythonAnywhere)
# ==========================================
models_to_fix = [Mietvertrag, MietzinsAnpassung, Leerstand, Dokument]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# ==========================================
# 1. INLINES
# ==========================================

class DokumentVertragInline(TabularInline):
    model = Dokument
    extra = 0
    fk_name = "vertrag"
    fields = ('bezeichnung', 'kategorie', 'datei', 'vorschau_btn')
    readonly_fields = ('vorschau_btn',)
    tab = True

    def vorschau_btn(self, obj):
        if obj.datei:
            return format_html('<a href="{}" target="_blank" class="text-emerald-600 font-bold">📄 PDF</a>', obj.datei.url)
        return "-"

# ==========================================
# 2. MIETVERTRAG ADMIN
# ==========================================

@admin.register(Mietvertrag)
class MietvertragAdmin(ModelAdmin):
    # Liste mit Fairwalter-Badges
    list_display = (
        'mieter', 'einheit', 'beginn', 'netto_mietzins',
        'get_status_badge', 'potenzial_preview', 'aktiv',
        'pdf_quick_link'
    )
    list_filter = ('sign_status', 'aktiv', 'einheit__liegenschaft')
    search_fields = ('mieter__nachname', 'mieter__vorname', 'vertragsnummer')
    inlines = [DokumentVertragInline]

    # Karten-Layout für den Vertrag
    fieldsets = (
        ('Parteien & Objekt', {
            'fields': (('mieter', 'einheit'), 'aktiv'),
        }),
        ('Vertragslaufzeit', {
            'fields': (('beginn', 'ende'), 'sign_status'),
        }),
        ('Finanzielle Konditionen', {
            'fields': (
                ('netto_mietzins', 'nebenkosten'),
                'kautions_betrag'
            ),
        }),
        ('Gesetzliche Grundlagen (Mietrecht)', {
            'fields': (
                ('basis_referenzzinssatz', 'basis_lik_punkte'),
            ),
        }),
        ('Digitale Signatur (DocuSeal)', {
            'fields': ('pdf_datei',),
        }),
    )

    # --- FAIRWALTER HEADER BUTTONS ---
    actions_detail = [
        "action_generate_pdf",
        "action_send_docuseal",
        "action_mietzins_rechner",
        "action_qr_rechnung"
    ]

    @action(description="📄 PDF Vertrag erstellen", url_path="generate-pdf")
    def action_generate_pdf(self, request, object_id):
        return redirect(reverse('generate_pdf', args=[object_id]))

    @action(description="✍️ Per DocuSeal senden", url_path="send-docuseal")
    def action_send_docuseal(self, request, object_id):
        return redirect(reverse('send_docuseal', args=[object_id]))

    @action(description="📈 Mietzins-Rechner", url_path="calc-rent")
    def action_mietzins_rechner(self, request, object_id):
        return redirect(reverse('mietzins_anpassung', args=[object_id]))

    @action(description="🔳 QR-Einzahlungsschein", url_path="qr-bill")
    def action_qr_rechnung(self, request, object_id):
        return redirect(reverse('generate_qr', args=[object_id]))

    # --- BADGES & PREVIEWS ---

    @display(description="Status", label=True)
    def get_status_badge(self, obj):
        if obj.sign_status == 'unterzeichnet':
            return "Unterzeichnet", "success"
        elif obj.sign_status == 'gesendet':
            return "In Signatur", "warning"
        return "Entwurf", "info"

    @display(description="Potenzial")
    def potenzial_preview(self, obj):
        try:
            v = Verwaltung.objects.first()
            if not v or not berechne_mietpotenzial: return "-"
            res = berechne_mietpotenzial(obj, v.aktueller_referenzzinssatz, v.aktueller_lik_punkte)
            color = "text-emerald-600" if res['action'] == 'UP' else "text-red-600"
            return format_html('<span class="font-bold {}">{} CHF</span>', color, res['delta_chf'])
        except:
            return "-"

    def pdf_quick_link(self, obj):
        if obj.id:
            return format_html('<a href="{}" target="_blank">📄</a>', reverse('generate_pdf', args=[obj.id]))
        return "-"

# ==========================================
# 3. WEITERE MODULE
# ==========================================

@admin.register(MietzinsAnpassung)
class MietzinsAnpassungAdmin(ModelAdmin):
    list_display = ('vertrag', 'datum_wirksamkeit', 'alter_zins', 'neuer_zins', 'status')
    list_filter = ('status',)

@admin.register(Leerstand)
class LeerstandAdmin(ModelAdmin):
    list_display = ('einheit', 'von_datum', 'bis_datum', 'grund')
    list_filter = ('grund', 'einheit__liegenschaft')

@admin.register(Dokument)
class DokumentAdmin(ModelAdmin):
    list_display = ('bezeichnung', 'kategorie', 'erstellt_am')
    list_filter = ('kategorie',)