"""Decisions 139 and 140 (Kim, 2026-10-26): non-rank bids at 85% of breakeven, down-only bidding, and the product-page
base bid (placement_shape.py).

The shape tests drive placement_shape.apply on a small laned plan: one exclusive campaign with two keywords and a product
target, its placement report, and its live settings. The factor and strategy tests use test_plan_lanes' synthetic run.
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

import lanes
import placement_review
import placement_shape
import plan as planner
import test_plan_lanes as T

ASIN = T.ASIN
CID = '555'
TODAY = '2026-10-26'
CONFIG = json.loads(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json'),
                         encoding='utf-8').read())


def campaign(cid=CID, name=f'Cards - {ASIN} - Broad', strategy='SALES_DOWN_ONLY', tos=0, audience=None, **extra):
    adjustments = dict(placementBidAdjustments=[dict(placement='TOP_OF_SEARCH', percentage=tos)])
    if audience:
        adjustments['audienceBidAdjustments'] = [dict(audienceId='42', percentage=audience)]
    return dict(dict(campaignId=cid, name=name, state='ENABLED', budget=dict(budget=10),
                     optimizations=dict(bidSettings=dict(bidStrategy=strategy, bidAdjustments=adjustments))), **extra)


def place(cid, placement, clicks, orders):
    return dict(asin=ASIN, campaignId=cid, placement=placement, clicks90=clicks, orders90=orders, spend90=clicks * 0.8,
                sales90=orders * 20, clicks30=0, orders30=0, spend30=0, sales30=0, clicks_recent=0, orders_recent=0,
                spend_recent=0, sales_recent=0)


def snapshot(campaigns=None, rows=None, live=None, as_of=TODAY):
    campaigns = campaigns or [campaign()]
    rows = rows if rows is not None else [place(CID, 'Top of Search on-Amazon', 200, 32),     # 16%
                                          place(CID, 'Other on-Amazon', 100, 14),             # 14%
                                          place(CID, 'Detail Page on-Amazon', 200, 16)]       # 8%
    return dict(asin=ASIN, as_of=as_of, complete=True, campaigns=campaigns, rows=rows,
                live_asins=live if live is not None else {c['campaignId']: [ASIN] for c in campaigns})


def shared(**shape):
    s = copy.deepcopy(CONFIG)
    s['placement']['shape'].update(shape)
    return s


def laned(changes=None, keyword_plan=None, target_plan=None, **summary):
    s = dict(shadow=False, stale_reason=None, inventory=dict(partial_reason=None), lanes=dict(auto=0, human=0, monitor=0))
    s.update(summary)
    kp = keyword_plan if keyword_plan is not None else [
        dict(keyword_id='1', keyword='cards', match='broad', family='Broad', campaign_id=CID, role='Discovery', bid=0.80,
             new_bid=0.68, action='Discovery: bid to 85% of breakeven'),
        dict(keyword_id='2', keyword='nice cards', match='phrase', family='Broad', campaign_id=CID, role='Hold', bid=0.50,
             new_bid=0.50, action='Hold at 85% of breakeven')]
    ch = changes if changes is not None else [
        dict(type='Bid change', keyword='cards', keyword_id='1', campaign_id=CID, current=0.80, new=0.68, lane='auto',
             row_id='Bid change:1', why='x')]
    tp = target_plan if target_plan is not None else [
        dict(ad_product='SP', target_id='7', campaign_id=CID, ad_group_id='g', bid=0.40, new=0.40, status='kept')]
    return dict(summary=[s], changes=ch, keyword_plan=kp, target_plan=tp)


def effective(base, modifier):
    return base * (1 + modifier / 100)


class FactorsTest(unittest.TestCase):
    def test_the_best_placement_keeps_the_bid_and_the_others_follow_their_conversion(self):
        share, mods, target = placement_shape.factors(
            dict(TOP_OF_SEARCH=0.16, REST_OF_SEARCH=0.14, PRODUCT_PAGE=0.08), None, 0.5)
        self.assertEqual(share, 0.5)
        for placement, value in dict(TOP_OF_SEARCH=1.0, REST_OF_SEARCH=0.875, PRODUCT_PAGE=0.5).items():
            self.assertAlmostEqual(target[placement], value)
        self.assertEqual(mods, dict(TOP_OF_SEARCH=100, REST_OF_SEARCH=75, PRODUCT_PAGE=0))

    def test_a_rank_campaign_keeps_its_full_top_of_search_bid(self):
        share, mods, target = placement_shape.factors(
            dict(TOP_OF_SEARCH=0.16, REST_OF_SEARCH=0.17, PRODUCT_PAGE=0.10), 50, 0.5)
        self.assertEqual(target['TOP_OF_SEARCH'], 1.5)
        self.assertEqual(target['REST_OF_SEARCH'], 1.0)
        self.assertAlmostEqual(share, 0.10 / 0.17)
        self.assertEqual(mods['TOP_OF_SEARCH'], 155)   # 1.5 / 0.588 - 1, rounded down
        self.assertEqual(mods['PRODUCT_PAGE'], 0)

    def test_no_placement_falls_under_min_share(self):
        share, _, target = placement_shape.factors(dict(TOP_OF_SEARCH=0.20, REST_OF_SEARCH=0.20, PRODUCT_PAGE=0.02), None, 0.5)
        self.assertEqual((share, target['PRODUCT_PAGE']), (0.5, 0.5))


class ShapeTest(unittest.TestCase):
    def shape(self, out=None, snap=None, cfg=None, **conf):
        out = out or laned()
        cfg = cfg or T.product()
        placement_shape.apply(out, cfg, shared(**conf), snapshot() if snap is None else snap, TODAY)
        return out

    def test_a_campaign_is_shaped_and_no_placement_bids_more_than_planned(self):
        out = self.shape()
        result = out['summary'][0]['placement_shape']
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['shaped']), 1, result)
        self.assertEqual((result['shaped'][0]['strategy_now'], result['shaped'][0]['shape_only']), ('SALES_DOWN_ONLY', 2))
        row = next(x for x in out['changes'] if x['type'] == 'Placement shape')
        self.assertEqual((row['lane'], row['campaign_id']), ('auto', CID))
        mods = row['modifiers']
        self.assertEqual(mods['PRODUCT_PAGE'], 0)
        self.assertGreater(mods['TOP_OF_SEARCH'], mods['REST_OF_SEARCH'])
        # every serving bid: its own row (priced or kept), written at the shaped base
        bids = {x.get('keyword_id') or x.get('target_id'): x for x in out['changes'] if x['type'] in ('Bid change', 'Target bid change')}
        self.assertEqual(sorted(bids), ['1', '2', '7'])
        planned = {'1': 0.68, '2': 0.50, '7': 0.40}
        for key, x in bids.items():
            self.assertEqual(planner.as_written(x)['new'], x['shape_base'])
            for placement, modifier in mods.items():
                # no placement bids more than its share of the plan's price
                self.assertLessEqual(effective(x['shape_base'], modifier), planned[key] * row_target(row, placement) + 1e-9)
        self.assertTrue(bids['2']['shape_only'])
        self.assertEqual((bids['2']['current'], bids['2']['new'], bids['2']['lane']), (0.5, 0.5, 'auto'))
        self.assertEqual(len({x['row_id'] for x in out['changes']}), len(out['changes']))

    def test_the_payload_writes_the_shape_last_with_every_placement(self):
        out = self.shape(snap=snapshot(campaigns=[dict(campaign(), optimizations=dict(bidSettings=dict(
            bidStrategy='SALES_DOWN_ONLY', bidAdjustments=dict(placementBidAdjustments=[
                dict(placement='TOP_OF_SEARCH', percentage=30), dict(placement='SITE_AMAZON_BUSINESS', percentage=20)]))))]))
        files = planner.payload_files([planner.as_written(x) for x in out['changes']], CONFIG, ASIN)
        names = [name for name, _ in files]
        self.assertEqual(names[-1], '9c_placement_shape.json')
        self.assertLess(names.index('4_bids_01.json'), names.index('9c_placement_shape.json'))
        [update] = dict(files)['9c_placement_shape.json']
        settings = update['optimizations']['bidSettings']
        self.assertEqual(settings['bidStrategy'], 'SALES_DOWN_ONLY')
        placements = {p['placement']: p['percentage'] for p in settings['bidAdjustments']['placementBidAdjustments']}
        self.assertEqual(set(placements), {'TOP_OF_SEARCH', 'REST_OF_SEARCH', 'PRODUCT_PAGE', 'SITE_AMAZON_BUSINESS'})
        self.assertEqual(placements['SITE_AMAZON_BUSINESS'], 20)   # an unshaped placement is sent back as read
        bids = {r['keywordId']: r['bid'] for r in dict(files)['4_bids_01.json']}
        self.assertEqual(bids['1'], next(x for x in out['changes'] if x.get('keyword_id') == '1')['shape_base'])

    def test_a_rank_campaign_keeps_top_of_search_at_the_policy(self):
        kp = [dict(keyword_id='1', keyword='cards', match='exact', family='SKC', campaign_id=CID, role='Rank',
                   sub_role='Invest', bid=1.00, new_bid=1.00, action='Invest: bid to be visible')]
        out = self.shape(out=laned(changes=[], keyword_plan=kp, target_plan=[]),
                         snap=snapshot(campaigns=[campaign(tos=50)]))
        row = next(x for x in out['changes'] if x['type'] == 'Placement shape')
        self.assertEqual(row['rank_tos'], 50)
        bid = next(x for x in out['changes'] if x.get('keyword_id') == '1')
        top = effective(bid['shape_base'], row['modifiers']['TOP_OF_SEARCH'])
        self.assertLessEqual(top, 1.50 + 1e-9)
        self.assertGreater(top, 1.45)
        self.assertLess(effective(bid['shape_base'], row['modifiers']['PRODUCT_PAGE']), 0.75)

    def test_an_auto_strategy_row_is_folded_into_the_shape(self):
        strategy = dict(type='Bidding strategy', campaign_id=CID, lane='auto', row_id='Bidding strategy:555::')
        out = laned()
        out['changes'].append(strategy)
        out = self.shape(out=out, snap=snapshot(campaigns=[campaign(strategy='SALES_UP_AND_DOWN')]))
        self.assertNotIn('Bidding strategy', [x['type'] for x in out['changes']])
        row = next(x for x in out['changes'] if x['type'] == 'Placement shape')
        self.assertIn('down-only', row['why'])

    def assertSkipped(self, out, words):
        result = out['summary'][0]['placement_shape']
        self.assertNotIn('Placement shape', [x['type'] for x in out['changes']])
        text = result['status'] + ' ' + ' '.join(s['why'] for s in result['skipped'])
        self.assertIn(words, text)

    def test_nothing_is_shaped_in_a_shadow_run_or_without_the_snapshot(self):
        self.assertSkipped(self.shape(out=laned(shadow=True)), 'shadow')
        out = laned()
        placement_shape.apply(out, T.product(), shared(), None, TODAY)
        self.assertSkipped(out, 'no placement_inputs.json')
        self.assertSkipped(self.shape(snap=snapshot(as_of='2026-10-20')), 'days old')

    def test_a_campaign_with_a_row_for_a_person_is_left_alone(self):
        out = laned()
        out['changes'][0]['lane'] = 'human'
        self.assertSkipped(self.shape(out=out), 'waits for a person')

    def test_a_locked_row_stops_the_shape(self):
        out = laned()
        out['changes'][0].update(lane='monitor', locked_until='2026-11-07')
        self.assertSkipped(self.shape(out=out), "a person's decision holds it")

    def test_a_held_row_is_shaped_from_its_live_bid(self):
        # the raise past the run's 20 is held (Monitor): keyword 1 serves at its live $0.80 this run, so the shape writes
        # 0.80 x share in a row of its own and leaves the held row in held/ as it was
        out = laned(changes=[dict(type='Bid change', keyword='cards', keyword_id='1', campaign_id=CID, current=0.80,
                                  new=0.95, lane='monitor', lane_reason="past the run's 20 raises", row_id='Bid change:1')])
        out = self.shape(out=out)
        row = next(x for x in out['changes'] if x['type'] == 'Placement shape')
        held = next(x for x in out['changes'] if x.get('row_id') == 'Bid change:1')
        self.assertEqual((held['lane'], held['new']), ('monitor', 0.95))
        self.assertNotIn('shape_base', held)
        mine = next(x for x in out['changes'] if x.get('keyword_id') == '1' and x.get('shape_only'))
        self.assertEqual((mine['lane'], mine['current'], mine['new'], mine['held_row_id']), ('auto', 0.8, 0.8, 'Bid change:1'))
        self.assertEqual(mine['shape_base'], placement_shape.floor_cents(0.80 * row['base_share']))
        self.assertIn('held this run', mine['why'])
        for modifier in row['modifiers'].values():
            self.assertLessEqual(effective(mine['shape_base'], modifier), 0.80 + 1e-9)   # never above its live bid

    def test_a_held_pause_keeps_its_keyword_serving_and_shaped(self):
        kp = laned()['keyword_plan']
        kp[1]['action'] = 'Pause: its new exact owner serves first'
        out = laned(keyword_plan=kp, changes=[
            dict(type='Bid change', keyword='cards', keyword_id='1', campaign_id=CID, current=0.80, new=0.68, lane='auto',
                 row_id='Bid change:1', why='x'),
            dict(type='Pause keyword', keyword='nice cards', keyword_id='2', campaign_id=CID, lane='monitor',
                 row_id='Pause keyword:2')])
        out = self.shape(out=out)
        two = [x for x in out['changes'] if x.get('keyword_id') == '2' and x.get('shape_only')]
        self.assertEqual(len(two), 1, 'a keyword whose pause is held still serves, so it must be shaped too')
        self.assertEqual(two[0]['current'], 0.5)
        # an auto pause goes out before the bids: that keyword is not shaped
        out = laned(keyword_plan=kp, changes=[
            dict(type='Bid change', keyword='cards', keyword_id='1', campaign_id=CID, current=0.80, new=0.68, lane='auto',
                 row_id='Bid change:1', why='x'),
            dict(type='Pause keyword', keyword='nice cards', keyword_id='2', campaign_id=CID, lane='auto',
                 row_id='Pause keyword:2')])
        out = self.shape(out=out)
        self.assertFalse([x for x in out['changes'] if x.get('keyword_id') == '2' and x.get('shape_only')])

    def test_a_kept_keyword_or_a_default_bid_stops_the_shape(self):
        kp = laned()['keyword_plan']
        kp[1]['action'] = 'Keep pending visibility review: x'
        self.assertSkipped(self.shape(out=laned(keyword_plan=kp)), 'keeps its live bid')
        tp = [dict(ad_product='SP', target_id='7', campaign_id=CID, bid=None, new=None, status='no bid of its own')]
        self.assertSkipped(self.shape(out=laned(target_plan=tp)), 'default bid')

    def test_campaign_level_rows_audience_shared_and_thin_campaigns_are_left_alone(self):
        out = laned()
        out['changes'].append(dict(type='Budget step', campaign_id=CID, lane='auto', row_id='Budget step:555::'))
        self.assertSkipped(self.shape(out=out), 'changes the campaign itself')
        self.assertSkipped(self.shape(snap=snapshot(campaigns=[campaign(audience=300)])), 'audience')
        self.assertSkipped(self.shape(snap=snapshot(live={CID: [ASIN, 'B0OTHER000']})), 'alone')
        self.assertSkipped(self.shape(snap=snapshot(campaigns=[campaign(name=f'Cards - {ASIN} - TOS 900%')])), 'experiment')
        out = self.shape(snap=snapshot(rows=[place(CID, 'Top of Search on-Amazon', 20, 2)]))
        self.assertEqual(out['summary'][0]['placement_shape']['skipped'], [])   # too little data: not even reported
        self.assertNotIn('Placement shape', [x['type'] for x in out['changes']])

    @unittest.skip('needs files from the original account')
    def test_overnight_experiment_campaigns_are_never_shaped(self):
        self.assertSkipped(self.shape(snap=snapshot(campaigns=[campaign(name=f'ON80 | {ASIN} | Cards - Broad')])),
                           'live experiment')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'map.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump([dict(asin=ASIN, created_ids=[dict(source=CID, campaignId='999')])], f)
            self.assertSkipped(self.shape(experiment_files=[path]), 'live experiment')
            self.assertSkipped(self.shape(experiment_files=[os.path.join(tmp, 'gone.json')]), 'experiment file')
        # the real experiment files are in the repo, and they name the overnight test's originals and copies
        ids, missing = placement_shape.experiment_campaigns(CONFIG['placement']['shape']['experiment_files'])
        self.assertEqual(missing, [])
        self.assertTrue({'900000000000014', '900000000000015'} <= ids)

    def test_placements_that_convert_alike_are_not_shaped(self):
        rows = [place(CID, 'Top of Search on-Amazon', 200, 30), place(CID, 'Other on-Amazon', 200, 29),
                place(CID, 'Detail Page on-Amazon', 200, 28)]
        self.assertSkipped(self.shape(snap=snapshot(rows=rows)), 'within 10%')


def row_target(row, placement):
    """The share of the plan's price a placement may bid: its conversion against the best (min share), rank TOS whole."""
    cvr = row['placement_cvr']
    best = max(cvr.values())
    if row.get('rank_tos') is not None and placement == 'TOP_OF_SEARCH':
        return 1 + row['rank_tos'] / 100
    return max(0.5, cvr[placement] / best)


class StrategyTest(unittest.TestCase):
    kind = staticmethod(lambda name: 'audience' if 'AMC' in (name or '') else 'consumer')

    def rows(self, campaigns, snap='default', enabled=True):
        plc = dict(down_only=dict(enabled=enabled))
        snap = snapshot(campaigns=campaigns) if snap == 'default' else snap
        return placement_review.strategy_rows(campaigns, ASIN, plc, self.kind, snap)

    def test_an_up_and_down_campaign_moves_to_down_only_with_its_adjustments_as_live(self):
        live = campaign(strategy='SALES_UP_AND_DOWN', tos=30)
        [row] = self.rows([live, campaign(cid='556'), campaign(cid='557', strategy='MANUAL')])
        self.assertEqual((row['type'], row['campaign_id'], row['strategy']), ('Bidding strategy', CID, 'SALES_DOWN_ONLY'))
        self.assertEqual(row['bid_adjustments'], live['optimizations']['bidSettings']['bidAdjustments'])
        self.assertFalse(row['audience'] or row['scope_unverified'])
        [(name, [update])] = planner.payload_files([row], CONFIG, ASIN)
        self.assertEqual(name, '5b_bidding_strategy.json')
        self.assertEqual(update, dict(type='sp_campaigns', campaignId=CID, optimizations=dict(bidSettings=dict(
            bidStrategy='SALES_DOWN_ONLY', bidAdjustments=live['optimizations']['bidSettings']['bidAdjustments']))))

    def test_an_audience_or_unverified_campaign_goes_to_a_person(self):
        amc = campaign(name=f'Cards - {ASIN} - AMC - Low Bids 0.25', strategy='SALES_UP_AND_DOWN', audience=300)
        [row] = self.rows([amc])
        self.assertTrue(row['audience'])
        self.assertEqual(row['bid_adjustments']['audienceBidAdjustments'], [dict(audienceId='42', percentage=300)])
        [row] = self.rows([campaign(strategy='SALES_UP_AND_DOWN')], snap=None)
        self.assertTrue(row['scope_unverified'])
        ctx = lanes.Ctx(auto=dict(T.AUTO), profit_per_unit=5.0, stale=None, onboarding=False, locks={}, today=TODAY,
                        band_left_month=0, raises_left=3)
        self.assertEqual(lanes.classify(dict(row, scope_unverified=False), None, ctx)[0], 'auto')
        self.assertEqual(lanes.classify(row, None, ctx)[0], 'human')
        self.assertEqual(lanes.classify(dict(row, scope_unverified=False, audience=True), None, ctx)[0], 'human')

    def test_switched_off_and_global_campaigns_plan_none(self):
        self.assertEqual(self.rows([campaign(strategy='SALES_UP_AND_DOWN')], enabled=False), [])
        self.assertEqual(self.rows([campaign(strategy='SALES_UP_AND_DOWN', globalCampaignId='g1')]), [])


class MainTest(unittest.TestCase):
    """plan.main shapes after the lanes and writes the shape last; an up-and-down campaign it can't shape gets 5b."""

    def test_main_writes_the_strategy_and_the_shape(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run, data = os.path.join(tmp.name, 'run'), os.path.join(tmp.name, 'data')
        T.make_run(run)
        path = os.path.join(run, 'campaigns.json')
        with open(path, encoding='utf-8') as f:
            camps = json.load(f)['items']
        for c in camps:
            c.setdefault('optimizations', dict(bidSettings=dict(bidStrategy='SALES_DOWN_ONLY',
                                                                bidAdjustments=dict(placementBidAdjustments=[]))))
        auto_id = T.IDS[T.AUTO_CAMPAIGN][0]
        next(c for c in camps if c['campaignId'] == auto_id)['optimizations']['bidSettings']['bidStrategy'] = 'SALES_UP_AND_DOWN'
        T.write(path, dict(items=camps))
        rows = [r for c in camps for r in (place(c['campaignId'], 'Top of Search on-Amazon', 200, 32),
                                           place(c['campaignId'], 'Other on-Amazon', 100, 14),
                                           place(c['campaignId'], 'Detail Page on-Amazon', 200, 16))]
        snap = dict(snapshot(campaigns=camps, rows=rows, as_of=T.TODAY), retrieved_at=T.TODAY + 'T10:00:00+08:00',
                    windows={'30d': ['2026-09-05', '2026-10-04'], '90d': ['2026-07-07', '2026-10-04'],
                             'recent': ['2026-09-19', '2026-10-18']})
        T.write(os.path.join(run, 'placement_inputs.json'), snap)
        os.makedirs(os.path.join(data, 'asins'))
        T.write(os.path.join(data, 'asins', f'{ASIN}.json'), T.product())
        argv = ['plan.py', '--asin', ASIN, '--run', run, '--data', data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.planned_at(), T.without_mid():
            planner.main()
        with open(os.path.join(run, 'plan.json'), encoding='utf-8') as f:
            plan = json.load(f)
        shaped = {x['campaign_id'] for x in plan['summary'][0]['placement_shape']['shaped']}
        self.assertIn(T.IDS[T.BROAD][0], shaped)
        self.assertIn(T.IDS[T.SKC][0], shaped)
        auto = sorted(os.listdir(os.path.join(run, 'payloads', 'auto')))
        self.assertIn('5b_bidding_strategy.json', auto)
        self.assertEqual([f for f in auto if f.endswith('.json') and f != 'rows.json'][-1], '9c_placement_shape.json')
        strategy = [x for x in plan['changes'] if x['type'] == 'Bidding strategy']
        self.assertEqual([(x['campaign_id'], x['lane']) for x in strategy], [(auto_id, 'auto')])
        self.assertNotIn('target_plan', plan)


class NonRankFactorTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = T.PlannerLanesTest.plan

    def test_config_is_breakeven_since_decision_157(self):
        self.assertEqual(CONFIG['thresholds']['non_rank_bid_factor'], 1.0)

    def test_non_rank_keywords_bid_85_percent_and_rank_ones_are_unchanged(self):
        base = T.shared_config()
        cut = T.shared_config()
        cut['thresholds']['non_rank_bid_factor'] = 0.85
        full = {p['keyword_id']: p for p in self.plan(shared=base, write_out=False)['keyword_plan']}
        low = {p['keyword_id']: p for p in self.plan(shared=cut, write_out=False)['keyword_plan']}
        seen = set()
        for kid, p in full.items():
            q = low[kid]
            if p['role'] in ('Hold', 'Defend', 'Discovery') and not p['action'].startswith(('Keep', 'Pause')):
                seen.add(p['role'])
                self.assertAlmostEqual(q['new_bid'], round(p['new_bid'] * 0.85, 2), delta=0.011, msg=(kid, p, q))
                self.assertIn('85% of breakeven', q['action'])
            elif p['role'] in ('Rank', 'Trim'):
                self.assertEqual(q['new_bid'], p['new_bid'], (kid, p['role']))
        self.assertTrue(seen, 'the fixture has non-rank keywords')


if __name__ == '__main__':
    unittest.main()
