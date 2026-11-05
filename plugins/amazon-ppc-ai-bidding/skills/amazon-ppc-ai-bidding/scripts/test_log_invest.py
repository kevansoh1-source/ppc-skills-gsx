"""log_invest.py: what went live starts (or keeps) a search's invest clock, and nothing else does (B7, I8).

Each test plans the synthetic run test_plan_lanes builds (shadow), then runs log_invest's main() on it with or without
<run>/payloads/applied_rows.json, the record `dashboard.py applied` keeps of every row that went out. The business invest
log's tests plan test_business_roles' run instead (its B2B campaigns and business search records).
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

import log_invest
import plan as planner
import test_business as B
import test_business_roles as R
import test_plan_lanes as T

ASIN = T.ASIN
BUNDLE = ['New exact campaign:::blank cards', 'Pause keyword:2', 'Negative exact:101:201:blank cards',
          'Negative exact:102:202:blank cards']


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)


class LogInvestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = os.path.join(tmp.name, 'run')
        self.data = os.path.join(tmp.name, 'data')
        self.product_file = os.path.join(self.data, 'asins', f'{ASIN}.json')

    def plan(self, **product_over):
        T.make_run(self.run_dir)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False), **product_over))
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.without_mid():
            planner.main()
        return read_json(os.path.join(self.run_dir, 'plan.json'))

    def log(self, applied=None, date='2026-10-20', went=None):
        """log_invest's main(); `applied` row_ids are recorded as gone out on `went` (default: `date`) from approved/."""
        if applied is not None:
            write_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'),
                       {rid: dict(date=went or date, folder='approved') for rid in applied})
        argv = ['log_invest.py', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--date', date]
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(out):
            log_invest.main()
        self.printed = json.loads(out.getvalue())
        return read_json(self.product_file)

    def test_a_gain_at_a_stop_loss_checkpoint_is_kept_for_the_next(self):
        """Decision 142: a search that passes a checkpoint (month 3 here, day 110) with an organic gain keeps that reading,
        and the next checkpoint (month 6) judges it against it. A measure unread today keeps the base it was judged on."""
        write_json(os.path.join(self.run_dir, 'radar_p1.json'), dict(keywords=[
            dict(keyword='thank you cards', ranks=[dict(date=d, organicRank=r) for d, r in
                                                   (('2026-10-15', 22), ('2026-10-17', 20), ('2026-10-18', 18))])]))
        self.plan(invest_log={'thank you cards': dict(since='2026-07-01', role='Invest', rank_then=40)})
        entry = self.log()['invest_log']['thank you cards']
        self.assertEqual({k: entry.get(k) for k in ('since', 'checkpoint', 'checkpoint_rank', 'checkpoint_organic', 'checkpoint_on')},
                         dict(since='2026-07-01', checkpoint=3, checkpoint_rank=20, checkpoint_organic=0,
                              checkpoint_on='2026-10-20'))
        self.assertIn('thank you cards: passed its month 3 stop-loss checkpoint (organic rank 40 -> 20)', self.printed['changes'])

    def test_a_lanes_run_without_the_applied_record_starts_no_clock(self):
        """C7 (I8, the re-review's probe): a week where nothing went out has no applied_rows.json. A plan made with the
        lanes then counts nothing as gone out: the promotion (blank cards) and the re-price waiting for a person (thank you
        cards) start no clock."""
        self.plan()
        product = self.log()
        self.assertEqual(product['invest_log'], {})
        self.assertIs(self.printed['applied_record'], False)
        self.assertIn('blank cards: not started, its change has not gone out', self.printed['changes'])

    def test_an_older_run_without_the_applied_record_starts_every_invest_search_as_today(self):
        plan = self.plan()
        del plan['summary'][0]['lanes']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log()
        self.assertEqual({t: e['since'] for t, e in product['invest_log'].items()},
                         {'blank cards': '2026-10-20', 'thank you cards': '2026-10-20'})

    def test_a_promotion_starts_its_clock_on_the_day_it_went_out(self):
        """N8: last week's promotion was approved, then applied and recorded at the start of this week (2026-10-26); its
        clock starts that day, whatever --date log_invest is given."""
        self.plan()
        product = self.log(applied=BUNDLE, date='2026-10-27', went='2026-10-26')
        self.assertEqual(product['invest_log']['blank cards']['since'], '2026-10-26')
        self.assertIn('blank cards: started Invest on 2026-10-26', ' '.join(self.printed['changes']))

    def test_the_older_record_shape_is_read_too(self):
        self.plan()
        write_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'), {rid: '2026-10-19' for rid in BUNDLE})
        product = self.log(date='2026-10-20')
        self.assertEqual(product['invest_log']['blank cards']['since'], '2026-10-19')

    def test_a_promotion_that_has_not_gone_out_starts_no_clock(self):
        self.plan()
        product = self.log(applied=[])
        self.assertEqual(product['invest_log'], {})
        self.assertIn('blank cards: not started, its change has not gone out', self.printed['changes'])

    def test_only_the_applied_promotion_starts_its_clock(self):
        self.plan()
        product = self.log(applied=BUNDLE)
        self.assertEqual(list(product['invest_log']), ['blank cards'])
        self.assertEqual((product['invest_log']['blank cards']['since'], product['invest_log']['blank cards']['role']),
                         ('2026-10-20', 'Invest'))
        # thank you cards' re-price (Bid change:1) is waiting for a person: its clock doesn't start either
        self.assertNotIn('thank you cards', product['invest_log'])

    def test_a_logged_search_keeps_its_clock_while_its_change_waits(self):
        since = dict(since='2026-07-01', role='Invest', index_then=1.2)
        self.plan(invest_log={'thank you cards': since})
        product = self.log(applied=[])
        self.assertEqual(product['invest_log']['thank you cards'], since)  # its campaign is still live: the clock runs on
        self.assertEqual(product.get('invest_history'), [])

    def test_a_logged_search_leaves_the_log_only_once_its_step_down_went_out(self):
        gold = dict(since='2026-07-01', role='Invest')
        self.plan(invest_log={'gold cards': gold})  # gold cards trails the market now: the plan cuts it (Bid change:3)
        product = self.log(applied=[])
        self.assertEqual(product['invest_log'].get('gold cards'), gold)
        product = self.log(applied=['Bid change:3'])
        self.assertNotIn('gold cards', product['invest_log'])
        self.assertEqual([h['search'] for h in product['invest_history']], ['gold cards'])
        # G1: the cut is the E1 row (invested_search), sent by a person from approved/, so it is the step-down on record
        self.assertEqual(product['invest_history'][0]['stepped_down'],
                         'Bid change:3 (a cut on the invested search) went out on 2026-10-20 from payloads/approved/')

    # --- G1 (N1): a logged search leaves the log only by a person's step-down on record ---------------------------------
    def without_the_cut(self, plan):
        """The plan with gold cards' cut taken out (its bid already sits at the step-down's price), so its only row is the
        stop-loss review, which has no payload."""
        plan['changes'] = [c for c in plan['changes'] if c['row_id'] != 'Bid change:3']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        return next(c['row_id'] for c in plan['changes'] if c['type'] == 'Stop-loss review' and c['keyword'] == 'gold cards')

    def approved_record(self, record):
        write_json(os.path.join(self.run_dir, 'payloads', 'approved_decisions.json'), record)

    def test_a_logged_search_with_nobody_deciding_stays_in_the_log(self):
        """The re-review's probe (N1): gold cards is logged, no longer a rank search, and its only row is a stop-loss review.
        Nobody decided anything, so it stays in the log (E1 keeps protecting it, and its spend stays in Kim's total)."""
        gold = dict(since='2026-07-01', role='Invest')
        self.without_the_cut(self.plan(invest_log={'gold cards': gold}))
        for applied in (None, []):
            with self.subTest(applied=applied):
                product = self.log(applied=applied)
                self.assertEqual(product['invest_log'].get('gold cards'), gold)
                self.assertEqual(product.get('invest_history'), [])
                self.assertIn('gold cards: not a rank term this run; kept until the stop-loss review decides',
                              self.printed['changes'])

    def test_an_approved_stop_loss_review_moves_the_search_to_its_history(self):
        """The run's approved decisions (payloads/approved_decisions.json, which approvals writes) hold the stop-loss review
        approved: that is the person's step-down, so the search leaves the log, and its history says who decided it."""
        gold = dict(since='2026-07-01', role='Invest')
        stop = self.without_the_cut(self.plan(invest_log={'gold cards': gold}))
        self.approved_record({stop: dict(by='Lee', on='2026-10-20', at='2026-10-20T02:00:00Z')})
        product = self.log()
        self.assertNotIn('gold cards', product['invest_log'])
        [ended] = product['invest_history']
        self.assertEqual((ended['search'], ended['ended'], ended['since']), ('gold cards', '2026-10-20', '2026-07-01'))
        self.assertEqual(ended['stepped_down'], 'the stop-loss review was approved by Lee on 2026-10-20')
        self.assertIn('gold cards: no longer invested (moved to invest_history: the stop-loss review was approved by Lee '
                      'on 2026-10-20)', self.printed['changes'])

    def test_only_a_stop_loss_review_of_that_search_counts_as_its_step_down(self):
        gold = dict(since='2026-07-01', role='Invest')
        stop = self.without_the_cut(self.plan(invest_log={'gold cards': gold}))
        self.approved_record({'Bid change:4': dict(by='Lee', on='2026-10-20'),  # an approved row on another search
                              'Stop-loss review:::blank cards': dict(by='Lee', on='2026-10-20')})  # not in this plan
        self.assertEqual(self.log()['invest_log'].get('gold cards'), gold)
        self.approved_record({stop: 'not a record'})  # an entry that doesn't say who approved it
        self.assertEqual(self.log()['invest_log'].get('gold cards'), gold)

    def test_a_cut_that_goes_out_without_the_invested_flag_is_not_a_step_down(self):
        """A recorded cut is a person's step-down only when it is the E1 row, a cut or pause on the invested search
        (invested_search), which only a person can send. Without the flag the search stays."""
        gold = dict(since='2026-07-01', role='Invest')
        plan = self.plan(invest_log={'gold cards': gold})
        for c in plan['changes']:
            c.pop('invested_search', None)
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        self.assertEqual(self.log(applied=['Bid change:3'])['invest_log'].get('gold cards'), gold)

    def test_an_automatic_cut_is_not_a_step_down(self):
        """A recorded row from payloads/auto/ (or an older record that doesn't say its folder) is no person's decision."""
        gold = dict(since='2026-07-01', role='Invest')
        self.plan(invest_log={'gold cards': gold})
        path = os.path.join(self.run_dir, 'payloads', 'applied_rows.json')
        for record in ({'Bid change:3': dict(date='2026-10-20', folder='auto')}, {'Bid change:3': '2026-10-20'}):
            with self.subTest(record=record):
                write_json(path, record)
                self.assertEqual(self.log()['invest_log'].get('gold cards'), gold)

    def test_an_older_run_still_moves_a_search_it_no_longer_invests_in(self):
        """Runs planned before the lanes keep today's behaviour: a logged search the run doesn't invest in leaves the log."""
        self.without_the_cut(self.plan(invest_log={'gold cards': dict(since='2026-07-01', role='Invest')}))
        plan = read_json(os.path.join(self.run_dir, 'plan.json'))
        del plan['summary'][0]['lanes']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log()
        self.assertNotIn('gold cards', product['invest_log'])
        self.assertEqual([h['search'] for h in product['invest_history']], ['gold cards'])

    def test_missing_sp_row_is_not_proof_that_a_rank_search_is_live(self):
        plan = self.plan()
        plan['changes'] = [c for c in plan['changes'] if c['row_id'] != 'Bid change:1']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log(applied=[])
        self.assertEqual(product['invest_log'], {})

    def test_explicit_consumer_live_owner_can_start_a_no_row_clock(self):
        plan = self.plan()
        plan['changes'] = [c for c in plan['changes'] if c['row_id'] != 'Bid change:1']
        plan['consumer_live_invests'] = [dict(keyword='thank you cards', role='Invest', campaign_id='101')]
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log(applied=[], date='2026-10-21')
        self.assertEqual(list(product['invest_log']), ['thank you cards'])
        self.assertEqual(product['invest_log']['thank you cards']['since'], '2026-10-21')

    def test_existing_no_row_consumer_clock_keeps_its_date_and_baseline(self):
        entry = dict(since='2026-07-01', role='Invest', rank_then=42, index_then=1.3)
        plan = self.plan(invest_log={'thank you cards': entry})
        plan['changes'] = [c for c in plan['changes'] if c['row_id'] != 'Bid change:1']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log(applied=[])
        self.assertEqual(product['invest_log']['thank you cards'], entry)

    def test_si_only_applied_ledger_starts_neither_consumer_nor_business_clock(self):
        plan = self.plan_business()
        # Onboarding can complete SI setup while visibility suppresses every SP promotion.
        si = dict(type='Scale Insights rules', row_id='Scale Insights rules:::handoff', keyword='', role='')
        plan['changes'] = [si]
        plan['business_live_invests'] = []
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log(applied=[si['row_id']])
        self.assertEqual(product['invest_log'], {})
        self.assertEqual(product.get('business_invest_log', {}), {})

    def test_applied_sb_creation_without_sp_promotion_starts_no_clock(self):
        plan = self.plan()
        # An SB campaign can be created (and still await moderation) with no live SP owner.
        sb = dict(type='New SB video campaign', row_id='New SB video campaign:::thank you cards',
                  keyword='thank you cards', role='Invest', campaign='test SB', new=0.67, budget=10)
        plan['changes'] = [sb]
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log(applied=[sb['row_id']])
        self.assertEqual(product['invest_log'], {})

    def test_pending_sp_promotion_overrides_live_owner_evidence(self):
        plan = self.plan()
        plan['consumer_live_invests'] = [dict(keyword='thank you cards', role='Invest', campaign_id='101')]
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        self.assertEqual(self.log(applied=[])['invest_log'], {})

    def test_mixed_sb_and_sp_execution_starts_only_the_sp_clock(self):
        plan = self.plan()
        plan['changes'] = [c for c in plan['changes'] if c['row_id'] != 'Bid change:1']
        sb = dict(type='New SB video campaign', row_id='New SB video campaign:::thank you cards',
                  keyword='thank you cards', role='Invest', campaign='test SB', new=0.67, budget=10)
        plan['changes'].append(sb)
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        product = self.log(applied=BUNDLE + [sb['row_id']], date='2026-10-23', went='2026-10-21')
        self.assertEqual(list(product['invest_log']), ['blank cards'])
        self.assertEqual(product['invest_log']['blank cards']['since'], '2026-10-21')

    # --- the business invest log (design 2026-10-21-b2b-lane-and-roles 4f): its own log, never invest_log ---------------
    def plan_business(self, keywords=R.KEYWORDS, campaigns=R.CAMPAIGNS, extra=None, **product_over):
        """Plan test_business_roles' fixture (B2B campaigns: zebra cards a business Invest owned by 902 in campaign 108, 25
        B2B clicks and 7 orders; office cards a New exact keyword in 110) into plan.json, as main() writes it. `extra` adds
        run files."""
        T.make_run(self.run_dir, extra=dict({'suggested_bids_business.json': R.SUGGESTED_B}, **(extra or {})), queries=R.QUERIES,
                   search_terms=R.SEARCH_TERMS, keywords=keywords, more_campaigns=campaigns, suggested=R.SUGGESTED)
        cfg = R.product(auto=dict(T.AUTO, enabled=False), **product_over)
        write_json(self.product_file, cfg)
        out = planner.build(ASIN, cfg, R.shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        planner.write_outputs(self.run_dir, out, R.shared(), ASIN)
        return read_json(os.path.join(self.run_dir, 'plan.json'))

    def row_id(self, plan, ctype, keyword, **match):
        return next(c['row_id'] for c in plan['changes'] if c['type'] == ctype and c.get('keyword') == keyword
                    and all(c.get(k) == v for k, v in match.items()))

    def test_a_business_invest_goes_to_the_business_log(self):
        plan = self.plan_business()
        invest = self.row_id(plan, 'Business invest', 'zebra cards')
        product = self.log(applied=[invest])
        entry = product['business_invest_log']['zebra cards']
        self.assertEqual({k: entry[k] for k in ('since', 'role', 'orders_then', 'clicks_then', 'owner_kind', 'campaign_id')},
                         dict(since='2026-10-20', role='Invest', orders_then=7, clicks_then=25, owner_kind='business',
                              campaign_id='108'))
        self.assertEqual((entry['spend_then'], entry['sales_then']), (28, 70))
        self.assertGreater(entry['index_then'], 1.1)
        self.assertNotIn('zebra cards', product.get('invest_log', {}))
        self.assertIn('zebra cards (B2B): started Invest on 2026-10-20', ' '.join(self.printed['changes']))
        # the consumer promotion of the same search hasn't gone out: its clock doesn't start, the business one's runs on
        self.assertIn('zebra cards: not started, its change has not gone out', self.printed['changes'])
        # office cards' New exact keyword hasn't gone out either: nothing starts for it
        self.assertNotIn('office cards', product['business_invest_log'])
        self.assertIn('office cards (B2B): not started, its change has not gone out', self.printed['changes'])

    def test_a_consumer_promotion_never_reaches_the_business_log(self):
        plan = self.plan_business()
        bundle = [c['row_id'] for c in plan['changes'] if c.get('keyword') == 'zebra cards' and c.get('owner_kind') != 'business']
        product = self.log(applied=bundle)
        self.assertEqual(product['invest_log']['zebra cards']['role'], 'Invest')
        self.assertNotIn('owner_kind', product['invest_log']['zebra cards'])
        self.assertEqual(product.get('business_invest_log', {}), {})

    def test_a_product_without_business_invests_gets_no_business_log(self):
        self.plan()
        product = self.log(applied=BUNDLE)
        self.assertNotIn('business_invest_log', product)
        self.assertNotIn('business_invest_history', product)

    def test_a_business_owner_already_invested_as_planned_still_counts(self):
        """902 already sits at its invest bid in campaign 108, which runs the policy's +50% and $10: no row
        (plan['business_live_invests']), so its clock starts on --date, as a consumer rank search's whose campaign needed no
        change does."""
        kws = [k for k in R.KEYWORDS if k['KeywordId'] != '902'] + [T.keyword('902', 'zebra cards', 'exact', B.B2B_EXACT, 1.20, 20, 6, 24)]
        camps = [c for c in R.CAMPAIGNS if c['name'] != B.B2B_EXACT] + [dict(T.campaign(B.B2B_EXACT, tos=50),
                                                                           siteRestrictions=['AMAZON_BUSINESS'])]
        plan = self.plan_business(keywords=kws, campaigns=camps)
        self.assertEqual([x['keyword'] for x in plan['business_live_invests']], ['zebra cards'])
        self.assertFalse([c for c in plan['changes'] if c['type'] == 'Business invest'])
        product = self.log(applied=[], date='2026-10-21')
        entry = product['business_invest_log']['zebra cards']
        self.assertEqual((entry['since'], entry['role'], entry['orders_then']), ('2026-10-21', 'Invest', 7))
        self.assertNotIn('zebra cards', product['invest_log'])

    def test_a_business_search_leaves_its_log_only_on_its_own_step_down(self):
        """G1 for the business log: gold cards is in both logs and is no rank search of either kind this run. Since
        autonomous runs (2026-10-22) its business stop-loss is a step-down the planner writes (stop_loss.py): its owner
        keyword 907's cut is marked as the step-down. That going out moves the business entry to business_invest_history and
        leaves the consumer entry; the consumer review (no exact SKC keyword in this fixture, so a person's) approved does
        the reverse. Nothing recorded keeps both."""
        gold = dict(since='2026-07-01', role='Invest')
        bgold = dict(gold, orders_then=0, owner_kind='business', campaign_id='108')
        plan = self.plan_business(invest_log={'gold cards': gold}, business_invest_log={'gold cards': bgold})
        # the consumer cut (Bid change:3, an E1 row) is taken out: the consumer's only row is its stop-loss review
        plan['changes'] = [c for c in plan['changes'] if c['row_id'] != 'Bid change:3']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        consumer = self.row_id(plan, 'Stop-loss review', 'gold cards', owner_kind=None)
        step = next(c for c in plan['changes'] if c['row_id'] == 'Bid change:907')
        self.assertEqual((step.get('owner_kind'), step.get('stop_loss_step_down'), step['lane']), ('business', True, 'auto'))
        self.assertFalse([c for c in plan['changes'] if c['type'] == 'Stop-loss review' and c.get('owner_kind') == 'business'])
        product = self.log()
        self.assertEqual((product['invest_log'].get('gold cards'), product['business_invest_log'].get('gold cards')), (gold, bgold))
        self.assertIn('gold cards (B2B): kept as it was, its change this run has not gone out', self.printed['changes'])
        product = self.log(applied=['Bid change:907'])
        self.assertEqual(product['invest_log'].get('gold cards'), gold)
        self.assertNotIn('gold cards', product['business_invest_log'])
        [ended] = product['business_invest_history']
        self.assertEqual((ended['search'], ended['ended'], ended['since'], ended['owner_kind']),
                         ('gold cards', '2026-10-20', '2026-07-01', 'business'))
        self.assertEqual(ended['stepped_down'], 'the stop-loss step-down Bid change:907 went out on 2026-10-20 from payloads/approved/ (invested in the B2B campaign for 110 days (15 weeks): B2B orders 0 -> 0, ACOS unknown (no B2B sales) against the 50% breakeven)')
        self.assertEqual(product['invest_history'], [])
        write_json(self.product_file, dict(read_json(self.product_file), business_invest_log={'gold cards': bgold},
                                           business_invest_history=[]))
        os.remove(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'))
        self.approved_record({consumer: dict(by='Lee', on='2026-10-20')})
        product = self.log()
        self.assertNotIn('gold cards', product['invest_log'])
        self.assertEqual(product['business_invest_log'].get('gold cards'), bgold)
        self.assertEqual(product['business_invest_history'], [])

    def test_a_business_cut_that_went_out_steps_down_the_business_search_only(self):
        gold = dict(since='2026-07-01', role='Invest')
        bgold = dict(gold, orders_then=0, owner_kind='business')
        self.plan_business(invest_log={'gold cards': gold}, business_invest_log={'gold cards': bgold})
        product = self.log(applied=['Bid change:907'])
        self.assertNotIn('gold cards', product['business_invest_log'])
        # the cut on 907 is also gold cards' business stop-loss step-down (6 weeks, no B2B orders): it says so
        self.assertEqual(product['business_invest_history'][0]['stepped_down'], 'the stop-loss step-down Bid change:907 went out on 2026-10-20 from payloads/approved/ (invested in the B2B campaign for 110 days (15 weeks): B2B orders 0 -> 0, ACOS unknown (no B2B sales) against the 50% breakeven)')
        self.assertEqual(product['invest_log'].get('gold cards'), gold)   # the consumer cut (Bid change:3) is still waiting

    def test_a_plain_invested_cut_from_auto_does_not_end_the_invest(self):
        """An invested cut (E1) that went out from auto/ is not a step-down (autonomous runs, 2026-10-22): the search stays
        logged and its stop-loss decides. From approved/ or review/ (a person's) it steps the search down, as before."""
        gold = dict(since='2026-10-10', role='Invest')   # 10 days: no stop-loss yet
        plan = self.plan_business(invest_log={'gold cards': gold})
        cut = next(c for c in plan['changes'] if c['row_id'] == 'Bid change:3')
        self.assertIs(cut.get('invested_search'), True)
        self.assertFalse(cut.get('stop_loss_step_down'))
        write_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'),
                   {'Bid change:3': dict(date='2026-10-20', folder='auto')})
        argv = ['log_invest.py', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--date', '2026-10-20']
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(out):
            log_invest.main()
        self.assertEqual(read_json(self.product_file)['invest_log'].get('gold cards'), gold)

    def test_a_waiting_business_row_never_keeps_a_consumer_step_down(self):        # ruling 13 (spec 9b)
        """zebra cards is in the consumer invest log and no consumer rank search this run, its consumer stop-loss review
        approved; the Business invest of zebra cards waits unapproved. That business change is another campaign: it no
        longer keeps the consumer entry "as it was", so the consumer step-down goes through (the waiting set is per kind,
        as the business one already was)."""
        since = dict(since='2026-07-01', role='Invest')
        plan = self.plan_business(invest_log={'zebra cards': since})
        plan['changes'] = [c for c in plan['changes'] if c.get('keyword') != 'zebra cards' or c.get('owner_kind') == 'business'
                           or c['type'] == 'Stop-loss review']
        for t in plan['terms']:
            if t['term'] == 'zebra cards':
                t['role'] = 'Hold'   # no consumer rank search this run
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        invest = self.row_id(plan, 'Business invest', 'zebra cards')
        review = self.row_id(plan, 'Stop-loss review', 'zebra cards', owner_kind=None)
        self.approved_record({review: dict(by='Lee', on='2026-10-20')})
        product = self.log(applied=[])
        self.assertNotIn('zebra cards', product['invest_log'])
        [ended] = product['invest_history']
        self.assertEqual((ended['search'], ended['stepped_down']),
                         ('zebra cards', 'the stop-loss review was approved by Lee on 2026-10-20'))
        self.assertNotIn('zebra cards: kept as it was, its change this run has not gone out', self.printed['changes'])
        # the business invest itself still waits: nothing starts in the business log
        self.assertNotIn(invest, read_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
        self.assertIn('zebra cards (B2B): not started, its change has not gone out', self.printed['changes'])

    def test_a_visibility_blocked_business_owner_does_not_start_a_clock(self):
        """A candidate owner's ID is not proof of live investment when a negative blocks its promotion."""
        # a check that came back "no" (a negative in the way) holds the owner: since decision 107 (2026-10-23) a check that
        # couldn't be answered (its live strategy unread) holds nothing
        inventory = dict(asin=ASIN, keyword_id='902', ad_product='SP', match='exact', campaign_id='108', ad_group_id='208',
                         keyword='zebra cards', observed_on=T.TODAY, current_bid=1.05, strategy='LEGACY_FOR_SALES',
                         gates=dict(campaign_enabled=True, ad_group_enabled=True, target_enabled=True, negatives_clear=False))
        plan = self.plan_business(extra={'visibility_inputs.json': dict(asin=ASIN, inventory_complete=True, inventory=[inventory],
                                                                        delivery=[], recommendations=[], experiments=[])})
        self.assertFalse([c for c in plan['changes'] if c['type'] == 'Business invest'])
        self.assertEqual(plan['business_live_invests'], [])
        self.assertIn(dict(keyword='zebra cards', keyword_id='902', campaign_id='108', ad_group_id='208'), plan['business_owners'])
        product = self.log(applied=[], date='2026-10-21')
        self.assertNotIn('zebra cards', product.get('business_invest_log', {}))

    # --- one start/keep/end loop for both logs (plan 2026-10-22-business-module, Task 2) ---------------------------------
    def test_mixed_plan_changed_messages_order(self):                       # Review Focus 4
        """The consumer and business logs run through one loop: what it prints, in its order, and what it writes are
        today's, pinned as literals captured before the fold (9157157). The plan has a consumer and a business invest of
        zebra cards that went out, and logged searches of both kinds that change role, wait, end or stay."""
        gold = dict(since='2026-07-01', role='Invest')
        bgold = dict(gold, orders_then=0, owner_kind='business')
        plan = self.plan_business(
            invest_log={'thank you cards': dict(since='2026-07-01', role='Prove first'), 'gold cards': dict(gold),
                        'birthday cards': dict(gold), 'random search': dict(gold)},
            business_invest_log={'gold cards': dict(bgold, campaign_id='108'), 'random search': dict(bgold),
                                 'blank cards': dict(bgold, orders_then=3)})
        write_json(os.path.join(self.run_dir, 'radar_p1.json'), dict(keywords=[
            dict(keyword='thank you cards', ranks=[dict(date=d, organicRank=r) for d, r in
                                                   (('2026-07-02', 30), ('2026-07-05', 20), ('2026-07-20', 9))]),
            dict(keyword='zebra cards', ranks=[dict(date=d, organicRank=r) for d, r in
                                               (('2026-10-14', 41), ('2026-10-16', 37), ('2026-10-19', 33))])]))
        applied = ['New exact campaign:::zebra cards', 'Bid change:3', 'Bid change:907',
                   self.row_id(plan, 'Business invest', 'zebra cards')]
        product = self.log(applied=applied)
        self.assertEqual(self.printed['changes'], [
            'blank cards: not started, its change has not gone out',
            'office cards: not started, its change has not gone out',
            'thank you cards: Prove first -> Invest (since 2026-07-01 kept)',
            'thank you cards: rank baseline backfilled (25.0) from Rank Radar, first two weeks after 2026-07-01',
            'zebra cards: started Invest on 2026-10-20 (rank 37, impression share 0.01)',
            'gold cards: no longer invested (moved to invest_history: Bid change:3 (a cut on the invested search) went out '
            'on 2026-10-20 from payloads/approved/)',
            'birthday cards: kept as it was, its change this run has not gone out',
            'random search: not a rank term this run; kept until the stop-loss review decides',
            'office cards (B2B): not started, its change has not gone out',
            'zebra cards (B2B): started Invest on 2026-10-20 (7 B2B orders on 25 B2B clicks)',
            'gold cards (B2B): no longer invested (moved to business_invest_history: the stop-loss step-down Bid change:907 '
            'went out on 2026-10-20 from payloads/approved/ (invested in the B2B campaign for 110 days (15 weeks): B2B orders 0 '
            '-> 0, ACOS unknown (no B2B sales) against the 50% breakeven))',   # its business stop-loss step-down (2026-10-22)
            'random search (B2B): not a business rank term this run; kept until the stop-loss review decides',
            'blank cards (B2B): kept as it was, its change this run has not gone out',
            'planned invest $56.33 a month (program total)'])   # the program check's record (autonomous runs)
        self.assertEqual(list(product), ['asin', 'product', 'sku', 'campaign_prefix', 'profit_per_unit', 'registry', 'auto',
                                         'price', 'invest_log', 'business_invest_log', 'invest_history',
                                         'business_invest_history', 'planned_invest', 'last_run'])
        self.assertEqual(json.dumps(product['invest_log']), json.dumps({
            'thank you cards': dict(since='2026-07-01', role='Invest', rank_then=25.0), 'birthday cards': gold,
            'random search': gold, 'zebra cards': dict(since='2026-10-20', role='Invest', index_then=2.0, imp_share_then=0.01,
                                                       organic_then=0, rank_then=37)}))
        stepped = 'Bid change:{} (a cut on the invested search) went out on 2026-10-20 from payloads/approved/'
        self.assertEqual(json.dumps(product['invest_history']), json.dumps([
            dict(search='gold cards', ended='2026-10-20', since='2026-07-01', role='Invest', stepped_down=stepped.format(3))]))
        self.assertEqual(json.dumps(product['business_invest_log']), json.dumps({
            'random search': bgold, 'blank cards': dict(bgold, orders_then=3),
            'zebra cards': dict(since='2026-10-20', role='Invest', index_then=2.41, clicks_then=25, orders_then=7,
                                spend_then=28.0, sales_then=70.0, owner_kind='business', campaign_id='108')}))
        self.assertEqual(json.dumps(product['business_invest_history']), json.dumps([
            dict(search='gold cards', ended='2026-10-20', since='2026-07-01', role='Invest', orders_then=0,
                 owner_kind='business', campaign_id='108', stepped_down='the stop-loss step-down Bid change:907 went out on 2026-10-20 from payloads/approved/ (invested in the B2B campaign for 110 days (15 weeks): B2B orders 0 -> 0, ACOS unknown (no B2B sales) against the 50% breakeven)',
                 stop_loss=True)]))   # the stop-loss ended it: the re-investment cool-off reads this (2026-10-22)

    def test_mixed_plan_business_role_change_message(self):
        """The business role change, after the consumer messages: office cards logged as Prove first, its New exact keyword
        went out as an Invest (captured before the fold, 9157157)."""
        plan = self.plan_business(business_invest_log={'office cards': dict(since='2026-07-01', role='Prove first',
                                                                            orders_then=1, owner_kind='business',
                                                                            campaign_id='110')})
        self.log(applied=[self.row_id(plan, 'New exact keyword', 'office cards', owner_kind='business')])
        self.assertEqual(self.printed['changes'], [
            'blank cards: not started, its change has not gone out',
            'office cards: not started, its change has not gone out',
            'thank you cards: not started, its change has not gone out',
            'zebra cards: not started, its change has not gone out',
            'zebra cards (B2B): not started, its change has not gone out',
            'office cards (B2B): Prove first -> Invest (since 2026-07-01 kept)',
            'planned invest $96.00 a month (program total)'])

    def test_consumer_only_plan_changed_messages_order(self):
        """A product with no B2B campaign: the consumer log's messages in today's order, and no business key written
        (captured before the fold, 9157157)."""
        gold = dict(since='2026-07-01', role='Invest')
        self.plan(invest_log={'gold cards': dict(gold), 'random search': dict(gold),
                              'thank you cards': dict(since='2026-07-01', role='Prove first')})
        product = self.log(applied=BUNDLE + ['Bid change:3'])
        self.assertEqual(self.printed['changes'], [
            'blank cards: started Invest on 2026-10-20 (rank None, impression share 0.01)',
            'thank you cards: Prove first -> Invest (since 2026-07-01 kept)',
            'gold cards: no longer invested (moved to invest_history: Bid change:3 (a cut on the invested search) went out '
            'on 2026-10-20 from payloads/approved/)',
            'random search: not a rank term this run; kept until the stop-loss review decides',
            'planned invest $54.33 a month (program total)'])
        self.assertEqual(list(product), ['asin', 'product', 'sku', 'campaign_prefix', 'profit_per_unit', 'registry', 'auto',
                                         'invest_log', 'invest_history', 'planned_invest', 'last_run'])
        self.assertEqual(product['planned_invest'], dict(month=54.33, as_of='2026-10-20', run='run', basis='plan'))

    def test_an_unreadable_applied_record_stops_it(self):
        self.plan()
        before = read_json(self.product_file)
        path = os.path.join(self.run_dir, 'payloads', 'applied_rows.json')
        for text in ('not json', '[]', '{"Bid change:1": 5}'):
            with self.subTest(text=text):
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(text)
                with self.assertRaises(SystemExit) as cm:
                    self.log()
                self.assertIn('applied_rows.json', str(cm.exception.code))
                self.assertEqual(read_json(self.product_file), before)


if __name__ == '__main__':
    unittest.main()
