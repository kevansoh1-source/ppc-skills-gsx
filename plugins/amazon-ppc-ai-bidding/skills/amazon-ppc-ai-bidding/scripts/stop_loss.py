"""Stop-loss step-downs: the rows that carry out the rulebook's exit for an invest search (rulebook section 4).

Autonomous runs (Kim, 2026-10-22, decision 98: "the AI applies stop-loss step-downs itself and notes them"). Until then
plan.py raised a 'Stop-loss review' row and a person stepped the search down by hand. Now, where the stop-loss finds no
gain after its weeks (4-6, or 2 and 4 on a seasonal rank build), the planner writes the step-down itself:
  - the search's owner keyword back to its breakeven bid (Hold), a 'Bid change' row;
  - its campaign's top of search back to 0% and its budget to the small standard one (consumer: min(live, $5/day); a B2B
    campaign keeps its live budget, rulebook 9.6), a 'Budget and top of search' row, when the campaign was read live.
Both rows carry stop_loss_step_down True and the reason (stop_loss_reason): lanes.classify sends them to Auto after the lock
and fresh-data checks, whatever the size of the cut, and log_invest.py takes the search out of the invest log once one of
them went out (from any folder). A row the plan already has on the owner keyword is marked instead of a second one, and a
budget step on the campaign is dropped: a step-down never raises a budget. Where no owner keyword can be found, nothing can
be written and the caller keeps a 'Stop-loss review' row for a person (the one stop-loss judgement left to people).
Standard library only (plus searchtext).
"""
from searchtext import norm

STEP = 8  # the stop-loss rows' step on the preview, as the review rows had
BID_TOLERANCE = 0.005  # a live bid this close to breakeven is already at Hold


def owner_row(keyword_plan, search, business=False, keyword_id=None):
    """The keyword plan row that owns `search`, or None: for a consumer search its exact keyword in an exact SKC (rulebook 3;
    the one with the most clicks when there are copies), for a business one the B2B exact keyword `keyword_id` names (the
    business owner, plan.py's owner_by_search), else its B2B exact keyword with the most clicks."""
    rows = [p for p in keyword_plan if p.get('match') == 'exact'
            and norm(str(p.get('keyword') or '')) == search and (p.get('owner_kind') == 'business') == business
            and p.get('keyword_id')]
    if business:
        named = [p for p in rows if keyword_id is not None and str(p['keyword_id']) == str(keyword_id)]
        rows = named or rows
    else:
        rows = [p for p in rows if p.get('family') == 'SKC']
    if not rows:
        return None
    return max(rows, key=lambda p: (p.get('clicks90') or 0, -rows.index(p)))


def step_down(changes, add, search, owner, reason, live_budget_tos, budget_to=None, campaign=True, owner_kind=None, bid_to=None):
    """Write the step-down of one invested search into the plan. Returns 'written' (a row was added or marked), 'nothing to
    write' (the live keyword and campaign are already at Hold), or None when there is no owner keyword (the caller keeps a
    'Stop-loss review' row for a person).

    `changes` is the plan's change list and `add` its add(); `owner` the owner keyword's plan row (owner_row); `reason` the
    stop-loss's words, on every row; `live_budget_tos(campaign_id)` -> (budget, top of search, other placements) as plan.py
    reads the live campaign (budget None: not read live, so no campaign row is written). `budget_to` caps the campaign's
    budget (the consumer Hold budget, $5/day); None keeps it as live (a B2B campaign). `campaign` False leaves the campaign
    alone (a B2B campaign another business invest still uses). `bid_to` (decision 182, a search over the rank volume cap)
    steps the keyword to the higher of its breakeven and this bid (the suggested low) instead of breakeven; never a raise."""
    if owner is None:
        return None
    kid, cid = str(owner['keyword_id']), str(owner['campaign_id'])
    be = round(max(owner['breakeven_cpc'], bid_to or 0), 2)
    mark = dict(stop_loss_step_down=True, stop_loss_reason=reason)
    kind = dict(owner_kind=owner_kind) if owner_kind else {}
    wrote = False
    existing = [x for x in changes if str(x.get('keyword_id')) == kid and x.get('type') in ('Bid change', 'Pause keyword')]
    for x in existing:
        # the plan already moves the owner keyword (its index slipped, or it pauses): that row is the step-down, at no more
        # than breakeven; for a search over the rank cap (bid_to), no more than its suggested low and never above its live bid
        to = min(be, x['current']) if bid_to and x.get('current') else be
        if x['type'] == 'Bid change' and x.get('new') is not None and x['new'] > to:
            x['new'] = to
            x['change'] = round(to / x['current'] - 1, 3) if x.get('current') else None
        x.update(mark, why=f"{x.get('why') or ''} Stop-loss: {reason}".strip())
        wrote = True
    if not existing and owner.get('bid') is not None and owner['bid'] > be + BID_TOLERANCE and not owner.get('not_live'):
        current = round(owner['bid'], 2)
        # an owner keyword paused live keeps its pause: the step-down is a cut only, flagged so the pre-write check and
        # the read-back compare it with the paused live row (decision 155), never "no longer enabled"
        paused = dict(paused=True) if owner.get('paused_live') else {}
        add(step=STEP, type='Bid change', keyword=search, match='exact', family=owner.get('family'), role='Hold',
            campaign=owner.get('campaign'), current=current, new=be, change=round(be / current - 1, 3) if current else None,
            clicks90=owner.get('clicks90'), orders90=owner.get('orders90'), spend90=owner.get('spend90'),
            cvr=owner.get('cvr_used'), breakeven=be, keyword_id=kid, campaign_id=cid, ad_group_id=owner.get('ad_group_id'),
            why=(f'Stop-loss step-down: {reason}. Back to its breakeven click (Hold).' if not bid_to else
                 f'Step-down: {reason}. To the suggested low (${be:.2f}, never under breakeven).')
            + (' The keyword is paused live and stays paused.' if paused else ''),
            how='MAP update sp_keywords: bid' + (' (the keyword stays paused)' if paused else ''),
            **mark, **kind, **paused)
        wrote = True
    if campaign:
        budget_now, tos_now, others = live_budget_tos(cid)
        if budget_now is not None:
            budget = budget_now if budget_to is None else min(budget_now, budget_to)
            # a step-down never raises the campaign's budget: a budget step planned on it this run is dropped
            changes[:] = [x for x in changes if not (x.get('type') == 'Budget step' and str(x.get('campaign_id')) == cid)]
            row = next((x for x in changes if x.get('type') == 'Budget and top of search' and str(x.get('campaign_id')) == cid),
                       None)
            if row is not None:
                row.update(mark, role='Hold', tos=0, budget=min(row.get('budget') or budget, budget), policy_tos_only=False,
                           why=f"{row.get('why') or ''} Stop-loss: {reason}".strip())
                wrote = True
            elif (tos_now or 0) != 0 or budget != budget_now:
                add(step=STEP, type='Budget and top of search', keyword=search, role='Hold', campaign=owner.get('campaign'),
                    budget_now=budget_now, budget=budget, tos_now=tos_now, tos=0, campaign_id=cid, other_placements=others,
                    why=(f'Stop-loss step-down: {reason}. Top of search back to 0%'
                         + (f' and the budget to ${budget:g}/day.' if budget != budget_now else '; the budget stays as live.')),
                    how='MAP update sp_campaigns: budget + complete dynamicBidding, top of search 0% (send every existing placement)',
                    **mark, **kind)
                wrote = True
    return 'written' if wrote else 'nothing to write'
