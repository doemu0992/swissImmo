from crm.models import Eigentuemer


def fw_badges(request):
    """Stellt Zähler für die Sidebar-Badges bereit (nur für eingeloggte
    Team-Mitglieder in der /neu/-Oberfläche). Zählt ungelesene Schadenmeldungen."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    # Nur fürs Team relevant (Mieter/Eigentümer sehen die Sidebar nicht)
    try:
        from core.auth import hat_rolle, TEAM_ROLLEN
        if not hat_rolle(user, TEAM_ROLLEN):
            return {}
        from tickets.models import SchadenMeldung
        return {'schaeden_ungelesen': SchadenMeldung.objects.filter(gelesen=False).count()}
    except Exception:
        return {}


def admin_baum_navigation(request):
    if request.path.startswith('/admin/'):
        baum_daten = Eigentuemer.objects.prefetch_related(
            'liegenschaften',
            'liegenschaften__einheiten',
            'liegenschaften__einheiten__geraete',
            'liegenschaften__einheiten__vertraege',
            'liegenschaften__einheiten__vertraege__mieter',
            'liegenschaften__einheiten__leerstaende'
        ).all()
        return {'custom_admin_nav': baum_daten}
    return {}