import json
from decimal import Decimal
from django import forms
from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.db.models import Sum
from django.template.defaultfilters import date as _date
from django.forms.widgets import TextInput
from django.shortcuts import redirect

# --- IMPORTS FÜR EMAIL ---
from django.core.mail import EmailMessage
from django.conf import settings

# --- UNFOLD IMPORT ---
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.decorators import action

# --- EIGENE IMPORTS ---
from core.gwr import get_egid_from_address, get_units_from_bfs
from core.utils.market_data import update_verwaltung_rates
from core.utils.billing import berechne_abrechnung
from core.utils.email_service import send_handyman_notification
from core.mietrecht_logic import berechne_mietpotenzial

from .models import (
    Liegenschaft, Einheit, Mieter, Mietvertrag,
    Handwerker, SchadenMeldung, Schluessel, SchluesselAusgabe,
    Dokument, MietzinsAnpassung, Geraet, Unterhalt,
    Zaehler, ZaehlerStand, AbrechnungsPeriode, NebenkostenBeleg,
    Verwaltung, Mandant, Leerstand, TicketNachricht,
    HandwerkerAuftrag,
    # --- SAUBERER IMPORT FÜR BUCHHALTUNG ---
    Buchungskonto, KreditorenRechnung, Zahlungseingang, Jahresabschluss, MietzinsKontrolle
)

# ==========================================
# 0. WIDGET FÜR CC-FELD
# ==========================================
class UnfoldDatalistWidget(TextInput):
    def __init__(self, data_list=None, name=None, attrs=None, *args, **kwargs):
        unfold_style = (
            "border block w-full max-w-2xl px-3 py-2 text-sm rounded-md shadow-sm "
            "focus:ring focus:ring-primary-300 focus:border-primary-600 "
            "border-gray-200 bg-white text-gray-500 "
            "dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400 dark:focus:border-primary-600"
        )
        default_attrs = {'class': unfold_style}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs, *args, **kwargs)
        self._name = name
        self._list = data_list or []
        self.attrs.update({'list': f'list__{self._name}', 'autocomplete': 'off'})

    def render(self, name, value, attrs=None, renderer=None):
        text_html = super().render(name, value, attrs, renderer)
        data_list_id = f'list__{self._name}'
        options = ''
        for email, label in self._list:
            if email:
                options += f'<option value="{email}">{label}</option>'
        datalist_html = f'<datalist id="{data_list_id}">{options}</datalist>'
        return mark_safe(text_html + datalist_html)

# ==========================================
# 1. INLINES
# ==========================================

class NebenkostenBelegInline(TabularInline):
    model = NebenkostenBeleg; extra = 1
    fields = ('datum', 'text', 'kategorie', 'verteilschluessel', 'betrag', 'beleg_scan')
    tab = True

class ZaehlerStandInline(TabularInline):
    model = ZaehlerStand; extra = 1; ordering = ('-datum',)
    tab = True

class EinheitInline(TabularInline):
    model = Einheit; extra = 0
    fields = ('detail_link', 'bezeichnung', 'flaeche_m2', 'nettomiete_aktuell')
    readonly_fields = ('detail_link',)
    tab = True
    def detail_link(self, obj):
        return format_html('<a href="{}" target="_blank" class="text-blue-600 hover:text-blue-900">✏️</a>', reverse("admin:core_einheit_change", args=[obj.id])) if obj.id else "-"

class MietvertragInline(TabularInline):
    model = Mietvertrag; extra = 0
    fields = ('mieter', 'beginn', 'netto_mietzins', 'nebenkosten', 'aktiv')
    tab = True

class DokumentVertragInline(TabularInline):
    model = Dokument; extra = 0; fk_name = "vertrag"
    fields = ('bezeichnung', 'kategorie', 'datei', 'vorschau_btn'); readonly_fields = ('vorschau_btn',)
    tab = True
    def vorschau_btn(self, obj): return format_html('<a href="{}" target="_blank" style="color:green; font-weight:bold;">PDF</a>', obj.datei.url) if obj.datei else "-"

class HandwerkerAuftragInline(TabularInline):
    model = HandwerkerAuftrag
    extra = 0
    fields = ('handwerker', 'status', 'bemerkung', 'beauftragt_am')
    readonly_fields = ('beauftragt_am',)
    tab = True
    verbose_name = "Beauftragter Handwerker"
    verbose_name_plural = "🛠️ Beauftragte Handwerker / Aufträge"

# ==========================================
# 2. CHAT SYSTEM (MIT TIMELINE)
# ==========================================

class TicketHistoryInline(StackedInline):
    model = TicketNachricht
    extra = 0
    fk_name = "ticket"
    tab = True
    verbose_name = "Eintrag"
    verbose_name_plural = "📜 Verlauf & Historie"
    fields = ('timeline_entry',)
    readonly_fields = ('timeline_entry',)

    def timeline_entry(self, obj):
        if obj.typ == 'system':
            icon, bg_color = "⚙️", "bg-gray-50 border-gray-200 dark:bg-gray-800 dark:border-gray-700"
            title = f"System: {obj.absender_name}"
        elif obj.typ == 'mail_antwort':
            icon, bg_color = "📩", "bg-white border-l-4 border-l-yellow-400 border-gray-200 shadow-sm dark:bg-gray-800"
            title = f"Von: {obj.absender_name} (E-Mail)"
        elif obj.typ == 'antwort_senden':
            icon, bg_color = "📤", "bg-blue-50 border-blue-200 shadow-sm dark:bg-blue-900/20"
            title = f"Gesendet an Melder: {obj.absender_name}"
        elif obj.typ == 'handwerker_mail':
            icon, bg_color = "🔨", "bg-orange-50 border-orange-200 shadow-sm dark:bg-orange-900/20"
            hw_name = obj.empfaenger_handwerker.firma if obj.empfaenger_handwerker else obj.absender_name
            title = f"Gesendet an Handwerker: {hw_name}"
        else:
            icon, bg_color = "📝", "bg-yellow-50 border-yellow-200 shadow-sm dark:bg-yellow-900/20"
            title = f"Interne Notiz: {obj.absender_name}"

        date_str = _date(obj.erstellt_am, "d.m.Y H:i")
        THRESHOLD, unique_id = 300, f"msg_{obj.id}"

        if len(obj.nachricht) > THRESHOLD:
            nachricht_html = f'<div id="{unique_id}" style="max-height: 80px; overflow: hidden; white-space: pre-wrap;">{obj.nachricht}</div>' \
                             f'<div id="btn_{unique_id}" onclick="var el=document.getElementById(\'{unique_id}\'); if(el.style.maxHeight!==\'none\'){{el.style.maxHeight=\'none\'; this.innerHTML=\'🔼 Weniger\';}}else{{el.style.maxHeight=\'80px\'; this.innerHTML=\'🔽 Mehr\';}}" class="mt-2 text-blue-600 text-xs cursor-pointer font-bold">🔽 Mehr anzeigen</div>'
        else:
            nachricht_html = f'<div style="white-space: pre-wrap;">{obj.nachricht}</div>'

        html = f'<div class="{bg_color} rounded-lg border p-4 text-sm mb-4"><div class="flex justify-between border-b pb-2 mb-2"><b>{icon} {title}</b><span class="text-xs">{date_str}</span></div>{nachricht_html}'
        if obj.datei: html += f'<div class="mt-2 pt-2 border-t"><a href="{obj.datei.url}" target="_blank" class="text-blue-600">📎 Anhang</a></div>'
        return mark_safe(html + "</div>")

    timeline_entry.short_description = "Inhalt"
    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class TicketInputInline(StackedInline):
    model = TicketNachricht; extra = 1; fk_name = "ticket"; tab = True
    verbose_name_plural = "✏️ Neue Nachricht / E-Mail verfassen"
    fields = ('typ', 'empfaenger_handwerker', 'cc_email', 'nachricht', 'datei')
    class Media: js = ('js/admin_ticket_logic.js',)
    def get_queryset(self, request): return super().get_queryset(request).none()
    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if obj:
            suggestions = []
            if obj.email_melder: suggestions.append((obj.email_melder, f"Melder: {obj.email_melder}"))
            for a in obj.handwerker_auftraege.all():
                if a.handwerker.email: suggestions.append((a.handwerker.email, f"HW: {a.handwerker.firma}"))
            formset.form.base_fields['cc_email'].widget = UnfoldDatalistWidget(data_list=suggestions, name='cc_list')
        return formset
    def has_add_permission(self, request, obj=None): return True
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

# ==========================================
# 3. EINFACHE INLINES
# ==========================================
class MietvertragMieterInline(TabularInline): model = Mietvertrag; extra = 0; fk_name = "mieter"; show_change_link = True; tab=True
class SchluesselMieterInline(TabularInline): model = SchluesselAusgabe; extra = 0; fk_name = "mieter"; tab=True
class SchadenMieterInline(TabularInline): model = SchadenMeldung; extra = 0; fk_name = "gemeldet_von"; tab=True
class ZaehlerInline(TabularInline): model = Zaehler; extra = 0; tab=True
class GeraetInline(TabularInline): model = Geraet; extra = 0; tab=True
class UnterhaltEinheitInline(TabularInline): model = Unterhalt; extra = 0; fk_name = "einheit"; tab=True
class UnterhaltLiegenschaftInline(TabularInline):
    model = Unterhalt; extra = 0; tab = True
    def get_queryset(self, request): return super().get_queryset(request).filter(einheit__isnull=True)
class DokumentEinheitInline(TabularInline): model = Dokument; extra = 0; fk_name = "einheit"; tab=True
class SchadenEinheitInline(TabularInline): model = SchadenMeldung; extra = 0; fk_name = "betroffene_einheit"; tab=True
class DokumentMieterInline(TabularInline): model = Dokument; extra = 0; fk_name = "mieter"; tab=True
class SchluesselAusgabeInline(TabularInline): model = SchluesselAusgabe; extra = 0; tab=True

# ==========================================
# 4. HAUPT ADMINS
# ==========================================

@admin.register(AbrechnungsPeriode)
class AbrechnungAdmin(ModelAdmin):
    inlines = [NebenkostenBelegInline]
    list_display = ('bezeichnung', 'liegenschaft', 'start_datum', 'abgeschlossen', 'pdf_button', 'email_button')
    list_filter = ('liegenschaft', 'abgeschlossen'); list_filter_submit = True

    fieldsets = (
        ('Stammdaten', {'fields': ('liegenschaft', 'bezeichnung', ('start_datum', 'ende_datum'), 'abgeschlossen')}),
        ('Vorschau (Live)', {'fields': ('live_preview_tabelle',)})
    )
    readonly_fields = ('live_preview_tabelle',)

    def pdf_button(self, obj): return format_html('<a href="{}" class="bg-blue-600 text-white px-2 py-1 rounded text-xs" target="_blank">📄 PDF</a>', reverse('abrechnung_pdf', args=[obj.pk])) if obj.pk else "-"
    def email_button(self, obj): return format_html('<a href="{}" class="bg-emerald-600 text-white px-2 py-1 rounded text-xs" onclick="return confirm(\'Alle senden?\')">📩 Senden</a>', reverse('abrechnung_send_mail', args=[obj.pk])) if obj.pk else "-"

    def live_preview_tabelle(self, obj):
        if not obj.pk: return "Bitte erst speichern."
        try: ergebnis = berechne_abrechnung(obj.pk)
        except Exception as e: return f"Fehler bei Berechnung: {e}"

        if 'error' in ergebnis: return format_html('<span style="color:red; font-weight:bold;">{}</span>', ergebnis.get('error', 'Unbekannter Fehler'))

        data = ergebnis.get('abrechnungen', [])
        total = ergebnis.get('total_kosten', 0)

        html = f"<div class='mb-4 font-bold text-lg'>Total zu verteilen: CHF {total:,.2f}</div>"
        html += "<div class='overflow-x-auto'><table class='w-full text-sm text-left text-gray-500 dark:text-gray-400 border rounded-lg'>"
        html += "<thead class='text-xs uppercase bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-300'><tr>"
        html += "<th class='px-4 py-3'>Einheit</th>"
        html += "<th class='px-4 py-3'>Name / Typ</th>"
        html += "<th class='px-4 py-3'>Zeitraum</th>"
        html += "<th class='px-4 py-3 text-right'>Kosten</th>"
        html += "<th class='px-4 py-3 text-right'>Akonto</th>"
        html += "<th class='px-4 py-3 text-right'>Saldo</th>"
        html += "</tr></thead><tbody class='divide-y divide-gray-200 dark:divide-gray-700'>"

        for row in data:
            is_nachzahlung = row.get('nachzahlung', False)
            color_saldo = "text-red-600 font-bold" if is_nachzahlung else "text-emerald-600 font-bold"
            bg_row = "bg-red-50 dark:bg-red-900/10" if row.get('typ') == 'leerstand' else "bg-white dark:bg-gray-800"

            von = row.get('von')
            bis = row.get('bis')
            zeitraum = f"{von} - {bis} ({row.get('tage', 0)} Tage)" if von != '-' else "n/a"

            html += f"<tr class='{bg_row} hover:bg-gray-50 dark:hover:bg-gray-700'>"
            html += f"<td class='px-4 py-2 font-medium'>{row.get('einheit', '-')}</td>"
            html += f"<td class='px-4 py-2'>{row.get('name', 'Unbekannt')}</td>"
            html += f"<td class='px-4 py-2 text-xs text-gray-500'>{zeitraum}</td>"
            html += f"<td class='px-4 py-2 text-right'>{row.get('kosten_anteil', 0):.2f}</td>"
            html += f"<td class='px-4 py-2 text-right'>{row.get('akonto', 0):.2f}</td>"
            html += f"<td class='px-4 py-2 text-right {color_saldo}'>{row.get('saldo', 0):.2f}</td>"
            html += "</tr>"

        html += "</tbody></table></div>"

        diff = ergebnis.get('differenz', 0)
        if diff != 0:
             html += f"<div class='mt-2 text-xs text-amber-600 font-bold'>⚠️ Rundungsdifferenz: {diff} CHF</div>"

        return mark_safe(html)

    live_preview_tabelle.short_description = "Vorschau"

@admin.register(Liegenschaft)
class LiegenschaftAdmin(ModelAdmin):
    list_display = ('strasse', 'ort', 'egid', 'einheiten_count', 'poster_button')
    search_fields = ('strasse', 'ort', 'egid')
    inlines = [EinheitInline, UnterhaltLiegenschaftInline]
    class Media: js = ('js/admin_address.js',)

    fieldsets = (('Zuständigkeit', {'fields': ('mandant', 'verwaltung')}), ('Standort', {'fields': ('strasse', 'plz', 'ort', 'kanton')}), ('Daten', {'fields': ('egid', 'baujahr', 'kataster_nummer', 'versicherungswert')}), ('Mietkonto & Abrechnung', {'fields': ('bank_name', 'iban', 'verteilschluessel_text')}))

    def einheiten_count(self, obj): return obj.einheiten.count()
    def poster_button(self, obj): return format_html('<a href="{}" target="_blank" class="bg-indigo-600 text-white px-2 py-1 rounded text-xs">🖨️ QR</a>', reverse('hallway_poster', args=[obj.pk])) if obj.pk else "-"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
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

@admin.register(Einheit)
class EinheitAdmin(ModelAdmin):
    list_display = ('bezeichnung', 'liegenschaft', 'typ', 'zimmer', 'status_text')
    list_filter = ('liegenschaft', 'typ'); list_filter_submit = True
    inlines = [MietvertragInline, ZaehlerInline, GeraetInline, UnterhaltEinheitInline, SchadenEinheitInline, DokumentEinheitInline]
    fieldsets = (('Basis', {'fields': ('liegenschaft', 'bezeichnung', 'typ', 'ewid')}), ('Details', {'fields': (('etage', 'zimmer'), 'flaeche_m2', 'wertquote')}), ('Finanzen', {'fields': ('nettomiete_aktuell', 'nebenkosten_aktuell', 'nk_abrechnungsart')}))

    def status_text(self, obj): return format_html('<span class="bg-green-100 text-green-800 text-xs px-2 py-0.5 rounded">Vermietet</span>') if obj.aktiver_vertrag else format_html('<span class="bg-red-100 text-red-800 text-xs px-2 py-0.5 rounded">Leerstand</span>')

@admin.register(Mietvertrag)
class MietvertragAdmin(ModelAdmin):
    list_display = ('mieter', 'einheit', 'beginn', 'netto_mietzins', 'status_badge_display', 'potenzial_preview', 'aktiv', 'pdf_vorschau_btn', 'qr_rechnung_btn', 'docuseal_action_btn', 'calc_btn')
    list_filter = ('sign_status', 'aktiv'); list_filter_submit = True
    inlines = [DokumentVertragInline]
    fieldsets = (('Parteien', {'fields': ('mieter', 'einheit')}), ('Vertrag', {'fields': ('beginn', 'ende', 'aktiv', 'sign_status')}), ('Konditionen', {'fields': ('netto_mietzins', 'nebenkosten', 'kautions_betrag', 'basis_referenzzinssatz', 'basis_lik_punkte')}), ('DocuSeal', {'fields': ('pdf_datei',)}))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.sign_status == 'unterzeichnet' and obj.pdf_datei:
            exists = Dokument.objects.filter(vertrag=obj, kategorie='vertrag').exists()
            if not exists:
                Dokument.objects.create(titel=f"Mietvertrag {obj.mieter}", kategorie='vertrag', vertrag=obj, mieter=obj.mieter, einheit=obj.einheit, datei=obj.pdf_datei)
                messages.success(request, "✅ Vertrag archiviert.")

    def status_badge_display(self, obj):
        colors = {'offen': 'bg-gray-100', 'gesendet': 'bg-yellow-50', 'unterzeichnet': 'bg-green-50'}
        return format_html('<span class="px-2 py-1 rounded text-xs font-bold {}">{}</span>', colors.get(obj.sign_status, 'bg-gray-100'), obj.get_sign_status_display())
    status_badge_display.short_description = "Status"

    def potenzial_preview(self, obj):
        v = Verwaltung.objects.first()
        if not v: return "-"
        res = berechne_mietpotenzial(obj, v.aktueller_referenzzinssatz, v.aktueller_lik_punkte)
        if not res: return "-"
        color = "bg-green-100 text-green-800" if res['action'] == 'UP' else "bg-red-100 text-red-800"
        return format_html('<span class="{} px-2 py-1 rounded text-xs font-bold">{} CHF</span>', color, res['delta_chf'])
    potenzial_preview.short_description = "Potenzial"

    def docuseal_action_btn(self, obj):
        if obj.sign_status == 'offen': return format_html('<a href="{}" class="bg-blue-600 text-white px-2 py-1 rounded text-xs">✍️ Senden</a>', reverse('send_docuseal', args=[obj.id]))
        elif obj.pdf_datei: return format_html('<a href="{}" target="_blank" class="text-emerald-600 font-bold text-xs">📄 Öffnen</a>', obj.pdf_datei.url)
        return "-"
    docuseal_action_btn.short_description = "DocuSeal"

    def get_changeform_initial_data(self, request):
        i = super().get_changeform_initial_data(request)
        try: v = Verwaltung.objects.first(); i['basis_referenzzinssatz'] = v.aktueller_referenzzinssatz; i['basis_lik_punkte'] = v.aktueller_lik_punkte
        except: pass
        return i

    def pdf_vorschau_btn(self, obj): return format_html('<a href="{}" target="_blank">📄</a>', reverse('generate_pdf', args=[obj.id])) if obj.id else "-"

    def qr_rechnung_btn(self, obj):
        if not obj.id: return "-"
        try:
            url = reverse('generate_qr', args=[obj.id])
            import datetime
            aktueller_monat = datetime.date.today().strftime('%m/%Y')
            js_onclick = f"var m=prompt('Für welchen Monat soll die QR-Rechnung erstellt werden? (MM/YYYY)', '{aktueller_monat}'); if(m){{ window.open('{url}?monat=' + encodeURIComponent(m), '_blank'); }} return false;"
            return format_html('<a href="#" onclick="{}" class="bg-indigo-100 text-indigo-800 px-2 py-1 rounded text-xs font-bold border border-indigo-300">🔳 QR</a>', js_onclick)
        except Exception:
            return "URL fehlt"
    qr_rechnung_btn.short_description = "QR-Schein"

    def calc_btn(self, obj): return format_html('<a href="{}" target="_blank" class="text-indigo-600 font-bold">Zins</a>', reverse('mietzins_anpassung', args=[obj.id])) if obj.aktiv else "-"

@admin.register(SchadenMeldung)
class SchadenMeldungAdmin(ModelAdmin):
    list_display = ('id_status_badge', 'titel', 'status', 'prioritaet', 'handwerker_count_preview', 'erstellt_am')
    list_display_links = ('id_status_badge', 'titel')
    list_filter = ('status', 'prioritaet'); list_filter_submit = True
    inlines = [HandwerkerAuftragInline, TicketHistoryInline, TicketInputInline]
    fieldsets = (('Status', {'fields': ('status', 'prioritaet', 'gelesen')}), ('Meldung', {'fields': ('titel', 'beschreibung', 'foto')}), ('Kontakt Melder', {'fields': ('gemeldet_von', 'email_melder', 'tel_melder', 'betroffene_einheit')}))
    readonly_fields = ('erstellt_am',)

    def id_status_badge(self, obj):
        ungelesene = obj.nachrichten.filter(gelesen=False).exclude(typ='system').exists()
        if not obj.gelesen or ungelesene:
            return format_html(
                '<div style="display:flex; align-items:center;">'
                '<span style="height:10px; width:10px; background-color:#ef4444; border-radius:50%; display:inline-block; margin-right:8px;"></span>'
                '<span>#{}</span>'
                '</div>',
                obj.id
            )
        return f"#{obj.id}"
    id_status_badge.short_description = "ID"

    def handwerker_count_preview(self, obj):
        cnt = obj.handwerker_auftraege.count()
        return f"{cnt} beauftragt" if cnt > 0 else "-"

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if object_id:
            try:
                ticket = SchadenMeldung.objects.get(pk=object_id)
                if not ticket.gelesen: ticket.gelesen = True; ticket.save()
                ticket.nachrichten.filter(gelesen=False).exclude(typ='system').update(gelesen=True)
            except: pass
        return super().change_view(request, object_id, form_url, extra_context)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, HandwerkerAuftrag):
                if instance.pk is None:
                    instance.save()
                    TicketNachricht.objects.create(ticket=instance.ticket, absender_name="System", typ='system', nachricht=f"Handwerker '{instance.handwerker.firma}' beauftragt.")
                    if instance.ticket.email_melder: send_handyman_notification(instance)
                instance.save()
            elif isinstance(instance, TicketNachricht):
                if instance.pk is None:
                    cc_list = [e.strip() for e in instance.cc_email.split(',')] if instance.cc_email else []
                    if instance.typ == 'antwort_senden':
                        empfaenger = instance.ticket.email_melder or (instance.ticket.gemeldet_von.email if instance.ticket.gemeldet_von else None)
                        if empfaenger:
                            EmailMessage(subject=f"Re: Ticket #{instance.ticket.id}", body=f"{instance.nachricht}\n\n--\nVerwaltung", from_email='reply@immoswiss.app', to=[empfaenger], cc=cc_list, reply_to=['reply@immoswiss.app']).send(fail_silently=True)
                            instance.absender_name = "Verwaltung (Gesendet)"; instance.gelesen = True
                    elif instance.typ == 'handwerker_mail' and instance.empfaenger_handwerker and instance.empfaenger_handwerker.email:
                        EmailMessage(subject=f"Ticket #{instance.ticket.id}", body=f"{instance.nachricht}\n\n--\nVerwaltung", from_email='reply@immoswiss.app', to=[instance.empfaenger_handwerker.email], cc=cc_list, reply_to=['reply@immoswiss.app']).send(fail_silently=True)
                        instance.absender_name = f"Verwaltung (an {instance.empfaenger_handwerker.firma})"; instance.gelesen = True
                instance.save()
        formset.save_m2m()

@admin.register(Mieter)
class MieterAdmin(ModelAdmin):
    list_display = ('nachname', 'vorname', 'ort', 'telefon', 'email')
    inlines = [MietvertragMieterInline, DokumentMieterInline, SchadenMieterInline, SchluesselMieterInline]
    fieldsets = (('Person', {'fields': ('anrede', 'vorname', 'nachname', 'geburtsdatum')}), ('Adresse', {'fields': ('strasse', 'plz', 'ort')}), ('Kontakt', {'fields': ('telefon', 'email')}))

@admin.register(Verwaltung)
class VerwaltungAdmin(ModelAdmin):
    list_display = ('firma', 'aktueller_referenzzinssatz', 'aktueller_lik_punkte')
    actions_detail = ["check_rates_now"]
    fieldsets = (('Stammdaten', {'fields': ('firma', 'strasse', 'plz', 'ort', 'logo')}), ('Marktdaten', {'fields': ('aktueller_referenzzinssatz', 'aktueller_lik_punkte')}))

    @action(description="🔄 Marktdaten prüfen", url_path="check-rates")
    def check_rates_now(self, request, object_id=None, **kwargs):
        msg, err = update_verwaltung_rates()
        if err: messages.error(request, f"Fehler: {err}")
        else: messages.success(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/admin/'))

@admin.register(Mandant)
class MandantAdmin(ModelAdmin): list_display = ('firma_oder_name', 'ort')
@admin.register(Handwerker)
class HandwerkerAdmin(ModelAdmin): list_display = ('firma', 'gewerk')
@admin.register(Dokument)
class DokumentAdmin(ModelAdmin): list_display = ('titel', 'kategorie', 'vertrag'); list_filter = ('kategorie',)
@admin.register(Zaehler)
class ZaehlerAdmin(ModelAdmin): list_display = ('typ', 'zaehler_nummer', 'einheit'); inlines = [ZaehlerStandInline]
@admin.register(Geraet)
class GeraetAdmin(ModelAdmin): list_display = ('typ', 'marke', 'einheit')
@admin.register(Unterhalt)
class UnterhaltAdmin(ModelAdmin): list_display = ('titel', 'datum', 'kosten')
@admin.register(Schluessel)
class SchluesselAdmin(ModelAdmin): list_display = ('schluessel_nummer', 'liegenschaft'); inlines = [SchluesselAusgabeInline]
@admin.register(TicketNachricht)
class TicketNachrichtAdmin(ModelAdmin):
    list_display = ('ticket', 'absender_name', 'erstellt_am')
    readonly_fields = ['nachricht_anzeige']
    def nachricht_anzeige(self, obj): return format_html('<div style="white-space: pre-wrap;">{}</div>', obj.nachricht)

admin.site.register([MietzinsAnpassung, Leerstand, SchluesselAusgabe])

# ==========================================
# BUCHHALTUNG & KREDITOREN
# ==========================================

@admin.register(Buchungskonto)
class BuchungskontoAdmin(ModelAdmin):
    list_display = ('nummer', 'bezeichnung', 'typ')
    search_fields = ('nummer', 'bezeichnung')
    list_filter = ('typ',)

    actions_list = ["load_standard_accounts"]

    @action(description="📚 Schweizer Kontenplan laden", url_path="load-accounts")
    def load_standard_accounts(self, request):
        standard_konten = [
            ('1020', 'Bankguthaben', 'bilanz'),
            ('1100', 'Forderungen (Ausstehende Mieten)', 'bilanz'),
            ('1600', 'Immobilien / Liegenschaften', 'bilanz'),
            ('2000', 'Verbindlichkeiten (Kreditoren)', 'bilanz'),
            ('2300', 'Rückstellungen (Sanierung)', 'bilanz'),

            ('3000', 'Mietertrag Wohnungen', 'ertrag'),
            ('3010', 'Mietertrag Gewerbe', 'ertrag'),
            ('3020', 'Mietertrag Parkplätze', 'ertrag'),
            ('3400', 'Nebenkosten Akonto-Einnahmen', 'ertrag'),

            ('4000', 'Material- und Warenaufwand', 'aufwand'),
            ('4200', 'Heizmaterial / Energieaufwand', 'aufwand'),
            ('4210', 'Wasser / Abwasser', 'aufwand'),
            ('4220', 'Allgemeinstrom', 'aufwand'),
            ('4300', 'Hauswartung & Reinigung', 'aufwand'),
            ('4400', 'Unterhalt & Reparaturen Gebäude', 'aufwand'),
            ('4410', 'Serviceabos (Lift, Heizung)', 'aufwand'),
            ('4420', 'Gartenunterhalt / Umgebung', 'aufwand'),
            ('6500', 'Verwaltungshonorar', 'aufwand'),
            ('6520', 'Versicherungen (Gebäude, Haftpflicht)', 'aufwand'),
            ('6530', 'Steuern, Abgaben, Gebühren', 'aufwand'),
            ('6800', 'Abschreibungen', 'aufwand'),
            ('6900', 'Finanzaufwand (Hypothekarzinsen, Spesen)', 'aufwand'),
        ]

        count = 0
        for nr, bez, typ in standard_konten:
            obj, created = Buchungskonto.objects.get_or_create(
                nummer=nr,
                defaults={'bezeichnung': bez, 'typ': typ}
            )
            if created:
                count += 1

        messages.success(request, f"✅ {count} Standard-Konten wurden erfolgreich angelegt!")
        return redirect(request.META.get('HTTP_REFERER', '/admin/core/buchungskonto/'))

@admin.register(KreditorenRechnung)
class KreditorenRechnungAdmin(ModelAdmin):
    list_display = ('lieferant', 'datum', 'betrag', 'status', 'liegenschaft', 'einheit')
    list_filter = ('status', 'liegenschaft', 'konto')
    search_fields = ('lieferant', 'iban', 'referenz')
    readonly_fields = ('fehlermeldung',)
    list_editable = ('status',)

    fieldsets = (
        ('KI-Scanner', {
            'fields': ('beleg_scan', 'fehlermeldung')
        }),
        ('Buchhaltung & Zuweisung', {
            'fields': ('status', 'liegenschaft', 'einheit', 'konto')
        }),
        ('Rechnungsdetails (Auto-Fill durch KI)', {
            'fields': ('lieferant', 'datum', 'faellig_am', 'betrag', 'iban', 'referenz')
        }),
    )

# ==========================================
# DEBITOREN & MIETEINNAHMEN
# ==========================================

@admin.register(Zahlungseingang)
class ZahlungseingangAdmin(ModelAdmin):
    list_display = ('vertrag', 'buchungs_monat_format', 'datum_eingang', 'betrag', 'konto', 'liegenschaft')
    list_filter = ('liegenschaft', 'buchungs_monat', 'konto')
    search_fields = ('vertrag__mieter__nachname', 'vertrag__mieter__vorname', 'bemerkung')
    date_hierarchy = 'datum_eingang'

    fieldsets = (
        ('Zuweisung', {
            'fields': ('vertrag', 'buchungs_monat', 'konto')
        }),
        ('Zahlungsdetails', {
            'fields': ('datum_eingang', 'betrag', 'bemerkung')
        }),
    )

    def buchungs_monat_format(self, obj):
        return obj.buchungs_monat.strftime('%m/%Y') if obj.buchungs_monat else "-"
    buchungs_monat_format.short_description = "Für Monat"

# ==========================================
# ERFOLGSRECHNUNG & AUSWERTUNGEN
# ==========================================

@admin.register(Jahresabschluss)
class JahresabschlussAdmin(ModelAdmin):
    list_display = ('liegenschaft', 'jahr')
    list_filter = ('liegenschaft', 'jahr')

    fieldsets = (
        ('Basisdaten', {'fields': ('liegenschaft', 'jahr', 'notizen')}),
        ('Finanzbericht (Live kalkuliert)', {'fields': ('bericht_anzeige',)}),
    )
    readonly_fields = ('bericht_anzeige',)

    def bericht_anzeige(self, obj):
        if not obj.pk:
            return "Bitte wähle eine Liegenschaft und ein Jahr und klicke auf Speichern, um den Bericht zu laden."

        einnahmen = Zahlungseingang.objects.filter(
            liegenschaft=obj.liegenschaft,
            datum_eingang__year=obj.jahr
        ).values('konto__nummer', 'konto__bezeichnung').annotate(total=Sum('betrag')).order_by('konto__nummer')

        total_ertrag = sum(e['total'] for e in einnahmen if e['total'])

        ausgaben = KreditorenRechnung.objects.filter(
            liegenschaft=obj.liegenschaft,
            datum__year=obj.jahr,
            status__in=['freigegeben', 'bezahlt']
        ).values('konto__nummer', 'konto__bezeichnung').annotate(total=Sum('betrag')).order_by('konto__nummer')

        total_aufwand = sum(a['total'] for a in ausgaben if a['total'])

        gewinn = total_ertrag - total_aufwand
        color_gewinn = "text-emerald-600" if gewinn >= 0 else "text-red-600"

        html = f"<div class='max-w-3xl'><h3 class='text-xl font-bold mb-4'>Erfolgsrechnung {obj.jahr}</h3>"

        html += "<h4 class='font-bold text-emerald-700 mt-4 mb-2'>Erträge (Einnahmen)</h4>"
        html += "<table class='w-full text-sm border-collapse mb-4'><tbody>"
        for e in einnahmen:
            konto_nr = e['konto__nummer'] if e['konto__nummer'] else '---'
            konto_bez = e['konto__bezeichnung'] if e['konto__bezeichnung'] else 'Ohne Konto'
            html += f"<tr class='border-b border-gray-200 dark:border-gray-700'><td class='py-2 text-gray-500 w-24'>{konto_nr}</td><td class='py-2'>{konto_bez}</td><td class='py-2 text-right'>CHF {e['total']:,.2f}</td></tr>"
        html += f"<tr class='font-bold bg-emerald-50 dark:bg-emerald-900/20 text-emerald-800 dark:text-emerald-400'><td colspan='2' class='py-2 px-2 rounded-l'>Total Ertrag</td><td class='py-2 px-2 text-right rounded-r'>CHF {total_ertrag:,.2f}</td></tr>"
        html += "</tbody></table>"

        html += "<h4 class='font-bold text-red-700 mt-6 mb-2'>Aufwand (Ausgaben)</h4>"
        html += "<table class='w-full text-sm border-collapse mb-4'><tbody>"
        for a in ausgaben:
            konto_nr = a['konto__nummer'] if a['konto__nummer'] else '---'
            konto_bez = a['konto__bezeichnung'] if a['konto__bezeichnung'] else 'Ohne Konto'
            html += f"<tr class='border-b border-gray-200 dark:border-gray-700'><td class='py-2 text-gray-500 w-24'>{konto_nr}</td><td class='py-2'>{konto_bez}</td><td class='py-2 text-right'>CHF {a['total']:,.2f}</td></tr>"
        html += f"<tr class='font-bold bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400'><td colspan='2' class='py-2 px-2 rounded-l'>Total Aufwand</td><td class='py-2 px-2 text-right rounded-r'>CHF {total_aufwand:,.2f}</td></tr>"
        html += "</tbody></table>"

        html += f"<div class='mt-6 p-4 bg-gray-100 dark:bg-gray-800 rounded-lg flex justify-between items-center text-lg font-bold'><span>Liegenschaftserfolg (Gewinn)</span><span class='{color_gewinn}'>CHF {gewinn:,.2f}</span></div></div>"

        return mark_safe(html)

    bericht_anzeige.short_description = "Auswertung"


# ==========================================
# MIETZINS-KONTROLLE (DEBITOREN SCANNER)
# ==========================================

@admin.register(MietzinsKontrolle)
class MietzinsKontrolleAdmin(ModelAdmin):
    list_display = ('liegenschaft', 'monat_format')
    list_filter = ('liegenschaft',)

    fieldsets = (
        ('Prüfung', {'fields': ('liegenschaft', 'monat', 'notizen')}),
        ('Scanner-Ergebnis (Live)', {'fields': ('kontroll_bericht',)}),
    )
    readonly_fields = ('kontroll_bericht',)

    def monat_format(self, obj):
        return obj.monat.strftime('%m/%Y') if obj.monat else "-"
    monat_format.short_description = "Geprüfter Monat"

    def kontroll_bericht(self, obj):
        if not obj.pk:
            return "Bitte wähle eine Liegenschaft und einen Monat und klicke auf Speichern, um den Scanner zu starten."

        # Holen aller aktiven Verträge für diese Liegenschaft
        vertraege = Mietvertrag.objects.filter(
            einheit__liegenschaft=obj.liegenschaft,
            aktiv=True,
            beginn__lte=obj.monat
        )

        html = f"<div class='max-w-4xl'><h3 class='text-xl font-bold mb-4'>Soll/Ist Abgleich für {obj.monat.strftime('%m/%Y')}</h3>"
        html += "<table class='w-full text-sm border-collapse mb-4'><thead><tr class='bg-gray-100 dark:bg-gray-800 text-left'><th class='p-2'>Einheit</th><th class='p-2'>Mieter</th><th class='p-2 text-right'>Soll (Miete+NK)</th><th class='p-2 text-right'>Ist (Bezahlt)</th><th class='p-2 text-right'>Offen</th><th class='p-2'>Status</th></tr></thead><tbody>"

        total_soll = Decimal('0.00')
        total_ist = Decimal('0.00')

        for vertrag in vertraege:
            # 1. Was der Mieter zahlen muss
            soll = vertrag.netto_mietzins + vertrag.nebenkosten
            total_soll += soll

            # 2. Was der Mieter wirklich gezahlt hat
            zahlungen = Zahlungseingang.objects.filter(
                vertrag=vertrag,
                buchungs_monat=obj.monat
            ).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')

            total_ist += zahlungen

            # 3. Differenz
            diff = soll - zahlungen

            # 4. Ampel
            if diff <= 0:
                status = "<span class='text-emerald-600 font-bold'>✅ Bezahlt</span>"
                row_bg = ""
            elif zahlungen == 0:
                status = "<span class='text-red-600 font-bold'>❌ Keine Zahlung</span>"
                row_bg = "bg-red-50 dark:bg-red-900/10"
            else:
                status = "<span class='text-amber-600 font-bold'>⚠️ Teilzahlung</span>"
                row_bg = "bg-amber-50 dark:bg-amber-900/10"

            html += f"<tr class='border-b {row_bg} border-gray-200 dark:border-gray-700'><td class='p-2'>{vertrag.einheit.bezeichnung}</td><td class='p-2 font-medium'>{vertrag.mieter}</td><td class='p-2 text-right'>CHF {soll:,.2f}</td><td class='p-2 text-right'>CHF {zahlungen:,.2f}</td><td class='p-2 text-right font-bold'>CHF {diff:,.2f}</td><td class='p-2'>{status}</td></tr>"

        # Abschlusszeile
        html += f"<tr class='font-bold bg-gray-200 dark:bg-gray-700'><td colspan='2' class='p-2'>GESAMT</td><td class='p-2 text-right'>CHF {total_soll:,.2f}</td><td class='p-2 text-right'>CHF {total_ist:,.2f}</td><td class='p-2 text-right text-red-600'>CHF {(total_soll-total_ist):,.2f}</td><td></td></tr>"
        html += "</tbody></table></div>"

        return mark_safe(html)

    kontroll_bericht.short_description = "Scanner Ergebnis"