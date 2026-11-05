"""The organic share, the top-10 rule and the weekly leak check (Kim, 2026-10-26, decision 143; reshaped 2026-10-31,
decision 175: "drop the under-half organic cut. Just let ordinary keywords stay at 100% of break-even"; "turn it into a leak
check"; top 10 "we can bid 75% of the break-even, but continue investing in the ranking and the high-index keywords"). None
of them touches a rank bid, a budget or a Prove-first launch.

Built on test_plan_lanes' synthetic run (a mature product; TODAY 2026-10-19; profit $5 a unit), with the rules on and the
live 100% non-rank share (decision 157). sales_daily.json is Scale Insights get_sales_data by day: every day $100 of sales,
`share` of it organic, and `profit` after ads. campaign_days.json is the budget check's MAP read (budget_headroom).
"""
import datetime as dt
import json
import os
import shutil
import unittest

import organic_share
import plan as planner
import test_budget_headroom as B
import test_plan_lanes as T

THROUGH = '2026-10-18'


def sales(share, profit, days=28, asin=T.ASIN):
    end = dt.date.fromisoformat(THROUGH)
    return dict(ASINs=[dict(ASIN=asin)],
                Daily=[dict(Date=(end - dt.timedelta(days=i)).isoformat(), Sales=100, PPCSales=round(100 * (1 - share), 2), Units=4,
                            Profits=profit) for i in range(days)])


def radar(keyword, *ranks):
    """Daily Rank Radar readings ending THROUGH, oldest first."""
    end = dt.date.fromisoformat(THROUGH)
    n = len(ranks)
    return dict(keyword=keyword, ranks=[dict(date=(end - dt.timedelta(days=n - 1 - i)).isoformat(), organicRank=r)
                                        for i, r in enumerate(ranks)])


def shared(on=True):
    s = T.shared_config(organic=on)
    s['thresholds']['non_rank_bid_factor'] = 1.0
    return s


def leaking(ordinary_orders=0, rank_orders=2):
    """campaign_days.json: the ordinary STW campaign spends $10 a day for `ordinary_orders` orders ($5 profit each), the rank
    SKC (thank you cards, Invest) $10 a day for `rank_orders`."""
    return {'data': B.days(B.STW_ID, T.STW, 10, 10, 40, orders=ordinary_orders)
            + B.days(B.SKC_ID, T.SKC, 10, 10, 40, orders=rank_orders)}


class OrganicShareTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, extra=None, on=True, cfg=None, **run):
        shutil.rmtree(self.run_dir, ignore_errors=True)   # each plan from a clean run folder: no radar or sales left over
        T.make_run(self.run_dir, extra=extra, **run)
        return planner.build(T.ASIN, cfg or T.product(), shared(on), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    @staticmethod
    def kw(out, kid):
        return next(p for p in out['keyword_plan'] if p['keyword_id'] == kid)

    # ---- the organic share: reported, never a bid (decision 175) ----------------------------------------------------
    def test_under_50_percent_organic_the_ordinary_keywords_stay_at_breakeven(self):
        low = self.plan({'sales_daily.json': sales(0.3, 0)})
        org = low['summary'][0]['organic']
        self.assertEqual((org['share']['share'], org['non_rank_factor'], org['base_factor']), (0.3, 1.0, 1.0))
        self.assertNotIn('brake', org)
        high = self.plan({'sales_daily.json': sales(0.6, 0)})
        # "cards" broad, Discovery, and the rank search: the same bids whatever the organic share
        self.assertEqual(self.kw(low, '4')['new_bid'], self.kw(high, '4')['new_bid'])
        self.assertEqual(self.kw(low, '1')['new_bid'], self.kw(high, '1')['new_bid'])
        self.assertNotIn('organic-share brake', str([c.get('why') for c in low['changes']]))

    def test_without_sales_data_nothing_applies_and_the_summary_says_so(self):
        out = self.plan()
        org = out['summary'][0]['organic']
        self.assertEqual((org['share'], org['leak'], org['non_rank_factor']), (None, None, 1.0))
        self.assertIn('no sales_daily.json', org['note'])
        self.assertIn('no campaign_days.json', org['note'])

    def test_off_in_config_it_plans_as_before(self):
        on = self.plan({'sales_daily.json': sales(0.3, -100)}, on=False)
        self.assertIs(on['summary'][0]['organic']['enabled'], False)
        self.assertEqual(on['summary'][0]['organic']['non_rank_factor'], 1.0)

    def test_a_sales_file_for_another_product_stops_the_run(self):
        with self.assertRaises(SystemExit) as cm:
            self.plan({'sales_daily.json': sales(0.3, 0, asin='B0OTHER001')})
        self.assertIn('not B0TEST0001', str(cm.exception))

    # ---- the top-10 rule ----------------------------------------------------------------------------------------------
    def test_a_search_in_the_top_10_on_rank_radar_bids_75_percent_but_a_rank_search_does_not(self):
        steady = radar('cards', *([9] * 14))
        invested = radar('thank you cards', *([4] * 14))
        out = self.plan({'sales_daily.json': sales(0.6, 0), 'radar_p1.json': dict(keywords=[steady, invested])})
        top10 = out['summary'][0]['organic']['top10']
        self.assertEqual(set(top10), {'cards', 'thank you cards'})
        self.assertIn('Rank Radar median 9', top10['cards'])
        base = self.plan({'sales_daily.json': sales(0.6, 0)})
        self.assertLess(self.kw(out, '4')['new_bid'], self.kw(base, '4')['new_bid'])
        self.assertIn('75% of breakeven', self.kw(out, '4')['action'])
        self.assertEqual(self.kw(out, '1')['new_bid'], self.kw(base, '1')['new_bid'])   # Invest: keeps investing in the top 10
        self.assertIn('the top-10 rule, decisions 143 and 175', T.one(out, 'Bid change', keyword_id='4')['why'])

    def test_a_single_day_in_the_top_10_is_not_ranking(self):
        noisy = radar('cards', *([40] * 13 + [8]))
        out = self.plan({'sales_daily.json': sales(0.6, 0), 'radar_p1.json': dict(keywords=[noisy])})
        self.assertNotIn('cards', out['summary'][0]['organic']['top10'])

    def test_without_rank_radar_sqp_decides_on_three_organic_purchases(self):
        # birthday cards: 5 SQP purchases, no ad orders, so all 5 organic; no Rank Radar for it
        queries = T.QUERIES + [T.query('birthday cards', 1000, 500, 50, 50, 5)]
        out = self.plan({'sales_daily.json': sales(0.6, 0)}, queries=queries)
        top10 = out['summary'][0]['organic']['top10']
        self.assertIn('no Rank Radar; SQP: 100% of its purchases organic', top10['birthday cards'])
        thin = self.plan({'sales_daily.json': sales(0.6, 0)}, queries=T.QUERIES + [T.query('birthday cards', 1000, 500, 50, 50, 2)])
        self.assertNotIn('birthday cards', thin['summary'][0]['organic']['top10'])

    def test_every_invest_search_without_a_rank_radar_is_listed(self):
        out = self.plan({'radar_p1.json': dict(keywords=[radar('thank you cards', 20, 18)])})
        self.assertEqual(out['summary'][0]['organic']['radar_missing'], ['blank cards'])

    # ---- the weekly leak check (decision 175) --------------------------------------------------------------------------
    def test_ordinary_campaigns_losing_money_pause_their_wasted_keywords_only(self):
        out = self.plan({'sales_daily.json': sales(0.3, -100), 'campaign_days.json': leaking(ordinary_orders=0)})
        leak = out['summary'][0]['organic']['leak']
        # Oct 10 to 16 (the newest 2 days settle): 7 x $10 spent, no orders
        self.assertEqual((leak['profit'], leak['spend'], leak['line'], leak['tripped'], leak['acted'], leak['campaigns']),
                         (-70, 70, -10, True, True, 1))
        self.assertEqual((leak['start'], leak['through']), ('2026-10-10', '2026-10-16'))
        # "greeting cards" phrase: 20 clicks, no orders
        pause = T.one(out, 'Pause keyword', keyword='greeting cards')
        self.assertIn('Leak check (decision 175)', pause['why'])
        self.assertEqual(leak['paused'], ['greeting cards'])
        calm = self.plan({'sales_daily.json': sales(0.3, -100), 'campaign_days.json': leaking(ordinary_orders=2)})
        self.assertEqual((calm['summary'][0]['organic']['leak']['profit'], calm['summary'][0]['organic']['leak']['tripped']),
                         (0, False))
        self.assertIn('greeting cards', {x.get('keyword') for x in T.by_type(calm, 'Bid change')})
        # no step-down: every other bid, the rank search's and the budgets are the same either way
        self.assertEqual(out['summary'][0]['organic']['non_rank_factor'], 1.0)
        for kid in ('1', '4'):
            self.assertEqual(self.kw(out, kid)['new_bid'], self.kw(calm, kid)['new_bid'])
        self.assertEqual([(x.get('campaign_id'), x.get('budget')) for x in T.by_type(out, 'Budget and top of search')],
                         [(x.get('campaign_id'), x.get('budget')) for x in T.by_type(calm, 'Budget and top of search')])

    def test_a_losing_rank_campaign_never_trips_the_leak_check(self):
        out = self.plan({'campaign_days.json': leaking(ordinary_orders=2, rank_orders=0)})
        leak = out['summary'][0]['organic']['leak']
        self.assertEqual((leak['profit'], leak['tripped'], leak['campaigns']), (0, False, 1))

    def test_a_tripped_leak_check_never_holds_a_new_prove_first_launch(self):
        queries = [q for q in T.QUERIES if q['Query'] != 'blank cards'] + [T.query('blank cards', 2000, 800, 80, 12, 2)]
        terms = [s for s in T.SEARCH_TERMS if s['SearchTerm'] != 'blank cards'] + [T.search_term('blank cards', T.STW, 12, 2, 8)]
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '2'] + [T.keyword('2', 'blank cards', 'exact', T.STW, 0.5, 12, 2, 8)]
        out = self.plan({'campaign_days.json': leaking(ordinary_orders=0)}, queries=queries, search_terms=terms,
                        keywords=keywords)
        self.assertIs(out['summary'][0]['organic']['leak']['tripped'], True)
        launch = T.one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((launch['role'], launch['lane']), ('Prove first', 'auto'))


    # ---- the leak check reads Sponsored Brands too (Kim, 2026-10-31: "extends to sponsored brands as well") -----------
    def sb_run(self, sb_days):
        """sb1: the AI's video series (a rank campaign); sb2: an older video campaign whose phrase keyword "greeting cards"
        has 20 clicks and no orders over 90 days. The SP campaigns break even."""
        camps = [dict(campaignId='sb1', name=f'Cards - {T.ASIN} - Videos - Highest Converting Search Terms - Exact - 1',
                      state='ENABLED', budget=10),
                 dict(campaignId='sb2', name=f'Cards - {T.ASIN} - Video - Older', state='ENABLED', budget=10)]
        kws = [dict(keywordId='k1', campaignId='sb1', adGroupId='g1', keywordText='thank you cards', matchType='EXACT',
                    state='ENABLED', bid=1.0),
               dict(keywordId='k2', campaignId='sb2', adGroupId='g2', keywordText='greeting cards', matchType='PHRASE',
                    state='ENABLED', bid=0.8)]
        files = {'campaign_days.json': leaking(ordinary_orders=2), 'sb_campaigns_p1.json': dict(items=camps),
                 'sb_keywords_p1.json': dict(items=kws),
                 'sb_kw_perf.json': dict(data=[dict(keywordId='k2', clicks=20, purchases=0, cost=12)])}
        if sb_days is not None:
            files['sb_campaign_days.json'] = {'data': sb_days}
        return self.plan(files, cfg=T.product(sb_video=dict(enabled=True, campaigns=['sb1'], video_asset_id='asset')))

    @staticmethod
    def sb_days(cid, cost, purchases):
        # the MAP sponsored_brands_campaigns spelling: campaignId, campaignName, purchases
        return [dict(campaignId=cid, campaignName='x', date=r['date'], cost=cost, campaignBudgetAmount=10, sales=0,
                     purchases=purchases, clicks=5) for r in B.days(cid, 'x', 10, cost, 0)]

    def test_an_ordinary_sb_campaign_losing_money_trips_it_and_pauses_its_wasted_keywords(self):
        out = self.sb_run(self.sb_days('sb2', 10, 0))
        leak = out['summary'][0]['organic']['leak']
        self.assertEqual((leak['profit'], leak['tripped']), (-70, True))
        self.assertEqual((leak['channels']['SB']['profit'], leak['channels']['SP']['profit']), (-70, 0))
        pause = T.one(out, 'SB pause keyword', keyword_id='k2')
        self.assertIn('Leak check (decision 175)', pause['why'])
        self.assertEqual(leak['sb_paused'], ['greeting cards'])
        # the AI's video series is a rank campaign: its keyword is priced as before, never paused by the check
        self.assertEqual([x for x in T.by_type(out, 'SB pause keyword') if x.get('keyword_id') == 'k1'], [])

    def test_a_losing_sb_rank_campaign_never_trips_it(self):
        out = self.sb_run(self.sb_days('sb1', 30, 0))
        leak = out['summary'][0]['organic']['leak']
        self.assertEqual((leak['profit'], leak['tripped'], set(leak['channels'])), (0, False, {'SP'}))
        self.assertEqual([x for x in T.by_type(out, 'SB pause keyword') if x.get('keyword_id') == 'k2'], [])

    def test_without_the_sb_read_it_runs_on_sponsored_products_and_says_so(self):
        out = self.sb_run(None)
        org = out['summary'][0]['organic']
        self.assertIs(org['leak']['tripped'], False)
        self.assertIn('no sb_campaign_days.json', org['note'])


class OrganicShareUnitTest(unittest.TestCase):
    S = organic_share.settings({})

    def test_the_share_and_the_leak_check_read_their_own_windows(self):
        days = {(dt.date(2026, 10, 18) - dt.timedelta(days=i)).isoformat(): dict(sales=100.0, ppc_sales=0.0 if i >= 7 else 100.0,
                                                                              units=4, profits=0.0)
                for i in range(28)}
        self.assertEqual(organic_share.product_share(dict(days=days, through='2026-10-18'), 28)['share'], 0.75)   # 21 of 28
        rows = B.days('1', 'ordinary', 10, 10, 0, orders=0) + B.days('2', 'rank', 10, 50, 0, orders=0)
        everything = organic_share.leak_reading(rows, lambda cid, name: True, 5.0, self.S)
        ordinary = organic_share.leak_reading(rows, lambda cid, name: cid == '1', 5.0, self.S)
        self.assertEqual((ordinary['profit'], ordinary['line'], ordinary['tripped'], ordinary['days']), (-70, -10, True, 7))
        self.assertEqual(everything['profit'], -420)
        self.assertEqual((ordinary['start'], ordinary['through']), ('2026-10-10', '2026-10-16'))
        # a $9 loss is inside the $10 tolerance; two orders at $5 pay for $10 of spend
        small = B.days('1', 'ordinary', 10, 9 / 7, 0, orders=0)
        self.assertIs(organic_share.leak_reading(small, lambda cid, name: True, 5.0, self.S)['tripped'], False)
        self.assertIsNone(organic_share.leak_reading([], lambda cid, name: True, 5.0, self.S))

    def test_the_live_config_matches_decision_175(self):
        s = organic_share.settings(T.shared_config(organic=True))
        self.assertEqual((s['top10_factor'], s['leak_days'], s['leak_tolerance'], s['leak_pause_clicks']), (0.75, 7, 10, 15))
        self.assertFalse({'brake_factor', 'guard_step', 'guard_floor', 'allowance_floor_day'} & set(s))

    def test_a_saved_response_with_the_account_context_after_it_loads(self):
        import tempfile
        with tempfile.TemporaryDirectory() as run:
            with open(os.path.join(run, 'sales_daily.json'), 'w', encoding='utf-8') as f:
                f.write(json.dumps(sales(0.4, 1)) + json.dumps({'account_context': {}}))
            loaded = organic_share.load_sales(run, T.ASIN)
        self.assertEqual((loaded['through'], len(loaded['days'])), (THROUGH, 28))

    def test_a_first_page_of_daily_rows_stops_the_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as run:
            part = dict(sales(0.4, 1), DailyMeta=dict(has_next_page=True))
            with open(os.path.join(run, 'sales_daily.json'), 'w', encoding='utf-8') as f:
                json.dump(part, f)
            with self.assertRaises(SystemExit) as cm:
                organic_share.load_sales(run, T.ASIN)
        self.assertIn('count=100', str(cm.exception))

if __name__ == '__main__':
    unittest.main()
