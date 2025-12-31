from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Liegenschaft, Einheit, Mieter, Mietvertrag, DokumentVorlage, Schluessel, SchluesselAusgabe, Handwerker, SchadenMeldung

class EinheitInline(admin.TabularInline):
    model = Einheit
    extra = 0

class SchluesselAusgabeInline(admin.TabularInline):
    model = SchluesselAusgabe
    extra = 0

@admin.register(Liegenschaft)
class LiegenschaftAdmin(admin.ModelAdmin):
    inlines = [EinheitInline]
    list_display = ('strasse', 'ort', 'kanton')

@admin.register(Einheit)
class EinheitAdmin(admin.ModelAdmin):
    list_display = ('bezeichnung', 'liegenschaft', 'typ', 'flaeche_m2')

@admin.register(Mieter)
class MieterAdmin(admin.ModelAdmin):
    list_display = ('nachname', 'vorname', 'email')

@admin.register(Mietvertrag)
class MietvertragAdmin(admin.ModelAdmin):
    list_display = ('mieter', 'einheit', 'brutto_display', 'drucken_button')
    def brutto_display(self, obj): return f"CHF {obj.bruttomietzins:.2f}"
    def drucken_button(self, obj):
        url = reverse('pdf_download', args=[obj.id])
        return format_html(f'<a class="button" href="{url}" target="_blank">PDF</a>')

@admin.register(DokumentVorlage)
class VorlageAdmin(admin.ModelAdmin): pass

@admin.register(Schluessel)
class SchluesselAdmin(admin.ModelAdmin):
    list_display = ('schluessel_nummer', 'liegenschaft', 'verfuegbar')
    inlines = [SchluesselAusgabeInline]

@admin.register(SchadenMeldung)
class SchadenAdmin(admin.ModelAdmin):
    list_display = ('betreff', 'status', 'erstellt_am')
    list_filter = ('status',)

@admin.register(Handwerker)
class HandwerkerAdmin(admin.ModelAdmin):
    list_display = ('firmenname', 'branche')
