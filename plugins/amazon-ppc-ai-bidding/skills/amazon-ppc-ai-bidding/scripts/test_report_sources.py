"""report_sources.py: the SoldScope and MAP backup for the Scale Insights report reads (Kim, 2026-11-04: Scale Insights
the default, SoldScope the backup)."""
import json
import os
import shutil
import tempfile
import unittest

import plan as planner
import report_sources as rs

ASIN = 'B0SAMP0017'


class ReportSourcesTest(unittest.TestCase):
    def setUp(self):
        self.run = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.run, ignore_errors=True)

    def save(self, name, obj):
        p = os.path.join(self.run, name)
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh)
        return p

    def test_weeks_are_the_saturdays_ending_at_the_last_complete_week(self):
        w = rs.weeks('2026-10-31')
        self.assertEqual((len(w), w[0], w[-1]), (13, '2026-08-08', '2026-10-31'))
        with self.assertRaises(SystemExit):
            rs.weeks('2026-11-01')

    def test_soldscope_rows_become_scale_insights_queries_the_planner_reads(self):
        raw = {'data': [
            dict(key='mini scripture cards', queryVolume=53, marketImpressionCount=1297, myImpressionCount=27,
                 marketClickCount=25, myClickCount=1, marketPurchaseCount=1, myPurchaseCount=0, dataPeriods=['2026-10-24']),
            dict(key='mini scripture￼ cards', queryVolume=7, marketImpressionCount=3, myImpressionCount=1,
                 marketClickCount=5, myClickCount=1, marketPurchaseCount=1, myPurchaseCount=1, dataPeriods=['2026-10-31'])],
            'meta': {'total': 2}}
        path = self.save('soldscope_sqp_raw.json', raw)
        rs.main(['sqp', '--asin', ASIN, '--run', self.run, path])
        sq, *_, through = planner.load_inputs(self.run, ASIN, {})
        q = sq['mini scripture cards']
        self.assertEqual((q['QueryVolume'], q['TotalClicks'], q['AsinClicks'], q['TotalPurchase'], q['AsinPurchase']), (60, 30, 2, 2, 1))
        self.assertEqual((q['QueryObservedDayCount'], through), (14, '2026-10-31'))

    def test_map_keyword_rows_split_into_keywords_and_targets(self):
        kw_raw = self.save('map_kw_raw_p1.json', {'status': 'success', 'data': [
            dict(keyword_id=900000000000016, keyword='scripture cards', match_type='EXACT', keyword_type='EXACT',
                 campaign_id=900000000000017, campaign_name=f'Cards - {ASIN} - Exact SKC - scripture cards', ad_group_id=5,
                 ad_group_name='Performance Exact', bid=0.42, clicks=70, impressions=6196, spend=37.75, orders=3, sales=23.97),
            dict(keyword_id=9, keyword=None, match_type='TARGETING_EXPRESSION', keyword_type='TARGETING_EXPRESSION',
                 targeting='asin="B0SAMP0039"', campaign_id=7, campaign_name=f'Cards - {ASIN} - PT', ad_group_id=8,
                 bid=0.3, clicks=4, impressions=90, spend=1.2, orders=0, sales=0),
            dict(keyword_id=10, keyword_type='TARGETING_EXPRESSION_PREDEFINED', targeting='close-match', campaign_id=11,
                 campaign_name=f'Cards - {ASIN} - Auto', ad_group_id=12, bid=0.25, clicks=2, spend=0.5, orders=1, sales=7.99)]})
        st_raw = self.save('map_st_raw_p1.json', {'data': [
            dict(search_term='scripture cards', keyword_id=900000000000016, keyword='scripture cards', match_type='EXACT',
                 keyword_type='EXACT', campaign_id=900000000000017, campaign_name=f'Cards - {ASIN} - Exact SKC - scripture cards',
                 ad_group_id=5, clicks=70, impressions=6196, spend=37.75, orders=3, sales=23.97)]})
        sb_raw = self.save('map_sb_st_raw_p1.json', {'data': [
            dict(search_term='bible cards', keyword_id=3, keyword='bible cards', match_type='EXACT', campaign_id=4,
                 campaign_name=f'SB video - {ASIN}', ad_group_id=6, clicks=5, spend=2.0, orders=1, sales=7.99)]})
        rs.main(['ads', '--asin', ASIN, '--run', self.run, '--kw', kw_raw, '--st', st_raw, '--sb-st', sb_raw])
        sq, st, kw, *_ = planner.load_inputs(self.run, ASIN, {})
        [k] = kw
        self.assertEqual((k['KeywordId'], k['MatchType'], k['Bid'], k['Clicks'], k['Orders'], k['AdType']),
                         ('900000000000016', 'exact', 0.42, 70, 3, 'SP'))
        targets = planner.load_targets(self.run, ASIN, auto=True)
        self.assertEqual(sorted((t['TargetId'], t['TargetType']) for t in targets), [('10', 'auto'), ('9', 'product')])
        self.assertEqual(sorted((s['SearchTerm'], s['AdType']) for s in st), [('bible cards', 'SB'), ('scripture cards', 'SP')])

    def test_it_never_writes_over_a_scale_insights_page(self):
        self.save('sqp_p1.json', {'Queries': []})
        path = self.save('soldscope_sqp_raw.json', {'data': []})
        with self.assertRaises(SystemExit):
            rs.main(['sqp', '--asin', ASIN, '--run', self.run, path])

    def test_the_sql_keeps_the_us_profile_the_window_and_the_product(self):
        q = rs.sql('kw', ASIN, '2026-11-03', campaign_ids=['123'])
        self.assertIn("__amazon_profile_id = '9000000000000003'", q)
        self.assertIn("DATE '2026-08-06' AND DATE '2026-11-03'", q)
        self.assertIn(f"(campaignName LIKE '%{ASIN}%' OR campaignId IN (123))", q)
        self.assertIn('SUM(purchases7d) AS orders', q)
        self.assertIn('SUM(purchases) AS orders', rs.sql('sb_st', ASIN, '2026-11-03'))
        with self.assertRaises(SystemExit):
            rs.sql('kw', "B0X'; DROP", '2026-11-03')


if __name__ == '__main__':
    unittest.main()
