"""The bid planner's lanes step (plan.py section 6): who has to say yes to each change in a plan.

lanes.classify judges one row and changes nothing. This module runs it over a whole plan from plan.build. It:
  - keeps the product's running totals (investment band left, information only since decision 100; invest spend planned;
    raises left);
  - groups each promotion with its duplicate pauses, funnel negatives and budget row, which share its lane;
  - reads a person's locks from the product file (its decisions and rank experiments);
  - prices the investment bands;
  - works out the product's planned invest a month against the investment guide ($2,000; information only, Kim
    2026-10-22, decision 99: no money level parks a promotion) and, for information, the whole program's;
  - stamps the current marketplace date and immediate any-day execution policy.
The spec was docs/superpowers/specs/2026-10-19-bid-auto-apply-design.md, sections 3-6; since 2026-10-22 the human list
are docs/superpowers/specs/2026-10-22-autonomous-runs-design.md (decision 98; decision 99 took the money levels out). plan.py reads the run
folder and passes what this step needs in `inputs`; nothing here reads a file. Standard library only (plus evidence,
lanes, placement_review's rank_tos and searchtext).
"""
import dataclasses
import datetime as dt
import math
from collections import Counter, defaultdict

import evidence
import lanes
import ownership_scope
from placement_review import rank_tos
from searchtext import norm

LOW_STOCK_DAYS = 14      # under this cover a run's increases wait For human until a person clears it (decision 174)
STOCK_CLEARANCE_DAYS = 7  # a person's stock clearance lasts this long unless it names its own `until`
ONBOARDING_DAYS = 14     # the first 2 weeks on AI bidding are onboarding
AUTO_KEYS = ('prove_orders', 'prove_index', 'invest_orders', 'invest_index', 'raise_orders', 'raise_index', 'max_raise_pct',
             'min_opportunity', 'monitor_spend_cap', 'max_raises', 'max_loss_month', 'big_cut_pct',
             'big_cut_orders')
BUNDLE_TYPES = ('Pause keyword', 'Negative exact', 'Budget and top of search')


def follows_sb_video(x):
    """The Sponsored Brands rows that wait with their search's new video: the video itself, and an older copy's holding
    bid. They are not part of the promotion's bundle (a video is its own creation), but they never go out while the
    promotion the ladder judged is held (decision 135), nor while the video is (2026-10-26). The copy's pause comes a run
    later, once the video owns the search (plan.py)."""
    return x['type'] == 'New SB video campaign' or (x['type'] == 'SB bid change' and x.get('copy_hold') is True)


NOT_LOCKING = ('dismissed', 'declined', 'cancelled', 'canceled')  # rank-experiment statuses that no longer hold a search
UNREADABLE_DECISIONS = "the product's decisions list can't be read"
UNREADABLE_REVIEWS = "the saved dashboard decisions (reviews.json) can't be read"
SGT = dt.timedelta(hours=8)  # the dashboard and its records keep Singapore time


def rerank_cost(month_clicks, cpc, budget, term, share, profit):
    """What winning `share` of a search's monthly clicks costs at `cpc`, inside 30 days of its daily budget:
    (spend, orders, net, capped). Its conversion is capped at 1.5x its market's (0.09 when SQP has no market).
    Shared by plan.py's re-rank (section 5) and the bands here."""
    cvr = min(term['cvr_est'], 1.5 * (term['market_cvr'] or 0.09))
    want = share * month_clicks
    spend = min(want * cpc, budget * 30)
    orders = spend / cpc * cvr if cpc else 0
    return spend, orders, orders * profit - spend, want * cpc > budget * 30


# ----------------------------------------------------------------------------- fresh data and onboarding
def _reading(data, key):
    v = data.get(key) if isinstance(data, dict) else None
    return v if evidence._number(v) else None


def auto_enabled(shared, cfg):
    """True when a product's Auto lane is on: config.json's `auto` block with the product file's own `auto` block merged
    over it, and its `enabled` exactly True. config.json turns it on for every AI product (Kim, 2026-10-22, decision 98);
    a product file's "auto": {"enabled": false} is that product's kill switch (autonomy.switch_off writes it)."""
    merged = dict((shared or {}).get('auto') or {})
    merged.update((cfg or {}).get('auto') or {})
    return merged.get('enabled') is True


def stock_cover(inputs):
    """The product's days of stock cover when it is LOW_STOCK_DAYS (14) or fewer, else None.

    Kim, 2026-10-31 (decision 174): a product under about 14 days of stock parks its increases "For human" unless a person
    clears it (stock_clearance). Cuts, pauses and holds still go out. Until then (2026-10-24 to 2026-10-31) low stock was an
    alert only and every Auto row went out. The dated summary.stock_reorder item stays either way.
    """
    n = _reading(inputs.get('inventory_cover'), 'cover_days') if inputs.get('inventory_cover') is not None else None
    return n if n is not None and n <= LOW_STOCK_DAYS else None


def stock_clearance(cfg, today):
    """The person's clearance of a low-stock product, when it still holds on `today`, else None. The product file's
    stock_clearance: {"by": "Kim", "on": "2026-10-31", "why": "supply chain is on it", "until": "2026-11-07"} ("until"
    optional: STOCK_CLEARANCE_DAYS after "on"). B0SAMP0015, 2026-10-31: Kim cleared it because supply chain was on it."""
    c = (cfg or {}).get('stock_clearance')
    if not isinstance(c, dict) or not c.get('by') or not c.get('on'):
        return None
    on = lanes.lock_date(c.get('on'))
    if on is None:
        return None
    until = lanes.lock_date(c.get('until')) if c.get('until') else on + dt.timedelta(days=STOCK_CLEARANCE_DAYS)
    return dict(c, until=until.isoformat()) if until and on <= today <= until else None


def is_increase(x):
    """A row that adds spend: a promotion, a raise, a new SB video, a budget step up, or a budget or top of search that goes
    up. What the low-stock park holds (decision 174); a cut, a pause or a hold is never one."""
    t = x.get('type')
    if is_promotion(x) or is_raise(x) or t == 'New SB video campaign':
        return True
    if t == 'Budget step':
        return x.get('direction') == 'up'
    if t == 'Budget and top of search':
        up = lambda now, new: new is not None and (now is None or new > now)  # noqa: E731
        return up(x.get('budget_now'), x.get('budget')) or up(x.get('tos_now'), x.get('tos'))
    return False


def sqp_age_days(sqp_data_through, today):
    """How many days old the SQP is at the run (its oldest page's Meta.data_through), or None without a readable date.
    Information only since 2026-10-30 (Kim, decision 172): the run plans on the newest SQP Scale Insights has, however old,
    and the run log and summary say how old it was. Until then SQP over 10 days old stopped an Auto run (decision 168)."""
    through = lanes.lock_date(sqp_data_through) if sqp_data_through else None
    return (today - through).days if through else None


def stale_reason(inputs, enabled=False):
    """Why the product's inputs aren't usable for the auto lane, in words, each with what to pull again; None when they are.
    While the Auto lane is on, plan_lanes stops the run on it up front (decision 168); in shadow its rows are held.

    Only the inventory cover file is checked: while the product's Auto lane is on (`enabled`, its merged auto.enabled is
    exactly True), a missing or unreadable inventory_cover.json stops the run (E6); in shadow a missing file never does.
    The SQP's age is not a reason since 2026-10-30 (decision 172, Kim: "just take the latest SQP data that is available
    and use it"): sqp_age_days reports it. A recent price change holds nothing either (decision 168).
    """
    why = []
    inv_fix = 'save inventory_cover.json, {"cover_days": n}, in the run folder (references/data-pull.md, "Inputs for the lanes")'
    if inputs.get('inventory_cover') is not None:
        n = _reading(inputs['inventory_cover'], 'cover_days')
        if n is None:
            why.append(f"the inventory cover file doesn't say how many days of stock are left: {inv_fix}")
    elif enabled:
        why.append(f'the inventory cover file is missing (needed while the Auto lane is on): {inv_fix}')
    return '; '.join(why) or None


def onboarding_reason(cfg, mode, today):
    """Why the product counts as onboarding, in words; None when it doesn't. A missing takeover date fails safe."""
    reg = cfg.get('registry') or {}
    why = []
    if reg.get('stage') == 'onboarding':
        why.append('the registry still marks the product as onboarding')
    if mode == 'onboard':
        why.append('this is an onboarding run')
    since = reg.get('owner_since')
    start = lanes.lock_date(since) if since else None
    if not since:
        why.append('the registry has no date for when the AI took over its bids')
    elif start is None:
        why.append(f"the registry's date for when the AI took over its bids ({since}) can't be read")
    elif start > today:
        why.append(f'the registry says the AI takes over its bids on {since}, after this run')
    elif (today - start).days < ONBOARDING_DAYS:
        why.append(f"the AI took over this product's bids on {since}, less than {ONBOARDING_DAYS} days ago")
    return '; '.join(why) or None


# ----------------------------------------------------------------------------- locks and row ids
def _until(lock):
    return lock.get('until') if isinstance(lock, dict) else lock


def holds_longer(a, b):
    """Of two locks on one key, the one that holds longer; a date that can't be read holds until someone changes it."""
    def end(lock):
        return lanes.lock_date(_until(lock)) or dt.date.max
    return a if end(a) >= end(b) else b


# G2 (N2): how a decliner ranks, as dashboard.py approvals ranks signers (human_review.signer_level: Kim, then Lee,
# then anyone else who signed). Kept here because human_review imports this module; test_plan_lanes checks the two agree.
DECLINER_RANK = {'kim': 2, 'lee': 1}


def decliner_rank(by):
    return DECLINER_RANK.get(by.strip().lower(), 0) if isinstance(by, str) else 0


def merge_locks(a, b, today=None):
    """Of two locks on one key, the one that holds longer (holds_longer), except that (G2, N2) when both are declines,
    the other one is from a higher-ranked decliner, still holds on `today` (a date; None: assume it does) and holds the
    same moves (lanes.lock_blocks on the longer one's direction; a lock with no direction holds every move), the result
    names that decliner: who may approve the row again is set by the highest-ranked decline that still holds, never by a
    later, lower one. The result is a new dict (the longer lock with the higher decliner's by and on, and a reason that
    says both); neither lock is changed."""
    longer = holds_longer(a, b)
    other = b if longer is a else a
    if not (isinstance(longer, dict) and isinstance(other, dict)
            and longer.get('what') == 'decline' and other.get('what') == 'decline'):
        return longer
    if decliner_rank(other.get('by')) <= decliner_rank(longer.get('by')):
        return longer
    end = lanes.lock_date(_until(other))
    if today is not None and end is not None and end < today:
        return longer  # the higher decline no longer holds: the bar is the decline that does
    way = longer.get('direction')
    if way in lanes.DIRECTIONS and not lanes.lock_blocks(other, way):
        return longer  # the higher decline was of another move (a raise, against a declined cut)
    by = other['by'].strip()
    on = f" on {other['on']}" if other.get('on') else ''
    reason = f"{longer.get('reason') or 'declined by a person'}; {by} declined it too{',' if on else ''}{on}, so only " \
             f"{by if decliner_rank(by) == 2 else by + ' or Kim'} can approve it again"
    return dict(longer, by=by, on=other.get('on'), reason=reason)


MOVE_WORDS = {'up': 'a raise', 'down': 'a cut', 'pause': 'a pause', 'other': 'this change'}
# C3: what a creation creates, so one that went out is known by its search whatever row id it carried. A new or reused
# exact campaign creates the search's Sponsored Products exact campaign; a new Sponsored Brands video campaign its video
# keyword; a new exact keyword (a business invest search no B2B exact keyword held) its keyword in the team's B2B exact
# campaign. `applied` writes a create lock (kind 'create', with the search, and the row's owner_kind) for each one that
# goes out.
CREATION_FAMILY = {'New exact campaign': 'sp exact', 'Reuse exact campaign': 'sp exact', 'New SB video campaign': 'sb video',
                   'New exact keyword': 'keyword'}


def creation_key(ctype, search, owner_kind=None):
    """The key a search's creation is known by ('created:<family>:<search>'), or None for a row that creates nothing. A
    creation made from a business row (owner_kind 'business') is known by its search prefixed 'business:' (as
    lanes.search_lock_key keys its search), so it never holds the consumer creation of the same search."""
    family = CREATION_FAMILY.get(ctype)
    text = norm(str(search)) if search not in (None, '') else ''
    if text and owner_kind == 'business':
        text = f'{lanes.BUSINESS_LOCK_PREFIX}{text}'
    return f'created:{family}:{text}' if family and text else None


def created_search(entry):
    """The search a create lock records: its own `search`, else the search part of its row id
    ('<type>:<campaign>:<ad group>:<search>'); None when neither says."""
    if isinstance(entry.get('search'), str) and entry['search'].strip():
        return entry['search']
    parts = str(entry.get('id')).split(':')
    return parts[3] if len(parts) >= 4 and parts[3] else None


def _iso(value):
    d = lanes.lock_date(value) if isinstance(value, str) and value.strip() else None
    return d.isoformat() if d else None


def decided_on(entry, until, lock_weeks):
    """The SGT date a decision was made: its own `on` (dashboard.py writes it), else its `until` less `lock_weeks` weeks.
    None when neither can be read."""
    on = _iso(entry.get('on'))
    if on:
        return on
    end = lanes.lock_date(until)
    if end is None or not evidence._number(lock_weeks) or lock_weeks <= 0:
        return None
    return (end - dt.timedelta(weeks=lock_weeks)).isoformat()


def decision_lock(entry, lock_weeks=None):
    """One entry of the product file's `decisions` as a lock: {until, what, by, on, direction, reason}.

    `direction` is the move of the decided row ('up', 'down', 'pause', 'other'; lanes.direction), None when the entry
    doesn't carry a readable one, and such a lock holds every move (lanes.lock_blocks). The reason reads "decided by
    <who> on <date> (<what they did>); it holds until <date>, so a person decides". A create lock (kind 'create', C3:
    `applied` writes one when a creation goes out) reads "already created on <date> ...": its row is shown read-only."""
    until = entry.get('until') or 'further notice'
    what = entry.get('what') if isinstance(entry.get('what'), str) and entry['what'].strip() else None
    by = entry['by'].strip() if isinstance(entry.get('by'), str) and entry['by'].strip() else None
    way = entry.get('direction') if entry.get('direction') in lanes.DIRECTIONS else None
    on = decided_on(entry, until, lock_weeks)
    if entry.get('kind') == 'create':
        made = _iso(entry.get('created_on')) or on or 'an earlier run'
        if entry.get('by_hand') is True:  # G3: a keyword of a Sponsored Brands video build whose campaign went out without it
            camp = entry['campaign'] if isinstance(entry.get('campaign'), str) and entry['campaign'].strip() else None
            return dict(until=until, what=what, by=by, on=on, direction=way, kind='create',
                        reason=(f"its campaign{' ' + camp if camp else ''} was created on {made} without this keyword; add "
                                'the keyword to it by hand. Nothing is proposed for it, and approving it does nothing'))
        return dict(until=until, what=what, by=by, on=on, direction=way, kind='create',
                    reason=(f'already created on {made}' + (f' (approved by {by})' if by else '') + "; the data this run "
                            "read doesn't show it yet, so nothing is proposed for it and approving it does nothing"))
    if what == 'decline':
        did = f'declined {MOVE_WORDS[way]}' if way else 'declined this row'
    elif what == 'approve':
        did = f'approved {MOVE_WORDS[way]}, and this goes the other way' if way in ('up', 'down') else 'approved this row'
    else:
        did = 'a decision on this row'
    who = f"decided by {by or 'a person'}" + (f' on {on}' if on else '')
    return dict(until=until, what=what, by=by, on=on, direction=way,
                reason=f'{who} ({did}); it holds until {_lock_date_text(until)}, so a person decides')


def _moment(text):
    """An ISO timestamp as an aware UTC datetime, or None. A naive time reads as UTC."""
    if not isinstance(text, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def review_declines(reviews, lock_weeks, today_iso=None):
    """The dashboard's saved decisions (<run>/reviews.json: GET /api/reviews/<ASIN> as `dashboard.py reviews --save`
    stores it, every decision ever made on the product) as decline entries for lock_table: one {id, what, by, on, until}
    for each (item_id, row_id) whose latest signed decision is a decline, on any item (B2).

    Latest is by `at`, or by list order when the times tie or can't be read, as dashboard.py approvals reads them, except
    that (G2, N2) a later decline from a lower-ranked signer never replaces an earlier, higher one on the item: the entry
    names the highest-ranked decliner since Kim's last approval. Only a
    later approval signed by Kim cancels a decline (C5, concern b): anyone else's leaves it standing, the safe side of
    approvals' own reading (which ignores an approval below the row's level). An approval makes no lock here (approve
    locks come only from `applied`, once the row has gone out). `on` is the decline's Singapore date (the run's own day,
    `today_iso`, when its time can't be read) and `until` that date plus `lock_weeks` weeks, or 'further notice' when
    lock_weeks isn't a positive number. The entry has no direction: the saved decision doesn't say which way the row
    went, so it holds every move. It carries the review entry's owner_kind when the entry has one (a decision on a
    business row: lock_table keys its search per shopper kind); an entry without one is consumer."""
    latest, stamp = {}, {}
    for e in reviews:
        if not (isinstance(e, dict) and isinstance(e.get('row_id'), str) and e['row_id'] and isinstance(e.get('item_id'), str)
                and e.get('decision') in ('approve', 'decline') and isinstance(e.get('by'), str) and e['by'].strip()):
            continue
        if e['decision'] == 'approve' and e['by'].strip().lower() != 'kim':
            continue  # concern (b): only Kim's later approval cancels a saved decline
        key, at = (e['item_id'], e['row_id']), _moment(e.get('at'))
        if key in latest and at and stamp.get(key) and at < stamp[key]:
            continue  # an older decision listed after a newer one
        prev = latest.get(key)
        if (e['decision'] == 'decline' and prev is not None and prev['decision'] == 'decline'
                and decliner_rank(e['by']) < decliner_rank(prev['by'])):
            stamp[key] = at or stamp.get(key)
            continue  # G2: a later, lower-ranked decline never replaces the earlier, higher one on the item
        latest[key] = e
        stamp[key] = at or stamp.get(key)
    today = dt.date.fromisoformat(today_iso[:10]) if today_iso else dt.date.today()
    weeks = lock_weeks if evidence._number(lock_weeks) and lock_weeks > 0 else None
    out = []
    for e in latest.values():
        if e['decision'] != 'decline':
            continue
        at = _moment(e.get('at'))
        day = (at + SGT).date() if at else today
        entry = dict(id=e['row_id'], what='decline', by=e['by'].strip(), on=day.isoformat(),
                     until=(day + dt.timedelta(weeks=weeks)).isoformat() if weeks else 'further notice')
        if isinstance(e.get('owner_kind'), str) and e['owner_kind']:
            entry['owner_kind'] = e['owner_kind']
        out.append(entry)
    return out


def lock_table(cfg, lock_weeks=None, reviews=None, today_iso=None):
    """The rows a person's decision holds (spec section 6): ({key: lock}, problem), problem None when all is readable.

    From the product file's `decisions` ({id, what, by, until}, and optionally on, direction and owner_kind;
    decision_lock). A
    row_id locks that row; '<type>:<keyword or target id>' also locks that keyword or target on every row; an id without
    a type locks that keyword id, target id or search; a create lock (kind 'create') also holds its search's creation
    under creation_key, which assign puts on every row that would create that search again (C3). Locks on a search are per
    shopper kind (design 2026-10-21-b2b-lane-and-roles 4d): a decision with owner_kind 'business' holds its search as
    'business:<search>' (lanes.search_lock_key) and its creation under creation_key with the search prefixed the same way,
    so it never holds the consumer rows of the same search, and a consumer decision never holds the business ones; an id
    without a type that is an Amazon keyword or target id (all digits) still locks that id, which names one row of one
    kind already. Row-id, keyword-id and target-id locks are specific and do not change. `lock_weeks`
    (auto.lock_weeks) dates a decision that doesn't carry its own `on`. From `reviews`, the dashboard's saved decisions (<run>/reviews.json; None when the run has none):
    every decline the team made there, as review_declines reads it, keyed like a decision, whether or not anyone ran
    dashboard.py approvals on it (B2); a `reviews` that isn't a list can't be read. And from `proposed_rank_experiments`,
    whose searches are held in every direction: until the review date once a person approved the experiment, otherwise
    until a person decides it. Dismissed, declined or cancelled ones hold nothing. Where two locks fall on one key, the
    one that holds longer wins (holds_longer), except that (G2) two declines name the higher-ranked decliner while that
    decline still holds on `today_iso` (merge_locks): its rank sets who may approve the row again.
    """
    locks = {}
    today = lanes.lock_date(today_iso) if today_iso else None

    def hold(key, lock):
        if key in (None, ''):
            return
        k = lanes.lock_key(key)
        locks[k] = merge_locks(locks[k], lock, today) if k in locks else lock

    def hold_decision(d):
        ident, lock = str(d['id']), decision_lock(d, lock_weeks)
        kind, sep, rest = ident.partition(':')
        business = d.get('owner_kind') == 'business'
        if d.get('kind') == 'create':
            # C3: the search's creation, whatever its row id (per shopper kind)
            hold(creation_key(kind, created_search(d), d.get('owner_kind')), lock)
        if not sep:
            if business:
                hold(lanes.search_lock_key(dict(keyword=ident, owner_kind='business')), lock)
                if norm(ident).isdigit():
                    hold(norm(ident), lock)  # an Amazon keyword or target id: it names one business row already
            else:
                hold(norm(ident), lock)
            return
        hold(ident, lock)
        if ':' not in rest:
            hold(norm(rest), lock)

    decisions = cfg.get('decisions')
    if decisions is not None:
        if not isinstance(decisions, list) or not all(isinstance(d, dict) and d.get('id') not in (None, '') for d in decisions):
            return {}, UNREADABLE_DECISIONS
        for d in decisions:
            hold_decision(d)
    if reviews is not None:
        if not isinstance(reviews, list):
            return {}, UNREADABLE_REVIEWS
        for d in review_declines(reviews, lock_weeks, today_iso):
            hold_decision(d)
    pre = cfg.get('proposed_rank_experiments') or {}
    for r in (pre.get('rows') if isinstance(pre, dict) else pre) or []:
        if not isinstance(r, dict):
            continue
        status = str(r.get('status') or '').lower()
        if any(word in status for word in NOT_LOCKING):
            continue
        search = norm(r.get('keyword') or r.get('search') or '')
        if (r.get('approved_to_apply') is True or approved_status(status)) and r.get('review_on'):
            by = r.get('approved_by') if isinstance(r.get('approved_by'), str) and r['approved_by'].strip() else None
            hold(search, dict(until=r['review_on'], what='experiment', by=by and by.strip(),
                              on=_iso(r.get('approved_on')) or _iso(r.get('launched_on')), direction=None,
                              reason=f"a person approved a rank experiment on this search until {r['review_on']}"))
        else:
            hold(search, dict(until='further notice', what='experiment', by=None, on=None, direction=None,
                              reason='a rank experiment is proposed on this search; a person decides it first'))
    return locks, None


def stopped_at_stop_loss(entry):
    """True for an invest_history (or business_invest_history) entry the stop-loss ended: log_invest marks it stop_loss
    True since 2026-10-22, and an entry written before that says so in its stepped_down words ('the stop-loss ...')."""
    return entry.get('stop_loss') is True or str(entry.get('stepped_down') or '').startswith('the stop-loss')


def cooloff_table(cfg, today, days):
    """{search_lock_key: (stepped-down date, held-until date)} (ISO dates) of the searches the stop-loss stepped down less
    than `days` days before `today` (Kim, 2026-10-22: no re-investment by the Auto lane for 8 weeks after a step-down,
    auto.repromote_cooloff_days). Read from the product file's invest_history (consumer searches) and
    business_invest_history (business ones, keyed 'business:<search>'); the step-down date is the entry's `ended`, the
    latest one when a search ended more than once. An entry whose date can't be read holds nothing."""
    out = {}
    for key, business in (('invest_history', False), ('business_invest_history', True)):
        history = cfg.get(key)
        for entry in history if isinstance(history, list) else []:
            if not isinstance(entry, dict) or not entry.get('search') or not stopped_at_stop_loss(entry):
                continue
            ended = lanes.lock_date(entry.get('ended')) if isinstance(entry.get('ended'), str) else None
            if ended is None:
                continue
            until = ended + dt.timedelta(days=days)
            if today >= until:
                continue
            k = lanes.search_lock_key(dict(keyword=entry['search'], owner_kind='business' if business else None))
            if k not in out or out[k][0] < ended.isoformat():
                out[k] = (ended.isoformat(), until.isoformat())
    return out


def approved_status(status):
    """True when a rank experiment's status says a person approved it: its first word is 'approved' ('approved',
    'Approved by Kim', 'approved_to_apply'). 'not_approved', 'Not approved yet' and 'unapproved' are not."""
    words = str(status or '').lower().replace('_', ' ').replace('-', ' ').split()
    return bool(words) and words[0] == 'approved'


def row_id(x):
    """'<type>:<keyword_id|target_id|theme_id>', or '<type>:<campaign_id>:<ad_group_id>:<search>' for a row with none."""
    def have(k):
        return x.get(k) not in (None, '', 'None')
    for k in ('keyword_id', 'target_id', 'theme_id'):
        if have(k):
            return f"{x.get('type')}:{x[k]}"
    parts = [str(x[k]) if have(k) else '' for k in ('campaign_id', 'ad_group_id')]
    return ':'.join([str(x.get('type')), *parts, norm(str(x['keyword'])) if have('keyword') else ''])


STABLE_FIELDS = ('match', 'ad_group_id', 'campaign_id')  # what tells colliding rows apart, in this order


def _stable(x, field):
    v = x.get(field)
    return 'none' if v in (None, '', 'None') else str(v)


def _suffixed(prefix, rows, fields, ids):
    """Name every row of `rows` (which share the id `prefix`) into ids ({id(row): row_id}).

    The first field in `fields` whose values differ splits the rows, and each part takes ':<that value>'; a part that
    still holds several rows is split by the next field. Rows no stable field tells apart are numbered in plan order
    (the first keeps the id, the rest get ':2', ':3' ...)."""
    if len(rows) == 1:
        ids[id(rows[0])] = prefix
        return
    for k, field in enumerate(fields):
        values = [_stable(x, field) for x in rows]
        if len(set(values)) > 1:
            parts = defaultdict(list)
            for x, v in zip(rows, values):
                parts[v].append(x)
            for v, part in parts.items():
                _suffixed(f'{prefix}:{v}', part, fields[k + 1:], ids)
            return
    for n, x in enumerate(rows, 1):
        ids[id(x)] = prefix if n == 1 else f'{prefix}:{n}'


def assign_row_ids(changes):
    """Give every row a row_id that is unique in its plan and stays on the same row from one week to the next.

    Rows that share an id (row_id above) all take a suffix from the first stable field that tells them apart: the match
    type, then the ad group, then the campaign (':phrase', ':<ad_group_id>'), so the plan's order doesn't decide which
    row a lock lands on. Only rows none of those fields tell apart are numbered ':2', ':3' ... in plan order."""
    groups = defaultdict(list)
    for x in changes:
        groups[row_id(x)].append(x)
    ids = {}
    for base, rows in groups.items():
        _suffixed(base, rows, STABLE_FIELDS, ids)
    used = set()
    for x in changes:
        rid = name = ids[id(x)]
        n = 1
        while name in used:  # a suffixed id that happens to equal another row's: keep ids unique whatever happens
            n += 1
            name = f'{rid}:{n}'
        used.add(name)
        x['row_id'] = name


# ----------------------------------------------------------------------------- bands and promotions
def is_raise(x):
    """A bid row that goes up: a keyword or target bid, and (autonomous runs, 2026-10-22) a Sponsored Brands keyword bid,
    which takes the same caps and counts toward the run's automatic raises (lanes._sb_raise_lane)."""
    return (x['type'] in lanes.CUT_BID_TYPES and x.get('current') is not None and x.get('new') is not None
            and x['new'] > x['current'])


def is_business(x):
    """A row made from a business (Amazon Business) keyword. Any other owner_kind, or none, is consumer."""
    return x.get('owner_kind') == 'business'


def row_key(x):
    """The key a row's search forecast is kept under (a change or a re-rank row): its search, or 'business:<search>' for a
    business row, so a business invest never overwrites the consumer owner's numbers of the same search (design
    2026-10-21-b2b-lane-and-roles 4d). Consumer rows (owner_kind 'consumer' or none) key by the search alone."""
    return f"{lanes.BUSINESS_LOCK_PREFIX}{x['keyword']}" if is_business(x) else x['keyword']


def is_promotion(x):
    """A row judged as a promotion: lanes.PROMOTION_TYPES (a new or reused exact campaign, a Business invest), and a
    business New exact keyword (design 4d: it adds a business invest search, so it carries modelled spend, counts in the
    bands and the product's planned invest and heads its own bundle; until 2026-10-22 it was always a person's call, and since
    autonomous runs lanes.classify judges it as a promotion, on the ladder, once its campaign and ad group are known)."""
    return x.get('type') in lanes.PROMOTION_TYPES or (x.get('type') == 'New exact keyword' and is_business(x))


def promotion_spend(x):
    """The monthly spend a promotion adds to the product's band and Kim's running total: its group's
    (group_spend_month, on the head of a campaign's business invests) when it heads one, else its own."""
    return x['group_spend_month'] if 'group_spend_month' in x else x.get('modelled_spend_month')


def business_group_campaign(x):
    """The campaign whose one update a business invest row writes, as a string; None for any other row.

    Every Business invest row, and every business New exact keyword row with its ad group (one without writes nothing),
    as plan.business_campaign_rows reads them: their campaign's top of search and budget go out in one update
    (campaign_tos, campaign_budget), so the rows of one campaign are one group (controller ruling 6, 2026-10-21)."""
    if not is_business(x) or x.get('campaign_id') in (None, ''):
        return None
    if x.get('type') == 'Business invest' or (x.get('type') == 'New exact keyword' and x.get('ad_group_id')):
        return str(x['campaign_id'])
    return None


def band_rows(out, inputs, shared, profit):
    """{row_key: (re-rank row, monthly clicks)}: the re-rank rows the bands are priced from (spec section 4).

    The re-rank row as it is, or for a search SQP has no clicks for, the same row priced on SoldScope's monthly
    searches (inputs['soldscope']) x the product's market click rate (SQP clicks / SQP searches). No SQP clicks and
    no SoldScope volume means no clicks to price, so the band is 0. A business re-rank row (owner_kind 'business',
    plan.py: priced on its B2B keyword's own 90 days) is kept under its own key (row_key) as it is, with its own monthly
    B2B clicks.

    The invest searches plan.py defers (out['rerank_held']: kept at their live bid while their visibility or
    rank-experiment review is pending, so left out of the re-rank forecast) are priced here too: they still spend, so
    they count as invest spend already planned, never as room in the band."""
    ss = inputs.get('soldscope') or {}
    terms = {t['term']: t for t in out['terms']}
    volume = sum(t.get('sqp_volume') or 0 for t in terms.values())
    rate = sum(t.get('sqp_total_clicks') or 0 for t in terms.values()) / volume if volume else 0.0
    rows = {}
    for r in list(out['rerank']) + list(out.get('rerank_held') or []):
        key = row_key(r)
        if is_business(r):
            rows[key] = (r, r.get('month_clicks') or 0)
            continue
        t = terms.get(r['keyword']) or {}
        if t.get('sqp_total_clicks'):
            rows[key] = (r, t['sqp_total_clicks'] * 30 / (t.get('observed_days') or 84))
            continue
        clicks = (_reading(ss, r['keyword']) or 0) * rate
        if clicks <= 0:
            rows[key] = (r, 0)
            continue
        spend, orders, net, capped = rerank_cost(clicks, r['cpc'], r['budget'], t, shared['budgets']['rerank_click_share_target'], profit)
        rows[key] = (dict(r, month_clicks=round(clicks), spend=round(spend), orders=round(orders, 1), net=round(net),
                          capped=capped), clicks)
    return rows


def bundles(changes, opps=None):
    """A promotion's bundle (spec 5a): its duplicate exact pauses, the holding bids of those copies (copy_hold, decision
    135), its funnel negatives and budget row.

    Returns (members, in_bundle): members maps the index of each promotion in `changes` (is_promotion) that heads a
    bundle to the list of rows that belong to it (matched on its search), and in_bundle is the set of indexes of every
    row that is a member. The members share the promotion's lane, and human_review gives them its approval level.

    Bundles never cross shopper kinds (design 2026-10-21-b2b-lane-and-roles 4d): a member has the promotion's owner_kind
    (none and 'consumer' are the same kind). A business pause or negative shares a consumer promotion's search text but is
    judged on its own shoppers' conversion, so it never rides a consumer promotion, and a consumer row never rides a
    business one.

    The business invests of one campaign are one bundle (controller ruling 6, 2026-10-21; business_group_campaign): one
    campaign update carries their top of search and budget, so they go out together. Its head is the one with the highest
    opportunity, `opps` (each row's, in plan order; None reads the opportunity assign stamped on each row), compared at the
    0.1 assign stamps it at, plan order breaking ties; the others are its members, with the pauses and negatives of
    their searches."""
    if opps is None:
        opps = [x.get('opportunity') for x in changes]

    def rank(i):
        o = opps[i] if evidence._number(opps[i]) else None
        return (o is None, -round(o or 0, 1))

    heads = sorted((i for i, x in enumerate(changes) if is_promotion(x)), key=rank)  # stable: plan order breaks ties
    lead = {}
    for i in heads:
        cid = business_group_campaign(changes[i])
        if cid is not None:
            lead.setdefault(cid, i)
    members = defaultdict(list)
    in_bundle = set()
    for i in sorted(heads):
        p = changes[i]
        cid = business_group_campaign(p)
        if cid is not None and lead[cid] != i:
            continue  # rides its campaign's head
        group = {j for j in heads if j != i and cid is not None and business_group_campaign(changes[j]) == cid}
        searches = {p['keyword']} | {changes[j]['keyword'] for j in group}
        for j, x in enumerate(changes):
            if j == i:
                continue
            # a copy's holding bid (plan.py copy_hold, decision 135) rides the promotion that takes its search over
            bundled = x['type'] in BUNDLE_TYPES or (x['type'] == 'Bid change' and x.get('copy_hold') is True)
            if j in group or (is_business(x) == is_business(p) and bundled
                              and x.get('keyword') in searches and (x['type'] != 'Pause keyword' or x.get('match') == 'exact')):
                members[i].append(x)
                in_bundle.add(j)
    return members, in_bundle


def _lock_date_text(until):
    """A lock's end as the ISO date when it can be read, else as written ('further notice')."""
    d = lanes.lock_date(until)
    return d.isoformat() if d else str(until)


def stamp_locks(changes, members, locks, today_iso, bundle_locks):
    """Write `locked_until`, `decided_by`, `decided_on` and `decision` on every row a lock holds (lanes.blocking_lock:
    a lock holds a row only for the moves it blocks).

    A row is stamped when a lock holds it today, and, for each promotion in `bundle_locks` (index -> the lock that sent
    its lane to a person), on the promotion and every member of its bundle too, because a person decided one part of
    what is approved together. Rows no lock holds get none of these keys. A lock whose date can't be read is stamped as
    written, and where two locks hold one row the longer wins, with its who, when and what. decision is 'approve',
    'decline' or 'experiment' (a rank experiment's search); decided_by and decided_on are None when the lock doesn't say."""
    held = {}

    def hold(row, lock):
        k = id(row)
        held[k] = lock if k not in held else holds_longer(held[k], lock)

    for x in changes:
        lock = lanes.blocking_lock(x, locks, today_iso)
        if lock:
            hold(x, lock)
    for i, lock in bundle_locks.items():
        for row in [changes[i]] + members[i]:
            hold(row, lock)
    for x in changes:
        lock = held.get(id(x))
        if lock is not None:
            lock = lock if isinstance(lock, dict) else dict(until=lock)
            x.update(locked_until=_lock_date_text(lock.get('until')), decided_by=lock.get('by'),
                     decided_on=lock.get('on'), decision=lock.get('what'))


def _odd_fields(x, group, bud, placement=None, overrides=None):
    """[(row, field, want, text)] for each way a promotion (its own row and its bundle's budget rows) isn't the rulebook's
    standard one (spec 5a: $10/day Invest, $5/day Prove first, its exact campaign at 0% top of search), in the order
    promotion_odd reads them; [] when it is.

    With the standing rank policy on (`placement` is config.json's placement block and its rank_tos_standing is approved,
    Kim 2026-10-20) the standard top of search is the policy's for the row's role, +50% Invest and +30% Prove first,
    instead of 0%, and any other boost is still odd. A row the policy leaves held (placement_hold: a placement experiment,
    another bidding strategy) is judged as before.

    A business promotion lives in a campaign a person built, whose budget is never lowered (design 4b: the role's budget,
    or the campaign's live budget when that is higher), so its standard budget is max(budget_now, the role's) (controller
    ruling 9, 2026-10-21): a B2B campaign already above the standard is not odd for it. `overrides` is the product file's
    budget_overrides ({search: $/day}, keyed like the rows' keywords): a budget a person set for that search is its
    standard (decision 107, 2026-10-23)."""
    out = []
    role_std = {'Invest': bud['invest_per_day'], 'Prove first': bud['prove_per_day']}.get(x.get('role'))
    for r in [x] + [m for m in group if m['type'] == 'Budget and top of search']:
        std = (overrides or {}).get(norm(r.get('keyword') or x.get('keyword') or ''), role_std) if role_std is not None else None
        if std is not None and r.get('rank_budget_step') is not None:
            std = max(std, r['rank_budget_step'])   # a rank campaign's budget step is its standard (decision 174)
        want_budget = max(r.get('budget_now') or 0, std) if std is not None and is_business(r) else std
        if std is not None and r.get('budget') != want_budget:
            have = 'no budget' if r.get('budget') is None else f"a budget of ${r['budget']:g}/day"
            if want_budget != std:
                text = (f"it has {have}, not ${want_budget:g}/day (its campaign's live budget, above the standard "
                        f"${std:g}/day for {x['role']})")
            else:
                text = f"it has {have}, not the standard ${std:g}/day for {x['role']}"
            out.append((r, 'budget', want_budget, text))
        tos = r.get('tos')
        boost = 'an unknown boost' if tos is None else f'+{tos:g}%'
        policy = rank_tos(placement, r.get('role') or x.get('role'))
        want = 0 if policy is None or r.get('placement_hold') else policy
        if r['type'] == 'New exact campaign' and tos != want:
            if want == 0:
                out.append((r, 'tos', want, f'a new exact campaign starts at 0% top of search, and this one would start at {boost}'))
            else:
                out.append((r, 'tos', want, f'a new exact campaign starts at +{want:g}% top of search (the standing rank policy), '
                                            f'and this one would start at {boost}'))
        elif r['type'] != 'New exact campaign' and not r.get('placement_hold') and tos != want:
            if want == 0:
                out.append((r, 'tos', want, f'it would set top of search to {boost} instead of holding the live setting'))
            else:
                out.append((r, 'tos', want, f"it would set top of search to {boost} instead of the standing rank policy's +{want:g}%"))
    return out


def promotion_odd(x, group, bud, placement=None, overrides=None):
    """Why a promotion isn't the rulebook's standard one (_odd_fields), in words: the first way; None when it is."""
    fields = _odd_fields(x, group, bud, placement, overrides)
    return fields[0][3] if fields else None


def standardize(x, group, bud, placement=None, overrides=None):
    """Write a promotion (and its bundle's budget rows) at the rulebook's standard budget and top of search, in place, and
    say so in words; None when it already is. Decision 107 (Kim, 2026-10-23): bid and rank calls are the AI's, so a
    non-standard budget or boost is put right by the run instead of going to a person (until 2026-10-23 it went to a
    person). The row keeps what the planner had as budget_planned / tos_planned, and a new exact campaign's tos_bid follows
    its new boost."""
    fields = _odd_fields(x, group, bud, placement, overrides)
    if not fields:
        return None
    words = []
    for r, field, want, text in fields:
        r.setdefault(field + '_planned', r.get(field))
        r[field] = want
        if field == 'tos' and r.get('new') is not None and 'tos_bid' in r:
            r['tos_bid'] = round(r['new'] * (1 + want / 100), 2)
        words.append(text)
    return 'written at the standard budget and top of search (' + '; '.join(words) + ')'


def _member(m):
    """A bundle member in words, for the reason its promotion goes to a person."""
    if m['type'] == 'Pause keyword':
        return f"the pause of the duplicate keyword in {m.get('campaign')}"
    if m['type'] == 'Negative exact':
        return f"the negative in {m.get('campaign')}"
    if is_promotion(m):
        return f"the {m['type']} row of {m.get('keyword')}"
    return f"the budget change for {m.get('campaign')}"


def invest_guide(planned_month, guide):
    """(planned invest a month, above the guide) for the run summary (Kim, 2026-10-22, decision 99: "its ok to invest $1800
    to $2000 per ASIN per month ... don't cap the promotion", and "if spend is overboard, the humans will notice it and step
    in anyway"). A guide, never a gate: nothing is parked for it. `guide` is auto.invest_guide_month; one that isn't a
    number flags nothing. Until 2026-10-22 Kim's $600 a month (kim_product_month) sent a promotion past it to him."""
    readable = isinstance(guide, (int, float)) and not isinstance(guide, bool) and math.isfinite(guide)
    return round(planned_month, 2), bool(readable and planned_month > guide)


# ----------------------------------------------------------------------------- the lanes
def experiment_rows(changes, shared):
    """{row_id: why} for the rows on a live experiment's own campaigns: a campaign whose name holds one of
    placement.shape.experiment_name_markers (the overnight test's copies, "ON80 |" and since 2026-11-04 "ON50 |"). Those
    campaigns' bids and budgets are set by the experiment's own thread, so the AI run leaves them alone (they go to held/).
    The originals the test copied (experiment_files) stay AI-bid: only placement shaping skips them."""
    markers = [m.lower() for m in (((shared or {}).get('placement') or {}).get('shape') or {}).get('experiment_name_markers') or [] if m]
    if not markers:
        return {}
    out = {}
    for x in changes:
        name = (x.get('campaign') or '').lower()
        hit = next((m for m in markers if m in name), None)
        if hit and x.get('row_id'):
            out[x['row_id']] = (f"experiment campaign ({hit.strip().upper()} copy): its bids and budget belong to the "
                                f"experiment's own thread, so this run leaves it alone")
    return out


def assign(out, cfg, shared, mode, inputs, today_iso=None, now_utc=None):
    """Put every change in out['changes'] in a lane, price the bands and stamp apply_after. Changes `out` in place.

    `inputs` comes from plan.load_lane_inputs: soldscope ({search: monthly searches}), inventory_cover, price_change and
    reviews (the dashboard's saved decisions; each None when the file isn't in the run folder); plan.py adds no_reviews
    (C5: the reason the decisions weren't read), which sends every change to a person, except the rows the planner holds
    anyway (monitor), which stay held (N-new-4). Each row gains lane, lane_reason,
    confidence, confidence_text, opportunity, row_id and lane_unlocked (the lane it would have had without any lock; equal to lane when no lock held
    it). A row a lock holds (lanes.blocking_lock: a person's decision, for the moves it blocks, or a rank experiment)
    also gains locked_until (the ISO date, or the lock's own words when it has no date), decided_by, decided_on and
    decision, and so does every row of a promotion's bundle when the promotion or one of its parts is locked.
    Promotions (is_promotion) gain modelled_spend_month, own_band_month and modelled_net_month; the head of a campaign's
    business invests also gains group_spend_month (ruling 6). The bands are information only since decision 100 (Kim,
    2026-10-22: "we don't want to put a cap and hamper the autonomous engine"): a judged promotion gains over_invest_band
    (its spend goes past what is left of the product's band, lanes.over_invest_band) and over_loss_line (its own search's
    band is shrunk because it is modelled to lose more than auto.max_loss_month, lanes.loss_line_text), and so does a
    policy-only top-of-search row (over_loss_line); neither parks it.
    A business row is judged on its search's business record (term_of), its forecast kept under row_key, its locks and
    invested searches per shopper kind (design 2026-10-21-b2b-lane-and-roles 4d). E1: a cut or pause on a search the
    team invests in (the product's invest_log and this run's rank searches, or for a business row the business_invest_log
    and this run's business rank searches; lanes.invested_cut) gains invested_search True, outside a promotion's own bundle
    (log_invest reads it; since 2026-10-22 classify judges it like any cut); such a search no longer a rank search still counts in planned_invest_month_start, at its
    recent monthly ad spend (its 90-day ad spend / 3), because its campaign keeps spending. A capped raise keeps new_capped and new_proposed where the auto lane's cap is what
    gets written (settle). summary[0] gains lanes (counts), shadow, apply_after, stale_reason, onboarding_reason,
    planned_invest_month_start (the invest spend already planned) and max_raise_pct (the cap a raise may take in one run,
    which the preview names); out gains bands and band_product_month.

    Autonomous runs (Kim, 2026-10-22, decision 98): a stale product's rows are held (monitor), and summary[0] gains
    stock_reorder ({cover_days}, or None: stock cover of 14 days or less, one "For human" item, since only a person can
    reorder). summary[0] also gains planned_invest_month (planned_invest_month_start plus this run's promotions in the Auto
    lane: the product's planned invest a month once they go out), invest_guide_month and above_invest_guide (invest_guide:
    information only, decision 99; the Slack recap names it). When `inputs` carries `program` ({other_month, products}:
    autonomy.program_month, the planned invest of every other product file; plan.main always passes it), summary[0]
    gains program ({other_month, start_month, after_month, products}), information only; without it, None. summary[0]
    also gains invest_band_month (the product's band, out['band_product_month']), over_invest_band (the Auto promotions that
    went past it, by row_key), loss_line_month (auto.max_loss_month) and over_loss_line ([{search, modelled_net_month}] of
    the Auto rows over their search's loss line): information only, which the Slack recap names.
    A promotion and a standalone 'Budget and top of search' row go out at the role's standard budget and boost: a
    non-standard one is written at the standard (standardize; decision 107, 2026-10-23), a budget the product file's
    budget_overrides sets for the search being its standard; a stop-loss step-down and a season's boost-off are the
    rulebook's own and are not checked.
    A row that re-invests in a search the stop-loss stepped down less than auto.repromote_cooloff_days (56) ago is held
    (cooloff_table, lanes._cooloff_hold), and summary[0].repromote_cooloff names those searches with their held-until date.
    """
    today = dt.date.fromisoformat(today_iso) if today_iso else dt.date.today()
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    changes, s = out['changes'], out['summary'][0]
    # a budget a person set for a search (the product file's budget_overrides) is its standard budget (decision 107)
    overrides = {norm(k): v for k, v in ((cfg or {}).get('budget_overrides') or {}).items()}
    terms = {t['term']: t for t in out['terms']}
    profit = float(cfg['profit_per_unit'])
    a = dict(shared.get('auto') or {})
    a.update(cfg.get('auto') or {})
    shadow = not auto_enabled(shared, cfg)  # only an explicit true turns the auto lane on
    missing = [k for k in AUTO_KEYS if k not in a]
    stale = stale_reason(inputs, enabled=not shadow)  # E6: a missing inventory file counts when enabled
    if stale and not shadow:
        raise SystemExit(f"Nothing planned: {stale}. Then plan again (decision 168: a stale input stops the run up front "
                         'instead of holding every row).')
    onboarding = onboarding_reason(cfg, mode, today)
    locks, unreadable = lock_table(cfg, a.get('lock_weeks'), inputs.get('reviews'), today.isoformat())
    # the re-investment cool-off after a stop-loss step-down (Kim, 2026-10-22): auto.repromote_cooloff_days, 56 when unset
    cool_days = a.get('repromote_cooloff_days')
    cool_days = cool_days if evidence._number(cool_days) and cool_days >= 0 else lanes.REPROMOTE_COOLOFF_DAYS
    cooloff = cooloff_table(cfg, today, cool_days)

    # bands: what each invest search may spend a month, net of the product's invest searches not promoted this run. Keyed
    # by row_key: a business invest search is priced on its B2B keyword's own numbers under its own key (design
    # 2026-10-21-b2b-lane-and-roles 4d), so it never overwrites the consumer owner's numbers of the same search
    priced = band_rows(out, inputs, shared, profit)
    bands = {t: round(lanes.search_band(r, profit, a['max_loss_month']), 2) for t, (r, _) in priced.items()} if 'max_loss_month' in a else {}
    band_product = sum(bands.values())
    promoted = {row_key(x) for x in changes if is_promotion(x)}
    business_terms = {t['term']: t for t in out.get('business_terms') or []}
    # E1: the searches the team invests in, per shopper kind: the invest log and this run's rank searches for consumer
    # rows, the business invest log and this run's business rank searches for business rows (lanes.invested_cut). A logged
    # search no longer a rank search isn't priced (it is in no re-rank), but its campaign still spends: it counts at its
    # recent monthly ad spend (a business one at its B2B keyword's), so Kim's running total sees it
    log = cfg.get('invest_log')
    logged = {norm(str(k)) for k in log} if isinstance(log, dict) else set()
    logged.discard('')
    invested = frozenset(logged | {norm(str(t)) for t, r in terms.items() if r.get('role') == 'Rank'})
    business_log = cfg.get('business_invest_log')
    business_logged = {norm(str(k)) for k in business_log} if isinstance(business_log, dict) else set()
    business_logged.discard('')
    invested_business = frozenset(business_logged | {norm(str(t)) for t, r in business_terms.items() if r.get('role') == 'Rank'})
    logged_spend = (sum(float((terms.get(t) or {}).get('ad_spend') or 0) for t in logged if t not in priced)
                    + sum(float((business_terms.get(t) or {}).get('ad_spend') or 0) for t in business_logged
                          if row_key(dict(keyword=t, owner_kind='business')) not in priced)) / 3
    planned = sum(r['spend'] for t, (r, _) in priced.items() if t not in promoted) + logged_spend
    assign_row_ids(changes)
    # C3: a search whose creation already went out (a create lock, whatever row id it went out under) holds every row that
    # would create it again: the row is held, read-only, and never proposed as a new creation. Per shopper kind
    for x in changes:
        key = creation_key(x['type'], x.get('keyword'), x.get('owner_kind'))
        created = locks.get(lanes.lock_key(key)) if key else None
        if created is not None:
            k = lanes.lock_key(x['row_id'])
            locks[k] = holds_longer(locks[k], created) if k in locks else created
    for x in changes:
        x.pop('group_spend_month', None)  # set again below on the head of each campaign's business invests
        if is_promotion(x):
            # no clicks to price means no modelled spend: the reason then says it isn't sized against a band
            r, clicks = priced.get(row_key(x), (None, 0))
            x['modelled_spend_month'] = r['spend'] if r and clicks else None
            # its own search's band (loss-capped) and the modelled net behind it: information only since decision 100
            # (over_loss_line below); until then classify sent a promotion over it to a person
            x['own_band_month'] = bands.get(row_key(x)) if r and clicks else None
            x['modelled_net_month'] = r.get('net') if r and clicks else None
    # a live rank campaign's top of search set to the standing policy (lanes.policy_tos_only): the mark is the planner's
    # (placement_review.hold_defaults) and is kept only while top of search really is the policy. Judged like a promotion on
    # the evidence (its own search's band is information); it adds nothing to the running total: its spend is already in
    # `planned`
    for x in changes:
        if x.get('policy_tos_only') is True and rank_tos(shared.get('placement'), x.get('role')) != x.get('tos'):
            x['policy_tos_only'] = False
        if lanes.policy_tos_only(x):
            r, clicks = priced.get(row_key(x), (None, 0))
            x['modelled_spend_month'] = r['spend'] if r and clicks else None
            x['own_band_month'] = bands.get(row_key(x)) if r and clicks else None
            x['modelled_net_month'] = r.get('net') if r and clicks else None

    def term_of(x):
        """The record a row is judged on: none for a target; a business row's search's business record (its B2B keyword's
        own index, clicks and orders, plan.py's business_terms), never the consumer one; else the search's record."""
        if x['type'] in lanes.TARGET_TYPES:
            return None
        return (business_terms if is_business(x) else terms).get(x.get('keyword'))

    def opportunity_of(x):
        t = term_of(x)
        return evidence.opportunity(t.get('index'), t.get('sqp_volume'), t.get('observed_days')) if t else None

    # the data stage (data-stage design 4.4.1, 4.4.4 and 4.6; 2026-10-22): every promotion, and every policy-only top-of-search
    # row, carries its search's SQP observed days and head-term flag from its record, which lanes._stage_hold reads; the stage
    # dict (when early), the volatile-week text (when early only, and already None when --allow-volatile lifted it) and the
    # two-week bar go into Ctx. summary.stage and summary.volatile_week stay as the planner wrote them (reported at every stage)
    for x in changes:
        if is_promotion(x) or lanes.policy_tos_only(x):
            t = term_of(x) or {}
            x['sqp_observed_days'] = t.get('sqp_observed_days')
            x['relevance_flag'] = t.get('relevance_flag')
    stage_now = s.get('stage') or {}
    early_stage = stage_now if stage_now.get('stage') == 'early' else None
    volatile = (s.get('volatile_week') or None) if early_stage else None   # early only (spec 4.6; mature is 4.5)
    auto_min_days = (shared.get('stage') or {}).get('auto_min_observed_days')

    def settle(x, lane, reason, ev, lane_unlocked):
        if x.get('relevance_hold'):
            lane = lane_unlocked = 'monitor'
            reason = x['relevance_hold']
        p, kind = ev.get('confidence'), ev.get('confidence_kind')
        who = "the product's ad average" if x['type'] in lanes.TARGET_TYPES else 'the market'
        x.update(lane=lane, lane_reason=reason, lane_unlocked=lane_unlocked, confidence=None if p is None else round(p, 4),
                 confidence_text=None if p is None else evidence.sure_text(p, f'beats {who}' if kind == 'beats' else f'converts under 0.8x {who}'),
                 opportunity=None if ev.get('opportunity') is None else round(ev['opportunity'], 1))
        capped = ev.get('new_capped')
        if capped is not None and lane == 'auto' and not shadow:
            x['new_proposed'], x['new'] = x['new'], capped  # the auto lane writes the cap
            x['change'] = round(capped / x['current'] - 1, 3) if x['current'] else None
        elif capped is not None and (lane == 'auto' or ev.get('raises_used_up')):
            # a shadow run's automatic row, or a raise sent to a person only because the run's automatic raises ran out:
            # new stays the bid as proposed and new_proposed records it; payloads (plan.as_written) and dashboard
            # approvals write new_capped, the auto lane's call
            x['new_capped'], x['new_proposed'] = capped, x['new']

    # a promotion's bundle (spec 5a): its duplicate pauses, funnel negatives and budget row share its lane; the business
    # invests of one campaign are one bundle, headed by the one with the highest opportunity (ruling 6)
    opps = [opportunity_of(x) for x in changes]
    members, in_bundle = bundles(changes, opps)
    bundle_locks = {}  # promotion index -> the lock that sent its lane to a person (its own, or a member's)

    def biggest_first(rows):
        return sorted(rows, key=lambda i: (opps[i] is None, -(opps[i] or 0)))

    promos = [i for i, x in enumerate(changes) if is_promotion(x) and i not in in_bundle]  # the heads of the bundles
    # ruling 6 (controller, 2026-10-21): the head of a campaign's business invests carries the group's monthly spend
    # (group_spend_month; None when one of them has none), which the product's band and planned invest take; each row keeps
    # its own modelled_spend_month for the card and its own search's band
    group = {i: [m for m in members[i] if is_promotion(m)] for i in promos}
    for i in promos:
        if group[i]:
            spends = [changes[i].get('modelled_spend_month')] + [m.get('modelled_spend_month') for m in group[i]]
            changes[i]['group_spend_month'] = None if any(v is None for v in spends) else sum(spends)

    no_reviews = inputs.get('no_reviews')
    blocked = (unreadable or (f"the dashboard decisions weren't read ({no_reviews})" if no_reviews else None)
               or (f"the settings for automatic changes are incomplete (config.json and the product file have "
                   f"no {', '.join(missing)}), so a person decides" if missing else None))
    # N-new-4: when only the dashboard decisions are missing, everything is still judged as in a normal week; the rows the
    # planner holds anyway (monitor) stay held, and only the rows that would have gone out (auto) or gone to a person
    # (human) go to a person. The degraded mode must hold at least as much as a normal week.
    keep_monitor = bool(no_reviews) and not unreadable and not missing

    def settle_judged(x, lane, reason, ev, lane_unlocked):
        if keep_monitor and lane != 'monitor':
            settle(x, 'human', blocked, dict(opportunity=opportunity_of(x)), 'human')
        else:
            settle(x, lane, reason, ev, lane_unlocked)

    def judge_promotion(i, c):
        """(lane, reason, evidence, lock) for promotion `i` under Ctx `c`: classify, then a lock on one of its bundle's
        rows, a non-standard budget or top of search (no money level since decision 99). `lock` is the lock that sent it
        to a person (its own, or a member's), or None."""
        x = changes[i]
        lane, reason, ev = lanes.classify(x, term_of(x), c)
        lock = lanes.blocking_lock(x, c.locks, c.today)
        # only a promotion that would go out is checked: one the AI holds anyway (its "not yet", decision 107) stays held,
        # and a person is not asked about it because a member of its bundle is locked
        if lane == 'auto':
            held = next(((m, hit) for m in members[i] if (hit := lanes.blocking_lock(m, c.locks, c.today))), None)
            # a stale product's promotion, or one in its search's re-investment cool-off, stays held (monitor) whatever its
            # budget: nothing of it goes out this run
            if held:
                lock = held[1]
                lane, reason = 'human', f"{_member(held[0])} is part of this promotion and is locked: {held[1]['reason']}"
            elif not (c.stale or lanes._cooloff_hold(x, c)):
                # a non-standard budget or boost is written at the standard (decision 107; a person decided it until
                # 2026-10-23); a stale product's promotion, or one in its search's re-investment cool-off, stays held
                fixed = standardize(x, members[i], shared['budgets'], shared.get('placement'), overrides)
                if fixed:
                    reason = f'{reason}; {fixed}'
        return lane, reason, ev, lock

    def group_prefix(x):
        return f"part of the business invests of {x.get('campaign') or x.get('campaign_id')}"

    def judge_group(i, c):
        """(lane, reason, evidence, lock, {id(member): its own evidence}) for the head `i` of a bundle under Ctx `c`:
        judge_promotion, then (ruling 6) each other business invest of its campaign classified on its own evidence, on a
        copy of `c` so its judgement consumes nothing. The group's lane is the weakest of its rows' own lanes: a member a
        person must decide sends the whole group to a person, and a member held back (monitor) holds an automatic group
        back, each with that member's reason. A member passes the head's standard-budget and top-of-search check too
        (standardize, on its own row, since decision 107): a member with a budget override would otherwise ride an automatic head and the
        campaign update write its budget, where a consumer promotion with that override goes to a person (final review I1,
        2026-10-21). For any other bundle this is judge_promotion."""
        lane, reason, ev, lock = judge_promotion(i, c)
        own, weakest = {}, None
        for m in group[i]:
            m_lane, m_reason, m_ev = lanes.classify(m, term_of(m), dataclasses.replace(c))
            if m_lane != 'human':
                fixed = standardize(m, [], shared['budgets'], shared.get('placement'), overrides)
                if fixed:
                    m_reason = f'{m_reason}; {fixed}'
            own[id(m)] = m_ev
            if m_lane == 'human' and (weakest is None or weakest[1] != 'human'):
                weakest = (m, m_lane, m_reason)
            elif m_lane == 'monitor' and weakest is None:
                weakest = (m, m_lane, m_reason)
        if weakest and lane != 'human' and (weakest[1] == 'human' or lane == 'auto'):
            m, m_lane, m_reason = weakest
            what = 'needs a person' if m_lane == 'human' else 'is held back'
            lane, reason = m_lane, f"{group_prefix(changes[i])}: {m['keyword']} {what}: {m_reason}"
        return lane, reason, ev, lock, own

    # A scoped handoff leaves mixed campaigns solely with SI. Neither Auto nor a later approval may touch them. Found
    # before any row is judged, so a held row takes none of the run's automatic raises or band (Codex review, 2026-10-23)
    scope_holds = ownership_scope.blocked_rows(changes, cfg)
    # a live experiment's own campaigns (the overnight test's "ON80 |" / "ON50 |" copies, placement.shape
    # .experiment_name_markers): their bids and budgets belong to the experiment's own thread, so no AI row on them goes
    # out, in any lane (2026-11-04). Held like a scope hold, whole with a promotion bundle
    experiment_holds = experiment_rows(changes, shared)
    for rid, why in experiment_holds.items():
        scope_holds.setdefault(rid, why)
    for i, group_rows in members.items():
        parts = [changes[i]] + group_rows
        held = next((scope_holds[x['row_id']] for x in parts if x['row_id'] in scope_holds), None)
        if held:
            for x in parts:
                scope_holds.setdefault(x['row_id'], f'ownership scope: promotion bundle held; {held}')

    if blocked and not keep_monitor:
        for x in changes:
            settle(x, 'human', blocked, dict(opportunity=opportunity_of(x)), 'human')
    else:
        ctx = lanes.Ctx(auto=a, profit_per_unit=profit, stale=stale, onboarding=bool(onboarding), onboarding_reason=onboarding,
                        locks=locks, today=today.isoformat(), band_left_month=band_product - planned,
                        # null: no count cap (Kim, 2026-10-29, decision 164); each raise keeps its own checks
                        raises_left=int(a['max_raises']) if a.get('max_raises') is not None else 10 ** 9, invested=invested,
                        season_switch=(s.get('season') or {}).get('switch'), invested_business=invested_business,
                        early_stage=early_stage, volatile=volatile,
                        auto_min_observed_days=int(auto_min_days if auto_min_days is not None else lanes.Ctx.auto_min_observed_days),
                        cooloff=cooloff)
        raises = [i for i, x in enumerate(changes) if is_raise(x)]
        judged = in_bundle | set(promos) | set(raises)  # bundle members are settled with their promotion
        rest = [i for i in range(len(changes)) if i not in judged]
        # lane_unlocked (A3): the lane a row would have had without any lock, judged on the same running totals, so the
        # shadow gate can count what the planner wanted; the totals follow the lane the row actually gets
        for i in biggest_first(promos) + biggest_first(raises) + rest:
            x = changes[i]
            if x['row_id'] in scope_holds:
                # held whole with its bundle (a held member holds its promotion above); judged on nothing
                for row in [x] + (members[i] if i in members else []):
                    settle_judged(row, 'monitor', scope_holds[row['row_id']], dict(opportunity=opportunity_of(row)), 'monitor')
                continue
            if is_promotion(x):
                # information only (decision 100): how it sits against what is left of the product's band, and each of its
                # campaign's business invests against its own search's loss line
                x['over_invest_band'] = lanes.over_invest_band(x, ctx)
                for row in [x] + group[i]:
                    row['over_loss_line'] = lanes.loss_line_text(row, a) is not None
                lane, reason, ev, lock, own = judge_group(i, ctx)
                unlocked = lane
                if lock:
                    bundle_locks[i] = lock
                    unlocked = judge_group(i, dataclasses.replace(ctx, locks={}))[0]
                if lane == 'auto':
                    spend = promotion_spend(x)
                    # Decision 100 permits an unsized promotion; keep its forecast unknown.
                    if spend is not None:
                        ctx.band_left_month -= spend
                settle_judged(x, lane, reason, ev, unlocked)
                # the members settle with the head's lane; a business invest of the group keeps its own evidence
                prefix = group_prefix(x) if group[i] else f"part of the promotion of {x['keyword']}"
                said = reason if reason.startswith(prefix) else f'{prefix}: {reason}'
                for m in members[i]:
                    settle_judged(m, lane, said, {k: v for k, v in own.get(id(m), ev).items() if k != 'new_capped'}, unlocked)
                continue
            if lanes.policy_tos_only(x):
                x['over_loss_line'] = lanes.loss_line_text(x, a) is not None   # information only (decision 100)
            lane, reason, ev = lanes.classify(x, term_of(x), ctx)
            unlocked = lane
            if lanes.blocking_lock(x, ctx.locks, ctx.today):
                unlocked = lanes.classify(x, term_of(x), dataclasses.replace(ctx, locks={}))[0]
            # a budget or top-of-search change outside a promotion goes out at its role's standard budget and boost
            # (decision 107: written at the standard; a person decided a non-standard one until 2026-10-23)
            if (lane == 'auto' and x['type'] == 'Budget and top of search' and not lanes.policy_tos_only(x)
                    and not x.get('stop_loss_step_down') and not x.get('season_harvest') and not x.get('placement_policy')):
                fixed = standardize(x, [], shared['budgets'], shared.get('placement'), overrides)
                if fixed:
                    reason = f'{reason}; {fixed}'
            if lane == 'auto' and is_raise(x):
                ctx.raises_left -= 1
            settle_judged(x, lane, reason, ev, unlocked)

    stamp_locks(changes, members, locks, today.isoformat(), bundle_locks)
    # low stock (Kim, 2026-10-31, decision 174): under LOW_STOCK_DAYS of cover every increase waits For human, with its
    # promotion's bundle, until a person clears the product (stock_clearance); cuts, pauses and holds still go out
    cover, cleared = stock_cover(inputs), stock_clearance(cfg, today)
    stock_held = []
    if cover is not None and cleared is None:
        why = (f"low stock: {cover:g} days of cover, {LOW_STOCK_DAYS} or fewer, so an increase waits for a person: approve it, "
               f"or clear the product (stock_clearance in its file) once restock is on the way (decision 174)")
        for i, x in enumerate(changes):
            if i in in_bundle or x.get('lane') != 'auto' or not is_increase(x):
                continue
            for row in [x] + (members[i] if is_promotion(x) else []):
                if row.get('lane') == 'auto':
                    settle(row, 'human', f"{why}. Otherwise: {row.get('lane_reason')}", dict(opportunity=opportunity_of(row)),
                           'human')
                    row['low_stock_hold'] = cover
                    stock_held.append(row['row_id'])
    # a search's new SB video, and the holding bids of its older SB copies, wait with the search's exact campaign when the
    # ladder holds it (Kim, 2026-10-25, decision 135: three orders before a search gets its own campaign and its video)
    held_promotion = {}
    for x in changes:
        if is_promotion(x) and not is_business(x) and x.get('lane') != 'auto':
            held_promotion.setdefault(x.get('keyword'), x)
    for x in changes:
        p = held_promotion.get(x.get('keyword'))
        if p is None or x.get('lane') != 'auto' or not follows_sb_video(x):
            continue
        settle(x, p['lane'], f"waits with its search's exact campaign ({p['row_id']}): {p.get('lane_reason')}",
               dict(opportunity=opportunity_of(x)), p['lane'])
    # and an older SB copy's holding bid waits with its search's new video when the video itself is held (a missing video
    # asset sends it to a person), so the copy keeps serving at its bid until the video can launch (2026-10-26)
    held_video = {x.get('keyword'): x for x in changes if x['type'] == 'New SB video campaign' and x.get('lane') != 'auto'}
    for x in changes:
        v = held_video.get(x.get('keyword'))
        if v is None or x.get('lane') != 'auto' or x['type'] == 'New SB video campaign' or not follows_sb_video(x):
            continue
        settle(x, v['lane'], f"waits with its search's new SB video ({v['row_id']}): {v.get('lane_reason')}",
               dict(opportunity=opportunity_of(x)), v['lane'])
    # E1: the flag log_invest reads to step the search down once a person sent the row out (it was also Lee's level
    # until 2026-10-22), on every such row whatever its lane (since autonomous runs such a cut applies on its own, and
    # only a person's cut, or the stop-loss step-down, takes the search out of the invest log). A promotion's own bundle is
    # left out: its duplicate pause moves the search into its new campaign (spec 5a)
    for i, x in enumerate(changes):
        if i not in in_bundle and lanes.invested_cut(x, invested, invested_business):
            x['invested_search'] = True
    # the scope holds found above, stamped on every row whatever path settled it (a blocked run sends all to a person)
    for x in changes:
        x.pop('ownership_scope_blocked', None)
        x.pop('experiment_hold', None)
        if x['row_id'] in scope_holds:
            x['experiment_hold' if x['row_id'] in experiment_holds else 'ownership_scope_blocked'] = scope_holds[x['row_id']]
            x['lane'] = x['lane_unlocked'] = 'monitor'
            x['lane_reason'] = scope_holds[x['row_id']]
    if 'ownership_scope' in cfg:
        s['ownership_scope_holds'] = {k: v for k, v in scope_holds.items() if k not in experiment_holds}
    s['experiment_holds'] = experiment_holds
    counts = Counter(x['lane'] for x in changes)
    # the investment guide and the program total: information only (Kim, 2026-10-22, decision 99), never a gate
    went = sum(promotion_spend(changes[i]) or 0 for i in promos if changes[i].get('lane') == 'auto')
    planned_month, above_guide = invest_guide(planned + went, a.get('invest_guide_month'))
    program = inputs.get('program') if isinstance(inputs.get('program'), dict) else None
    program_out = None
    if program is not None:
        other = float(program['other_month']) if evidence._number(program.get('other_month')) else None
        program_out = dict(other_month=None if other is None else round(other, 2),
                           start_month=None if other is None else round(other + planned, 2),
                           after_month=None if other is None else round(other + planned_month, 2),
                           products=program.get('products'))
    # the product's band and the $60 loss line for one search: information only (decision 100), never a gate
    over_band = [row_key(changes[i]) for i in biggest_first(promos)
                 if changes[i].get('lane') == 'auto' and changes[i].get('over_invest_band')]
    over_loss = [dict(search=row_key(x), modelled_net_month=None if x.get('modelled_net_month') is None
                      else round(x['modelled_net_month'], 2))
                 for x in changes if x.get('lane') == 'auto' and x.get('over_loss_line')]
    s.update(lanes={k: counts.get(k, 0) for k in ('auto', 'human', 'monitor')}, shadow=shadow,
             apply_after=lanes.us_date(now_utc).isoformat(), execution_policy="during_audit_any_day", stale_reason=stale, sqp_age_days=sqp_age_days(s.get('sqp_data_through'), today),
             onboarding_reason=onboarding,
             planned_invest_month_start=round(planned, 2), max_raise_pct=a.get('max_raise_pct'),
             planned_invest_month=planned_month, invest_guide_month=a.get('invest_guide_month'),
             above_invest_guide=above_guide,
             invest_band_month=round(band_product, 2), over_invest_band=over_band,
             loss_line_month=a.get('max_loss_month'), over_loss_line=over_loss,
             stock_reorder=None if cover is None else dict(cover_days=cover, held=stock_held,
                                                           cleared=None if cleared is None else
                                                           {k: cleared.get(k) for k in ('by', 'on', 'until', 'why')}),
             program=program_out,
             repromote_cooloff={k: until for k, (_, until) in sorted(cooloff.items())})
    out['bands'], out['band_product_month'] = bands, round(band_product, 2)
    return out
