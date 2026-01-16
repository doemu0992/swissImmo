import requests
from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.db.models import Sum

# Import der Hilfsfunktionen aus utils.py
from core.utils import get_egid_from_address, get_units_from_bfs

from .models import (
    Liegenschaft, Einheit, Mieter, Mietvertrag,
    Handwerker, SchadenMeldung, Schluessel, SchluesselAusgabe,
    Dokument, MietzinsAnpassung, Geraet, Unterhalt,
    Zaehler, ZaehlerStand, AbrechnungsPeriode, NebenkostenBeleg,
    Verwaltung, Mandant, Leerstand, TicketNachricht
)

# ==========================================
# 1. STYLE & HELPER
# ==========================================

class TwoColumnAdmin(admin.ModelAdmin):
    class Media:
        css = { 'all': ('admin/css/forms.css',) }

# ==========================================
# 2. INLINES
# ==========================================

class NebenkostenBelegInline(admin.TabularInline):
    model = NebenkostenBeleg; extra = 1
    fields = ('datum', 'text', 'kategorie', 'verteilschluessel', 'betrag', 'beleg_scan')

class ZaehlerStandInline(admin.TabularInline):
    model = ZaehlerStand; extra = 1; ordering = ('-datum',)

class EinheitInline(admin.TabularInline):
    model = Einheit; extra = 0
    fields = ('detail_link', 'bezeichnung', 'flaeche_m2', 'nettomiete_aktuell')
    readonly_fields = ('detail_link',)
    def detail_link(self, obj):
        return format_html('<a href="{}" target="_blank">✏️</a>', reverse("admin:core_einheit_change", args=[obj.id])) if obj.id else "-"

class MietvertragInline(admin.TabularInline):
    model = Mietvertrag; extra = 0
    fields = ('mieter', 'beginn', 'netto_mietzins', 'aktiv')

class DokumentVertragInline(admin.TabularInline):
    model = Dokument; extra = 0; fk_name = "vertrag"
    fields = ('bezeichnung', 'kategorie', 'datei', 'vorschau_btn'); readonly_fields = ('vorschau_btn',)
    def vorschau_btn(self, obj): return format_html('<a href="{}" target="_blank" class="button" style="background:green; color:white; padding:2px 5px;">PDF</a>', obj.datei.url) if obj.datei else "-"

class TicketNachrichtInline(admin.TabularInline):
    model = TicketNachricht; extra = 1; fk_name = "ticket"
    fields = ('absender_name', 'nachricht', 'datei', 'erstellt_am'); readonly_fields = ('erstellt_am',)

# Einfache Inlines
class MietvertragMieterInline(admin.TabularInline): model = Mietvertrag; extra = 0; fk_name = "mieter"; show_change_link = True
class SchluesselMieterInline(admin.TabularInline): model = SchluesselAusgabe; extra = 0; fk_name = "mieter"
class SchadenMieterInline(admin.TabularInline): model = SchadenMeldung; extra = 0; fk_name = "gemeldet_von"
class ZaehlerInline(admin.TabularInline): model = Zaehler; extra = 0
class GeraetInline(admin.TabularInline): model = Geraet; extra = 0
class UnterhaltEinheitInline(admin.TabularInline): model = Unterhalt; extra = 0; fk_name = "einheit"
class UnterhaltLiegenschaftInline(admin.TabularInline):
    model = Unterhalt; extra = 0
    def get_queryset(self, request): return super().get_queryset(request).filter(einheit__isnull=True)
class DokumentEinheitInline(admin.TabularInline): model = Dokument; extra = 0; fk_name = "einheit"
class SchadenEinheitInline(admin.TabularInline): model = SchadenMeldung; extra = 0; fk_name = "betroffene_einheit"
class DokumentMieterInline(admin.TabularInline): model = Dokument; extra = 0; fk_name = "mieter"
class SchluesselAusgabeInline(admin.TabularInline): model = SchluesselAusgabe; extra = 0

# ==========================================
# 3. HAUPT ADMINS
# ==========================================

@admin.register(AbrechnungsPeriode)
class AbrechnungAdmin(admin.ModelAdmin):
    inlines = [NebenkostenBelegInline]
    list_display = ('bezeichnung', 'liegenschaft', 'start_datum', 'abgeschlossen', 'pdf_button')
    list_filter = ('liegenschaft', 'abgeschlossen')
    actions = ['periode_abschliessen', 'periode_oeffnen']

    fieldsets = (
        ('Stammdaten', {'fields': ('liegenschaft', 'bezeichnung', ('start_datum', 'ende_datum'), 'abgeschlossen')}),
        ('Vorschau', {'fields': ('live_preview_tabelle',)})
    )
    readonly_fields = ('live_preview_tabelle',)

    def pdf_button(self, obj):
        return format_html('<a href="{}" class="button" target="_blank">📄 PDF</a>', reverse('abrechnung_pdf', args=[obj.pk])) if obj.pk else "-"

    def live_preview_tabelle(self, obj):
        if not obj.pk: return "Bitte erst speichern."
        if hasattr(obj, 'generiere_abrechnung_preview'):
            try:
                data = obj.generiere_abrechnung_preview()
                html = "<table style='width:100%'><thead><tr style='text-align:left'><th>Einheit</th><th>Kosten</th><th>Akonto</th><th>Saldo</th></tr></thead><tbody>"
                for row in data:
                    color = "green" if row['saldo'] >= 0 else "red"
                    html += f"<tr><td>{row['unit']}</td><td>{row['kosten']:.2f}</td><td>{row['akonto']:.2f}</td><td style='color:{color}'><b>{row['saldo']:.2f}</b></td></tr>"
                return mark_safe(html + "</tbody></table>")
            except Exception as e: return f"Fehler in Vorschau: {e}"
        return "Keine Vorschau-Logik im Modell gefunden."

    def periode_abschliessen(self, request, queryset): queryset.update(abgeschlossen=True)
    def periode_oeffnen(self, request, queryset): queryset.update(abgeschlossen=False)

@admin.register(Liegenschaft)
class LiegenschaftAdmin(admin.ModelAdmin):
    list_display = ('strasse', 'ort', 'egid', 'einheiten_count', 'baujahr')
    search_fields = ('strasse', 'ort', 'egid')
    inlines = [EinheitInline, UnterhaltLiegenschaftInline]

    class Media:
        js = ('js/admin_address.js',)
        css = {'all': ('admin/css/forms.css',)}

    fieldsets = (
        ('Zuständigkeit', {'fields': ('mandant', 'verwaltung')}),
        ('Standort', {'fields': ('strasse', 'plz', 'ort', 'kanton')}),
        ('Daten', {'fields': ('egid', 'baujahr', 'kataster_nummer', 'versicherungswert')}),
        ('Mietkonto & Abrechnung', {'fields': ('bank_name', 'iban', 'verteilschluessel_text')})
    )

    def einheiten_count(self, obj): return obj.einheiten.count()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        try:
            if not obj.egid:
                found = get_egid_from_address(obj.strasse, obj.plz, obj.ort)
                if found:
                    obj.egid = found
                    obj.save()
                    messages.info(request, f"EGID automatisch gefunden: {obj.egid}")

            if obj.egid and obj.einheiten.count() == 0:
                data_list = get_units_from_bfs(obj.egid)
                created_count = 0
                baujahr_gefunden = None

                for item in data_list:
                    if item.get('is_meta'):
                        if item.get('baujahr'):
                            baujahr_gefunden = item['baujahr']
                        continue

                    Einheit.objects.create(
                        liegenschaft=obj,
                        bezeichnung=item['bezeichnung'],
                        ewid=item['ewid'],
                        zimmer=item['zimmer'],
                        etage=item['etage'],
                        flaeche_m2=item['flaeche'],
                        typ='whg'
                    )
                    created_count += 1

                if baujahr_gefunden:
                    obj.baujahr = baujahr_gefunden
                    obj.save()
                    messages.info(request, f"Baujahr {baujahr_gefunden} übernommen.")

                if created_count > 0:
                    messages.success(request, f"GWR (Plan B): {created_count} Einheiten importiert.")
                elif not change:
                    messages.warning(request, "GWR: Keine Wohnungsanzahl gefunden.")

        except Exception as e:
            messages.error(request, f"Import Fehler: {e}")

@admin.register(Einheit)
class EinheitAdmin(admin.ModelAdmin):
    list_display = ('bezeichnung', 'liegenschaft', 'typ', 'zimmer', 'etage', 'status_text')
    list_filter = ('liegenschaft', 'typ'); search_fields = ('bezeichnung', 'ewid')
    inlines = [MietvertragInline, ZaehlerInline, GeraetInline, UnterhaltEinheitInline, SchadenEinheitInline, DokumentEinheitInline]

    fieldsets = (
        ('Basis', {'fields': ('liegenschaft', 'bezeichnung', 'typ', 'ewid')}),
        ('Details', {'fields': (('etage', 'zimmer'), 'flaeche_m2', 'wertquote')}),
        ('Finanzen', {'fields': ('nettomiete_aktuell', 'nebenkosten_aktuell', 'nk_abrechnungsart')})
    )
    def status_text(self, obj): return format_html('<span style="color:green;">Vermietet</span>') if obj.aktiver_vertrag else format_html('<span style="color:red;">Leerstand</span>')

# ==========================================
# WICHTIG: Hier sind die reparierten Buttons!
# ==========================================
@admin.register(Mietvertrag)
class MietvertragAdmin(admin.ModelAdmin):
    # Jetzt wieder mit Status, PDF und DocuSeal-Buttons
    list_display = ('mieter', 'einheit', 'beginn', 'status_badge', 'aktiv', 'pdf_vorschau_btn', 'docuseal_action_btn')
    list_filter = ('sign_status', 'aktiv')
    inlines = [DokumentVertragInline]

    fieldsets = (
        ('Parteien', {'fields': ('mieter', 'einheit')}),
        ('Vertrag', {'fields': ('beginn', 'ende', 'aktiv', 'sign_status')}),
        ('Konditionen', {'fields': ('netto_mietzins', 'nebenkosten', 'kautions_betrag', 'basis_referenzzinssatz')}),
        ('DocuSeal', {'fields': ('pdf_datei',)})
    )

    # Bunter Status-Badge
    def status_badge(self, obj):
        colors = {'offen': '#999', 'gesendet': 'orange', 'unterzeichnet': 'green'}
        return format_html('<span style="color:white; background-color:{}; padding:3px 8px; border-radius:4px;">{}</span>', colors.get(obj.sign_status, 'black'), obj.get_sign_status_display())
    status_badge.short_description = "Status"

    # PDF Button
    def pdf_vorschau_btn(self, obj):
        if obj.id:
            return format_html('<a href="{}" target="_blank" class="button">PDF Vorschau</a>', reverse('generate_pdf', args=[obj.id]))
        return "-"
    pdf_vorschau_btn.short_description = "PDF"

    # DocuSeal Button
    def docuseal_action_btn(self, obj):
        if obj.sign_status == 'offen':
            return format_html('<a href="{}" class="button" style="background:#447e9b; color:white;">Senden</a>', reverse('send_docuseal', args=[obj.id]))
        elif obj.sign_status == 'gesendet':
            return format_html('<span style="color:orange;">Warten auf Unterschrift...</span>')
        elif obj.pdf_datei:
            return format_html('<a href="{}" target="_blank" style="color:green; font-weight:bold;">✅ Signiert</a>', obj.pdf_datei.url)
        return "-"
    docuseal_action_btn.short_description = "E-Signing"

@admin.register(SchadenMeldung)
class SchadenMeldungAdmin(admin.ModelAdmin):
    list_display = ('titel', 'status', 'prioritaet', 'betroffene_einheit')
    list_filter = ('status', 'prioritaet')
    inlines = [TicketNachrichtInline]

    fieldsets = (
        ('Status', {'fields': ('status', 'prioritaet')}),
        ('Meldung', {'fields': ('titel', 'beschreibung', 'gemeldet_von', 'betroffene_einheit')}),
        ('Medien', {'fields': ('foto',)})
    )

@admin.register(Mieter)
class MieterAdmin(admin.ModelAdmin):
    list_display = ('nachname', 'vorname', 'ort', 'telefon', 'email')
    search_fields = ('nachname', 'vorname', 'email'); list_filter = ('ort',)
    inlines = [MietvertragMieterInline, DokumentMieterInline, SchadenMieterInline, SchluesselMieterInline]

    fieldsets = (
        ('Person', {'fields': ('anrede', 'vorname', 'nachname', 'geburtsdatum', 'heimatort', 'nationalitaet', 'ahv_nummer', 'zivilstand')}),
        ('Adresse', {'fields': ('strasse', 'plz', 'ort')}),
        ('Kontakt', {'fields': ('telefon', 'email')}),
        ('Zweite Partei', {'fields': ('partner_name',)})
    )

@admin.register(Verwaltung)
class VerwaltungAdmin(admin.ModelAdmin):
    list_display = ('firma', 'ort')

@admin.register(Mandant)
class MandantAdmin(admin.ModelAdmin):
    list_display = ('firma_oder_name', 'ort')

@admin.register(Handwerker)
class HandwerkerAdmin(admin.ModelAdmin):
    list_display = ('firma', 'gewerk')

@admin.register(Dokument)
class DokumentAdmin(admin.ModelAdmin):
    list_display = ('titel', 'kategorie', 'vertrag')
    list_filter = ('kategorie',)

@admin.register(Zaehler)
class ZaehlerAdmin(admin.ModelAdmin):
    list_display = ('typ', 'zaehler_nummer', 'einheit')
    inlines = [ZaehlerStandInline]

@admin.register(Geraet)
class GeraetAdmin(admin.ModelAdmin):
    list_display = ('typ', 'marke', 'einheit')

@admin.register(Unterhalt)
class UnterhaltAdmin(admin.ModelAdmin):
    list_display = ('titel', 'datum', 'kosten')

@admin.register(Schluessel)
class SchluesselAdmin(admin.ModelAdmin):
    list_display = ('schluessel_nummer', 'liegenschaft')
    inlines = [SchluesselAusgabeInline]

@admin.register(MietzinsAnpassung)
class MietzinsAnpassungAdmin(admin.ModelAdmin):
    pass

admin.site.register(Leerstand)
admin.site.register(SchluesselAusgabe)