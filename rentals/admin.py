# rentals/admin.py
import urllib.parse
from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Sum
from datetime import date

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display, action

# Lokale Modelle (Rentals)
from .models import Mietvertrag, MietzinsAnpassung, Leerstand, Dokument
from crm.models import Verwaltung

# Helper-Funktion
try:
    from core.mietrecht_logic import berechne_mietpotenzial
except ImportError:
    berechne_mietpotenzial = None

# ==========================================
# 0. SICHERHEITS-CHECK (Gegen Reload-Abstürze)
# ==========================================
models_to_fix = [Mietvertrag, MietzinsAnpassung, Leerstand, Dokument]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass


# ==========================================
# 1. INLINES (SaaS-Tabs)
# ==========================================

class DokumentVertragInline(TabularInline):
    model = Dokument
    extra = 0
    fk_name = "vertrag"
    tab = True
    verbose_name = "Vertragsdokument"
    verbose_name_plural = "📄 Verknüpfte Dokumente"

    fields = ('dokument_profil', 'kategorie_info', 'vorschau_btn')
    readonly_fields = ('dokument_profil', 'kategorie_info', 'vorschau_btn')

    @display(description="Dokument")
    def dokument_profil(self, obj):
        if not obj.pk: return "-"
        titel = getattr(obj, 'titel', getattr(obj, 'bezeichnung', 'Dokument'))
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-50 text-indigo-700 text-sm ring-1 ring-inset ring-indigo-600/20">📎</div>'
            '<div class="font-bold text-gray-900">{}</div>'
            '</div>', titel
        )

    @display(description="Kategorie")
    def kategorie_info(self, obj):
        if not obj.pk: return "-"
        kat = obj.get_kategorie_display() if hasattr(obj, 'get_kategorie_display') else getattr(obj, 'kategorie', '-')
        return format_html('<span class="inline-flex items-center rounded-md bg-gray-50 px-2 py-1 text-xs font-medium text-gray-600 ring-1 ring-inset ring-gray-500/10">{}</span>', kat)

    @display(description="Aktion")
    def vorschau_btn(self, obj):
        if getattr(obj, 'datei', None):
            return format_html('<a href="{}" target="_blank" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">⬇️ Ansehen</a>', obj.datei.url)
        return "-"

    def has_add_permission(self, request, obj=None):
        return False


# ==========================================
# 2. MIETVERTRAG ADMIN (SaaS-Look)
# ==========================================

@admin.register(Mietvertrag)
class MietvertragAdmin(ModelAdmin):
    list_display = ('vertrag_profil', 'finanzen_info', 'laufzeit_info', 'docuseal_badge', 'schnell_aktionen')
    list_filter = ('sign_status', 'aktiv')
    list_filter_submit = True
    search_fields = ('mieter__vorname', 'mieter__nachname', 'einheit__bezeichnung')
    inlines = [DokumentVertragInline]

    readonly_fields = ('vertrag_full_header',)

    fieldsets = (
        (None, {
            'fields': ('vertrag_full_header',),
            # FIX: Zwingend .map-fieldset verwenden, damit das Layout 1:1 wie bei Liegenschaften funktioniert!
            'classes': ('map-fieldset',),
        }),
        ('Vertragsparteien & Objekt', {'fields': ('mieter', 'einheit')}),
        ('Laufzeit & Status', {'fields': (('beginn', 'ende'), ('aktiv', 'sign_status'))}),
        ('Finanzielle Konditionen', {'fields': (('netto_mietzins', 'nebenkosten'), 'kautions_betrag')}),
        ('Mietrechtliche Basis', {'fields': (('basis_referenzzinssatz', 'basis_lik_punkte'),)}),
        ('Digitale Akte', {'fields': ('pdf_datei',)})
    )

    # --- SAAS HEADER BUTTONS ---
    actions_detail = ["action_generate_pdf", "action_send_docuseal", "action_mietzins_rechner"]

    @action(description="📄 PDF erstellen", url_path="generate-pdf")
    def action_generate_pdf(self, request, object_id):
        return redirect(reverse('generate_pdf', args=[object_id]))

    @action(description="✍️ Per DocuSeal senden", url_path="send-docuseal")
    def action_send_docuseal(self, request, object_id):
        return redirect(reverse('send_docuseal', args=[object_id]))

    @action(description="📈 Zinsrechner öffnen", url_path="calc-rent")
    def action_mietzins_rechner(self, request, object_id):
        return redirect(reverse('mietzins_anpassung', args=[object_id]))

    # --- DASHBOARD HEADER ---
    @display(description="")
    def vertrag_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-blue-50 text-blue-700 rounded-xl font-bold border border-blue-100">✨ Neuen Mietvertrag anlegen</div>')

        netto = float(getattr(obj, 'netto_mietzins', 0) or 0)
        nk = float(getattr(obj, 'nebenkosten', 0) or 0)
        brutto = netto + nk
        mieter_name = str(getattr(obj, 'mieter', 'Unbekannt'))

        # Einheit und Liegenschaft sicher abrufen
        einheit_name = str(getattr(obj.einheit, 'bezeichnung', '-')) if getattr(obj, 'einheit', None) else '-'
        lieg_obj = getattr(obj.einheit, 'liegenschaft', None) if getattr(obj, 'einheit', None) else None
        liegenschaft_name = str(getattr(lieg_obj, 'strasse', '-')) if lieg_obj else '-'

        beginn = obj.beginn.strftime('%d.%m.%Y') if getattr(obj, 'beginn', None) else "-"

        aktiv_color = "#059669" if getattr(obj, 'aktiv', False) else "#dc2626"
        aktiv_text = "Aktiv" if getattr(obj, 'aktiv', False) else "Inaktiv"

        # --- MIETERKONTO STATUS BERECHNEN ---
        heute = date.today()
        aktueller_monat = heute.replace(day=1)
        monat_str = aktueller_monat.strftime('%m/%Y')

        if not getattr(obj, 'aktiv', False):
            konto_status = "Inaktiv"
            konto_color = "#6b7280" # Grau
            konto_icon = "⏸️"
        else:
            zahlungen_aktuell = obj.zahlungen.filter(buchungs_monat=aktueller_monat).aggregate(Sum('betrag'))['betrag__sum'] or 0
            zahlungen_aktuell = float(zahlungen_aktuell)

            if zahlungen_aktuell >= brutto:
                konto_status = "Bezahlt"
                konto_color = "#059669" # Grün
                konto_icon = "✅"
            elif zahlungen_aktuell > 0:
                konto_status = f"Teilz. ({zahlungen_aktuell:,.0f})"
                konto_color = "#d97706" # Orange
                konto_icon = "⚠️"
            else:
                konto_status = "Offen"
                konto_color = "#dc2626" # Rot
                konto_icon = "⏳"

        # --- GOOGLE MAPS URL GENERIEREN ---
        if lieg_obj and getattr(lieg_obj, 'strasse', None) and getattr(lieg_obj, 'ort', None):
            address_query = urllib.parse.quote(f"{lieg_obj.strasse}, {lieg_obj.plz} {lieg_obj.ort}")
            map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
        else:
            map_url = "https://maps.google.com/maps?q=Selzacherstrasse%204%2C%204512%20Bellach&t=&z=15&ie=UTF8&iwloc=&output=embed"

        html = f"""
        <style>
            #content-main form > div, form .max-w-5xl, form .max-w-4xl, form .max-w-3xl, form .max-w-2xl {{ max-width: 100% !important; width: 100% !important; }}
            fieldset.map-fieldset {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; border: none !important; background: transparent !important; box-shadow: none !important; grid-column: 1 / -1 !important; }}
            fieldset.map-fieldset > div, fieldset.map-fieldset .form-row {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; margin: 0 !important; border: none !important; }}
            fieldset.map-fieldset label {{ display: none !important; }}
            .liegenschaft-header-grid {{ display: grid; grid-template-columns: 1fr; gap: 1.5rem; width: 100%; margin-bottom: 2rem; }}
            @media (min-width: 1024px) {{ .liegenschaft-header-grid {{ grid-template-columns: 350px 1fr; }} }}
        </style>

        <div class="liegenschaft-header-grid">
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                <div style="background: white; padding: 1.5rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 1rem;">
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #eff6ff; color: #3b82f6; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">👤</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{mieter_name}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px;">🏠 {einheit_name}</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px;">📍 {liegenschaft_name}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Bruttomiete</span>
                        <span style="font-size: 1.25rem; font-weight: 700; color: #111827;">{brutto:,.0f}.-</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Status</span>
                        <span style="font-size: 1.25rem; font-weight: 700; color: {aktiv_color};">{aktiv_text}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; justify-content: space-between; grid-column: span 2;">
                        <div>
                            <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; display: block;">Mietkonto ({monat_str})</span>
                            <span style="font-size: 1.25rem; font-weight: 700; color: {konto_color};">{konto_status}</span>
                        </div>
                        <div style="font-size: 1.5rem;">{konto_icon}</div>
                    </div>
                </div>
            </div>

            <div style="width: 100%; height: 100%; min-height: 250px; background-color: #e5e7eb; border-radius: 12px; overflow: hidden; border: 1px solid #d1d5db; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <iframe
                    width="100%"
                    height="100%"
                    frameborder="0"
                    style="border:0;"
                    src="{map_url}"
                    allowfullscreen>
                </iframe>
            </div>
        </div>
        """
        return mark_safe(html)

    # --- Listenansicht Formatierungen ---
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
        netto = float(getattr(obj, 'netto_mietzins', 0) or 0)
        nk = float(getattr(obj, 'nebenkosten', 0) or 0)
        brutto = netto + nk
        return format_html(
            '<div class="flex flex-col gap-1">'
            '<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20 w-max">CHF {}</span>'
            '<span class="text-[10px] text-gray-500">N: {} | NK: {}</span>'
            '</div>',
            f"{brutto:,.2f}", f"{netto:,.2f}", f"{nk:,.2f}"
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
            '<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>'
            '<a href="{}" target="_blank" class="text-gray-600 bg-gray-50 hover:bg-gray-200 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">🖨️ PDF</a>'
            '<a href="{}" target="_blank" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📈 Zins</a>'
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
# 3. LEERSTAND ADMIN (SaaS-Look)
# ==========================================

@admin.register(Leerstand)
class LeerstandAdmin(ModelAdmin):
    list_display = ('leerstand_profil', 'dauer_info', 'schnell_aktionen')

    fieldsets = (
        ("Leerstand Details", {
            "fields": ("einheit", "grund")
        }),
        ("Dauer", {
            "fields": ("beginn", "ende")
        }),
        ("Zusätzliche Informationen", {
            "fields": ("bemerkung",)
        }),
    )

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
            '<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:rentals_leerstand_change', args=[obj.id])
        )


# ==========================================
# 4. MIETZINSANPASSUNG ADMIN (SaaS-Look)
# ==========================================

@admin.register(MietzinsAnpassung)
class MietzinsAnpassungAdmin(ModelAdmin):
    list_display = ('anpassung_profil', 'datum_info', 'schnell_aktionen')

    fieldsets = (
        ("Vertrag & Wirksamkeit", {
            "fields": ("vertrag", "wirksam_ab")
        }),
        ("Mietzins (Neu vs. Alt)", {
            "fields": ("neuer_netto_mietzins", "alter_netto_mietzins", "erhoehung_prozent_total")
        }),
        ("Basis-Parameter (Neu vs. Alt)", {
            "fields": ("neuer_referenzzinssatz", "alter_referenzzinssatz", "neuer_lik_index", "alter_lik_index")
        }),
        ("Zusatz", {
            "fields": ("begruendung",)
        }),
    )

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
        datum = getattr(obj, 'wirksam_ab', None)
        datum_str = datum.strftime('%d.%m.%Y') if datum else "-"
        return format_html('<span class="text-sm font-medium text-gray-700">{}</span>', datum_str)

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html(
            '<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:rentals_mietzinsanpassung_change', args=[obj.id])
        )


# ==========================================
# 5. DOKUMENTE ADMIN
# ==========================================

@admin.register(Dokument)
class DokumentAdmin(ModelAdmin):
    list_display = ('dokument_profil', 'kategorie_badge', 'schnell_aktionen')
    list_filter = ('kategorie',)

    fieldsets = (
        ("Dokumenten-Details", {
            "fields": ("titel", "bezeichnung", "kategorie", "datei")
        }),
        ("Verknüpfungen", {
            "fields": ("mandant", "liegenschaft", "einheit", "mieter", "vertrag")
        }),
    )

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

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html(
            '<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:rentals_dokument_change', args=[obj.id])
        )