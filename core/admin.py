import requests
from django.contrib import admin
from django.contrib import messages
from django.utils.html import mark_safe, format_html
from django.urls import reverse
from django.db.models import Sum
from .models import *

# --- Inlines ---

class DokumentVertragInline(admin.TabularInline):
    model = Dokument; extra = 0; fk_name = "vertrag"
    fields = ('bezeichnung', 'kategorie', 'datei', 'erstellt_am'); readonly_fields = ('erstellt_am',)
    verbose_name = "Unterschriebener Vertrag / Dokument"; verbose_name_plural = "Zugehörige Dokumente"
    def has_add_permission(self, request, obj): return False

class MietvertragMieterInline(admin.TabularInline): model = Mietvertrag; extra = 0; fk_name = "mieter"; fields = ('einheit', 'beginn', 'aktiv')
class SchluesselMieterInline(admin.TabularInline): model = SchluesselAusgabe; extra = 0; fk_name = "mieter"
class SchadenMieterInline(admin.TabularInline): model = SchadenMeldung; extra = 0; fk_name = "gemeldet_von"
class EinheitInline(admin.TabularInline):
    model = Einheit; extra = 0; fields = ('detail_link', 'bezeichnung', 'etage', 'zimmer', 'flaeche_m2'); readonly_fields = ('detail_link',)
    def detail_link(self, obj): return mark_safe(f'<a href="{reverse("admin:core_einheit_change", args=[obj.id])}" target="_blank">✏️</a>') if obj.id else "-"
class ZaehlerStandInline(admin.TabularInline): model = ZaehlerStand; extra = 1; ordering = ('-datum',)
class NebenkostenBelegInline(admin.TabularInline): model = NebenkostenBeleg; extra = 1

# --- Admins ---

@admin.register(Verwaltung)
class VerwaltungAdmin(admin.ModelAdmin):
    list_display = ('firma', 'ort', 'email')
    fieldsets = (
        ('Firma', {'fields': ('firma', 'strasse', 'plz', 'ort')}),
        ('Kontakt', {'fields': ('telefon', 'email', 'webseite', 'logo')}),
    )

@admin.register(Mandant)
class MandantAdmin(admin.ModelAdmin):
    list_display = ('firma_oder_name', 'ort')
    fieldsets = (
        ('Eigentümer', {'fields': ('firma_oder_name', 'strasse', 'plz', 'ort')}),
        ('Einstellungen', {'fields': ('bank_name', 'unterschrift_bild')}),
    )

@admin.register(Mieter)
class MieterAdmin(admin.ModelAdmin):
    list_display = ('nachname', 'vorname', 'ort', 'telefon', 'email')
    search_fields = ('nachname', 'vorname', 'email')
    inlines = [MietvertragMieterInline, SchluesselMieterInline, SchadenMieterInline]
    fieldsets = (
        ('Person', {'fields': ('anrede', 'vorname', 'nachname', 'geburtsdatum', 'heimatort', 'zivilstand')}),
        ('Aktuelle Adresse (Korrespondenz)', {'fields': ('strasse', 'plz', 'ort')}),
        ('Kontakt', {'fields': ('telefon', 'email')}),
        ('Zweite Partei', {'fields': ('partner_name',), 'description': 'Solidarhafter / Ehepartner'}),
    )

@admin.register(Mietvertrag)
class MietvertragAdmin(admin.ModelAdmin):
    list_display = ('mieter', 'einheit', 'beginn', 'status_colored', 'aktiv', 'pdf_drucken', 'docuseal_btn')
    list_filter = ('sign_status', 'aktiv', 'beginn')
    readonly_fields = ('jotform_submission_id',)
    inlines = [DokumentVertragInline]
    fieldsets = (
        ('Parteien', {'fields': ('mieter', 'einheit')}),
        ('Vertrag', {'fields': ('beginn', 'ende', 'aktiv', 'sign_status')}),
        ('Konditionen', {'fields': ('netto_mietzins', 'nebenkosten', 'kautions_betrag', 'basis_referenzzinssatz', 'basis_lik_punkte')}),
        ('System', {'fields': ('pdf_datei', 'jotform_submission_id')}),
    )

    def status_colored(self, obj):
        color = {'offen': 'gray', 'gesendet': 'orange', 'unterzeichnet': 'green'}.get(obj.sign_status, 'black')
        return mark_safe(f'<span style="color:{color}; font-weight:bold;">{obj.get_sign_status_display()}</span>')
    status_colored.short_description = "Status"

    # --- KORRIGIERTE FUNKTION ---
    def pdf_drucken(self, obj):
        # Hier stand vorher 'vertrag_pdf', das war falsch. Es muss 'generate_pdf' heißen (wie in urls.py).
        return format_html('<a href="{}" target="_blank" class="button">🖨️ PDF</a>', reverse('generate_pdf', args=[obj.id])) if obj.id else "-"
    pdf_drucken.short_description = "Vorschau"
    # ----------------------------

    def docuseal_btn(self, obj):
        if obj.sign_status == 'offen':
            return format_html('<a href="{}" class="button" style="background-color:#447e9b; color:white;">📨 Senden</a>', reverse('send_docuseal', args=[obj.id]))
        elif obj.pdf_datei:
             return format_html('<a href="{}" target="_blank">✅ Signiert</a>', obj.pdf_datei.url)
        return "-"
    docuseal_btn.short_description = "Aktion"

    def get_changeform_initial_data(self, request):
        data = super().get_changeform_initial_data(request)
        if 'einheit' in request.GET:
            try:
                e = Einheit.objects.get(id=request.GET.get('einheit'))
                data.update({'einheit': e, 'netto_mietzins': e.nettomiete_aktuell, 'nebenkosten': e.nebenkosten_aktuell, 'basis_referenzzinssatz': e.ref_zinssatz, 'basis_lik_punkte': e.lik_punkte})
            except: pass
        return data

@admin.register(Einheit)
class EinheitAdmin(admin.ModelAdmin):
    list_display = ('bezeichnung', 'liegenschaft', 'zimmer', 'etage', 'ewid')
    list_filter = ('liegenschaft',); search_fields = ('bezeichnung', 'ewid')
    fieldsets = (('Basis', {'fields': ('liegenschaft', 'bezeichnung', 'typ', 'ewid')}), ('Details', {'fields': ('etage', 'position', 'zimmer', 'flaeche_m2', 'wertquote')}), ('Finanzen', {'fields': ('nettomiete_aktuell', 'nebenkosten_aktuell', 'nk_abrechnungsart', 'ref_zinssatz', 'lik_punkte')}))

@admin.register(Liegenschaft)
class LiegenschaftAdmin(admin.ModelAdmin):
    list_display = ('strasse', 'ort', 'mandant', 'verwaltung')
    inlines = [EinheitInline]
    fieldsets = (
        ('Zuständigkeit', {'fields': ('mandant', 'verwaltung')}),
        ('Standort', {'fields': ('strasse', 'plz', 'ort', 'kanton')}),
        ('Daten', {'fields': ('egid', 'baujahr', 'kataster_nummer', 'versicherungswert')}),
        ('Mietkonto & Abrechnung', {'fields': ('bank_name', 'iban', 'verteilschluessel_text')})
    )

@admin.register(Dokument)
class DokumentAdmin(admin.ModelAdmin):
    list_display = ('bezeichnung', 'kategorie', 'vertrag', 'erstellt_am'); list_filter = ('kategorie',)
    fieldsets = (('Zuordnung', {'fields': ('vertrag', 'liegenschaft', 'mieter')}), ('Datei', {'fields': ('titel', 'kategorie', 'datei')}))

# Weitere einfache Admins
admin.site.register(Leerstand)
admin.site.register(Handwerker)
admin.site.register(Schluessel)
admin.site.register(SchluesselAusgabe)
admin.site.register(SchadenMeldung)
admin.site.register(Unterhalt)
admin.site.register(Geraet)
admin.site.register(Zaehler, list_display=('typ', 'zaehler_nummer', 'einheit'), inlines=[ZaehlerStandInline])
admin.site.register(AbrechnungsPeriode, inlines=[NebenkostenBelegInline], list_display=('bezeichnung', 'liegenschaft', 'start_datum'))
admin.site.register(MietzinsAnpassung)