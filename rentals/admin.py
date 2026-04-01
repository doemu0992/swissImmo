from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.contrib import messages
import datetime

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

# Lokale Modelle (Rentals)
from .models import Mietvertrag, MietzinsAnpassung, Leerstand, Dokument
from crm.models import Verwaltung

# Helper-Funktion
try:
    from core.mietrecht_logic import berechne_mietpotenzial
except ImportError:
    berechne_mietpotenzial = None


# ==========================================
# 0. INLINES
# ==========================================

class DokumentVertragInline(TabularInline):
    model = Dokument
    extra = 0
    fk_name = "vertrag"
    fields = ('bezeichnung', 'kategorie', 'datei', 'vorschau_btn')
    readonly_fields = ('vorschau_btn',)
    tab = True

    def vorschau_btn(self, obj):
        if getattr(obj, 'datei', None):
            return format_html('<a href="{}" target="_blank" class="text-emerald-600 font-bold text-xs">📄 PDF ansehen</a>', obj.datei.url)
        return "-"


# ==========================================
# 1. MIETVERTRAG ADMIN (SaaS-Look)
# ==========================================

@admin.register(Mietvertrag)
class MietvertragAdmin(ModelAdmin):
    list_display = ('vertrag_profil', 'finanzen_info', 'laufzeit_info', 'docuseal_badge', 'schnell_aktionen')
    list_filter = ('sign_status', 'aktiv')
    list_filter_submit = True
    search_fields = ('mieter__vorname', 'mieter__nachname', 'einheit__bezeichnung')
    inlines = [DokumentVertragInline]

    fieldsets = (
        ('Parteien', {'fields': ('mieter', 'einheit')}),
        ('Vertrag', {'fields': ('beginn', 'ende', 'aktiv', 'sign_status')}),
        ('Konditionen', {'fields': ('netto_mietzins', 'nebenkosten', 'kautions_betrag', 'basis_referenzzinssatz', 'basis_lik_punkte')}),
        ('DocuSeal & PDF', {'fields': ('pdf_datei',)})
    )

    @display(description="Mietvertrag", ordering="mieter")
    def vertrag_profil(self, obj):
        mieter_name = str(getattr(obj, 'mieter', 'Unbekannt'))
        einheit_name = str(getattr(obj.einheit, 'bezeichnung', 'Keine Einheit')) if getattr(obj, 'einheit', None) else 'Keine Einheit'
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-blue-100 text-blue-700 text-xl shadow-sm ring-1 ring-inset ring-blue-600/10">📄</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">🏠 {}</div></div>'
            '</div>',
            mieter_name, einheit_name
        )

    @display(description="Mietzins (Brutto)")
    def finanzen_info(self, obj):
        # HIER IST DER FIX: Zahlenwerte sichern und vorab mit f-Strings formatieren
        netto = float(getattr(obj, 'netto_mietzins', 0) or 0)
        nk = float(getattr(obj, 'nebenkosten', 0) or 0)
        brutto = netto + nk

        return format_html(
            '<div class="flex flex-col gap-1">'
            '<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20 w-max">CHF {}</span>'
            '<span class="text-[10px] text-gray-500">N: {} | NK: {}</span>'
            '</div>',
            f"{brutto:.2f}", f"{netto:.2f}", f"{nk:.2f}"
        )

    @display(description="Laufzeit & Status")
    def laufzeit_info(self, obj):
        beginn = obj.beginn.strftime('%d.%m.%Y') if getattr(obj, 'beginn', None) else "-"
        aktiv = getattr(obj, 'aktiv', False)
        aktiv_html = '<span class="text-xs font-bold text-emerald-600">● Aktiv</span>' if aktiv else '<span class="text-xs font-bold text-red-500">○ Aufgelöst</span>'
        return format_html(
            '<div class="flex flex-col gap-0.5">'
            '{}'
            '<span class="text-xs text-gray-500">Ab {}</span>'
            '</div>',
            mark_safe(aktiv_html), beginn
        )

    @display(description="Unterschrift", label=True)
    def docuseal_badge(self, obj):
        status = getattr(obj, 'sign_status', 'offen')
        if status == 'offen': return "Ausstehend", "danger"
        elif status == 'gesendet': return "Gesendet", "warning"
        elif status == 'unterzeichnet': return "Signiert", "success"
        return status, "info"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        edit_url = reverse('admin:rentals_mietvertrag_change', args=[obj.id])
        pdf_url = reverse('generate_pdf', args=[obj.id]) if obj.id else '#'
        calc_url = reverse('mietzins_anpassung', args=[obj.id]) if getattr(obj, 'aktiv', False) else '#'

        return format_html(
            '<div class="flex gap-1.5">'
            '<a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>'
            '<a href="{}" target="_blank" class="text-gray-600 bg-gray-50 hover:bg-gray-200 px-2 py-1 rounded text-xs transition-colors">🖨️ PDF</a>'
            '<a href="{}" target="_blank" class="text-blue-600 bg-blue-50 hover:bg-blue-100 px-2 py-1 rounded text-xs transition-colors">📈 Zins</a>'
            '</div>',
            edit_url, pdf_url, calc_url
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if getattr(obj, 'sign_status', '') == 'unterzeichnet' and getattr(obj, 'pdf_datei', None):
            exists = Dokument.objects.filter(vertrag=obj, kategorie='vertrag').exists()
            if not exists:
                Dokument.objects.create(titel=f"Mietvertrag {obj.mieter}", kategorie='vertrag', vertrag=obj, mieter=obj.mieter, einheit=obj.einheit, datei=obj.pdf_datei)
                messages.success(request, "✅ Vertrag archiviert.")


# ==========================================
# 2. LEERSTAND ADMIN (SaaS-Look)
# ==========================================

@admin.register(Leerstand)
class LeerstandAdmin(ModelAdmin):
    list_display = ('leerstand_profil', 'dauer_info', 'schnell_aktionen')

    @display(description="Objekt & Grund", ordering="einheit__bezeichnung")
    def leerstand_profil(self, obj):
        einheit = getattr(obj, 'einheit', None)
        einheit_name = einheit.bezeichnung if einheit else "Unbekannt"
        grund = obj.get_grund_display() if hasattr(obj, 'get_grund_display') else getattr(obj, 'grund', '-')

        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-red-100 text-red-700 text-xl shadow-sm ring-1 ring-inset ring-red-600/10">⏳</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-[11px] font-medium text-red-600 mt-0.5 bg-red-50 px-1.5 rounded w-max">{}</div></div>'
            '</div>',
            einheit_name, grund
        )

    @display(description="Zeitraum")
    def dauer_info(self, obj):
        beginn = obj.beginn.strftime('%d.%m.%Y') if getattr(obj, 'beginn', None) else "-"
        ende = obj.ende.strftime('%d.%m.%Y') if getattr(obj, 'ende', None) else "Laufend"
        return format_html('<span class="text-sm font-medium text-gray-700">{} – {}</span>', beginn, ende)

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html(
            '<a href="{}" class="text-red-600 hover:text-red-900 bg-red-50 hover:bg-red-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>',
            reverse('admin:rentals_leerstand_change', args=[obj.id])
        )


# ==========================================
# 3. MIETZINSANPASSUNG ADMIN (SaaS-Look)
# ==========================================

@admin.register(MietzinsAnpassung)
class MietzinsAnpassungAdmin(ModelAdmin):
    list_display = ('anpassung_profil', 'datum_info', 'status_badge', 'schnell_aktionen')

    @display(description="Vertrag & Änderung")
    def anpassung_profil(self, obj):
        vertrag = getattr(obj, 'vertrag', None)
        mieter = str(vertrag.mieter) if vertrag else "Unbekannt"

        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-teal-100 text-teal-700 text-xl shadow-sm ring-1 ring-inset ring-teal-600/10">📈</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-[11px] text-gray-500 mt-0.5">ID: #{}</div></div>'
            '</div>',
            mieter, obj.id
        )

    @display(description="Wirksam ab")
    def datum_info(self, obj):
        datum = getattr(obj, 'wirksam_ab', None) or getattr(obj, 'datum_wirksam', None)
        datum_str = datum.strftime('%d.%m.%Y') if datum else "-"
        return format_html('<span class="text-sm font-medium text-gray-700">{}</span>', datum_str)

    @display(description="Status", label=True)
    def status_badge(self, obj):
        status = getattr(obj, 'status', 'erstellt')
        if status == 'erstellt': return "Erstellt", "info"
        elif status == 'gesendet': return "Gesendet", "warning"
        elif status == 'akzeptiert': return "Akzeptiert", "success"
        return status, "info"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html(
            '<a href="{}" class="text-teal-600 hover:text-teal-900 bg-teal-50 hover:bg-teal-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>',
            reverse('admin:rentals_mietzinsanpassung_change', args=[obj.id])
        )


# ==========================================
# 4. DOKUMENTE ADMIN
# ==========================================

@admin.register(Dokument)
class DokumentAdmin(ModelAdmin):
    list_display = ('dokument_profil', 'kategorie_badge')
    list_filter = ('kategorie',)

    @display(description="Dokument")
    def dokument_profil(self, obj):
        titel = getattr(obj, 'titel', getattr(obj, 'bezeichnung', 'Unbekanntes Dokument'))
        return format_html(
            '<div class="flex items-center gap-2">'
            '<span class="text-lg">📎</span> <span class="font-medium text-gray-800">{}</span>'
            '</div>',
            titel
        )

    @display(description="Kategorie", label=True)
    def kategorie_badge(self, obj):
        kat = getattr(obj, 'kategorie', 'Sonstiges')
        return kat, "info"