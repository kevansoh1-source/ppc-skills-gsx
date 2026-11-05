import copy
import unittest

import visibility


ASIN = 'B0SAMP0005'
TODAY = '2026-10-19'
POLICY = dict(review_days=7, experiment_window_days=14, max_recommendation_age_days=7,
              max_snapshot_age_days=2, max_delivery_age_days=2)
KEY = dict(asin=ASIN, keyword_id='123', campaign_id='456', ad_group_id='789',
           keyword='Thank you cards assorted', match='BROAD')


def fixture():
    row = dict(KEY, role='Discovery', bid=.16, new_bid=.47, breakeven_cpc=.47,
               clicks90=44, orders90=7, family='Discovery')
    live = dict(KEY, observed_on=TODAY, strategy='down_only', current_bid=.16,
                effective_bid_multiplier=1, gates={field: True for field in visibility.GATES},
                demand=dict(known=True, available=True, source='saved matched demand review', as_of=TODAY),
                query_mix_review=dict(reviewed=True, exact_owner_checked=True, source='matched search term report',
                                      as_of=TODAY, reason_to_test_target='Several relevant converting shopper queries remain in this bounded target.'))
    delivery = dict(KEY, start_on='2026-10-12', end_on='2026-10-18', complete=True,
                    eligible_days=7, impressions=0, clicks=0, orders=0, spend=0,
                    click_goal=14, goal_days=14, attribution_mature=False)
    recommendation = dict(KEY, fetched_on=TODAY, strategy='down_only', low=.73, median=1.02,
                          high=1.32, source='Amazon target recommendations')
    return row, dict(asin=ASIN, inventory_complete=True, inventory=[live], delivery=[delivery],
                     recommendations=[recommendation], experiments=[])


def experiment(state='proposed', stage='initial'):
    return dict(KEY, experiment_id='visibility-123-v1', state=state, stage=stage, attempt=1,
                start_on='2026-10-12', review_on=TODAY, end_on='2026-10-26', click_goal=14,
                max_base_bid=1.1, max_effective_bid=1.1, max_spend=15, max_loss=8,
                spend_to_date=2, loss_to_date=1, stage_eligible_days=7, stage_started_on='2026-10-12',
                approval=dict(state='approved' if state in ('approved', 'active') else 'pending',
                              by='Reviewer', reference='approval-123', experiment_id='visibility-123-v1',
                              asin=ASIN, keyword_id='123'))


def review(row=None, data=None):
    default_row, default_data = fixture()
    return visibility.build_review(ASIN, [row or default_row], {}, default_data if data is None else data,
                                   POLICY, TODAY)['rows'][0]


class VisibilityTests(unittest.TestCase):
    def test_missing_inputs_preserve_historical_baseline_without_inference(self):
        result = review(data={})
        self.assertEqual(result['status'], 'missing_data')
        self.assertFalse(result['protect_baseline'])
        self.assertIsNone(result['proposal'])

    def test_zero_activity_is_visible_but_not_approved(self):
        row, data = fixture()
        result = review(row, data)
        self.assertEqual(result['status'], 'needs_bounds')
        self.assertTrue(result['protect_baseline'])
        self.assertEqual(result['proposal']['candidate_bid'], .73)
        self.assertTrue(result['proposal']['needs_boundaries'])
        self.assertFalse(result['proposal']['executable'])
        self.assertNotIn('changes', result)

    def test_bounded_proposal_does_not_require_prior_approval(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        result = review(row, data)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['proposal']['approval_state'], 'pending')
        self.assertTrue(result['proposal']['approval_required'])
        self.assertEqual(result['proposal']['max_loss'], 8)

    def test_inputs_are_not_mutated(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        before = copy.deepcopy((row, data))
        review(row, data)
        self.assertEqual((row, data), before)

    def test_live_missing_vs_explicit_zero(self):
        row, data = fixture()
        data['delivery'] = []
        result = review(row, data)
        self.assertEqual(result['reason_code'], 'missing_or_ambiguous_delivery')
        self.assertIsNone(result['proposal'])

    def test_incomplete_inventory_blocks(self):
        row, data = fixture()
        data['inventory_complete'] = False
        self.assertEqual(review(row, data)['reason_code'], 'incomplete_inventory')

    def test_each_unknown_preflight_blocks(self):
        for gate in visibility.GATES:
            with self.subTest(gate=gate):
                row, data = fixture()
                del data['inventory'][0]['gates'][gate]
                result = review(row, data)
                self.assertEqual(result['reason_code'], 'preflight_unknown')
                self.assertIsNone(result['proposal'])

    def test_each_false_preflight_blocks(self):
        for gate in visibility.GATES:
            with self.subTest(gate=gate):
                row, data = fixture()
                data['inventory'][0]['gates'][gate] = False
                self.assertEqual(review(row, data)['status'], 'blocked')

    def test_fewer_than_seven_eligible_days_waits(self):
        row, data = fixture()
        data['delivery'][0]['eligible_days'] = 6
        self.assertEqual(review(row, data)['status'], 'waiting_data')

    def test_regular_clicks_do_not_trigger_range_floor(self):
        row, data = fixture()
        data['delivery'][0].update(impressions=700, clicks=7, orders=1, spend=1)
        result = review(row, data)
        self.assertEqual(result['status'], 'healthy')
        self.assertFalse(result['protect_baseline'])
        self.assertIsNone(result['proposal'])

    def test_impressions_without_clicks_are_not_enough(self):
        row, data = fixture()
        data['delivery'][0]['impressions'] = 100
        self.assertEqual(review(row, data)['status'], 'needs_bounds')

    def test_low_ctr_is_traffic_diagnosis_not_bid_raise(self):
        row, data = fixture()
        data['delivery'][0].update(impressions=1000, ctr_floor=.005, ctr_min_impressions=500)
        self.assertEqual(review(row, data)['reason_code'], 'low_ctr')

    def test_poor_mature_conversion_is_not_visibility_rescue(self):
        row, data = fixture()
        data['delivery'][0].update(impressions=1000, clicks=20, spend=10, click_goal=60,
                                   cvr_floor=.1, cvr_min_clicks=15, attribution_mature=True)
        self.assertEqual(review(row, data)['reason_code'], 'poor_conversion')

    def test_immature_conversion_is_not_declared_poor(self):
        row, data = fixture()
        data['delivery'][0].update(impressions=1000, clicks=20, spend=10, click_goal=60,
                                   cvr_floor=.1, cvr_min_clicks=15)
        result = review(row, data)
        self.assertNotIn('poor_conversion', result['flags'])
        self.assertIn('conversion_attribution_not_mature', result['flags'])

    def test_trim_has_no_visibility_rescue(self):
        row, data = fixture()
        row['role'] = 'Trim'
        result = review(row, data)
        self.assertEqual(result['status'], 'trim_no_rescue')
        self.assertFalse(result['protect_baseline'])
        self.assertIsNone(result['proposal'])

    def test_trim_missing_delivery_still_keeps_economic_trim(self):
        row, data = fixture()
        row['role'] = 'Trim'
        data['delivery'] = []
        data['recommendations'] = []
        result = review(row, data)
        self.assertEqual(result['status'], 'trim_no_rescue')
        self.assertFalse(result['protect_baseline'])
        self.assertEqual(result['recommendation_status'], 'missing_contextual_recommendation')

    def test_hold_and_defend_can_preview_bounded_rescue(self):
        for role in ('Hold', 'Defend', 'Test', 'Discovery'):
            with self.subTest(role=role):
                row, data = fixture()
                row['role'] = role
                data['experiments'] = [experiment()]
                self.assertEqual(review(row, data)['status'], 'candidate')

    def test_unknown_demand_fails_closed(self):
        row, data = fixture()
        data['inventory'][0]['demand'] = {}
        self.assertEqual(review(row, data)['reason_code'], 'demand_unknown')

    def test_limited_demand_does_not_escalate(self):
        row, data = fixture()
        data['inventory'][0]['demand']['available'] = False
        self.assertEqual(review(row, data)['status'], 'limited_demand')

    def test_recommendation_identity_has_no_text_only_fallback(self):
        for field, different in [('asin', 'OTHER'), ('campaign_id', 'OTHER'), ('ad_group_id', 'OTHER'),
                                  ('keyword_id', 'OTHER'), ('match', 'EXACT'), ('keyword', 'different')]:
            with self.subTest(field=field):
                row, data = fixture()
                data['recommendations'][0][field] = different
                self.assertEqual(visibility.match_recommendation(row, data, TODAY, POLICY),
                                 (None, 'missing_contextual_recommendation'))

    def test_strategy_must_match(self):
        row, data = fixture()
        data['recommendations'][0]['strategy'] = 'up_and_down'
        self.assertEqual(review(row, data)['reason_code'], 'recommendation_strategy_mismatch')

    def test_profile_must_match_if_supplied(self):
        row, data = fixture()
        data['profile_id'] = 'us-profile'
        self.assertEqual(review(row, data)['reason_code'], 'recommendation_profile_mismatch')

    def test_stale_or_future_recommendations_fail_closed(self):
        for fetched_on in ('2026-10-11', '2026-10-20', None):
            with self.subTest(fetched_on=fetched_on):
                row, data = fixture()
                data['recommendations'][0]['fetched_on'] = fetched_on
                self.assertEqual(review(row, data)['reason_code'], 'stale_contextual_recommendation')

    def test_invalid_ranges_fail_closed(self):
        for value in (None, True, float('nan'), -.1, 1.5):
            with self.subTest(value=value):
                row, data = fixture()
                data['recommendations'][0]['low'] = value
                self.assertEqual(review(row, data)['reason_code'], 'invalid_contextual_range')

    def test_missing_and_duplicate_recs_fail_closed(self):
        row, data = fixture()
        data['recommendations'] *= 2
        self.assertEqual(review(row, data)['reason_code'], 'ambiguous_contextual_recommendation')
        self.assertEqual(visibility.match_recommendation(row, {}, TODAY, POLICY),
                         (None, 'missing_target_identity'))

    def test_effective_bid_requires_multiplier(self):
        row, data = fixture()
        del data['inventory'][0]['effective_bid_multiplier']
        self.assertEqual(review(row, data)['reason_code'], 'effective_exposure_unknown')

    def test_effective_bid_cap_checked_separately(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        data['inventory'][0]['effective_bid_multiplier'] = 2
        result = review(row, data)
        self.assertEqual(result['reason_code'], 'experiment_bid_ceiling')
        self.assertEqual(result['proposal']['effective_bid'], 1.46)

    def test_active_test_is_not_repriced_before_review(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'low')]
        data['experiments'][0]['review_on'] = '2026-10-20'
        result = review(row, data)
        self.assertEqual(result['reason_code'], 'experiment_not_due')
        self.assertTrue(result['protect_baseline'])

    def test_expired_experiment_never_resets(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'low')]
        data['experiments'][0]['end_on'] = TODAY
        result = review(row, data)
        self.assertEqual(result['reason_code'], 'experiment_expired')
        self.assertEqual(result['experiment']['attempt'], 1)
        self.assertIsNone(result['proposal'])

    def test_cumulative_spend_and_loss_stop_without_reset(self):
        for field, value in [('spend_to_date', 15), ('loss_to_date', 8)]:
            with self.subTest(field=field):
                row, data = fixture()
                data['experiments'] = [experiment('active', 'low')]
                data['experiments'][0][field] = value
                self.assertEqual(review(row, data)['reason_code'], 'experiment_allowance_exhausted')

    def test_no_restart_of_closed_experiment(self):
        row, data = fixture()
        data['experiments'] = [experiment('completed', 'low')]
        self.assertEqual(review(row, data)['reason_code'], 'experiment_closed')

    def test_experiment_monitoring_and_named_approval_required(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'low')]
        del data['experiments'][0]['approval']['by']
        self.assertEqual(review(row, data)['reason_code'], 'approval_unverified')
        data['experiments'][0] = experiment('active', 'low')
        del data['experiments'][0]['loss_to_date']
        self.assertEqual(review(row, data)['reason_code'], 'experiment_monitoring_missing')

    def test_low_stage_must_have_eligible_observation_before_median(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'low')]
        data['experiments'][0]['stage_eligible_days'] = 3
        self.assertEqual(review(row, data)['reason_code'], 'stage_not_mature')
        data['experiments'][0]['stage_eligible_days'] = 7
        data['inventory'][0]['current_bid'] = .73
        result = review(row, data)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['proposal']['candidate_bid'], 1.02)
        self.assertEqual(result['proposal']['previous_stage'], 'low')
        self.assertEqual(result['proposal']['attempt'], 1)
        self.assertEqual(result['proposal']['start_on'], '2026-10-12')
        self.assertEqual(result['proposal']['remaining_spend'], 13)

    def test_median_never_escalates_to_high(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'median')]
        self.assertEqual(review(row, data)['reason_code'], 'median_stage_exhausted')

    def test_above_low_without_test_record_is_not_proof_to_jump(self):
        row, data = fixture()
        data['inventory'][0]['current_bid'] = .8
        self.assertEqual(review(row, data)['reason_code'], 'already_at_suggested_stage')

    def test_approved_but_unverified_activation_cannot_escalate(self):
        row, data = fixture()
        data['experiments'] = [experiment('approved', 'low')]
        self.assertEqual(review(row, data)['reason_code'], 'activation_not_verified')

    def test_all_limits_required_and_invalid_values_block(self):
        for field in visibility.LIMITS:
            with self.subTest(field=field):
                row, data = fixture()
                data['experiments'] = [experiment()]
                data['experiments'][0][field] = None
                result = review(row, data)
                self.assertEqual(result['status'], 'needs_bounds')
                self.assertIn(field, result['proposal']['missing_fields'])

    def test_invalid_delivery_never_zero_filled(self):
        for field, value in [('clicks', None), ('impressions', -1), ('spend', float('inf')),
                              ('complete', False), ('eligible_days', 8), ('click_goal', 0),
                              ('goal_days', None), ('end_on', '2026-10-10')]:
            with self.subTest(field=field):
                row, data = fixture()
                data['delivery'][0][field] = value
                self.assertEqual(review(row, data)['reason_code'], 'invalid_delivery_window')

    def test_counts_and_missing_requests_include_target(self):
        row, data = fixture()
        result = visibility.build_review(ASIN, [row], {}, data, POLICY, TODAY)
        self.assertEqual(result['counts'], {'needs_bounds': 1})
        self.assertEqual(result['missing_requests'][0]['keyword_id'], '123')

    def test_rank_roles_cannot_create_replacement_visibility_clock(self):
        for role in ('Rank', 'Invest', 'Prove first'):
            with self.subTest(role=role):
                row, data = fixture()
                row['role'] = role
                row['rank_investment_existing'] = True
                result = review(row, data)
                self.assertEqual(result['status'], 'rank_review')
                self.assertTrue(result['protect_baseline'])
                self.assertIsNone(result['proposal'])

    def test_new_rank_can_use_contextual_baseline_preview_without_trial(self):
        for role in ('Rank', 'Invest', 'Prove first'):
            with self.subTest(role=role):
                row, data = fixture()
                row['role'] = role
                row['rank_investment_existing'] = False
                result = review(row, data)
                self.assertEqual(result['reason_code'], 'new_rank_preview_permitted')
                self.assertFalse(result['protect_baseline'])
                self.assertIsNone(result['proposal'])

    def test_new_rank_missing_context_still_protected(self):
        row, data = fixture()
        row['role'] = 'Rank'
        row['rank_investment_existing'] = False
        data['recommendations'] = []
        result = review(row, data)
        self.assertEqual(result['reason_code'], 'rank_recommendation_missing')
        self.assertTrue(result['protect_baseline'])

    def test_healthy_existing_rank_remains_protected(self):
        row, data = fixture()
        row.update(role='Rank', rank_investment_existing=True)
        data['delivery'][0].update(impressions=700, clicks=7, orders=1, spend=1)
        result = review(row, data)
        self.assertEqual(result['status'], 'healthy')
        self.assertTrue(result['protect_baseline'])

    def test_retained_rank_is_protected_when_input_snapshot_is_missing(self):
        row, data = fixture()
        row.update(role='Rank', rank_investment_existing=True)
        self.assertTrue(review(row, {})['protect_baseline'])
        data['inventory'] = []
        self.assertTrue(review(row, data)['protect_baseline'])
        row['rank_investment_existing'] = False
        self.assertFalse(review(row, {})['protect_baseline'])

    def test_healthy_rank_requires_own_recommendation_for_repricing(self):
        row, data = fixture()
        row['role'] = 'Rank'
        data['recommendations'] = []
        data['delivery'][0].update(impressions=700, clicks=7, orders=1, spend=1)
        result = review(row, data)
        self.assertEqual(result['reason_code'], 'rank_recommendation_missing')
        self.assertTrue(result['protect_baseline'])

    def test_healthy_nonrank_not_held_for_missing_recommendation(self):
        row, data = fixture()
        data['recommendations'] = []
        data['delivery'][0].update(impressions=700, clicks=7, orders=1, spend=1)
        result = visibility.build_review(ASIN, [row], {}, data, POLICY, TODAY)
        self.assertEqual(result['rows'][0]['status'], 'healthy')
        self.assertFalse(result['rows'][0]['protect_baseline'])
        self.assertEqual(result['missing_requests'][0]['required'], ['recommendations'])

    def test_healthy_and_trim_retain_contextual_range(self):
        for role in ('Discovery', 'Trim'):
            with self.subTest(role=role):
                row, data = fixture()
                row['role'] = role
                data['delivery'][0].update(impressions=700, clicks=7, orders=1, spend=1)
                self.assertEqual(review(row, data)['suggested']['low'], .73)

    def test_leave_negate_and_audience_never_rescued(self):
        for role in ('Leave', 'Negate', 'Unknown'):
            with self.subTest(role=role):
                row, data = fixture()
                row['role'] = role
                self.assertEqual(review(row, data)['reason_code'], 'role_not_eligible_for_rescue')
        row['role'] = 'Discovery'
        row['family'] = 'Audience (low bids)'
        self.assertEqual(review(row, data)['reason_code'], 'role_not_eligible_for_rescue')

    def test_discovery_preview_requires_query_mix_review(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        del data['inventory'][0]['query_mix_review']
        result = review(row, data)
        self.assertEqual(result['status'], 'needs_bounds')
        self.assertIn('query_mix_review', result['proposal']['missing_fields'])
        self.assertIn('prefer_exact_query_validation', result['flags'])

    def test_exhaustion_has_priority_over_serving_blockers(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'low')]
        data['experiments'][0]['loss_to_date'] = 8
        data['inventory'][0]['gates']['campaign_enabled'] = False
        self.assertEqual(review(row, data)['reason_code'], 'experiment_allowance_exhausted')
        data['inventory'] = []
        self.assertEqual(review(row, data)['reason_code'], 'experiment_allowance_exhausted')

    def test_stage_history_cannot_use_pre_activation_delivery(self):
        row, data = fixture()
        data['experiments'] = [experiment('active', 'low')]
        data['inventory'][0]['current_bid'] = .73
        data['experiments'][0]['stage_started_on'] = '2026-10-18'
        self.assertEqual(review(row, data)['reason_code'], 'stage_window_unverified')
        del data['experiments'][0]['stage_started_on']
        self.assertEqual(review(row, data)['reason_code'], 'stage_window_unverified')

    def test_malformed_optional_collections_do_not_crash(self):
        for field in ('inventory', 'delivery', 'recommendations', 'experiments'):
            with self.subTest(field=field):
                row, data = fixture()
                data[field] = None
                result = review(row, data)
                self.assertFalse((result.get('proposal') or {}).get('executable', False))
        for field in ('gates', 'demand', 'query_mix_review'):
            with self.subTest(field=field):
                row, data = fixture()
                data['inventory'][0][field] = ['invalid']
                self.assertNotEqual(review(row, data)['status'], 'candidate')

    def test_proposed_experiment_invalid_counters_do_not_crash(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        data['experiments'][0]['spend_to_date'] = 'unknown'
        result = review(row, data)
        self.assertEqual(result['status'], 'needs_bounds')
        self.assertIn('spend_to_date', result['proposal']['missing_fields'])

    def test_pending_experiment_cannot_discard_prior_spend(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        data['experiments'][0]['spend_to_date'] = 16
        self.assertEqual(review(row, data)['reason_code'], 'experiment_allowance_exhausted')

    def test_malformed_experiment_state_is_not_trusted(self):
        row, data = fixture()
        data['experiments'] = [experiment()]
        data['experiments'][0]['state'] = ['active']
        result = review(row, data)
        self.assertEqual(result['status'], 'needs_bounds')
        self.assertIn('state', result['proposal']['missing_fields'])

    def test_live_exposure_ceiling_checked_before_review_date(self):
        for current_bid, multiplier in ((1.2, 1), (.6, 2)):
            with self.subTest(current_bid=current_bid, multiplier=multiplier):
                row, data = fixture()
                data['experiments'] = [experiment('active', 'low')]
                data['experiments'][0]['review_on'] = '2026-10-20'
                data['inventory'][0].update(current_bid=current_bid, effective_bid_multiplier=multiplier)
                self.assertEqual(review(row, data)['reason_code'], 'live_experiment_bid_ceiling')

    def test_active_exposure_must_be_known_before_waiting_or_healthy(self):
        for review_on in (TODAY, '2026-10-20'):
            with self.subTest(review_on=review_on):
                row, data = fixture()
                data['experiments'] = [experiment('active', 'low')]
                data['experiments'][0]['review_on'] = review_on
                del data['inventory'][0]['effective_bid_multiplier']
                data['delivery'][0].update(impressions=700, clicks=7, orders=1, spend=1)
                result = review(row, data)
                self.assertEqual(result['reason_code'], 'effective_exposure_unknown')
                self.assertTrue(result['protect_baseline'])


if __name__ == '__main__':
    unittest.main()
