from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages
from django.template.defaultfilters import date as _date

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.decorators import action, display

# Modelle
from .models import SchadenMeldung, HandwerkerAuftrag, TicketNachricht

# ==========================================
# 0. SICHERHEITS-CHECK
# ==========================================
models_to_fix = [SchadenMeldung, HandwerkerAuftrag, TicketNachricht]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# ==========================================
# 1. INLINES (Chat & Aufträge)
# ==========================================

class TicketHistoryInline(StackedInline):
    model = TicketNachricht
    extra = 0
    fk_name = "ticket"
    tab = True
    verbose_name = "Nachricht / Notiz"
    verbose_name_plural = "💬 Kommunikationsverlauf"

    # Wir zeigen nur das formatierte Chat-Feld
    fields = ('timeline_entry',)
    readonly_fields = ('timeline_entry',)

    def timeline_entry(self, obj):
        if not obj.pk: return "-"

        # Farben und Icons je nach Typ der Nachricht
        if obj.typ == 'system':
            icon, bg_color, text_color = "⚙️", "bg-gray-50 border-gray-200", "text-gray-800"
            title = f"System-Meldung: {obj.absender_name}"
        elif obj.typ == 'antwort_senden':
            icon, bg_color, text_color = "📤", "bg-blue-50 border-blue-200", "text-blue-900"
            title = f"Antwort an Mieter: {obj.absender_name}"
        elif obj.typ == 'handwerker_mail':
            icon, bg_color, text_color = "🔨", "bg-orange-50 border-orange-200", "text-orange-900"
            title = f"Auftrag an Handwerker: {obj.absender_name}"
        else:
            icon, bg_color, text_color = "📝", "bg-yellow-50 border-yellow-200", "text-yellow-900"
            title = f"Interne Notiz: {obj.absender_name}"

        date_str = _date(obj.erstellt_am, "d.m.Y H:i")

        html = format_html(
            '<div class="{} rounded-xl border p-4 text-sm mb-3 shadow-sm">'
            '<div class="flex justify-between border-b border-black/5 pb-2 mb-3">'
            '<div class="font-bold flex items-center gap-2"><span class="text-lg">{}</span> <span class="{}">{}</span></div>'
            '<span class="text-xs text-gray-500 font-medium">{}</span>'
            '</div>'
            '<div class="whitespace-pre-wrap leading-relaxed text-gray-700">{}</div>'
            '</div>',
            bg_color, icon, text_color, title, date_str, obj.nachricht
        )
        return mark_safe(html)

    def has_add_permission(self, request, obj=None): return False

class HandwerkerAuftragInline(TabularInline):
    model = HandwerkerAuftrag
    extra = 0
    tab = True
    verbose_name = "Auftrag"
    verbose_name_plural = "🛠️ Handwerker-Aufträge"

    fields = ('auftrag_profil', 'status_badge', 'detail_link')
    readonly_fields = ('auftrag_profil', 'status_badge', 'detail_link')

    @display(description="Handwerker")
    def auftrag_profil(self, obj):
        if not obj.pk: return "-"
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-orange-50 text-orange-700 text-sm ring-1 ring-inset ring-orange-600/20">🔨</div>'
            '<div class="font-bold text-gray-900">{}</div>'
            '</div>', obj.handwerker
        )

    @display(description="Status")
    def status_badge(self, obj):
        if not obj.pk: return "-"
        if obj.status == 'erledigt': return format_html('<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">Erledigt</span>')
        return format_html('<span class="inline-flex items-center rounded-md bg-orange-50 px-2 py-1 text-xs font-medium text-orange-700 ring-1 ring-inset ring-orange-600/10">Offen</span>')

    @display(description="Aktion")
    def detail_link(self, obj):
        if obj.id: return format_html('<a href="{}" class="text-orange-600 hover:text-orange-900 bg-orange-50 hover:bg-orange-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">📄 Details</a>', reverse("admin:tickets_handwerkerauftrag_change", args=[obj.id]))
        return "-"

    def has_add_permission(self, request, obj=None): return False


# ==========================================
# 2. SCHADENMELDUNG ADMIN
# ==========================================

@admin.register(SchadenMeldung)
class SchadenMeldungAdmin(ModelAdmin):
    list_display = ('ticket_profil', 'einheit_info', 'prioritaet_badge', 'status_badge', 'schnell_aktionen')
    list_filter = ('status', 'prioritaet', 'betroffene_einheit__liegenschaft')
    search_fields = ('titel', 'beschreibung', 'email_melder')
    inlines = [HandwerkerAuftragInline, TicketHistoryInline]

    readonly_fields = ('ticket_full_header',)

    fieldsets = (
        (None, {
            'fields': ('ticket_full_header',),
            'classes': ('header-fieldset',),
        }),
        ('Meldung & Beschreibung', {'fields': ('titel', 'beschreibung', 'foto')}),
        ('Status & Steuerung', {'fields': (('status', 'prioritaet'), 'gelesen')}),
        ('Kontaktinformationen', {'fields': (('gemeldet_von', 'betroffene_einheit'), ('email_melder', 'tel_melder'))}),
    )

    # --- HEADER BUTTONS ---
    actions_detail = ["action_mark_done", "action_create_note"]

    @action(description="✅ Als erledigt markieren", url_path="mark-done")
    def action_mark_done(self, request, object_id):
        obj = self.get_object(request, object_id)
        obj.status = 'erledigt'
        obj.save()
        messages.success(request, "Ticket wurde erfolgreich geschlossen.")
        return redirect(request.META.get('HTTP_REFERER'))

    @action(description="📝 Neue Notiz / Antwort", url_path="add-note")
    def action_create_note(self, request, object_id):
        url = reverse('admin:tickets_ticketnachricht_add') + f"?ticket={object_id}"
        return redirect(url)


    # --- DASHBOARD HEADER ---
    @display(description="")
    def ticket_full_header(self, obj):
        if not obj.pk:
            return format_html('<div class="p-4 bg-rose-50 text-rose-700 rounded-xl font-bold border border-rose-100">✨ Neues Ticket erstellen</div>')

        einheit_name = str(getattr(obj, 'betroffene_einheit', 'Allgemein'))
        erstellt = obj.erstellt_am.strftime('%d.%m.%Y %H:%M') if obj.erstellt_am else "-"

        # Prio Logik
        if obj.prioritaet == 'hoch': prio_color, prio_text = "#dc2626", "🚨 HOCH"
        elif obj.prioritaet == 'mittel': prio_color, prio_text = "#d97706", "⚠️ MITTEL"
        else: prio_color, prio_text = "#059669", "🟢 TIEF"

        # Status Logik
        if obj.status == 'neu': stat_color, stat_text = "#dc2626", "NEU"
        elif obj.status == 'in_bearbeitung': stat_color, stat_text = "#d97706", "IN BEARBEITUNG"
        else: stat_color, stat_text = "#059669", "ERLEDIGT"

        html = f"""
        <style>
            fieldset.header-fieldset {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; border: none !important; background: transparent !important; box-shadow: none !important; grid-column: 1 / -1 !important; }}
            fieldset.header-fieldset > div, fieldset.header-fieldset .form-row {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; margin: 0 !important; border: none !important; }}
            fieldset.header-fieldset label {{ display: none !important; }}
        </style>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; width: 100%; margin-bottom: 2rem;">
            <div style="background: white; padding: 1.5rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 1rem; grid-column: span 2;">
                <div style="display: flex; align-items: center; justify-content: center; width: 3.5rem; height: 3.5rem; background: #fff1f2; color: #e11d48; border-radius: 0.75rem; font-size: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0;">🎫</div>
                <div style="overflow: hidden;">
                    <h2 style="font-size: 1.25rem; font-weight: 700; color: #111827; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{obj.titel}</h2>
                    <p style="font-size: 0.875rem; color: #6b7280; margin: 0; margin-top: 2px;">Ticket #{obj.id} • Gemeldet am {erstellt}</p>
                </div>
            </div>

            <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Betroffenes Objekt</span>
                <span style="font-size: 1.125rem; font-weight: 700; color: #111827;">{einheit_name}</span>
            </div>

            <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Priorität</span>
                <span style="font-size: 1.125rem; font-weight: 700; color: {prio_color};">{prio_text}</span>
            </div>

            <div style="background: white; padding: 1.25rem; border-radius: 12px; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center;">
                <span style="font-size: 0.7rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em;">Status</span>
                <span style="font-size: 1.125rem; font-weight: 700; color: {stat_color};">{stat_text}</span>
            </div>
        </div>
        """
        return mark_safe(html)

    # --- Listenansicht Formatierungen ---
    @display(description="Ticket", ordering="-erstellt_am")
    def ticket_profil(self, obj):
        erstellt = obj.erstellt_am.strftime('%d.%m.%Y') if obj.erstellt_am else "-"
        gelesen_indicator = "" if getattr(obj, 'gelesen', True) else '<span class="w-2 h-2 rounded-full bg-blue-600 absolute top-0 right-0 transform translate-x-1/2 -translate-y-1/2"></span>'

        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="relative flex items-center justify-center w-10 h-10 rounded-xl bg-rose-100 text-rose-700 text-xl shadow-sm ring-1 ring-inset ring-rose-600/10">🎫{}</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">#{} • {}</div></div>'
            '</div>',
            mark_safe(gelesen_indicator), obj.titel[:40] + ('...' if len(obj.titel) > 40 else ''), obj.id, erstellt
        )

    @display(description="Betroffenes Objekt", ordering="betroffene_einheit")
    def einheit_info(self, obj):
        if obj.betroffene_einheit:
            return format_html('<span class="text-sm font-medium text-gray-700">🏠 {}</span>', obj.betroffene_einheit.bezeichnung)
        return format_html('<span class="text-sm font-medium text-gray-500">Allgemein</span>')

    @display(description="Priorität", label=True, ordering="prioritaet")
    def prioritaet_badge(self, obj):
        if obj.prioritaet == 'hoch': return "HOCH", "danger"
        elif obj.prioritaet == 'mittel': return "MITTEL", "warning"
        return "TIEF", "success"

    @display(description="Status", label=True, ordering="status")
    def status_badge(self, obj):
        if obj.status == 'neu': return "NEU", "danger"
        elif obj.status == 'in_bearbeitung': return "IN BEARBEITUNG", "warning"
        return "ERLEDIGT", "success"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        edit_url = reverse('admin:tickets_schadenmeldung_change', args=[obj.id])
        return format_html(
            '<a href="{}" class="text-rose-600 hover:text-rose-900 bg-rose-50 hover:bg-rose-100 px-3 py-1.5 rounded-md text-xs font-bold transition-colors shadow-sm">🎫 Öffnen</a>',
            edit_url
        )


# ==========================================
# 3. WEITERE ADMINS (Handwerkerauftrag & Nachricht)
# ==========================================

@admin.register(HandwerkerAuftrag)
class HandwerkerAuftragAdmin(ModelAdmin):
    list_display = ('auftrag_profil', 'ticket_info', 'status_badge')
    list_filter = ('status', 'handwerker')

    @display(description="Auftrag", ordering="handwerker")
    def auftrag_profil(self, obj):
        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="flex items-center justify-center w-10 h-10 rounded-xl bg-orange-100 text-orange-700 text-xl shadow-sm ring-1 ring-inset ring-orange-600/10">🔨</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">Beauftragt: {}</div></div>'
            '</div>',
            obj.handwerker, obj.beauftragt_am.strftime('%d.%m.%Y') if getattr(obj, 'beauftragt_am', None) else "-"
        )

    @display(description="Ticket")
    def ticket_info(self, obj):
        if obj.ticket: return format_html('<a href="{}" class="text-blue-600 font-medium hover:text-blue-800 transition-colors">🎫 Ticket #{}</a>', reverse('admin:tickets_schadenmeldung_change', args=[obj.ticket.id]), obj.ticket.id)
        return "-"

    @display(description="Status", label=True)
    def status_badge(self, obj):
        if obj.status == 'erledigt': return "Erledigt", "success"
        return "Offen", "warning"

@admin.register(TicketNachricht)
class TicketNachrichtAdmin(ModelAdmin):
    list_display = ('ticket', 'typ', 'absender_name', 'erstellt_am')
    list_filter = ('typ',)