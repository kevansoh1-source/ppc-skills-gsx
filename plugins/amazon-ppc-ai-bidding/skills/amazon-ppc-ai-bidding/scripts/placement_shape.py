"""The product-page base bid (Kim, 2026-10-26, decision 140: "let's try this to build 1 and 2 as you suggest").

A keyword has one bid for every placement, priced on its blended conversion, so it overpays on product pages (Oct 18-24
2026, US: product pages converted 8.4% against 15.1% at the top of search and ran at 91% ACOS) and Amazon only lets a
placement go up, never down. So, campaign by campaign, the placement that converts best keeps the keyword's bid as the
plan priced it, each other placement bids in proportion to its own conversion against that best one (never under
`min_share` of it), and the base bid drops to the lowest placement's share while the modifiers raise the others back up.
A rank campaign's top of search keeps its full standing-policy bid (+50% Invest, +30% Prove first). No placement bids
more than the plan priced it: every bid and modifier is rounded down.

It runs after the lanes (plan.main), and shapes a campaign only when all of this holds, else it says why in
summary.placement_shape:
- the product's Auto lane is on (not a shadow run), its data fresh, and the live keywords and targets were read;
- placement_inputs.json is complete, this product's, and at most `max_snapshot_age_days` old (placements.md);
- the campaign is a live Sponsored Products campaign this product has alone (its live product ads), not global, not an
  audience copy, not Amazon Business, not the harvest campaign, with no placement experiment in its name, on down-only,
  up-and-down or fixed bidding, outside the ownership scope's exclusions, and not part of a live experiment
  (`experiment_files`, `experiment_name_markers`: the overnight test's originals and its ON80 copies);
- the plan writes nothing else to the campaign itself this run (budget, top of search, a new or reused exact campaign);
- every row of the campaign is in the Auto lane or held by the planner this run (Monitor, no person's decision): a held
  row writes nothing, so its keyword or target is shaped from its live bid; every serving keyword and target has a bid the
  plan knows (none on its ad group's default bid, none kept at its live bid by a review or a skip marker);
- the campaign has `min_campaign_clicks` and `min_campaign_orders` in the placement window, and some placement converts
  at most 1 - `min_cut` of the best one.

Each serving bid of a shaped campaign is written at its shaped base (`shape_base`, which plan.as_written writes): a bid row
the plan already has gains it, and a keyword or target whose bid the plan keeps gains a bid row of its own, in the Auto
lane. The campaign gets one 'Placement shape' row (payload 9c_placement_shape.json, applied after every bid file, MAP's optimizations shape at down-only
bidding: every live placement sent, the three it shapes at their new modifiers). An Auto 'Bidding strategy' row of the
same campaign is folded into it, since the shape writes down-only bidding too.
"""
import datetime as dt
import json
import math
import os

import ownership_scope
import plan_lanes
import placement_review
from placement_review import ALIASES, EXPERIMENT_MARKER, PLACEMENTS, rank_tos, settings

SHAPE_TYPE = 'Placement shape'
STRATEGY_TYPE = placement_review.STRATEGY_TYPE
# rows that change a campaign itself: a campaign with one of them this run is shaped on a later run, once it is settled
CAMPAIGN_ROWS = ('Budget and top of search', 'Budget step', 'Reuse exact campaign', 'New exact campaign', 'Business invest',
                 'New exact keyword')
STRATEGIES = ('SALES_DOWN_ONLY', 'SALES_UP_AND_DOWN', 'MANUAL')
PAUSED_KEEP = 'Keep: its campaign, ad group or keyword is paused'
API_PLACEMENT = {'TOP_OF_SEARCH': 'TOP_OF_SEARCH', 'REST_OF_SEARCH': 'REST_OF_SEARCH', 'PRODUCT_PAGE': 'PRODUCT_PAGE'}


# the repo's root (scripts -> skill -> skills -> .claude -> repo): experiment files are named from it in config.json
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
ID_KEYS = ('campaign_id', 'campaignId', 'source_campaign_id', 'source')


def experiment_campaigns(paths, root=ROOT):
    """(campaign ids, missing files) of the live experiments config.json's placement.shape.experiment_files names: every
    string or number under a campaign id key (campaign_id, campaignId, source_campaign_id, source) anywhere in each file,
    so both an experiment's original campaigns and its copies are found."""
    found, missing = set(), []
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ID_KEYS and isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).isdigit():
                    found.add(str(value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    for path in paths or []:
        full = path if os.path.isabs(path) else os.path.join(root, path)
        if not os.path.exists(full):
            missing.append(path)
            continue
        with open(full, encoding='utf-8') as f:
            walk(json.load(f))
    return found, missing


def floor_cents(value):
    return math.floor(value * 100 + 1e-9) / 100


def placement_cvr(rows, cid, window, prior):
    """({placement: shrunk conversion}, pooled conversion, clicks, orders) of one campaign in `window` ('90d' or '30d'):
    each placement's own orders and clicks shrunk toward the campaign's pooled conversion by `prior` clicks."""
    suffix = window[:-1]
    got = {p: rows.get((cid, p), {}) for p in PLACEMENTS}
    clicks = sum(r.get('clicks' + suffix, 0) for r in got.values())
    orders = sum(r.get('orders' + suffix, 0) for r in got.values())
    pooled = orders / clicks if clicks else 0
    cvr = {p: (r.get('orders' + suffix, 0) + prior * pooled) / (r.get('clicks' + suffix, 0) + prior) for p, r in got.items()}
    return cvr, pooled, clicks, orders


def factors(cvr, rank_tos_pct, min_share):
    """(base share s, {placement: modifier %}, {placement: share of the plan's bid}) for one campaign. The placement that
    converts best keeps the plan's bid (share 1); each other one bids its conversion against the best, never under
    min_share; a rank campaign's top of search keeps 1 + its policy. The base is the lowest share, and each modifier the
    whole percent, rounded down, that brings the base back to that placement's share."""
    best = max(cvr.values())
    share = {p: max(min_share, min(1.0, v / best)) if best > 0 else 1.0 for p, v in cvr.items()}
    target = dict(share)
    if rank_tos_pct is not None:
        target['TOP_OF_SEARCH'] = 1 + rank_tos_pct / 100
    s = min(target.values())
    modifiers = {p: max(0, min(900, math.floor((t / s - 1) * 100 + 1e-9))) for p, t in target.items()}
    return s, modifiers, target


def _row_lane(row):
    return row.get('lane') == 'auto' and not row.get('locked_until') and not row.get('ownership_scope_blocked')


def _held(row):
    """A row the planner holds this run (Monitor: a raise past the run's 20, a pause waiting for its new owner to serve)
    that no person's decision or ownership boundary holds. Nothing of it is written, so its keyword or target serves at
    its live bid this run, and the shape prices it there (2026-10-26: the first rollout plan, B0SAMP0014, held a row in
    every campaign, so no campaign was shaped)."""
    return row.get('lane') == 'monitor' and not row.get('locked_until') and not row.get('ownership_scope_blocked')


def _new_row_id(row, used):
    rid = name = plan_lanes.row_id(row)
    n = 1
    while name in used:
        n += 1
        name = f'{rid}:{n}'
    used.add(name)
    return name


def apply(out, cfg, shared, snapshot, today):
    """Shape the campaigns of a laned plan (module docstring). Changes out['changes'] in place and sets
    summary[0]['placement_shape']: {status, window, shaped: [...], skipped: [{campaign_id, campaign, why}]}."""
    plc = shared.get('placement') or {}
    conf = plc.get('shape') or {}
    s0 = out['summary'][0]
    result = dict(status='off', shaped=[], skipped=[])
    s0['placement_shape'] = result
    if not conf.get('enabled'):
        return result
    reasons = []
    if s0.get('shadow') is not False:
        reasons.append("the product's Auto lane is off (a shadow run)")
    if s0.get('stale_reason'):
        reasons.append(f"the product's data is not fresh ({s0['stale_reason']})")
    if (s0.get('inventory') or {}).get('partial_reason'):
        reasons.append('the live keywords and targets were not read (--partial-inventory)')
    experiments, missing = experiment_campaigns(conf.get('experiment_files'))
    if missing:
        reasons.append('an experiment file named in config.json is missing (' + ', '.join(missing) + ')')
    if snapshot is None:
        reasons.append('no placement_inputs.json in the run folder')
    else:
        policy = plc.get('recommendations') or {}
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(snapshot['as_of'])).days
        if not 0 <= age <= policy.get('max_snapshot_age_days', 2):
            reasons.append(f"placement_inputs.json is {age} days old")
    if reasons:
        result.update(status='not shaped: ' + '; '.join(reasons))
        return result
    window = conf.get('window', '90d')
    prior = float(conf.get('prior_clicks', 30))
    min_share = float(conf.get('min_share', 0.5))
    min_cut = float(conf.get('min_cut', 0.1))
    min_base = float(conf.get('min_base_bid', 0.02))
    asin = cfg['asin']
    markers = [m.lower() for m in shared.get('audience_campaign_markers') or []]
    b2b = [m.lower() for m in shared.get('b2b_campaign_markers') or []]
    harvest_cid = str(((cfg.get('harvest') or {}).get('campaign_id')) or '')
    rows = {(str(r['campaignId']), ALIASES.get(r['placement'], r['placement'])): r for r in snapshot['rows']}
    live_asins = snapshot.get('live_asins') or {}
    changes = out['changes']
    by_campaign = {}
    for x in changes:
        if x.get('campaign_id'):
            by_campaign.setdefault(str(x['campaign_id']), []).append(x)
    kw_plan = {}
    for p in out.get('keyword_plan') or []:
        kw_plan.setdefault(str(p.get('campaign_id')), []).append(p)
    t_plan = {}
    for t in out.get('target_plan') or []:
        if t.get('ad_product') == 'SP':
            t_plan.setdefault(str(t.get('campaign_id')), []).append(t)
    used = {x.get('row_id') for x in changes}
    added, dropped = [], set()

    for c in snapshot['campaigns']:
        cid = str(c.get('campaignId'))
        name = c.get('name') or ''
        if (c.get('state') or '').upper() != 'ENABLED':
            continue
        cvr, pooled, clicks, orders = placement_cvr(rows, cid, window, prior)
        if clicks < conf.get('min_campaign_clicks', 50) or orders < conf.get('min_campaign_orders', 5):
            continue   # not enough placement data: nothing to shape, and nothing worth reporting

        def skip(why):
            result['skipped'].append(dict(campaign_id=cid, campaign=name, why=why))

        current, bid = settings(c)
        low = name.lower()
        if current is None:
            skip('its live placement settings were not read')
            continue
        if c.get('globalCampaignId'):
            skip('a global campaign: its bid settings cannot be changed through the API')
            continue
        if bid.get('bidStrategy') not in STRATEGIES:
            skip(f"its bidding strategy is {bid.get('bidStrategy')}")
            continue
        if any(m in low for m in markers) or (bid.get('bidAdjustments') or {}).get('audienceBidAdjustments'):
            skip('an audience (AMC, low-bid) campaign: people own these (decision 107)')
            continue
        if any(m in low for m in b2b) or 'AMAZON_BUSINESS' in str(c.get('siteRestrictions') or ''):
            skip('an Amazon Business campaign')
            continue
        if EXPERIMENT_MARKER.search(name):
            skip('its name carries a placement experiment')
            continue
        if cid in experiments or any(m.lower() in low for m in conf.get('experiment_name_markers') or []):
            skip('part of a live experiment (the overnight test): its bid settings stay as the experiment set them')
            continue
        if harvest_cid and cid == harvest_cid:
            skip("the harvest campaign: Scale Insights adds keywords to it at the ad group's default bid")
            continue
        if set(live_asins.get(cid) or []) != {asin}:
            skip('not shown to advertise this product alone')
            continue
        if ownership_scope.reason(dict(type=SHAPE_TYPE, campaign_id=cid), cfg):
            skip("outside the product's ownership scope")
            continue
        mine = [x for x in by_campaign.get(cid, []) if x.get('type') != STRATEGY_TYPE]
        if any(x.get('type') in CAMPAIGN_ROWS for x in mine):
            skip('the plan changes the campaign itself this run (budget, top of search or a new keyword): shaped once settled')
            continue
        if not all(_row_lane(x) or _held(x) for x in mine):
            skip("a row of the campaign waits for a person, or a person's decision holds it")
            continue
        held = {str(x.get('keyword_id') or x.get('target_id')): x for x in mine if _held(x)
                and x.get('type') in ('Bid change', 'Target bid change', 'Pause keyword', 'Pause target')}
        strategy_row = next((x for x in by_campaign.get(cid, []) if x.get('type') == STRATEGY_TYPE), None)
        if strategy_row is not None and not _row_lane(strategy_row):
            skip('its move to down-only bidding waits for a person')
            continue
        # every serving bid of the campaign, with the bid the plan writes for it. A held row writes nothing: its keyword or
        # target keeps serving at its live bid (a held pause too), so that is the bid the shape starts from
        bid_rows = {(x['type'], str(x.get('keyword_id') or x.get('target_id'))): x for x in mine
                    if _row_lane(x) and x.get('type') in ('Bid change', 'Target bid change')}
        paused = {str(x.get('keyword_id') or x.get('target_id')) for x in mine
                  if _row_lane(x) and x.get('type') in ('Pause keyword', 'Pause target')}
        serving, problem = [], None
        rank_roles = set()
        for p in kw_plan.get(cid, []):
            kid = str(p.get('keyword_id'))
            action = p.get('action') or ''
            if action.startswith(PAUSED_KEEP) or kid in paused:
                continue
            if action.startswith('Keep'):
                problem = f"keyword \"{p.get('keyword')}\" keeps its live bid this run ({action})"
                break
            if p.get('role') == 'Rank' and action.startswith(('Invest', 'Prove')):
                rank_roles.add(p.get('sub_role'))
            row = bid_rows.get(('Bid change', kid))
            planned = plan_written(row) if row else p.get('bid')
            if not planned:
                problem = f"keyword \"{p.get('keyword')}\" has no bid of its own (its ad group's default bid)"
                break
            serving.append(('keyword', p, row, planned))
        for t in t_plan.get(cid, []) if problem is None else []:
            tid = str(t.get('target_id'))
            if t['status'] == 'paused' or tid in paused:
                continue
            if t['status'] in ('skipped', 'no bid of its own'):
                problem = f"a product target is {'left out of pricing' if t['status'] == 'skipped' else 'on its ad group default bid'}"
                break
            row = bid_rows.get(('Target bid change', tid))
            planned = plan_written(row) if row else t.get('bid')
            if not planned:
                problem = 'a product target has no bid of its own'
                break
            serving.append(('target', t, row, planned))
        if problem or not serving:
            skip(problem or 'no serving keyword or target')
            continue
        tos_policy = None
        if rank_roles:
            policies = [rank_tos(plc, r) for r in rank_roles]
            if any(v is None for v in policies):
                skip("a rank campaign, and the standing top-of-search policy is off")
                continue
            tos_policy = max(policies)
        share, modifiers, target = factors(cvr, tos_policy, min_share)
        if min(v for p, v in target.items() if not (tos_policy is not None and p == 'TOP_OF_SEARCH')) > 1 - min_cut:
            skip(f'its placements convert within {min_cut:.0%} of each other')
            continue
        bases = [(kind, rec, row, planned, floor_cents(planned * share)) for kind, rec, row, planned in serving]
        if any(base < min_base for *_, base in bases):
            skip(f"a shaped bid would fall under Amazon's ${min_base:.2f} minimum")
            continue
        # the shape: the live placements, the three shaped ones at their new modifiers, any other (Amazon Business) as read
        live_list = (bid.get('bidAdjustments') or {}).get('placementBidAdjustments') or []
        out_list = [dict(placement=API_PLACEMENT[p], percentage=int(modifiers[p])) for p in PLACEMENTS]
        out_list += [dict(r) for r in live_list if ALIASES.get(r.get('placement'), r.get('placement')) not in PLACEMENTS]
        words = ', '.join(f"{PLACEMENTS[p].lower()} {cvr[p]:.1%} ({target[p]:.0%} of the bid)" for p in PLACEMENTS)
        why = (f"Product-page base bid (decision 140): {window} placement conversion {words}; campaign {pooled:.1%} on "
               f"{int(clicks)} clicks, each placement shrunk toward it by {prior:g} clicks. The base bid drops to {share:.0%} "
               'of each keyword\'s price and the modifiers raise the better placements back, so no placement bids more '
               'than the plan priced it' + (f" (top of search keeps the rank policy, +{tos_policy:g}%)" if tos_policy is not None else '')
               + '.')
        if strategy_row is not None:
            why += ' It also moves the campaign from up-and-down to down-only bidding.'
            dropped.add(id(strategy_row))
        shape_row = dict(step=6, type=SHAPE_TYPE, campaign=name, campaign_id=cid, item='Product-page base bid',
                         current=None, new=None, modifiers_now=dict(current), modifiers=modifiers, base_share=round(share, 4),
                         placement_cvr={p: round(v, 4) for p, v in cvr.items()}, campaign_cvr=round(pooled, 4),
                         clicks_window=int(clicks), orders_window=int(orders), window=window, rank_tos=tos_policy,
                         strategy_now=bid.get('bidStrategy'), bid_adjustments=dict(placementBidAdjustments=out_list),
                         bids=len(bases), why=why,
                         how=('MAP update sp_campaigns: optimizations.bidSettings at SALES_DOWN_ONLY with every placement '
                              '(9c_placement_shape.json), only once every shaped bid of the campaign (4_bids, 9_target_bids) '
                              'is written and read back (map-playbook.md, "Product-page base bid")'),
                         lane='auto', lane_unlocked='auto', confidence=None, confidence_text=None, opportunity=None,
                         lane_reason=("the product-page base bid: no placement bids more than the plan priced it (decision "
                                      '140; every bid of the campaign applies on its own this run)'))
        shape_row['row_id'] = _new_row_id(shape_row, used)
        added.append(shape_row)
        for kind, rec, row, planned, base in bases:
            note = (f" Written at a ${base:.2f} base ({share:.0%}, the campaign's product-page base bid, decision 140); "
                    f"its best placement still bids ${planned:.2f}.")
            waiting = held.get(str(rec.get('keyword_id') if kind == 'keyword' else rec.get('target_id')))
            if row is not None:
                row['shape_base'] = base
                row['shape_share'] = round(share, 4)
                row['shape_row_id'] = shape_row['row_id']
                row['why'] = (row.get('why') or '') + note
                continue
            new = dict(step=5, type='Bid change' if kind == 'keyword' else 'Target bid change',
                       campaign=name, campaign_id=cid, ad_group_id=str(rec.get('ad_group_id')),
                       current=round(planned, 2), new=round(planned, 2), change=0.0, shape_base=base,
                       shape_share=round(share, 4), shape_row_id=shape_row['row_id'], shape_only=True,
                       lane='auto', lane_unlocked='auto', confidence=None, confidence_text=None, opportunity=None,
                       lane_reason='the product-page base bid only: its price is unchanged (decision 140)',
                       how=f"MAP update {'sp_keywords' if kind == 'keyword' else 'sp_targets'}: bid")
            if kind == 'keyword':
                new.update(keyword=rec.get('keyword'), keyword_id=str(rec.get('keyword_id')), match=rec.get('match'),
                           family=rec.get('family'), role=rec.get('sub_role') or rec.get('role'),
                           why='Price unchanged.' + note)
            else:
                new.update(keyword=rec.get('target_id'), target_id=str(rec.get('target_id')), match='target',
                           role='Shape', why='Price unchanged.' + note)
            if waiting is not None:
                new.update(held_row_id=waiting.get('row_id'),
                           why=(f"Its planned change ({waiting['type'].lower()}) is held this run "
                                f"({waiting.get('lane_reason') or waiting.get('reason') or 'Monitor'}), so it keeps its live "
                                f"${planned:.2f}." + note))
            new['row_id'] = _new_row_id(new, used)
            added.append(new)
        result['shaped'].append(dict(campaign_id=cid, campaign=name, base_share=round(share, 4), modifiers=modifiers,
                                     modifiers_now=dict(current), strategy_now=bid.get('bidStrategy'), rank_tos=tos_policy,
                                     bids=len(bases), shape_only=sum(1 for _, _, row, _, _ in bases if row is None),
                                     placement_cvr={p: round(v, 4) for p, v in cvr.items()}))
    if dropped:
        changes[:] = [x for x in changes if id(x) not in dropped]
    changes.extend(added)
    lanes_count = s0.get('lanes')
    if isinstance(lanes_count, dict):
        lanes_count['auto'] = lanes_count.get('auto', 0) + len(added) - len(dropped)
    result.update(status='ok', window=window)
    return result


def plan_written(row):
    """The bid a laned row writes before any shaping: its cap where the auto lane capped it, else its new bid."""
    capped = row.get('new_capped')
    return row.get('new') if capped is None else capped
