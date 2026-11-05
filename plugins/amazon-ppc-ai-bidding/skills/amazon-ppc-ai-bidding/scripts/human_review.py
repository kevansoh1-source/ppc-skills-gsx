"""Evidence-backed human decisions; never writes listings, prices or ad settings."""
import copy
import datetime as dt
import math
import re
from collections import Counter

import lanes
import plan_lanes
from growth import CLOSED_STATUSES as GROWTH_CLOSED, PASS_FIRST, PASS_SECOND
from market_review import sufficiently_sampled

# copy_pushed is the For Growth item's own step (Growth's "Copy pushed": the copy is submitted, the listing change not
# seen yet; launch design 4e), so only a growth item may hold it
STATUSES = ('open', 'in_progress', 'waiting_approval', 'copy_pushed', 'resolved', 'dismissed')
ACTIVE = STATUSES[:4]
GROWTH_ONLY_STATUSES = ('copy_pushed',)
# 'growth': the For Growth item (id for-growth, growth.py), Growth's listing pass with its hand-over block; not an approval
KINDS = ('listing', 'price', 'bid', 'growth')
GAP_ID = 'listing-conversion-gap'
GAP_SUPERSEDED = 'Superseded by the For Growth item (design 2026-10-20)'
# Who has to say yes, lowest to highest (sweep-playbook "Approval levels", 2026-10-22). A bid row starts at 'owner' or
# 'Kim' (row_levels); 'Lee' is the team leader's level, for listing items and for a row she declined. A growth item
# has no level (R32: it is Growth's work, not an approval).
LEVELS = ('owner', 'Lee', 'Kim')


def sgt_today():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()


def _validate_bid_rows(identity, item):
    """The checks of a kind 'bid' item: a non-empty rows list, and in every row a row_id, a type and an approval level.

    A closed item (not ACTIVE) may have had its rows dropped for a summary (_compact_rows); then it needs `rows_count`
    instead. An active item always needs its rows.

    Returns the item's approval level: the higher of the one it carries (when readable) and the highest level among its
    rows, so a bid item is never reset to the listing or price rule and never reads lower than its hardest row. A
    summary with no readable level falls back to the highest level (the safe one)."""
    rows = item.get('rows')
    declared = item.get('approval_required')
    declared = declared if declared in LEVELS else None
    if item['status'] not in ACTIVE and (rows is None or rows == []):
        count = item.get('rows_count')
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f'{identity}: a closed bid item without rows needs rows_count')
        return declared or LEVELS[-1]
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'{identity}: a bid item needs a non-empty rows list')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'{identity}: each bid row must be an object')
        if not isinstance(row.get('row_id'), str) or not row['row_id'].strip():
            raise ValueError(f'{identity}: each bid row needs a row_id')
        if not isinstance(row.get('type'), str) or not row['type'].strip():
            raise ValueError(f'{identity}: each bid row needs a type')
        if row.get('approval_required') not in LEVELS:
            raise ValueError(f'{identity}: bid row approval_required must be one of {", ".join(LEVELS)}')
    levels = [row['approval_required'] for row in rows] + ([declared] if declared else [])
    return max(levels, key=LEVELS.index)


def _validate_growth(identity, item):
    """The checks of a kind 'growth' item (growth.build_item): its growth block with the pass tag and the hand-over block
    in both of Growth's forms, the markdown (growth.block_md) and the JSON (growth.block)."""
    g = item.get('growth')
    if not isinstance(g, dict):
        raise ValueError(f'{identity}: a growth item needs its growth block')
    if g.get('pass') not in (PASS_FIRST, PASS_SECOND):
        raise ValueError(f'{identity}: growth.pass must be "{PASS_FIRST}" or "{PASS_SECOND}"')
    if not isinstance(g.get('block_md'), str) or not g['block_md'].strip():
        raise ValueError(f'{identity}: growth.block_md (the markdown block) is required')
    if not isinstance(g.get('block'), dict):
        raise ValueError(f'{identity}: growth.block (the JSON block) is required')


def validate(items):
    if not isinstance(items, list):
        raise ValueError('human_review must be a list')
    result, seen = [], set()
    for original in items:
        item = copy.deepcopy(original)
        identity = item.get('id', '')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', identity) or identity in seen:
            raise ValueError('Each human review needs a unique stable lowercase id')
        seen.add(identity)
        if item.get('kind') not in KINDS:
            raise ValueError(f'{identity}: kind must be listing, price, bid or growth')
        if item.get('status', 'open') not in STATUSES:
            raise ValueError(f'{identity}: unsupported status')
        if item.get('status') in GROWTH_ONLY_STATUSES and item['kind'] != 'growth':
            raise ValueError(f"{identity}: status {item['status']} is the For Growth item's only")
        for field in ('title', 'reason', 'action', 'source', 'window'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f'{identity}: {field} is required')
        if item.get('priority', 'normal') not in ('high', 'normal', 'low'):
            raise ValueError(f'{identity}: unsupported priority')
        item.setdefault('status', 'open')
        item.setdefault('priority', 'normal')
        item.setdefault('owner', None)
        item.setdefault('evidence', [])
        item.setdefault('ai_review', dict(phase='research', missing=['AI relevance and Amazon market/offer research not completed.']))
        if not isinstance(item['ai_review'], dict) or item['ai_review'].get('phase') not in ('research', 'human_ready', 'monitor'):
            raise ValueError(f'{identity}: unsupported AI review phase')
        if not isinstance(item['evidence'], list):
            raise ValueError(f'{identity}: evidence must be a list')
        if item['kind'] == 'growth':
            _validate_growth(identity, item)
            # not an approval (R32): Growth runs the pass with the block, nobody signs it, so it has no approval level
            item.pop('approval_required', None)
        elif item['kind'] == 'bid':
            item['approval_required'] = _validate_bid_rows(identity, item)
        else:
            # a price is Kim's; a listing item (revamp the images, improve the listing or offer) is a harder product call,
            # the team leader's (Kim, 2026-10-22)
            item['approval_required'] = 'Kim' if item['kind'] == 'price' else 'Lee'
        price = item.get('price') or {}
        if item['kind'] == 'price' and price.get('proposed') is not None:
            for field in ('current', 'proposed', 'profit_per_unit_current', 'profit_per_unit_proposed'):
                value = price.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f'{identity}: price.{field} must be a finite number')
            if price['current'] <= 0 or price['proposed'] <= 0:
                raise ValueError(f'{identity}: prices must be positive')
            for field in ('economics_as_of', 'economics_source', 'comparison_source', 'rollback', 'review_on'):
                if not price.get(field):
                    raise ValueError(f'{identity}: price.{field} is required for a numeric price proposal')
            dt.date.fromisoformat(price['economics_as_of'])
            dt.date.fromisoformat(price['review_on'])
            price['change'] = round(price['proposed'] - price['current'], 2)
            price['profit_change'] = round(price['profit_per_unit_proposed'] - price['profit_per_unit_current'], 2)
            price['margin_current'] = price['profit_per_unit_current'] / price['current']
            price['margin_proposed'] = price['profit_per_unit_proposed'] / price['proposed']
            item['price'] = price
        result.append(item)
    return result


def _window(plan, date):
    return plan.get('terms_window') or 'SQP up to 12 weeks / ads 90 days; saved sources for ' + str((plan.get('summary') or [{}])[0].get('run', date))


def propose(plan, product, shared, date):
    thresholds = shared['thresholds']
    weak, strong = [], []
    for term in plan.get('terms', []):
        if not sufficiently_sampled(term, thresholds):
            continue
        sqp = term['index_basis'] == 'SQP'
        clicks = term.get('sqp_our_clicks', 0) if sqp else term.get('ad_clicks', 0)
        orders = term.get('sqp_our_purchases', 0) if sqp else term.get('ad_orders', 0)
        evidence = dict(query=term['term'], basis=term['index_basis'], clicks=clicks, purchases=orders,
                        our_cvr=term.get('cvr_est'), market_cvr=term['market_cvr'], index=term['index'],
                        note='Smoothed decision CVRs/index; ad fallback and SQP have different traffic mixes.')
        if term['index'] < thresholds['index_hold'] and clicks >= thresholds['trim_min_clicks']:
            weak.append(evidence)
        elif term['index'] >= thresholds['index_invest'] and orders >= thresholds['invest_min_purchases']:
            strong.append(evidence)
    window = _window(plan, date)
    source = 'Scale Insights SQP + search-term reports; same-query market benchmark; existing rulebook smoothing.'
    base = dict(status='open', priority='normal', first_seen=date, last_seen=date, origin='sweep', source=source, window=window)
    items = []
    if weak:
        items.append(dict(base, id='listing-conversion-gap', kind='listing', title='Assess query fit before diagnosing conversion',
                          reason=f'{len(weak)} sufficiently sampled searches fall below the existing conversion-index threshold. Product fit still needs AI review: broad intent is not proof the listing is defective.',
                          action='AI first: classify query relevance, rank relevant opportunities by IDX × search volume, inspect Amazon competitors and explain direct-fit gaps versus broad-intent mismatch.',
                          evidence=sorted(weak, key=lambda row: row['index'])[:10], evidence_count=len(weak)))
    monitor = product.get('monitor') or {}
    profit = monitor.get('profit')
    if weak or (strong and isinstance(profit, (int, float)) and profit < 0):
        direction = 'review'
        items.append(dict(base, id='price-positioning', kind='price', title='Research price and offer positioning',
                          reason='Conversion weakness merits a comparable-pack price check, not an automatic discount.' if weak else f'Conversion beats the market on {len(strong)} sampled searches while product profit after ads is negative ({monitor.get("start")} to {monitor.get("end")}). Verify whether price or ad cost is the constraint.',
                          action='Compare live effective prices for like-for-like packs and current fees. Suggest an increase, decrease or no change, with contribution-margin scenarios, review date and rollback. Kim must approve any actual price change.',
                          price=dict(direction=direction, current=product.get('price'), proposed=None, economics_as_of=product.get('economics_as_of')),
                          evidence=(weak or strong)[:10], evidence_count=len(weak or strong)))
    return validate(items)


# --- the per-ASIN "Bids" item --------------------------------------------------------------------------------------
BIDS_PREFIX = 'bids-'
BIDS_ACTION = ('Approve or decline each row. Approved rows are applied during the audit through '
               'MarketplaceAdPros.')
# Row types whose approval level comes from the type alone: Kim keeps the listing price (sweep-playbook "Approval
# levels"). Every other row is the book owner's, unless row_levels raises it to Kim's.
KIM_TYPES = ('Listing price',)


def row_levels(plan):
    """Who has to approve each change in a plan, as a list of LEVELS in plan order: 'owner' or 'Kim', never 'Lee'.

    Since 2026-10-22 (Kim, decision 95) the book owner approves every bid call on their own products. Kim keeps, from
    the rows' own fields: a 'Listing price' row, and (autonomous runs, decision 98) a Scale Insights row beyond the
    standard AI setup (si_beyond_standard). The lane reason decides nothing. Everything else is the owner's: bid and
    target-bid changes, harvest prices, promotions and their bundles whatever their monthly spend, cuts and pauses of
    Invest, Prove-first or invested searches, stop-loss reviews, 'Budget and top of search' rows, budget steps of any
    size, Sponsored Brands rows, Scale Insights rules and setup, and every row of an onboarding product or of a seasonal
    product's phase switch. Until 2026-10-22 a promotion past the product's $600 a month (past_kim_level), with its
    bundle, was Kim's; decision 99 made money a guide, not a gate ("we don't want to put a cap and hamper the
    autonomous engine"), so no row is Kim's for its spend. Lee, the team leader, keeps the harder product calls
    (listing items, validate) and the rows she declined (propose_bids raises a held row to its decliner's level); no plan
    row starts at her level."""
    changes = plan.get('changes') or []
    kim = LEVELS.index('Kim')
    return [LEVELS[kim if x.get('type') in KIM_TYPES or x.get('si_beyond_standard') else 0] for x in changes]


def _n(count, noun):
    return f"{count} {noun}{'' if count == 1 else 's'}"


def signer_level(by):
    """The level a signer's name holds (E3), as dashboard.py approvals reads names: 'Kim' and 'Lee' by name, trimmed
    and in any case; anyone else, and no name at all, 'owner'."""
    name = by.strip().lower() if isinstance(by, str) else ''
    return {'kim': 'Kim', 'lee': 'Lee'}.get(name, 'owner')


# A held row's lock, as plan_lanes stamps it on the plan's change (decided_by, decided_on, decision), under the item row's own
# names: the dashboard server writes decision and decided_by on a row when someone decides it there, so the lock must not
# share those names. item-row name -> plan-change name.
LOCK_ROW_FIELDS = (('locked_until', 'locked_until'), ('lock_by', 'decided_by'), ('lock_on', 'decided_on'), ('lock_decision', 'decision'))
# E2 (I2): what a row commits beyond its bid, copied when the change has it, so the card shows it and an approval's `seen`
# covers it. A promotion always carries its budget and modelled_spend_month (None when the plan has none), so the card
# shows what it commits.
MONEY_ROW_FIELDS = ('budget_now', 'budget', 'tos_now', 'tos')
# A business invest row's campaign-wide values (plan.stamp_business_campaigns): what its campaign's one update writes.
CAMPAIGN_WIDE_FIELDS = (('tos', 'campaign_tos'), ('budget', 'campaign_budget'))


def card_money(x):
    """The MONEY_ROW_FIELDS a row commits, as its card shows them. A business invest row (Business invest, or a business
    New exact keyword with its ad group) shows the top of search and budget its campaign update writes, campaign_tos and
    campaign_budget, when the planner stamped them, not its own role's: a Prove first row riding an Invest in one campaign
    writes the Invest's +50% (spec 9b, ruling 19). budget_now and tos_now stay the live ones. dashboard.py's seen_check
    reads a plan row through this too, so an approval of what the card showed is compared with what goes out."""
    out = {k: x[k] for k in MONEY_ROW_FIELDS if k in x}
    out.update({field: x[wide] for field, wide in CAMPAIGN_WIDE_FIELDS if wide in x})
    return out


def _bid_row(x, level):
    row = dict(row_id=x.get('row_id'), keyword=x.get('keyword') or x.get('item'), type=x.get('type'), role=x.get('role'),
               current=x.get('current'), new=x.get('new'), orders90=x.get('orders90'), clicks90=x.get('clicks90'),
               confidence_text=x.get('confidence_text'), opportunity=x.get('opportunity'),
               lane_reason=x.get('lane_reason'), approval_required=level, lane=x.get('lane'),
               lane_unlocked=x.get('lane_unlocked', x.get('lane')))
    if x.get('new_capped') is not None:
        row['new_capped'] = x['new_capped']  # what the auto lane would write, on a shadow run's automatic rows
    money = card_money(x)
    row.update(money)
    if plan_lanes.is_promotion(x) or lanes.policy_tos_only(x):  # the latter carries a modelled spend the card must show
        row.update(budget=money.get('budget'), modelled_spend_month=x.get('modelled_spend_month'))
    if x.get('locked_until'):
        row.update({name: x.get(field) for name, field in LOCK_ROW_FIELDS})  # who decided it, when, and what, from the lock that holds it
    return row


def propose_bids(plan, date):
    """The one "Bids" item of a run, or None when it would have no rows at all.

    Enabled mode (the Auto lane on: autonomous runs, Kim 2026-10-22, decision 98) lists only the changes in the human
    lane, the ones parked "For human": the run applies the Auto rows itself and holds the Monitor rows, so neither is a
    decision and neither is on the item. With no human-lane row there is no item. Shadow mode (summary.shadow anything but
    False, as plan.write_outputs reads it: a product whose Auto is switched off) lists every change, so the team can agree
    or refuse the planner's automatic calls too.
    A row a person's decision or a planned rank experiment holds (plan_lanes writes locked_until) is in the human lane, so
    it stays on the item in both modes, with locked_until, lock_by, lock_on and lock_decision (the plan change's decided_by, decided_on and
    decision, renamed on the row because the dashboard server writes decision and decided_by on a row it decides);
    locked_rows counts them. Every row carries lane_unlocked, the lane the planner would have given it without any lock.
    E3 (I3): a row a decline holds asks for the higher of its own level and the decliner's (signer_level of the lock's
    decided_by: Kim when Kim declined, Lee when Lee did, else a book owner), so the card shows who can approve
    it again; dashboard.py approvals checks the same. E2: a row carries the budgets, boosts and modelled monthly spend it
    commits (MONEY_ROW_FIELDS, and on a promotion its budget and modelled_spend_month).
    Rows come from the plan only, biggest opportunity first, with plan order breaking ties.
    """
    changes = plan.get('changes') or []
    summary = (plan.get('summary') or [{}])[0]
    shadow = summary.get('shadow') is not False
    levels = row_levels(plan)
    for i, x in enumerate(changes):
        if x.get('locked_until') and x.get('decision') == 'decline':
            levels[i] = max(levels[i], signer_level(x.get('decided_by')), key=LEVELS.index)
    lane_of = [x.get('lane') if x.get('lane') in ('auto', 'monitor') else 'human' for x in changes]
    counts = Counter(lane_of)
    shown = [i for i in range(len(changes)) if shadow or lane_of[i] == 'human']
    locked = [i for i in shown if changes[i].get('locked_until')]
    if not shown:
        return None
    shown.sort(key=lambda i: (changes[i].get('opportunity') is None, -(changes[i].get('opportunity') or 0)))
    rows = [_bid_row(changes[i], levels[i]) for i in shown]
    total = len(changes)
    if shadow:
        title = f"{_n(len(rows), 'change')} to agree or refuse (shadow run)"
        reason = (f"Shadow run, so nothing applies automatically yet. Of {_n(total, 'planned change')}: {counts['auto']} the planner "
                  f"would have applied on its own, {counts['human']} it would have sent to a person, {counts['monitor']} it would "
                  'have held until the next run. Each row below can be marked agree or refuse so the team can check its calls.')
    else:
        title = f"{_n(len(rows), 'bid change')} to decide"
        reason = (f"Of {_n(total, 'planned change')}: {counts['auto']} to apply automatically, {counts['human']} waiting for a person, "
                  f"{counts['monitor']} held until the next run.")
    if locked:
        one = len(locked) == 1
        reason += (f" {_n(len(locked), 'row')} {'is' if one else 'are'} held by an earlier decision (a person's, or a "
                   f"planned rank experiment) and {'is' if one else 'are'} shown with it.")
    item = dict(id=BIDS_PREFIX + date, kind='bid', title=title, status='open', origin='sweep', priority='normal',
                reason=reason, action=BIDS_ACTION,
                source='AI bid planner (plan.json), ' + str(summary.get('run', date)), window=_window(plan, date),
                first_seen=date, last_seen=date, ai_review=dict(phase='human_ready'), shadow=shadow,
                locked_rows=len(locked), rows=rows,
                approval_required=max((row['approval_required'] for row in rows), key=LEVELS.index))
    return validate([item])[0]


SUMMARY_KEYS = ('rows_count', 'rows_by_lane', 'rows_dropped_on')


def _compact_rows(item, date):
    """Keep a closed bid item small (it is published twice and stored in the product file for good).

    Once a bid item leaves an active status its rows are dropped for a summary: rows_count, rows_by_lane (a count of
    rows per lane) and rows_dropped_on (`date`). The decisions on those rows live on the dashboard server, keyed by item
    and row id, and the run folder's plan.json keeps the rows themselves. An item that is active again (a later sweep
    reopened it, with fresh rows) loses the summary instead. Other kinds are left alone."""
    if item.get('kind') != 'bid':
        return
    if item['status'] in ACTIVE:
        for key in SUMMARY_KEYS:
            item.pop(key, None)
        return
    rows = item.pop('rows', None)
    if isinstance(rows, list) and rows:
        item.update(rows_count=len(rows), rows_dropped_on=date,
                    rows_by_lane=dict(Counter(str(row.get('lane') or 'unknown') for row in rows)))


def _set_status(item, status, owner, note, date):
    """Move an item to `status` the way transition does: owner, a history line and, when closed, how and when.

    A bid item that closes drops its rows for a summary (_compact_rows)."""
    item.update(status=status)
    if owner is not None:
        item['owner'] = owner
    item.setdefault('history', []).append(dict(date=date, status=status, owner=item.get('owner'), note=note))
    if status in ('resolved', 'dismissed'):
        item.update(resolved_on=date, resolution=note)
    _compact_rows(item, date)


def _merge_growth(old, item):
    """The For Growth item (one per ASIN, updated in place: launch design 4a, for-growth design 3 and 4) merged onto the
    stored one.

    - A block not newer than the stored one (growth.produced, 'YYYY-MM-DD HH:MM SGT', compared as text: the same or
      earlier): the stored item is kept whole. That is the carried copy of a run without a trigger, whatever happened to
      the item after the plan (Picked up, Copy pushed, resolved), and an older plan published again, so "Picked up" keeps
      meaning the block Growth read (for-growth design 7), as the bids items guard an older run published again.
    - A newer block over an item not yet closed (a rotate-out flag on the open item, R7): the new block, with the stored
      status, status_by, status_at, owner, first_seen and history kept, the run's own history lines added after them.
    - A newer block over a closed item (resolved or dismissed): taken only when it was built as a new item (a new pass,
      R11: status open, no status_by), born open, with the stored history kept and the run's lines added; nothing else of
      the closed item (who moved it, its resolution) carries. A refresh planned while the item was still open (in
      progress, picked up by someone) was overtaken by the close: the closed item stands."""
    if not str(item['growth'].get('produced') or '') > str(old['growth'].get('produced') or ''):   # validated: dicts
        return copy.deepcopy(old)
    if old['status'] in GROWTH_CLOSED:
        if item['status'] != 'open' or item.get('status_by'):
            return copy.deepcopy(old)
        merged = copy.deepcopy(item)
    else:
        merged = dict(old, **item)
        for field in ('status', 'status_by', 'status_at', 'owner', 'first_seen', 'resolution', 'resolved_on'):
            if field in old:
                merged[field] = copy.deepcopy(old[field])
    history = copy.deepcopy(old.get('history') or [])
    history += [copy.deepcopy(line) for line in item.get('history') or [] if line not in history]
    if history:
        merged['history'] = history
    return merged


def merge(existing, incoming, date, run_date=None, product=None):
    """The product file's human_review with a run's items merged in (`date` is the publish date).

    One active bids item at a time: an incoming bids item supersedes every other active one (the newest run's wins).
    A run with nothing to decide brings no bids item; `run_date` (the run's own date, the one its item id would carry)
    then supersedes every active bids item older than bids-<run_date>, with a note that says so. Items closed this way
    keep a summary, not their rows (_compact_rows).

    The For Growth item merges in place (_merge_growth). On an AI-managed product (`product`, the product file:
    registry.bid_owner AI) an incoming For Growth item supersedes the listing-conversion-gap item: an active one is
    resolved with the note GAP_SUPERSEDED, and one proposed again is not reopened while the For Growth item comes in."""
    previous = {item['id']: item for item in validate(existing)}
    proposed = validate(incoming)
    supersede = (isinstance(product, dict) and ((product.get('registry') or {}).get('bid_owner') == 'AI')
                 and any(item['kind'] == 'growth' for item in proposed))
    for item in proposed:
        old = previous.get(item['id'])
        if old and item['kind'] == 'growth' and old['kind'] == 'growth':
            item = _merge_growth(old, item)
        elif old:
            merged = dict(old, **item)
            for field in ('status', 'owner', 'first_seen', 'resolution', 'resolved_on', 'history'):
                if field in old:
                    merged[field] = copy.deepcopy(old[field])
            if (old['status'] == 'resolved' and date > max(old.get('last_seen', date), old.get('resolved_on', date))
                    and not (supersede and item['id'] == GAP_ID)):
                merged['status'] = 'open'
                merged.setdefault('history', []).append(dict(date=date, status='open', note='Signal detected again in a later sweep; prior resolution retained.'))
            if old.get('price', {}).get('proposed') is not None and item.get('price', {}).get('proposed') is None:
                merged['price'] = old['price']
                merged['price_recheck_required'] = True
                merged['ai_review']['phase'] = 'research'
                merged['ai_review'].setdefault('missing', []).append('Revalidate the retained numeric price proposal before escalation.')
            elif item.get('price', {}).get('proposed') is not None:
                merged['price_recheck_required'] = False
            item = merged
        item.setdefault('first_seen', date)
        item['last_seen'] = date
        item['detected_latest_sweep'] = True
        previous[item['id']] = item
    received = {item['id'] for item in proposed}
    for identity, item in previous.items():
        if identity not in received and item.get('origin') == 'sweep':
            item['detected_latest_sweep'] = False
    if any(item['kind'] == 'bid' for item in proposed):
        # one active bids item at a time: the newest run's (ids end in the run date). That also holds when an older
        # run is published again, which is then the one that is superseded.
        active = sorted(identity for identity, item in previous.items() if item['kind'] == 'bid' and item['status'] in ACTIVE)
        for identity in active[:-1]:
            _set_status(previous[identity], 'dismissed', None, 'Superseded by ' + active[-1], date)
    elif isinstance(run_date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', run_date):
        # a run with nothing to decide still replaces the older runs' items, so none of them stays approvable
        for identity, item in previous.items():
            if item['kind'] == 'bid' and item['status'] in ACTIVE and identity < BIDS_PREFIX + run_date:
                _set_status(item, 'dismissed', None, f'Superseded by the run of {run_date}, which had nothing to decide', date)
    if supersede and previous.get(GAP_ID, {}).get('status') in ACTIVE:
        _set_status(previous[GAP_ID], 'resolved', None, GAP_SUPERSEDED, date)
    for item in previous.values():
        _compact_rows(item, date)  # e.g. a closed item a same-day re-run just gave fresh rows
    return validate(list(previous.values()))


def for_people(items):
    """The review items people see: decisions only, each cut to what the decision needs (Kim, 2026-10-22, decision 97).

    A decision is an item in phase 'human_ready': the AI finished its research and the call is one it can't make itself
    (a listing, image, offer or price change) or a borderline one. Items still in AI research and items the AI only
    monitors stay in the product file for the AI and are never published. A listing or price item is shown with the
    AI's recommendation as its action and without the research write-up (rationale, counterevidence, query tables,
    competitor offers, open checks); the product file keeps all of it. The Bids item is shown as it is.

    So is the For Growth item (kind growth, always human_ready: growth.build_item): it is not a listing or price
    decision but Growth's work order, and the For Growth tab and the product page read it from the published doc, its
    growth block (the hand-over block, pass, flags, opened_on) and its status, status_by, status_at and history whole. It
    has no assessment, so its action stays its own. It is not counted as a decision (R32, attach)."""
    shown = []
    for item in items:
        if item['ai_review'].get('phase') != 'human_ready':
            continue
        if item['kind'] in ('bid', 'growth'):
            shown.append(item)
            continue
        item = copy.deepcopy(item)
        review = item['ai_review']
        assessment = review.get('assessment') or {}
        if assessment.get('recommendation'):
            item['action'] = assessment['recommendation']
        item['ai_review'] = dict(phase='human_ready', as_of=review.get('as_of'), missing=[],
                                 assessment={k: assessment[k] for k in ('recommendation', 'confidence') if assessment.get(k)})
        shown.append(item)
    return shown


def attach(doc, product):
    """The product's items on the page and the card: what people see (for_people, decision 97). The counts are the
    Needs-human queue's: the For Growth item (kind growth) is not a Needs-human item (R32, launch design 4a), so it is
    published for the For Growth tab but stays out of "N decisions need you"."""
    items = validate(product.get('human_review', []))
    shown = for_people(items)
    doc['human_review'] = shown
    doc['card']['human_review'] = shown
    # "N decisions need you": the For Growth item is shown (the For Growth tab reads it) but is not a decision (R32)
    doc['card']['human_review_count'] = sum(item['kind'] != 'growth' and item['status'] in ACTIVE for item in shown)
    # the AI's own backlog, a count for the AI's next run; no page draws it
    doc['card']['ai_research_count'] = sum(item['kind'] != 'growth' and item['status'] in ACTIVE
                                           and item['ai_review']['phase'] == 'research' for item in items)


def transition(items, identity, status, owner, note, date):
    result = validate(items)
    item = next((item for item in result if item['id'] == identity), None)
    if item is None:
        raise ValueError('Unknown human-review id: ' + identity)
    if status not in STATUSES or not note.strip():
        raise ValueError('A valid status and dated reason are required')
    if item['kind'] == 'bid' and status in ACTIVE and 'rows' not in item:
        raise ValueError(f'{identity}: a closed bid item has dropped its rows and cannot be reopened; the next run makes a new one')
    if item['kind'] == 'growth' and status in ('resolved', 'waiting_approval'):
        # the AI resolves a growth item when it sees the listing change (dashboard.close_on_listing_change), and nobody
        # approves Growth's work (R32): a person closes one with dismissed
        raise ValueError(f'{identity}: a For Growth item is resolved only by the AI, when a run sees the listing change, '
                         f'and takes no approval; to close it by hand use --status dismissed')
    _set_status(item, status, owner, note, date)
    return result
