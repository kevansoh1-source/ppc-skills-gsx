"""The coverage ledger (Kim, 2026-10-27, decision 155: "every single campaign and every single keyword falls under the
purview of the skill as it runs its process").

After the plan, every live entity of the product is given one status: the rule that owns it this run. The entities are the
product's Sponsored Products campaigns (their top of search and bidding strategy), keywords, targets and ad groups, its
Sponsored Brands campaigns, keywords, targets and theme targets, and its Sponsored Display campaigns and targets, as the run's
live reads hold them (references/data-pull.md). Since decision 156 (Kim, 2026-10-27, "don't leave any out") a campaign is
the product's when its ads say so (ad_campaigns_p*.json), not only when its name carries the ASIN. A status says who owns it:

  changed            a row of this plan writes it
  priced             priced by its role and left as it is (already at or under its price, or never raised)
  rank               a rank campaign: its top of search is the invest policy's (rulebook 7.5)
  policy             the placement policy sets its top of search this run
  boost_kept         its top-of-search boost can't come off this run, so its bids are priced for it
  at_policy          its top of search is already at the policy
  experiment         a placement experiment named in config placement.shape, left as it is
  ad_group_default   it bids its ad group's default, which the plan prices (or, not read, see reads_missing)
  paused_kept        paused, and the config leaves paused rows as they are (inventory.paused, targets.paused, sb_video.paused)
  si_owned           a whole shared campaign the product file's ownership_scope gives to Scale Insights (decisions 109, 111)
  multi_asin         a campaign advertising several ASINs (product collection, cross-selling): left out on purpose and
                     listed (Kim, 2026-10-27, decision 156)
  vcpm               a Sponsored Display campaign (or its target) bidding per thousand impressions: never priced like a
                     click, listed for a person
  down_only          its bidding strategy is already down only (or fixed bids)
  harvest            the harvest ad group: its starting bid is the harvest's (rulebook section 5)
  unowned            read, live, and no rule handled it: the run stops (coverage.stop_on_unowned) unless --accept-unowned

reads_missing names the live reads the run didn't have (live_ad_groups, sb_targets, sb_themes, ad_campaigns, ...): the
entities they hold are not in the ledger. With coverage.stop_on_missing_reads (decision 156) a missing read stops the run
like an unowned entity, since what it holds would be left out unseen.

"priced" is checked: an SB keyword, target or theme, or an ad group, counts as priced only when the planner priced it this
run (the plan's _priced ids); one it never reached is unowned.
"""
from collections import Counter

LIVE = ('ENABLED', 'PAUSED')


def _state(x):
    return (x.get('state') or '').upper()


def _id(x, *keys):
    for k in keys:
        if x.get(k) not in (None, ''):
            return str(x[k])
    return None


def ledger(out, cfg, shared, asin, read):
    """{'entities': [{kind, id, campaign_id, status, why}], 'reads_missing': [...]}. read(prefix) returns the saved
    list_resources rows of the run files with that prefix, or None when the run has no such file."""
    items = lambda prefix: read(prefix) or []
    s = out['summary'][0]
    inv_cfg, tcfg, sbc = shared.get('inventory') or {}, shared.get('targets') or {}, shared.get('sb_video') or {}
    scope = cfg.get('ownership_scope') or {}
    si_camps = {str(x) for x in scope.get('excluded_campaign_ids') or []}
    si_groups = {str(x) for x in scope.get('excluded_ad_group_ids') or []}
    shared_ids = ({str(x.get('campaign_id') if isinstance(x, dict) else x) for x in cfg.get('shared_campaigns') or []}
                  if inv_cfg.get('shared_campaigns') else set())
    scope = s.get('campaign_scope') or {}
    multi = {str(m['id']): m for m in scope.get('multi') or []}
    own = {str(m['id']) for m in scope.get('own') or []}
    camps = [c for c in items('campaigns') if asin in (c.get('name') or '') and str(c.get('campaignId')) not in multi]
    camps += [c for c in items('own_campaigns') if str(c.get('campaignId')) in own and str(c.get('campaignId')) not in multi]
    camps += [c for c in items('shared_campaigns') if str(c.get('campaignId')) in shared_ids]
    camp_by = {str(c.get('campaignId')): c for c in camps}
    priced_ids = out.get('_priced')    # None for a plan built before decision 156: "priced" is then taken as read
    sb_priced = None if priced_ids is None else set(priced_ids.get('sb') or [])
    ag_priced = None if priced_ids is None else set(priced_ids.get('ad_groups') or [])
    changes = out.get('changes') or []
    changed = {str(x.get('keyword_id') or x.get('target_id') or x.get('theme_id')) for x in changes
               if x.get('keyword_id') or x.get('target_id') or x.get('theme_id')}
    changed_groups = {str(x.get('ad_group_id')) for x in changes if x['type'] in ('Ad group default bid', 'Harvest default bid')}
    changed_camps = {str(x.get('campaign_id')) for x in changes if x.get('campaign_id')}
    planned_kw = {str(p.get('keyword_id')) for p in out.get('keyword_plan') or []}
    planned_t = {str(r.get('target_id')): r for r in out.get('target_plan') or []}
    pol = s.get('placement_policy') or {}
    hv_ag = str((cfg.get('harvest') or {}).get('ad_group_id') or '')
    entities, missing = [], []
    strategy_rows = {str(x.get('campaign_id')) for x in changes if x['type'] == 'Bidding strategy'}

    def add(kind, eid, cid, status, why=''):
        entities.append(dict(kind=kind, id=eid, campaign_id=cid, status=status, **({'why': why} if why else {})))

    def owned_by_scope(cid, ag=None):
        return cid in si_camps or (ag is not None and ag in si_groups)

    # Sponsored Products campaigns: their top of search and bidding strategy (the placement policy, decision 155)
    tos_target = float(((shared.get('placement') or {}).get('policy') or {}).get('non_rank_tos_pct') or 0)
    for cid, c in sorted(camp_by.items()):
        if _state(c) not in LIVE:
            continue
        if owned_by_scope(cid):
            add('sp_campaign', cid, cid, 'si_owned')
        elif cid in set(pol.get('rank') or []):
            add('sp_campaign', cid, cid, 'rank')
        elif cid in set(pol.get('set') or []):
            add('sp_campaign', cid, cid, 'policy')
        elif cid in (pol.get('kept_boost') or {}):
            add('sp_campaign', cid, cid, 'boost_kept')
        elif cid in set(pol.get('experiments') or []):
            add('sp_campaign', cid, cid, 'experiment')
        else:
            top = _top_of_search(c)
            if top is None or top <= tos_target or not pol.get('enabled'):
                add('sp_campaign', cid, cid, 'at_policy' if pol.get('enabled') else 'priced',
                    '' if pol.get('enabled') else 'placement policy off')
            else:
                add('sp_campaign', cid, cid, 'unowned', f'top of search +{top:g}% and no rule set it')
        # its bidding strategy (decision 140, audience_auto since 155): up and down lets Amazon raise every bid by up to 100%
        if owned_by_scope(cid):
            continue
        strategy = ((c.get('optimizations') or {}).get('bidSettings') or {}).get('bidStrategy')
        if strategy is None:
            continue
        if strategy != 'SALES_UP_AND_DOWN':
            add('sp_bidding_strategy', cid, cid, 'down_only')
        elif cid in strategy_rows:
            add('sp_bidding_strategy', cid, cid, 'changed')
        elif _state(c) == 'PAUSED':
            add('sp_bidding_strategy', cid, cid, 'paused_kept', 'paused: moved to down only when it is turned back on')
        elif c.get('globalCampaignId'):
            add('sp_bidding_strategy', cid, cid, 'unowned', "a global campaign's bidding strategy can't be changed through the API")
        else:
            add('sp_bidding_strategy', cid, cid, 'unowned', 'up-and-down bidding and no row moves it to down only')

    # multi-ASIN campaigns (product collection and cross-selling, decision 156): left out on purpose, listed by name
    for cid, m in sorted(multi.items()):
        add(f"{(m.get('ad_type') or 'SP').lower()}_campaign", cid, cid, 'multi_asin',
            f"{m.get('name')}: advertises {len(m.get('asins') or [])} ASINs ({', '.join(m.get('asins') or [])}), left out on purpose")
    for m in scope.get('sb_multi') or []:
        add('sb_campaign', str(m['id']), str(m['id']), 'multi_asin', f"{m.get('name')}: a product collection or store spotlight ad")
    if inv_cfg.get('ad_campaigns') and not scope.get('read'):
        missing.append('ad_campaigns')

    # Sponsored Products keywords
    kws = items('live_keywords')
    if read('live_keywords') is None:
        missing.append('live_keywords')
    groups_read = read('live_ad_groups') is not None
    for k in kws:
        kid, cid, ag = _id(k, 'keywordId'), str(k.get('campaignId')), str(k.get('adGroupId'))
        c = camp_by.get(cid)
        if not c or _state(k) not in LIVE or _state(c) not in LIVE:
            continue   # another product's campaign, or archived
        paused = 'PAUSED' in (_state(k), _state(c))
        if owned_by_scope(cid, ag):
            add('sp_keyword', kid, cid, 'si_owned')
        elif kid in changed:
            add('sp_keyword', kid, cid, 'changed')
        elif k.get('bid') in (None, ''):
            add('sp_keyword', kid, cid, 'ad_group_default', '' if groups_read else 'live_ad_groups not read')
        elif kid in planned_kw:
            add('sp_keyword', kid, cid, 'priced')
        elif paused and not inv_cfg.get('paused'):
            add('sp_keyword', kid, cid, 'paused_kept')
        else:
            add('sp_keyword', kid, cid, 'unowned', 'live keyword the plan never priced')

    # Sponsored Products targets
    tgts = items('live_targets')
    if read('live_targets') is None:
        missing.append('live_targets')
    for t in tgts:
        tid, cid, ag = _id(t, 'targetId'), str(t.get('campaignId')), str(t.get('adGroupId'))
        c = camp_by.get(cid)
        if not c or _state(t) not in LIVE or _state(c) not in LIVE:
            continue
        rec = planned_t.get(tid)
        if owned_by_scope(cid, ag):
            add('sp_target', tid, cid, 'si_owned')
        elif tid in changed:
            add('sp_target', tid, cid, 'changed')
        elif t.get('bid') in (None, ''):
            add('sp_target', tid, cid, 'ad_group_default', '' if groups_read else 'live_ad_groups not read')
        elif rec and rec.get('status') == 'paused':
            add('sp_target', tid, cid, 'paused_kept')
        elif rec and rec.get('status') in ('kept', 'priced', None) and 'new' in rec:
            add('sp_target', tid, cid, 'priced')
        elif rec is None and not tcfg.get('enabled', True):
            add('sp_target', tid, cid, 'unowned', 'targets are switched off in config')
        else:
            add('sp_target', tid, cid, 'unowned', f"target the plan never priced ({(rec or {}).get('status') or 'not in the plan'})")

    # Sponsored Products ad groups: their default bids (decision 155, inventory.ad_group_default_bids)
    if inv_cfg.get('ad_group_default_bids'):
        if not groups_read:
            missing.append('live_ad_groups')
        for g in items('live_ad_groups'):
            agid, cid = str(g.get('adGroupId')), str(g.get('campaignId'))
            c = camp_by.get(cid)
            if not c or _state(g) not in LIVE or _state(c) not in LIVE:
                continue
            if owned_by_scope(cid, agid):
                add('sp_ad_group', agid, cid, 'si_owned')
            elif agid == hv_ag:
                add('sp_ad_group', agid, cid, 'harvest')
            elif agid in changed_groups:
                add('sp_ad_group', agid, cid, 'changed')
            elif cid in set(pol.get('rank') or []):
                add('sp_ad_group', agid, cid, 'rank')
            elif cid in set(pol.get('experiments') or []):
                add('sp_ad_group', agid, cid, 'experiment')
            elif ag_priced is not None and agid not in ag_priced and g.get('defaultBid') not in (None, ''):
                add('sp_ad_group', agid, cid, 'unowned', 'its default bid was never priced')
            else:
                add('sp_ad_group', agid, cid, 'priced')

    # Sponsored Brands: campaigns (Amazon's bid optimisation), keywords and targets
    sb_multi = {str(m['id']) for m in scope.get('sb_multi') or []}
    sb_camps = {str(c.get('campaignId')): c for c in items('sb_campaigns') if asin in (c.get('name') or '')
                and str(c.get('campaignId')) not in sb_multi}
    if read('sb_campaigns') is not None:
        ai_ids = {str(x) for x in (cfg.get('sb_video') or {}).get('campaigns') or []}
        for cid, c in sorted(sb_camps.items()):
            if _state(c) not in LIVE:
                continue
            on = bool((c.get('bidding') or {}).get('bidOptimization'))
            if cid in ai_ids or not on:
                add('sb_campaign', cid, cid, 'priced')
            elif cid in changed_camps:
                add('sb_campaign', cid, cid, 'changed')
            else:
                add('sb_campaign', cid, cid, 'unowned', "Amazon's bid optimisation is on and no rule switched it off")
        for kind, prefix, key in (('sb_keyword', 'sb_keywords', 'keywordId'), ('sb_target', 'sb_targets', 'targetId'),
                                  ('sb_theme', 'sb_themes', 'themeId')):
            rows = items(prefix)
            if read(prefix) is None:
                if kind == 'sb_keyword' or sbc.get({'sb_target': 'targets', 'sb_theme': 'themes'}.get(kind, '')):
                    if sb_camps:
                        missing.append(prefix)
                continue
            for k in rows:
                eid, cid = _id(k, key), str(k.get('campaignId'))
                c = sb_camps.get(cid)
                if not c or _state(k) not in LIVE or _state(c) not in LIVE:
                    continue
                paused = 'PAUSED' in (_state(k), _state(c))
                if eid in changed:
                    add(kind, eid, cid, 'changed')
                elif paused and not sbc.get('paused'):
                    add(kind, eid, cid, 'paused_kept')
                elif kind == 'sb_target' and not sbc.get('targets'):
                    add(kind, eid, cid, 'unowned', 'Sponsored Brands targets are switched off in config')
                elif kind == 'sb_theme' and not sbc.get('themes'):
                    add(kind, eid, cid, 'unowned', 'Sponsored Brands theme targets are switched off in config')
                elif sb_priced is not None and eid not in sb_priced:
                    add(kind, eid, cid, 'unowned', 'live and the planner never priced it')
                else:
                    add(kind, eid, cid, 'priced')
    else:
        missing.append('sb_campaigns')
    # Sponsored Display (decision 156): the product's SD campaigns and targets. A CPC target is priced like a Sponsored
    # Products one (plan.py, product targets); a vCPM campaign bids per thousand impressions and is listed for a person
    if tcfg.get('sd') and tcfg.get('enabled', True):
        sd_plan = {str(r['target_id']): r for r in out.get('target_plan') or [] if r.get('ad_product') == 'SD'}
        sd_ids = {str(r['campaign_id']) for r in sd_plan.values()} | {str(x) for x in scope.get('sd') or []}
        sd_c = {str(c.get('campaignId')): c for c in items('sd_campaigns') if str(c.get('campaignId')) in sd_ids}
        vcpm = {cid for cid, c in sd_c.items() if (c.get('costType') or 'cpc').lower() in
                {x.lower() for x in tcfg.get('sd_skip_cost_types') or ('vcpm',)}}
        for cid in sorted(sd_ids):
            c = sd_c.get(cid)
            if c is None:
                add('sd_campaign', cid, cid, 'unowned', 'its live record was not read (sd_campaigns)')
            elif (c.get('state') or '').lower() not in ('enabled', 'paused'):
                continue
            elif owned_by_scope(cid):
                add('sd_campaign', cid, cid, 'si_owned')
            elif cid in vcpm:
                add('sd_campaign', cid, cid, 'vcpm', 'bids per thousand impressions: never priced like a click, a person decides')
            else:
                add('sd_campaign', cid, cid, 'priced')
        live_sd = {str(t.get('targetId')): t for t in items('live_sd_targets')}
        if scope.get('sd') and read('live_sd_targets') is None:
            missing.append('live_sd_targets')
        for tid in sorted(set(sd_plan) | {k for k, t in live_sd.items() if str(t.get('campaignId')) in sd_ids}):
            r, t = sd_plan.get(tid), live_sd.get(tid) or {}
            cid = str((r or {}).get('campaign_id') or t.get('campaignId'))
            if r is None and (t.get('state') or '').lower() not in ('enabled', 'paused'):
                continue
            if owned_by_scope(cid):
                add('sd_target', tid, cid, 'si_owned')
            elif tid in changed:
                add('sd_target', tid, cid, 'changed')
            elif cid in vcpm:
                add('sd_target', tid, cid, 'vcpm')
            elif r and r.get('status') == 'paused':
                add('sd_target', tid, cid, 'paused_kept')
            elif r and r.get('status') in ('kept', 'priced'):
                add('sd_target', tid, cid, 'priced')
            elif (sd_c.get(cid) or {}).get('state', '').lower() == 'paused':
                add('sd_target', tid, cid, 'paused_kept', 'its campaign is paused')
            else:
                add('sd_target', tid, cid, 'unowned', f"live SD target the plan never priced ({(r or {}).get('status') or 'not in the plan'})")
    if inv_cfg.get('shared_campaigns') and shared_ids and read('shared_campaigns') is None:
        missing.append('shared_campaigns')
    return dict(entities=entities, reads_missing=missing)


def _top_of_search(c):
    """A campaign's live top-of-search percentage from its MAP record (either shape MAP returns), or None."""
    bs = (c.get('optimizations') or {}).get('bidSettings') or {}
    adj = (bs.get('bidAdjustments') or {}).get('placementBidAdjustments') or []
    adj = adj or ((c.get('dynamicBidding') or {}).get('placementBidding') or [])
    for p in adj:
        if (p.get('placement') or '').upper() in ('PLACEMENT_TOP', 'TOP_OF_SEARCH'):
            try:
                return float(p.get('percentage') or 0)
            except (TypeError, ValueError):
                return None
    return 0.0 if adj or bs else None


def summary(led):
    """The run summary's coverage block: counts by kind and status, the unowned entities (up to 50), the reads missing."""
    counts = Counter((e['kind'], e['status']) for e in led['entities'])
    by_kind = {}
    for (kind, status), n in sorted(counts.items()):
        by_kind.setdefault(kind, {})[status] = n
    unowned = [e for e in led['entities'] if e['status'] == 'unowned']
    return dict(entities=len(led['entities']), by_kind=by_kind, unowned=len(unowned), unowned_rows=unowned[:50],
                reads_missing=led['reads_missing'],
                left_out=[dict(kind=e['kind'], id=e['id'], why=e.get('why', '')) for e in led['entities']
                          if e['status'] in ('multi_asin', 'vcpm') and e['kind'].endswith('campaign')])


# how to read each required read (decision 191): the stop names it, so the session fetches it instead of planning past it
REQUIRED_HOW = {
    'sb_campaigns': 'MAP list_resources sb_campaigns, filters {name_filter: <ASIN>, state_filter: "ENABLED,PAUSED", '
                    'max_results: 100}, every page saved as sb_campaigns_p1.json, sb_campaigns_p2.json, ... '
                    '(an empty list is a read: the product has no SB campaigns)',
    'sb_keywords': 'need_sb_keywords.json lists the campaign id groups and how',
    'sb_targets': 'need_sb_keywords.json lists the campaign id groups and how',
    'sb_themes': 'need_sb_keywords.json lists the campaign id groups and how',
    'live_ad_groups': 'MAP list_resources sp_ad_groups, filters {campaign_id: <one group of the campaign ids '
                      'live_keywords was read by>, state_filter: "ENABLED,PAUSED", max_results: 500}, every page saved as '
                      'live_ad_groups_p1.json, live_ad_groups_p2.json, ... (references/data-pull.md, "Live inventory")',
}


def required_missing(cov, required):
    """The reads in config coverage.required_reads this run doesn't have (decision 191, Kim 2026-11-05: "make sure we are
    optimizing both sponsored products and sponsored brands at the same time"). --accept-unowned never lifts these."""
    return [r for r in (cov or {}).get('reads_missing') or [] if r in set(required or [])]


def required_stop(missing):
    """The stop text for required reads still missing, or None."""
    if not missing:
        return None
    how = '; '.join(f"{r}: {REQUIRED_HOW.get(r, 'references/data-pull.md')}" for r in missing)
    return (f"the run doesn't have {', '.join(missing)}, so the Sponsored Brands keyword bids or the ad-group default bids "
            f"would be left as they are (decision 191: Sponsored Products and Sponsored Brands are priced in the same run, "
            f"and --accept-unowned doesn't lift this). Read them and rerun. {how}")


def stop_reason(cov, stop_on_missing=False):
    """Why the run stops on its coverage (config coverage.stop_on_unowned, and with stop_on_missing the reads it didn't
    have, coverage.stop_on_missing_reads, decision 156), or None."""
    if stop_on_missing and cov and cov.get('reads_missing'):
        return (f"the run doesn't have every live read the coverage check needs ({', '.join(cov['reads_missing'])}), so what "
                'they hold would be left out unseen: read them (references/data-pull.md) and rerun, or plan with '
                '--accept-unowned "<why>"')
    if not cov or not cov.get('unowned'):
        return None
    sample = '; '.join(f"{e['kind']} {e['id']} ({e.get('why', '')})" for e in cov['unowned_rows'][:5])
    return (f"{cov['unowned']} live entities have no owner in this plan (coverage.json lists them; e.g. {sample}). Fix the "
            'planner or the reads, or plan with --accept-unowned "<why>"')
