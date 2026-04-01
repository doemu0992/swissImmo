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
# 1. INLINES (SaaS-Tabs)
# ==========================================

class EinheitInline(TabularInline):
    model = Einheit
    extra = 0
    tab = True
    fields = ('detail_link', 'bezeichnung', 'flaeche_m2', 'nettomiete_aktuell')
    readonly_fields = ('detail_link',)
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" target="_blank" class="text-blue-600 hover:text-blue-900 font-bold">✏️ Öffnen</a>', reverse("admin:portfolio_einheit_change", args=[obj.id]))
        return "-"

class UnterhaltLiegenschaftInline(TabularInline):
    model = Unterhalt
    extra = 0
    tab = True
    verbose_name = "Unterhalt / Reparatur"
    verbose_name_plural = "🛠️ Unterhaltshistorie"
    def get_queryset(self, request):
        return super().get_queryset(request).filter(einheit__isnull=True)

class ZaehlerStandInline(TabularInline): model = ZaehlerStand; extra = 1; ordering = ('-datum',); tab = True
class MietvertragInline(TabularInline): model = Mietvertrag; extra = 0; fields = ('mieter', 'beginn', 'netto_mietzins', 'nebenkosten', 'aktiv'); tab = True
class ZaehlerInline(TabularInline): model = Zaehler; extra = 0; tab=True
class GeraetInline(TabularInline): model = Geraet; extra = 0; tab=True
class UnterhaltEinheitInline(TabularInline): model = Unterhalt; extra = 0; fk_name = "einheit"; tab=True
class DokumentEinheitInline(TabularInline): model = Dokument; extra = 0; fk_name = "einheit"; tab=True
class SchadenEinheitInline(TabularInline): model = SchadenMeldung; extra = 0; fk_name = "betroffene_einheit"; tab=True
class SchluesselAusgabeInline(TabularInline): model = SchluesselAusgabe; extra = 0; tab=True

# ==========================================
# 2. LIEGENSCHAFT ADMIN
# ==========================================

@admin.register(Liegenschaft)
class LiegenschaftAdmin(ModelAdmin):
    list_display = ('liegenschaft_profil', 'standort_info', 'portfolio_stats', 'schnell_aktionen')
    search_fields = ('strasse', 'ort', 'egid')
    inlines = [EinheitInline, UnterhaltLiegenschaftInline]
    class Media: js = ('js/admin_address.js',)

    readonly_fields = ('liegenschaft_full_header',)

    # WICHTIG: Hier haben wir jetzt ein Fieldset NUR für den Header ganz oben
    fieldsets = (
        (None, {
            'fields': ('liegenschaft_full_header',),
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
        # Korrigierte Google Maps URL (Sicherer Embed-Link)
        map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"

        html = f"""
        <div style="display: flex; flex-direction: row; background: white; border-radius: 1rem; overflow: hidden; border: 1px solid #e5e7eb; min-height: 380px; width: 100%; margin-bottom: 1.5rem;">

            <div style="padding: 2rem; border-right: 1px solid #f3f4f6; background-color: #f9fafb; display: flex; flex-direction: column; justify-content: space-between; width: 300px; flex-shrink: 0;">
                <div>
                    <div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem;">
                        <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #eef2ff; color: #4f46e5; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">🏢</div>
                        <div style="overflow: hidden;">
                            <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{obj.strasse}</h2>
                            <p style="font-size: 0.875rem; color: #6b7280; margin: 0;">{obj.plz} {obj.ort}</p>
                        </div>
                    </div>

                    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                        <div style="background: white; padding: 1rem; border-radius: 0.75rem; border: 1px solid #f3f4f6; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                            <span style="font-size: 0.65rem; font-weight: 700; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em;">Einheiten</span>
                            <span style="font-size: 1.125rem; font-weight: 700; color: #111827;">{einheiten_count}</span>
                        </div>
                        <div style="background: white; padding: 1rem; border-radius: 0.75rem; border: 1px solid #f3f4f6; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                            <span style="font-size: 0.65rem; font-weight: 700; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em;">Baujahr</span>
                            <span style="font-size: 1.125rem; font-weight: 700; color: #111827;">{baujahr}</span>
                        </div>
                        <div style="background: white; padding: 1rem; border-radius: 0.75rem; border: 1px solid #f3f4f6; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                            <span style="font-size: 0.65rem; font-weight: 700; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em;">EGID</span>
                            <span style="font-size: 1rem; font-weight: 700; color: #4f46e5;">{egid}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div style="flex-grow: 1; position: relative; background: #f3f4f6;">
                <iframe
                    width="100%"
                    height="100%"
                    frameborder="0"
                    style="border:0; position: absolute; top: 0; left: 0; width: 100%; height: 100%;"
                    src="{map_url}"
                    allowfullscreen>
                </iframe>
            </div>

        </div>
        """
        return mark_safe(html)

    # --- Listenansicht (Unverändert) ---
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
        return format_html('<div class="flex gap-2"><a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a><a href="{}" target="_blank" class="text-emerald-600 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 px-2 py-1 rounded text-xs font-semibold transition-colors">🖨️ QR Aushang</a></div>', edit_url, qr_url)

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
# 3. EINHEIT ADMIN
# ==========================================

@admin.register(Einheit)
class EinheitAdmin(ModelAdmin):
    list_display = ('einheit_profil', 'liegenschaft_info', 'details_info', 'get_status_badge', 'schnell_aktionen')
    list_filter = ('liegenschaft', 'typ'); list_filter_submit = True
    inlines = [MietvertragInline, ZaehlerInline, GeraetInline, UnterhaltEinheitInline, SchadenEinheitInline, DokumentEinheitInline]
    search_fields = ('bezeichnung', 'liegenschaft__strasse')

    fieldsets = (
        ('Basis', {'fields': ('liegenschaft', 'bezeichnung', ('typ', 'ewid'))}),
        ('Details', {'fields': (('etage', 'zimmer'), ('flaeche_m2', 'wertquote'))}),
        ('Finanzen', {'fields': (('nettomiete_aktuell', 'nebenkosten_aktuell'), 'nk_abrechnungsart')})
    )

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
    def get_status_badge(self, obj): return "Vermietet", "success" if obj.aktiver_vertrag else "danger"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj): return format_html('<a href="{}" class="text-teal-600 hover:text-teal-900 bg-teal-50 hover:bg-teal-100 px-2 py-1 rounded text-xs font-semibold transition-colors">Bearbeiten</a>', reverse('admin:portfolio_einheit_change', args=[obj.id]))

# ==========================================
# 4. WEITERE ADMINS
# ==========================================

@admin.register(Zaehler)
class ZaehlerAdmin(ModelAdmin): list_display = ('typ', 'zaehler_nummer', 'einheit'); inlines = [ZaehlerStandInline]
@admin.register(Geraet)
class GeraetAdmin(ModelAdmin): list_display = ('typ', 'marke', 'einheit')
@admin.register(Unterhalt)
class UnterhaltAdmin(ModelAdmin): list_display = ('titel', 'datum', 'kosten')
@admin.register(Schluessel)
class SchluesselAdmin(ModelAdmin): list_display = ('schluessel_nummer', 'liegenschaft'); inlines = [SchluesselAusgabeInline]
admin.site.register(SchluesselAusgabe)