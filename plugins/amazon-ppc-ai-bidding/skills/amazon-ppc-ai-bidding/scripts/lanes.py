"""Lanes: who has to say yes to each change the bid planner proposes.

Standard library only (plus evidence.py and searchtext.py). `classify` puts every change in one of three lanes:
  auto     applied by the run itself, inside the guardrails (autonomous runs, Kim 2026-10-22, decision 98)
  human    parked "For human": a decision the AI can't make (a price, a person's earlier decision, a borderline
           call); it waits on the dashboard and the run's Slack message tags the person. Money parks nothing: the
           $2,000-a-month investment guide, the product's investment band and the $60 loss line for one search are
           information (Kim, 2026-10-22, decisions 99 and 100)
  monitor  held back, not applied and not escalated: a close call too small to bother anyone with, or a product whose
           data isn't fresh; re-judged next run
It decides nothing else: roles and bid formulas stay in plan.py and the rulebook. `classify` never changes its
inputs, so the planner keeps the running totals (Ctx.band_left_month, information only since decision 100;
raises_left) and passes the updated Ctx to the next row. Settings come from the `auto` block of config.json (Ctx.auto). The design is
docs/superpowers/specs/2026-10-22-autonomous-runs-design.md (it replaced the human list of the 2026-10-19 design).

`us_write_window_open` is a compatibility interface that permits audit execution every day.
`readback_mismatches` compares
what was written with what the account shows afterwards. `us_date` is the one place the Los Angeles date is worked out.
`spend_check` is the 24-hour check that switches a product's automatic changes off when its spend jumps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import evidence
from searchtext import norm

BID_TYPES = ('Bid change', 'Target bid change')
PAUSE_TYPES = ('Pause keyword', 'Pause target')
TARGET_TYPES = ('Target bid change', 'Pause target')
# a Business invest (an owner keyword's invest inside the team's B2B campaign, design 2026-10-21-b2b-lane-and-roles 4b) is a
# promotion like a consumer exact campaign: Kim's ladder on the B2B keyword's own record
PROMOTION_TYPES = ('New exact campaign', 'Reuse exact campaign', 'Business invest')
JUDGED_TYPES = BID_TYPES + PAUSE_TYPES + PROMOTION_TYPES  # the types judged on their evidence (and policy_tos_only)
INVEST_ROLES = ('Invest', 'Prove first')
# Autonomous runs (Kim, 2026-10-22, decision 98): the types that are a person's call whatever the evidence. A price is
# Kim's. A 'Stop-loss review' (planned only where no step-down can be written: plan.py and business.py write the
# step-down rows themselves wherever they can, stop_loss.py) went to a person too until 2026-10-23; since decision 107 it is
# held and the next run tries again. Until 2026-10-22 this list also held budgets, negatives, the stop-loss, Scale Insights
# rules and setup, harvest rows, new exact keywords and budget steps; they apply on their own now, inside the guards below.
HUMAN_TYPES = ('Listing price',)
ALWAYS_HUMAN_TYPES = HUMAN_TYPES  # the name the 2026-10-19 design used
SI_TYPES = ('Scale Insights rules', 'Scale Insights setup')  # done in the signed-in browser (scale-insights-playbook.md)
# executable rows that apply on their own once the first rules (lock, fresh data, stop-loss) let them through; each has
# its own rule below, and 'Budget and top of search' is checked for a non-standard budget or boost by plan_lanes
AUTO_TYPES = ('Negative exact', 'Archive negative', 'Harvest default bid', 'Harvest setup', 'Budget step',
              'Budget and top of search', 'New SB video campaign', 'SB pause keyword', 'SB bid change',
              'SB bid optimisation', 'Ad group default bid') + SI_TYPES
SB_BID = 'SB bid change'
# a campaign moved from up-and-down to down-only bidding (decision 140, 2026-10-26): it can only lower bids, so it applies on
# its own, except an audience copy (people own AMC, decision 107) or a campaign not shown to advertise this product alone
STRATEGY = 'Bidding strategy'
# the product-page base bid (placement_shape.py, decision 140): written after the lanes, only where every bid row of its
# campaign went to the Auto lane, so it is never classified; listed so a re-run of classify on a saved plan knows it
SHAPE = 'Placement shape'
CUT_BID_TYPES = BID_TYPES + (SB_BID,)  # bid rows the big-cut guard reads (a pause is never a "big cut", 2026-10-22)


def policy_tos_only(change):
    """True for a 'Budget and top of search' row on a live Invest or Prove-first campaign whose only change is top of search
    set to the standing rank policy (Kim, 2026-10-20): placement_review.hold_defaults marks it `policy_tos_only` when
    the policy applies and the budget is unchanged, and plan_lanes.assign takes the mark off a row whose top of search is
    not the policy. This reads the mark with the row's own fields, so a budget change, another role or a planner hold
    (placement_hold) is never one. classify judges such a row like a promotion (`_policy_tos_lane`): the ladder for its
    role (its own search's band is information since decision 100), where any other 'Budget and top of search' row applies
    on its own at the standard budget and boost (plan_lanes checks it with promotion_odd)."""
    return (change.get('type') == 'Budget and top of search' and change.get('policy_tos_only') is True
            and change.get('role') in INVEST_ROLES and not change.get('placement_hold')
            and change.get('budget') is not None and change.get('budget') == change.get('budget_now'))


@dataclass
class Ctx:
    auto: dict                       # the `auto` config, product overrides merged
    profit_per_unit: float
    stale: str | None                # why the product's data isn't fresh, or None: every row is held (monitor)
    onboarding: bool                 # registry stage "onboarding", or under 14 days on AI (reported; since 2026-10-22 an
                                     # onboarding product's rows are judged like any other's, decision 98)
    locks: dict                      # row_id, keyword_id, target_id or search (search_lock_key: 'business:<search>' for a
                                     # business row) -> the date a person's decision holds until, or a dict: {'until',
                                     # 'reason'} and what/by/on/direction (blocking_lock)
    today: str                       # ISO date of the run
    band_left_month: float           # monthly investment band not yet spoken for: information only since decision 100
                                     # (the reason and plan_lanes' over_invest_band flag say how a promotion sits in it)
    raises_left: int                 # automatic raises still allowed in this run
    onboarding_reason: str | None = None  # why it counts as onboarding, in words, when the planner knows
    invested: frozenset = frozenset()  # E1: the searches the team invests in (searchtext.norm): the product's invest log
                                       # and this run's rank searches. plan_lanes flags a cut or pause on one
                                       # invested_search (log_invest reads it); since 2026-10-22 it applies on its own
    season_switch: str | None = None  # a seasonal product's phase switch ("rank build -> harvest", season.state), or None:
                                      # reported; since 2026-10-22 the switch's rows are judged like any other's
    invested_business: frozenset = frozenset()  # E1 inside the business kind: the product's business invest log and this
                                                # run's business rank searches. A business row is checked against these,
                                                # a consumer row against `invested` (invested_cut)
    # the data stage (data-stage design 4.4.1 and 4.6, 2026-10-22; plan_lanes.assign fills these from the planner's summary)
    early_stage: dict | None = None   # the summary's stage dict when the product is in stage early, else None
    volatile: str | None = None       # the volatile-week text (summary.volatile_week) that holds every promotion, else None;
                                      # plan_lanes passes it in stage early only (spec 4.6)
    auto_min_observed_days: int = 14  # a promotion is automatic only when its SQP row has this many observed days (two SQP
                                      # weeks; in stage early, and at every stage since 2026-10-25, decision 135): config.json
                                      # stage.auto_min_observed_days
    cooloff: dict | None = None       # the re-investment cool-off (Kim, 2026-10-22): {search_lock_key: (stepped-down date,
                                      # held-until date)} of the searches the stop-loss stepped down less than
                                      # auto.repromote_cooloff_days ago (plan_lanes.cooloff_table); _cooloff_hold reads it


def ladder(orders, index, a):
    """Kim's evidence ladder for a promotion: 'Invest', 'Prove first' or None."""
    if index is None:
        return None
    if orders >= a['invest_orders'] and index >= a['invest_index']:
        return 'Invest'
    if orders >= a['prove_orders'] and index >= a['prove_index']:
        return 'Prove first'
    return None


def search_band(row, profit_per_unit, max_loss_month):
    """Monthly spend a search's band shows: the cost of the target click share, shrunk when it would lose more than
    max_loss_month. Information only since 2026-10-22 (decision 100): a promotion over it is flagged, never parked.

    `row` is a re-rank row from plan.py. Its modelled loss is `net` (worked out from orders and profit when absent).
    """
    spend = float(row['spend'])
    net = row.get('net')
    if net is None:
        net = (row.get('orders') or 0) * profit_per_unit - spend
    if net < -max_loss_month:
        return spend * max_loss_month / -net
    return spend


def _money(value):
    return f'${value:.2f}'


def _count(n, noun):
    return f"{n:g} {noun}{'' if n == 1 else 's'}"


def _orders(n):
    return _count(n, 'order')


def lock_key(value):
    """How lock keys and a row's identifiers are compared: lower case, single spaces."""
    return ' '.join(str(value).lower().split())


def lock_date(value):
    """A lock's end date, or None when it can't be read (such a lock holds until someone changes it)."""
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# Which way a row moves (direction): the moves a lock compares. A lock remembers the move of the row a person decided.
DIRECTIONS = ('up', 'down', 'pause', 'other')
CUT_MOVES = ('down', 'pause')  # both cut: a person who refused one has refused the other
DIRECTION_BID_TYPES = BID_TYPES + ('SB bid change', 'Harvest default bid')
DIRECTION_PAUSE_TYPES = PAUSE_TYPES + ('SB pause keyword',)
LOCK_FIELDS = ('what', 'by', 'on', 'direction')  # what a lock may say besides until and reason (None when it doesn't)


def direction(change):
    """Which way a row moves: 'pause' for a pause; 'up' or 'down' for a bid row, by its new bid against its current one;
    'other' for everything else (a promotion, a negative, a budget, a bid that doesn't move or can't be read).

    The planner compares a proposal's direction with the direction of the decision that locks its row (lock_blocks);
    whoever writes a lock (dashboard.py) takes its direction from the decided row with this same function."""
    ctype = change.get('type')
    if ctype in DIRECTION_PAUSE_TYPES:
        return 'pause'
    current, new = change.get('current'), change.get('new')
    if ctype in DIRECTION_BID_TYPES and evidence._number(current) and evidence._number(new):
        if new > current:
            return 'up'
        if new < current:
            return 'down'
    return 'other'


def lock_blocks(lock, move):
    """True when `lock` holds a proposal that moves `move` way (direction), so the row goes to a person.

    - A declined move holds the same move (a declined cut also holds a pause, and a declined pause a cut): the person
      said no to it. A different move is a new call and is planned as usual.
    - An approved raise holds a cut or a pause, and an approved cut holds a raise: the way back would undo it. An
      approved pause or other change holds every move.
    - A lock that doesn't say which way it went (an older entry, a rank experiment, a plain date) or what was decided
      holds every move, as locks always did.
    """
    if not isinstance(lock, dict):
        return True
    what, way = lock.get('what'), lock.get('direction')
    if way not in DIRECTIONS:
        return True
    if what == 'decline':
        return move == way or (move in CUT_MOVES and way in CUT_MOVES)
    if what == 'approve':
        if way == 'up':
            return move in CUT_MOVES
        if way == 'down':
            return move == 'up'
        return True
    return True


BUSINESS_LOCK_PREFIX = 'business:'


def search_lock_key(change):
    """The key a row's search is locked under: its search as the planner writes it (searchtext.norm), or
    'business:<search>' for a row made from a business (Amazon Business) keyword ('' when the row has no search).

    Locks are per shopper kind (design 2026-10-21-b2b-lane-and-roles 4d): a person's decision on a consumer search never
    holds the B2B keyword of the same search, nor the other way round. plan_lanes.lock_table keys a decision that carries
    owner_kind 'business' the same way."""
    search = norm(str(change.get('keyword') or ''))
    if not search:
        return ''
    return f'{BUSINESS_LOCK_PREFIX}{search}' if change.get('owner_kind') == 'business' else search


def blocking_lock(change, locks, today_iso):
    """The lock holding this row on `today_iso`, as a dict, or None when no lock holds it.

    A lock names the row's own row_id (as dashboard approvals write it), its keyword or target id, or its search
    (search_lock_key: a business row's search is 'business:<search>'). Its
    value is the date it holds until, or a dict: {'until', 'reason'} when it says why in its own words, plus what was
    decided ('approve', 'decline', 'experiment'), by whom, on which date, and which way the decided row moved
    (plan_lanes.lock_table). A lock holds only until its date (one that can't be read holds), and only a move it blocks
    (lock_blocks); the identifiers are tried in that order and the first lock that holds is returned, with `until`,
    `reason` (a plain date's reason is 'decided by a person until <date>') and every LOCK_FIELDS key (None when the lock
    doesn't say). It needs only the locks and the date, so the planner can ask it before it has built a Ctx.
    """
    if not locks:
        return None
    locks = {lock_key(k): v for k, v in locks.items()}
    today = date.fromisoformat(today_iso[:10])
    move = direction(change)
    for ident in (change.get('row_id'), change.get('keyword_id'), change.get('target_id'), change.get('theme_id'),
                  search_lock_key(change)):
        lock = locks.get(lock_key(ident)) if ident not in (None, '') else None
        held = dict(lock) if isinstance(lock, dict) else dict(until=lock)
        until = held.get('until')
        if until in (None, ''):
            continue
        end = lock_date(until)  # a date we can't read (None) is treated as still holding
        if end is not None and end < today:
            continue
        if not lock_blocks(lock, move):
            continue
        held['reason'] = held.get('reason') or f'decided by a person until {until}'
        for field in LOCK_FIELDS:
            held.setdefault(field, None)
        return held
    return None


def lock_hit(change, locks, today_iso):
    """The lock holding this row on `today_iso`, as (until, reason in words), or None (see blocking_lock)."""
    held = blocking_lock(change, locks, today_iso)
    return (held['until'], held['reason']) if held else None


def lock_on(change, ctx):
    """The lock holding this row today, as (until, reason in words), or None (see blocking_lock)."""
    return lock_hit(change, ctx.locks, ctx.today)


def locked_until(change, ctx):
    """The date a person's decision on this row holds until, when that date hasn't passed."""
    hit = lock_on(change, ctx)
    return hit[0] if hit else None


def invested_cut(change, invested, invested_business=frozenset()):
    """E1: True for a cut or a pause (direction 'down' or 'pause') whose search, written as the planner writes it
    (searchtext.norm), is one the team invests in for the row's shopper kind: `invested_business` for a row made from a
    business keyword (owner_kind 'business'), `invested` for any other. plan_lanes stamps such a row invested_search, and
    log_invest.py reads the flag to step the search down once a person sent it out (approved/ or review/). Until
    2026-10-22 classify sent it to a person; since autonomous runs (decision 98) it applies on its own like any cut, and
    a search leaves the invest log by its stop-loss step-down (stop_loss.py) or a person's cut."""
    pool = invested_business if change.get('owner_kind') == 'business' else invested
    # a copy's holding bid (plan.py copy_hold, decision 135) moves the search to its new owner: never a step-down
    if not pool or direction(change) not in CUT_MOVES or change.get('copy_hold') is True:
        return False
    search = norm(str(change.get('keyword') or ''))
    return bool(search) and search in pool


def is_cut(change):
    """True for a pause (a Sponsored Brands one too), or a bid, target bid or Sponsored Brands bid that goes down."""
    if change.get('type') in DIRECTION_PAUSE_TYPES:
        return True
    current, new = change.get('current'), change.get('new')
    return change.get('type') in CUT_BID_TYPES and current is not None and new is not None and new < current


def _counts(change, term):
    """Orders and clicks behind the call: the search's SQP record, its ad record, or the row's own 90 days."""
    if term:
        if str(term.get('index_basis') or '').startswith('SQP'):
            return term.get('sqp_our_purchases') or 0, term.get('sqp_our_clicks') or 0
        return term.get('ad_orders') or 0, term.get('ad_clicks') or 0
    return change.get('orders90') or 0, change.get('clicks90') or 0


def _ladder_orders(term, orders):
    """The orders a search's promotion or raise is judged on: the higher of its SQP purchases and its search-term report ad
    orders, whichever record its index reads (Kim, 2026-10-30: "ad data counts too"; decision 174). SQP purchases
    already hold the ad-attributed ones, so the two are never added; a search whose ads show more orders than SQP has
    caught yet is judged on them. Confidence keeps the index record's own orders and clicks (_counts), a matched pair."""
    if not term or term.get('owner_kind') == 'business':   # SQP counts every shopper: a business record reads its own B2B orders
        return orders
    return max(orders, term.get('sqp_our_purchases') or 0, term.get('ad_orders') or 0)


def _baseline(change, term):
    """The conversion we are measured against: a search's market, or the product's own ads for a target."""
    if change.get('type') in TARGET_TYPES:
        return change.get('baseline_cvr')
    return (term or {}).get('market_cvr')


def _index(change, term):
    if term:
        return term.get('index')
    baseline, cvr = change.get('baseline_cvr'), change.get('cvr')
    if change.get('type') in TARGET_TYPES and baseline and cvr:
        return cvr / baseline
    return None


def _confidence(change, orders, clicks, baseline):
    if change.get('type') not in JUDGED_TYPES and not policy_tos_only(change):
        return None, None
    if not (isinstance(baseline, (int, float)) and 0 < baseline < 1) or clicks <= 0 or orders < 0:
        return None, None
    if is_cut(change):
        return evidence.p_below(orders, clicks, baseline), 'below'
    return evidence.p_beats(orders, clicks, baseline), 'beats'


def _spend_30d(change, term):
    spend90 = change.get('spend90')
    if spend90 is None:
        spend90 = (term or {}).get('ad_spend')
    return (spend90 or 0.0) / 3


def _raise_limit(current, max_raise_pct, breakeven):
    """The most a bid may rise in one run.

    That is +max_raise_pct rounded down to a cent, so it never passes the percentage, but never less than one cent
    more than now, so a tiny bid can still move. That one-cent minimum stops at breakeven; the percentage cap does not.
    max_raise_pct None (config.json since 2026-10-29, decision 165): no limit.
    """
    if max_raise_pct is None:
        return math.inf   # no step (Kim, 2026-10-29, decision 165): a raise goes to its price in one run
    by_percent = math.floor(current * (1 + max_raise_pct / 100) * 100 + 1e-9) / 100
    one_cent = round(current + 0.01, 2)
    if breakeven is not None:
        one_cent = min(one_cent, breakeven)
    return max(by_percent, one_cent)


def _who(ctype):
    """What a row's conversion is measured against: a search's market, or the product's own ads for a target."""
    return "the product's ad average" if ctype in TARGET_TYPES else 'the market'


def _evidence_text(orders, index, who):
    if index is None:
        return f'{_orders(orders)} and no index'
    return f'{_orders(orders)} at index {index:.2f} (converts {round(index, 2):g}x {who})'


def _need_text(orders, index, who):
    return f'{orders:g}+ orders at {index:g}x {who}'


def _close_call(what, opportunity, spend_30d, a):
    """A call the evidence doesn't settle yet: the AI's "not yet". Held (monitor), and the next run judges it again on
    more data (Kim, 2026-10-23, decision 107: "the bid changes and rank investments are all actually programmatically
    calculated and quantifiably decided", so the AI makes them). Until 2026-10-23 one worth a person's time (an opportunity
    of min_opportunity or more, or monitor_spend_cap or more spent in 30 days with no volume to size it) went to a person."""
    if opportunity is not None:
        size = f'opportunity {opportunity:.0f} (conversion index x monthly searches)'
        return 'monitor', f'{what}; {size}: not yet, the next run judges it again'
    return 'monitor', (f'{what}; no search volume to size it ({_money(spend_30d)} spent in 30 days): not yet, the next run '
                       'judges it again')


def loss_line_text(change, a):
    """How a promotion's modelled spend sits against its own search's band, in words, when it is over it; None when it
    fits or there is nothing to compare (no band of its own, no modelled spend).

    The planner puts the search's band on the row as `own_band_month` (search_band: shrunk when the search is modelled to
    lose more than max_loss_month, the $60 loss line for one search) and the re-rank's modelled net as
    `modelled_net_month`. Information only since 2026-10-22 (Kim, decision 100: "we don't want to put a cap and hamper the
    autonomous engine"): plan_lanes flags the row over_loss_line, the summary lists it and the Slack recap names it; until
    then such a promotion went to a person."""
    own, modelled = change.get('own_band_month'), change.get('modelled_spend_month')
    if own is None or modelled is None or modelled <= own + 1e-9:
        return None
    line = f"${a['max_loss_month']:g}"
    net = change.get('modelled_net_month')
    if net is None or net >= 0:
        return f'modelled to lose more than the {line} a month loss line for one search'
    return f'modelled to lose {_money(-net)} a month, over the {line} loss line for one search'


def band_words(change, ctx):
    """How an automatic promotion sits against its own search's band and the product's investment band, in words, for its
    reason. Information only (decision 100): nothing here parks it. The product's band is checked on the group's spend for
    the head of a campaign's business invests (group_spend_month, ruling 6)."""
    modelled = change.get('modelled_spend_month')
    if modelled is None:
        return "its monthly spend isn't modelled, so it isn't sized against a band"
    words, past = [], False
    loss = loss_line_text(change, ctx.auto)
    grouped = 'group_spend_month' in change
    need = change['group_spend_month'] if grouped else modelled
    if need is None:
        words.append("a business invest of its campaign has no modelled monthly spend, so the campaign isn't sized "
                     'against the band')
    else:
        who = 'with the other business invests of its campaign it' if grouped else 'it'
        left = ctx.band_left_month
        past = need > left + 1e-9
        if past:
            words.append(f"{who} goes past the product's monthly invest band ({_money(need)}, with "
                         f"{_money(max(0.0, left))} left)")
        else:
            words.append(f"{who} fits the product's monthly invest band ({_money(need)} of {_money(left)} left)")
    if loss:
        words.append(loss)
    text = '; '.join(words)
    return f'{text} (information only: no cap, decision 100)' if loss or past else text


def over_invest_band(change, ctx):
    """True when an automatic promotion's spend (its group's, when it heads one) goes past what is left of the product's
    investment band (Ctx.band_left_month): information only since decision 100, for over_invest_band on the row."""
    need = change['group_spend_month'] if 'group_spend_month' in change else change.get('modelled_spend_month')
    return need is not None and need > ctx.band_left_month + 1e-9


def _promotion_lane(change, term, ctx, orders, index, opportunity):
    """Rule 4: Kim's ladder. Returns (lane, reason).

    Nothing about money parks a promotion (Kim, 2026-10-22, decisions 99 and 100: "don't cap the promotion because i want good
    keywords to be invested on" and "we don't want to put a cap and hamper the autonomous engine. if spend is overboard,
    the humans will notice it and step in anyway"). Its own search's band (shrunk when the search is modelled to lose more
    than max_loss_month, the $60 loss line) and the product's investment band are information: the reason says how it
    sits against them (band_words), plan_lanes flags over_loss_line and over_invest_band on the row and the run summary,
    and the Slack recap names them. Until 2026-10-22 a promotion past either band, or with no modelled spend to check,
    went to a person; one past Kim's $600 a month a product went to him, and for a few hours on 2026-10-22 one past
    $3,000 for the program.

    The ladder reads the row's own record (`term`): a business row's is its B2B keyword's (plan_lanes.assign looks it up
    by owner_kind), so a Business invest is proved on its own B2B clicks and orders. A row that heads its campaign's
    business invests (controller ruling 6, 2026-10-21: one campaign update carries their top of search and budget, so they
    go out together) carries the group's monthly spend as `group_spend_month`, which the product's band words use."""
    a = ctx.auto
    role = change.get('role')
    who = 'the market'
    proof = _evidence_text(orders, index, who)
    if role in INVEST_ROLES and ladder(orders, index, a) == role:
        return 'auto', f'enough proof for {role}: {proof}; {band_words(change, ctx)}'
    if role == 'Invest':
        needs = _need_text(a['invest_orders'], a['invest_index'], who)
        what = f'not enough proof yet for Invest (needs {needs}); it has {proof}'
    elif role == 'Prove first':
        needs = _need_text(a['prove_orders'], a['prove_index'], who)
        what = f'not enough proof yet for Prove first (needs {needs}); it has {proof}'
    else:
        what = ('promotion without a role' if not role else f'a {role} promotion')
        what += ", so it can't be checked against the proof Invest or Prove first need"
    return _close_call(what, opportunity, _spend_30d(change, term), a)


def _policy_tos_lane(change, term, ctx, orders, index, opportunity):
    """Rule 4b: top of search set to the standing rank policy (+50% Invest, +30% Prove first) on a live rank campaign, the
    budget unchanged (policy_tos_only). Judged like a promotion on the evidence: Kim's ladder for its role. Its own
    search's band is information (decision 100, 2026-10-22: the reason names a search modelled past the $60 loss line, and
    plan_lanes flags it over_loss_line); until then one past it, or with no modelled spend, went to a person. Unlike a
    promotion it adds no spend to the product's running total: the campaign is live, its spend is already in the product's
    planned invest, and its budget is unchanged. Returns (lane, reason)."""
    a = ctx.auto
    role = change.get('role')
    proof = _evidence_text(orders, index, 'the market')
    if ladder(orders, index, a) == role:
        over = loss_line_text(change, a)
        return 'auto', (f"enough proof for {role}: {proof}; it only sets top of search to the standing rank policy "
                        f"(+{change.get('tos', 0):g}%), with the budget unchanged at {_money(change['budget'])}/day"
                        + (f'; {over} (information only: no cap, decision 100)' if over else ''))
    needs = _need_text(a['invest_orders'], a['invest_index'], 'the market') if role == 'Invest' else _need_text(a['prove_orders'], a['prove_index'], 'the market')
    what = f'not enough proof yet for {role} (needs {needs}); it has {proof}'
    return _close_call(what, opportunity, _spend_30d(change, term), a)


def _raise_lane(change, term, ctx, orders, index, opportunity):
    """Rule 5: returns (lane, reason, capped bid or None, raises used up). A raise may rise at most +max_raise_pct a run.

    `raises used up` is True when the raise would have been automatic but the run has no automatic raises left.
    """
    a = ctx.auto
    ctype, role = change.get('type'), change.get('role')
    current, new = change['current'], change['new']
    who = _who(ctype)
    proof = _evidence_text(orders, index, who)
    needs_to_beat = _need_text(a['raise_orders'], a['raise_index'], who)
    breakeven = change.get('breakeven')
    if breakeven is None and term:
        breakeven = term.get('be_cpc')
    capped = None
    limit = _raise_limit(current, a['max_raise_pct'], breakeven)
    if new > limit:
        if limit <= current + 1e-9:
            return 'monitor', (f"it can't rise this run: one more cent would pass its breakeven click "
                               f"({_money(breakeven)}), so it waits for the next run"), None, False
        capped = limit
    uplift = change.get('hold_uplift')
    mid = change.get('mid_bid') or {}
    if mid.get('bid') is not None and new <= mid['bid'] + 1e-9:
        # the suggested mid (Kim, 2026-10-31, decision 177): a validated or still-launching ordinary keyword bids the
        # suggested middle bid, above or below breakeven, so the raise to it applies on its own like a raise to breakeven
        lane, reason = 'auto', (f"the raise stops at the suggested mid ({_money(mid['bid'])}, {mid.get('priced_on')}): "
                                f"a {mid.get('state')} keyword bids the mid, never the high (decision 177)")
    elif breakeven is not None and new <= breakeven + 1e-9:
        lane, reason = 'auto', (f"the raise stops at its breakeven click ({_money(breakeven)}, the most a click "
                                'can cost and still pay for itself)')
    elif (uplift and role == 'Hold' and breakeven is not None
          and new <= round(breakeven * (1 + uplift / 100), 2) + 1e-9):
        # the Hold uplift test (Kim, 2026-10-23, decision 108): a Hold search at index 1.0-1.1 bids its breakeven
        # +hold_uplift.pct, its role's own price, so the raise to it applies on its own like a raise to breakeven
        lane, reason = 'auto', (f"Hold at index 1.0-1.1: the raise stops at breakeven +{uplift:g}% "
                                f"({_money(round(breakeven * (1 + uplift / 100), 2))}), the Hold uplift test (decision 108)")
    elif (ctype == 'Bid change' and role in INVEST_ROLES and change.get('sug_low') is not None
          and change.get('sug_high') is not None and change['sug_low'] <= new <= change['sug_high']):
        # a range from SoldScope stands in when Amazon gave none (bid_fallback, decision 106), and the reason says so
        source = "SoldScope's estimated range" if change.get('bid_source') == 'soldscope' else "Amazon's suggested range"
        lane, reason = 'auto', (f"invest re-price inside {source} "
                                f"{_money(change['sug_low'])} to {_money(change['sug_high'])}")
    elif index is not None and orders >= a['raise_orders'] and index >= a['raise_index']:
        lane, reason = 'auto', f'enough proof to bid above breakeven: {proof}; the bar is {needs_to_beat}'
    else:
        lane, reason = _close_call(f'not enough proof to bid above breakeven (needs {needs_to_beat}); it has {proof}',
                                   opportunity, _spend_30d(change, term), a)
    if lane == 'auto' and ctx.raises_left <= 0:
        # held, not a person's call (decision 107): the next run raises it, inside that run's own count
        return 'monitor', (f"this run has used up its {_count(a['max_raises'], 'automatic raise')}, so it goes out on the "
                           'next run'), capped, True
    return lane, reason, capped, False


def _sb_raise_lane(change, ctx):
    """A Sponsored Brands keyword bid that goes up (autonomous runs, 2026-10-22): its role's bid, as plan.py prices the AI's
    own video keywords (an invest search's Sponsored Products invest bid x sb_cvr_ratio, breakeven for Hold), applies on its
    own inside the same caps as a Sponsored Products raise: +max_raise_pct a run (written at the cap) and the run's
    max_raises. Amazon gives no Sponsored Brands suggested bids or SQP of their own, so there is no ladder to read here: the
    search's role already passed it. Returns (lane, reason, capped bid or None, raises used up), as _raise_lane does."""
    a = ctx.auto
    current, new = change['current'], change['new']
    limit = _raise_limit(current, a['max_raise_pct'], None)
    capped = limit if new > limit else None
    reason = f"Sponsored Brands keyword re-priced to its {change.get('role') or 'role'} bid ({_money(new)})"
    if capped is not None:
        reason += f", written at {_money(capped)}, the most a bid may rise in one run (+{a['max_raise_pct']:g}%)"
    if ctx.raises_left <= 0:
        return 'monitor', (f"this run has used up its {_count(a['max_raises'], 'automatic raise')}, so it goes out on the "
                           'next run'), capped, True
    return 'auto', reason, capped, False


# Data-stage holds that the next run settles on its own (a second SQP week, a steadier week): held, not escalated, since
# autonomous runs (2026-10-22). The head-term flags stay a person's call: no later week answers them. The fallback goes out
# as a Prove-first test since 2026-10-23 (decision 107).
WAITS_FOR_DATA = ('volatile SQP week', 'early SQP: ')


def _stage_hold(change, term, ctx):
    """Why a consumer promotion, or a policy-only top-of-search row on a rank campaign, is not judged on the ladder this run
    (data-stage design 4.4.1, 4.4.2, 4.4.4 and 4.6; 2026-10-22), as (lane, reason), or None. In this order: a search
    promoted on the search-term fallback (no SQP row yet, so no index the ladder could read) goes out as a Prove-first test
    (auto, decision 107; a person approved it until 2026-10-23); a head-term flag (one word, or in none of the product's
    lists) at every stage goes to a person; a volatile SQP week (plan_lanes sets
    `ctx.volatile` in stage early only) and a search seen in fewer than `auto_min_observed_days` SQP days (one week; in stage
    early, a search with no SQP count too; at every stage since 2026-10-25, decision 135) are held (monitor) until the data
    settles them (WAITS_FOR_DATA; a person sent both until 2026-10-22). The
    row's own stamps (plan_lanes.assign: sqp_observed_days, relevance_flag) are read first, the term's when the row has none.
    Cuts never get here, and nor does a business row (classify)."""
    term = term or {}
    if term.get('index_status') == 'product_market_fallback':
        # the fallback already passed its own bar (rulebook 10.3, item 2); it goes out as a small Prove-first test, which
        # the stop-loss ends if it doesn't pay (decision 107; a person approved it until 2026-10-23)
        fb = term.get('fallback_index')
        how = f"its ads convert {fb:.2f}x the product's market" if isinstance(fb, (int, float)) else 'its ads beat the product\'s market'
        return 'auto', (f'Prove first on the search-term fallback (no SQP row yet): {how}; a small Prove-first test, which '
                        'the stop-loss ends if it does not pay')
    flag = change.get('relevance_flag') or term.get('relevance_flag')
    if flag == 'one token':
        return 'human', 'one-word search: a head term, generic and hard to rank on, so a person decides (rulebook section 10)'
    if flag == 'unlisted':
        return 'human', ("not in the product's niche list, its launch list or its roots, so a person decides whether it is "
                         "the product's search (rulebook section 10)")
    if flag:
        return 'human', f'flagged "{flag}", so a person decides'
    if ctx.volatile:
        text = str(ctx.volatile)
        text = text if text.startswith('volatile SQP week') else f'volatile SQP week: {text}'
        return 'monitor', f'{text}; promotions wait for a steadier week (a person may lift the hold with --allow-volatile)'
    days = change.get('sqp_observed_days')
    if days is None:
        days = term.get('sqp_observed_days')
    # in stage early a search with no SQP count waits too; at every other stage since 2026-10-25 (Kim, decision 135, fix
    # 11 of the AI spend review) a search SQP has seen in fewer days waits, and one with no SQP row is judged as before
    if ctx.early_stage or days is not None:
        days = days or 0
        if days < ctx.auto_min_observed_days:
            return 'monitor', (f'early SQP: seen in one SQP week only ({days:g} observed days, under '
                               f'{ctx.auto_min_observed_days}), so it waits for its second week')
    return None


REPROMOTE_COOLOFF_DAYS = 56  # auto.repromote_cooloff_days when the config doesn't say: 8 weeks (Kim, 2026-10-22)


def reinvests(change):
    """True for a row that invests in its search again: a promotion (a new or reused exact campaign, a Business invest, a
    business invest search's new exact keyword), a raise of an Invest or Prove-first keyword bid (Sponsored Brands too), or a
    'Budget and top of search' row of an Invest or Prove-first campaign (its budget and the rank boost). A cut, a pause and
    any row of another role do not."""
    ctype = change.get('type')
    if ctype in PROMOTION_TYPES or is_business_new_keyword(change):
        return True
    if change.get('role') not in INVEST_ROLES:
        return False
    if ctype == 'Budget and top of search':
        return True
    return ctype in CUT_BID_TYPES and direction(change) == 'up'


def _cooloff_hold(change, ctx):
    """Why a row that re-invests in a search the stop-loss stepped down is held (monitor), or None (Kim, 2026-10-22: a
    stepped-down search can't be promoted again by the Auto lane for auto.repromote_cooloff_days, 56, after its step-down;
    held, not sent to a person, to keep "For human" items few). After the window it is judged on the ladder as usual. The
    search is keyed per shopper kind (search_lock_key): a business step-down never holds the consumer search."""
    if not ctx.cooloff or not reinvests(change):
        return None
    hit = ctx.cooloff.get(search_lock_key(change))
    if not hit:
        return None
    stepped, until = hit
    return f'stepped down at stop-loss on {stepped}; held from re-investment until {until}'


def is_business_new_keyword(change):
    """A business invest search's new exact keyword (business.new_keyword_rows): judged as a promotion (plan_lanes.is_promotion)."""
    return change.get('type') == 'New exact keyword' and change.get('owner_kind') == 'business'


def _executable_lane(change, ctype):
    """Section 3 of classify: an executable row of AUTO_TYPES that is not judged on its evidence, as (lane, reason).

    Each applies on its own (Kim, 2026-10-22, decision 98), except where it can't be written: a Scale Insights change
    beyond the standard AI setup (si_beyond_standard, a new rule set such as an unmade strategy) is Kim's, and a new
    Sponsored Brands video campaign without a video asset can't be built."""
    if ctype in SI_TYPES:
        if change.get('si_beyond_standard'):
            return 'human', (f"{change['si_beyond_standard']}: a Scale Insights rule set beyond the standard AI setup is "
                             "Kim's call")
        return 'auto', ('the standard Scale Insights setup of an AI product (no-bid-rule strategies, exact owners off the '
                        'blacklist, the harvest import): done in the signed-in browser and read back '
                        '(scale-insights-playbook.md)')
    if ctype == 'New SB video campaign':
        if not change.get('video_asset'):
            return 'human', ("the product file has no Sponsored Brands video asset (sb_video.video_asset_id), so the "
                             'campaign can\'t be built: a person adds the asset')
        return 'auto', ("a Sponsored Brands video keyword for an invest search at its invest bid x the video click ratio "
                        '(rulebook 5b)')
    if ctype == 'SB bid optimisation':
        return 'auto', ("Amazon's bid optimisation off in an older Sponsored Brands campaign: the bids then stay at the AI's price, "
                        'and its positive placement modifiers go to 0% (decision 155)')
    if ctype == 'Ad group default bid':
        return 'auto', ('the default bid of an ad group whose keywords or targets bid it: priced like a Discovery keyword, cut '
                        'only (decision 155)')
    if ctype == 'SB pause keyword':
        return 'auto', 'pause: an older Sponsored Brands copy of an invest search, or an irrelevant one; a pause is never held back'
    if ctype in ('Negative exact', 'Archive negative'):
        return 'auto', 'funnel negative: the owner campaign takes the search (rulebook section 3)'
    if ctype in ('Harvest default bid', 'Harvest setup'):
        return 'auto', "the harvest ad group's starting bid, worked out by the rulebook (section 5)"
    if ctype == 'Budget step':
        if change.get('rank_campaign'):
            return 'auto', ('budget headroom: a rank campaign out of budget steps up whatever its ACOS, losses are accepted '
                            'for ranking (decision 174; budget-headroom.md)')
        return 'auto', 'budget headroom: out of budget at a low ACOS, or a step that stopped paying goes back (budget-headroom.md)'
    if change.get('season_harvest'):
        return 'auto', 'season: top of search back to 0% on a search the season does not invest in (rulebook section 8)'
    if change.get('placement_policy'):
        return 'auto', ('placement policy: top of search to 0% on a campaign that is not a rank campaign; it can only lower '
                        'bids (decision 155)')
    return 'auto', "its role's standard budget and top of search (rulebook 7.5)"


def classify(change, term, ctx):
    """Return (lane, reason, evidence) for one change. `term` is the search's plan.py record, or None without SQP.

    A row made from a business (Amazon Business) keyword takes the same rules as a consumer one, judged on the business
    record of its search (plan.py's business_terms: its index, orders and clicks are the B2B keyword's own), with its
    locks and its invested searches kept per shopper kind (search_lock_key, invested_cut). There is no business-only rule
    (design 2026-10-21-b2b-lane-and-roles 4d).

    evidence holds confidence, confidence_kind ('beats' or 'below') and opportunity, and new_capped when a raise
    went past the per-run cap or a big cut steps down: the planner writes that bid instead of `new` on an automatic row.
    raises_used_up is True on a raise held only because the run's automatic raises ran out; it keeps new_capped too.

    Bid and rank calls are the AI's (Kim, 2026-10-23, decision 107: "the bid changes and rank investments are all
    actually programmatically calculated and quantifiably decided"). The human list: a lock (a person's decision); a
    price; a Scale Insights change beyond the standard setup; a row that can't be written (no video asset, no B2B campaign
    for a new keyword, an unknown type); and a head-term promotion (one word, or not in the product's lists). A close call
    is the AI's "not yet" (monitor); a big cut on 3+ orders steps down big_cut_pct this run; a search-term-fallback
    promotion goes out as a Prove-first test; a raise past the run's count, a stop-loss with no step-down that can be
    written yet and a row with no current or new bid are held for the next run; a non-standard budget or boost is
    written at the standard (plan_lanes). Money parks nothing (decisions 99 and 100): the investment guide, the product's
    band and the $60 loss line for one search are information on the row and the run's summary.
    """
    a = ctx.auto
    ctype = change.get('type')
    current, new = change.get('current'), change.get('new')
    orders, clicks = _counts(change, term)
    index = _index(change, term)
    confidence, kind = _confidence(change, orders, clicks, _baseline(change, term))
    orders = _ladder_orders(term, orders)   # the ladder's count: SQP or ads, whichever shows more (decision 174)
    opportunity = None
    if term:
        opportunity = evidence.opportunity(term.get('index'), term.get('sqp_volume'), term.get('observed_days'))
    ev = {'confidence': confidence, 'confidence_kind': kind, 'opportunity': opportunity}

    # 1. A person's decision, then data that isn't fresh. Stale data holds every row (monitor: not applied, not escalated;
    #    autonomous runs, 2026-10-22): the next run with fresh data judges them again. Low stock is a separate inventory
    #    alert (stock_reorder), not stale data or an Auto hold (Kim, 2026-10-24). An onboarding product and a
    #    seasonal phase switch are no longer a person's call (decision 98): their rows are judged like any other's
    hit = lock_on(change, ctx)
    if hit:
        return 'human', hit[1], ev
    if ctx.stale:
        return 'monitor', f'the product data is not fresh: {ctx.stale}', ev

    # 2. A stop-loss step-down (stop_loss.py): the rulebook's own exit for an invest search with no gain after its weeks,
    #    written by the planner, so it applies on its own whatever the size of the cut (Kim, 2026-10-22)
    if change.get('stop_loss_step_down') is True:
        return 'auto', change.get('stop_loss_reason') or 'stop-loss step-down: no organic gain at a stop-loss checkpoint', ev
    # ...and a search it stepped down is not re-invested in for the cool-off weeks: held, not escalated (2026-10-22)
    cooled = _cooloff_hold(change, ctx)
    if cooled:
        return 'monitor', cooled, ev

    # 3. The types that are a person's call, and the executable rows that apply on their own
    policy_only = policy_tos_only(change)  # judged like a promotion below
    if ctype == 'Listing price':
        return 'human', "a price change is Kim's call (rulebook section 6)", ev
    if ctype == 'Stop-loss review':
        return 'monitor', ('no step-down can be written for this search yet (its why says what is missing): held, and '
                           'the next run tries again (decision 107)'), ev
    if ctype == STRATEGY:
        if change.get('audience') and not change.get('audience_auto'):
            return 'human', ("an audience (AMC, low-bid) campaign: people own these (decision 107) and its audience boost "
                             'compounds on the bid, so a person decides whether it moves to down-only bidding'), ev
        if change.get('scope_unverified'):
            return 'human', ('the campaign is not shown to advertise this product alone, so moving it to down-only bidding '
                             'is a person\'s call'), ev
        if change.get('audience'):
            return 'auto', ('down-only bidding on an audience (AMC, low-bid) copy: Amazon may lower a bid in an auction, never '
                            'raise it, so it moves on its own like any other campaign (decision 155)'), ev
        return 'auto', 'down-only bidding: Amazon may lower a bid in an auction, never raise it (decision 140)', ev
    if ctype == SHAPE:
        return 'auto', ("the product-page base bid: no placement bids more than the plan priced it (decision 140; written "
                        'only where every bid of the campaign applies on its own)'), ev
    if ctype in AUTO_TYPES and not policy_only and ctype != SB_BID:
        lane, reason = _executable_lane(change, ctype)
        return lane, reason, ev
    if is_business_new_keyword(change) and not (change.get('campaign_id') and change.get('ad_group_id')):
        return 'human', ("the B2B exact campaign or its ad group isn't known, so there is nothing to write: a person checks "
                         'the Ads console first (its how says what to do)'), ev
    if ctype not in JUDGED_TYPES + (SB_BID,) and not policy_only and not is_business_new_keyword(change):
        return 'human', (f"{ctype or 'a change with no type'} is not one of the automatic change types, "
                         'so a person decides'), ev
    if ctype in CUT_BID_TYPES and (current is None or new is None):
        return 'monitor', 'the row has no current or no new bid yet: held, and the next run tries again (decision 107)', ev

    # 4. Cuts are never held back (Invest, Prove-first and invested searches too, since 2026-10-22: the stop-loss and the
    #    planner's roles are the exits, decision 98), except a big bid cut on a proven search while auto.big_cut_pct is set
    #    (null since decision 168: a cut goes straight to its price too). A pause, with or without
    #    orders, applies on its own: the guard reads bid cuts only (until 2026-10-22 a pause with orders went to a person)
    if is_cut(change):
        if ctype in CUT_BID_TYPES:
            pct = round((current - new) / current * 100, 6)
            # a copy's holding bid (copy_hold, decision 135) is not stepped: its search's orders move to the new owner
            if (a.get('big_cut_pct') is not None and pct > a['big_cut_pct'] and orders >= a['big_cut_orders']
                    and change.get('copy_hold') is not True):
                # a step, not a person's call (decision 107): the cut goes out at big_cut_pct this run, and the next run
                # takes the rest if the numbers still say so; the auto lane writes the step (new_capped)
                step = round(current * (1 - a['big_cut_pct'] / 100), 2)
                ev['new_capped'] = step
                return 'auto', (f"a {pct:.0f}% cut on a search that already has {_orders(orders)}: it steps down "
                                f"{a['big_cut_pct']:g}% this run, from {_money(current)} to {_money(step)}, and the next "
                                f"run takes the rest to {_money(new)} if the numbers still say so"), ev
            return 'auto', f'cut from {_money(current)} to {_money(new)}: a cut is never held back', ev
        return 'auto', 'pause: a cut is never held back', ev

    # 5. Promotions, and a live rank campaign's top of search set to the standing policy. A consumer row first passes the
    #    data-stage checks (_stage_hold: the fallback, the head-term flags, a volatile week, one SQP week in early); a business
    #    row is judged as before, on its own record (design 4d; data-stage design, 2026-10-22). A business invest search's
    #    new exact keyword is judged as a promotion (it adds an invest search)
    promotion = ctype in PROMOTION_TYPES or is_business_new_keyword(change)
    if (promotion or policy_only) and ctype != 'Business invest' and change.get('owner_kind') != 'business':
        held = _stage_hold(change, term, ctx)
        if held:
            return held[0], held[1], ev
    if promotion:
        lane, reason = _promotion_lane(change, term, ctx, orders, index, opportunity)
        return lane, reason, ev
    if policy_only:
        lane, reason = _policy_tos_lane(change, term, ctx, orders, index, opportunity)
        return lane, reason, ev

    # 6. Raises. A raise on the live keyword of a search promoted on the search-term fallback is a person's call (R34,
    #    2026-10-22): the fallback supports Prove first and nothing more, never a raise (data-stage design 4.4.2), and
    #    _raise_lane's suggested-range rule needs no index, so it would lane the re-price automatic. Cuts returned in section
    #    4; a business row is judged as before. A Sponsored Brands raise takes the same caps (_sb_raise_lane)
    if (ctype == 'Bid change' and change.get('owner_kind') != 'business' and new > current
            and (term or {}).get('index_status') == 'product_market_fallback'):
        return 'monitor', ('promoted on the search-term fallback (no SQP row yet): its live keyword keeps its bid, since the '
                           'fallback supports a Prove-first test in its own exact campaign and never a raise'), ev
    if ctype == SB_BID:
        lane, reason, capped, used_up = _sb_raise_lane(change, ctx)
    else:
        lane, reason, capped, used_up = _raise_lane(change, term, ctx, orders, index, opportunity)
    if capped is not None:
        ev['new_capped'] = capped
    if used_up:
        ev['raises_used_up'] = True
    return lane, reason, ev


# --- Apply guard: the two checks around live writes ---------------------------------------------------------------

def _nth_sunday(year, month, n):
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def _la_offset_hours(moment_utc):
    """Los Angeles' offset from UTC in hours at an aware UTC moment: -7 (PDT) or -8 (PST).

    The US rule, worked out here so no timezone database is needed: the clocks go forward at 02:00 PST (10:00 UTC) on
    the second Sunday of March and back at 02:00 PDT (09:00 UTC) on the first Sunday of November.
    """
    year = moment_utc.year
    forward = datetime.combine(_nth_sunday(year, 3, 2), time(10, 0), tzinfo=timezone.utc)
    back = datetime.combine(_nth_sunday(year, 11, 1), time(9, 0), tzinfo=timezone.utc)
    return -7 if forward <= moment_utc < back else -8


def us_date(now_utc):
    """The calendar date in Los Angeles at `now_utc`, weekend or not.

    `now_utc` must carry a timezone (any zone is read as the instant it is). A naive time raises ValueError rather
    than being guessed at; the date is used for reporting and schedule interpretation.
    """
    if now_utc.utcoffset() is None:
        raise ValueError('a timezone-aware time is needed to work out the US date')
    moment = now_utc.astimezone(timezone.utc)
    return (moment + timedelta(hours=_la_offset_hours(moment))).date()


def first_us_weekday(now_utc):
    """The first Monday to Friday date, as Los Angeles keeps it, on or after `now_utc`.

    Retained calendar helper for historical consumers/tests. It no longer controls plan eligibility or execution.
    """
    day = us_date(now_utc)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def us_write_window_open(now_utc, apply_after):
    """Audits execute any day. Legacy apply_after was only a generated weekday delay.

    Keep this interface for saved plans; approval, ownership, eligibility and readback
    controls remain independent. An ambiguous timestamp is still invalid.
    """
    us_date(now_utc)
    return True


def _row_id(row):
    """A MAP payload or live row's id as a string (the id may arrive as an int or a string), or None.

    keywordId, targetId and themeId share one namespace: Amazon ids are globally unique, so one id never names both a keyword
    and a target.
    """
    for key in ('keywordId', 'targetId', 'themeId'):
        if row.get(key) is not None:
            return str(row[key])
    return None


def _bid_differs(written, live):
    try:
        gap = round(abs(float(written) - float(live)), 6)
    except (TypeError, ValueError):
        return True  # a bid that is missing or unreadable can't be confirmed
    return not gap <= 0.005  # written as "not <=" so a NaN gap can't pass as a match


def _under_modifier(written, live, modifiers):
    """The live bid is the written one times a dayparting modifier (rounded to the cent, a cent either way)."""
    try:
        w, l = float(written), float(live)
    except (TypeError, ValueError):
        return False
    return any(abs(l - round(w * float(m), 2)) <= 0.011 for m in modifiers or ())


def _state_differs(written, live):
    return live is None or str(written).lower() != str(live).lower()


def _compared(row, has_bid, has_state):
    """The value or values of a row that read-back compares: the bid, the state, or both as a dict."""
    if has_bid and has_state:
        return {'bid': row.get('bid'), 'state': row.get('state')}
    if has_bid:
        return row.get('bid')
    if has_state:
        return row.get('state')
    return None


def readback_mismatches(written, live, modifiers=()):
    """The written rows the account doesn't show as written: `[{id, written, live}]`, in the order written.

    `written` is the payload sent to MAP (`keywordId` or `targetId`, with `bid` and/or `state`); `live` is the same
    rows read back (id, `bid`, `state`). A row is checked only on what it carries: a state-only row on its state, a
    bid-only row on its bid, both on both. A bid differs by more than $0.005; states compare without regard to case;
    ids compare as strings and come back as strings. A written row that can't be confirmed is a mismatch with `live`
    None: one missing from `live`, one with no id to look up, or one carrying neither `bid` nor `state`. `written` and
    `live` hold the values compared: the bid, the state, or a dict of both (None when there was nothing to compare).
    `modifiers` (daypart_base.modifiers: rule 203's weekend 0.8 since 2026-10-31, 0.6 before) are dayparting modifiers: a live bid at the written bid x
    one of them is Scale Insights applying its hours to the written bid, so it reads back as written (decision 152).
    """
    live_by_id = {}
    for row in live:
        row_id = _row_id(row)
        if row_id is not None:
            live_by_id[row_id] = row
    out = []
    for row in written:
        row_id = _row_id(row)
        has_bid, has_state = row.get('bid') is not None, row.get('state') is not None
        sent = _compared(row, has_bid, has_state)
        match = live_by_id.get(row_id)
        if match is None or not (has_bid or has_state):
            out.append({'id': row_id, 'written': sent, 'live': None})
        elif ((has_bid and _bid_differs(row['bid'], match.get('bid'))
               and not _under_modifier(row['bid'], match.get('bid'), modifiers))
              or (has_state and _state_differs(row['state'], match.get('state')))):
            out.append({'id': row_id, 'written': sent, 'live': _compared(match, has_bid, has_state)})
    return out


# --- The 24-hour spend check: when a product's automatic changes switch off ---------------------------------------

SPEND_TRIP_RATIO = 1.5  # the next weekday's spend trips the check when it is over this many times the average


def spend_check(next_weekday_spend, last14_weekday_spends):
    """True when the product's auto lane must switch off: the next US weekday's spend is over 1.5 times the average.

    `last14_weekday_spends` is the product's ad spend on the US weekdays of the 14 days before the apply (Los Angeles
    dates; the caller picks the days and passes their spends). An empty history is False, since
    there is nothing to compare with. A NaN or infinite spend, now or in the history, is True: the check fails safe.
    A negative spend is a data error, so it raises ValueError rather than being guessed at (-inf is negative too).
    """
    history = list(last14_weekday_spends)
    values = [next_weekday_spend, *history]
    if any(value < 0 for value in values):
        raise ValueError('a spend cannot be negative')
    if not all(math.isfinite(value) for value in values):
        return True
    if not history:
        return False
    average = sum(history) / len(history)
    # With an average of 0 this is simply next > 0, so a jump from nothing trips.
    return next_weekday_spend > SPEND_TRIP_RATIO * average
