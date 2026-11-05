"""Seasonal products (season.py, and the planner's season handling in plan.py, plan_lanes.py, lanes.py,
placement_review.py and human_review.py).

The curve tests run on SoldScope's real 2025 Thanksgiving weeks (pulled 2026-10-20) and must give the dates of the
approved Oct 18 table in docs/seasonal-bidding.md section 2, and B0SAMP0010's approved plan in section 4 (rank build to
Nov 6, harvest from Nov 7, halve Nov 25, pause Nov 26, harvest sweeps Nov 9, 12, 16, 19 and 23). The planner tests reuse
test_plan_lanes' synthetic run folder.
"""
import copy
import datetime as dt
import os
import tempfile
import unittest

import human_review
import plan as planner
import season
import test_plan_lanes as T

D = dt.date.fromisoformat

# SoldScope weekly US searches, week-ending Saturdays from 2025-05-03 to 2026-01-10 (common_search_volume_batch, 2026-10-20)
FIRST_WEEK = D('2025-05-03')
THANKSGIVING_2025 = {
    'thanksgiving stickers': [128, 143, 170, 169, 139, 144, 221, 215, 191, 280, 382, 455, 506, 522, 598, 836, 879, 1217, 1763,
                              2412, 2560, 2701, 2851, 3678, 5847, 8498, 15468, 28504, 37359, 37642, 16754, 496, 273, 245,
                              160, 249, 260],
    'thanksgiving stickers for kids': [103, 46, 62, 64, 68, 30, 22, 25, 27, 96, 70, 102, 88, 73, 70, 93, 160, 183, 189, 263,
                                       353, 508, 893, 967, 1941, 3991, 6268, 15571, 16899, 15445, 5555, 104, 89, 87, 110,
                                       114, 93],
    'turkey stickers': [147, 159, 111, 141, 134, 101, 36, 41, 139, 135, 120, 126, 175, 138, 126, 145, 171, 251, 270, 282, 358,
                        371, 687, 665, 972, 1743, 2720, 6373, 9582, 11603, 4239, 233, 129, 87, 100, 117, 107],
    'happy thanksgiving stickers': [60, 97, 54, 26, 56, 61, 14, 16, 31, 96, 93, 99, 82, 90, 94, 66, 76, 124, 74, 175, 161, 167,
                                    200, 225, 321, 483, 776, 1740, 4185, 5224, 2656, 94, 103, 108, 87, 91, 90]}
RANK = ['thanksgiving stickers', 'thanksgiving stickers for kids', 'turkey stickers', 'happy thanksgiving stickers']


def soldscope_page(series_by_search, first=FIRST_WEEK):
    """The shape common_search_volume_batch returns."""
    return dict(data=[dict(keyword=k, marketplace='US', svHistory=[
        dict(event_date=(first + dt.timedelta(weeks=i)).isoformat(), search_volume=v) for i, v in enumerate(vs)])
        for k, vs in series_by_search.items()])


def volume():
    return season.read_volume(soldscope_page(THANKSGIVING_2025))


def thanksgiving_block(**kw):
    args = dict(rank_searches=RANK, holiday_key='thanksgiving', year=2026, today=D('2026-10-18'), index=0.9)
    args.update(kw)
    return season.season_block(volume(), **args)


class HolidayTest(unittest.TestCase):
    def test_holidays(self):
        self.assertEqual(season.holiday('thanksgiving', 2025), D('2025-11-27'))
        self.assertEqual(season.holiday('thanksgiving', 2026), D('2026-11-26'))
        self.assertEqual(season.holiday('thanksgiving', 2027), D('2027-11-25'))
        self.assertEqual(season.holiday('halloween', 2026), D('2026-10-31'))
        self.assertEqual(season.holiday('christmas', 2026), D('2026-12-25'))
        self.assertEqual(season.holiday('easter', 2026), D('2026-04-05'))
        self.assertEqual(season.holiday('easter', 2027), D('2027-03-28'))
        self.assertEqual(season.holiday('mothers_day', 2026), D('2026-05-10'))
        self.assertEqual(season.holiday('fathers_day', 2026), D('2026-06-21'))
        self.assertEqual(season.holiday('valentines', 2027), D('2027-02-14'))
        with self.assertRaises(ValueError):
            season.holiday('diwali', 2026)


class ReadVolumeTest(unittest.TestCase):
    def test_raw_page_and_compact_shapes(self):
        raw = season.read_volume(soldscope_page({'Turkey Stickers': [5, 7]}))
        self.assertEqual(raw, {'turkey stickers': [(D('2025-05-03'), 5), (D('2025-05-10'), 7)]})
        compact = season.read_volume({'turkey stickers': [['2025-05-10', 7], ['2025-05-03', 5]], '_note': 'x'})
        self.assertEqual(compact, raw)
        pages = season.read_volume([soldscope_page({'a': [1]}), soldscope_page({'b': [2]})])
        self.assertEqual(sorted(pages), ['a', 'b'])

    def test_unknown_keyword_has_empty_history(self):
        self.assertEqual(season.read_volume(dict(data=[dict(keyword='nothing', svHistory=[])])), {'nothing': []})


class CurveTest(unittest.TestCase):
    def test_one_search_matches_the_oct_18_table(self):
        c = season.curve(volume()['thanksgiving stickers'], D('2025-11-27'))
        self.assertEqual(c['up20'], D('2025-10-25'))
        self.assertEqual(c['up50'], D('2025-11-08'))
        self.assertEqual(c['peak'], D('2025-11-22'))
        self.assertEqual(c['peak_searches'], 37642)
        self.assertEqual(c['weeks_20'], 6)
        self.assertEqual(c['window80'], (D('2025-10-19'), D('2025-11-29')))

    def test_every_thanksgiving_search_matches_the_table(self):
        table = {'thanksgiving stickers for kids': ('2025-10-25', '2025-11-08', '2025-11-15', 6, '2025-10-19', '2025-11-22'),
                 'turkey stickers': ('2025-11-01', '2025-11-08', '2025-11-22', 5, '2025-10-26', '2025-11-29'),
                 'happy thanksgiving stickers': ('2025-11-08', '2025-11-15', '2025-11-22', 4, '2025-10-26', '2025-11-29')}
        for search, (up20, up50, peak, weeks, start, end) in table.items():
            c = season.curve(volume()[search], D('2025-11-27'))
            self.assertEqual((c['up20'], c['up50'], c['peak'], c['weeks_20'], c['window80']),
                             (D(up20), D(up50), D(peak), weeks, (D(start), D(end))), search)

    def test_no_season_in_the_window(self):
        self.assertIsNone(season.curve([], D('2025-11-27')))
        flat = [(FIRST_WEEK + dt.timedelta(weeks=i), 100) for i in range(37)]
        self.assertIsNone(season.curve(flat, D('2025-11-27')))


class SeasonBlockTest(unittest.TestCase):
    def test_b0h6j5rwdc_dates_match_the_approved_plan(self):
        b = thanksgiving_block()
        self.assertEqual(b['holiday'], '2026-11-26')
        self.assertEqual(b['reference_season'], 2025)
        self.assertEqual(b['rank_build_end'], '2026-11-06')     # the plan: rank build to Nov 6
        self.assertEqual(b['last_mile'], '2026-11-25')          # halve Nov 25
        self.assertEqual(b['pause'], '2026-11-26')              # pause Nov 26
        self.assertEqual(b['rank_build_start'], '2026-10-18')   # the 80%-of-volume window opens (2025: Oct 19)
        self.assertEqual(b['wake'], '2026-10-04')               # two weeks before the rank build
        self.assertEqual(b['review_by'], '2026-12-10')
        self.assertEqual(b['next_wake'], '2027-10-03')
        self.assertEqual(b['season_end'], '2026-11-28')
        self.assertIs(b['rank_build'], True)
        self.assertIs(b['payback']['passed'], True)
        self.assertEqual(b['rank_searches'], RANK)
        self.assertEqual(b['stop_loss_weeks'], [2, 4])
        self.assertEqual(b['invest_cap'], 600)
        self.assertEqual(b['curves']['thanksgiving stickers']['up50'], '2025-11-08')
        self.assertNotIn('phase_applied', b)  # a person records it when the phase's changes are applied

    def test_payback_test(self):
        self.assertIs(thanksgiving_block(index=0.6)['rank_build'], False)
        self.assertIn('0.6', ' '.join(thanksgiving_block(index=0.6)['payback']['reasons']))
        unknown = thanksgiving_block(index=None)
        self.assertIsNone(unknown['payback']['passed'])
        self.assertIs(unknown['rank_build'], False)  # nobody has judged the index: no rank build until a person does
        late = thanksgiving_block(today=D('2026-11-07'))
        self.assertIs(late['rank_build'], False)
        self.assertIn('passed', ' '.join(late['payback']['reasons']))
        decided = thanksgiving_block(index=None, rank_build=True, decided_by='Kim, 2026-10-18')
        self.assertIs(decided['rank_build'], True)
        self.assertEqual(decided['payback']['decided_by'], 'Kim, 2026-10-18')

    def test_short_season_after_the_rank_build_fails(self):
        # only two weeks of searches after the 50% week: the rank build can't pay back
        cut = {k: v[:30] + [0] * 7 for k, v in THANKSGIVING_2025.items()}
        b = season.season_block(season.read_volume(soldscope_page(cut)), RANK, 'thanksgiving', 2026, D('2026-10-18'), index=0.9)
        self.assertIs(b['rank_build'], False)
        self.assertIn('weeks of season', ' '.join(b['payback']['reasons']))

    def test_overrides_win_and_are_checked(self):
        b = thanksgiving_block(overrides={'last_mile': '2026-11-20'})
        self.assertEqual(b['last_mile'], '2026-11-20')
        self.assertEqual(b['overrides'], {'last_mile': '2026-11-20'})
        with self.assertRaises(ValueError):
            thanksgiving_block(overrides={'last_mile': '2026-11-01'})  # before the rank build ends

    def test_missing_rank_search_is_reported(self):
        b = thanksgiving_block(rank_searches=RANK + ['pilgrim stickers'])
        self.assertEqual(b['missing_volume'], ['pilgrim stickers'])
        with self.assertRaises(ValueError):
            thanksgiving_block(rank_searches=['pilgrim stickers'])

    def test_this_year_against_last(self):
        # 2024-10-26 had 200 searches; 2025-10-25, the latest week and 6 days before Halloween like it, has 300
        two_years = {'x': [10] * 20 + [100, 200] + [10] * 50 + [150, 300]}
        vol = season.read_volume(soldscope_page(two_years, first=D('2024-06-01')))
        self.assertEqual(season.yoy(vol['x'], D('2024-10-31'), D('2025-10-31')), 1.5)
        self.assertIsNone(season.yoy(vol['x'][:30], D('2024-10-31'), D('2025-10-31')))  # no week of this season yet


BLOCK = season.season_block(volume(), RANK, 'thanksgiving', 2026, D('2026-10-18'), index=0.9)


class PhaseTest(unittest.TestCase):
    def test_phases_through_the_season(self):
        expect = {'2026-10-03': 'asleep', '2026-10-04': 'wake', '2026-10-17': 'wake', '2026-10-18': 'rank build',
                  '2026-11-06': 'rank build', '2026-11-07': 'harvest', '2026-11-24': 'harvest', '2026-11-25': 'last mile',
                  '2026-11-26': 'off', '2026-11-27': 'review', '2026-12-10': 'review', '2026-12-11': 'asleep'}
        for day, phase in expect.items():
            self.assertEqual(season.phase_of(BLOCK, D(day))[0], phase, day)
        self.assertEqual(season.phase_of(BLOCK, D('2026-12-11'))[1:], ('wake', D('2027-10-03')))
        self.assertEqual(season.phase_of(BLOCK, D('2026-11-01'))[1:], ('harvest', D('2026-11-07')))

    def test_no_rank_build_means_harvest(self):
        b = dict(BLOCK, rank_build=False)
        self.assertEqual(season.phase_of(b, D('2026-10-20'))[0], 'harvest')

    def test_a_longer_last_mile(self):
        b = dict(BLOCK, last_mile='2026-11-22')  # e.g. Christmas: the delivery cut-off, then floor budgets to the holiday
        self.assertEqual(season.phase_of(b, D('2026-11-23'))[0], 'last mile')


class StateTest(unittest.TestCase):
    def test_evergreen_product_has_no_state(self):
        self.assertIsNone(season.state({}, D('2026-10-20')))

    def test_harvest_mode_without_a_block(self):
        s = season.state({'mode': 'harvest'}, D('2026-10-20'))
        self.assertEqual((s['phase'], s['plan'], s['harvest'], s['rank_searches'], s['switch']), ('harvest', True, True, [], None))
        self.assertIsNone(s['stop_loss_weeks'])

    def test_rank_build_and_its_switch(self):
        s = season.state({'season': BLOCK}, D('2026-10-20'))
        self.assertEqual((s['phase'], s['plan'], s['harvest']), ('rank build', True, False))
        self.assertEqual(s['rank_searches'], RANK)
        self.assertEqual(s['stop_loss_weeks'], [2, 4])
        self.assertIn('rank build', s['switch'])
        same = season.state({'season': dict(BLOCK, phase_applied='rank build')}, D('2026-10-20'))
        self.assertIsNone(same['switch'])
        nxt = season.state({'season': dict(BLOCK, phase_applied='rank build')}, D('2026-11-07'))
        self.assertEqual((nxt['phase'], nxt['harvest'], nxt['rank_searches']), ('harvest', True, []))
        self.assertEqual(nxt['switch'], 'rank build -> harvest')

    def test_harvest_mode_overrides_a_rank_build(self):
        s = season.state({'season': BLOCK, 'mode': 'harvest'}, D('2026-10-20'))
        self.assertEqual((s['phase'], s['harvest'], s['rank_searches']), ('harvest', True, []))

    def test_harvest_mode_plans_before_the_wake_but_not_after_the_season(self):
        # the Christmas cards: onboarded in harvest mode in late October, before their searches wake in November
        early = season.state({'season': BLOCK, 'mode': 'harvest'}, D('2026-09-20'))
        self.assertEqual((early['phase'], early['plan'], early['next']), ('harvest', True, dict(phase='last mile', on='2026-11-25')))
        for day in ('2026-11-25', '2026-11-26', '2026-12-01', '2026-12-20'):
            self.assertIs(season.state({'season': BLOCK, 'mode': 'harvest'}, D(day))['plan'], False, day)

    def test_unplanned_phases(self):
        for day, phase in (('2026-10-01', 'asleep'), ('2026-11-25', 'last mile'), ('2026-11-26', 'off'), ('2026-12-01', 'review')):
            s = season.state({'season': BLOCK}, D(day))
            self.assertEqual((s['phase'], s['plan']), (phase, False), day)
            self.assertIsNone(s['switch'])


class OpenItemsTest(unittest.TestCase):
    def test_dated_steps(self):
        items = season.open_items(BLOCK, D('2026-10-20'), run_id='season-test', owner='Sam (book owner)',
                                  approval='Kim, 2026-10-20 SGT: the season plan')
        due = {}
        for x in items:
            due.setdefault(x['due'], []).append(x['short'])
            w = x['workflow']
            self.assertEqual((w['lane'], w['run_id'], w['source_text'], w['due'], x['status']),
                             ('scheduled', 'season-test', x['text'], x['due'], 'open'))
            self.assertGreaterEqual(x['due'], '2026-10-20')
        self.assertTrue(any('Stop-loss' in s for s in due['2026-11-01']))      # 2 weeks into the rank build
        self.assertNotIn('2026-11-15', due)                                     # week 4 falls after the rank build ends
        self.assertTrue(any('Harvest' in s for s in due['2026-11-07']))
        sweeps = sorted(d for d, ss in due.items() if any(s.startswith('Harvest sweep') for s in ss))
        self.assertEqual(sweeps, ['2026-11-09', '2026-11-12', '2026-11-16', '2026-11-19', '2026-11-23'])
        self.assertTrue(any('Halve' in s for s in due['2026-11-25']))
        self.assertTrue(any('Pause' in s for s in due['2026-11-26']))
        self.assertTrue(any('review' in s.lower() for s in due['2026-12-10']))
        self.assertTrue(any('Wake' in s for s in due['2027-10-03']))
        self.assertNotIn('2026-10-04', due)  # already past


# ---------------------------------------------------------------------------------------------------- the planner
PLANNER_BLOCK = dict(name='Test season 2026', holiday_key='thanksgiving', holiday='2026-11-26', wake='2026-10-04',
                     rank_build_start='2026-10-18', rank_build_end='2026-11-06', last_mile='2026-11-25', pause='2026-11-26',
                     review_by='2026-12-10', next_wake='2027-10-03', season_end='2026-11-28', rank_build=True,
                     rank_searches=['gold cards', 'zebra stickers'], evergreen_searches=[], invest_cap=600,
                     stop_loss_weeks=[2, 4])
SUGGESTED = dict(T.SUGGESTED, **{'gold cards': [0.40, 0.60, 0.90], 'zebra stickers': [0.30, 0.45, 0.70]})


class SeasonPlannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = os.path.join(tmp.name, 'run')

    def plan(self, cfg, today=T.TODAY, write_out=True, **run):
        run.setdefault('suggested', SUGGESTED)
        T.make_run(self.run_dir, **run)
        out = planner.build(T.ASIN, cfg, T.shared_config(), self.run_dir, 'weekly', today, now_utc=T.NOW)
        if write_out:
            planner.write_outputs(self.run_dir, out, T.shared_config(), T.ASIN)
        return out

    def terms(self, out):
        return {t['term']: t for t in out['terms']}

    def test_evergreen_product_is_unchanged(self):
        out = self.plan(T.product())
        self.assertIsNone(out['summary'][0]['season'])
        self.assertEqual(self.terms(out)['blank cards']['role'], 'Rank')
        self.assertEqual(len(T.by_type(out, 'New exact campaign')), 1)

    def test_harvest_mode_invests_in_nothing(self):
        cfg = T.product(mode='harvest', invest_log={'thank you cards': {'since': '2026-08-01'}})
        out = self.plan(cfg)
        terms = self.terms(out)
        self.assertEqual((terms['blank cards']['role'], terms['thank you cards']['role']), ('Defend', 'Defend'))
        self.assertEqual(T.by_type(out, 'New exact campaign') + T.by_type(out, 'Reuse exact campaign'), [])
        self.assertEqual(T.by_type(out, 'Stop-loss review'), [])  # harvest has no stop-loss: nothing is invested
        skc = next(p for p in out['keyword_plan'] if p['keyword_id'] == '1')
        self.assertTrue(skc['action'].startswith('Hold at breakeven'), skc['action'])
        tos = T.one(out, 'Budget and top of search', campaign_id='105')
        self.assertEqual((tos['tos_now'], tos['tos'], tos['budget'], tos['budget_now'], tos['season_harvest']), (50, 0, 10, 10, True))
        self.assertEqual(tos['lane'], 'auto')  # the season's own rule: it applies on its own since 2026-10-22 (decision 98)
        self.assertEqual(out['summary'][0]['season']['phase'], 'harvest')
        updates = T.read_payloads(self.run_dir, 'auto')['5_campaign_updates.json']
        top = next(u for u in updates if u['campaignId'] == '105')
        self.assertEqual(top['dynamicBidding']['placementBidding'][0], dict(placement='PLACEMENT_TOP', percentage=0))

    def test_rank_build_invests_only_in_the_season_searches(self):
        out = self.plan(T.product(season=PLANNER_BLOCK))
        terms = self.terms(out)
        self.assertEqual(terms['blank cards']['role'], 'Defend')     # beats the market, but it isn't a season search
        self.assertEqual((terms['gold cards']['role'], terms['gold cards']['sub_role']), ('Rank', 'Invest'))
        self.assertEqual((terms['zebra stickers']['role'], terms['zebra stickers']['sub_role']), ('Rank', 'Invest'))
        self.assertEqual(sorted(x['keyword'] for x in T.by_type(out, 'New exact campaign')), ['gold cards', 'zebra stickers'])
        self.assertEqual(T.one(out, 'Budget and top of search', campaign_id='105')['tos'], 0)  # 'thank you cards' isn't one
        s = out['summary'][0]['season']
        self.assertEqual((s['phase'], s['name'], s['invest_cap']), ('rank build', 'Test season 2026', 600))
        self.assertIn('rank build', s['switch'])
        # a phase switch is no longer a person's call (autonomous runs, 2026-10-22, decision 98): its rows are judged as
        # usual, and the summary still names the switch
        self.assertFalse(any('season phase' in x['lane_reason'] for x in out['changes']))
        self.assertEqual(T.one(out, 'Budget and top of search', campaign_id='105')['lane'], 'auto')
        # a phase switch's rows are the book owner's since 2026-10-22 (Lee's level before), its promotions too: no
        # money level since decision 99
        levels = dict(zip([x['row_id'] for x in out['changes']], human_review.row_levels(out)))
        self.assertEqual(set(levels.values()), {'owner'}, levels)

    def test_rank_build_season_search_over_the_rank_cap_is_not_invested_in(self):
        # decision 185 (Kim, 2026-11-04, "Yes, cap seasonal too"): B0SAMP0010's "thanksgiving stickers" peaked at 37,642
        # searches a week, far over the 2,400-a-month cap, and was still an Invest rank build search
        block = dict(PLANNER_BLOCK, curves={'zebra stickers': dict(peak_searches=9000), 'gold cards': dict(peak_searches=100)})
        keywords = T.KEYWORDS + [T.keyword('9', 'zebra stickers', 'exact', T.STW, 0.80, 20, 2, 2)]
        out = self.plan(T.product(season=block, rank_max_monthly_searches=2400), keywords=keywords)  # fixture has no cap
        terms = self.terms(out)
        zebra = terms['zebra stickers']
        self.assertEqual((zebra['role'], zebra['over_rank_cap']), ('Defend', True))
        self.assertTrue(any(s.startswith('season peak 39,000') for s in zebra['rank_cap_sources']), zebra['rank_cap_sources'])
        self.assertIn('decision 185', zebra['why'])
        self.assertEqual((terms['gold cards']['role'], terms['gold cards']['sub_role']), ('Rank', 'Invest'))  # 433 a month
        self.assertEqual(sorted(x['keyword'] for x in T.by_type(out, 'New exact campaign')), ['gold cards'])
        kw = next(p for p in out['keyword_plan'] if p['keyword_id'] == '9')   # its exact keyword: suggested low, not under breakeven
        self.assertTrue(kw['action'].startswith('Big search over the rank cap'), kw['action'])
        self.assertEqual(kw['new_bid'], max(0.30, kw['breakeven_cpc']))

    def test_rank_build_logged_search_over_the_rank_cap_steps_down(self):
        # decision 185: B0SAMP0010's logged "thanksgiving stickers" (over the cap) kept +50% top of search and $12/day in
        # its rank build, because the cap step-down skipped every seasonal product
        block = dict(PLANNER_BLOCK, rank_searches=['thank you cards', 'gold cards'],
                     curves={'thank you cards': dict(peak_searches=9000)})
        cfg = T.product(season=block, rank_max_monthly_searches=2400,
                        invest_log={'thank you cards': dict(since='2026-10-18', role='Invest', organic_then=0)})
        out = self.plan(cfg)
        self.assertEqual(self.terms(out)['thank you cards']['role'], 'Defend')
        [entry] = [s for s in out['stop_loss'] if s['keyword'] == 'thank you cards' and s.get('over_rank_cap')]
        self.assertEqual((entry['slip'], entry['step_down']), (False, 'written'))
        camp = next(c for c in out['changes'] if c.get('keyword') == 'thank you cards' and c['type'] == 'Budget and top of search')
        self.assertEqual((camp['tos'], camp['budget']), (0, 5))

    def test_a_recorded_phase_is_not_a_switch(self):
        out = self.plan(T.product(season=dict(PLANNER_BLOCK, phase_applied='rank build')))
        self.assertIsNone(out['summary'][0]['season']['switch'])
        self.assertFalse(any('season phase' in x['lane_reason'] for x in out['changes']))

    def test_season_exact_keyword_without_market_data_holds_at_breakeven(self):
        evergreen = next(p for p in self.plan(T.product())['keyword_plan'] if p['keyword_id'] == '6')
        self.assertTrue(evergreen['action'].startswith('Test'), evergreen['action'])
        seasonal = next(p for p in self.plan(T.product(season=PLANNER_BLOCK))['keyword_plan'] if p['keyword_id'] == '6')
        self.assertTrue(seasonal['action'].startswith('Hold at breakeven'), seasonal['action'])
        self.assertEqual(seasonal['new_bid'], seasonal['breakeven_cpc'])

    def test_season_exact_keyword_left_at_a_low_bid_holds_at_breakeven(self):
        # B0SAMP0010's "thanksgiving sticker" (dry run 2026-10-21): orders as a keyword, none as its own search term
        keywords = T.KEYWORDS + [T.keyword('9', 'random search', 'exact', T.STW, 0.50, 3, 0, 2)]
        evergreen = next(p for p in self.plan(T.product(), keywords=keywords)['keyword_plan'] if p['keyword_id'] == '9')
        self.assertTrue(evergreen['action'].startswith('Leave'), evergreen['action'])
        seasonal = next(p for p in self.plan(T.product(season=PLANNER_BLOCK), keywords=keywords)['keyword_plan']
                        if p['keyword_id'] == '9')
        self.assertTrue(seasonal['action'].startswith('Hold at breakeven'), seasonal['action'])
        self.assertEqual(seasonal['new_bid'], seasonal['breakeven_cpc'])

    def test_a_seasonal_product_plans_without_sqp(self):
        out = self.plan(T.product(season=PLANNER_BLOCK), queries=[], data_through=None)
        self.assertEqual(out['summary'][0]['inputs']['sqp'], 0)
        self.assertEqual(self.terms(out)['zebra stickers']['role'], 'Rank')
        self.assertIsNone(out['summary'][0]['stale_reason'])  # no SQP to be stale: a new seasonal listing has none
        with self.assertRaises(SystemExit):
            self.plan(T.product(), queries=[])

    def test_last_season_sqp_prices_a_seasonal_search(self):
        # decision 172 (Kim, 2026-10-30, "use last season's sqp"): a seasonal product's search is priced on this season's
        # SQP plus last season's same weeks; organic, volume and the evergreen product stay on this year's rows
        last = dict(Meta=dict(data_through='2025-11-29'),
                    Queries=[T.query('gold cards', 4000, 900, 180, 60, 18), T.query('not searched now', 900, 100, 10, 5, 1)])
        base = self.terms(self.plan(T.product(season=PLANNER_BLOCK)))['gold cards']
        out = self.plan(T.product(season=PLANNER_BLOCK), extra={'last_season_sqp_p1.json': last})
        gold = self.terms(out)['gold cards']
        self.assertEqual((gold['last_season_clicks'], gold['last_season_purchases']), (60, 18))
        self.assertEqual((gold['sqp_our_clicks'], gold['sqp_our_purchases']), (30, 0))      # this year's own
        self.assertEqual(gold['sqp_volume'], base['sqp_volume'])
        self.assertGreater(gold['cvr_price'], base['cvr_price'])   # 18 purchases on 90 clicks, not 0 on 30
        self.assertGreater(gold['be_cpc'], base['be_cpc'])
        self.assertNotIn('not searched now', self.terms(out))   # last season only informs this season's searches
        self.assertEqual(out['summary'][0]['last_season_sqp'], dict(searches=2, data_through='2025-11-29'))
        evergreen = self.plan(T.product(), extra={'last_season_sqp_p1.json': last})
        self.assertIsNone(self.terms(evergreen)['gold cards']['last_season_clicks'])
        self.assertIsNone(evergreen['summary'][0]['last_season_sqp'])

    def test_rank_build_budgets_past_the_cap_are_named(self):
        fine = self.plan(T.product(season=PLANNER_BLOCK))['summary'][0]['season']
        self.assertEqual((fine['rank_build_days_left'], fine['rank_build_budget_to_end'], fine['over_invest_cap']), (19, 380, False))
        over = self.plan(T.product(season=dict(PLANNER_BLOCK, invest_cap=300)))['summary'][0]['season']
        self.assertIs(over['over_invest_cap'], True)
        self.assertIn('$300 cap', over['text'])

    def test_seasonal_stop_loss_comes_at_two_weeks(self):
        log = {'gold cards': {'since': '2026-10-04', 'rank_then': 30}}
        seasonal = self.plan(T.product(season=PLANNER_BLOCK, invest_log=log))
        self.assertEqual([x['keyword'] for x in T.by_type(seasonal, 'Stop-loss review')], ['gold cards'])
        evergreen = self.plan(T.product(invest_log=log))
        # no checkpoint is due on an evergreen product at two weeks; the only review is decision 182's index slip (gold
        # cards trails the market), held because the fixture has no exact keyword of it to step down
        self.assertEqual([('decision 182' in x['why']) for x in T.by_type(evergreen, 'Stop-loss review')], [True])

    def test_unplanned_phase_plans_nothing(self):
        for day in ('2026-11-26', '2026-11-25', '2026-10-01'):
            with self.assertRaises(SystemExit) as cm:
                self.plan(T.product(season=PLANNER_BLOCK), today=day, write_out=False)
            self.assertIn('Nothing planned', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
