from django.contrib import admin
from django.utils.html import format_html, mark_safe
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
# 0. SICHERHEITS-CHECK (Gegen Reload-Abstürze)
# ==========================================
models_to_fix = [Verwaltung, Mandant, Mieter, Handwerker]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass


# ==========================================
# 1. INLINES (SaaS-Tabs für Mieter)
# ==========================================

class MietvertragMieterInline(TabularInline):
    model = Mietvertrag
    extra = 0
    fk_name = "mieter"
    tab = True
    verbose_name = "Mietvertrag"
    verbose_name_plural = "🤝 Mietverträge"
    fields = ('vertrag_profil', 'laufzeit', 'finanzen', 'status_badge', 'detail_link')
    readonly_fields = ('vertrag_profil', 'laufzeit', 'finanzen', 'status_badge', 'detail_link')

    @display(description="Vertrag & Objekt")
    def vertrag_profil(self, obj):
        if not obj.pk: return "-"
        einheit = obj.einheit.bezeichnung if getattr(obj, 'einheit', None) else "Unbekanntes Objekt"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-blue-50 text-blue-700 text-sm ring-1 ring-inset ring-blue-600/20">📄</div>'
            '<div><div class="font-bold text-gray-900">{}</div></div>'
            '</div>', einheit
        )
    @display(description="Laufzeit")
    def laufzeit(self, obj):
        return obj.beginn.strftime('%d.%m.%Y') if obj.pk and getattr(obj, 'beginn', None) else "-"
    @display(description="Bruttomiete")
    def finanzen(self, obj):
        if not obj.pk: return "-"
        total = (obj.netto_mietzins or 0) + (obj.nebenkosten or 0)
        return format_html('<span class="font-semibold text-gray-900">CHF {:,.2f}</span>', total)
    @display(description="Status")
    def status_badge(self, obj):
        if not obj.pk: return "-"
        if getattr(obj, 'aktiv', False): return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">Aktiv</span>')
        return format_html('<span class="inline-flex items-center rounded-md bg-gray-50 px-2 py-1 text-xs font-medium text-gray-700 ring-1 ring-inset ring-gray-600/10">Inaktiv</span>')
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 Öffnen</a>', reverse("admin:rentals_mietvertrag_change", args=[obj.id]))
        return "-"
    def has_add_permission(self, request, obj=None): return False

class SchadenMieterInline(TabularInline):
    model = SchadenMeldung
    extra = 0
    fk_name = "gemeldet_von"
    tab = True
    verbose_name = "Schadensmeldung"
    verbose_name_plural = "🎫 Gemeldete Schäden"
    fields = ('ticket_profil', 'status_badge', 'detail_link')
    readonly_fields = ('ticket_profil', 'status_badge', 'detail_link')

    @display(description="Ticket & Datum")
    def ticket_profil(self, obj):
        if not obj.pk: return "-"
        erstellt = obj.erstellt_am.strftime('%d.%m.%Y') if getattr(obj, 'erstellt_am', None) else "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-rose-50 text-rose-700 text-sm ring-1 ring-inset ring-rose-600/20">🚨</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-[10px] text-gray-500 uppercase">Gemeldet: {}</div></div>'
            '</div>', getattr(obj, 'titel', 'Ticket'), erstellt
        )
    @display(description="Status")
    def status_badge(self, obj):
        if not obj.pk: return "-"
        if getattr(obj, 'status', '') == 'erledigt': return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">Erledigt</span>')
        return format_html('<span class="inline-flex items-center rounded-md bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 ring-1 ring-inset ring-rose-600/10">In Bearbeitung</span>')
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-rose-600 hover:text-rose-900 bg-rose-50 hover:bg-rose-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">🎫 Ticket öffnen</a>', reverse("admin:tickets_schadenmeldung_change", args=[obj.id]))
        return "-"
    def has_add_permission(self, request, obj=None): return False

class DokumentMieterInline(TabularInline):
    model = Dokument
    extra = 0
    fk_name = "mieter"
    tab = True
    verbose_name = "Dokument"
    verbose_name_plural = "📄 Verknüpfte Dokumente"
    fields = ('doc_profil', 'detail_link')
    readonly_fields = ('doc_profil', 'detail_link')

    @display(description="Dokument")
    def doc_profil(self, obj):
        if not obj.pk: return "-"
        titel = getattr(obj, 'titel', getattr(obj, 'bezeichnung', 'Unbekannt'))
        kategorie = obj.get_kategorie_display() if hasattr(obj, 'get_kategorie_display') else getattr(obj, 'kategorie', '')
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-50 text-indigo-700 text-sm ring-1 ring-inset ring-indigo-600/20">📄</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-[10px] text-gray-500 uppercase">{}</div></div>'
            '</div>', titel, kategorie
        )
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">⬇️ Ansehen</a>', reverse("admin:rentals_dokument_change", args=[obj.id]))
        return "-"
    def has_add_permission(self, request, obj=None): return False

class SchluesselMieterInline(TabularInline):
    model = SchluesselAusgabe
    extra = 0
    fk_name = "mieter"
    tab = True
    verbose_name = "Schlüssel"
    verbose_name_plural = "🔑 Ausgegebene Schlüssel"
    fields = ('schluessel_profil', 'detail_link')
    readonly_fields = ('schluessel_profil', 'detail_link')

    @display(description="Schlüssel")
    def schluessel_profil(self, obj):
        if not obj.pk: return "-"
        nr = str(obj.schluessel) if getattr(obj, 'schluessel', None) else "Unbekannt"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-50 text-zinc-700 text-sm ring-1 ring-inset ring-zinc-600/20">🔑</div>'
            '<div class="font-bold text-gray-900">{}</div>'
            '</div>', nr
        )
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-zinc-600 hover:text-zinc-900 bg-zinc-50 hover:bg-zinc-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 Details</a>', reverse("admin:portfolio_schluesselausgabe_change", args=[obj.id]))
        return "-"
    def has_add_permission(self, request, obj=None): return False


# ==========================================
# 2. MIETER ADMIN (SaaS-Look: BLAU)
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
# 3. HANDWERKER ADMIN (SaaS-Look: ORANGE)
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
# 4. MANDANTEN ADMIN (SaaS-Look: VIOLETT)
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
# 5. VERWALTUNG ADMIN
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