"""Verify an SP ad-group's temporary scheduled pause without pretending it is serving."""
import datetime as dt

from lanes import _la_offset_hours


def scheduled_pause(live, as_of, max_age_days=2):
    """Return evidence for a bid-only exception, or None. No state/schedule writes are authorized.

    The collector must retain exact assignment, rule-grid and pause-classification sources.
    Clock arithmetic alone cannot classify a manual pause as a scheduled pause.
    """
    if not isinstance(live, dict) or live.get('ad_product', 'SP') != 'SP':
        return None
    proof, gates = live.get('dayparting'), live.get('gates') or {}
    if not isinstance(proof, dict):
        return None
    if (gates.get('campaign_enabled') is not True or gates.get('target_enabled') is not True
            or gates.get('ad_group_enabled') not in (True, False)
            or gates.get('schedule_open') is not False):
        return None
    if (proof.get('pause_reason') != 'scheduled_dayparting' or proof.get('manual_pause') is not False
            or proof.get('assignment_verified') is not True or proof.get('resume_managed') is not True
            or proof.get('timezone') != 'America/Los_Angeles'
            or not all(proof.get(k) for k in ('rule_id', 'assignment_source', 'schedule_source', 'pause_source'))):
        return None
    for key in ('asin', 'campaign_id', 'ad_group_id'):
        if not live.get(key) or str(proof.get(key)) != str(live[key]):
            return None
    if live.get('profile_id') and proof.get('profile_id') != live['profile_id']:
        return None
    hours = proof.get('weekly_hours')  # Monday first; 7 arrays of 24 literal booleans.
    if (not isinstance(hours, list) or len(hours) != 7
            or any(not isinstance(day, list) or len(day) != 24 or any(type(x) is not bool for x in day) for day in hours)):
        return None
    try:
        observed = dt.datetime.fromisoformat(proof['observed_at'])
        today = dt.date.fromisoformat(as_of)
        snapshot = dt.date.fromisoformat(live['observed_on'])
        if observed.utcoffset() is None or not 0 <= (today - snapshot).days <= max_age_days:
            return None
        # Input dates are SGT; timestamps may use any explicit offset.
        if observed.astimezone(dt.timezone(dt.timedelta(hours=8))).date() != snapshot:
            return None
        utc = observed.astimezone(dt.timezone.utc)
        local = utc + dt.timedelta(hours=_la_offset_hours(utc))
        if hours[local.weekday()][local.hour]:
            return None  # Paused during ON hours is a serving problem, not this exception.
        next_on = None
        for offset in range(1, 169):
            candidate = utc.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=offset)
            market = candidate + dt.timedelta(hours=_la_offset_hours(candidate))
            if hours[market.weekday()][market.hour]:
                next_on = candidate.isoformat()
                break
        if next_on is None:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    exempt = ['ad_group_enabled', 'schedule_open']
    # Amazon may label the ad ineligible solely because its parent is paused.
    reasons = live.get('ad_delivery_reasons')
    if (live.get('ad_state') == 'ENABLED' and isinstance(reasons, list) and reasons
            and set(reasons) <= {'AD_GROUP_PAUSED', 'AD_GROUP_PAUSED_DETAIL'}):
        exempt.append('ad_eligible')
    return dict(rule_id=proof['rule_id'], timezone=proof['timezone'], next_on_utc=next_on,
                exempt_gates=exempt, scope='base_bid_only', source=proof['pause_source'])
