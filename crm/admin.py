from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages

# Unfold Imports
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

# Deine Modelle
from .models import Verwaltung, Mandant, Mieter, Handwerker

# Helper-Funktion für die Marktdaten (falls vorhanden)
try:
    from core.utils.market_data import update_verwaltung_rates
except ImportError:
    update_verwaltung_rates = None

# ==========================================
# 0. SICHERHEITS-CHECK (Bereinigung für PythonAnywhere)
# ==========================================
models_to_fix = [Verwaltung, Mandant, Mieter, Handwerker]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# ==========================================
# 1. MIETER ADMIN
# ==========================================

@admin.register(Mieter)
class MieterAdmin(ModelAdmin):
    list_display = ('nachname', 'vorname', 'ort', 'telefon', 'email', 'kontakt_button')
    search_fields = ('nachname', 'vorname', 'email')

    # Karten-Layout (Fairwalter Style)
    fieldsets = (
        ('Persönliche Daten', {
            'fields': (('anrede', 'geburtsdatum'), ('vorname', 'nachname')),
        }),
        ('Wohnadresse', {
            'fields': ('strasse', ('plz', 'ort')),
        }),
        ('Kontaktdaten', {
            'fields': (('telefon', 'email'),),
        }),
    )

    def kontakt_button(self, obj):
        if obj.email:
            return format_html('<a href="mailto:{}" class="text-blue-600 font-bold">✉️ Mail</a>', obj.email)
        elif obj.telefon:
            return format_html('<a href="tel:{}" class="text-emerald-600 font-bold">📞 Anrufen</a>', obj.telefon)
        return "-"
    kontakt_button.short_description = "Kontakt"

# ==========================================
# 2. HANDWERKER ADMIN
# ==========================================

@admin.register(Handwerker)
class HandwerkerAdmin(ModelAdmin):
    list_display = ('firma', 'get_gewerk_badge', 'ort', 'telefon', 'email')
    search_fields = ('firma', 'gewerk', 'ort')
    list_filter = ('gewerk',)

    fieldsets = (
        ('Unternehmensprofil', {
            'fields': (('firma', 'gewerk'),),
        }),
        ('Adresse', {
            'fields': ('strasse', ('plz', 'ort')),
        }),
        ('Kontaktdaten', {
            'fields': (('telefon', 'email'),),
        }),
    )

    @display(description="Kategorie / Gewerk", label=True)
    def get_gewerk_badge(self, obj):
        # Zeigt das Gewerk als blauen Badge an
        return obj.gewerk, "info"

# ==========================================
# 3. EIGENE VERWALTUNG ADMIN (Systemeinstellungen)
# ==========================================

@admin.register(Verwaltung)
class VerwaltungAdmin(ModelAdmin):
    list_display = ('firma', 'ort', 'get_zins_badge', 'aktueller_lik_punkte')

    fieldsets = (
        ('Stammdaten der Verwaltung', {
            'fields': ('firma', 'logo', ('strasse', 'plz', 'ort')),
        }),
        ('Gesetzliche Marktdaten (Mietrecht)', {
            'fields': (('aktueller_referenzzinssatz', 'aktueller_lik_punkte'),),
        }),
    )

    # --- HEADER BUTTON ---
    actions_detail = ["action_check_rates"]

    @action(description="🔄 Marktdaten prüfen (BfS)", url_path="check-rates")
    def action_check_rates(self, request, object_id):
        if not update_verwaltung_rates:
            messages.error(request, "Das Modul 'update_verwaltung_rates' wurde nicht gefunden.")
            return redirect(request.META.get('HTTP_REFERER'))

        msg, err = update_verwaltung_rates()
        if err:
            messages.error(request, f"Fehler beim Abruf: {err}")
        else:
            messages.success(request, f"Erfolg: {msg}")

        return redirect(request.META.get('HTTP_REFERER'))

    @display(description="Referenzzinssatz", label=True)
    def get_zins_badge(self, obj):
        if obj.aktueller_referenzzinssatz:
            return f"{obj.aktueller_referenzzinssatz} %", "success"
        return "Fehlt", "danger"

# ==========================================
# 4. MANDANTEN ADMIN (Eigentümer)
# ==========================================

@admin.register(Mandant)
class MandantAdmin(ModelAdmin):
    list_display = ('firma_oder_name', 'ort', 'telefon', 'email')
    search_fields = ('firma_oder_name', 'ort')

    fieldsets = (
        ('Stammdaten', {
            'fields': ('firma_oder_name',),
        }),
        ('Adresse', {
            'fields': ('strasse', ('plz', 'ort')),
        }),
        ('Kontaktdaten', {
            'fields': (('telefon', 'email'),),
        }),
    )