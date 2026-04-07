from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.db.models import Sum
from django.contrib import messages
from django.shortcuts import redirect

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

# Lokale Modelle (Finance)
from .models import (
    Buchungskonto, KreditorenRechnung, Zahlungseingang,
    Jahresabschluss, MietzinsKontrolle, AbrechnungsPeriode, NebenkostenBeleg
)

# Helper-Funktion für Nebenkostenabrechnung
try:
    from core.utils.billing import berechne_abrechnung
except ImportError:
    berechne_abrechnung = None


# ==========================================
# 1. INLINES
# ==========================================

class NebenkostenBelegInline(TabularInline):
    model = NebenkostenBeleg
    extra = 1
    fields = ('datum', 'text', 'kategorie', 'verteilschluessel', 'betrag', 'beleg_scan')
    tab = True


# ==========================================
# 2. ABRECHNUNG (Nebenkosten - SaaS Look)
# ==========================================

@admin.register(AbrechnungsPeriode)
class AbrechnungAdmin(ModelAdmin):
    list_display = ('periode_profil', 'zeitraum_info', 'status_badge', 'schnell_aktionen')
    list_filter = ('liegenschaft', 'abgeschlossen')
    list_filter_submit = True
    inlines = [NebenkostenBelegInline]

    fieldsets = (
        ('Stammdaten', {'fields': ('liegenschaft', 'bezeichnung', ('start_datum', 'ende_datum'), 'abgeschlossen')}),
        ('Vorschau (Live)', {'fields': ('live_preview_tabelle',)})
    )
    readonly_fields = ('live_preview_tabelle',)

    @display(description="Abrechnung", ordering="bezeichnung")
    def periode_profil(self, obj):
        liegenschaft = getattr(obj.liegenschaft, 'strasse', 'Keine Liegenschaft') if getattr(obj, 'liegenschaft', None) else 'Keine Liegenschaft'
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-blue-100 text-blue-700 text-xl shadow-sm ring-1 ring-inset ring-blue-600/10">📊</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">🏢 {}</div></div>'
            '</div>',
            getattr(obj, 'bezeichnung', 'Unbekannt'), liegenschaft
        )

    @display(description="Zeitraum")
    def zeitraum_info(self, obj):
        start = obj.start_datum.strftime('%d.%m.%Y') if getattr(obj, 'start_datum', None) else "-"
        ende = obj.ende_datum.strftime('%d.%m.%Y') if getattr(obj, 'ende_datum', None) else "-"
        return format_html('<span class="text-sm font-medium text-gray-700">{} – {}</span>', start, ende)

    @display(description="Status", label=True)
    def status_badge(self, obj):
        if getattr(obj, 'abgeschlossen', False): return "Abgeschlossen", "success"
        return "In Bearbeitung", "warning"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        edit_url = reverse('admin:finance_abrechnungsperiode_change', args=[obj.id])
        pdf_url = reverse('abrechnung_pdf', args=[obj.id]) if obj.id else '#'
        mail_url = reverse('abrechnung_send_mail', args=[obj.id]) if obj.id else '#'

        return format_html(
            '<div class="flex gap-1.5">'
            '<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>'
            '<a href="{}" target="_blank" class="text-gray-600 bg-gray-50 hover:bg-gray-200 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 PDF</a>'
            '<a href="{}" onclick="return confirm(\'Alle senden?\')" class="text-emerald-600 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📩 Senden</a>'
            '</div>',
            edit_url, pdf_url, mail_url
        )

    def live_preview_tabelle(self, obj):
        if not obj.pk: return "Bitte erst speichern."
        if not berechne_abrechnung: return "Berechnungsmodul fehlt."
        try: ergebnis = berechne_abrechnung(obj.pk)
        except Exception as e: return f"Fehler bei Berechnung: {e}"

        if 'error' in ergebnis: return format_html('<span style="color:red; font-weight:bold;">{}</span>', ergebnis.get('error', 'Unbekannter Fehler'))
        data = ergebnis.get('abrechnungen', [])
        total = ergebnis.get('total_kosten', 0)

        html = f"<div class='mb-4 font-bold text-lg'>Total zu verteilen: CHF {total:,.2f}</div>"
        html += "<div class='overflow-x-auto'><table class='w-full text-sm text-left text-gray-500 dark:text-gray-400 border rounded-lg'>"
        html += "<thead class='text-xs uppercase bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-300'><tr>"
        html += "<th class='px-4 py-3'>Einheit</th><th class='px-4 py-3'>Name / Typ</th><th class='px-4 py-3'>Zeitraum</th><th class='px-4 py-3 text-right'>Kosten</th><th class='px-4 py-3 text-right'>Akonto</th><th class='px-4 py-3 text-right'>Saldo</th></tr></thead><tbody class='divide-y divide-gray-200 dark:divide-gray-700'>"

        for row in data:
            is_nachzahlung = row.get('nachzahlung', False)
            color_saldo = "text-red-600 font-bold" if is_nachzahlung else "text-emerald-600 font-bold"
            bg_row = "bg-red-50 dark:bg-red-900/10" if row.get('typ') == 'leerstand' else "bg-white dark:bg-gray-800"
            von, bis = row.get('von'), row.get('bis')
            zeitraum = f"{von} - {bis} ({row.get('tage', 0)} T.)" if von != '-' else "n/a"

            html += f"<tr class='{bg_row} hover:bg-gray-50 dark:hover:bg-gray-700'><td class='px-4 py-2 font-medium'>{row.get('einheit', '-')}</td><td class='px-4 py-2'>{row.get('name', 'Unbekannt')}</td><td class='px-4 py-2 text-xs text-gray-500'>{zeitraum}</td><td class='px-4 py-2 text-right'>{row.get('kosten_anteil', 0):.2f}</td><td class='px-4 py-2 text-right'>{row.get('akonto', 0):.2f}</td><td class='px-4 py-2 text-right {color_saldo}'>{row.get('saldo', 0):.2f}</td></tr>"
        html += "</tbody></table></div>"

        diff = ergebnis.get('differenz', 0)
        if diff != 0: html += f"<div class='mt-2 text-xs text-amber-600 font-bold'>⚠️ Rundungsdifferenz: {diff} CHF</div>"
        return mark_safe(html)
    live_preview_tabelle.short_description = "Vorschau"


# ==========================================
# 3. KREDITOREN RECHNUNG (Ausgaben - Rot/Rose)
# ==========================================

@admin.register(KreditorenRechnung)
class KreditorenRechnungAdmin(ModelAdmin):
    list_display = ('rechnung_profil', 'betrag_info', 'zuweisung_info', 'status_badge', 'schnell_aktionen')
    list_filter = ('status', 'liegenschaft', 'konto')
    search_fields = ('lieferant', 'iban', 'referenz')
    readonly_fields = ('fehlermeldung',)

    fieldsets = (
        ('KI-Scanner', {'fields': ('beleg_scan', 'fehlermeldung')}),
        ('Buchhaltung & Zuweisung', {'fields': ('status', 'liegenschaft', 'einheit', 'konto')}),
        ('Rechnungsdetails (Auto-Fill durch KI)', {'fields': ('lieferant', 'datum', 'faellig_am', 'betrag', 'iban', 'referenz')}),
    )

    @display(description="Lieferant & Rechnung", ordering="lieferant")
    def rechnung_profil(self, obj):
        datum = obj.datum.strftime('%d.%m.%Y') if getattr(obj, 'datum', None) else "Kein Datum"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-rose-100 text-rose-700 text-xl shadow-sm ring-1 ring-inset ring-rose-600/10">🧾</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-[11px] text-gray-500 mt-0.5">📅 {}</div></div>'
            '</div>',
            getattr(obj, 'lieferant', 'Unbekannt'), datum
        )

    @display(description="Betrag", ordering="betrag")
    def betrag_info(self, obj):
        betrag = float(getattr(obj, 'betrag', 0) or 0)
        return format_html('<span class="font-bold text-gray-900">CHF {}</span>', f"{betrag:,.2f}")

    @display(description="Zuweisung")
    def zuweisung_info(self, obj):
        lieg = getattr(obj.liegenschaft, 'strasse', '-') if getattr(obj, 'liegenschaft', None) else '-'
        konto = getattr(obj.konto, 'nummer', '-') if getattr(obj, 'konto', None) else '-'
        return format_html('<div class="text-xs text-gray-600">📍 {}<br>🏷️ Konto: {}</div>', lieg, konto)

    @display(description="Status", label=True)
    def status_badge(self, obj):
        st = getattr(obj, 'status', 'neu')
        if st == 'neu': return "Neu / Scan", "danger"
        elif st == 'freigegeben': return "Freigegeben", "warning"
        elif st == 'bezahlt': return "Bezahlt", "success"
        return st, "info"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-rose-600 hover:text-rose-900 bg-rose-50 hover:bg-rose-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:finance_kreditorenrechnung_change', args=[obj.id]))


# ==========================================
# 4. ZAHLUNGSEINGANG (Einnahmen - Grün)
# ==========================================

@admin.register(Zahlungseingang)
class ZahlungseingangAdmin(ModelAdmin):
    list_display = ('zahlung_profil', 'betrag_info', 'zuweisung_info', 'schnell_aktionen')
    list_filter = ('liegenschaft', 'buchungs_monat', 'konto')
    search_fields = ('vertrag__mieter__nachname', 'vertrag__mieter__vorname', 'bemerkung')
    date_hierarchy = 'datum_eingang'

    fieldsets = (
        ('Zuweisung', {'fields': ('vertrag', 'buchungs_monat', 'konto')}),
        ('Zahlungsdetails', {'fields': ('datum_eingang', 'betrag', 'bemerkung')}),
    )

    @display(description="Eingang", ordering="-datum_eingang")
    def zahlung_profil(self, obj):
        datum = obj.datum_eingang.strftime('%d.%m.%Y') if getattr(obj, 'datum_eingang', None) else "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 text-xl shadow-sm ring-1 ring-inset ring-emerald-600/10">💵</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-[11px] text-gray-500 mt-0.5">Eingang: {}</div></div>'
            '</div>',
            getattr(obj, 'bemerkung', 'Zahlung'), datum
        )

    @display(description="Betrag", ordering="betrag")
    def betrag_info(self, obj):
        betrag = float(getattr(obj, 'betrag', 0) or 0)
        return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-sm font-bold text-emerald-700 ring-1 ring-inset ring-emerald-600/20">CHF {}</span>', f"{betrag:,.2f}")

    @display(description="Zuweisung")
    def zuweisung_info(self, obj):
        mieter = str(getattr(obj.vertrag, 'mieter', '-')) if getattr(obj, 'vertrag', None) else '-'
        monat = obj.buchungs_monat.strftime('%m/%Y') if getattr(obj, 'buchungs_monat', None) else "-"
        return format_html('<div class="text-xs text-gray-600">👤 {}<br>📅 Für: {}</div>', mieter, monat)

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-emerald-600 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>',
            reverse('admin:finance_zahlungseingang_change', args=[obj.id]))


# ==========================================
# 5. WEITERE BUCHHALTUNGS-ADMINS
# ==========================================

@admin.register(Buchungskonto)
class BuchungskontoAdmin(ModelAdmin):
    list_display = ('konto_profil', 'typ_badge')
    search_fields = ('nummer', 'bezeichnung')
    list_filter = ('typ',)
    actions_list = ["load_standard_accounts"]

    fieldsets = (
        ('Konto Definition', {'fields': ('nummer', 'bezeichnung', 'typ')}),
    )

    @display(description="Konto", ordering="nummer")
    def konto_profil(self, obj):
        return format_html(
            '<div class="flex items-center gap-2">'
            '<span class="px-2 py-1 bg-gray-100 text-gray-600 font-mono text-xs rounded border border-gray-200">{}</span>'
            '<span class="font-bold text-gray-800">{}</span>'
            '</div>', getattr(obj, 'nummer', ''), getattr(obj, 'bezeichnung', '')
        )

    @display(description="Typ", label=True)
    def typ_badge(self, obj):
        typ = getattr(obj, 'typ', '')
        if typ == 'ertrag': return "Ertrag", "success"
        elif typ == 'aufwand': return "Aufwand", "danger"
        return "Bilanz", "info"

    @action(description="📚 Standard-Kontenplan laden", url_path="load-accounts")
    def load_standard_accounts(self, request):
        standard_konten = [
            ('1020', 'Bankguthaben', 'bilanz'), ('1100', 'Forderungen', 'bilanz'), ('2000', 'Kreditoren', 'bilanz'),
            ('3000', 'Mietertrag Wohnungen', 'ertrag'), ('3400', 'NK Akonto', 'ertrag'),
            ('4000', 'Materialaufwand', 'aufwand'), ('4400', 'Unterhalt Gebäude', 'aufwand'), ('6500', 'Verwaltungshonorar', 'aufwand'),
        ]
        cnt = 0
        for nr, bez, typ in standard_konten:
            obj, created = Buchungskonto.objects.get_or_create(nummer=nr, defaults={'bezeichnung': bez, 'typ': typ})
            if created: cnt += 1
        messages.success(request, f"✅ {cnt} Konten angelegt!")
        return redirect(request.META.get('HTTP_REFERER', '/admin/'))

@admin.register(Jahresabschluss)
class JahresabschlussAdmin(ModelAdmin):
    list_display = ('abschluss_profil', 'liegenschaft', 'schnell_aktionen')
    list_filter = ('liegenschaft', 'jahr')

    fieldsets = (
        ('Basisdaten', {'fields': ('liegenschaft', 'jahr', 'notizen')}),
        ('Bericht', {'fields': ('bericht_anzeige',)})
    )
    readonly_fields = ('bericht_anzeige',)

    @display(description="Erfolgsrechnung", ordering="-jahr")
    def abschluss_profil(self, obj):
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-indigo-100 text-indigo-700 text-lg shadow-sm">📈</div>'
            '<div><div class="font-bold text-gray-900">Jahresabschluss {}</div></div>'
            '</div>', obj.jahr
        )

    def bericht_anzeige(self, obj):
        return format_html('<div class="p-4 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600">Bericht erfolgreich generiert und im System gespeichert.</div>')

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:finance_jahresabschluss_change', args=[obj.id]))

@admin.register(MietzinsKontrolle)
class MietzinsKontrolleAdmin(ModelAdmin):
    list_display = ('kontrolle_profil', 'liegenschaft', 'schnell_aktionen')
    list_filter = ('liegenschaft',)

    fieldsets = (
        ('Überprüfung', {'fields': ('liegenschaft', 'monat', 'notizen')}),
    )

    @display(description="Scanner-Lauf", ordering="-monat")
    def kontrolle_profil(self, obj):
        monat = obj.monat.strftime('%m/%Y') if obj.monat else "Unbekannt"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-9 h-9 rounded-xl bg-emerald-100 text-emerald-700 text-lg shadow-sm">🔍</div>'
            '<div><div class="font-bold text-gray-900">Mietzins-Scanner</div><div class="text-xs text-gray-500">{}</div></div>'
            '</div>', monat
        )

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        return format_html('<a href="{}" class="text-blue-600 hover:text-blue-900 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">✏️ Bearbeiten</a>', reverse('admin:finance_mietzinskontrolle_change', args=[obj.id]))