"""Live size evidence can release only an identified wrong-size positive-keyword pause."""
import copy
import unittest
from unittest.mock import patch
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile

import listing_size
import plan as planner
import plan_lanes
import test_plan_lanes as T
import test_product_size as product_size
import dashboard
WRONG, RIGHT = product_size.WRONG, product_size.RIGHT


class ListingSizeTest(unittest.TestCase):
    def setUp(self):
        self.cfg = T.product(size='4x6in')
        self.raw = {'listings': [{'asin': T.ASIN, 'sku': 'TEST-SKU', 'title': 'Cards 6x4in', 'status': ['BUYABLE'],
                                 'attributes': {'bullet_point': [{'value': 'Each card measures 4x6 inches.',
                                                                  'marketplace_id': 'ATVPDKIKX0DER'}]}}]}
        self.review = dict(asin=T.ASIN, sku='TEST-SKU', marketplace='US', source='MAP get_selling_partner_listings',
                           raw_listing_file='listing_raw.json', observed_at='2026-10-19T22:55:00+08:00',
                           complete=True, ambiguous=False,
                           claims=[dict(field='title', quote='6x4in'),
                                   dict(field='bullets', index=0, quote='Each card measures 4x6 inches.')])

    def confirm(self, **kwargs):
        return listing_size.confirm(self.raw, self.review, self.cfg, {(4., 6.)}, planner.dimension_pairs,
                                    kwargs.get('today', T.TODAY), kwargs.get('now', T.NOW))

    def row(self, **over):
        return dict(type='Pause keyword', keyword=WRONG, role='Negate', current=.5, new=None,
                    asin=T.ASIN, campaign_id='11', ad_group_id='12', keyword_id='13', **over)

    def test_live_size_releases_pause_but_never_raise_promotion_or_negative(self):
        proof, problem = self.confirm()
        self.assertIsNone(problem)
        rows = [self.row(), dict(type='Bid change', keyword=WRONG, current=.2, new=.5),
                dict(type='New exact campaign', keyword=WRONG), dict(type='Negative exact', keyword=WRONG)]
        planner.size_holds(rows, {(4., 6.)}, proof)
        self.assertNotIn('relevance_hold', rows[0])
        self.assertIn('listing_size_verified_pause', rows[0])
        self.assertTrue(all(r.get('relevance_hold') for r in rows[1:]))

    def test_missing_stale_future_wrong_asin_sku_marketplace_and_ambiguous_stay_held(self):
        for field, value in [('observed_at', '2026-10-18T22:55:00+08:00'),
                             ('observed_at', '2026-10-19T23:55:00+08:00'),
                             ('observed_at', '2026-10-19T22:55:00'), ('asin', 'OTHER'), ('sku', 'OTHER'),
                             ('marketplace', 'UK'), ('complete', False), ('ambiguous', True),
                             ('source', 'fingerprint')]:
            with self.subTest(field=field, value=value):
                review = copy.deepcopy(self.review); review[field] = value
                proof, problem = listing_size.confirm(self.raw, review, self.cfg, {(4., 6.)},
                                                      planner.dimension_pairs, T.TODAY, T.NOW)
                self.assertIsNone(proof); self.assertTrue(problem)
        row = self.row(); planner.size_holds([row], {(4., 6.)})
        self.assertTrue(row.get('relevance_hold'))

    def test_raw_identity_and_unanchored_or_conflicting_size_evidence_fail(self):
        for change in ['asin', 'sku', 'quote', 'conflict', 'metric', 'package', 'package_context', 'buyability', 'error']:
            with self.subTest(change=change):
                raw, review = copy.deepcopy(self.raw), copy.deepcopy(self.review)
                item = raw['listings'][0]
                if change in ('asin', 'sku'): item[change] = 'OTHER'
                elif change == 'quote': review['claims'][0]['quote'] = 'Actual product is 4x6in'
                elif change == 'conflict': item['title'] = 'Cards 5x7in'
                elif change == 'metric': item['title'] = 'Cards 4x6 cm'; review['claims'][0]['quote'] = '4x6 cm'
                elif change == 'buyability': item['status'] = ['DISCOVERABLE']
                elif change == 'error': raw['isError'] = True
                elif change == 'package':
                    item['title'] = 'Package 4x6in'; review['claims'][0]['quote'] = 'Package 4x6in'
                else:
                    item['title'] = 'Package 4x6in'; review['claims'][0]['quote'] = '4x6in'
                proof, problem = listing_size.confirm(raw, review, self.cfg, {(4., 6.)},
                                                      planner.dimension_pairs, T.TODAY, T.NOW)
                self.assertIsNone(proof); self.assertTrue(problem)

    def test_folded_and_unfolded_product_sizes_both_count(self):
        text = 'Folded to 5x5 inches, opening to 10x10.'
        self.cfg['size'] = '5x5 and 10x10in'
        self.raw['listings'][0]['title'] = 'Cocktail napkins'
        self.raw['listings'][0]['attributes']['bullet_point'][0]['value'] = text
        self.review['claims'] = [dict(field='bullets', index=0, quote=text)]
        proof, problem = listing_size.confirm(self.raw, self.review, self.cfg, {(5., 5.), (10., 10.)},
                                              planner.dimension_pairs, T.TODAY, T.NOW)
        self.assertIsNone(problem); self.assertTrue(proof)
        # Existing products may store the folded size as own and explicitly protect the unfolded size.
        self.cfg.update(size='5x5 inches', relevance={'protect': ['10x10 inches']})
        proof, problem = listing_size.confirm(self.raw, self.review, self.cfg, {(5., 5.)},
                                              planner.dimension_pairs, T.TODAY, T.NOW)
        self.assertIsNone(problem); self.assertTrue(proof)

    def test_matching_protected_mixed_and_routing_pauses_do_not_gain_exception(self):
        proof, _ = self.confirm()
        for row in [dict(self.row(), keyword=RIGHT), dict(self.row(), keyword='4x6 or 5x7 thank you cards'),
                    dict(self.row(), role='Invest'), dict(self.row(), keyword='13x18 cm cards'),
                    dict(self.row(), keyword_id=None)]:
            with self.subTest(row=row):
                planner.size_holds([row], {(4., 6.)}, proof)
                self.assertNotIn('listing_size_verified_pause', row)
        row = self.row(); planner.size_holds([row], {(4., 6.), (5., 7.)}, proof)
        self.assertNotIn('listing_size_verified_pause', row)

    def test_lane_guards_still_win_and_payload_is_a_pause_only(self):
        proof, _ = self.confirm()
        for guard in ['none', 'price', 'sqp', 'inventory', 'lock', 'ownership', 'auto_off']:
            with self.subTest(guard=guard):
                cfg = copy.deepcopy(self.cfg); row = self.row(); planner.size_holds([row], {(4., 6.)}, proof)
                out = dict(summary=[dict(asin=T.ASIN, sqp_data_through='2026-10-12', inputs={'sqp': 3})],
                           changes=[row], terms=[], business_terms=[], rerank=[], rerank_held=[])
                inputs = dict(price_change={'days_since': 30}, inventory_cover={'cover_days': 60}, reviews=[])
                if guard == 'price': inputs['price_change']['days_since'] = 1
                if guard == 'sqp': out['summary'][0]['sqp_data_through'] = '2026-09-01'
                if guard == 'inventory': inputs['inventory_cover'] = None
                if guard == 'auto_off': cfg['auto']['enabled'] = False
                if guard == 'ownership':
                    cfg['ownership_scope'] = dict(mode='exclusive_campaigns', excluded_campaign_ids=['11'])
                if guard == 'lock':
                    cfg['decisions'] = [dict(id='Pause keyword:13', what='decline', by='Kim', on=T.TODAY,
                                             until='2026-11-20', direction='pause', reason='keep it')]
                if guard == 'inventory':   # decision 168: a missing inventory file stops an Auto product's run up front
                    with self.assertRaises(SystemExit):
                        plan_lanes.assign(out, cfg, T.shared_config(), 'weekly', inputs, T.TODAY, T.NOW)
                    continue
                plan_lanes.assign(out, cfg, T.shared_config(), 'weekly', inputs, T.TODAY, T.NOW)
                if guard in ('none', 'price', 'sqp'):   # nor a price change (decision 168) nor old SQP (decision 172)
                    self.assertEqual(row['lane'], 'auto')
                    payloads = dict(planner.payload_files(out['changes'], T.shared_config(), T.ASIN))
                    self.assertEqual(payloads['3_pauses.json'], [dict(type='sp_keywords', keywordId='13', state='PAUSED')])
                elif guard == 'auto_off': self.assertTrue(out['summary'][0]['shadow'])
                else: self.assertNotEqual(row['lane'], 'auto')

    def test_planner_build_uses_live_evidence_and_keeps_wrong_size_out_of_rank_and_harvest(self):
        proof, _ = self.confirm()
        inputs = planner.load_lane_inputs('unused-size-test-run')
        inputs.update(price_change={'days_since': 30}, inventory_cover={'cover_days': 60}, reviews=[])
        with patch.object(planner.listing_size, 'read_confirmation', return_value=(proof, None)), \
                patch.object(planner, 'load_lane_inputs', return_value=inputs):
            out = product_size.ProductSizeTest().build()
        rows = [r for r in out['changes'] if r.get('keyword') == WRONG]
        self.assertTrue(any(r['type']=='Pause keyword' and r['lane']=='auto' for r in rows))
        self.assertFalse(any(r['type']=='New exact campaign' for r in rows))
        self.assertNotIn(WRONG, [r['keyword'] for r in out['rerank']])
        self.assertEqual(out['harvest']['priced_searches'], 2)

    def test_preapply_rechecks_snapshot_age_identity_and_planned_evidence(self):
        proof, _ = self.confirm(); row = self.row(); planner.size_holds([row], {(4., 6.)}, proof)
        with patch.object(listing_size, 'read_confirmation', return_value=(proof, None)):
            self.assertIsNone(listing_size.preapply_problem([row], 'run', self.cfg, {(4., 6.)}, {(4., 6.)},
                                                            planner.dimension_pairs, T.TODAY, T.NOW))
        for changed, problem in [(None, 'stale'), (dict(proof, snapshot_sha256='changed'), None),
                                 (dict(proof, asin='OTHER'), None)]:
            with self.subTest(proof=changed, problem=problem), \
                    patch.object(listing_size, 'read_confirmation', return_value=(changed, problem)):
                self.assertTrue(listing_size.preapply_problem([row], 'run', self.cfg, {(4., 6.)}, {(4., 6.)},
                                                              planner.dimension_pairs, T.TODAY, T.NOW))
        with patch.object(listing_size, 'read_confirmation', side_effect=AssertionError('No evidence needed')):
            self.assertIsNone(listing_size.preapply_problem([], 'run', self.cfg, set(), set(),
                                                            planner.dimension_pairs, T.TODAY, T.NOW))

    def test_file_loader_uses_actual_raw_response_and_rejects_escape_paths(self):
        import json
        def read_text(path, **kwargs):
            return json.dumps(self.review if path.name == listing_size.FILE else self.raw)
        with patch.object(listing_size.Path, 'read_text', read_text):
            proof, problem = listing_size.read_confirmation('unused-run', self.cfg, {(4., 6.)},
                                                            planner.dimension_pairs, T.TODAY, T.NOW)
            self.assertIsNone(problem); self.assertTrue(proof)
            self.review['raw_listing_file'] = '../other-product.json'
            proof, problem = listing_size.read_confirmation('unused-run', self.cfg, {(4., 6.)},
                                                            planner.dimension_pairs, T.TODAY, T.NOW)
            self.assertIsNone(proof); self.assertTrue(problem)

    def test_apply_command_refuses_missing_stale_or_changed_live_size_proof(self):
        proof, _ = self.confirm(); row = self.row(); row['row_id'] = 'Pause keyword:13'
        planner.size_holds([row], {(4., 6.)}, proof); row['lane'] = 'auto'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); run = root/'run'; run.mkdir(); data = root/'data'; (data/'asins').mkdir(parents=True)
            product = data/'asins'/f'{T.ASIN}.json'; product.write_text(json.dumps(self.cfg), encoding='utf8')
            (run/'listing_raw.json').write_text(json.dumps(self.raw), encoding='utf8')
            review_file = run/listing_size.FILE; review_file.write_text(json.dumps(self.review), encoding='utf8')
            out = dict(summary=[dict(asin=T.ASIN, shadow=False)], changes=[row], terms=[], checks=[])
            planner.write_outputs(str(run), out, T.shared_config(), T.ASIN)
            args = argparse.Namespace(asin=T.ASIN, run=str(run), data=str(data), folder='auto', date=T.TODAY,
                                      dry_run=True, now=T.NOW.isoformat(), rows=None)
            before = product.read_bytes()
            with patch.object(dashboard, 'config', return_value=T.shared_config()), \
                    patch.object(dashboard, 'call', side_effect=AssertionError('No network in this test')):
                with contextlib.redirect_stdout(io.StringIO()) as captured: dashboard.cmd_applied(args)
                self.assertEqual(json.loads(captured.getvalue())['rows'], 1)
                for change in ['stale', 'changed', 'missing']:
                    with self.subTest(change=change):
                        review = copy.deepcopy(self.review)
                        if change == 'stale': review['observed_at'] = '2026-10-18T22:55:00+08:00'
                        if change == 'changed': review['claims'][0]['quote'] = 'Cards 6x4in'
                        review_file.write_text(json.dumps(review), encoding='utf8')
                        if change == 'missing': review_file.unlink()
                        with self.assertRaisesRegex(SystemExit, 'Live listing size verification refuses'):
                            dashboard.cmd_applied(args)
                self.assertEqual(product.read_bytes(), before)
                self.assertFalse((run/'payloads/applied_rows.json').exists())


if __name__ == '__main__': unittest.main()
