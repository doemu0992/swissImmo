# core/admin.py
from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import AktivitaetsLog


@admin.register(AktivitaetsLog)
class AktivitaetsLogAdmin(ModelAdmin):
    """Audit-Trail — nur lesend (auch für Superuser nicht editierbar)."""
    list_display = ('zeitpunkt', 'benutzer', 'aktion', 'objekt', 'details')
    list_filter = ('aktion', 'benutzer')
    search_fields = ('aktion', 'objekt', 'details')
    date_hierarchy = 'zeitpunkt'
    ordering = ('-zeitpunkt',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
