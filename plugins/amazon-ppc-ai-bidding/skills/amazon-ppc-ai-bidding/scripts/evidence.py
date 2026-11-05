"""Evidence helpers shared by the bid planner: how sure we are a search beats the market, and how big it is.

Standard library only. `p_beats` and `p_below` read our orders and clicks against the market conversion
rate through a Beta posterior; `opportunity` is the index-weighted 30-day search volume used to rank searches.
"""
import math


def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (modified Lentz, as in Numerical Recipes)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        step = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + step * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + step / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        step = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + step * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + step / c
        c = c if abs(c) > tiny else tiny
        change = d * c
        h *= change
        if abs(change - 1.0) < 1e-14:
            break
    return h


def _beta_cdf(x, a, b):
    """Regularized incomplete beta function I_x(a, b): the chance a Beta(a, b) draw is at most x."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def p_beats(orders, clicks, market_cvr, prior_clicks=10, ratio=1.0):
    """Posterior probability that our conversion exceeds ratio x market_cvr.

    The market rate acts as a prior worth `prior_clicks` clicks, so the posterior is
    Beta(orders + prior x m, clicks - orders + prior x (1 - m)) with m = market_cvr.
    Orders above clicks (an attribution quirk in search-query data) are capped at clicks.
    """
    if not 0.0 < market_cvr < 1.0:
        raise ValueError('market_cvr must be between 0 and 1')
    if orders < 0 or clicks < 0:
        raise ValueError('orders and clicks cannot be negative')
    orders = min(orders, clicks)
    a = orders + prior_clicks * market_cvr
    b = clicks - orders + prior_clicks * (1.0 - market_cvr)
    return 1.0 - _beta_cdf(ratio * market_cvr, a, b)


def p_below(orders, clicks, market_cvr, prior_clicks=10, ratio=0.8):
    """Posterior probability that our conversion is below ratio x market_cvr."""
    return 1.0 - p_beats(orders, clicks, market_cvr, prior_clicks, ratio)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value):
    return _number(value) and value > 0


def monthly_searches(volume, days):
    """Search volume normalised to 30 days: volume x 30 / days.

    None when there is no volume (missing, negative or not a number) or no days (missing or not positive). A volume of
    0 is a real reading, so it gives 0.0, not None.
    """
    if not (_number(volume) and volume >= 0 and _positive(days)):
        return None
    return volume * 30 / days


def opportunity(index, volume, observed_days):
    """Index x monthly searches; None unless the index and the monthly searches are present and positive."""
    monthly = monthly_searches(volume, observed_days)
    if not (_positive(index) and _positive(monthly)):
        return None
    return index * monthly


def sure_text(p, claim='beats the market'):
    """How sure we are, in words: 'about 65% sure it beats the market'. Cuts pass claim='converts under 0.8x the market'."""
    return f'about {round(p * 100)}% sure it {claim}'
