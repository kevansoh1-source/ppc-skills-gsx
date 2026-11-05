"""The suggested mid for validated and still-launching ordinary keywords (Kim, 2026-10-31, decision 177: "stop cutting
validated or still-launching keywords to breakeven just because they convert at about the market rate. Bid them at the
suggested middle bid"; "take the Amazon mid suggested bid by default. If it is rate-limited or unavailable, then take
Soldscope. If both are not available, then derive it using the next best possible calculation that is close to it").

Built on test_plan_lanes' synthetic run (profit $5 a unit) with the rule on and no raise step (decision 165). "kraft cards"
converts about like the market on 2 SQP purchases (a Hold search, index 0.8 to 1.1); its breakeven click is about $0.50, and
Amazon's mid is $0.95.
"""
import json
import os
import shutil
import unittest

import mid_bid
import plan as planner
import test_plan_lanes as T

KRAFT = T.query('kraft cards', 1000, 500, 50, 20, 2)            # SQP: 2 purchases on 20 clicks, a market of 10%: Hold
FOIL = T.query('foil cards', 1000, 1000, 50, 5, 2)              # 2 purchases on 5 clicks against a 5% market: index 1.3+
KRAFT_KW = T.keyword('9', 'kraft cards', 'exact', T.STW, 0.40, 20, 2, 8)
AMAZON = dict(T.SUGGESTED, **{'kraft cards': [0.60, 0.95, 1.30]})
AUTO = dict(T.AUTO, max_raise_pct=None, max_raises=None, prove_index=1.1)   # the live bars (decisions 165 and 178)


def filler(cvr):
    """A search-term row that puts the product's ad conversion at cvr with the fixture's 88 clicks and 13 orders: 10% sizes
    the launch test at 20 and 30 clicks, 5% at 40 and 60."""
    clicks = {0.10: 212, 0.05: 512}[cvr]
    return T.search_term('card stock', T.AUTO_CAMPAIGN, clicks, 17, 100)


def launch(kid, text, clicks, orders, match='exact', campaign=T.STW, bid=0.30):
    return T.keyword(kid, text, match, campaign, bid, clicks, orders, round(clicks * 0.4, 2))


class MidBidTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, keywords, queries=(), suggested=None, extra=None, organic=False, cfg=None, cvr=None, all_matches=False):
        shutil.rmtree(self.run_dir, ignore_errors=True)   # a clean run folder: no tried or SoldScope file left over
        T.make_run(self.run_dir, queries=T.QUERIES + list(queries), keywords=[T.KEYWORDS[0]] + list(keywords),
                   suggested=AMAZON if suggested is None else suggested, extra=extra,
                   search_terms=T.SEARCH_TERMS + ([filler(cvr)] if cvr else []))
        shared = T.shared_config(mid=True, organic=organic)
        shared['auto'] = dict(AUTO, enabled=False)
        if all_matches:   # decision 177 as built: the mid on broad, phrase and SB keywords too (decision 183 narrowed it)
            shared['mid_bid'].update(match_types=['exact', 'broad', 'phrase'], sponsored_brands=True)
        return planner.build(T.ASIN, cfg or T.product(auto=dict(AUTO)), shared, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    @staticmethod
    def kw(out, kid):
        return next(p for p in out['keyword_plan'] if p['keyword_id'] == kid)

    # ---- rule 1: a validated keyword at the suggested mid -------------------------------------------------------------
    def test_a_validated_hold_keyword_bids_amazons_mid_above_its_breakeven(self):
        out = self.plan([KRAFT_KW], [KRAFT])
        p = self.kw(out, '9')
        self.assertEqual(p['role'], 'Hold')
        self.assertLess(p['breakeven_cpc'], 0.95)
        self.assertEqual((p['new_bid'], p['mid_bid']['source'], p['mid_bid']['state']), (0.95, 'amazon', 'validated'))
        change = T.one(out, 'Bid change', keyword_id='9')
        self.assertEqual((change['new'], change['role'], change['lane']), (0.95, 'Hold', 'auto'))
        self.assertIn('suggested mid', change['lane_reason'])
        self.assertIn('decision 177', change['why'])
        self.assertIsNone(change.get('tos'))   # no top-of-search boost of its own
        row = out['summary'][0]['mid_bid']['rows'][0]
        self.assertEqual((row['keyword'], row['state'], row['mid'], row['source'], row['spend90']),
                         ('kraft cards', 'validated', 0.95, 'amazon', 8))

    def test_the_mid_goes_below_breakeven_too_never_the_low_or_the_high(self):
        out = self.plan([KRAFT_KW], [KRAFT], suggested=dict(T.SUGGESTED, **{'kraft cards': [0.20, 0.30, 0.45]}))
        p = self.kw(out, '9')
        self.assertGreater(p['breakeven_cpc'], 0.30)
        self.assertEqual(p['new_bid'], 0.30)

    def test_a_hold_search_with_one_order_keeps_its_breakeven(self):
        out = self.plan([T.keyword('9', 'kraft cards', 'exact', T.STW, 0.40, 12, 1, 5)], [T.query('kraft cards', 1000, 500, 50, 12, 1)])
        p = self.kw(out, '9')
        self.assertEqual(p['role'], 'Hold')
        self.assertNotIn('mid_bid', p)
        self.assertEqual(p['new_bid'], p['breakeven_cpc'])

    def test_rate_limited_amazon_takes_soldscopes_mid(self):
        # Amazon not read yet: the run stops for it, naming the search
        with self.assertRaises(SystemExit) as cm:
            self.plan([KRAFT_KW], [KRAFT], suggested=T.SUGGESTED)
        self.assertEqual(cm.exception.code, 2)
        with open(os.path.join(self.run_dir, 'need_suggested_bids.json'), encoding='utf-8') as fh:
            self.assertIn('kraft cards', json.load(fh)['searches'])
        # Amazon rate-limited after its retry: SoldScope's middle cost per click
        out = self.plan([KRAFT_KW], [KRAFT], suggested=T.SUGGESTED,
                        extra={'bid_sources_tried.json': {'amazon': 'rate limited twice, 14:05 SGT'},
                               'soldscope_bids.json': {'kraft cards': [0.50, 0.88, 1.20]}})
        p = self.kw(out, '9')
        self.assertEqual((p['new_bid'], p['mid_bid']['source']), (0.88, 'soldscope'))
        self.assertIn('SoldScope', T.one(out, 'Bid change', keyword_id='9')['why'])

    def test_with_neither_the_mid_is_derived_from_its_own_cost_per_click(self):
        out = self.plan([KRAFT_KW], [KRAFT], suggested=T.SUGGESTED,
                        extra={'bid_sources_tried.json': {'amazon': 'no suggestion', 'soldscope': 'no cpc'}})
        p = self.kw(out, '9')
        # $8 on 20 clicks = $0.40; only two other Amazon mids, under the 3 the estimate's first tier needs
        self.assertEqual((p['new_bid'], p['mid_bid']['source']), (0.40, 'estimate'))
        self.assertIn('own cost per click', p['mid_bid']['priced_on'])

    def test_on_a_top_10_search_it_bids_75_percent_of_the_mid(self):
        steady = dict(keyword='kraft cards', ranks=[dict(date=f'2026-10-{d:02d}', organicRank=6) for d in range(5, 19)])
        out = self.plan([KRAFT_KW], [KRAFT], organic=True, extra={'radar_p1.json': dict(keywords=[steady])})
        self.assertIn('kraft cards', out['summary'][0]['organic']['top10'])
        p = self.kw(out, '9')
        self.assertEqual((p['new_bid'], p['mid_bid']['factor']), (round(0.95 * 0.75, 2), 0.75))

    def test_only_the_owning_copy_of_a_duplicate_bids_the_mid(self):
        copy = T.keyword('10', 'kraft cards', 'exact', T.BROAD, 0.40, 5, 0, 2)
        out = self.plan([KRAFT_KW, copy], [KRAFT])
        self.assertEqual(self.kw(out, '9')['new_bid'], 0.95)
        other = self.kw(out, '10')
        self.assertNotIn('mid_bid', other)
        self.assertEqual(other['mid_state'], 'copy')
        self.assertEqual(out['summary'][0]['mid_bid']['copies'], 1)

    def test_off_in_config_every_keyword_keeps_its_role_price(self):
        T.make_run(self.run_dir, queries=T.QUERIES + [KRAFT], keywords=[T.KEYWORDS[0], KRAFT_KW], suggested=AMAZON)
        out = planner.build(T.ASIN, T.product(), T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        self.assertNotIn('mid_bid', self.kw(out, '9'))
        self.assertIsNone(out['summary'][0]['mid_bid'])

    # ---- rule 2: the launch test ----------------------------------------------------------------------------------------
    LINEN = dict(AMAZON, **{'linen cards': [0.70, 1.10, 1.50]})

    def linen(self, clicks, orders, cvr=0.10, **kw):
        out = self.plan([launch('11', 'linen cards', clicks, orders)], suggested=self.LINEN, cvr=cvr, **kw)
        self.assertAlmostEqual(out['summary'][0]['asin_ad_cvr'], cvr, places=4)
        return out, self.kw(out, '11')

    def test_a_launch_keyword_with_no_orders_bids_the_mid_until_2_expected_orders_then_drops(self):
        # at 10% conversion the test ends at 20 clicks (decision 178; the brief's numbers)
        _, early = self.linen(19, 0)
        self.assertEqual((early['role'], early['new_bid'], early['mid_bid']['state']), ('Test', 1.10, 'testing'))
        out, late = self.linen(20, 0)
        self.assertNotIn('mid_bid', late)
        self.assertEqual(late['mid_state'], 'failed')
        self.assertLess(late['new_bid'], 1.10)   # back to its Test (breakeven) price
        self.assertTrue(late['action'].startswith('Test: economic starting bid'), late['action'])
        ended = out['summary'][0]['mid_bid']['ended']
        self.assertEqual([(e['keyword'], e['state'], e['spend90']) for e in ended], [('linen cards', 'failed', 8.0)])

    def test_on_a_5_percent_product_the_test_runs_to_40_clicks(self):
        _, p = self.linen(39, 0, cvr=0.05)
        self.assertEqual((p['new_bid'], p['mid_bid']['state']), (1.10, 'testing'))
        self.assertIn('40 clicks, 2 expected orders', T.one(self.plan([launch('11', 'linen cards', 39, 0, bid=0.5)],
                                                                      suggested=self.LINEN, cvr=0.05), 'Bid change',
                                                            keyword_id='11')['why'])
        self.assertEqual(self.linen(40, 0, cvr=0.05)[1]['mid_state'], 'failed')

    def test_a_keyword_in_its_test_is_not_paused_by_the_leak_check_but_a_failed_one_is(self):
        import test_organic_share as O
        losing = {'campaign_days.json': O.leaking(ordinary_orders=0)}
        _, testing = self.linen(30, 0, cvr=0.05, organic=True, extra=losing)   # 30 clicks, still under its 40
        self.assertEqual((testing['new_bid'], testing['mid_bid']['state']), (1.10, 'testing'))
        _, failed = self.linen(20, 0, organic=True, extra=losing)
        self.assertTrue(failed['action'].startswith('Pause: leak check'), failed['action'])

    def test_one_order_gets_more_clicks_at_the_mid_up_to_3_expected_orders(self):
        _, extended = self.linen(22, 1)
        self.assertEqual((extended['new_bid'], extended['mid_bid']['state']), (1.10, 'extended'))
        _, judged = self.linen(30, 1)
        self.assertNotIn('mid_bid', judged)
        self.assertEqual(judged['mid_state'], 'judged')
        # at 5%: testing to 40 clicks, extended to 60
        self.assertEqual(self.linen(50, 1, cvr=0.05)[1]['mid_bid']['state'], 'extended')
        self.assertEqual(self.linen(60, 1, cvr=0.05)[1]['mid_state'], 'judged')

    def test_a_broad_launch_keyword_reads_amazons_broad_mid(self):
        broad = launch('12', 'linen cards', 4, 0, match='broad', campaign=T.BROAD)
        with self.assertRaises(SystemExit):
            self.plan([broad], all_matches=True)
        with open(os.path.join(self.run_dir, 'need_suggested_bids.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['keywords'], [dict(text='linen cards', match_type='BROAD')])
        out = self.plan([broad], extra={mid_bid.MATCH_FILE: {'broad': {'linen cards': [0.5, 0.85, 1.1]}}}, all_matches=True)
        p = self.kw(out, '12')
        self.assertEqual((p['role'], p['new_bid'], p['mid_bid']['source']), ('Discovery', 0.85, 'amazon'))

    def test_since_decision_183_a_broad_launch_keyword_keeps_its_role_price(self):
        """Decision 183 (Kim, 2026-11-04, the visibility test made the rule): the mid prices SP exact keywords only, so
        a broad keyword in its launch test needs no broad suggestion and bids its role's price, not Amazon's broad mid."""
        broad = launch('12', 'linen cards', 4, 0, match='broad', campaign=T.BROAD)
        out = self.plan([broad], extra={mid_bid.MATCH_FILE: {'broad': {'linen cards': [0.5, 0.85, 1.1]}}})
        p = self.kw(out, '12')
        self.assertFalse(p.get('mid_bid'))
        self.assertNotEqual(p['new_bid'], 0.85)

    def test_two_orders_at_index_1_3_go_to_prove_first(self):
        foil = launch('13', 'foil cards', 5, 2)
        out = self.plan([foil], [FOIL], suggested=dict(AMAZON, **{'foil cards': [0.60, 0.90, 1.20]}))
        rec = next(r for r in out['terms'] if r['term'] == 'foil cards')
        self.assertIn('decision 177', rec['why'])
        p = self.kw(out, '13')
        self.assertEqual((p['role'], p['sub_role']), ('Rank', 'Prove first'))
        promo = [x for x in out['changes'] if x['type'] in ('New exact campaign', 'Reuse exact campaign')
                 and x.get('keyword') == 'foil cards']
        self.assertEqual([(x['role'], x['lane']) for x in promo], [('Prove first', 'auto')])

    def test_two_orders_at_index_1_2_go_to_prove_first_on_the_1_1_bar(self):
        # 2 purchases on 15 SQP clicks against a 10% market: index 1.20, under the old 1.25 bar (decision 178)
        out = self.plan([], [T.query('ink pens', 5000, 1000, 100, 15, 2)],
                        suggested=dict(AMAZON, **{'ink pens': [0.40, 0.50, 0.60]}))
        rec = next(r for r in out['terms'] if r['term'] == 'ink pens')
        self.assertEqual((rec['index'], rec['sub_role']), (1.2, 'Prove first'))
        row = T.one(out, 'New exact campaign', keyword='ink pens')
        self.assertEqual(row['lane'], 'auto', row['lane_reason'])

    def test_two_orders_under_index_0_8_go_to_trim(self):
        weak = T.query('foil cards', 1000, 100, 90, 9, 2)   # a 90% market: 2 of 9 trails it
        out = self.plan([launch('13', 'foil cards', 9, 2)], [weak])
        p = self.kw(out, '13')
        self.assertEqual(p['role'], 'Trim')
        self.assertNotIn('mid_bid', p)

    # ---- Sponsored Brands -----------------------------------------------------------------------------------------------
    def test_an_ai_sb_keyword_on_a_validated_search_bids_its_mid_times_the_sb_rank_ratio(self):
        camps = [dict(campaignId='sb1', name=f'Cards - {T.ASIN} - Videos - Highest Converting Search Terms - Exact - 1',
                      state='ENABLED', budget=10)]
        kws = [dict(keywordId='k9', campaignId='sb1', adGroupId='g1', keywordText='kraft cards', matchType='EXACT',
                    state='ENABLED', bid=0.30)]
        out = self.plan([KRAFT_KW], [KRAFT], cfg=T.product(auto=dict(AUTO), sb_video=dict(enabled=True, campaigns=['sb1'],
                                                                                        video_asset_id='asset')),
                        extra={'sb_campaigns_p1.json': dict(items=camps), 'sb_keywords_p1.json': dict(items=kws),
                               'sb_kw_perf.json': dict(data=[dict(keywordId='k9', clicks=6, purchases=1, cost=2)])},
                        all_matches=True)
        ratio = out['summary'][0]['sb_video']['sb_rank_ratio']
        change = T.one(out, 'SB bid change', keyword_id='k9')
        self.assertEqual(change['new'], round(0.95 * ratio, 2))
        self.assertEqual(change['mid_bid']['state'], 'validated')
        self.assertIn('decision 177', change['why'])
        self.assertIn('SB', [r['channel'] for r in out['summary'][0]['mid_bid']['rows']])


class MidBidUnitTest(unittest.TestCase):
    S = mid_bid.settings({'mid_bid': {'enabled': True}})

    def test_the_states(self):
        st = lambda role, clicks, orders, ladder=None, index=1.0, cvr=0.10: mid_bid.state(
            role, clicks, orders, orders if ladder is None else ladder, index, self.S, cvr)
        self.assertEqual(st('Hold', 40, 0, ladder=2), 'validated')
        self.assertIsNone(st('Hold', 40, 1))
        self.assertEqual(st('Test', 8, 2, index=1.05), 'validated')
        self.assertEqual(st('Test', 8, 2, index=1.3), 'validated')   # a search still Test here (too few searches) keeps the mid
        self.assertIsNone(st('Test', 8, 2, index=0.7))   # Trim's
        # 10%: 20 and 30 clicks
        self.assertEqual(st('Discovery', 19, 0), 'testing')
        self.assertEqual(st('Discovery', 20, 0), 'failed')
        self.assertEqual(st('Test', 19, 1), 'testing')
        self.assertEqual(st('Test', 20, 1), 'extended')
        self.assertEqual(st('Test', 29, 1), 'extended')
        self.assertEqual(st('Test', 30, 1), 'judged')
        # 20%: never under 15 clicks; 2%: never past 60 (90 with one order)
        self.assertEqual(st('Test', 14, 0, cvr=0.2), 'testing')
        self.assertEqual(st('Test', 15, 0, cvr=0.2), 'failed')
        self.assertEqual(st('Test', 15, 1, cvr=0.2), 'judged')
        self.assertEqual(st('Test', 59, 0, cvr=0.02), 'testing')
        self.assertEqual(st('Test', 60, 0, cvr=0.02), 'failed')
        self.assertEqual(st('Test', 89, 1, cvr=0.02), 'extended')
        self.assertEqual(st('Test', 90, 1, cvr=0.02), 'judged')
        self.assertEqual(mid_bid.test_ends(self.S, 0.05), (40, 60))
        for role in ('Rank', 'Defend', 'Trim', 'Leave', 'Negate'):
            self.assertIsNone(st(role, 5, 0))

    def test_the_source_chain(self):
        self.assertEqual(mid_bid.pick((0.5, 0.9, 1.2), [0.4, 0.8, 1.0], True, 0.3, 20, [], self.S)[:2], (0.9, 'amazon'))
        self.assertEqual(mid_bid.pick(None, [0.4, 0.8, 1.0], True, 0.3, 20, [], self.S)[:2], (0.8, 'soldscope'))
        self.assertEqual(mid_bid.pick(None, [0.4, 0.8, 1.0], False, 0.3, 20, [], self.S)[:2], (None, 'none'))
        # the estimate: the higher of its own cost per click (10+ clicks) and the median of 3+ Amazon mids...
        self.assertEqual(mid_bid.pick(None, None, True, 0.3, 20, [0.6, 0.7, 0.9], self.S)[:2], (0.7, 'estimate'))
        # ...then the same on any clicks or any one search
        self.assertEqual(mid_bid.pick(None, None, True, 0.3, 4, [0.6], self.S)[:2], (0.6, 'estimate'))
        self.assertEqual(mid_bid.pick(None, None, True, None, 0, [], self.S)[:2], (None, 'none'))

    def test_the_owner_is_the_copy_with_the_most_clicks(self):
        self.assertEqual(mid_bid.owners([('1', 'a', 'exact', 5, 0), ('2', 'a', 'exact', 9, 0), ('3', 'a', 'broad', 1, 0)]),
                         {('a', 'exact'): '2', ('a', 'broad'): '3'})

    def test_off_without_the_config_block(self):
        self.assertIsNone(mid_bid.settings({}))


if __name__ == '__main__':
    unittest.main()
