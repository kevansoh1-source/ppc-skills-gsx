"""Campaign-level placement experiments for review, never an Ads write."""
import datetime as dt
import html
import json
import math
import re
from collections import Counter
from pathlib import Path

PLACEMENTS = {'TOP_OF_SEARCH': 'Top of search', 'PRODUCT_PAGE': 'Product pages', 'REST_OF_SEARCH': 'Rest of search'}
ALIASES = {'Top of Search on-Amazon': 'TOP_OF_SEARCH', 'Detail Page on-Amazon': 'PRODUCT_PAGE',
           'Other on-Amazon': 'REST_OF_SEARCH', 'PLACEMENT_TOP': 'TOP_OF_SEARCH',
           'PLACEMENT_PRODUCT_PAGE': 'PRODUCT_PAGE', 'PLACEMENT_REST_OF_SEARCH': 'REST_OF_SEARCH'}
SOURCE = 'Amazon Ads Sponsored Products campaign placement report via MarketplaceAdPros run_report_sql; purchases14d / clicks. Campaign-level, not keyword-level or market placement CVR. Advertised-ASIN scope does not guarantee purchased-ASIN-only attribution.'


def settings(campaign):
    bid = (campaign.get('optimizations') or {}).get('bidSettings')
    if not isinstance(bid, dict) or 'bidAdjustments' not in bid:
        return None, None
    values = {key: 0 for key in PLACEMENTS}
    for row in bid['bidAdjustments'].get('placementBidAdjustments', []):
        key = ALIASES.get(row.get('placement'), row.get('placement'))
        if key in values:
            values[key] = row['percentage']
    return values, bid


RANK_ROLES = ('Invest', 'Prove first')
# A placement experiment in a campaign's name ("Single Product Targeting - TOS 900%"). The standing rank policy leaves such a
# campaign alone. The rank campaigns the planner names itself end in "TOS Rank", which is not one, so config.json's plain
# "TOS" marker for product targets is not used here.
EXPERIMENT_MARKER = re.compile(r'\bTOS\s*[+-]?\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*%\s*TOS\b', re.IGNORECASE)


def rank_tos(placement, role):
    """The standing policy's top-of-search percentage for a rank-investment role (config.json placement.rank_tos_standing,
    Kim 2026-10-20), or None: the flag is not exactly true, the role is not Invest or Prove first, or the percentage in
    the config is not a number from 0 to 900. `placement` is config.json's `placement` block; None means no policy."""
    standing = (placement or {}).get('rank_tos_standing')
    if not isinstance(standing, dict) or standing.get('approved') is not True or role not in RANK_ROLES:
        return None
    value = placement.get('prove_tos_pct' if role == 'Prove first' else 'invest_tos_pct')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 900:
        return None
    return value


def other_placements(campaign):
    """A live campaign's placement modifiers other than top of search, as the campaign returns them."""
    bid = (campaign.get('optimizations') or {}).get('bidSettings')
    rows = ((bid or {}).get('bidAdjustments') or {}).get('placementBidAdjustments') or []
    return [dict(row) for row in rows if ALIASES.get(row.get('placement'), row.get('placement')) != 'TOP_OF_SEARCH']


def standing_blocker(name, new, campaign, current, bid):
    """Why the standing policy does not set this campaign's top of search, or None when it does. A new campaign has
    nothing live to read. The payload writes down-only bidding and the placement percentages, so a live campaign that write
    would change by more than that is left as it is."""
    if EXPERIMENT_MARKER.search(name or '') or EXPERIMENT_MARKER.search(campaign.get('name') or ''):
        return 'The campaign name carries a placement experiment, which is left alone.'
    if new:
        return None
    if current is None:
        return 'The live placement settings were not read.'
    if campaign.get('globalCampaignId'):
        return 'It is a global campaign.'
    if bid.get('bidStrategy') != 'SALES_DOWN_ONLY':
        return f"It is not on down-only bidding (live strategy: {bid.get('bidStrategy')}), and the write would change that."
    if (bid.get('bidAdjustments') or {}).get('audienceBidAdjustments'):
        return 'It has audience adjustments, which the write would not carry.'
    return None


def policy_blocker(campaign):
    """Why the placement policy (decision 155) can't set this live campaign's top of search this run, or None when it can.
    As standing_blocker, except that a placement experiment in the name is no reason: the policy ends the experiment (the
    "TOS 900%" campaigns nobody bid). The write sends down-only bidding and every placement, so a campaign on another bidding
    strategy, with audience adjustments, a global one or one not read live keeps its boost, and plan.py prices its non-rank
    bids at price / (1 + boost) instead."""
    current, bid = settings(campaign)
    if current is None:
        return 'The live placement settings were not read.'
    if campaign.get('globalCampaignId'):
        return 'It is a global campaign.'
    if bid.get('bidStrategy') != 'SALES_DOWN_ONLY':
        return f"It is not on down-only bidding (live strategy: {bid.get('bidStrategy')}), and the write would change that."
    if (bid.get('bidAdjustments') or {}).get('audienceBidAdjustments'):
        return 'It has audience adjustments, which the write would not carry.'
    return None


STRATEGY_TYPE = 'Bidding strategy'
STRATEGY_WORDS = {'SALES_UP_AND_DOWN': 'up and down', 'SALES_DOWN_ONLY': 'down only', 'MANUAL': 'fixed bids',
                  'RULE_BASED': 'rule-based'}


def strategy_rows(campaigns, asin, placement, kind, snapshot=None):
    """The 'Bidding strategy' rows of a plan (Kim, 2026-10-26, decision 140): one per live (ENABLED) Sponsored Products
    campaign on up-and-down bidding, moving it to down only. Up and down lets Amazon raise a bid up to 100% at the top of
    search and 50% elsewhere; down only never raises it. The write resends the campaign's placement and audience adjustments
    exactly as live (MAP's optimizations shape), so nothing else changes. A global campaign is left out (its bid settings
    can't be changed through the API yet). `placement` is config.json's placement block: placement.down_only.enabled false
    plans none. `kind` is plan.py's kind(name). `snapshot` is placement_inputs.json (read_inputs) or None: its live_asins
    say whether the campaign advertises this product alone.

    Each row carries `audience` (an audience copy: AMC or low-bid by name, or audience adjustments) and `scope_unverified`
    (the campaign is not shown to advertise this product alone): lanes.classify sends either to a person."""
    if not ((placement or {}).get('down_only') or {}).get('enabled'):
        return []
    live_asins = (snapshot or {}).get('live_asins') or {}
    rows = []
    for c in campaigns:
        bid = (c.get('optimizations') or {}).get('bidSettings')
        if ((c.get('state') or '').upper() != 'ENABLED' or c.get('globalCampaignId') or not isinstance(bid, dict)
                or bid.get('bidStrategy') != 'SALES_UP_AND_DOWN'):
            continue
        cid = str(c.get('campaignId'))
        adjustments = bid.get('bidAdjustments') if isinstance(bid.get('bidAdjustments'), dict) else {}
        audience = kind(c.get('name')) == 'audience' or bool(adjustments.get('audienceBidAdjustments'))
        alone = snapshot is not None and set(live_asins.get(cid) or []) == {asin}
        why = ('Up-and-down bidding lets Amazon raise this campaign\'s bids up to 100% at the top of search and 50% elsewhere, '
               'above the price the planner set; down only never raises them (decision 140). Its placement'
               + (' and audience' if adjustments.get('audienceBidAdjustments') else '') + ' adjustments stay as they are.')
        audience_auto = bool(((placement or {}).get('down_only') or {}).get('audience_auto'))
        if audience and not audience_auto:
            why += (' An audience (AMC, low-bid) campaign: people own these (decision 107), and its audience boost compounds on '
                    'the bid, so a person decides.')
        elif not alone:
            why += (' Not shown to advertise this product alone (' + ('its live product ads were not read'
                    if snapshot is None or cid not in live_asins else 'it advertises other products too') + '), so a person decides.')
        elif audience:
            why += (' An audience (AMC, low-bid) copy: down only can never raise its bids, so it moves on its own too '
                    '(decision 155).')
        rows.append(dict(step=6, type=STRATEGY_TYPE, item=f"Bidding: {STRATEGY_WORDS['SALES_UP_AND_DOWN']} to "
                                                           f"{STRATEGY_WORDS['SALES_DOWN_ONLY']}",
                         campaign=c.get('name'), campaign_id=cid, strategy_now='SALES_UP_AND_DOWN', strategy='SALES_DOWN_ONLY',
                         bid_adjustments=json.loads(json.dumps(adjustments)), audience=audience, scope_unverified=not alone,
                         audience_auto=audience and audience_auto,
                         budget_now=(c.get('budget') or {}).get('budget'), why=why,
                         how=('MAP update sp_campaigns: optimizations.bidSettings, bidStrategy SALES_DOWN_ONLY with every live '
                              'placement and audience adjustment sent back unchanged (map-playbook.md, "Down-only bidding")')))
    return rows


def hold_defaults(changes, campaigns, placement=None):
    """Hold every placement of the invest campaigns a plan creates or changes: a new campaign starts at 0%, a live one keeps
    its modifiers and strategy (a placement experiment needs its own approval).

    Exception: with the standing rank policy on (`placement` is config.json's `placement` block, rank_tos_standing approved),
    a row whose role is Invest or Prove first takes the planner's policy top of search instead (+50% / +30%). A new campaign
    is created at it; a reused or budget row sets top of search to it and carries the live campaign's other placement
    modifiers unchanged. A campaign with a placement experiment in its name, on another bidding strategy, with audience
    adjustments or not read live is held as above, with the reason in placement_note. Without `placement`, or with the flag
    off, this is exactly the hold.

    A business invest (a 'Business invest' row, or a business 'New exact keyword' row adding the keyword to a live B2B
    campaign) is treated like a reused campaign: the team's B2B campaign takes the standing policy or keeps its live
    placements, with the reason (Kim, 2026-10-21: "treat it the same as the consumer rank campaigns"). A new keyword
    whose ad group isn't known yet writes nothing, so it is left as the planner wrote it (its how says what to do first)."""
    live = {str(item['campaignId']): item for item in campaigns}
    for row in changes:
        business = row['type'] == 'Business invest' or (row['type'] == 'New exact keyword' and row.get('owner_kind') == 'business'
                                                        and row.get('ad_group_id'))
        if row['type'] not in ('New exact campaign', 'Reuse exact campaign', 'Budget and top of search') and not business:
            continue
        new = row['type'] == 'New exact campaign'
        campaign = {} if new else live.get(str(row.get('campaign_id')), {})
        current, bid = settings(campaign)
        row['placement_previous_plan_tos'] = row.get('placement_previous_plan_tos', row.get('tos'))
        season_blocker = None
        if row.get('placement_policy') is True and row['type'] == 'Budget and top of search':
            # the placement policy (plan.py, decision 155): top of search to the policy, the rest as live, where the write
            # can be made safely; otherwise the row writes nothing (plan.py already priced the campaign's bids for the boost)
            blocker = policy_blocker(campaign)
            row.pop('placement_hold', None)
            row['policy_tos_only'] = False
            if blocker is None:
                row['tos_now'] = current['TOP_OF_SEARCH']
                row['other_placements'] = other_placements(campaign)
                row['placement_note'] = ('Placement policy: top of search to the policy; rest of search and product pages stay '
                                         'as live (the product-page base-bid shape owns them).')
            else:
                row['placement_hold'] = row['policy_blocked'] = True
                row['tos'] = row['tos_now'] = (current or {}).get('TOP_OF_SEARCH')
                row['placement_note'] = 'Placement policy not written: ' + blocker
                row['why'] = row.get('why', '') + ' Not written this run: ' + blocker
                row['how'] = 'Nothing to write this run: the boost stays and the bids are priced for it.'
            continue
        step_down = row.get('stop_loss_step_down') is True and row['type'] == 'Budget and top of search'
        if (row.get('season_harvest') is True or step_down) and not new:
            # a seasonal product's boost taken off (plan.py, docs/seasonal-bidding.md), or a stop-loss step-down
            # (stop_loss.py, autonomous runs 2026-10-22): top of search to 0%, the rest as live, where the write can be made
            # safely; otherwise held below, with the reason (a step-down then writes its budget only)
            season_blocker = standing_blocker(row.get('campaign'), new, campaign, current, bid)
            if season_blocker is None:
                row.pop('placement_hold', None)
                row['policy_tos_only'] = False
                row['tos'], row['tos_now'] = 0, current['TOP_OF_SEARCH']
                row['other_placements'] = other_placements(campaign)
                row['placement_note'] = (('Stop-loss step-down' if step_down else 'Season') + ': top of search back to 0%, so '
                                         'the breakeven bid is not multiplied at the top of search. Rest of search and product '
                                         'pages stay as live.')
                continue
        policy = rank_tos(placement, row.get('role'))
        blocker = None
        if policy is not None:
            blocker = standing_blocker(row.get('campaign'), new, campaign, current, bid)
            if blocker is None:
                standing = placement['rank_tos_standing']
                row.pop('placement_hold', None)
                row['rank_tos_standing'] = True
                row['tos'] = policy
                row['tos_now'] = None if new else current['TOP_OF_SEARCH']
                if not new:
                    row['other_placements'] = other_placements(campaign)
                if row['type'] == 'Budget and top of search':
                    # the budget is unchanged, so top of search to the policy is the row's only change: the lanes need not
                    # treat it as always a person's call (lanes.policy_tos_only)
                    row['policy_tos_only'] = row.get('budget') is not None and row.get('budget') == row.get('budget_now')
                if row.get('new') is not None:
                    row['tos_bid'] = round(row['new'] * (1 + policy / 100), 2)
                row['placement_note'] = (f"Rank-investment top of search follows the standing policy (+{policy:g}%, {standing.get('by', 'Kim')}, "
                                         f"{standing.get('on', '')}). Rest of search and product pages " + ('start at 0%.' if new else 'stay as live.'))
                continue
        row.pop('rank_tos_standing', None)
        if 'policy_tos_only' in row:
            row['policy_tos_only'] = False
        row['placement_hold'] = True
        row['tos'] = 0 if new else (current or {}).get('TOP_OF_SEARCH')
        row['tos_now'] = None if new else row['tos']
        row['placement_note'] = 'No campaign history: start at 0% for all placements.' if new else 'Hold all live placement modifiers and bidding strategy; placement experiments require separate approval.'
        if blocker:
            row['placement_note'] += ' The standing rank policy does not apply: ' + blocker
        if season_blocker:
            row['placement_note'] += ((" The stop-loss step-down's" if step_down else " The season's")
                                      + ' top of search 0% is not written: ' + season_blocker)
        if row.get('new') is not None and row['tos'] is not None:
            row['tos_bid'] = round(row['new'] * (1 + row['tos'] / 100), 2)
        if row['type'] == 'Budget and top of search':
            row['why'] = ('Stop-loss step-down, budget only. ' if step_down else 'Budget review only. ') + row['placement_note']
            row['how'] = 'MAP campaign budget only; omit dynamicBidding and optimizations.'
        elif new:
            row['how'] = 'After approval, create the exact campaign with down-only bidding and 0% placement modifiers.'
        elif business:
            # the negatives check before the bid goes up (or the keyword goes in) stays: the team's B2B ad groups carry
            # Scale Insights negatives
            # and a campaign not read live gets no budget (it is never lowered blind): the budget is checked first
            row['how'] = ('After approval, check the ad group for self-blocking negatives (references/live-checks.md); '
                          + ('add the exact keyword at its bid' if row['type'] == 'New exact keyword' else 'set the keyword bid')
                          + (' and the campaign budget only' if row.get('budget_now') is not None else
                             ' only (the campaign was not read live: check its budget before any change)')
                          + '; preserve complete live campaign bidding settings.')
        else:
            row['how'] = 'After approval, verify keyword ownership and change its bid/budget only; preserve complete live campaign bidding settings.'


def refresh_forecast(plan, product, shared):
    """Re-price the consumer re-rank rows at their campaigns' settled top of search, and the summary's invest totals from
    them. A business re-rank row (owner_kind 'business', plan.py: priced on its B2B keyword's own 90 days, whatever the
    top of search) is left as it is and out of the totals, as build leaves it out of them."""
    changes = {row['keyword']: row for row in plan['changes'] if row['type'] in ('New exact campaign', 'Reuse exact campaign', 'Budget and top of search')}
    terms = {row['term']: row for row in plan['terms']}
    consumer = [row for row in plan.get('rerank', []) if row.get('owner_kind') != 'business']
    for row in consumer:
        change = changes.get(row['keyword'])
        if not change or change.get('tos') is None:
            continue
        term = terms[row['keyword']]
        days = term.get('observed_days') or 84
        row['tos'] = change['tos']
        row['cpc'] = round(row['bid'] * (1 + row['tos'] / 200), 2)
        wanted = shared['budgets']['rerank_click_share_target'] * term['sqp_total_clicks'] * 30 / days
        spend = min(wanted * row['cpc'], row['budget'] * 30)
        orders = spend / row['cpc'] * min(term['cvr_est'], 1.5 * (term.get('market_cvr') or 0.09)) if row['cpc'] else 0
        row.update(spend=round(spend), orders=round(orders, 1), net=round(orders * product['profit_per_unit'] - spend), capped=wanted * row['cpc'] > row['budget'] * 30)
    for summary in plan.get('summary', []):
        summary.update(invest_plan_day=round(sum(row['spend'] for row in consumer) / 30, 1),
                       invest_orders_month=round(sum(row['orders'] for row in consumer)),
                       invest_net_month=round(sum(row['net'] for row in consumer)))


def read_inputs(run, asin):
    path = Path(run) / 'placement_inputs.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('asin') != asin or not data.get('complete'):
        raise ValueError('Placement snapshot must be complete and match this ASIN')
    seen = set()
    for row in data['rows']:
        key = (str(row['campaignId']), row['placement'])
        if row.get('asin') != asin or key in seen:
            raise ValueError('Mixed-ASIN or duplicate placement rows')
        seen.add(key)
        for suffix in ('30', '90', '_recent'):
            for field in ('clicks', 'orders', 'spend', 'sales'):
                value = row[field + suffix]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid placement metric: ' + field + suffix)
    return data


def recommend(plan, product, shared, data, today):
    policy = shared['placement']['recommendations']
    rates = [f"{role} +{rank_tos(shared['placement'], role):g}%" for role in RANK_ROLES if rank_tos(shared['placement'], role) is not None]
    standing = shared['placement'].get('rank_tos_standing') or {}
    result = dict(as_of=today, source=SOURCE, policy=policy, preview_only=True, rows=[],
                  note='Recommendation-only experiments; not included in executable bid payloads. Hold means no placement change, not necessarily a healthy campaign. New campaigns start at 0%; existing modifiers are preserved. No automatic transfer of ASIN-wide results to a campaign.'
                  + (f" Exception: top of search on rank-investment campaigns ({', '.join(rates)}) follows the standing policy ({standing.get('by')}, {standing.get('on')})." if rates else ''))
    if data is None:
        result.update(status='missing_data', reason='Hold all modifiers: missing placement_inputs.json; pull complete campaign placement data and live settings.', summary={'recommend':0, 'hold':0})
        return result
    result.update(status='ready', windows=data['windows'], retrieved_at=data['retrieved_at'], source_files=data.get('source_files', []))
    day = dt.date.fromisoformat(today)
    stale = (day - dt.date.fromisoformat(data['as_of'])).days not in range(policy['max_snapshot_age_days'] + 1)
    economics_date = product.get('economics_as_of')
    economics_ok = economics_date and 0 <= (day - dt.date.fromisoformat(economics_date[:10])).days <= policy['max_economics_age_days']
    profit = product.get('profit_per_unit')
    economics_ok = economics_ok and isinstance(profit, (int, float)) and profit > 0
    result['economics'] = dict(profit_per_unit=profit, as_of=economics_date, source='Saved product economics from Scale Insights costs; recheck price/fees before approval')
    mature_end = dt.date.fromisoformat(data['windows']['90d'][1])
    if (day - mature_end).days < policy['attribution_lag_days']:
        raise ValueError('Placement decision window has not matured for 14-day attribution')
    snapshot_day = dt.date.fromisoformat(data['as_of'])
    for window, length, end in [('30d', 30, mature_end), ('90d', 90, mature_end), ('recent', 30, snapshot_day - dt.timedelta(days=1))]:
        if data['windows'][window] != [(end - dt.timedelta(days=length - 1)).isoformat(), end.isoformat()]:
            raise ValueError('Placement window dates do not match the labelled duration')
    indexed = {(str(row['campaignId']), ALIASES.get(row['placement'], row['placement'])): row for row in data['rows']}
    # a campaign whose top of search this plan sets (the standing rank policy) is changing too: no second modifier is proposed on it.
    # A Business invest row re-bids its owner keyword inside a B2B campaign, as a reused exact campaign does, so its campaign
    # is changing whatever its top of search does (design 2026-10-21-b2b-lane-and-roles 4e). A B2B campaign whose owner is
    # already invested as planned (plan.py's business_live_invests: no row) runs the policy top of search that invest needs,
    # so it gets no proposal either, as the planner keeps it out of the budget steps
    changing = {str(row.get('campaign_id')) for row in plan.get('changes', [])
                if row['type'] in ('Bid change', 'Reuse exact campaign', 'Business invest', 'Pause keyword', 'Negative exact',
                                   'New exact keyword')
                or (row.get('rank_tos_standing') and row.get('tos') != row.get('tos_now'))}
    changing |= {str(x['campaign_id']) for x in plan.get('business_live_invests') or [] if x.get('campaign_id')}
    for campaign in data['campaigns']:
        if campaign.get('state') != 'ENABLED':
            continue
        identity = str(campaign['campaignId'])
        current, bid = settings(campaign)
        pooled = {}
        for suffix in ('30', '90'):
            total_clicks = sum(indexed.get((identity, placement), {}).get('clicks' + suffix, 0) for placement in PLACEMENTS)
            total_orders = sum(indexed.get((identity, placement), {}).get('orders' + suffix, 0) for placement in PLACEMENTS)
            pooled[suffix] = total_orders / total_clicks if total_clicks else 0
        for placement, label in PLACEMENTS.items():
            raw = indexed.get((identity, placement), {})
            selected = None
            for suffix, click_gate, order_gate in [('30', policy['min_clicks_30d'], policy['min_orders_30d']), ('90', policy['min_clicks_90d'], policy['min_orders_90d'])]:
                if raw.get('clicks' + suffix, 0) >= click_gate and (raw.get('orders' + suffix, 0) >= order_gate or raw.get('orders' + suffix) == 0):
                    selected = suffix
                    break
            shown = selected or '30'
            clicks, orders, spend, sales = (raw.get(field + shown, 0) for field in ('clicks', 'orders', 'spend', 'sales'))
            value = dict(campaign_id=identity, campaign=campaign['name'], placement=placement, label=label,
                         current=(current or {}).get(placement), proposed=(current or {}).get(placement), status='hold',
                         sufficient=selected is not None, window=shown + 'd', window_dates=data['windows'][shown + 'd'],
                         clicks=clicks, purchases=orders, spend=spend, sales=sales,
                         cvr=orders / clicks if clicks else None, cpc=spend / clicks if clicks else None,
                         acos=spend / sales if sales else None, cpa=spend / orders if orders else None,
                         sample_90d=dict(clicks=raw.get('clicks90', 0), purchases=raw.get('orders90', 0)),
                         recent=dict(clicks=raw.get('clicks_recent', 0), purchases=raw.get('orders_recent', 0), spend=raw.get('spend_recent', 0)),
                         strategy=(bid or {}).get('bidStrategy'), reason='', confidence='insufficient',
                         review_on=(day + dt.timedelta(days=policy['review_days'])).isoformat())
            result['rows'].append(value)
            def hold(reason, code):
                value.update(reason=reason, reason_code=code)
            if selected:
                value.update(confidence='operational sample; not statistical significance',
                             cvr_adjusted=(orders + shared['thresholds']['prior_clicks'] * pooled[selected]) / (clicks + shared['thresholds']['prior_clicks']))
                if economics_ok:
                    value['breakeven_cpc'] = profit * value['cvr_adjusted']
            # an Amazon Business (B2B) campaign is priced like any other (Kim, 2026-10-21; design
            # 2026-10-21-b2b-lane-and-roles 4e): one carrying a business invest is `changing` through its invest row, the
            # others may get a placement-economics proposal, information only since decision 155 (the placement policy and the
            # placement shape act on their own; Kim, 2026-10-31)
            if any(marker.lower() in campaign['name'].lower() for marker in shared['audience_campaign_markers']) or (bid or {}).get('bidAdjustments', {}).get('audienceBidAdjustments'):
                hold('Audience/AMC low-bid campaign is outside this sweep; preserve its compounded settings.', 'audience_excluded')
            elif set(data.get('live_asins', {}).get(identity, [])) != {product['asin']}:
                hold('Shared-ASIN or unverified live product-ad scope; no campaign-wide modifier inferred for this ASIN.', 'scope_unverified')
            elif not raw:
                hold('No exclusive-ASIN placement history for this campaign and placement.', 'no_history')
            elif not selected:
                hold('Insufficient mature placement data; no ASIN-wide or other-campaign substitution.', 'thin_data')
            elif stale or current is None or not economics_ok:
                hold('Refresh campaign snapshot and product economics before computing a modifier.', 'stale_or_missing')
            elif campaign.get('globalCampaignId') or value['strategy'] not in ('SALES_DOWN_ONLY', 'MANUAL'):
                hold('Global/rule-based/up-and-down bidding requires a separate effective-bid review; preserve strategy.', 'strategy_review')
            elif identity in changing:
                hold('This plan changes campaign keywords, bids or routing. Hold modifiers until post-change placement data matures.', 'base_or_mix_changes')
            elif value['recent']['clicks'] < policy['recent_min_clicks']:
                hold('Mature history exists but recent traffic is too thin to justify a current modifier test.', 'stale_traffic')
            elif not value['cpc']:
                hold('No usable paid CPC baseline.', 'no_cpc')
            else:
                ratio = value['breakeven_cpc'] / value['cpc'] if orders else 0
                recent = value['recent']
                recent_ratio = profit * recent['purchases'] / recent['spend'] if recent['spend'] else None
                if ratio > 1 + policy['deadband'] and recent['clicks'] >= policy['recent_min_clicks'] and recent_ratio is not None and recent_ratio < 1:
                    hold('Recent, still-maturing economics do not support an increase; wait for attribution.', 'recent_conflict')
                elif ratio < 1 - policy['deadband'] and recent['clicks'] >= policy['recent_min_clicks'] and recent_ratio is not None and recent_ratio > 1 + policy['deadband']:
                    hold('Recent economics have improved; hold rather than cut from older history.', 'recent_conflict')
                elif 1 - policy['deadband'] <= ratio <= 1 + policy['deadband']:
                    hold('CPC is within the proposed breakeven deadband; no material modifier change justified.', 'near_breakeven')
                elif ratio > 1 and value['current'] >= policy['max_positive_modifier']:
                    hold('Existing modifier is at/above the proposed positive cap; no further increase.', 'positive_cap')
                else:
                    target = max(0, (1 + value['current'] / 100) * ratio * 100 - 100)
                    if ratio > 1:
                        target = min(target, value['current'] + policy['max_step_pp'], max(value['current'], policy['max_positive_modifier']))
                        proposed = math.floor(target / policy['rounding_pp']) * policy['rounding_pp']
                    else:
                        target = max(target, value['current'] - policy['max_step_pp'])
                        proposed = math.ceil(target / policy['rounding_pp']) * policy['rounding_pp']
                    if abs(proposed - value['current']) < policy['rounding_pp']:
                        hold('Modifier already 0% or change below the minimum step; review base bids/offer separately, not a negative modifier.', 'no_modifier_headroom')
                    else:
                        value.update(status='recommend', proposed=proposed, reason_code='bounded_economics_test',
                                     reason='Bounded placement-only experiment from shrunk CVR and breakeven CPC; keep base bids, budgets and strategy unchanged.',
                                     modeled_cpc=value['cpc'] * (1 + proposed / 100) / (1 + value['current'] / 100),
                                     rollback='Restore the previous modifier if mature cost per purchase exceeds contribution per purchase or the separately approved rank-investment allowance. No automatic rollback.',
                                     assumption='Linear CPC response to the multiplier is a scenario, not an auction forecast; current base bids and traffic mix must be revalidated.')
    for change in plan.get('changes', []):
        if change['type'] == 'New exact campaign':
            for placement, label in PLACEMENTS.items():
                standing = placement == 'TOP_OF_SEARCH' and change.get('rank_tos_standing')
                result['rows'].append(dict(campaign_id=None, campaign=change['campaign'], placement=placement, label=label,
                                           current=None, proposed=change['tos'] if standing else 0, status='hold', sufficient=False, confidence='no history',
                                           reason=(f"Rank-investment top of search follows the standing policy (+{change['tos']:g}%); the campaign has no placement history to judge it by."
                                                   if standing else
                                                   'New campaign has no placement history. Start at 0%; do not inherit another campaign or ASIN-wide CVR.'),
                                           reason_code='standing_policy' if standing else 'new_campaign'))
    result['summary'] = dict(Counter(row['status'] for row in result['rows']))
    result['summary'].setdefault('recommend', 0)
    result['summary'].setdefault('hold', 0)
    result['supported_rows'] = sum(row['sufficient'] for row in result['rows'])
    return result


def attach(plan, product, shared, run, today):
    data = read_inputs(run, product['asin'])
    plan['placement_review'] = recommend(plan, product, shared, data, today)


def preview_html(review):
    if not review:
        return ''
    esc = lambda value: html.escape(str(value))
    pct = lambda value: '—' if value is None else f'{value:.2%}'
    money = lambda value: '—' if value is None else f'USD {value:.2f}'
    modifier = lambda value: 'new / unknown' if value is None else f'+{value:g}%'
    parts = ['<section id="placement-review"><h2>Placement recommendations — preview only</h2><p>' + esc(review.get('note', '')) + '</p>',
             '<p>' + esc(review.get('source', '')) + '</p><p>' + esc(review.get('reason', '')) + '</p>']
    if 'rank_experiments' in review:
        experiments = review['rank_experiments']
        parts.append('<h3>' + str(len(experiments)) + ' rank-investment experiments — proposed</h3><p>Early search conversion evidence, not proven placement superiority. Separate launch approval required.</p>')
        for experiment in experiments:
            parts.append('<p><strong>' + esc(experiment['keyword']) + ': +' + str(experiment['tos']) + '% TOS</strong> · Base ' + money(experiment['bid']) + ' → base × TOS multiplier ' + money(experiment['tos_bid']) + ' (before other boosts). ' + esc(experiment['evidence']) + ' Our / market observed CVR: ' + pct(experiment['our_cvr']) + ' / ' + pct(experiment['market_cvr']) + '; adjusted index ' + esc(experiment['index']) + '. ' + esc(experiment['source'] + ' · ' + experiment['window']) + '. ' + esc(experiment['guardrails']) + '</p>')
        parts.append('<h3>Placement economics — separate baseline assessment</h3><p>Baseline holds do not cancel the rank-investment proposals above.</p>')
    if review.get('windows'):
        parts.append('<p>Decision windows: ' + esc(review['windows']) + '. Pulled ' + esc(review['retrieved_at']) + '.</p>')
    parts.append('<p>Proposed experimental policy: 30 mature clicks + 3 purchases (30d), or 50 clicks + 5 purchases (90d). Zero-order samples may support reductions only. Maximum change 25 percentage points, positive modifier cap 100%, 5-point rounding. Separate approval required.</p>')
    rows = sorted(review.get('rows', []), key=lambda row: (row['status'] != 'recommend', not row['sufficient'], row['campaign'], row['placement']))
    parts.append('<div style="overflow:auto"><table><thead><tr>' + ''.join('<th>' + heading + '</th>' for heading in ['Campaign / ID', 'Placement', 'Decision', 'Current → proposed', 'Sample / CVR', 'CPC / breakeven CPC', 'Reason']) + '</tr></thead><tbody>')
    for row in rows:
        cells = [esc(row['campaign']) + '<br><small>' + esc(row.get('campaign_id') or 'New campaign') + '</small>', esc(row['label']), esc(row['status'].title()),
                 esc(modifier(row['current']) + ' → ' + modifier(row['proposed'])),
                 esc(f"{row.get('purchases', 0):g} purchases / {row.get('clicks', 0):g} clicks; " + pct(row.get('cvr')) + '; ' + row.get('window', 'no history')),
                 esc(money(row.get('cpc')) + ' / ' + money(row.get('breakeven_cpc'))), esc(row['reason'])]
        parts.append('<tr>' + ''.join('<td>' + cell + '</td>' for cell in cells) + '</tr>')
    return ''.join(parts) + '</tbody></table></div></section>'
