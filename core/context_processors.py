from .models import Mandant

def admin_baum_navigation(request):
    if request.path.startswith('/admin/'):
        baum_daten = Mandant.objects.prefetch_related(
            'liegenschaften',
            'liegenschaften__einheiten',
            'liegenschaften__einheiten__geraete',
            'liegenschaften__einheiten__vertraege',
            'liegenschaften__einheiten__vertraege__mieter',
            'liegenschaften__einheiten__leerstaende'
        ).all()
        return {'custom_admin_nav': baum_daten}
    return {}