import requests
from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.db.models import Sum
from .models import *

# ==========================================
# 1. STYLE: ZWEI-SPALTEN LAYOUT
# ==========================================
# Wir fügen hier CSS hinzu, damit das Admin-Formular schön aussieht
# ohne dass wir templates/change_form.html brauchen.

class TwoColumnAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('admin/css/forms.css',)
        }

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        return form

# ==========================================
# 2. INLINES
# ==========================================

class DokumentVertragInline(admin.TabularInline):
    model = Dokument; extra = 0; fk_name = "vertrag"
    fields = ('bezeichnung', 'kategorie', 'datei', 'vorschau_btn', 'erstellt_am'); readonly_fields = ('vorschau_btn', 'erstellt_am')
    verbose_name = "Dokument"; verbose_name_plural = "Zugehörige Dokumente"
    def vorschau_btn(self, obj): return format_html('<a href="{}" target="_blank" class="button" style="background-color:green; color:white; padding: 4px 10px; border-radius: 4px; font-weight:bold; text-decoration:none;">✅ PDF Ansehen</a>', obj.datei.url) if obj.datei else "-"
    vorschau_btn.short_description = "Vorschau"
    def has_add_permission(self, request, obj): return True

class DokumentMieterInline(admin.TabularInline):
    model = Dokument; extra = 0; fk_name = "mieter"
    fields = ('bezeichnung', 'kategorie', 'datei', 'vorschau_btn', 'erstellt_am'); readonly_fields = ('vorschau_btn', 'erstellt_am')
    verbose_name = "Dokument"; verbose_name_plural = "Zugehörige Dokumente (Alle)"
    def vorschau_btn(self, obj): return format_html('<a href="{}" target="_blank" class="button" style="background-color:green; color:white; padding: 4px 10px; border-radius: 4px; font-weight:bold; text-decoration:none;">✅ PDF Ansehen</a>', obj.datei.url) if obj.datei else "-"
    vorschau_btn.short_description = "Vorschau"
    def has_add_permission(self, request, obj): return True

class MietvertragEinheitInline(admin.TabularInline):
    model = Mietvertrag; fk_name = "einheit"
    fields = ('edit_link', 'mieter', 'beginn', 'status_badge', 'aktiv', 'pdf_btn', 'docuseal_btn')
    readonly_fields = ('edit_link', 'mieter', 'beginn', 'status_badge', 'aktiv', 'pdf_btn', 'docuseal_btn')
    verbose_name = "Mietvertrag"; verbose_name_plural = "Mietverträge (Historie & Aktuell)"
    ordering = ('-beginn',); extra = 0; min_num = 0; max_num = 0; can_delete = False; show_change_link = False
    def has_add_permission(self, request, obj): return True

    def edit_link(self, obj):
        css = """<style>.inline-group .tabular td.original, .inline-group .tabular th.original { display: none !important; width: 0 !important; } .inline-group .tabular th.column-edit_link, .inline-group .tabular td.field-edit_link { width: 60px !important; text-align: center !important; } .inline-group .tabular th.column-mieter, .inline-group .tabular td.field-mieter { padding-left: 15px !important; text-align: left !important; } .inline-group .tabular td { vertical-align: middle !important; white-space: nowrap !important; }</style>"""
        if obj and obj.id: return mark_safe(css + f'<a href="{reverse("admin:core_mietvertrag_change", args=[obj.id])}" target="_blank"><b>#{obj.id}</b></a>')
        return "-"
    edit_link.short_description = "ID"

    def status_badge(self, obj):
        if not obj: return "-"
        colors = {'offen': '#999', 'gesendet': '#ffa500', 'unterzeichnet': 'green', 'abgelehnt': 'red'}
        return format_html('<div style="white-space:nowrap;"><span style="color: white; background-color: {}; padding: 4px 8px; border-radius: 4px; font-weight: bold;">{}</span></div>', colors.get(obj.sign_status, 'black'), obj.get_sign_status_display())
    status_badge.short_description = "Status"

    def pdf_btn(self, obj): return format_html('<div style="white-space:nowrap;"><a href="{}" target="_blank" class="button" style="padding: 4px 8px;">📄 Vorschau</a></div>', reverse('generate_pdf', args=[obj.id])) if obj and obj.id else "-"
    pdf_btn.short_description = "PDF"

    def docuseal_btn(self, obj):
        if not obj or not obj.id: return "-"
        div_start = '<div style="white-space:nowrap;">'; div_end = '</div>'
        if obj.sign_status == 'offen': return mark_safe(div_start + format_html('<a href="{}" class="button" style="background-color:#447e9b; color:white; padding: 4px 8px;">📨 Senden</a>', reverse('send_docuseal', args=[obj.id])) + div_end)
        elif obj.sign_status == 'gesendet': return mark_safe(f'{div_start}<span style="color:orange;">⏳ Warten...</span>{div_end}')
        elif obj.pdf_datei: return format_html(f'{div_start}<a href="{{}}" target="_blank" style="color:green; font-weight:bold;">✅ Signiert</a>{div_end}', obj.pdf_datei.url)
        return "-"
    docuseal_btn.short_description = "E-Signing"

class SchadenEinheitInline(admin.TabularInline):
    model = SchadenMeldung; fk_name = "betroffene_einheit"
    fields = ('edit_link', 'titel', 'gemeldet_von', 'prioritaet_badge', 'status_badge', 'foto_preview')
    readonly_fields = ('edit_link', 'titel', 'gemeldet_von', 'prioritaet_badge', 'status_badge', 'foto_preview')
    verbose_name = "Schaden"; verbose_name_plural = "Gemeldete Schäden"
    ordering = ('-erstellt_am',); extra = 0; min_num = 0; max_num = 0; can_delete = False; show_change_link = False
    def has_add_permission(self, request, obj): return True

    def edit_link(self, obj):
        css = """<style>.inline-group .tabular th.column-edit_link, .inline-group .tabular td.field-edit_link { width: 60px !important; text-align: center !important; }</style>"""
        if obj.id: return mark_safe(css + f'<a href="{reverse("admin:core_schadenmeldung_change", args=[obj.id])}" target="_blank"><b>#{obj.id}</b></a>')
        return "-"
    edit_link.short_description = "ID"

    def status_badge(self, obj):
        colors = {'neu': 'red', 'in_bearbeitung': 'orange', 'beauftragt': 'blue', 'erledigt': 'green', 'warte_auf_mieter': 'purple'}
        return format_html('<span style="color:white; background-color:{}; padding:4px 8px; border-radius:4px; font-weight:bold;">{}</span>', colors.get(obj.status, 'grey'), obj.get_status_display())
    status_badge.short_description = "Status"

    def prioritaet_badge(self, obj):
        icons = {'hoch': '🔥 Hoch', 'mittel': '⚡ Mittel', 'niedrig': '💤 Niedrig'}
        return format_html('<span style="{}">{}</span>', 'color:red; font-weight:bold;' if obj.prioritaet == 'hoch' else '', icons.get(obj.prioritaet, obj.prioritaet))
    prioritaet_badge.short_description = "Prio"

    def foto_preview(self, obj): return format_html('<a href="{}" target="_blank"><img src="{}" style="height:30px; border-radius:3px;" /></a>', obj.foto.url, obj.foto.url) if obj.foto else "-"
    foto_preview.short_description = "Foto"

class SchadenMieterInline(admin.TabularInline):
    model = SchadenMeldung; fk_name = "gemeldet_von"
    fields = ('edit_link', 'titel', 'betroffene_einheit', 'prioritaet_badge', 'status_badge', 'erstellt_am')
    readonly_fields = ('edit_link', 'titel', 'betroffene_einheit', 'prioritaet_badge', 'status_badge', 'erstellt_am')
    verbose_name = "Gemeldeter Schaden"; verbose_name_plural = "Gemeldete Schäden"
    extra = 0; min_num = 0; max_num = 0; can_delete = False; show_change_link = False
    def has_add_permission(self, request, obj): return True
    def edit_link(self, obj): return format_html('<a href="{}" target="_blank"><b>#{}</b></a>', reverse("admin:core_schadenmeldung_change", args=[obj.id]), obj.id) if obj.id else "-"
    edit_link.short_description = "ID"
    def status_badge(self, obj): return format_html('<span style="color:white; background-color:{}; padding:4px 8px; border-radius:4px;">{}</span>', {'neu':'red','in_bearbeitung':'orange','beauftragt':'blue','erledigt':'green'}.get(obj.status, 'grey'), obj.get_status_display())
    status_badge.short_description = "Status"
    def prioritaet_badge(self, obj): return {'hoch':'🔥','mittel':'⚡','niedrig':'💤'}.get(obj.prioritaet, '-')
    prioritaet_badge.short_description = "Prio"

class MietvertragMieterInline(admin.TabularInline):
    model = Mietvertrag; extra = 0; fk_name = "mieter"; fields = ('einheit', 'beginn', 'aktiv'); show_change_link = True
class SchluesselMieterInline(admin.TabularInline): model = SchluesselAusgabe; extra = 0; fk_name = "mieter"
class EinheitInline(admin.TabularInline):
    model = Einheit; extra = 0; fields = ('edit_link', 'bezeichnung', 'etage', 'zimmer', 'flaeche_m2'); readonly_fields = ('edit_link',)
    def edit_link(self, obj): return format_html('<a href="{}" target="_blank">✏️</a>', reverse("admin:core_einheit_change", args=[obj.id])) if obj.id else "-"
class ZaehlerStandInline(admin.TabularInline): model = ZaehlerStand; extra = 1; ordering = ('-datum',)
class NebenkostenBelegInline(admin.TabularInline): model = NebenkostenBeleg; extra = 1

# ==========================================
# 3. HAUPT ADMINS
# ==========================================

@admin.register(Verwaltung)
class VerwaltungAdmin(admin.ModelAdmin):
    list_display = ('firma', 'ort', 'email')
    fieldsets = (('Firma', {'fields': ('firma', 'strasse', 'plz', 'ort')}), ('Kontakt', {'fields': ('telefon', 'email', 'webseite', 'logo')}))

@admin.register(Mandant)
class MandantAdmin(admin.ModelAdmin):
    list_display = ('firma_oder_name', 'ort')
    fieldsets = (('Eigentümer', {'fields': ('firma_oder_name', 'strasse', 'plz', 'ort')}), ('Einstellungen', {'fields': ('bank_name', 'unterschrift_bild')}))

@admin.register(Handwerker)
class HandwerkerAdmin(admin.ModelAdmin):
    list_display = ('firma', 'gewerk', 'kontaktperson', 'telefon', 'email')
    search_fields = ('firma', 'gewerk'); list_filter = ('gewerk',)

@admin.register(SchadenMeldung)
class SchadenMeldungAdmin(admin.ModelAdmin):
    list_display = ('id_display', 'titel', 'status_badge', 'prioritaet_badge', 'betroffene_einheit', 'chat_link', 'erstellt_am')
    list_filter = ('status', 'prioritaet', 'zutritt', 'handwerker')
    search_fields = ('titel', 'beschreibung', 'betroffene_einheit__bezeichnung', 'gemeldet_von__nachname')
    readonly_fields = ('erstellt_am', 'foto_gross_preview', 'chat_link_gross')

    # HIER STELLEN WIR DAS LAYOUT WIEDER HER (Feldgruppen)
    fieldsets = (
        ('AKTION (Chat & Status)', {
            'fields': ('chat_link_gross', 'status', 'prioritaet'),
            'classes': ('extrapretty',), # Django CSS Klasse
        }),
        ('MELDUNG', {
            'fields': ('titel', 'beschreibung'),
        }),
        ('KONTAKT (Mieter)', {
            'fields': ('gemeldet_von', 'mieter_email', 'mieter_telefon', 'zutritt'),
        }),
        ('ZUORDNUNG & AUFTRAG', {
            'fields': ('handwerker', 'betroffene_einheit', 'liegenschaft'),
        }),
        ('FOTOS', {
            'fields': ('foto', 'foto_gross_preview'),
        }),
        ('SYSTEM', {
            'fields': ('erstellt_am',),
            'classes': ('collapse',),
        }),
    )

    # DIESES CSS SORGT FÜR EINE BREITERE DARSTELLUNG
    class Media:
        css = {
            'all': ('admin/css/widgets.css',)
        }
        # Wir injizieren hier etwas CSS, um die Blöcke schöner zu machen
        # (Da wir keine Template-Datei mehr nutzen wollen, machen wir es inline-safe)

    def id_display(self, obj): return f"#{obj.id}"
    id_display.short_description = "ID"
    def status_badge(self, obj): return format_html('<span style="color:white; background-color:{}; padding:5px 10px; border-radius:4px; font-weight:bold;">{}</span>', {'neu':'red','in_bearbeitung':'orange','beauftragt':'blue','erledigt':'green','warte_auf_mieter':'purple'}.get(obj.status, 'grey'), obj.get_status_display())
    status_badge.short_description = "Status"
    def prioritaet_badge(self, obj): return format_html('<span style="{}">{}</span>', 'color:red; font-weight:bold;' if obj.prioritaet == 'hoch' else '', {'hoch':'🔥 Hoch','mittel':'⚡ Mittel','niedrig':'💤 Niedrig'}.get(obj.prioritaet, obj.prioritaet))
    prioritaet_badge.short_description = "Prio"
    def foto_gross_preview(self, obj): return format_html('<img src="{}" style="max-height:300px; max-width:100%; border-radius:5px;" />', obj.foto.url) if obj.foto else "Kein Foto"
    foto_gross_preview.short_description = "Vorschau"
    def chat_link(self, obj): return format_html('<a href="{}" class="button" style="background-color:#28a745; color:white; padding: 4px 10px; border-radius: 4px; font-weight:bold;">💬 Zum Chat</a>', reverse('ticket_detail_admin', args=[obj.pk]))
    chat_link.short_description = "Kommunikation"

    def chat_link_gross(self, obj):
        url = reverse('ticket_detail_admin', args=[obj.pk])
        # Hier machen wir den Button schön groß und auffällig
        return format_html(
            '<div style="background:#e9f7ef; padding:15px; border-left:5px solid #28a745; margin-bottom:10px;">'
            '<h3 style="margin-top:0; color:#28a745;">🚀 Ticket bearbeiten</h3>'
            '<p style="margin-bottom:10px;">Hier klicken, um mit dem Mieter zu chatten und Nachrichten zu sehen.</p>'
            '<a href="{}" style="background-color:#28a745; color:white; padding: 10px 20px; border-radius: 4px; font-weight:bold; font-size:14px; text-decoration:none; display:inline-block;">💬 Chat öffnen</a>'
            '</div>',
            url
        )
    chat_link_gross.short_description = "Aktion"

@admin.register(Mieter)
class MieterAdmin(admin.ModelAdmin):
    list_display = ('nachname', 'vorname', 'ort', 'telefon', 'email')
    search_fields = ('nachname', 'vorname', 'email'); list_filter = ('ort',)
    inlines = [MietvertragMieterInline, DokumentMieterInline, SchadenMieterInline, SchluesselMieterInline]
    fieldsets = (('Person', {'fields': ('anrede', 'vorname', 'nachname', 'geburtsdatum', 'heimatort', 'zivilstand')}), ('Adresse', {'fields': ('strasse', 'plz', 'ort')}), ('Kontakt', {'fields': ('telefon', 'email')}), ('Zweite Partei', {'fields': ('partner_name',)}))

@admin.register(Mietvertrag)
class MietvertragAdmin(admin.ModelAdmin):
    list_display = ('id', 'mieter', 'einheit', 'beginn', 'status_badge', 'aktiv', 'pdf_vorschau_btn', 'docuseal_action_btn')
    list_filter = ('sign_status', 'aktiv', 'beginn'); search_fields = ('mieter__nachname', 'einheit__bezeichnung')
    readonly_fields = ('jotform_submission_id',); inlines = [DokumentVertragInline]
    fieldsets = (('Parteien', {'fields': ('mieter', 'einheit')}), ('Vertrag', {'fields': ('beginn', 'ende', 'aktiv', 'sign_status')}), ('Konditionen', {'fields': ('netto_mietzins', 'nebenkosten', 'kautions_betrag', 'basis_referenzzinssatz', 'basis_lik_punkte')}), ('System / DocuSeal', {'fields': ('pdf_datei', 'jotform_submission_id')}))
    def status_badge(self, obj): return format_html('<span style="color: white; background-color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold;">{}</span>', {'offen':'#999','gesendet':'#ffa500','unterzeichnet':'green','abgelehnt':'red'}.get(obj.sign_status, 'black'), obj.get_sign_status_display())
    status_badge.short_description = "Status"
    def pdf_vorschau_btn(self, obj): return format_html('<a href="{}" target="_blank" class="button" style="padding: 5px 10px;">📄 Vorschau</a>', reverse('generate_pdf', args=[obj.id])) if obj.id else "-"
    pdf_vorschau_btn.short_description = "PDF"
    def docuseal_action_btn(self, obj):
        if obj.sign_status == 'offen': return format_html('<a href="{}" class="button" style="background-color:#447e9b; color:white; padding: 5px 10px;">📨 Via DocuSeal senden</a>', reverse('send_docuseal', args=[obj.id]))
        elif obj.sign_status == 'gesendet': return format_html('<span style="color:orange;">⏳ Warten...</span>')
        elif obj.pdf_datei: return format_html('<a href="{}" target="_blank" style="color:green; font-weight:bold;">✅ PDF Ansehen</a>', obj.pdf_datei.url)
        return "-"
    docuseal_action_btn.short_description = "E-Signing"
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
    list_display = ('bezeichnung', 'liegenschaft', 'typ', 'zimmer', 'etage', 'status_text')
    list_filter = ('liegenschaft', 'typ'); search_fields = ('bezeichnung', 'ewid')
    inlines = [MietvertragEinheitInline, SchadenEinheitInline]
    fieldsets = (('Basis', {'fields': ('liegenschaft', 'bezeichnung', 'typ', 'ewid')}), ('Details', {'fields': ('etage', 'position', 'zimmer', 'flaeche_m2', 'wertquote')}), ('Finanzen (Soll)', {'fields': ('nettomiete_aktuell', 'nebenkosten_aktuell', 'nk_abrechnungsart', 'ref_zinssatz', 'lik_punkte')}))
    def status_text(self, obj): return format_html('<span style="color:green;">Vermietet</span>') if obj.aktiver_vertrag else format_html('<span style="color:red;">Leerstand</span>')
    status_text.short_description = "Status"

@admin.register(Liegenschaft)
class LiegenschaftAdmin(admin.ModelAdmin):
    list_display = ('strasse', 'ort', 'mandant', 'einheiten_count'); inlines = [EinheitInline]
    fieldsets = (('Zuständigkeit', {'fields': ('mandant', 'verwaltung')}), ('Standort', {'fields': ('strasse', 'plz', 'ort', 'kanton')}), ('Daten', {'fields': ('egid', 'baujahr', 'kataster_nummer', 'versicherungswert')}), ('Mietkonto & Abrechnung', {'fields': ('bank_name', 'iban', 'verteilschluessel_text')}))
    def einheiten_count(self, obj): return obj.einheiten.count()

@admin.register(Dokument)
class DokumentAdmin(admin.ModelAdmin):
    list_display = ('bezeichnung', 'kategorie', 'vertrag', 'erstellt_am'); list_filter = ('kategorie', 'erstellt_am'); date_hierarchy = 'erstellt_am'
    fieldsets = (('Zuordnung', {'fields': ('vertrag', 'liegenschaft', 'mieter')}), ('Datei', {'fields': ('titel', 'kategorie', 'datei')}))

# ==========================================
# 3. EINFACHE REGISTRIERUNGEN
# ==========================================
admin.site.register(Leerstand); admin.site.register(Schluessel)
admin.site.register(SchluesselAusgabe); admin.site.register(Unterhalt)
admin.site.register(Geraet); admin.site.register(Zaehler, list_display=('typ', 'zaehler_nummer', 'einheit'), inlines=[ZaehlerStandInline])
admin.site.register(AbrechnungsPeriode, inlines=[NebenkostenBelegInline]); admin.site.register(MietzinsAnpassung)