from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib import messages
from django.template.defaultfilters import date as _date

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.decorators import action, display

# Deine Modelle
from .models import SchadenMeldung, HandwerkerAuftrag, TicketNachricht

# ==========================================
# 0. SICHERHEITS-CHECK (Bereinigung)
# ==========================================
models_to_fix = [SchadenMeldung, HandwerkerAuftrag, TicketNachricht]
for m in models_to_fix:
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# ==========================================
# 1. TIMELINE / CHAT INLINE (Der Fairwalter-Look)
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
        # Farben und Icons je nach Typ der Nachricht
        if obj.typ == 'system':
            icon, bg_color = "⚙️", "bg-gray-50 border-gray-200"
            title = f"System: {obj.absender_name}"
        elif obj.typ == 'antwort_senden':
            icon, bg_color = "📤", "bg-blue-50 border-blue-200"
            title = f"Gesendet an Melder: {obj.absender_name}"
        elif obj.typ == 'handwerker_mail':
            icon, bg_color = "🔨", "bg-orange-50 border-orange-200"
            title = f"An Handwerker: {obj.absender_name}"
        else:
            icon, bg_color = "📝", "bg-yellow-50 border-yellow-200"
            title = f"Interne Notiz: {obj.absender_name}"

        date_str = _date(obj.erstellt_am, "d.m.Y H:i")

        # HTML für die Chat-Blase
        html = format_html(
            '<div class="{} rounded-lg border p-4 text-sm mb-2">'
            '<div class="flex justify-between border-b pb-2 mb-2 font-bold">'
            '<span>{} {}</span><span class="text-xs font-normal">{}</span>'
            '</div>'
            '<div style="white-space: pre-wrap;">{}</div>'
            '</div>',
            bg_color, icon, title, date_str, obj.nachricht
        )
        return html

    def has_add_permission(self, request, obj=None): return False

class HandwerkerAuftragInline(TabularInline):
    model = HandwerkerAuftrag
    extra = 0
    fields = ('handwerker', 'status', 'beauftragt_am')
    readonly_fields = ('beauftragt_am',)
    tab = True

# ==========================================
# 2. SCHADENMELDUNG ADMIN
# ==========================================

@admin.register(SchadenMeldung)
class SchadenMeldungAdmin(ModelAdmin):
    list_display = ('id_display', 'titel', 'get_status_badge', 'get_prioritaet_badge', 'betroffene_einheit', 'erstellt_am')
    list_filter = ('status', 'prioritaet', 'betroffene_einheit__liegenschaft')
    search_fields = ('titel', 'beschreibung', 'email_melder')
    inlines = [HandwerkerAuftragInline, TicketHistoryInline]

    # Karten-Layout
    fieldsets = (
        ('Status & Dringlichkeit', {
            'fields': (('status', 'prioritaet'), 'gelesen'),
        }),
        ('Meldung Details', {
            'fields': ('titel', 'beschreibung', 'foto'),
        }),
        ('Melder & Ort', {
            'fields': (('gemeldet_von', 'betroffene_einheit'), ('email_melder', 'tel_melder')),
        }),
    )

    # --- HEADER BUTTONS ---
    actions_detail = ["action_mark_done", "action_create_order"]

    @action(description="✅ Ticket abschliessen", url_path="mark-done")
    def action_mark_done(self, request, object_id):
        obj = self.get_object(request, object_id)
        obj.status = 'erledigt'
        obj.save()
        messages.success(request, "Ticket wurde erfolgreich als erledigt markiert.")
        return redirect(request.META.get('HTTP_REFERER'))

    @action(description="🛠️ Handwerker beauftragen", url_path="create-order")
    def action_create_order(self, request, object_id):
        # Hier könnte man auf ein Formular weiterleiten
        messages.info(request, "Bitte Handwerker im Bereich 'Aufträge' auswählen.")
        return redirect(request.META.get('HTTP_REFERER'))

    # --- BADGES ---

    @display(description="Status", label=True)
    def get_status_badge(self, obj):
        if obj.status == 'neu': return "Neu", "danger"
        elif obj.status == 'in_bearbeitung': return "In Arbeit", "warning"
        elif obj.status == 'erledigt': return "Erledigt", "success"
        return obj.status, "info"

    @display(description="Priorität", label=True)
    def get_prioritaet_badge(self, obj):
        if obj.prioritaet == 'hoch': return "Hoch", "danger"
        elif obj.prioritaet == 'mittel': return "Mittel", "warning"
        return "Tief", "success"

    def id_display(self, obj):
        return f"#{obj.id}"
    id_display.short_description = "ID"

# ==========================================
# 3. WEITERE MODULE
# ==========================================

@admin.register(HandwerkerAuftrag)
class HandwerkerAuftragAdmin(ModelAdmin):
    list_display = ('ticket', 'handwerker', 'status', 'beauftragt_am')

@admin.register(TicketNachricht)
class TicketNachrichtAdmin(ModelAdmin):
    list_display = ('ticket', 'typ', 'absender_name', 'erstellt_am')