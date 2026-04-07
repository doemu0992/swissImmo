# crm/admin.py
from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Sum
from datetime import date
import urllib.parse

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

    readonly_fields = ('mieter_full_header',)

    fieldsets = (
        (None, {
            'fields': ('mieter_full_header',),
            'classes': ('map-fieldset',),
        }),
        ("Mieterdaten", {
            "fields": ("anrede", "vorname", "nachname", "email", "telefon", "geburtsdatum")
        }),
        ("Adresse", {
            "fields": ("strasse", "plz", "ort")
        }),
    )

    @display(description="")
    def mieter_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-blue-50 text-blue-700 rounded-xl font-bold border border-blue-100">✨ Neuen Mieter anlegen</div>')

        vorname = getattr(obj, 'vorname', '')
        nachname = getattr(obj, 'nachname', '')
        mieter_name = f"{vorname} {nachname}".strip()

        email_val = getattr(obj, 'email', '')
        telefon_val = getattr(obj, 'telefon', '')

        email_html = f'<a href="mailto:{email_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{email_val}</a>' if email_val else '-'
        telefon_html = f'<a href="tel:{telefon_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{telefon_val}</a>' if telefon_val else '-'

        aktive_vertraege = obj.vertraege.filter(aktiv=True)
        anzahl_vertraege = aktive_vertraege.count()

        total_brutto = 0
        for vertrag in aktive_vertraege:
            total_brutto += float(getattr(vertrag, 'netto_mietzins', 0) or 0) + float(getattr(vertrag, 'nebenkosten', 0) or 0)

        heute = date.today()
        aktueller_monat = heute.replace(day=1)
        monat_str = aktueller_monat.strftime('%m/%Y')

        if anzahl_vertraege == 0:
            konto_status = "Kein aktiver Vertrag"
            konto_color = "#6b7280"
            konto_icon = "⏸️"
        else:
            zahlungen_aktuell = 0
            for vertrag in aktive_vertraege:
                z = vertrag.zahlungen.filter(buchungs_monat=aktueller_monat).aggregate(Sum('betrag'))['betrag__sum'] or 0
                zahlungen_aktuell += float(z)

            if zahlungen_aktuell >= total_brutto:
                konto_status = "Alles bezahlt"
                konto_color = "#059669"
                konto_icon = "✅"
            elif zahlungen_aktuell > 0:
                konto_status = f"Teilz. ({zahlungen_aktuell:,.0f})"
                konto_color = "#d97706"
                konto_icon = "⚠️"
            else:
                konto_status = "Offen"
                konto_color = "#dc2626"
                konto_icon = "⏳"

        offene_tickets = SchadenMeldung.objects.filter(gemeldet_von=obj).exclude(status='erledigt').count()
        ticket_color = "#dc2626" if offene_tickets > 0 else "#059669"
        ticket_text = f"{offene_tickets} Tickets" if offene_tickets > 0 else "Keine Probleme"
        ticket_icon = "🚨" if offene_tickets > 0 else "✅"

        if getattr(obj, 'strasse', None) and getattr(obj, 'ort', None):
            address_query = urllib.parse.quote(f"{obj.strasse}, {obj.plz} {obj.ort}")
            map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
        else:
            map_url = "https://maps.google.com/maps?q=Selzacherstrasse%204%2C%204512%20Bellach&t=&z=15&ie=UTF8&iwloc=&output=embed"

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
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #eff6ff; color: #3b82f6; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">👤</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{mieter_name}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">✉️ {email_html}</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">📞 {telefon_html}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Mietobjekte</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">{anzahl_vertraege} Aktiv</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Gesamt-Miete</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">CHF {total_brutto:,.0f}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Konto ({monat_str})</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: {konto_color}; white-space: nowrap;">{konto_icon} {konto_status}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Support</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: {ticket_color}; white-space: nowrap;">{ticket_icon} {ticket_text}</span>
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
        return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:crm_mieter_change', args=[obj.id]))


# ==========================================
# 3. HANDWERKER ADMIN (SaaS-Look: ORANGE)
# ==========================================

@admin.register(Handwerker)
class HandwerkerAdmin(ModelAdmin):
    list_display = ('handwerker_profil', 'kontakt_info', 'standort_info', 'schnell_aktionen')
    search_fields = ('firma', 'gewerk')

    readonly_fields = ('handwerker_full_header',)

    fieldsets = (
        (None, {
            'fields': ('handwerker_full_header',),
            'classes': ('map-fieldset',),
        }),
        ("Handwerker Profil", {
            "fields": ("firma", "gewerk", "email", "telefon", "iban")
        }),
    )

    @display(description="")
    def handwerker_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-orange-50 text-orange-700 rounded-xl font-bold border border-orange-100">✨ Neuen Handwerker anlegen</div>')

        firma = getattr(obj, 'firma', 'Unbekannt')
        gewerk = getattr(obj, 'gewerk', '-')
        iban = getattr(obj, 'iban', '-') or '-'

        email_val = getattr(obj, 'email', '')
        telefon_val = getattr(obj, 'telefon', '')

        email_html = f'<a href="mailto:{email_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{email_val}</a>' if email_val else '-'
        telefon_html = f'<a href="tel:{telefon_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{telefon_val}</a>' if telefon_val else '-'

        icon = "🔧"
        if "sanitär" in str(gewerk).lower(): icon = "💧"
        elif "elektro" in str(gewerk).lower(): icon = "⚡"
        elif "maler" in str(gewerk).lower(): icon = "🎨"

        # Schlüssel prüfen
        schluessel_count = obj.schluesselausgabe_set.filter(rueckgabe_am__isnull=True).count() if hasattr(obj, 'schluesselausgabe_set') else 0
        schluessel_text = f"{schluessel_count} im Besitz" if schluessel_count > 0 else "Keine"
        schluessel_color = "#d97706" if schluessel_count > 0 else "#059669"

        # Map URL (Falls jemals Adresse in DB hinzugefügt wird)
        strasse = getattr(obj, 'strasse', None)
        ort = getattr(obj, 'ort', None)
        plz = getattr(obj, 'plz', None)

        if strasse and ort:
            address_query = urllib.parse.quote(f"{strasse}, {plz or ''} {ort}")
            map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
        else:
            map_url = "https://maps.google.com/maps?q=Selzacherstrasse%204%2C%204512%20Bellach&t=&z=15&ie=UTF8&iwloc=&output=embed"

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
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #fff7ed; color: #ea580c; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">{icon}</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{firma}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">✉️ {email_html}</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">📞 {telefon_html}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Gewerk</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{gewerk}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Schlüssel</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: {schluessel_color}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">🔑 {schluessel_text}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center; grid-column: span 2;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">IBAN</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827; font-family: monospace;">{iban}</span>
                    </div>
                </div>
            </div>

            <div style="width: 100%; height: 100%; min-height: 250px; background-color: #e5e7eb; border-radius: 12px; overflow: hidden; border: 1px solid #d1d5db; box-shadow: 0 1px 3px rgba(0,0,0,0.05); position: relative;">
                <iframe
                    width="100%"
                    height="100%"
                    frameborder="0"
                    style="border:0;"
                    src="{map_url}"
                    allowfullscreen>
                </iframe>
                {'' if strasse else '<div style="position:absolute; top:0; left:0; right:0; bottom:0; display:flex; align-items:center; justify-content:center; background:rgba(243,244,246,0.8); font-weight:bold; color:#6b7280;">Keine Adresse in Datenbank</div>'}
            </div>
        </div>
        """
        return mark_safe(html)

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
        return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:crm_handwerker_change', args=[obj.id]))


# ==========================================
# 4. MANDANTEN ADMIN (SaaS-Look: VIOLETT)
# ==========================================

@admin.register(Mandant)
class MandantAdmin(ModelAdmin):
    list_display = ('mandant_profil', 'kontakt_info', 'standort_info', 'schnell_aktionen')
    search_fields = ('firma_oder_name',)

    readonly_fields = ('mandant_full_header',)

    fieldsets = (
        (None, {
            'fields': ('mandant_full_header',),
            'classes': ('map-fieldset',),
        }),
        ("Mandanten Profil", {
            "fields": ("firma_oder_name", "bank_name", "unterschrift_bild")
        }),
        ("Adresse", {
            "fields": ("strasse", "plz", "ort")
        }),
    )

    @display(description="")
    def mandant_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-purple-50 text-purple-700 rounded-xl font-bold border border-purple-100">✨ Neuen Mandanten anlegen</div>')

        name = getattr(obj, 'firma_oder_name', 'Unbekannt')
        bank = getattr(obj, 'bank_name', '-') or '-'
        strasse = getattr(obj, 'strasse', '')
        plz = getattr(obj, 'plz', '')
        ort = getattr(obj, 'ort', '')

        email_val = getattr(obj, 'email', '')
        telefon_val = getattr(obj, 'telefon', '')

        email_html = f'<a href="mailto:{email_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{email_val}</a>' if email_val else '-'
        telefon_html = f'<a href="tel:{telefon_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{telefon_val}</a>' if telefon_val else '-'

        liegenschaften_count = obj.liegenschaften.count() if hasattr(obj, 'liegenschaften') else 0

        if strasse and ort:
            address_query = urllib.parse.quote(f"{strasse}, {plz} {ort}")
            map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
            map_info = f"📍 {strasse}, {plz} {ort}"
        else:
            map_url = "https://maps.google.com/maps?q=Selzacherstrasse%204%2C%204512%20Bellach&t=&z=15&ie=UTF8&iwloc=&output=embed"
            map_info = "📍 Keine Adresse"

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
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #faf5ff; color: #9333ea; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">🏢</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{name}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">✉️ {email_html}</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">📞 {telefon_html}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Portfolio</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">{liegenschaften_count} Gebäude</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Bank</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{bank}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center; grid-column: span 2;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Hauptsitz</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{map_info}</span>
                    </div>
                </div>
            </div>

            <div style="width: 100%; height: 100%; min-height: 250px; background-color: #e5e7eb; border-radius: 12px; overflow: hidden; border: 1px solid #d1d5db; box-shadow: 0 1px 3px rgba(0,0,0,0.05); position: relative;">
                <iframe
                    width="100%"
                    height="100%"
                    frameborder="0"
                    style="border:0;"
                    src="{map_url}"
                    allowfullscreen>
                </iframe>
                {'' if strasse else '<div style="position:absolute; top:0; left:0; right:0; bottom:0; display:flex; align-items:center; justify-content:center; background:rgba(243,244,246,0.8); font-weight:bold; color:#6b7280;">Keine Adresse hinterlegt</div>'}
            </div>
        </div>
        """
        return mark_safe(html)

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
        return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:crm_mandant_change', args=[obj.id]))


# ==========================================
# 5. VERWALTUNG ADMIN (SaaS-Look: SCHIEFERGRAU)
# ==========================================

@admin.register(Verwaltung)
class VerwaltungAdmin(ModelAdmin):
    list_display = ('firma', 'standort_info', 'get_zins_badge', 'aktueller_lik_punkte')
    actions_detail = ["action_check_rates"]

    readonly_fields = ('verwaltung_full_header',)

    fieldsets = (
        (None, {
            'fields': ('verwaltung_full_header',),
            'classes': ('map-fieldset',),
        }),
        ("Unternehmensdaten", {
            "fields": ("firma", "logo", "telefon", "email")
        }),
        ("Adresse", {
            "fields": ("strasse", "plz", "ort")
        }),
        ("Marktdaten", {
            "fields": ("aktueller_referenzzinssatz", "aktueller_lik_punkte", "letztes_update_marktdaten")
        }),
    )

    @display(description="")
    def verwaltung_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-slate-50 text-slate-700 rounded-xl font-bold border border-slate-100">✨ Neue Verwaltung anlegen</div>')

        firma = getattr(obj, 'firma', 'Unbekannt')
        ref_zins = getattr(obj, 'aktueller_referenzzinssatz', '-')
        lik = getattr(obj, 'aktueller_lik_punkte', '-')

        email_val = getattr(obj, 'email', '')
        telefon_val = getattr(obj, 'telefon', '')

        email_html = f'<a href="mailto:{email_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{email_val}</a>' if email_val else '-'
        telefon_html = f'<a href="tel:{telefon_val}" class="hover:text-blue-600 transition-colors" style="text-decoration: none;">{telefon_val}</a>' if telefon_val else '-'

        strasse = getattr(obj, 'strasse', '')
        plz = getattr(obj, 'plz', '')
        ort = getattr(obj, 'ort', '')

        if strasse and ort:
            address_query = urllib.parse.quote(f"{strasse}, {plz} {ort}")
            map_url = f"https://maps.google.com/maps?q={address_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
            map_info = f"📍 {strasse}, {plz} {ort}"
        else:
            map_url = "https://maps.google.com/maps?q=Selzacherstrasse%204%2C%204512%20Bellach&t=&z=15&ie=UTF8&iwloc=&output=embed"
            map_info = "📍 Keine Adresse"

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
                    <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #f8fafc; color: #475569; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">⚙️</div>
                    <div style="overflow: hidden;">
                        <h2 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{firma}</h2>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">✉️ {email_html}</p>
                        <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">📞 {telefon_html}</p>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Ref-Zins</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">{ref_zins} %</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">LIK</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827;">{lik}</span>
                    </div>
                    <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center; grid-column: span 2;">
                        <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Hauptsitz</span>
                        <span style="font-size: 1.15rem; font-weight: 700; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{map_info}</span>
                    </div>
                </div>
            </div>

            <div style="width: 100%; height: 100%; min-height: 250px; background-color: #e5e7eb; border-radius: 12px; overflow: hidden; border: 1px solid #d1d5db; box-shadow: 0 1px 3px rgba(0,0,0,0.05); position: relative;">
                <iframe
                    width="100%"
                    height="100%"
                    frameborder="0"
                    style="border:0;"
                    src="{map_url}"
                    allowfullscreen>
                </iframe>
                {'' if strasse else '<div style="position:absolute; top:0; left:0; right:0; bottom:0; display:flex; align-items:center; justify-content:center; background:rgba(243,244,246,0.8); font-weight:bold; color:#6b7280;">Keine Adresse hinterlegt</div>'}
            </div>
        </div>
        """
        return mark_safe(html)

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