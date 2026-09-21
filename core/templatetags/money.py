from django import template

register = template.Library()


@register.filter
def inr(paise):
    """Format integer paise exactly with Indian digit grouping, including negatives."""
    amount = int(paise)
    rupees, fraction = divmod(abs(amount), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while head:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ','.join(groups + [tail])
    return ('−' if amount < 0 else '') + '₹' + digits + f'.{fraction:02d}'
