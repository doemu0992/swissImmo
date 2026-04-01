from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

# Modelle aus der eigenen App (CRM)
from .models import Verwaltung, Mandant, Mieter, Handwerker

# Modelle aus anderen Apps für die Inlines (Verknüpfungen)
from rentals.models import Mietvertrag, Dokument
from tickets.models import SchadenMeldung
from portfolio.models import SchluesselAusgabe

try:
    from core.utils.market_data import update_verwaltung_rates
except ImportError:
    update_verwaltung_rates = None


# ==========================================
# 0. INLINES
# ==========================================

class MietvertragMieterInline(TabularInline): model = Mietvertrag; extra = 0; fk_name = "mieter"; show_change_link = True; tab = True
class SchluesselMieterInline(TabularInline): model = SchluesselAusgabe; extra = 0; fk_name = "mieter"; tab = True
class SchadenMieterInline(TabularInline): model = SchadenMeldung; extra = 0; fk_name = "gemeldet_von"; tab = True
class DokumentMieterInline(TabularInline): model = Dokument; extra = 0; fk_name = "mieter"; tab = True


# ==========================================
# 1. MIETER ADMIN (SaaS-Look: BLAU)
# ==========================================

@admin.register(Mieter)
class MieterAdmin(ModelAdmin):
    list_display = ('mieter_profil', 'kontakt_info', 'standort_info', 'schnell_aktionen')
    search_fields = ('nachname', 'vorname', 'email')
    inlines = [MietvertragMieterInline, DokumentMieterInline, SchadenMieterInline, SchluesselMieterInline]

    @display(description="Mieter Profil", ordering="nachname")
    def mieter_profil(self, obj):
        init_v = obj.vorname[0].upper() if getattr(obj, 'vorname', None) else ""
        init_n = obj.nachname[0].upper() if getattr(obj, 'nachname', None) else ""
        initials = f"{init_v}{init_n}"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-full bg-blue-100 text-blue-700 font-bold text-xs ring-2 ring-white shadow-sm">{}</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{} {}</div><div class="text-xs text-gray-500 mt-0.5">ID: #{}</div></div>'
            '</div>',
            initials, getattr(obj, 'vorname', ''), getattr(obj, 'nachname', ''), obj.id
        )

    @display(description="Kontakt")
    def kontakt_info(self, obj):
        html = '<div class="flex flex-col gap-1">'
        tel, mail = getattr(obj, 'telefon', None), getattr(obj, 'email', None)
        if tel: html += f'<a href="tel:{tel}" class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 text-xs font-medium text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 w-max">📞 {tel}</a>'
        if mail: html += f'<a href="mailto:{mail}" class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 text-xs font-medium text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 w-max">✉️ {mail}</a>'
        return format_html(html or '<span class="text-xs text-gray-400">-</span>')

    @display(description="Standort")
    def standort_info(self, obj): return getattr(obj, 'ort', '-')

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>',
            reverse('admin:crm_mieter_change', args=[obj.id]))


# ==========================================
# 2. HANDWERKER ADMIN (SaaS-Look: ORANGE)
# ==========================================

@admin.register(Handwerker)
class HandwerkerAdmin(ModelAdmin):
    list_display = ('handwerker_profil', 'kontakt_info', 'standort_info', 'schnell_aktionen')
    search_fields = ('firma', 'gewerk')

    @display(description="Handwerker & Gewerk", ordering="firma")
    def handwerker_profil(self, obj):
        gewerk = getattr(obj, 'gewerk', '')
        icon = "🔧"
        if "sanitär" in str(gewerk).lower(): icon = "💧"
        elif "elektro" in str(gewerk).lower(): icon = "⚡"
        elif "maler" in str(gewerk).lower(): icon = "🎨"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-orange-100 text-orange-700 text-lg shadow-sm">{}</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><span class="inline-flex items-center mt-1 rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">{}</span></div>'
            '</div>',
            icon, getattr(obj, 'firma', 'Unbekannt'), gewerk
        )

    @display(description="Kontakt")
    def kontakt_info(self, obj):
        html = '<div class="flex flex-col gap-1">'
        tel, mail = getattr(obj, 'telefon', None), getattr(obj, 'email', None)
        if tel: html += f'<a href="tel:{tel}" class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 text-xs font-medium text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 w-max">📞 {tel}</a>'
        if mail: html += f'<a href="mailto:{mail}" class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 text-xs font-medium text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 w-max">✉️ {mail}</a>'
        return format_html(html or '<span class="text-xs text-gray-400">-</span>')

    @display(description="Standort")
    def standort_info(self, obj): return getattr(obj, 'ort', '-')

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-orange-600 hover:text-orange-900 bg-orange-50 hover:bg-orange-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>',
            reverse('admin:crm_handwerker_change', args=[obj.id]))


# ==========================================
# 3. MANDANTEN ADMIN (SaaS-Look: VIOLETT)
# ==========================================

@admin.register(Mandant)
class MandantAdmin(ModelAdmin):
    list_display = ('mandant_profil', 'kontakt_info', 'standort_info', 'schnell_aktionen')
    search_fields = ('firma_oder_name',)

    @display(description="Mandant / Eigentümer", ordering="firma_oder_name")
    def mandant_profil(self, obj):
        name = getattr(obj, 'firma_oder_name', 'Unbekannt')
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-purple-100 text-purple-700 text-lg shadow-sm">🏢</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">ID: #{}</div></div>'
            '</div>',
            name, obj.id
        )

    @display(description="Kontakt")
    def kontakt_info(self, obj):
        html = '<div class="flex flex-col gap-1">'
        tel, mail = getattr(obj, 'telefon', None), getattr(obj, 'email', None)
        if tel: html += f'<a href="tel:{tel}" class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 text-xs font-medium text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 w-max">📞 {tel}</a>'
        if mail: html += f'<a href="mailto:{mail}" class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 text-xs font-medium text-gray-600 hover:bg-gray-100 ring-1 ring-inset ring-gray-200 w-max">✉️ {mail}</a>'
        return format_html(html or '<span class="text-xs text-gray-400">-</span>')

    @display(description="Standort")
    def standort_info(self, obj): return getattr(obj, 'ort', '-')

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-purple-600 hover:text-purple-900 bg-purple-50 hover:bg-purple-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>',
            reverse('admin:crm_mandant_change', args=[obj.id]))


# ==========================================
# 4. VERWALTUNG ADMIN
# ==========================================

@admin.register(Verwaltung)
class VerwaltungAdmin(ModelAdmin):
    list_display = ('firma', 'standort_info', 'get_zins_badge', 'aktueller_lik_punkte')
    actions_detail = ["action_check_rates"]

    @display(description="Standort")
    def standort_info(self, obj): return getattr(obj, 'ort', '-')

    @action(description="🔄 Marktdaten prüfen (BfS)", url_path="check-rates")
    def action_check_rates(self, request, object_id=None):
        if not update_verwaltung_rates:
            messages.error(request, "Das Modul 'update_verwaltung_rates' wurde nicht gefunden.")
            return redirect(request.META.get('HTTP_REFERER', '/admin/'))
        msg, err = update_verwaltung_rates()
        if err: messages.error(request, f"Fehler: {err}")
        else: messages.success(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/admin/'))

    @display(description="Referenzzinssatz", label=True)
    def get_zins_badge(self, obj):
        zins = getattr(obj, 'aktueller_referenzzinssatz', None)
        return f"{zins} %" if zins else "Fehlt", "success" if zins else "danger"