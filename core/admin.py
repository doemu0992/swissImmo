# core/admin.py
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User

from core.admin_base import NurLesenMixin, NurLesenModelAdmin

from .models import AktivitaetsLog


@admin.register(AktivitaetsLog)
class AktivitaetsLogAdmin(NurLesenModelAdmin):
    """Audit-Trail — nur lesend (auch für Superuser nicht editierbar).

    Die drei `has_*_permission`-Überschreibungen standen bis E2 hier von Hand;
    sie kommen jetzt aus `NurLesenModelAdmin` und galten damit ohnehin. Dieser
    Admin war das Vorbild für die Regel, die seit E2 für alle gilt.
    """
    list_display = ('zeitpunkt', 'benutzer', 'aktion', 'objekt', 'details')
    list_filter = ('aktion', 'benutzer')
    search_fields = ('aktion', 'objekt', 'details')
    date_hierarchy = 'zeitpunkt'
    ordering = ('-zeitpunkt',)


# ---------------------------------------------------------------------------
# Djangos eigene Benutzer- und Gruppen-Admins kommen aus `django.contrib.auth`
# und wüssten von E2 nichts. Sie werden deshalb ab- und schreibgeschützt
# wieder angemeldet — sonst bliebe ausgerechnet die Rechteverwaltung der eine
# offene Schreibpfad im Admin.
#
# Das nimmt nichts weg: /neu/benutzer/ deckt Anlegen, Bearbeiten samt Rolle
# und Löschen vollständig ab (fw_benutzer_form, fw_benutzer_loeschen), mit
# Rollenprüfung und Audit-Trail. Der allererste Superuser entsteht ohnehin
# über `manage.py createsuperuser`, nicht über die Oberfläche.
# ---------------------------------------------------------------------------
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class NurLesenUserAdmin(NurLesenMixin, UserAdmin):
    """Benutzer ansehen — anlegen und ändern über /neu/benutzer/."""


@admin.register(Group)
class NurLesenGroupAdmin(NurLesenMixin, GroupAdmin):
    """Rollen ansehen — vergeben werden sie über /neu/benutzer/."""
