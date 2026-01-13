from django import template

register = template.Library()

@register.filter(name='swiss_money')
def swiss_money(value):
    """
    Wandelt 1250.50 -> 1'250.50
    """
    try:
        if value is None:
            return "0.00"
        val = float(value)
        return f"{val:,.2f}".replace(",", "'")
    except (ValueError, TypeError):
        return str(value)