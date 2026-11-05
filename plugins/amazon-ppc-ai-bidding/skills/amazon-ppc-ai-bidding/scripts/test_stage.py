"""stage.py: the data stage, the volatile SQP week, the volume fallback, the product-market fallback index and the
head-term flags (docs/superpowers/specs/2026-10-21-keyword-selection-by-data-stage-design.md, sections 4.1 to 4.6).

The figures come from the spec's gel pens example (B0SAMP0026; 159 queries, 214 clicks through 2026-10-10, 462 through
2026-10-17; 'colored gel pens fine tip' 3 orders on 6 clicks against a 14.6% product market conversion).
"""
import datetime as dt
import unittest

import stage

TODAY = '2026-10-22'

CFG = {
    'thresholds': {'trusted_min_clicks': 10},
    'launch': {'sqp_min_queries': 10, 'rank_count': 5, 'min_relevancy': 0.5, 'amazon_top_rank': 20},
    'stage': {'early_max_observed_days': 28, 'early_min_trusted_queries': 5, 'auto_min_observed_days': 14,
              'volatile_week_ratio': 1.0, 'full_window_days': 77},
}
# a config from before full_window_days (2026-10-22): the 84-day default applies
CFG_NO_FULL_WINDOW = {**CFG, 'stage': {k: v for k, v in CFG['stage'].items() if k != 'full_window_days'}}


def query(text, volume, total_clicks, total_purchases, asin_clicks, asin_purchases, observed_days=84, impressions=100):
    return dict(ASIN='B0SAMP0026', Query=text, QueryVolume=volume, TotalClicks=total_clicks,
                TotalPurchase=total_purchases, AsinClicks=asin_clicks, AsinPurchase=asin_purchases,
                AsinImpressions=impressions, TotalImpressions=10000, QueryObservedDayCount=observed_days)


def rows(n, observed_days=84, trusted=0):
    """n SQP rows with impressions: the first `trusted` carry 12 of our clicks (over the 10-click bar), the rest 1."""
    return [query(f'search {i}', 500, 1000, 50, 12 if i < trusted else 1, 0, observed_days) for i in range(n)]


def days_ago(n):
    return (dt.date.fromisoformat(TODAY) - dt.timedelta(days=n)).isoformat()


def block(days):
    return {'date': days_ago(days), 'searches': []}


class DataStage(unittest.TestCase):
    def test_launch_needs_block_and_under_10_queries(self):
        product = {'launch': block(20)}
        # 9 queries with impressions, plus 5 rows with none that do not count
        qs = rows(9, observed_days=14) + [query(f'quiet {i}', 100, 1000, 10, 0, 0, 14, impressions=0) for i in range(5)]
        got = stage.data_stage(product, qs, CFG, TODAY)
        self.assertEqual(got['stage'], 'launch')
        self.assertEqual(got['sqp_queries'], 9)
        got = stage.data_stage(product, rows(10, observed_days=14), CFG, TODAY)
        self.assertEqual(got['stage'], 'early')
        self.assertEqual(got['sqp_queries'], 10)

    def test_launch_block_must_be_dated_within_90_days(self):
        qs = rows(3, observed_days=14)
        self.assertEqual(stage.data_stage({'launch': block(90)}, qs, CFG, TODAY)['stage'], 'launch')
        self.assertEqual(stage.data_stage({'launch': block(0)}, qs, CFG, TODAY)['stage'], 'launch')
        self.assertEqual(stage.data_stage({'launch': block(91)}, qs, CFG, TODAY)['stage'], 'early')
        self.assertEqual(stage.data_stage({'launch': block(-3)}, qs, CFG, TODAY)['stage'], 'early')
        self.assertEqual(stage.data_stage({'launch': {'searches': []}}, qs, CFG, TODAY)['stage'], 'early')
        self.assertEqual(stage.data_stage({'launch': {'date': None}}, qs, CFG, TODAY)['stage'], 'early')

    def test_no_launch_block_is_early_not_launch(self):
        got = stage.data_stage({}, rows(159, observed_days=14, trusted=2), CFG, TODAY)
        self.assertEqual(got['stage'], 'early')
        self.assertEqual((got['sqp_queries'], got['observed_days'], got['trusted_queries']), (159, 14, 2))
        self.assertIn('14 observed days', got['reason'])
        self.assertEqual(got['reason'],
                         'early: 14 observed days, 2 trusted queries, 159 SQP queries with impressions')
        self.assertFalse(got['left_launch_this_run'])

    def test_early_by_days_then_by_trusted(self):
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=21, trusted=13), CFG, TODAY)['stage'], 'early')
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=28, trusted=4), CFG, TODAY)['stage'], 'early')
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=28, trusted=5), CFG, TODAY)['stage'], 'mature')

    def test_recorded_mature_sticks(self):
        got = stage.data_stage({'data_stage': 'mature'}, rows(40, observed_days=21, trusted=2), CFG, TODAY)
        self.assertEqual(got['stage'], 'mature')
        # a stock-out that thins SQP below 10 queries does not make a recorded-mature product launch again
        thin = stage.data_stage({'data_stage': 'mature', 'launch': block(20)}, rows(3, observed_days=14), CFG, TODAY)
        self.assertEqual(thin['stage'], 'mature')
        self.assertFalse(thin['left_launch_this_run'])

    def test_full_window_is_mature_whatever_trusted(self):
        # the line is config stage.full_window_days (77 since 2026-10-22: a 90-day pull holds 11 complete SQP weeks, so
        # the design's 84 never fired); with 2 trusted queries only the window makes the product mature
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=77, trusted=2), CFG, TODAY)['stage'], 'mature')
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=76, trusted=2), CFG, TODAY)['stage'], 'early')
        # a config without the key keeps the old 84-day line
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=84, trusted=2), CFG_NO_FULL_WINDOW, TODAY)['stage'],
                         'mature')
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=83, trusted=2), CFG_NO_FULL_WINDOW, TODAY)['stage'],
                         'early')
        self.assertEqual(stage.data_stage({}, rows(40, observed_days=77, trusted=2), CFG_NO_FULL_WINDOW, TODAY)['stage'],
                         'early')

    def test_a_launch_date_that_is_not_a_date_stops_the_run(self):
        with self.assertRaises(SystemExit) as cm:
            stage.data_stage({'launch': {'date': 'Oct 14', 'searches': []}}, rows(3, observed_days=14), CFG, TODAY)
        self.assertEqual(str(cm.exception), "the product file's launch.date 'Oct 14' is not a date (YYYY-MM-DD)")
        # a datetime string is read by its date part, as before
        self.assertEqual(stage.data_stage({'launch': {'date': days_ago(20) + 'T00:00:00Z'}}, rows(3, observed_days=14),
                                          CFG, TODAY)['stage'], 'launch')

    def test_missing_observed_days_counts_as_84(self):
        qs = rows(40, trusted=6)
        for q in qs:
            del q['QueryObservedDayCount']
        got = stage.data_stage({}, qs, CFG, TODAY)
        self.assertEqual(got['observed_days'], 84)
        self.assertEqual(got['stage'], 'mature')
        # one row with a short count among rows with none: the longest count still rules
        qs[0]['QueryObservedDayCount'] = 14
        self.assertEqual(stage.data_stage({}, qs, CFG, TODAY)['observed_days'], 84)

    def test_no_rows_is_zero_observed_days(self):
        got = stage.data_stage({}, [], CFG, TODAY)
        self.assertEqual((got['stage'], got['sqp_queries'], got['observed_days'], got['trusted_queries']),
                         ('early', 0, 0, 0))

    def test_left_launch_this_run(self):
        product = {'data_stage': 'launch', 'launch': block(10)}
        got = stage.data_stage(product, rows(12, observed_days=14), CFG, TODAY)
        self.assertTrue(got['left_launch_this_run'])
        self.assertEqual(got['stage'], 'early')
        # still in launch: has not left it
        self.assertFalse(stage.data_stage(product, rows(9, observed_days=14), CFG, TODAY)['left_launch_this_run'])
        # no recorded launch stage: nothing left
        self.assertFalse(stage.data_stage({'launch': block(10)}, rows(12, observed_days=14), CFG, TODAY)
                         ['left_launch_this_run'])
        # no dated block: nothing to leave
        self.assertFalse(stage.data_stage({'data_stage': 'launch'}, rows(12, observed_days=14), CFG, TODAY)
                         ['left_launch_this_run'])


class SqpTotals(unittest.TestCase):
    def test_sums_every_row_and_counts_every_row(self):
        qs = [query('a', 100, 1000, 10, 40, 2), query('b', 100, 1000, 10, 7, 0, impressions=0),
              dict(Query='c', AsinClicks=None)]
        self.assertEqual(stage.sqp_totals(qs), {'our_clicks': 47, 'our_purchases': 2, 'queries': 3})
        self.assertEqual(stage.sqp_totals([]), {'our_clicks': 0, 'our_purchases': 0, 'queries': 0})


class VolatileWeek(unittest.TestCase):
    HISTORY = [{'data_through': '2026-10-10', 'our_clicks': 214, 'our_purchases': 3, 'queries': 159}]

    def run_week(self, history, clicks, data_through, cfg=CFG):
        product = {'sqp_history': history} if history is not None else {}
        return stage.volatile_week(product, [query('gel pens', 500, 1000, 50, clicks, 5)], data_through, cfg)

    def test_volatile_week_flags_doubling(self):
        got = self.run_week(self.HISTORY, 462, '2026-10-17')
        # the text names the span measured, baseline to this run (final review, 2026-10-22: a history that missed a week
        # compares two weeks against the baseline, and the text says so)
        self.assertEqual(got, 'volatile SQP week: the SQP since 2026-10-10 (through 2026-10-17) added 248 of our clicks, '
                              'more than the 214 of all earlier weeks')
        self.assertIn('since 2026-10-10 (through 2026-10-24)', self.run_week(self.HISTORY, 462, '2026-10-24'))
        self.assertIsNone(self.run_week(self.HISTORY, 400, '2026-10-17'))   # 186 added < 214
        self.assertIsNone(self.run_week(self.HISTORY, 462, '2026-10-10'))   # same pull again
        self.assertIsNone(self.run_week(self.HISTORY, 462, '2026-10-03'))   # older than the baseline
        self.assertIsNone(self.run_week(self.HISTORY, 462, None))
        self.assertIsNone(self.run_week(None, 462, '2026-10-17'))
        self.assertIsNone(self.run_week([], 462, '2026-10-17'))

    def test_baseline_is_the_newest_entry_whatever_the_order(self):
        history = [{'data_through': '2026-10-10', 'our_clicks': 214, 'our_purchases': 3, 'queries': 159},
                   {'data_through': '2026-10-03', 'our_clicks': 100, 'our_purchases': 1, 'queries': 120},
                   {'our_clicks': 5}]                                       # an entry without a date is ignored
        self.assertIsNotNone(self.run_week(history, 462, '2026-10-17'))     # against 214, not 100
        self.assertIsNone(self.run_week(history, 462, '2026-10-10'))
        self.assertIsNone(self.run_week(history, 400, '2026-10-17'))

    def test_a_zero_baseline_is_no_baseline(self):
        history = [{'data_through': '2026-10-10', 'our_clicks': 0, 'our_purchases': 0, 'queries': 0}]
        self.assertIsNone(self.run_week(history, 462, '2026-10-17'))

    def test_the_ratio_is_the_configs(self):
        cfg = {**CFG, 'stage': {**CFG['stage'], 'volatile_week_ratio': 2.0}}
        self.assertIsNone(self.run_week(self.HISTORY, 462, '2026-10-17', cfg))     # 248 < 2 x 214
        got = self.run_week(self.HISTORY, 700, '2026-10-17', cfg)                  # 486 > 428
        self.assertIn('added 486 of our clicks', got)
        self.assertIn('more than 2 x the 214', got)


class VolumeOf(unittest.TestCase):
    LAUNCH = {'date': '2026-10-10', 'searches': [{'search': 'Gel Pens for Coloring', 'volume': 9297},
                                                 {'search': 'fine point gel pen', 'volume': None},
                                                 {'search': 'colored gel pens', 'volume': 21729,
                                                  'folded': ['gel pens colored', 'colored gel pen']}]}

    def test_volume_of_order(self):
        row = query('gel pens', 33884, 1000, 50, 20, 2)
        self.assertEqual(stage.volume_of('gel pens', row, self.LAUNCH, {'gel pens': 5000}), (33884, 'SQP'))
        self.assertEqual(stage.volume_of('gel pens for coloring', None, self.LAUNCH, None, 14), (4339, 'launch list'))
        # a folded variant of a listed search has the list's volume (final review, 2026-10-22)
        self.assertEqual(stage.volume_of('gel pens colored', None, self.LAUNCH, {'gel pens colored': 100}, 30),
                         (21729, 'launch list'))
        self.assertEqual(stage.volume_of('Colored Gel Pen', None, self.LAUNCH, None, 30), (21729, 'launch list'))
        self.assertEqual(stage.volume_of('pastel pens', None, None, {'pastel pens': 250}, 21), (175, 'SoldScope'))
        self.assertEqual(stage.volume_of('pastel pens', None, None, {'pastel pens': 1000}), (2800, 'SoldScope'))
        self.assertEqual(stage.volume_of('pastel pens', None, None, None), (0, 'none'))

    def test_a_row_without_volume_falls_to_the_next_source(self):
        no_volume = query('gel pens for coloring', 0, 1000, 50, 20, 2)
        self.assertEqual(stage.volume_of('gel pens for coloring', no_volume, self.LAUNCH, None, 14),
                         (4339, 'launch list'))
        self.assertEqual(stage.volume_of('fine point gel pen', None, self.LAUNCH, {'fine point gel pen': 300}, 21),
                         (210, 'SoldScope'))                                # a list row with no volume is skipped
        self.assertEqual(stage.volume_of('gel pens for coloring', None, {'searches': []}, {}, 14), (0, 'none'))

    def test_terms_match_by_normal_form(self):
        self.assertEqual(stage.volume_of('GEL  pens, for coloring', None, self.LAUNCH, None, 30), (9297, 'launch list'))
        self.assertEqual(stage.volume_of('Pastel Pens', None, None, {'pastel pens': 300}, 30), (300, 'SoldScope'))


class FallbackIndex(unittest.TestCase):
    def test_fallback_index_shrinks(self):
        # ((3 + 10 x 0.146) / 16) / 0.146: 3 orders on 6 clicks reads 1.91x the product market, not 3.4x
        self.assertEqual(round(stage.fallback_index(6, 3, 0.146), 2), 1.91)
        self.assertEqual(round(stage.fallback_index(2, 2, 0.146), 2), 1.97)
        self.assertIsNone(stage.fallback_index(6, 3, None))
        self.assertIsNone(stage.fallback_index(6, 3, 0))

    def test_the_prior_is_a_parameter(self):
        self.assertEqual(round(stage.fallback_index(6, 3, 0.146, prior_clicks=0), 2), 3.42)   # (3 / 6) / 0.146


class RelevanceFlag(unittest.TestCase):
    ROOTS = ['pens', 'colored', 'colorful']
    LAUNCH = {'searches': [{'search': 'Gel Pens For Coloring', 'volume': 9297}]}

    def test_relevance_flag(self):
        self.assertEqual(stage.relevance_flag('pen', None, set(), self.ROOTS), 'one token')
        self.assertEqual(stage.relevance_flag('school supplies', None, set(), self.ROOTS), 'unlisted')
        self.assertEqual(stage.relevance_flag('school supplies', None, set(), []), 'unlisted')
        self.assertIsNone(stage.relevance_flag('gel pens for coloring', None, set(), self.ROOTS))   # a root token
        self.assertIsNone(stage.relevance_flag('colored gel pens', None, {'colored gel pens'}, []))  # in the niche
        # a root matches its plural and singular (R41, 2026-10-22): "pen" under the root "pens", "markers" under "mark"
        self.assertIsNone(stage.relevance_flag('fine point gel pen', None, set(), ['pens']))
        self.assertIsNone(stage.relevance_flag('gel pens fine point', None, set(), ['pen']))
        self.assertIsNone(stage.relevance_flag('bible markers', None, set(), ['mark']))
        self.assertEqual(stage.relevance_flag('school supplies', None, set(), ['pens']), 'unlisted')
        # a folded variant of a listed search is listed (final review, 2026-10-22)
        folded = {'searches': [{'search': 'colored gel pens', 'volume': 21729, 'folded': ['gel pens colored']}]}
        self.assertIsNone(stage.relevance_flag('gel pens colored', folded, set(), []))
        self.assertEqual(stage.relevance_flag('gel pens for kids', folded, set(), []), 'unlisted')

    def test_the_launch_list_clears_a_search(self):
        self.assertIsNone(stage.relevance_flag('gel pens for coloring', self.LAUNCH, set(), []))
        self.assertIsNone(stage.relevance_flag('GEL PENS for Coloring', self.LAUNCH, set(), []))
        self.assertEqual(stage.relevance_flag('gel pens for kids', self.LAUNCH, set(), []), 'unlisted')

    def test_one_word_is_flagged_even_when_listed(self):
        self.assertEqual(stage.relevance_flag('pens', self.LAUNCH, {'pens'}, self.ROOTS), 'one token')


if __name__ == '__main__':
    unittest.main()
