"""budget_headroom.py: profitable campaigns that run out of budget get a +50% step, a step that stopped paying goes back,
and the weekly run carries the steps as 'Budget step' rows a person approves (Kim, 2026-10-20).

The rule is judged against the product's own breakeven ACOS: the planner's synthetic product (test_plan_lanes) earns $5 on
a $10 price, so its breakeven ACOS is 50% and a step needs ACOS at or below 40%.
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

import budget_headroom as bh
import human_review
import log_invest
import plan as planner
import test_business as B
import test_business_roles as R
import test_plan_lanes as T
from test_business import FLAGGED_ONLY   # a B2B campaign known only by its siteRestrictions flag (ids 111 / 211)

CFG = dict(bh.DEFAULTS)
TODAY = dt.date(2026, 10, 19)


def days(cid, name, budget, cost, sales, orders=1, clicks=10, n=14, end=dt.date(2026, 10, 18)):
    """n campaign-day rows ending `end`, every day the same."""
    return [dict(campaign_id=cid, campaign=name, date=(end - dt.timedelta(days=i)).isoformat(), cost=cost, budget=budget,
                 sales=sales, orders=orders, clicks=clicks) for i in range(n)]


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)


class RuleTest(unittest.TestCase):
    def decide(self, rows, be=0.5, **kw):
        return bh.decide(bh.day_rows(rows), lambda name: be, CFG, TODAY, **kw)

    def test_a_capped_campaign_well_under_breakeven_steps_up_by_half(self):
        v = self.decide(days('1', 'A - B0TEST0001 - Broad', 10, 10, 40))  # ACOS 25% against 50%, out of budget every day
        self.assertEqual([(x['campaign_id'], x['budget_now'], x['budget']) for x in v['up']], [('1', 10, 15.0)])
        self.assertIn('ran out of budget on 14 of 14 days', v['up'][0]['why'])

    def test_a_rank_campaign_out_of_budget_steps_up_whatever_its_acos(self):
        # Kim, 2026-10-31 (decision 174): losses are accepted for ranking, so a rank campaign (Invest, Prove first) on a
        # validated search that runs out of budget steps up with no ACOS or order test; a non-rank one keeps the test
        loss = days('9', 'SKC - B0TEST0001 - blank cards', 10, 10, 8, orders=1)   # ACOS 125% against 50%, 1 order
        v = self.decide(loss, rank={'9'})
        self.assertEqual([(x['campaign_id'], x['budget'], x.get('rank')) for x in v['up']], [('9', 15.0, True)])
        self.assertIn('losses are accepted for ranking', v['up'][0]['why'])
        self.assertEqual(self.decide(loss)['up'], [])
        self.assertEqual([x['campaign_id'] for x in self.decide(loss)['at_loss']], ['9'])
        # no sales at all, and no breakeven on file, still step a rank campaign
        self.assertEqual(len(bh.decide(bh.day_rows(days('9', 'SKC', 10, 10, 0, orders=0)), lambda n: None, CFG, TODAY,
                                       rank={'9'})['up']), 1)

    def test_a_rank_campaign_keeps_the_ceiling_the_step_and_the_week(self):
        self.assertEqual(self.decide(days('9', 'SKC', 50, 50, 10), rank={'9'})['up'], [])
        self.assertEqual(self.decide(days('9', 'SKC', 40, 40, 10), rank={'9'})['up'][0]['budget'], 50.0)
        recent = {'steps': [dict(campaign_id='9', date='2026-10-17', **{'from': 10, 'to': 15})]}
        v = self.decide(days('9', 'SKC', 15, 15, 5), rank={'9'}, ledger=recent)
        self.assertEqual((v['up'], len(v['waiting'])), ([], 1))
        # a week on, above breakeven, it is never stepped back on ACOS: it steps again while it runs out of budget
        old = {'steps': [dict(campaign_id='9', date='2026-10-01', **{'from': 10, 'to': 15})]}
        v = self.decide(days('9', 'SKC', 15, 15, 5, clicks=30), rank={'9'}, ledger=old)
        self.assertEqual((v['back'], [x['budget'] for x in v['up']]), ([], [23.0]))
        # not out of budget on enough days: nothing
        self.assertEqual(self.decide(days('9', 'SKC', 10, 5, 2), rank={'9'})['up'], [])

    def test_a_small_budget_steps_at_least_a_dollar_and_rounds_up(self):
        self.assertEqual(bh.step_up(3, CFG), 5.0)    # 3 x 1.5 = 4.5 -> 5
        self.assertEqual(bh.step_up(1, CFG), 2.0)    # 1.5 -> 2, and at least +$1
        self.assertEqual(bh.step_up(10, CFG), 15.0)

    def test_the_step_never_passes_amazons_suggestion_or_the_ceiling(self):
        self.assertEqual(bh.step_up(10, CFG, suggested=12), 12.0)
        self.assertEqual(bh.step_up(40, CFG), 50.0)
        self.assertIsNone(bh.step_up(50, CFG))
        self.assertEqual(bh.step_up(10, CFG, suggested=8), 15.0)  # a suggestion below today's budget is no cap

    def test_capped_above_breakeven_is_a_loss_the_budget_limits(self):
        v = self.decide(days('1', 'A', 10, 10, 15))  # ACOS 67%
        self.assertEqual(v['up'], [])
        self.assertEqual([x['campaign_id'] for x in v['at_loss']], ['1'])

    def test_capped_at_breakeven_is_watched_not_stepped(self):
        v = self.decide(days('1', 'A', 10, 10, 22))  # ACOS 45%: under 50% but over 40%
        self.assertEqual(v['up'], [])
        self.assertEqual([x['campaign_id'] for x in v['watch']], ['1'])

    def test_few_orders_is_watched(self):
        rows = days('1', 'A', 10, 10, 40, orders=0)
        rows[5]['orders'] = 2  # 2 orders in 14 days
        v = self.decide(rows)
        self.assertEqual(v['up'], [])
        self.assertEqual(len(v['watch']), 1)

    def test_a_campaign_rarely_out_of_budget_is_left_alone(self):
        rows = days('1', 'A', 10, 4, 40)
        for r in rows[:4]:
            r['cost'] = 10  # out of budget on 4 days: one short
        v = self.decide(rows)
        self.assertEqual(sum(len(v[k]) for k in ('up', 'back', 'watch', 'at_loss', 'no_breakeven')), 0)

    def test_the_newest_two_days_count_for_capped_days_but_not_for_acos(self):
        rows = days('1', 'A', 10, 10, 40)
        for r in rows[:2]:
            r['sales'] = 0  # attribution not in yet: would push ACOS up if counted
        v = self.decide(rows)
        self.assertEqual(v['up'][0]['acos'], 0.25)
        self.assertEqual(v['up'][0]['capped_days'], 14)
        self.assertEqual(v['window']['acos_through'], '2026-10-16')

    def test_no_breakeven_on_file_proposes_nothing(self):
        v = bh.decide(bh.day_rows(days('1', 'A', 10, 10, 40)), lambda name: None, CFG, TODAY)
        self.assertEqual(v['up'], [])
        self.assertEqual(len(v['no_breakeven']), 1)

    def test_a_live_budget_beats_the_report(self):
        v = self.decide(days('1', 'A', 10, 10, 40), live_budgets={'1': 20})
        self.assertEqual((v['up'][0]['budget_now'], v['up'][0]['budget']), (20, 30.0))

    def test_excluded_campaigns_are_skipped(self):
        v = self.decide(days('1', 'A', 10, 10, 40), exclude={'1'})
        self.assertEqual(v['up'], [])

    def test_a_step_waits_a_week_before_another(self):
        ledger = {'steps': [{'campaign_id': '1', 'from': 5, 'to': 10, 'date': '2026-10-15'}]}
        v = self.decide(days('1', 'A', 10, 10, 40), ledger=ledger)
        self.assertEqual(v['up'], [])
        self.assertEqual([x['campaign_id'] for x in v['waiting']], ['1'])

    def test_a_step_that_still_pays_steps_again(self):
        ledger = {'steps': [{'campaign_id': '1', 'from': 5, 'to': 10, 'date': '2026-10-08'}]}
        v = self.decide(days('1', 'A', 10, 10, 40), ledger=ledger)
        self.assertEqual([(x['budget_now'], x['budget']) for x in v['up']], [(10, 15.0)])

    def test_a_step_that_stopped_paying_goes_back(self):
        ledger = {'steps': [{'campaign_id': '1', 'from': 5, 'to': 10, 'date': '2026-10-08'}]}
        v = self.decide(days('1', 'A', 10, 10, 12, clicks=10), ledger=ledger)  # ACOS 83% on 110 clicks since the step
        self.assertEqual([(x['budget_now'], x['budget']) for x in v['back']], [(10, 5.0)])
        self.assertIn('back to $5/day', v['back'][0]['why'])

    def test_a_step_back_needs_enough_clicks(self):
        ledger = {'steps': [{'campaign_id': '1', 'from': 5, 'to': 10, 'date': '2026-10-08'}]}
        v = self.decide(days('1', 'A', 10, 10, 12, clicks=1), ledger=ledger)  # 11 clicks since the step: too few to judge
        self.assertEqual(v['back'], [])

    def test_amazons_recommendation_is_read(self):
        recs = bh.recs_of({'budgetRecommendationsSuccessResults': [{'campaignId': '1', 'suggestedBudget': 12.0,
                           'sevenDaysMissedOpportunities': {'percentTimeInBudget': 0.3, 'estimatedMissedSalesLower': 100,
                                                            'estimatedMissedSalesUpper': 300}}]})
        v = self.decide(days('1', 'A', 10, 10, 40), recs=recs)
        self.assertEqual(v['up'][0]['budget'], 12.0)
        self.assertIn('in budget 30% of the time (Amazon)', v['up'][0]['why'])

    def test_map_sql_rows_are_read_in_their_own_spelling(self):
        raw = {'data': [dict(campaignId=1, campaignName='A', date='2026-10-18', cost=10.0, campaignBudgetAmount=10.0,
                             sales14d=40.0, purchases14d=1, clicks=10)]}
        self.assertEqual(bh.day_rows(raw), [dict(campaign_id='1', campaign='A', date='2026-10-18', cost=10.0, budget=10.0,
                                                 sales=40.0, orders=1, clicks=10)])


class LedgerTest(unittest.TestCase):
    def test_record_keeps_steps_in_date_order_and_last_steps_reads_the_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'budget_steps.json')
            bh.record_step(path, {'campaign_id': '1', 'from': 10, 'to': 15, 'date': '2026-10-27'})
            bh.record_step(path, {'campaign_id': '1', 'from': 5, 'to': 10, 'date': '2026-10-20'})
            ledger = bh.load_ledger(path)
            self.assertEqual([s['date'] for s in ledger['steps']], ['2026-10-20', '2026-10-27'])
            self.assertEqual(bh.last_steps(ledger)['1']['to'], 15)


SKC_ID = T.IDS[T.SKC][0]
STW_ID = T.IDS[T.STW][0]
BROAD_ID = T.IDS[T.BROAD][0]


def campaign_days():
    # STW: out of budget every day at 25% ACOS; the invest SKC the same (a rank campaign: it steps up without the ACOS
    # condition since decision 174); Broad at a loss
    return {'data': days(STW_ID, T.STW, 10, 10, 40, orders=2) + days(SKC_ID, T.SKC, 10, 10, 40, orders=2)
            + days(BROAD_ID, T.BROAD, 10, 10, 15)}


class PlannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = os.path.join(tmp.name, 'run')
        self.data = os.path.join(tmp.name, 'data')
        self.product_file = os.path.join(self.data, 'asins', f'{T.ASIN}.json')

    def plan(self, with_days=True, more_campaigns=(), more_days=(), **product_over):
        extra = {'campaign_days.json': {'data': campaign_days()['data'] + list(more_days)}} if with_days else None
        T.make_run(self.run_dir, extra=extra, more_campaigns=more_campaigns)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False), price=10.0, **product_over))
        argv = ['plan.py', '--asin', T.ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.without_mid():
            planner.main()
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            return json.load(fh)

    def steps(self, plan):
        return [c for c in plan['changes'] if c['type'] == 'Budget step']

    def test_the_weekly_run_steps_the_profitable_capped_campaign_and_the_capped_rank_campaign(self):
        plan = self.plan()
        rows = self.steps(plan)
        self.assertEqual([(r['campaign_id'], r['budget_now'], r['budget'], r['direction']) for r in rows],
                         [(STW_ID, 10, 15.0, 'up'), (SKC_ID, 10, 15.0, 'up')])
        self.assertTrue(rows[1].get('rank_campaign'))
        self.assertIn('losses are accepted for ranking', rows[1]['lane_reason'])
        # a budget step applies on its own since autonomous runs (2026-10-22, decision 98); a person said yes to each before
        self.assertEqual(rows[0]['lane'], 'auto')
        self.assertIn('budget headroom', rows[0]['lane_reason'])
        summary = plan['summary'][0]
        self.assertEqual((summary['budget_steps'], summary['budget_headroom']['capped_at_loss'],
                          summary['budget_headroom']['rank_steps_up']), (2, 1, 1))

    def test_a_business_campaign_out_of_budget_steps_like_a_consumer_one(self):
        # design 2026-10-21-b2b-lane-and-roles 4e: B2B campaigns are judged again. This one (known only by the live flag) is
        # out of budget every day at 25% ACOS, as the STW is, and holds no business invest this run: it steps. The audience
        # copy ('... Low Bids') runs the same and still gets none
        b2b = dict(T.campaign(FLAGGED_ONLY), siteRestrictions=['AMAZON_BUSINESS'])
        low = T.IDS[T.LOW][0]
        plan = self.plan(more_campaigns=[b2b], more_days=days(b2b['campaignId'], FLAGGED_ONLY, 10, 10, 40, orders=2)
                         + days(low, T.LOW, 10, 10, 40, orders=2))
        self.assertEqual(sorted(r['campaign_id'] for r in self.steps(plan)), sorted([STW_ID, SKC_ID, b2b['campaignId']]))
        self.assertNotIn(low, [r['campaign_id'] for r in self.steps(plan)])

    def test_a_rank_campaigns_recorded_step_is_never_undone_by_the_standard(self):
        # decision 174: the rank campaign's Invest standard is $10/day; once a step took it to $15, the run keeps $15
        write_json(os.path.join(self.data, 'budget_steps.json'),
                   {'steps': [dict(campaign_id=SKC_ID, date='2026-10-01', by='weekly run', **{'from': 10, 'to': 15})]})
        quiet = days(STW_ID, T.STW, 10, 3, 40, orders=2) + days(SKC_ID, T.SKC, 15, 5, 20, orders=2)
        T.make_run(self.run_dir, extra={'campaign_days.json': {'data': quiet}})
        with open(os.path.join(self.run_dir, 'campaigns.json'), encoding='utf-8') as fh:
            camps = json.load(fh)
        for c in camps['items']:
            if str(c['campaignId']) == SKC_ID:
                c['budget']['budget'] = 15
        write_json(os.path.join(self.run_dir, 'campaigns.json'), camps)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False), price=10.0))
        argv = ['plan.py', '--asin', T.ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.without_mid():
            planner.main()
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            plan = json.load(fh)
        rows = [c for c in plan['changes'] if str(c.get('campaign_id')) == SKC_ID and c.get('budget') is not None
                and c['type'] in ('Budget and top of search', 'Budget step')]
        self.assertTrue(all(c['budget'] >= 15 for c in rows), [(c['type'], c['budget']) for c in rows])

    def test_the_step_goes_out_budget_only(self):
        plan = self.plan()
        review = T.read_payloads(self.run_dir, 'review')
        rid = self.steps(plan)[0]['row_id']
        self.assertIn(dict(type='sp_campaigns', campaignId=STW_ID, budget=dict(budget=15.0, budgetType='DAILY')),
                      review['5_campaign_updates.json'])
        self.assertIn(rid, [r for ids in T.read_rows(self.run_dir, 'review')['5_campaign_updates.json'] for r in ([ids] if isinstance(ids, str) else ids)])

    def test_a_step_of_any_size_is_the_book_owners(self):
        # Kim, 2026-10-22: budget steps of any size are the book owner's (a step worth more than $50 a month was Lee's)
        plan = self.plan()
        levels = human_review.row_levels(plan)
        i = next(i for i, c in enumerate(plan['changes']) if c['type'] == 'Budget step')
        self.assertEqual(levels[i], 'owner')  # +$5/day = $150 a month
        for now, new in ((3, 4.5), (10, 50), (20, 10)):  # +$45 a month, +$1,200 a month, a step back
            with self.subTest(now=now, new=new):
                step = dict(plan['changes'][i], budget_now=now, budget=new)
                self.assertEqual(human_review.row_levels(dict(plan, changes=[step]))[0], 'owner')

    def test_without_campaign_days_the_run_says_so_and_proposes_nothing(self):
        plan = self.plan(with_days=False)
        self.assertEqual(self.steps(plan), [])
        self.assertIn('campaign_days.json not pulled', plan['summary'][0]['budget_headroom']['status'])

    def test_a_step_that_went_out_is_recorded_and_waits_a_week(self):
        plan = self.plan()
        rid = self.steps(plan)[0]['row_id']
        write_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'), {rid: dict(date='2026-10-20', folder='review')})
        argv = ['log_invest.py', '--asin', T.ASIN, '--run', self.run_dir, '--data', self.data, '--date', '2026-10-20']
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(out):
            log_invest.main()
        ledger = bh.load_ledger(os.path.join(self.data, 'budget_steps.json'))
        self.assertEqual([(s['campaign_id'], s['from'], s['to'], s['date']) for s in ledger['steps']], [(STW_ID, 10, 15.0, '2026-10-20')])
        self.assertIn('budget step recorded', ' '.join(json.loads(out.getvalue())['changes']))
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            log_invest.main()  # run twice: recorded once
        self.assertEqual(len(bh.load_ledger(os.path.join(self.data, 'budget_steps.json'))['steps']), 1)


class BusinessInvestCampaignTest(unittest.TestCase):
    """design 2026-10-21-b2b-lane-and-roles 4e, on the business roles fixture: a B2B campaign that holds a business invest
    this run (a Business invest row, a business New exact keyword, or an owner already invested as planned) has its budget
    set by that invest, so it gets no second budget row; the product's other B2B campaigns step like consumer ones."""
    setUp = T.PlannerLanesTest.setUp
    shared = staticmethod(R.shared)
    plan = R.BusinessRolesTest.plan

    def test_a_campaign_holding_a_business_invest_gets_no_step(self):
        s = R.shared()
        s['data_dir'] = os.path.join(self.tmp, 'data')   # an empty budget-step ledger, never the skill's own
        b2b = [B.B2B_EXACT, B.B2B_STWS, R.B2B_STWS_EXACT, R.B2B_EXACT2]   # 108, 109, 110, 111
        out_of_budget = {'campaign_days.json': {'data': [r for n in b2b for r in days(T.IDS[n][0], n, 10, 10, 40, orders=2)]}}
        # 108 holds the zebra cards Business invest; 110 takes the office cards New exact keyword
        out = self.plan(shared=s, extra=out_of_budget)
        T.one(out, 'Business invest', keyword='zebra cards', campaign_id='108')
        T.one(out, 'New exact keyword', keyword='office cards', campaign_id='110')
        self.assertEqual(sorted(r['campaign_id'] for r in T.by_type(out, 'Budget step')), ['109', '111'])
        # 902 already invested as planned in 108 (test_an_owner_already_invested_as_planned_writes_no_row): no row, but 108's
        # budget is still the invest's
        kws = [k for k in R.KEYWORDS if k['KeywordId'] != '902'] + [T.keyword('902', 'zebra cards', 'exact', B.B2B_EXACT, 1.20, 20, 6, 24)]
        camps = [c for c in R.CAMPAIGNS if c['name'] != B.B2B_EXACT] + [dict(T.campaign(B.B2B_EXACT, tos=50), siteRestrictions=['AMAZON_BUSINESS'])]
        out = self.plan(shared=s, extra=out_of_budget, keywords=kws, more_campaigns=camps)
        self.assertFalse(T.by_type(out, 'Business invest'))
        self.assertEqual([x['campaign_id'] for x in out['business_live_invests']], ['108'])
        self.assertEqual(sorted(r['campaign_id'] for r in T.by_type(out, 'Budget step')), ['109', '111'])


class CatalogTest(unittest.TestCase):
    def test_the_catalog_scan_skips_ai_products_and_writes_a_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, 'data')
            write_json(os.path.join(data, 'asins', 'B0AIPROD01.json'), {'registry': {'stage': 'ai', 'bid_owner': 'AI'}})
            write_json(os.path.join(tmp, 'days.json'), {'data': days('1', 'Cards - B0CATALOG1 - Broad', 3, 3, 12, orders=1)
                                                        + days('2', 'Pens - B0AIPROD01 - Broad', 3, 3, 12, orders=1)})
            write_json(os.path.join(tmp, 'be.json'), {'B0CATALOG1': 44.0, 'B0AIPROD01': 44.0})
            out = os.path.join(tmp, 'out')
            argv = ['budget_headroom.py', '--data', data, 'catalog', '--days', os.path.join(tmp, 'days.json'),
                    '--be', os.path.join(tmp, 'be.json'), '--today', '2026-10-19', '--out', out,
                    '--ledger', os.path.join(tmp, 'ledger.json')]
            with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                bh.main()
            with open(os.path.join(out, 'budget_steps_payload.json'), encoding='utf-8') as fh:
                payload = json.load(fh)
            self.assertEqual(payload, [dict(type='sp_campaigns', campaignId='1', budget=dict(budget=5.0, budgetType='DAILY'))])
            with open(os.path.join(out, 'budget_headroom.md'), encoding='utf-8') as fh:
                self.assertIn('## Step up (1)', fh.read())


if __name__ == '__main__':
    unittest.main()
