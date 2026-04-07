# portfolio/admin.py
from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.contrib import messages
import urllib.parse

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

# Lokale Modelle (Portfolio)
from .models import Liegenschaft, Einheit, Zaehler, ZaehlerStand, Geraet, Unterhalt, Schluessel, SchluesselAusgabe

# Externe Modelle für Inlines
from rentals.models import Mietvertrag, Dokument
from tickets.models import SchadenMeldung

# Helper
try:
    from core.gwr import get_egid_from_address, get_units_from_bfs
except ImportError:
    get_egid_from_address = None
    get_units_from_bfs = None

# ==========================================
# 0. SICHERHEITS-CHECK (Gegen Reload-Abstürze)
# ==========================================
models_to_fix = [Liegenschaft, Einheit, Zaehler, Schluessel, Geraet, Unterhalt, SchluesselAusgabe, ZaehlerStand]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# ==========================================
# 1. INLINES (SaaS-Tabs für Liegenschaft)
# ==========================================

class EinheitInline(TabularInline):
    model = Einheit
    extra = 0
    tab = True
    fields = ('einheit_profil', 'flaeche_info', 'miet_info', 'status_badge', 'detail_link')
    readonly_fields = ('einheit_profil', 'flaeche_info', 'miet_info', 'status_badge', 'detail_link')

    @display(description="Mietobjekt")
    def einheit_profil(self, obj):
        if not obj.pk: return "-"
        icon = "🏠" if obj.typ == 'whg' else "🚗" if obj.typ in ['pp', 'gar'] else "🏬"
        typ_name = obj.get_typ_display()
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-teal-50 text-teal-700 text-sm ring-1 ring-inset ring-teal-600/20">{}</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-[10px] text-gray-500 uppercase tracking-wide">{}</div></div>'
            '</div>', icon, obj.bezeichnung, typ_name
        )

    @display(description="Fläche")
    def flaeche_info(self, obj):
        if not obj.pk or not getattr(obj, 'flaeche_m2', None): return "-"
        return format_html('<span class="text-sm font-medium text-gray-700">{} m²</span>', obj.flaeche_m2)

    @display(description="Finanzen (Brutto)")
    def miet_info(self, obj):
        if not obj.pk: return "-"
        total = (getattr(obj, 'nettomiete_aktuell', 0) or 0) + (getattr(obj, 'nebenkosten_aktuell', 0) or 0)
        return format_html('<span class="font-semibold text-gray-900">CHF {:,.2f}</span>', total)

    @display(description="Status")
    def status_badge(self, obj):
        if not obj.pk: return "-"
        if getattr(obj, 'aktiver_vertrag', False):
            return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">Vermietet</span>')
        return format_html('<span class="inline-flex items-center rounded-md bg-red-50 px-2 py-1 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-600/10">Leerstand</span>')

    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id:
            return format_html('<a href="{}" class="text-teal-600 hover:text-teal-900 bg-teal-50 hover:bg-teal-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse("admin:portfolio_einheit_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


class UnterhaltLiegenschaftInline(TabularInline):
    model = Unterhalt
    extra = 0
    tab = True
    verbose_name = "Unterhalt Gebäude"
    verbose_name_plural = "🛠️ Unterhaltshistorie (Allgemein)"
    fields = ('unterhalt_profil', 'datum_info', 'kosten_info', 'detail_link')
    readonly_fields = ('unterhalt_profil', 'datum_info', 'kosten_info', 'detail_link')

    def get_queryset(self, request):
        return super().get_queryset(request).filter(einheit__isnull=True)

    @display(description="Auftrags-Titel")
    def unterhalt_profil(self, obj):
        if not obj.pk: return "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-amber-50 text-amber-700 text-sm ring-1 ring-inset ring-amber-600/20">🛠️</div>'
            '<div class="font-bold text-gray-900">{}</div>'
            '</div>', obj.titel
        )

    @display(description="Datum")
    def datum_info(self, obj):
        if not obj.pk or not obj.datum: return "-"
        return format_html('<span class="text-sm text-gray-600">{}</span>', obj.datum.strftime('%d.%m.%Y'))

    @display(description="Kosten")
    def kosten_info(self, obj):
        if not obj.pk: return "-"
        return format_html('<span class="inline-flex items-center rounded-md bg-red-50 px-2 py-1 text-xs font-bold text-red-700 ring-1 ring-inset ring-red-600/10">CHF {:,.2f}</span>', obj.kosten)

    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-amber-600 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 Details</a>', reverse("admin:portfolio_unterhalt_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


# ==========================================
# 2. INLINES (SaaS-Tabs für Wohnung/Einheit)
# ==========================================

class MietvertragInline(TabularInline):
    model = Mietvertrag
    extra = 0
    tab = True
    verbose_name = "Mietvertrag"
    verbose_name_plural = "🤝 Mietverträge"
    fields = ('vertrag_profil', 'laufzeit', 'finanzen', 'status_badge', 'detail_link')
    readonly_fields = ('vertrag_profil', 'laufzeit', 'finanzen', 'status_badge', 'detail_link')

    @display(description="Mieter")
    def vertrag_profil(self, obj):
        if not obj.pk: return "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-blue-50 text-blue-700 text-sm ring-1 ring-inset ring-blue-600/20">👤</div>'
            '<div class="font-bold text-gray-900">{}</div>'
            '</div>', obj.mieter
        )
    @display(description="Beginn")
    def laufzeit(self, obj):
        return obj.beginn.strftime('%d.%m.%Y') if obj.pk and obj.beginn else "-"
    @display(description="Mietzins (Brutto)")
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
        if obj.id: return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 Vertrag öffnen</a>', reverse("admin:rentals_mietvertrag_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class ZaehlerInline(TabularInline):
    model = Zaehler
    extra = 0
    tab = True
    verbose_name = "Zähler"
    verbose_name_plural = "⚡ Zähler (Strom/Wasser/Heizung)"
    fields = ('zaehler_profil', 'detail_link')
    readonly_fields = ('zaehler_profil', 'detail_link')

    @display(description="Zähler Details")
    def zaehler_profil(self, obj):
        if not obj.pk: return "-"
        icon = "⚡" if obj.typ == 'strom' else "💧" if obj.typ == 'wasser' else "🔥"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gray-50 text-gray-700 text-sm ring-1 ring-inset ring-gray-600/20">{}</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-[10px] text-gray-500 uppercase tracking-wide">Zähler-Nr: {}</div></div>'
            '</div>', icon, obj.get_typ_display(), obj.zaehler_nummer
        )
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-gray-600 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Ablesen / Details</a>', reverse("admin:portfolio_zaehler_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class GeraetInline(TabularInline):
    model = Geraet
    extra = 0
    tab = True
    verbose_name = "Gerät"
    verbose_name_plural = "🔌 Haushaltsgeräte"
    fields = ('geraet_profil', 'garantie_badge', 'detail_link')
    readonly_fields = ('geraet_profil', 'garantie_badge', 'detail_link')

    @display(description="Gerät & Modell")
    def geraet_profil(self, obj):
        if not obj.pk: return "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-50 text-slate-700 text-sm ring-1 ring-inset ring-slate-600/20">🔌</div>'
            '<div><div class="font-bold text-gray-900">{} {}</div><div class="text-[10px] text-gray-500 uppercase tracking-wide">Modell: {}</div></div>'
            '</div>', getattr(obj, 'marke', ''), getattr(obj, 'typ', ''), getattr(obj, 'modell', '-')
        )
    @display(description="Garantie")
    def garantie_badge(self, obj):
        if not obj.pk: return "-"
        from django.utils import timezone
        if obj.garantie_bis:
            if obj.garantie_bis >= timezone.now().date():
                return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">Bis {}</span>', obj.garantie_bis.strftime('%d.%m.%Y'))
            return format_html('<span class="inline-flex items-center rounded-md bg-red-50 px-2 py-1 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-600/10">Abgelaufen</span>')
        return "-"
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-slate-600 hover:text-slate-900 bg-slate-50 hover:bg-slate-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Details</a>', reverse("admin:portfolio_geraet_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class UnterhaltEinheitInline(TabularInline):
    model = Unterhalt
    extra = 0
    fk_name = "einheit"
    tab = True
    verbose_name = "Reparatur"
    verbose_name_plural = "🛠️ Reparaturen (Objekt)"
    fields = ('unterhalt_profil', 'datum_info', 'kosten_info', 'detail_link')
    readonly_fields = ('unterhalt_profil', 'datum_info', 'kosten_info', 'detail_link')

    @display(description="Auftrag")
    def unterhalt_profil(self, obj):
        if not obj.pk: return "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-amber-50 text-amber-700 text-sm ring-1 ring-inset ring-amber-600/20">🛠️</div>'
            '<div class="font-bold text-gray-900">{}</div>'
            '</div>', obj.titel
        )

    @display(description="Datum")
    def datum_info(self, obj):
        if not obj.pk or not obj.datum: return "-"
        return format_html('<span class="text-sm text-gray-600">{}</span>', obj.datum.strftime('%d.%m.%Y'))

    @display(description="Kosten")
    def kosten_info(self, obj):
        if not obj.pk: return "-"
        return format_html('<span class="inline-flex items-center rounded-md bg-red-50 px-2 py-1 text-xs font-bold text-red-700 ring-1 ring-inset ring-red-600/10">CHF {:,.2f}</span>', obj.kosten)

    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-amber-600 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 Details</a>', reverse("admin:portfolio_unterhalt_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class SchadenEinheitInline(TabularInline):
    model = SchadenMeldung
    extra = 0
    fk_name = "betroffene_einheit"
    tab = True
    verbose_name = "Schadensmeldung"
    verbose_name_plural = "🎫 Schadensmeldungen (Tickets)"
    fields = ('ticket_profil', 'status_badge', 'detail_link')
    readonly_fields = ('ticket_profil', 'status_badge', 'detail_link')

    @display(description="Ticket")
    def ticket_profil(self, obj):
        if not obj.pk: return "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-rose-50 text-rose-700 text-sm ring-1 ring-inset ring-rose-600/20">🚨</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-[10px] text-gray-500 uppercase">Gemeldet: {}</div></div>'
            '</div>', obj.titel, obj.erstellt_am.strftime('%d.%m.%Y') if obj.erstellt_am else "-"
        )
    @display(description="Status")
    def status_badge(self, obj):
        if not obj.pk: return "-"
        if obj.status == 'erledigt': return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">Erledigt</span>')
        return format_html('<span class="inline-flex items-center rounded-md bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 ring-1 ring-inset ring-rose-600/10">In Bearbeitung</span>')
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-rose-600 hover:text-rose-900 bg-rose-50 hover:bg-rose-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">🎫 Öffnen</a>', reverse("admin:tickets_schadenmeldung_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class DokumentEinheitInline(TabularInline):
    model = Dokument
    extra = 0
    fk_name = "einheit"
    tab = True
    verbose_name = "Dokument"
    verbose_name_plural = "📄 Dokumente & Pläne"
    fields = ('doc_profil', 'detail_link')
    readonly_fields = ('doc_profil', 'detail_link')

    @display(description="Dokument")
    def doc_profil(self, obj):
        if not obj.pk: return "-"
        kategorie = obj.get_kategorie_display() if hasattr(obj, 'get_kategorie_display') else getattr(obj, 'kategorie', '')
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-50 text-indigo-700 text-sm ring-1 ring-inset ring-indigo-600/20">📄</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-[10px] text-gray-500 uppercase">{}</div></div>'
            '</div>', obj.bezeichnung, kategorie
        )
    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">⬇️ Ansehen</a>', reverse("admin:rentals_dokument_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class ZaehlerStandInline(TabularInline):
    model = ZaehlerStand
    extra = 1
    ordering = ('-datum',)
    tab = True

class SchluesselAusgabeInline(TabularInline):
    model = SchluesselAusgabe
    extra = 0
    tab = True


# ==========================================
# 3. LIEGENSCHAFT ADMIN
# ==========================================

@admin.register(Liegenschaft)
class LiegenschaftAdmin(ModelAdmin):
    list_display = ('liegenschaft_profil', 'standort_info', 'portfolio_stats', 'schnell_aktionen')
    search_fields = ('strasse', 'ort', 'egid')
    inlines = [EinheitInline, UnterhaltLiegenschaftInline]

    readonly_fields = ('liegenschaft_full_header',)

    fieldsets = (
        (None, {
            'fields': ('liegenschaft_full_header',),
            'classes': ('map-fieldset',),
        }),
        ('Zuständigkeit & Standort', {
            'fields': (
                ('mandant', 'verwaltung'),
                ('strasse', 'plz', 'ort', 'kanton'),
            )
        }),
        ('Gebäudedaten (GWR)', {
            'fields': (('egid', 'baujahr'), ('kataster_nummer', 'versicherungswert'))
        }),
        ('Finanzen & Abrechnung', {
            'fields': (('bank_name', 'iban'), 'verteilschluessel_text')
        })
    )

    @display(description="")
    def liegenschaft_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-indigo-50 text-indigo-700 rounded-xl font-bold border border-indigo-100">✨ Neue Liegenschaft anlegen</div>')

        einheiten_count = obj.einheiten.count()
        egid = getattr(obj, 'egid', 'Fehlt')
        baujahr = getattr(obj, 'baujahr', '-')

        address_query = urllib.parse.quote(f"{obj.strasse}, {obj.plz} {obj.ort}")
        map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"

        html = f"""
        <style>
            #content-main form > div, form .max-w-5xl, form .max-w-4xl, form .max-w-3xl, form .max-w-2xl {{ max-width: 100% !important; width: 100% !important; }}
            fieldset.map-fieldset {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; border: none !important; background: transparent !important; box-shadow: none !important; grid-column: 1 / -1 !important; }}
            fieldset.map-fieldset > div, fieldset.map-fieldset .form-row {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; margin: 0 !important; border: none !important; }}
            fieldset.map-fieldset label {{ display: none !important; }}
            .master-header-grid {{ display: grid; grid-template-columns: 1fr; gap: 1.5rem; width: 100%; margin-bottom: 2rem; }}
            @media (min-width: 1024px) {{ .master-header-grid {{ grid-template-columns: 350px 1fr; }} }}
        </style>

        <div class="master-header-grid">
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                <div style="background: white; padding: 1.5rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 1rem;">
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #eef2ff; color: #4f46e5; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">🏢</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{obj.strasse}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px;">🏢 Liegenschaft</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px;">📍 {obj.plz} {obj.ort}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Einheiten</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">{einheiten_count}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Baujahr</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">{baujahr}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center; grid-column: span 2;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">EGID</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #4f46e5;">{egid}</span>
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

    @display(description="Liegenschaft", ordering="strasse")
    def liegenschaft_profil(self, obj):
        egid = getattr(obj, 'egid', '')
        egid_html = f'<div class="text-[11px] text-gray-500 mt-0.5">EGID: {egid}</div>' if egid else '<div class="text-[11px] text-amber-500 mt-0.5 font-medium">⚠️ Kein EGID</div>'
        return format_html('<div class="flex items-center gap-3"><div class="flex items-center justify-center w-10 h-10 rounded-xl bg-indigo-100 text-indigo-700 text-xl shadow-sm ring-1 ring-inset ring-indigo-600/10">🏢</div><div><div class="font-bold text-gray-900 leading-tight">{}</div>{}</div></div>', getattr(obj, 'strasse', 'Unbekannt'), mark_safe(egid_html))

    @display(description="Standort", ordering="ort")
    def standort_info(self, obj): return format_html('<span class="text-sm font-medium text-gray-700">{} {}</span>', getattr(obj, 'plz', ''), getattr(obj, 'ort', ''))

    @display(description="Bestand")
    def portfolio_stats(self, obj): return format_html('<span class="inline-flex items-center rounded-md bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 ring-1 ring-inset ring-blue-700/10">{} Einheiten</span>', obj.einheiten.count())

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        edit_url = reverse('admin:portfolio_liegenschaft_change', args=[obj.id])
        qr_url = reverse('hallway_poster', args=[obj.id]) if obj.id else '#'
        return format_html(
            '<div class="flex gap-2">'
            '<a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>'
            '<a href="{}" target="_blank" class="text-emerald-600 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">🖨️ QR Aushang</a>'
            '</div>', edit_url, qr_url
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not get_egid_from_address or not get_units_from_bfs: return
        try:
            if not obj.egid:
                found = get_egid_from_address(obj.strasse, obj.plz, obj.ort)
                if found: obj.egid = found; obj.save(); messages.info(request, f"EGID: {obj.egid}")
            if obj.egid and obj.einheiten.count() == 0:
                data = get_units_from_bfs(obj.egid)
                cnt = 0
                for i in data:
                    if i.get('is_meta'):
                        if i.get('baujahr'): obj.baujahr = i['baujahr']; obj.save()
                        continue
                    Einheit.objects.create(liegenschaft=obj, bezeichnung=i['bezeichnung'], ewid=i['ewid'], zimmer=i['zimmer'], etage=i['etage'], flaeche_m2=i['flaeche'], typ='whg')
                    cnt += 1
                if cnt > 0: messages.success(request, f"GWR: {cnt} Einheiten erstellt.")
        except Exception as e: messages.error(request, f"GWR Fehler: {e}")

# ==========================================
# 4. EINHEIT ADMIN
# ==========================================

@admin.register(Einheit)
class EinheitAdmin(ModelAdmin):
    list_display = ('einheit_profil', 'liegenschaft_info', 'details_info', 'get_status_badge', 'schnell_aktionen')
    list_filter = ('liegenschaft', 'typ'); list_filter_submit = True
    inlines = [MietvertragInline, ZaehlerInline, GeraetInline, UnterhaltEinheitInline, SchadenEinheitInline, DokumentEinheitInline]
    search_fields = ('bezeichnung', 'liegenschaft__strasse')

    readonly_fields = ('einheit_full_header',)

    fieldsets = (
        (None, {
            'fields': ('einheit_full_header',),
            'classes': ('map-fieldset',),
        }),
        ('Basis', {'fields': ('liegenschaft', 'bezeichnung', ('typ', 'ewid'))}),
        ('Details', {'fields': (('etage', 'zimmer'), ('flaeche_m2', 'wertquote'))}),
        ('Finanzen', {'fields': (('nettomiete_aktuell', 'nebenkosten_aktuell'), 'nk_abrechnungsart', ('ref_zinssatz', 'lik_punkte'))})
    )

    @display(description="")
    def einheit_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-teal-50 text-teal-700 rounded-xl font-bold border border-teal-100">✨ Neue Einheit anlegen</div>')

        # Typ und Icon
        typ_display = obj.get_typ_display()
        icon = "🏠" if obj.typ == 'whg' else "🚗" if obj.typ in ['pp', 'gar'] else "🏬" if obj.typ == 'com' else "🚪"

        # Liegenschaft Adresse für Map & Header
        lieg_obj = getattr(obj, 'liegenschaft', None)
        liegenschaft_str = lieg_obj.strasse if lieg_obj else "Keine Liegenschaft"

        # Finanzen
        netto = float(getattr(obj, 'nettomiete_aktuell', 0) or 0)
        nk = float(getattr(obj, 'nebenkosten_aktuell', 0) or 0)
        brutto = netto + nk

        # Details
        zimmer = getattr(obj, 'zimmer', '-')
        flaeche = getattr(obj, 'flaeche_m2', '-')
        etage = getattr(obj, 'etage', '-')

        # Status & Mieter
        aktiver_vertrag = getattr(obj, 'aktiver_vertrag', None)
        if aktiver_vertrag:
            status_text = "Vermietet"
            status_color = "#059669" # Grün
            mieter_info = str(aktiver_vertrag.mieter)
        else:
            status_text = "Leerstand"
            status_color = "#dc2626" # Rot
            mieter_info = "Kein Mieter"

        # Map URL
        if lieg_obj and getattr(lieg_obj, 'strasse', None):
            address_query = urllib.parse.quote(f"{lieg_obj.strasse}, {lieg_obj.plz} {lieg_obj.ort}")
            map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
        else:
            map_url = "https://maps.google.com/maps?q=Selzacherstrasse%204%2C%204512%20Bellach&t=&z=15&ie=UTF8&iwloc=&output=embed"

        # HTML
        html = f"""
        <style>
            #content-main form > div, form .max-w-5xl, form .max-w-4xl, form .max-w-3xl, form .max-w-2xl {{ max-width: 100% !important; width: 100% !important; }}
            fieldset.map-fieldset {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; border: none !important; background: transparent !important; box-shadow: none !important; grid-column: 1 / -1 !important; }}
            fieldset.map-fieldset > div, fieldset.map-fieldset .form-row {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; margin: 0 !important; border: none !important; }}
            fieldset.map-fieldset label {{ display: none !important; }}
            .master-header-grid {{ display: grid; grid-template-columns: 1fr; gap: 1.5rem; width: 100%; margin-bottom: 2rem; }}
            @media (min-width: 1024px) {{ .master-header-grid {{ grid-template-columns: 350px 1fr; }} }}
        </style>

        <div class="master-header-grid">
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                <div style="background: white; padding: 1.5rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 1rem;">
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #f0fdfa; color: #0d9488; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">{icon}</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{obj.bezeichnung}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px;">{icon} {typ_display}</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px;">📍 {liegenschaft_str}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Soll-Miete</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">CHF {brutto:,.0f}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Status</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: {status_color};">{status_text}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center; grid-column: span 2;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Eckdaten & Mieter</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{zimmer} Zi. / {flaeche} m²</span>
                        <span style="font-size: 0.8rem; font-weight: 500; color: #4b5563; margin-top: 4px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">👤 {mieter_info}</span>
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

    @display(description="Mietobjekt", ordering="bezeichnung")
    def einheit_profil(self, obj):
        typ = getattr(obj, 'get_typ_display', lambda: obj.typ)()
        icon = "🏠" if obj.typ == 'whg' else "🚗" if obj.typ in ['pp', 'gar'] else "🏬" if obj.typ == 'com' else "🚪"
        return format_html('<div class="flex items-center gap-3"><div class="flex items-center justify-center w-9 h-9 rounded-xl bg-teal-100 text-teal-700 text-lg shadow-sm ring-1 ring-inset ring-teal-600/10">{}</div><div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">{}</div></div></div>', icon, getattr(obj, 'bezeichnung', 'Unbekannt'), typ)

    @display(description="Liegenschaft", ordering="liegenschaft__strasse")
    def liegenschaft_info(self, obj):
        if obj.liegenschaft: return format_html('<a href="{}" class="text-blue-600 font-medium hover:text-blue-800 transition-colors">📍 {}</a>', reverse('admin:portfolio_liegenschaft_change', args=[obj.liegenschaft.id]), obj.liegenschaft.strasse)
        return "-"

    @display(description="Objekt Details")
    def details_info(self, obj):
        html = '<div class="flex flex-wrap gap-1.5">'
        if getattr(obj, 'zimmer', None): html += f'<span class="inline-flex items-center rounded-md bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-600 ring-1 ring-inset ring-gray-200">{obj.zimmer} Zi.</span>'
        if getattr(obj, 'flaeche_m2', None): html += f'<span class="inline-flex items-center rounded-md bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-600 ring-1 ring-inset ring-gray-200">{obj.flaeche_m2} m²</span>'
        return format_html(html + '</div>' if html != '<div class="flex flex-wrap gap-1.5">' else '<span class="text-xs text-gray-400">-</span>')

    @display(description="Status", label=True)
    def get_status_badge(self, obj):
        return ("Vermietet", "success") if getattr(obj, 'aktiver_vertrag', False) else ("Leerstand", "danger")

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-teal-600 hover:text-teal-900 bg-teal-50 hover:bg-teal-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:portfolio_einheit_change', args=[obj.id]))


# ==========================================
# 5. WEITERE ADMINS (SaaS Upgrade)
# ==========================================

@admin.register(Zaehler)
class ZaehlerAdmin(ModelAdmin):
    list_display = ('zaehler_profil', 'standort_info', 'schnell_aktionen')
    list_filter = ('typ', 'einheit__liegenschaft')
    inlines = [ZaehlerStandInline]

    fieldsets = (
        ('Zähler-Stammdaten', {'fields': ('typ', 'zaehler_nummer', 'standort')}),
        ('Zuweisung', {'fields': ('einheit',)})
    )

    @display(description="Zähler & Typ", ordering="zaehler_nummer")
    def zaehler_profil(self, obj):
        icon = "⚡" if obj.typ == 'strom' else "💧" if obj.typ == 'wasser' else "🔥"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-gray-100 text-gray-700 text-lg shadow-sm">{}</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-xs text-gray-500">Nr: {}</div></div>'
            '</div>', icon, obj.get_typ_display(), obj.zaehler_nummer
        )

    @display(description="Zuweisung")
    def standort_info(self, obj):
        if obj.einheit: return format_html('<span class="text-xs text-gray-600">🏠 {}</span>', obj.einheit.bezeichnung)
        return "-"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-gray-600 hover:text-blue-600 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:portfolio_zaehler_change', args=[obj.id]))

@admin.register(Geraet)
class GeraetAdmin(ModelAdmin):
    list_display = ('geraet_profil', 'garantie_badge', 'schnell_aktionen')
    list_filter = ('einheit__liegenschaft',)

    fieldsets = (
        ('Geräte-Details', {'fields': (('typ', 'marke'), 'modell', ('installations_datum', 'garantie_bis'))}),
        ('Zuweisung', {'fields': ('einheit',)})
    )

    @display(description="Gerät & Marke", ordering="typ")
    def geraet_profil(self, obj):
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-50 text-slate-700 text-sm ring-1 ring-inset ring-slate-600/20">🔌</div>'
            '<div><div class="font-bold text-gray-900">{} {}</div><div class="text-[10px] text-gray-500 uppercase tracking-wide">Modell: {}</div></div>'
            '</div>', getattr(obj, 'marke', ''), getattr(obj, 'typ', ''), getattr(obj, 'modell', '-')
        )

    @display(description="Garantie-Status", label=True)
    def garantie_badge(self, obj):
        from django.utils import timezone
        if obj.garantie_bis:
            if obj.garantie_bis >= timezone.now().date(): return f"Bis {obj.garantie_bis.strftime('%d.%m.%Y')}", "success"
            return "Abgelaufen", "danger"
        return "Unbekannt", "info"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-gray-600 hover:text-blue-600 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:portfolio_geraet_change', args=[obj.id]))

@admin.register(Unterhalt)
class UnterhaltAdmin(ModelAdmin):
    list_display = ('unterhalt_profil', 'kosten_info', 'schnell_aktionen')
    list_filter = ('liegenschaft',)

    fieldsets = (
        ('Arbeiten', {'fields': ('titel', 'datum', 'kosten', 'beleg')}),
        ('Zuweisung', {'fields': ('liegenschaft', 'einheit')})
    )

    @display(description="Unterhalt & Datum", ordering="-datum")
    def unterhalt_profil(self, obj):
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-amber-100 text-amber-700 text-lg shadow-sm">🛠️</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-xs text-gray-500">📅 {}</div></div>'
            '</div>', obj.titel, obj.datum.strftime('%d.%m.%Y')
        )

    @display(description="Kosten")
    def kosten_info(self, obj):
        return format_html('<span class="font-bold text-red-600">CHF {:,.2f}</span>', obj.kosten)

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-amber-600 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:portfolio_unterhalt_change', args=[obj.id]))

@admin.register(Schluessel)
class SchluesselAdmin(ModelAdmin):
    list_display = ('schluessel_profil', 'liegenschaft', 'schnell_aktionen')
    inlines = [SchluesselAusgabeInline]

    fieldsets = (
        ('Schlüssel Details', {'fields': ('liegenschaft', 'schluessel_nummer')}),
    )

    @display(description="Schlüssel-ID", ordering="schluessel_nummer")
    def schluessel_profil(self, obj):
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-zinc-100 text-zinc-700 text-lg shadow-sm">🔑</div>'
            '<div><div class="font-bold text-gray-900">{}</div></div>'
            '</div>', obj.schluessel_nummer
        )

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-zinc-600 hover:text-zinc-900 bg-zinc-50 hover:bg-zinc-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:portfolio_schluessel_change', args=[obj.id]))

@admin.register(SchluesselAusgabe)
class SchluesselAusgabeAdmin(ModelAdmin):
    list_display = ('ausgabe_profil', 'datum_info', 'schnell_aktionen')

    fieldsets = (
        ('Zuweisung', {'fields': ('schluessel', 'mieter', 'handwerker')}),
        ('Zeitraum', {'fields': ('ausgegeben_am', 'rueckgabe_am')})
    )

    @display(description="Schlüssel & Person", ordering="-ausgegeben_am")
    def ausgabe_profil(self, obj):
        person = obj.mieter if obj.mieter else obj.handwerker if obj.handwerker else "Unbekannt"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-zinc-100 text-zinc-700 text-lg shadow-sm">🗝️</div>'
            '<div><div class="font-bold text-gray-900">{}</div><div class="text-xs text-gray-500">Schlüssel: {}</div></div>'
            '</div>', person, obj.schluessel.schluessel_nummer if obj.schluessel else "Unbekannt"
        )

    @display(description="Zeitraum")
    def datum_info(self, obj):
        von = obj.ausgegeben_am.strftime('%d.%m.%Y') if obj.ausgegeben_am else "-"
        bis = obj.rueckgabe_am.strftime('%d.%m.%Y') if obj.rueckgabe_am else "Im Besitz"
        return format_html('<span class="text-sm text-gray-600">{} – {}</span>', von, bis)

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:portfolio_schluesselausgabe_change', args=[obj.id]))