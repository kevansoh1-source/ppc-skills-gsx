"""The stop-loss judges an invest search on what it is for, gains we don't pay for: organic rank (Rank Radar) and organic
purchases (SQP purchases less ad orders), at months 3, 6, 9 and 12 of investing (Kim, 2026-10-26, decision 142: "count
the organic rank and organic sales only, its correct. but ranking horizon is now around 10 to 12 months on amazon.. not
just 4-6 weeks"). SQP impression share no longer counts: it includes the impressions we buy.

Built on test_plan_lanes' synthetic run; TODAY is 2026-10-19. "thank you cards" is the fixture's Invest search; its
owner keyword bids $2.00 here, so a step-down has a cut to write.
"""
import datetime as dt
import unittest

import plan as planner
import test_plan_lanes as T

TERM = 'thank you cards'
HIGH = [k for k in T.KEYWORDS if k['KeywordId'] != '1'] + [T.keyword('1', TERM, 'exact', T.SKC, 2.00, 40, 8, 30)]


def since(days):
    """The start date that makes TODAY day `days` of investing."""
    return (dt.date.fromisoformat(T.TODAY) - dt.timedelta(days=days)).isoformat()


def radar(*ranks):
    """Rank Radar readings in the week to TODAY: the planner takes their median."""
    days = ('2026-10-15', '2026-10-17', '2026-10-18')
    return {'radar_p1.json': dict(keywords=[dict(keyword=TERM, ranks=[dict(date=d, organicRank=r) for d, r in zip(days, ranks)])])}


class CheckpointDaysTest(unittest.TestCase):
    def test_the_checkpoints_fall_on_these_days(self):
        self.assertEqual([planner.checkpoint_days(m) for m in (3, 6, 9, 12)], [91, 182, 274, 365])


class StopLossCheckpointTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = T.PlannerLanesTest.plan

    def run_with(self, **log):
        extra, queries = log.pop('extra', None), log.pop('queries', None)
        return self.plan(cfg=T.product(invest_log={TERM: dict(role='Invest', **log)}), keywords=HIGH, extra=extra, queries=queries)

    def step_downs(self, out):
        return [x for x in out['changes'] if x.get('stop_loss_step_down')]

    def test_before_month_3_a_search_is_not_judged(self):
        # day 60, no gain on anything: under the old 4-week rule this stepped down
        out = self.run_with(since=since(60), organic_then=0, rank_then=40, extra=radar(45, 50, 55))
        self.assertEqual(out['stop_loss'], [])
        self.assertEqual(self.step_downs(out), [])

    def test_no_organic_gain_at_month_3_steps_down_even_with_impression_share_up(self):
        # SQP impression share 0.001 then, 0.01 now: up, but it counts paid impressions, so it is no gain
        out = self.run_with(since=since(96), organic_then=0, imp_share_then=0.001)
        [stop] = out['stop_loss']
        self.assertEqual((stop['checkpoint'], stop['against'], stop['gains'], stop['readable'], stop['step_down']),
                         (3, 'its start', [], 1, 'written'))
        self.assertNotIn('imp_share_then', stop)
        rows = self.step_downs(out)
        self.assertEqual(sorted(x['type'] for x in rows), ['Bid change', 'Budget and top of search'])
        for x in rows:
            self.assertEqual(x['lane_reason'], 'invested 96 days (the month 3 checkpoint) with no gain since its start in organic '
                                               'rank (None -> None) or organic purchases (0 -> 0)')

    def test_an_organic_purchase_gain_passes_the_checkpoint(self):
        # 12 SQP purchases less the 8 ad orders: 4 organic, up from 0
        queries = [q for q in T.QUERIES if q['Query'] != TERM] + [T.query(TERM, 1500, 600, 60, 40, 12)]
        out = self.run_with(since=since(96), organic_then=0, queries=queries)
        self.assertEqual(out['stop_loss'][0]['gains'], ['organic purchases 0 -> 4'])
        self.assertEqual(self.step_downs(out), [])

    def test_a_rank_radar_gain_passes_the_checkpoint(self):
        out = self.run_with(since=since(96), organic_then=0, rank_then=40, extra=radar(22, 20, 18))
        self.assertEqual(out['stop_loss'][0]['gains'], ['organic rank 40 -> 20'])
        self.assertEqual(self.step_downs(out), [])

    def test_a_passed_checkpoint_is_not_judged_again_before_the_next(self):
        out = self.run_with(since=since(150), organic_then=0, rank_then=40, checkpoint=3, checkpoint_rank=20,
                            checkpoint_organic=0, extra=radar(45, 50, 55))
        self.assertEqual(out['stop_loss'], [])
        self.assertEqual(self.step_downs(out), [])

    def test_the_next_checkpoint_judges_against_the_last_ones_reading(self):
        # rank 25 is better than its start (40) but worse than month 3's reading (20): no gain since month 3
        out = self.run_with(since=since(190), organic_then=0, rank_then=40, checkpoint=3, checkpoint_rank=20,
                            checkpoint_organic=0, extra=radar(24, 25, 26))
        [stop] = out['stop_loss']
        self.assertEqual((stop['checkpoint'], stop['against'], stop['rank_base'], stop['rank_now'], stop['gains']),
                         (6, 'the month 3 checkpoint', 20, 25, []))
        self.assertEqual(stop['step_down'], 'written')
        self.assertTrue(all(x['lane_reason'].startswith('invested 190 days (the month 6 checkpoint) with no gain since the month 3 '
                                                        'checkpoint in organic rank (20 -> 25)') for x in self.step_downs(out)))

    def test_a_search_first_judged_late_is_judged_at_the_latest_checkpoint_it_passed(self):
        out = self.run_with(since=since(200), organic_then=0, rank_then=40, extra=radar(22, 20, 18))
        self.assertEqual((out['stop_loss'][0]['checkpoint'], out['stop_loss'][0]['against']), (6, 'its start'))

    def test_after_month_12_there_is_no_checkpoint(self):
        out = self.run_with(since=since(400), organic_then=0, checkpoint=12, checkpoint_organic=0)
        self.assertEqual(out['stop_loss'], [])

    def test_neither_measure_readable_is_held_for_a_person(self):
        out = self.run_with(since=since(96))   # no organic baseline, no Rank Radar
        self.assertEqual(out['stop_loss'][0]['step_down'], 'review')
        self.assertEqual(self.step_downs(out), [])
        row = T.one(out, 'Stop-loss review', keyword=TERM)
        self.assertEqual(row['lane'], 'monitor')
        self.assertIn('neither organic rank nor organic purchases can be read against its start', row['why'])


if __name__ == '__main__':
    unittest.main()


class StepDownToTheLowTest(unittest.TestCase):
    """stop_loss.step_down with bid_to (decision 182): the higher of breakeven and the suggested low, never above the live bid."""
    def run_one(self, existing_new, bid=0.47, be=0.38, low=0.73):
        import stop_loss
        changes = [] if existing_new is None else [dict(type='Bid change', keyword_id='7', current=bid, new=existing_new)]
        owner = dict(keyword_id='7', campaign_id='70', breakeven_cpc=be, bid=bid, campaign='c', family='SKC')
        stop_loss.step_down(changes, lambda **r: changes.append(r), 'calendar for kids', owner, 'over the cap',
                            lambda cid: (None, None, None), budget_to=5, bid_to=low)
        return [c for c in changes if c.get('type') == 'Bid change']

    def test_an_existing_mid_row_goes_back_to_the_live_bid(self):
        [row] = self.run_one(0.97)
        self.assertEqual(row['new'], 0.47)

    def test_no_bid_row_when_the_live_bid_is_under_the_low(self):
        self.assertEqual(self.run_one(None), [])

    def test_a_bid_over_the_low_steps_to_the_low(self):
        [row] = self.run_one(None, bid=1.06, be=0.22, low=0.55)
        self.assertEqual(row['new'], 0.55)
