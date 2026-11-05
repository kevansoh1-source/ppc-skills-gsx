"""Bid and rank calls are the AI's (Kim, 2026-10-23, decision 107), and the Hold uplift test (decision 108). The lane
rules themselves are in test_lanes.py and test_plan_lanes.py; this file covers the visibility rule (only a check that came
back "no" holds a bid or a rank investment), the paused-only inventory hold, and the Hold +15% price at index 1.0-1.1. It
runs on the lanes fixture (test_plan_lanes)."""
import contextlib
import copy
import io
import json
import os
import unittest
import unittest.mock

import hold_uplift
import plan as planner
import routine
import test_plan_lanes as T
import visibility

INVEST_KEYWORD = '1'   # 'thank you cards' exact in the SKC: an Invest search in the fixture


def live(**gates):
    """The live snapshot of the Invest search's SKC keyword: fresh, its enabled-state read, any other gate as given."""
    cid, ag = T.IDS[T.SKC]
    return dict(asin=T.ASIN, keyword_id=INVEST_KEYWORD, ad_product='SP', match='exact', campaign_id=cid, ad_group_id=ag,
                keyword='thank you cards', observed_on=T.TODAY, current_bid=0.80,
                gates=dict(campaign_enabled=True, ad_group_enabled=True, target_enabled=True, **gates))


class HoldsBidTest(unittest.TestCase):
    def test_only_a_no_or_a_protected_experiment_holds(self):
        self.assertFalse(visibility.holds_bid(None))
        self.assertFalse(visibility.holds_bid(dict(guard_bid_change=False, status='blocked')))
        self.assertTrue(visibility.holds_bid(dict(guard_bid_change=True, status='blocked')))
        self.assertTrue(visibility.holds_bid(dict(guard_bid_change=True, status='active_experiment')))
        self.assertTrue(visibility.holds_bid(dict(guard_bid_change=True)))   # a review that says nothing more holds, as before
        # a check that couldn't be answered holds nothing (decision 107)...
        for status, code in (('missing_data', 'preflight_unknown'), ('missing_data', 'stale_inventory'),
                             ('waiting_data', 'too_few_eligible_days'), ('rank_review', 'rank_recommendation_missing')):
            with self.subTest(status=status, code=code):
                self.assertFalse(visibility.holds_bid(dict(guard_bid_change=True, status=status, reason_code=code)))
        # ...except a tracked experiment, whose history it keeps
        tracked = dict(guard_bid_change=True, status='missing_data', reason_code='stale_inventory', experiment=dict(state='active'))
        self.assertTrue(visibility.holds_bid(tracked))


class PlannerVisibilityTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, inventory):
        snapshot = dict(asin=T.ASIN, inventory_complete=True, inventory=[inventory], delivery=[], recommendations=[], experiments=[])
        T.make_run(self.run_dir, extra={'visibility_inputs.json': snapshot})
        out = planner.build(T.ASIN, T.product(), T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        return out, next(p for p in out['keyword_plan'] if p['keyword_id'] == INVEST_KEYWORD)

    def test_an_unanswered_check_no_longer_defers_a_rank_investment(self):
        # the live bidding strategy wasn't read: until 2026-10-23 that kept the bid "pending visibility review"
        out, row = self.plan(live())
        self.assertFalse(row['action'].startswith('Keep'), row['action'])
        self.assertTrue(row['action'].startswith('Invest: bid to be visible'), row['action'])
        self.assertEqual(out['summary'][0]['rank_reviews_deferred'], 0)
        review = next(r for r in out['visibility_review']['rows'] if r['keyword_id'] == INVEST_KEYWORD)
        self.assertEqual(review['status'], 'missing_data')   # the gap is still recorded

    def test_a_check_that_says_no_still_holds_it(self):
        out, row = self.plan(dict(live(negatives_clear=False), strategy='LEGACY_FOR_SALES'))
        self.assertTrue(row['action'].startswith('Keep pending visibility review'), row['action'])
        self.assertEqual(out['summary'][0]['rank_reviews_deferred'], 1)

    def test_only_a_paused_keyword_is_an_inventory_hold(self):
        _, row = self.plan(dict(live(), observed_on='2026-09-01'))   # a stale snapshot: noted, not a hold
        self.assertFalse(row['action'].startswith('Keep:'), row['action'])
        paused = live()
        paused['gates']['target_enabled'] = False
        _, row = self.plan(paused)
        self.assertEqual(row['action'], 'Keep: its campaign, ad group or keyword is paused')

    def test_a_paused_copy_does_not_hold_a_live_rank_search(self):
        # decision 154 (2026-10-27): a paused exact copy of the invest search, beside its live SKC keyword, is kept as it
        # is, and the search still invests through the live one
        cid, ag = T.IDS[T.STW]
        paused_copy = dict(asin=T.ASIN, keyword_id='99', ad_product='SP', match='exact', campaign_id=cid, ad_group_id=ag,
                           keyword='thank you cards', observed_on=T.TODAY, current_bid=0.30,
                           gates=dict(campaign_enabled=True, ad_group_enabled=True, target_enabled=False))
        snapshot = dict(asin=T.ASIN, inventory_complete=True, inventory=[live(), paused_copy], delivery=[], recommendations=[],
                        experiments=[])
        T.make_run(self.run_dir, extra={'visibility_inputs.json': snapshot})
        out = planner.build(T.ASIN, T.product(), T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        rows = {p['keyword_id']: p for p in out['keyword_plan']}
        self.assertEqual(rows['99']['action'], 'Keep: its campaign, ad group or keyword is paused')
        self.assertTrue(rows[INVEST_KEYWORD]['action'].startswith('Invest: bid to be visible'), rows[INVEST_KEYWORD]['action'])
        self.assertEqual(out['summary'][0]['rank_reviews_deferred'], 0)


class HoldUpliftTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, gold):
        shared = T.shared_config()
        # on, as it was live from 2026-10-23 (decision 108) until Kim ended it on 2026-10-25 (decision 135): the machinery
        # stays for a re-run of the test
        shared['hold_uplift'] = dict(copy.deepcopy(T.CONFIG['hold_uplift']), enabled=True)
        queries = [q for q in T.QUERIES if q['Query'] != 'gold cards'] + [gold]
        T.make_run(self.run_dir, queries=queries)
        out = planner.build(T.ASIN, T.product(), shared, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        term = next(t for t in out['terms'] if t['term'] == 'gold cards')
        return out, term

    def test_a_hold_search_at_index_1_0_to_1_1_bids_breakeven_plus_15(self):
        out, term = self.plan(T.query('gold cards', 500, 300, 30, 30, 3))
        self.assertEqual(term['role'], 'Hold')
        self.assertTrue(1.0 <= term['index'] < 1.1, term['index'])
        row = T.one(out, 'Bid change', keyword_id='3')
        self.assertEqual((row['role'], row['hold_uplift']), ('Hold', 15))
        self.assertAlmostEqual(row['new'], row['breakeven'] * 1.15, delta=0.011)
        self.assertIn('the Hold uplift test to 2026-11-20 (decision 108)', row['why'])
        self.assertEqual(row['lane'], 'auto')
        self.assertEqual(out['summary'][0]['hold_uplift'], dict(pct=15, review_on='2026-11-20', keywords=['3'], comparison=[]))

    def test_a_hold_search_under_index_1_0_stays_at_breakeven(self):
        out, term = self.plan(T.query('gold cards', 500, 300, 30, 50, 4))
        self.assertEqual(term['role'], 'Hold')
        self.assertTrue(0.8 <= term['index'] < 1.0, term['index'])
        row = T.one(out, 'Bid change', keyword_id='3')
        self.assertNotIn('hold_uplift', row)
        # $0.50 to its breakeven is a cut of more than 50% on a search with 4 orders: it steps down half this run (decision 107)
        self.assertEqual(row['new_proposed'], row['breakeven'])
        self.assertIsNone(out['summary'][0]['hold_uplift'])

    def test_off_in_the_live_config_since_decision_135(self):
        self.assertIs(T.CONFIG['hold_uplift']['enabled'], False)

    def test_off_in_config_it_bids_breakeven(self):
        T.make_run(self.run_dir, queries=[q for q in T.QUERIES if q['Query'] != 'gold cards'] + [T.query('gold cards', 500, 300, 30, 30, 3)])
        out = planner.build(T.ASIN, T.product(), T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        row = T.one(out, 'Bid change', keyword_id='3')
        self.assertEqual(row.get('new_proposed', row['new']), row['breakeven'])


class HoldUpliftRecordTest(unittest.TestCase):
    """hold_uplift.py: the baseline the first applied run records, the dated review on the product's page, the review and
    the verdict (decision 108; docs/experiments/hold-uplift-2026-10-23/protocol.md)."""
    setUp = T.PlannerLanesTest.setUp

    def run_cmd(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), unittest.mock.patch.object(hold_uplift, 'experiment_dir', return_value=self.exp):
            hold_uplift.main(list(argv))
        return json.loads(out.getvalue())

    def test_baseline_review_and_verdict(self):
        shared = T.shared_config()
        shared['hold_uplift'] = dict(copy.deepcopy(T.CONFIG['hold_uplift']), enabled=True)   # off since decision 135
        queries = [q for q in T.QUERIES if q['Query'] != 'gold cards'] + [
            T.query('gold cards', 500, 300, 30, 30, 3),          # index 1.0: the uplift group
            T.query('birthday cards', 500, 300, 30, 50, 4)]      # index about 0.83: the comparison group
        keywords = [dict(k, Impressions=900) if k['KeywordId'] in ('3', '6') else k for k in T.KEYWORDS]
        T.make_run(self.run_dir, queries=queries, keywords=keywords)
        out = planner.build(T.ASIN, T.product(), shared, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        planner.write_outputs(self.run_dir, out, shared, T.ASIN)
        self.assertEqual((out['summary'][0]['hold_uplift']['keywords'], out['summary'][0]['hold_uplift']['comparison']), (['3'], ['6']))
        self.exp = os.path.join(self.tmp, 'exp')
        data = os.path.join(self.tmp, 'data')
        os.makedirs(os.path.join(data, 'asins'))
        T.write(os.path.join(data, 'asins', f'{T.ASIN}.json'), T.product(reviews=[]))

        done = self.run_cmd('baseline', '--run', self.run_dir, '--data', data, '--date', '2026-10-23')
        self.assertEqual((done['uplift'], done['comparison'], done['review_added'], done['review_on']), (1, 1, True, '2026-11-20'))
        base = hold_uplift.load(os.path.join(self.exp, 'baseline', f'{T.ASIN}.json'))
        self.assertEqual([(k['keyword_id'], k['group']) for k in base['keywords']], [('3', 'uplift'), ('6', 'comparison')])
        self.assertEqual(base['totals']['uplift']['impressions'], 280.0)   # 900 over 90 days, as a 28-day rate
        product = hold_uplift.load(os.path.join(data, 'asins', f'{T.ASIN}.json'))
        self.assertEqual([(r['date'], r['short']) for r in product['reviews']], [('2026-11-20', 'Hold +15% test review')])
        again = self.run_cmd('baseline', '--run', self.run_dir, '--data', data)
        self.assertIn('kept', again)   # the first baseline stands
        self.assertEqual(len(hold_uplift.load(os.path.join(data, 'asins', f'{T.ASIN}.json'))['reviews']), 1)

        pull = os.path.join(self.tmp, 'kw28.json')
        T.write(pull, dict(data=[dict(KeywordId='3', Impressions=420, Clicks=6, Orders=1, Spend=3.0, Sales=10),
                                 dict(KeywordId='6', Impressions=280, Clicks=3, Orders=0, Spend=1.0, Sales=0)]))
        res = self.run_cmd('review', '--asin', T.ASIN, '--kw', pull, '--date', '2026-11-20')
        self.assertEqual((res['impressions_lift_pts'], res['orders_held'], res['verdict']), (50.0, True, 'keep'))
        verdict = self.run_cmd('verdict')
        self.assertEqual((verdict['overall'], verdict['keep'], verdict['not_reviewed']), ('keep', [T.ASIN], []))
        # impressions that moved no more than the comparison group's: roll back
        T.write(pull, dict(data=[dict(KeywordId='3', Impressions=300, Clicks=6, Orders=1), dict(KeywordId='6', Impressions=280)]))
        self.assertEqual(self.run_cmd('review', '--asin', T.ASIN, '--kw', pull)['verdict'], 'roll back')


class RoutineTest(unittest.TestCase):
    """routine.py: the morning routine's work list (decision 107)."""

    def product(self, asin, **over):
        p = dict(asin=asin, product=asin, registry=dict(bid_owner='AI', stage='ai', next_run='2026-10-24'),
                 last_run=dict(date='2026-10-17'), open_items=[], reviews=[])
        p.update(over)
        return p

    def test_the_work_list(self):
        products = [
            self.product('B0DUE00001', open_items=[dict(status='open', due='2026-10-23', short='Day-1 check'),
                                                    dict(status='done', due='2026-10-22', short='old'),
                                                    dict(status='decision', short='a price for Kim')]),
            self.product('B0LATER002', registry=dict(bid_owner='AI', stage='ai', next_run='2026-10-30'),
                         open_items=[dict(status='open', due='2026-10-24', short='re-check the negative')],
                         reviews=[dict(date='2026-10-24', short='Hold +15% test review', experiment='hold-uplift-2026-10-23'),
                                  dict(date='2026-10-20', short='done one', done='2026-10-20'),
                                  dict(date='2026-11-20', short='later')]),
            self.product('B0STALE003', registry=dict(bid_owner='AI', stage='ai', next_run='2026-10-10'), last_run=dict(date='2026-10-20')),
            self.product('B0TODAY004', last_run=dict(date='2026-10-24')),
            self.product('B0QUEUE005', registry=dict(bid_owner='Scale Insights', stage='queued', next_run='2026-10-20'))]
        out = routine.work_list(products, '2026-10-24')
        self.assertEqual([r['asin'] for r in out['runs']], ['B0DUE00001'])   # B0STALE003 is due Oct 27 (last run + 7)
        self.assertEqual([(g['asin'], g['with_run'], [i['what'] for i in g['items']]) for g in out['checks']],
                         [('B0DUE00001', True, ['Day-1 check']), ('B0LATER002', False, ['re-check the negative'])])
        self.assertEqual([(r['asin'], r['what']) for r in out['reviews']], [('B0LATER002', 'Hold +15% test review')])
        self.assertEqual(out['waiting_on_people'], 1)
        self.assertEqual(routine.due_on(products[2], 7), '2026-10-27')
        self.assertEqual(out['ended_reviews'], 0)

    def test_an_ended_experiments_review_is_skipped(self):
        cfg = routine.load(os.path.join(routine.SKILL, 'config.json'))
        ended = routine.ended_experiments(cfg)
        self.assertIn('hold-uplift-2026-10-23', ended)   # hold_uplift ended 2026-10-25 (decision 135)
        p = self.product('B0LATER002', reviews=[dict(date='2026-11-20', short='Hold +15% test review',
                                                     experiment='hold-uplift-2026-10-23'),
                                                dict(date='2026-11-20', short='another review')])
        out = routine.work_list([p], '2026-11-20', ended=ended)
        self.assertEqual([r['what'] for r in out['reviews']], ['another review'])
        self.assertEqual(out['ended_reviews'], 1)


if __name__ == '__main__':
    unittest.main()
