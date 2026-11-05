"""placement_inputs.py builds a placement_inputs.json that placement_review.read_inputs and placement_shape accept."""
import contextlib
import io
import json
import os
import tempfile
import unittest

import placement_inputs
import placement_review

ASIN = 'B0TESTASIN'
CONFIG = json.loads(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json'),
                         encoding='utf-8').read())


def dump(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f)


def row(cid, placement, clicks=10, orders=1):
    return dict(campaignId=cid, campaign_name=f'Cards - {ASIN} - Broad', placement=placement, clicks30=clicks,
                orders30=orders, spend30=8.0, sales30=20.0, clicks90=clicks * 3, orders90=orders * 3, spend90=24.0,
                sales90=60.0, clicks_recent=clicks, orders_recent=orders, spend_recent=8.0, sales_recent=20.0)


class BuildTest(unittest.TestCase):
    def run_folder(self, tmp, report=None, ads=True):
        report = report if report is not None else dict(status='success', truncated=False, data=[
            row('11', 'Top of Search on-Amazon'), row('11', 'Detail Page on-Amazon'), row('11', 'Other on-Amazon')])
        dump(report, os.path.join(tmp, 'placement_report.json'))
        dump(dict(items=[dict(campaignId='11', name=f'Cards - {ASIN} - Broad', state='ENABLED'),
                         dict(campaignId='12', name=f'Cards - {ASIN} - Old', state='PAUSED'),
                         dict(campaignId='13', name='Another product', state='ENABLED')]),
             os.path.join(tmp, 'campaigns.json'))
        if ads:
            dump([dict(type='text', text=json.dumps(dict(items=[
                dict(adId='1', campaignId='11', asin=ASIN, state='ENABLED'),
                dict(adId='2', campaignId='11', asin='B0OTHER000', state='ARCHIVED')])))],
                os.path.join(tmp, 'live_product_ads_p1.json'))
        return tmp

    def test_windows_match_what_the_review_checks(self):
        w = placement_inputs.windows('2026-10-26', 15)
        self.assertEqual(w, {'30d': ['2026-09-12', '2026-10-11'], '90d': ['2026-07-14', '2026-10-11'],
                             'recent': ['2026-09-26', '2026-10-25']})
        text, _ = placement_inputs.sql(ASIN, '2026-10-26', CONFIG)
        self.assertIn("MAX(advertisedAsin) = 'B0TESTASIN'", text)
        self.assertIn("__amazon_profile_id = '9000000000000003'", text)
        for name in ('clicks30', 'orders90', 'spend_recent', 'sales_recent'):
            self.assertIn(' AS ' + name, text)

    def test_build_writes_a_snapshot_the_planner_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_folder(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                placement_inputs.main(['build', '--asin', ASIN, '--run', tmp, '--as-of', '2026-10-26'])
            data = placement_review.read_inputs(tmp, ASIN)
        self.assertTrue(data['complete'])
        self.assertEqual([c['campaignId'] for c in data['campaigns']], ['11', '12'])   # this product's campaigns only
        self.assertEqual(data['live_asins'], {'11': [ASIN]})                            # archived ads don't count
        self.assertEqual(len(data['rows']), 3)
        self.assertEqual(data['rows'][0]['asin'], ASIN)
        self.assertEqual(data['windows']['recent'], ['2026-09-26', '2026-10-25'])

    def test_it_stops_on_a_truncated_report_a_duplicate_or_missing_product_ads(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_folder(tmp, report=dict(status='success', truncated=True, data=[]))
            with self.assertRaises(SystemExit) as stop:
                placement_inputs.build(ASIN, tmp, '2026-10-26', CONFIG)
            self.assertIn('truncated', str(stop.exception))
        with tempfile.TemporaryDirectory() as tmp:
            self.run_folder(tmp, report=[row('11', 'Top of Search on-Amazon'), row('11', 'Top of Search on-Amazon')])
            with self.assertRaises(SystemExit) as stop:
                placement_inputs.build(ASIN, tmp, '2026-10-26', CONFIG)
            self.assertIn('duplicate', str(stop.exception))
        with tempfile.TemporaryDirectory() as tmp:
            self.run_folder(tmp, ads=False)
            with self.assertRaises(SystemExit) as stop:
                placement_inputs.build(ASIN, tmp, '2026-10-26', CONFIG)
            self.assertIn('"11"', str(stop.exception))
            self.assertFalse(os.path.exists(os.path.join(tmp, 'placement_inputs.json')))


if __name__ == '__main__':
    unittest.main()
