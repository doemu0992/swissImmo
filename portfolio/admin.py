from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

# Deine Modelle
from .models import Liegenschaft, Einheit, Zaehler, Geraet, Unterhalt, Schluessel

# --- IMPORT GWR LOGIK ---
# Stelle sicher, dass diese Datei und Funktionen in deinem core-Ordner existieren!
try:
    from core.gwr import get_egid_from_address, get_units_from_bfs
except ImportError:
    get_egid_from_address = None
    get_units_from_bfs = None

# ==========================================
# 0. SICHERHEITS-CHECK
# ==========================================
models_to_fix = [Liegenschaft, Einheit, Zaehler, Schluessel, Geraet, Unterhalt]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# ==========================================
# 1. INLINES
# ==========================================

class EinheitInline(TabularInline):
    model = Einheit
    extra = 0
    fields = ('detail_link', 'bezeichnung', 'zimmer', 'etage', 'nettomiete_aktuell')
    readonly_fields = ('detail_link',)
    tab = True

    def detail_link(self, obj):
        if obj.id:
            url = reverse("admin:portfolio_einheit_change", args=[obj.id])
            return format_html('<a href="{}" class="text-primary-600 font-bold">✏️ Öffnen</a>', url)
        return "-"

class UnterhaltInline(TabularInline):
    model = Unterhalt
    extra = 0
    fields = ('titel', 'datum', 'kosten')
    tab = True

# ==========================================
# 2. LIEGENSCHAFT ADMIN (Gebäude)
# ==========================================

@admin.register(Liegenschaft)
class LiegenschaftAdmin(ModelAdmin):
    list_display = ('strasse', 'ort', 'egid', 'get_einheiten_count', 'get_poster_link')
    search_fields = ('strasse', 'ort', 'egid')
    inlines = [EinheitInline, UnterhaltInline]

    fieldsets = (
        ('Mandat & Verwaltung', {
            'fields': ('mandant', 'verwaltung'),
        }),
        ('Standort & Adresse', {
            'fields': (('strasse', 'plz', 'ort'), 'kanton'),
        }),
        ('Technische Daten (GWR)', {
            'fields': (('egid', 'baujahr'), 'kataster_nummer', 'versicherungswert'),
        }),
        ('Zahlungsverbindung', {
            'fields': ('bank_name', 'iban', 'verteilschluessel_text'),
        }),
    )

    # --- HEADER BUTTONS (FAIRWALTER STYLE) ---
    actions_detail = ["action_update_gwr", "action_print_qr_poster"]

    @action(description="🔄 GWR Daten importieren", url_path="update-gwr")
    def action_update_gwr(self, request, object_id):
        obj = self.get_object(request, object_id)

        if not get_egid_from_address or not get_units_from_bfs:
            messages.error(request, "GWR-Modul in 'core.gwr' wurde nicht gefunden.")
            return redirect(request.META.get('HTTP_REFERER'))

        try:
            # 1. EGID suchen falls nicht vorhanden
            if not obj.egid:
                found_egid = get_egid_from_address(obj.strasse, obj.plz, obj.ort)
                if found_egid:
                    obj.egid = found_egid
                    obj.save()
                    messages.info(request, f"EGID {obj.egid} automatisch gefunden.")

            # 2. Einheiten importieren falls EGID vorhanden
            if obj.egid:
                data = get_units_from_bfs(obj.egid)
                cnt = 0
                for item in data:
                    if item.get('is_meta'):
                        if item.get('baujahr'):
                            obj.baujahr = item['baujahr']
                            obj.save()
                        continue

                    # Einheit erstellen falls noch nicht vorhanden (EWID Check)
                    Einheit.objects.get_or_create(
                        liegenschaft=obj,
                        ewid=item.get('ewid'),
                        defaults={
                            'bezeichnung': item.get('bezeichnung'),
                            'zimmer': item.get('zimmer'),
                            'etage': item.get('etage'),
                            'flaeche_m2': item.get('flaeche'),
                            'typ': 'whg'
                        }
                    )
                    cnt += 1
                messages.success(request, f"Erfolgreich: {cnt} Einheiten vom GWR synchronisiert.")
            else:
                messages.warning(request, "Keine EGID gefunden. Bitte Adresse prüfen.")

        except Exception as e:
            messages.error(request, f"Fehler beim GWR-Abruf: {str(e)}")

        return redirect(request.META.get('HTTP_REFERER'))

    @action(description="🖨️ Hausflur-Poster (QR)", url_path="print-poster")
    def action_print_qr_poster(self, request, object_id):
        return redirect(reverse('hallway_poster', args=[object_id]))

    @display(description="Einheiten")
    def get_einheiten_count(self, obj):
        return f"{obj.einheiten.count()} Objekte"

    def get_poster_link(self, obj):
        try:
            url = reverse('hallway_poster', args=[obj.pk])
            return format_html('<a href="{}" target="_blank" class="bg-indigo-100 text-indigo-700 px-2 py-1 rounded text-xs font-bold">🖨️ QR</a>', url)
        except:
            return "-"

# ==========================================
# 3. EINHEIT ADMIN (Wohnungen)
# ==========================================

@admin.register(Einheit)
class EinheitAdmin(ModelAdmin):
    list_display = ('bezeichnung', 'liegenschaft', 'zimmer', 'get_status_badge', 'nettomiete_aktuell')
    list_filter = ('liegenschaft', 'typ')

    fieldsets = (
        ('Basis Informationen', {
            'fields': ('liegenschaft', ('bezeichnung', 'typ'), 'ewid'),
        }),
        ('Objekt-Details', {
            'fields': (('etage', 'zimmer'), ('flaeche_m2', 'wertquote')),
        }),
        ('Mietzins & NK', {
            'fields': (('nettomiete_aktuell', 'nebenkosten_aktuell'), 'nk_abrechnungsart'),
        }),
    )

    @display(description="Status", label=True)
    def get_status_badge(self, obj):
        if hasattr(obj, 'aktiver_vertrag') and obj.aktiver_vertrag:
            return "Vermietet", "success"
        return "Leerstand", "danger"

# ==========================================
# 4. WEITERE MODULE
# ==========================================

@admin.register(Zaehler)
class ZaehlerAdmin(ModelAdmin):
    list_display = ('zaehler_nummer', 'typ', 'einheit', 'liegenschaft')
    list_filter = ('typ', 'liegenschaft')

@admin.register(Schluessel)
class SchluesselAdmin(ModelAdmin):
    list_display = ('schluessel_nummer', 'liegenschaft')

@admin.register(Geraet)
class GeraetAdmin(ModelAdmin):
    list_display = ('typ', 'marke', 'einheit')

@admin.register(Unterhalt)
class UnterhaltAdmin(ModelAdmin):
    list_display = ('titel', 'datum', 'kosten')