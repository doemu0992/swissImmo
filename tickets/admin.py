from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.template.defaultfilters import date as _date
from django.forms.widgets import TextInput
from django.core.mail import EmailMessage
from django.urls import reverse

# Unfold Imports
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.decorators import display

# Lokale Modelle (Tickets)
from .models import SchadenMeldung, HandwerkerAuftrag, TicketNachricht

# Externe Utils
try:
    from core.utils.email_service import send_handyman_notification
except ImportError:
    send_handyman_notification = None

# ==========================================
# 0. WIDGET FÜR CC-FELD (Chat)
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
# 1. INLINES (Chat & Aufträge)
# ==========================================

class HandwerkerAuftragInline(TabularInline):
    model = HandwerkerAuftrag
    extra = 0
    fields = ('handwerker', 'status', 'bemerkung', 'beauftragt_am')
    readonly_fields = ('beauftragt_am',)
    tab = True
    verbose_name = "Beauftragter Handwerker"
    verbose_name_plural = "🛠️ Beauftragte Handwerker / Aufträge"

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
# 2. HAUPT ADMINS (SaaS-Look)
# ==========================================

@admin.register(SchadenMeldung)
class SchadenMeldungAdmin(ModelAdmin):
    list_display = ('ticket_profil', 'status_prio_info', 'handwerker_info', 'datum_info', 'schnell_aktionen')
    list_filter = ('status', 'prioritaet', 'gelesen')
    list_filter_submit = True
    search_fields = ('titel', 'email_melder', 'id')
    inlines = [HandwerkerAuftragInline, TicketHistoryInline, TicketInputInline]

    fieldsets = (
        ('Status', {'fields': ('status', 'prioritaet', 'gelesen')}),
        ('Meldung', {'fields': ('titel', 'beschreibung', 'foto')}),
        ('Kontakt Melder', {'fields': ('gemeldet_von', 'email_melder', 'tel_melder', 'betroffene_einheit')})
    )
    readonly_fields = ('erstellt_am',)

    @display(description="Ticket & Melder", ordering="-id")
    def ticket_profil(self, obj):
        prio = getattr(obj, 'prioritaet', 'mittel')
        icon = "🚨" if prio == 'hoch' else "🛠️"
        bg_color = "bg-red-100 text-red-700 ring-red-600/10" if prio == 'hoch' else "bg-gray-100 text-gray-700 ring-gray-600/10"

        melder = getattr(obj, 'email_melder', None) or (obj.gemeldet_von.email if getattr(obj, 'gemeldet_von', None) else "Unbekannt")
        titel = getattr(obj, 'titel', 'Ohne Titel')

        ungelesene = obj.nachrichten.filter(gelesen=False).exclude(typ='system').exists() if obj.id else False
        dot = '<span class="absolute -top-1 -right-1 flex h-3 w-3"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span><span class="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span></span>' if (not obj.gelesen or ungelesene) else ''

        return format_html(
            '<div class="flex items-center gap-3">'
            '<div class="relative flex items-center justify-center w-10 h-10 rounded-xl {} text-xl shadow-sm ring-1 ring-inset">{} {}</div>'
            '<div><div class="font-bold text-gray-900 leading-tight">{}</div><div class="text-xs text-gray-500 mt-0.5">#{} • {}</div></div>'
            '</div>',
            bg_color, icon, mark_safe(dot), titel, obj.id, melder
        )

    @display(description="Status & Prio")
    def status_prio_info(self, obj):
        st = getattr(obj, 'status', 'neu')
        if st == 'neu': st_html = '<span class="inline-flex items-center rounded-md bg-red-50 px-2 py-1 text-[11px] font-semibold text-red-700 ring-1 ring-inset ring-red-600/10">Neu</span>'
        elif st == 'in_bearbeitung': st_html = '<span class="inline-flex items-center rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700 ring-1 ring-inset ring-amber-600/10">In Bearbeitung</span>'
        elif st == 'erledigt': st_html = '<span class="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/10">Erledigt</span>'
        elif st == 'abgelehnt': st_html = '<span class="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-[11px] font-semibold text-gray-600 ring-1 ring-inset ring-gray-500/10">Abgelehnt</span>'
        else: st_html = f'<span class="inline-flex items-center rounded-md bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-600 ring-1 ring-inset ring-gray-500/10">{st}</span>'

        pr = getattr(obj, 'prioritaet', 'mittel')
        if pr == 'hoch': pr_html = '<span class="text-red-600 font-bold">🔥 Hoch</span>'
        elif pr == 'mittel': pr_html = '<span class="text-amber-600 font-bold">⚡ Mittel</span>'
        else: pr_html = '<span class="text-blue-500 font-bold">🧊 Tief</span>'

        return format_html('<div class="flex flex-col gap-1 items-start">{}<span class="text-[10px]">{}</span></div>', mark_safe(st_html), mark_safe(pr_html))

    @display(description="Aufträge")
    def handwerker_info(self, obj):
        cnt = obj.handwerker_auftraege.count() if obj.id else 0
        if cnt > 0:
            return format_html('<span class="inline-flex items-center rounded-md bg-orange-50 px-2 py-1 text-xs font-medium text-orange-700 ring-1 ring-inset ring-orange-600/20">👷 {} beauftragt</span>', cnt)
        return format_html('<span class="text-xs text-gray-400">-</span>')

    @display(description="Erstellt am", ordering="erstellt_am")
    def datum_info(self, obj):
        datum = getattr(obj, 'erstellt_am', None)
        return datum.strftime('%d.%m.%Y') if datum else "-"

    @display(description="Aktionen")
    def schnell_aktionen(self, obj):
        edit_url = reverse('admin:tickets_schadenmeldung_change', args=[obj.id])
        return format_html(
            '<a href="{}" class="text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-2.5 py-1.5 rounded text-xs font-semibold transition-colors">Ticket öffnen</a>',
            edit_url
        )

    # --- Die E-Mail Logik aus deinem alten Code (Bleibt unangetastet) ---
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
                    if instance.ticket.email_melder and send_handyman_notification: send_handyman_notification(instance)
                instance.save()
            elif isinstance(instance, TicketNachricht):
                if instance.pk is None:
                    cc_list = [e.strip() for e in instance.cc_email.split(',')] if getattr(instance, 'cc_email', None) else []
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

@admin.register(TicketNachricht)
class TicketNachrichtAdmin(ModelAdmin):
    list_display = ('ticket', 'absender_name', 'erstellt_am')
    readonly_fields = ['nachricht_anzeige']
    def nachricht_anzeige(self, obj): return format_html('<div style="white-space: pre-wrap;">{}</div>', obj.nachricht)