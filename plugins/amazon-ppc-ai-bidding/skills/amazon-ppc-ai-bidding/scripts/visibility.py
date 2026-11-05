"""Delivery-aware bid review; recommendations never become executable Ads changes."""
import copy
import datetime as dt
import math
from collections import Counter
from dayparting import scheduled_pause


GATES = ('campaign_enabled', 'ad_group_enabled', 'target_enabled', 'ad_eligible',
         'in_stock', 'featured_offer', 'budget_available', 'schedule_open',
         'negatives_clear', 'routing_clear', 'ownership_clear')
IDENTITY = ('asin', 'campaign_id', 'ad_group_id', 'keyword_id', 'keyword', 'match')
LIMITS = ('max_base_bid', 'max_effective_bid', 'max_spend', 'max_loss')
EXPERIMENT_FIELDS = ('experiment_id', 'state', 'stage', 'attempt', 'start_on', 'review_on',
                     'end_on', 'click_goal', *LIMITS)
CLOSED_STATES = {'completed', 'stopped', 'expired', 'cancelled'}
TRACKED_STATES = {'approved', 'active', *CLOSED_STATES}


def number(value, minimum=0):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= minimum)


def date(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def fresh(value, today, maximum):
    observed = date(value)
    return observed is not None and 0 <= (today - observed).days <= maximum


def identity(row, asin=None):
    values = [row.get(field, asin if field == 'asin' else None) for field in IDENTITY]
    if any(value is None or isinstance(value, bool) or not str(value).strip() for value in values):
        return None
    values = [str(value).strip() for value in values]
    values[-2] = ' '.join(values[-2].casefold().split())
    values[-1] = values[-1].upper()
    return tuple(values)


def matching(rows, key):
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows if isinstance(row, dict) and identity(row) == key]


def match_recommendation(row, inputs, as_of, policy):
    inputs = inputs if isinstance(inputs, dict) else {}
    policy = policy if isinstance(policy, dict) else {}
    today = date(as_of)
    key = identity(row, inputs.get('asin'))
    if not today or not key or key[0] != inputs.get('asin'):
        return None, 'missing_target_identity'
    inventory = matching(inputs.get('inventory', []), key)
    if len(inventory) != 1:
        return None, 'missing_or_ambiguous_inventory'
    live = inventory[0]
    if not fresh(live.get('observed_on'), today, policy.get('max_snapshot_age_days', 2)):
        return None, 'stale_inventory'
    candidates = matching(inputs.get('recommendations', []), key)
    if not candidates:
        return None, 'missing_contextual_recommendation'
    if len(candidates) != 1:
        return None, 'ambiguous_contextual_recommendation'
    recommendation = candidates[0]
    if (not isinstance(recommendation.get('strategy'), str) or not recommendation['strategy']
            or recommendation['strategy'] != live.get('strategy')):
        return None, 'recommendation_strategy_mismatch'
    if inputs.get('profile_id') and (recommendation.get('profile_id') != inputs['profile_id']
                                     or live.get('profile_id') != inputs['profile_id']):
        return None, 'recommendation_profile_mismatch'
    if not recommendation.get('source'):
        return None, 'recommendation_source_missing'
    if not fresh(recommendation.get('fetched_on'), today, policy.get('max_recommendation_age_days', 7)):
        return None, 'stale_contextual_recommendation'
    values = [recommendation.get(field) for field in ('low', 'median', 'high')]
    if not all(number(value, .000001) for value in values) or values != sorted(values):
        return None, 'invalid_contextual_range'
    return copy.deepcopy(recommendation), 'matched'


# A review that couldn't answer a check: the planner's bid goes out and the gap is logged (decision 107).
UNANSWERED_STATUSES = ('missing_data', 'waiting_data')
UNANSWERED_CODES = ('rank_recommendation_missing',)


def holds_bid(review):
    """Whether a review holds its keyword's bid (and, for a rank search, its investment) this run. Kim, 2026-10-23,
    decision 107: "a check that comes back 'no' still stops it ... a check the AI couldn't answer no longer stops it".

    A check that came back "no" holds it (manual/unknown pause, not eligible, out of stock, no Buy Box, no budget,
    a negative or another campaign's routing in the way). A verified scheduled OFF period permits base-bid pricing.
    A review that protects a live experiment or
    a retained rank investment. A check the AI couldn't answer (missing or stale inputs, an unknown gate, too few days
    of delivery, no contextual recommendation) holds nothing, except for a tracked experiment, whose history it keeps:
    the planner's bid goes out, and the review row records the gap (status, reason_code, missing_requests)."""
    if not review or not review.get('guard_bid_change'):
        return False
    if review.get('status') in UNANSWERED_STATUSES or review.get('reason_code') in UNANSWERED_CODES:
        experiment = review.get('experiment') or {}
        return isinstance(experiment.get('state'), str) and experiment['state'] in TRACKED_STATES
    return True


def experiment_errors(experiment, today, maximum_days):
    missing = [field for field in EXPERIMENT_FIELDS if experiment.get(field) is None]
    errors = []
    for field in LIMITS:
        if field in missing:
            continue
        minimum = 0 if field == 'max_loss' else .000001
        if not number(experiment[field], minimum):
            errors.append(field)
    for field in ('click_goal', 'attempt'):
        value = experiment.get(field)
        if field not in missing and (not number(value, 1) or int(value) != value):
            errors.append(field)
    start, review, end = [date(experiment.get(field)) for field in ('start_on', 'review_on', 'end_on')]
    if not all((start, review, end)):
        errors.append('experiment_dates')
    elif not start <= review <= end or (end - start).days > maximum_days:
        errors.append('experiment_window')
    if experiment.get('stage') not in ('initial', 'low', 'median'):
        errors.append('stage')
    if not isinstance(experiment.get('state'), str) or experiment['state'] not in {'proposed', *TRACKED_STATES}:
        errors.append('state')
    for field in ('spend_to_date', 'loss_to_date', 'stage_eligible_days'):
        if field in experiment and not number(experiment[field]):
            errors.append(field)
    if number(experiment.get('attempt'), 2):
        errors += [field for field in ('spend_to_date', 'loss_to_date') if field not in experiment]
    return sorted(set(missing + errors))


def approval_valid(experiment, key):
    approval = experiment.get('approval') or {}
    return (isinstance(approval, dict) and approval.get('state') == 'approved'
            and approval.get('by') and approval.get('reference')
            and approval.get('experiment_id') == experiment.get('experiment_id')
            and approval.get('asin') == key[0]
            and str(approval.get('keyword_id')) == key[3])


def stop_reason(experiment, today):
    if not isinstance(experiment.get('state'), str) or experiment['state'] not in {'proposed', *TRACKED_STATES}:
        return None
    if experiment['state'] in CLOSED_STATES:
        return 'experiment_closed', 'This experiment is already closed; retain the outcome and do not start its clock again.'
    end = date(experiment.get('end_on'))
    if end and today >= end:
        return 'experiment_expired', 'The experiment deadline has arrived; review results and rollback/stop within its approved scope. Do not renew automatically.'
    for metric, limit in (('spend_to_date', 'max_spend'), ('loss_to_date', 'max_loss')):
        used, maximum = experiment.get(metric), experiment.get(limit)
        if number(used) and number(maximum) and used > 0 and used >= maximum:
            return 'experiment_allowance_exhausted', 'The cumulative approved spend/loss allowance is exhausted; stop/review, never reset the allowance.'
    return None


def delivery_errors(delivery, today, policy):
    errors = []
    if delivery.get('complete') is not True:
        errors.append('complete')
    start, end = date(delivery.get('start_on')), date(delivery.get('end_on'))
    if not start or not end or start > end or end > today:
        errors.append('window')
    elif not fresh(delivery['end_on'], today, policy.get('max_delivery_age_days', 2)):
        errors.append('stale_window')
    for field in ('eligible_days', 'impressions', 'clicks', 'orders', 'spend'):
        if not number(delivery.get(field)):
            errors.append(field)
    for field in ('click_goal', 'goal_days'):
        if not number(delivery.get(field), 1):
            errors.append(field)
    if start and end and number(delivery.get('eligible_days')):
        if delivery['eligible_days'] > (end - start).days + 1:
            errors.append('eligible_days_exceed_window')
    if number(delivery.get('impressions')) and number(delivery.get('clicks')):
        if delivery['clicks'] > delivery['impressions']:
            errors.append('clicks_exceed_impressions')
    return errors


def flags_for(delivery, row):
    flags = []
    impressions, clicks = delivery['impressions'], delivery['clicks']
    ctr_floor = delivery.get('ctr_floor')
    ctr_sample = delivery.get('ctr_min_impressions')
    if (number(ctr_floor, .000001) and ctr_floor <= 1 and number(ctr_sample, 1)
            and impressions >= ctr_sample and clicks / impressions < ctr_floor):
        flags.append('low_ctr')
    cvr_floor = delivery.get('cvr_floor')
    cvr_sample = delivery.get('cvr_min_clicks')
    if (delivery.get('attribution_mature') is True and number(cvr_floor, .000001)
            and cvr_floor <= 1 and number(cvr_sample, 1) and clicks >= cvr_sample
            and delivery['orders'] / clicks < cvr_floor):
        flags.append('poor_conversion')
    if clicks and number(row.get('breakeven_cpc'), .000001):
        if delivery['spend'] / clicks > row['breakeven_cpc']:
            flags.append('observed_cpc_above_estimated_breakeven')
    if delivery.get('attribution_mature') is not True:
        flags.append('conversion_attribution_not_mature')
    return flags


def build_review(asin, rows, terms, inputs, policy, as_of):
    inputs = inputs if isinstance(inputs, dict) else {}
    policy = policy if isinstance(policy, dict) else {}
    today = date(as_of)
    if not today:
        raise ValueError('Visibility as_of must be an ISO calendar date')
    result = dict(asin=asin, as_of=as_of, preview_only=True, rows=[], counts={}, missing_requests=[],
                  note='Delivery diagnostics and bounded experiment previews only. No bid is applied, and suggested bids do not guarantee impressions, paid CPC or profitability.')
    reviews = result['rows']
    minimum_days = policy.get('review_days', 7)
    maximum_days = policy.get('experiment_window_days', 14)
    for source in rows:
        row = copy.deepcopy(source)
        key = identity(row, asin)
        retained_rank = row.get('role') in ('Rank', 'Invest', 'Prove first') and row.get('rank_investment_existing') is True
        review = {field: row.get(field, asin if field == 'asin' else None) for field in IDENTITY}
        review.update(role=row.get('role'), economic_base_bid=row.get('new_bid'), live_bid=row.get('bid'),
                      breakeven_cpc=row.get('breakeven_cpc'), suggested=None, experiment=None, proposal=None,
                      protect_baseline=retained_rank, guard_bid_change=retained_rank, flags=[], preview_only=True)
        reviews.append(review)

        def finish(status, reason_code, reason, protect=None, missing=None):
            review.update(status=status, delivery_state=status, reason_code=reason_code, reason=reason)
            if protect is not None:
                review['protect_baseline'] = review['guard_bid_change'] = protect
            if missing:
                result['missing_requests'].append(dict(keyword_id=review['keyword_id'], asin=asin,
                                                       reason=reason_code, required=list(missing)))

        if inputs.get('asin') != asin or not key:
            finish('missing_data', 'missing_visibility_inputs', 'Delivery is unverified; provide this ASIN and the exact target identity.', missing=['visibility_inputs.json'])
            continue
        live_rows = matching(inputs.get('inventory', []), key)
        experiment_rows = matching(inputs.get('experiments', []), key)
        if len(experiment_rows) > 1:
            finish('review_experiment', 'ambiguous_experiment_history', 'Multiple experiment records match this target; reconcile history without restarting it.', True)
            continue
        experiment = experiment_rows[0] if experiment_rows else None
        review['experiment'] = copy.deepcopy(experiment)
        tracked = bool(experiment and isinstance(experiment.get('state'), str)
                       and experiment['state'] in TRACKED_STATES)
        stop = stop_reason(experiment, today) if experiment else None
        if stop:
            finish('stop_review', stop[0], stop[1], True)
            continue
        if len(live_rows) != 1:
            finish('missing_data', 'missing_or_ambiguous_inventory', 'A unique current live target snapshot is required; missing rows are not zero delivery.', tracked or retained_rank, ['inventory'])
            continue
        live = live_rows[0]
        review['live_bid'] = live.get('current_bid')
        review['protect_baseline'] = review['guard_bid_change'] = True
        # Exact-ID schedule evidence remains useful when unrelated inventory is incomplete.
        # Resolve this before generic data-gap exits so they cannot hide a known blocker
        # or accidentally authorize routing while the verified owner is scheduled OFF.
        pause = scheduled_pause(live, as_of, policy.get('max_snapshot_age_days', 2))
        review['scheduled_pause'] = pause
        if pause:
            gates = live.get('gates') or {}
            blocked = [gate for gate in GATES if gates.get(gate) is False and gate not in pause['exempt_gates']]
            if blocked:
                finish('blocked', 'preflight_blocked', 'Resolve the serving/ownership blocker before changing bids: ' + ', '.join(blocked) + '.')
                review['blocked_gates'] = blocked
            else:
                finish('scheduled_off', 'scheduled_dayparting_pause',
                       'Verified scheduled OFF period: continue normal base-bid pricing; do not unpause, change the schedule, '
                       'infer low delivery or cut replacement routes. Next scheduled ON: ' + pause['next_on_utc'] + '.',
                       tracked or retained_rank or (row.get('owner_kind') == 'business' and row.get('role') == 'Rank'))
            continue
        if inputs.get('inventory_complete') is not True:
            finish('missing_data', 'incomplete_inventory', 'The live target inventory is incomplete; preserve the bid pending reconciliation.', missing=['inventory_complete'])
            continue
        if not fresh(live.get('observed_on'), today, policy.get('max_snapshot_age_days', 2)):
            finish('missing_data', 'stale_inventory', 'Refresh live target state before diagnosing delivery or changing a tracked bid.', missing=['inventory.observed_on'])
            continue
        if not isinstance(live.get('strategy'), str) or not live['strategy'] or not number(live.get('current_bid'), .000001):
            finish('missing_data', 'missing_live_bid_context', 'Current bid and campaign bidding strategy must be verified.', missing=['inventory.current_bid', 'inventory.strategy'])
            continue
        recommendation, recommendation_reason = match_recommendation(row, inputs, as_of, policy)
        review['suggested'] = recommendation
        review['recommendation_status'] = recommendation_reason
        if not recommendation:
            result['missing_requests'].append(dict(keyword_id=review['keyword_id'], asin=asin,
                                                   reason=recommendation_reason, required=['recommendations']))
        gates = live.get('gates') if isinstance(live.get('gates'), dict) else {}
        review['retained_rank'] = retained_rank
        blocked = [gate for gate in GATES if gates.get(gate) is False]
        unknown = [gate for gate in GATES if gates.get(gate) is not True and gates.get(gate) is not False]
        if blocked:
            finish('blocked', 'preflight_blocked', 'Resolve the serving/ownership blocker before raising bids: ' + ', '.join(blocked) + '.')
            review['blocked_gates'] = blocked
            continue
        if unknown:
            finish('missing_data', 'preflight_unknown', 'Preflight is not fully verified; no visibility increase is proposed.', missing=['gates.' + gate for gate in unknown])
            continue
        if experiment:
            errors = experiment_errors(experiment, today, maximum_days)
            if tracked and errors:
                finish('review_experiment', 'invalid_experiment_record', 'The existing experiment has missing or invalid controls; preserve its history and reconcile before any new proposal.', missing=errors)
                continue
            if tracked:
                if not approval_valid(experiment, key):
                    finish('review_experiment', 'approval_unverified', 'An approved/active experiment needs its named, target-matched approval record before continuation.', missing=['experiment.approval'])
                    continue
                if not all(number(experiment.get(field)) for field in ('spend_to_date', 'loss_to_date')):
                    finish('review_experiment', 'experiment_monitoring_missing', 'Cumulative spend and loss must be known before continuing the existing experiment.', missing=['spend_to_date', 'loss_to_date'])
                    continue
                if not number(live.get('effective_bid_multiplier'), 1):
                    finish('review_experiment', 'effective_exposure_unknown', 'The tracked experiment needs a verified combined bid multiplier before its live exposure can be considered within bounds.', missing=['inventory.effective_bid_multiplier'])
                    continue
                if (live['current_bid'] > experiment['max_base_bid']
                        or live['current_bid'] * live['effective_bid_multiplier'] > experiment['max_effective_bid']):
                    finish('stop_review', 'live_experiment_bid_ceiling', 'The observed bid exposure exceeds the experiment ceiling; review/rollback within the approved scope, never raise the ceiling automatically.')
                    continue
                if today < date(experiment['start_on']) or today < date(experiment['review_on']):
                    finish('active_experiment', 'experiment_not_due', 'Keep the approved experiment unchanged until its recorded start/review date; do not reprice from the old baseline.')
                    continue
        if row.get('role') == 'Trim':
            finish('trim_no_rescue', 'intentional_efficiency_reduction', 'Trim deliberately limits uneconomic traffic. Missing visibility metrics or low delivery do not justify a bid rescue; retain the economic trim unless a tracked experiment conflicts.', tracked)
            continue
        if (row.get('role') not in ('Test', 'Discovery', 'Hold', 'Defend', 'Rank', 'Invest', 'Prove first')
                or row.get('family') in ('Audience (low bids)', 'Business')):
            finish('review_traffic', 'role_not_eligible_for_rescue', 'This role, audience or business campaign is not eligible for a visibility bid rescue.', tracked)
            continue
        delivery_rows = matching(inputs.get('delivery', []), key)
        if len(delivery_rows) != 1:
            finish('missing_data', 'missing_or_ambiguous_delivery', 'Provide one complete delivery window, including explicit zeros for an idle target.', missing=['delivery'])
            continue
        delivery = delivery_rows[0]
        errors = delivery_errors(delivery, today, policy)
        if errors:
            finish('missing_data', 'invalid_delivery_window', 'Delivery cannot be judged from missing, stale or inconsistent observations.', missing=['delivery.' + field for field in errors])
            continue
        review['metrics'] = copy.deepcopy(delivery)
        review['flags'] = flags_for(delivery, row)
        if row.get('role') == 'Discovery':
            review['flags'].append('prefer_exact_query_validation')
        eligible_days = delivery['eligible_days']
        expected_clicks = delivery['click_goal'] * eligible_days / delivery['goal_days']
        review['metrics']['expected_clicks_at_current_pace'] = round(expected_clicks, 2)
        review['metrics']['observed_cpc'] = round(delivery['spend'] / delivery['clicks'], 4) if delivery['clicks'] else None
        review['metrics']['ctr'] = delivery['clicks'] / delivery['impressions'] if delivery['impressions'] else None
        if eligible_days < minimum_days:
            finish('waiting_data', 'too_few_eligible_days', f'Only {eligible_days:g} eligible days; wait for {minimum_days:g} before diagnosing a stalled test.')
            continue
        if delivery['clicks'] >= expected_clicks:
            if row.get('role') in ('Rank', 'Invest', 'Prove first') and not recommendation:
                finish('rank_review', 'rank_recommendation_missing', 'Delivery is adequate, but rank repricing requires a fresh recommendation for this exact target context; preserve the current investment until it is verified.')
            else:
                finish('healthy', 'adequate_click_pace', 'Clicks are arriving at the explicit target pace; do not raise the bid merely to match Amazon recommendations.', tracked or retained_rank)
            continue
        if row.get('role') in ('Rank', 'Invest', 'Prove first'):
            if row.get('rank_investment_existing') is True or tracked:
                finish('rank_review', 'existing_rank_controls_apply', 'Review under-delivery within the original rank investment, loss allowance and stop-loss clock. Do not create a replacement 14-day visibility experiment.')
            elif not recommendation:
                finish('rank_review', 'rank_recommendation_missing', 'A new rank proposal needs a fresh recommendation for this exact target context before repricing; no visibility trial substitutes for it.')
            else:
                finish('rank_review', 'new_rank_preview_permitted', 'No existing rank investment is recorded. The contextual range supports the normal rank-investment preview, subject to its separate approval and controls; no 14-day visibility trial is created.', False)
            continue
        if 'low_ctr' in review['flags']:
            finish('review_traffic', 'low_ctr', 'Impressions are present but CTR is below the supplied benchmark; review relevance/offer before paying more for visibility.')
            continue
        if 'poor_conversion' in review['flags']:
            finish('review_traffic', 'poor_conversion', 'Mature conversion is below the supplied benchmark; diagnose economics/relevance rather than rescuing delivery automatically.')
            continue
        demand = live.get('demand') if isinstance(live.get('demand'), dict) else {}
        if demand.get('known') is not True or not demand.get('source') or not fresh(demand.get('as_of'), today, policy.get('max_recommendation_age_days', 7)):
            finish('missing_data', 'demand_unknown', 'Establish current query/target opportunity before interpreting low delivery as a bid problem.', missing=['inventory.demand'])
            continue
        if demand.get('available') is not True:
            if demand.get('available') is False:
                finish('limited_demand', 'insufficient_demand', 'Verified demand is insufficient; a higher bid cannot create searches.')
            else:
                finish('missing_data', 'demand_unknown', 'Available demand must be explicitly verified.', missing=['inventory.demand.available'])
            continue
        if not recommendation:
            finish('under_delivering', recommendation_reason, 'Click pace is insufficient, but a fresh target/match/group/strategy-specific Amazon range is required before proposing a visibility test.')
            continue
        multiplier = live.get('effective_bid_multiplier')
        if not number(multiplier, 1):
            finish('missing_data', 'effective_exposure_unknown', 'Verify the conservative combined placement/strategy bid multiplier; a base-bid cap alone is insufficient.', missing=['inventory.effective_bid_multiplier'])
            continue
        stage = experiment.get('stage', 'initial') if experiment else 'initial'
        if tracked and experiment['state'] == 'approved':
            finish('review_experiment', 'activation_not_verified', 'Approval is recorded but activation is not; verify the live launch before escalating a test.')
            continue
        if stage == 'median':
            finish('stop_review', 'median_stage_exhausted', 'The recorded median-stage test is still under-delivering; investigate/review rather than escalate automatically to high.')
            continue
        next_stage = 'low'
        if stage == 'low':
            if not tracked or experiment.get('state') != 'active':
                finish('review_experiment', 'low_stage_not_verified', 'A completed observation period at the low stage must be recorded before proposing median.')
                continue
            if not number(experiment.get('stage_eligible_days')) or experiment['stage_eligible_days'] < minimum_days:
                finish('active_experiment', 'stage_not_mature', 'Keep the low-stage test unchanged until it has enough eligible days; do not skip to median.')
                continue
            stage_start = date(experiment.get('stage_started_on'))
            if (not stage_start or stage_start < date(experiment['start_on'])
                    or stage_start > date(delivery['start_on'])
                    or experiment['stage_eligible_days'] > (date(delivery['end_on']) - stage_start).days + 1):
                finish('review_experiment', 'stage_window_unverified', 'The low-stage observation window must follow its recorded activation date; pre-change traffic cannot qualify the next stage.', missing=['stage_started_on', 'stage_eligible_days'])
                continue
            next_stage = 'median'
        candidate = recommendation[next_stage]
        if candidate <= live['current_bid']:
            finish('review_traffic', 'already_at_suggested_stage', 'The current bid already meets this ladder stage. Investigate delivery and record the trial before escalating; no automatic high bid.')
            continue
        proposal = dict(preview_only=True, stage=next_stage, candidate_bid=round(candidate, 2),
                        effective_bid=round(candidate * multiplier, 4), effective_bid_multiplier=multiplier,
                        economics_note='Suggested bids are auction guidance, not paid CPC. Compare observed CPC and attributable contribution; exposure above breakeven requires an explicit learning/investment allowance.',
                        needs_boundaries=True, missing_fields=[], approval_state='not_approved',
                        approval_required=True, executable=False)
        if number(row.get('breakeven_cpc'), .000001):
            proposal['base_bid_to_breakeven'] = round(candidate / row['breakeven_cpc'], 3)
            proposal['effective_bid_to_breakeven'] = round(candidate * multiplier / row['breakeven_cpc'], 3)
        errors = experiment_errors(experiment or {}, today, maximum_days)
        query_review = live.get('query_mix_review')
        if row.get('role') == 'Discovery':
            query_review = query_review if isinstance(query_review, dict) else {}
            proposal['scope_note'] = 'Prefer a proven shopper query in its exact owner. A broad/phrase target test needs a reviewed traffic mix and a reason not to isolate the query; never lift the whole discovery pool.'
            if (query_review.get('reviewed') is not True or query_review.get('exact_owner_checked') is not True
                    or not query_review.get('source') or not query_review.get('reason_to_test_target')
                    or not fresh(query_review.get('as_of'), today, policy.get('max_recommendation_age_days', 7))):
                errors.append('query_mix_review')
            else:
                proposal['query_mix_review'] = copy.deepcopy(query_review)
        proposal['missing_fields'] = errors
        review['proposal'] = proposal
        if errors:
            finish('needs_bounds', 'experiment_controls_required', 'Potential visibility test only: supply a named experiment, dates, click goal, separate base/effective ceilings and cumulative spend/loss limits before approval.', missing=errors)
            continue
        proposal.update({field: experiment[field] for field in EXPERIMENT_FIELDS})
        approval = experiment.get('approval') if isinstance(experiment.get('approval'), dict) else {}
        proposal.update(stage=next_stage, previous_stage=stage, needs_boundaries=False,
                        remaining_spend=experiment['max_spend'] - experiment.get('spend_to_date', 0),
                        remaining_loss=experiment['max_loss'] - experiment.get('loss_to_date', 0),
                        approval_state=approval.get('state', 'not_approved'))
        if today >= date(experiment['end_on']):
            finish('stop_review', 'experiment_expired', 'The proposed experiment dates have expired; do not silently restart or extend them.')
            continue
        if candidate > experiment['max_base_bid'] or candidate * multiplier > experiment['max_effective_bid']:
            finish('under_delivering', 'experiment_bid_ceiling', 'The next suggested stage exceeds its base/effective bid ceiling; do not lift the cap automatically.')
            continue
        finish('candidate', 'bounded_visibility_preview', 'Preview a bounded visibility test at the next permitted suggested stage. Obtain exact-scope approval and live preflight before any write.')
    result['counts'] = dict(Counter(row['status'] for row in reviews))
    result['status'] = 'review_ready' if inputs.get('asin') == asin else 'missing_data'
    return result
