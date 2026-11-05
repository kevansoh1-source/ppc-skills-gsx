"""Decision 156 (Kim, 2026-10-27: "check to see if the new skill covers every single campaign and every single keyword,
product targeting on SP, SB, SD for the ASIN, don't leave any out"; "Price the bid around the boost"; "we can leave out
campaigns with multiple ASINs ... done on purpose for product collection ads and cross selling campaigns").

1. a campaign is the product's when its own ads say so (ad_campaigns_p*.json), not only when its name carries the ASIN.
2. a campaign that advertises several ASINs is left out of the pricing and listed in the coverage ledger.
3. an audience bid adjustment (the AMC campaigns' +240% to +300%) is priced around: price / (1 + the boost).
4. Sponsored Brands theme targets are priced, cut only.
5. a live Sponsored Display target with no 90-day row is priced; a vCPM campaign is listed for a person.
6. a run missing a live read the coverage check needs stops (coverage.stop_on_missing_reads).

Built on test_plan_lanes' synthetic run (make_run): profit $5.00 a unit, the product's ad conversion 13 orders on 88
clicks.
"""
import json
import os
import unittest

import coverage
import plan as planner
import test_plan_lanes as T
import test_price_everything as P

AD_CVR = 13 / 88
OWN = 'Auto - $0.65 down only'            # this product's campaign, named without its ASIN
CROSS = f'Cards - {T.ASIN} - Cross-Selling - Cards and Bookmarks'   # carries the ASIN, advertises two


def ad_row(cid, name, asins, ad_type='SP', spend90=10):
    return dict(ad_type=ad_type, campaignId=cid, campaignName=name, asins=','.join(asins), spend90=spend90)


def kw_row(kid, text, cid, name, bid=1.50, clicks=20, orders=0, spend=9):
    return dict(KeywordId=kid, Keyword=text, MatchType='phrase', CampaignName=name, CampaignId=cid, AdGroupId='g' + cid,
                AdGroupName='Group', AdType='SP', Bid=bid, Clicks=clicks, Orders=orders, Spend=spend, Sales=orders * 10)


def sp_campaign(cid, name, audience=None):
    c = dict(campaignId=cid, name=name, state='ENABLED', budget=dict(budget=10),
             optimizations=dict(bidSettings=dict(bidStrategy='SALES_DOWN_ONLY', bidAdjustments=dict(
                 placementBidAdjustments=[dict(placement='PLACEMENT_TOP', percentage=0)]))))
    if audience:
        c['optimizations']['bidSettings']['bidAdjustments']['audienceBidAdjustments'] = [dict(audienceId='a1', percentage=audience)]
    return c


def fixture_campaigns(*more):
    return [T.campaign(n) for n in (T.STW, T.AUTO_CAMPAIGN, T.BROAD, T.LOW, T.PT)] + [T.campaign(T.SKC, tos=50)] + list(more)


class Base(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, extra=None, keywords=None, cfg=None, shared_cfg=None, items=None):
        files = {'live_keywords_p1.json': [], 'live_targets_p1.json': [], 'campaigns.json': dict(items=items or fixture_campaigns())}
        files.update(extra or {})
        T.make_run(self.run_dir, keywords=keywords, extra=files)
        s = shared_cfg or T.shared_config()
        out = planner.build(T.ASIN, cfg or T.product(), s, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        planner.write_outputs(self.run_dir, out, s, T.ASIN)
        return out


class CampaignScopeTest(Base):
    def test_a_campaign_named_without_the_asin_is_priced_from_its_own_ads(self):
        ads = [ad_row('501', OWN, [T.ASIN])]
        out = self.plan(extra={'ad_campaigns_p1.json': dict(data=ads), 'own_campaigns.json': dict(items=[sp_campaign('501', OWN)])},
                        keywords=T.KEYWORDS + [kw_row('51', 'pretty cards', '501', OWN)])
        row = T.one(out, 'Bid change', keyword_id='51')
        self.assertLess(row['new'], 1.50)
        scope = out['summary'][0]['campaign_scope']
        self.assertEqual((scope['read'], scope['own']), (True, [dict(id='501', name=OWN, ad_type='SP')]))

    def test_without_its_ads_read_the_unnamed_campaign_is_missed_and_the_run_asks(self):
        out = self.plan(extra={'ad_campaigns_p1.json': None}, keywords=T.KEYWORDS + [kw_row('51', 'pretty cards', '501', OWN)])
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == '51'], [])
        self.assertEqual(out['summary'][0]['campaign_scope'], dict(read=False, sb_multi=[]))
        self.assertIn('ad_campaigns', out['summary'][0]['coverage']['reads_missing'])

    def test_a_multi_asin_campaign_is_left_out_and_listed(self):
        ads = [ad_row('502', CROSS, [T.ASIN, 'B0OTHER001'], spend90=42.5)]
        out = self.plan(extra={'ad_campaigns_p1.json': dict(data=ads)}, items=fixture_campaigns(sp_campaign('502', CROSS)),
                        keywords=T.KEYWORDS + [kw_row('52', 'pretty cards', '502', CROSS)])
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == '52' or x.get('campaign_id') == '502'], [])
        multi = out['summary'][0]['campaign_scope']['multi']
        self.assertEqual(multi, [dict(id='502', name=CROSS, ad_type='SP', asins=['B0OTHER001', T.ASIN], spend90=42.5)])
        cov = out['summary'][0]['coverage']
        self.assertEqual(cov['by_kind']['sp_campaign'].get('multi_asin'), 1)
        self.assertEqual(cov['unowned'], 0)

    def test_a_campaign_of_another_product_alone_is_never_ours(self):
        ads = [ad_row('503', 'Auto - other', ['B0OTHER001'])]
        out = self.plan(extra={'ad_campaigns_p1.json': dict(data=ads)},
                        keywords=T.KEYWORDS + [kw_row('53', 'pretty cards', '503', 'Auto - other')])
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == '53'], [])
        self.assertEqual(out['summary'][0]['campaign_scope']['own'], [])


class AudienceBoostTest(Base):
    def test_an_audience_campaign_is_priced_around_its_boost(self):
        plain = T.one(self.plan(), 'Bid change', keyword_id='5')
        items = [sp_campaign('103', T.BROAD, audience=240) if c['campaignId'] == '103' else c for c in fixture_campaigns()]
        out = self.plan(items=items)
        row = T.one(out, 'Bid change', keyword_id='5')
        # +240% for the audience's shoppers, so a $1.00 bid pays $3.40 for them: the bid is the price / 3.4
        self.assertEqual((row['priced_bid'], row['boost_kept']), (plain['new'], 240))
        self.assertEqual(row['new'], max(0.02, round(plain['new'] / 3.4, 2)))
        self.assertIn('+240% audience boost', row['why'])
        self.assertEqual(out['summary'][0]['placement_policy']['audience_boost'], {'103': 240})

    def test_switched_off_it_prices_as_before(self):
        plain = T.one(self.plan(), 'Bid change', keyword_id='5')
        s = T.shared_config()
        s['placement'] = dict(s['placement'], audience=dict(price_around=False))
        items = [sp_campaign('103', T.BROAD, audience=240) if c['campaignId'] == '103' else c for c in fixture_campaigns()]
        row = T.one(self.plan(items=items, shared_cfg=s), 'Bid change', keyword_id='5')
        self.assertEqual(row['new'], plain['new'])


class ThemeTest(Base):
    def sb(self, themes, perf=(), camps_extra=()):
        files = P.PriceEverythingTest.sb_files(self, [], perf)
        files['sb_campaigns_p1.json']['items'] += list(camps_extra)
        files['sb_themes_p1.json'] = dict(items=themes)
        cfg = T.product(sb_video=dict(enabled=True, campaigns=['sb1'], video_asset_id='asset'))
        return self.plan(extra=files, cfg=cfg)

    def test_a_theme_target_is_priced_cut_only(self):
        themes = [dict(themeId='th1', campaignId='sb2', adGroupId='gsb2', themeType='KEYWORDS_RELATED_TO_YOUR_BRAND',
                       state='ENABLED', bid=1.50),
                  dict(themeId='th2', campaignId='sb2', adGroupId='gsb2', themeType='KEYWORDS_RELATED_TO_YOUR_LANDING_PAGES',
                       state='ENABLED', bid=0.25)]
        out = self.sb(themes, perf=[dict(keywordId='th1', clicks=10, purchases=0, cost=9)])
        row = T.one(out, 'SB bid change', theme_id='th1')
        self.assertEqual((row['role'], row['keyword'], row['match'], row['lane']),
                         ('Theme cap', 'keywords related to your brand', 'theme', 'auto'))
        self.assertLess(row['new'], 1.50)
        self.assertEqual([x for x in out['changes'] if x.get('theme_id') == 'th2'], [])   # under its price: never raised
        payloads = T.read_payloads(self.run_dir, 'auto')
        self.assertEqual(payloads['8d_sb_theme_updates.json'],
                         [dict(type='sb_themes', themeId='th1', adGroupId='gsb2', campaignId='sb2', bid=row['new'])])
        self.assertNotIn('th1', json.dumps([u for n, rows in payloads.items() if n != '8d_sb_theme_updates.json' for u in rows]))
        by = out['summary'][0]['coverage']['by_kind']['sb_theme']
        self.assertEqual(by, {'changed': 1, 'priced': 1})

    def test_themes_not_read_ask_for_them(self):
        files = P.PriceEverythingTest.sb_files(self, [P.PriceEverythingTest.sb_kw('k2', 'sb2', 'gold cards', 'EXACT', 1.50)])
        cfg = T.product(sb_video=dict(enabled=True, campaigns=['sb1'], video_asset_id='asset'))
        out = self.plan(extra=files, cfg=cfg)
        with open(os.path.join(self.run_dir, 'need_sb_keywords.json')) as fh:
            need = json.load(fh)
        self.assertIs(need['themes_read'], False)
        self.assertIn('sb_themes', need['how'])
        self.assertIn('sb_themes', out['summary'][0]['coverage']['reads_missing'])

    def test_a_product_collection_campaign_is_left_out_and_listed(self):
        pc = dict(campaignId='sb7', name=f'Cards - {T.ASIN} - Product Collection - Cards', state='ENABLED', budget=5)
        files = P.PriceEverythingTest.sb_files(self, [P.PriceEverythingTest.sb_kw('k9', 'sb7', 'cards', 'BROAD', 1.40)])
        files['sb_campaigns_p1.json']['items'].append(pc)
        cfg = T.product(sb_video=dict(enabled=True, campaigns=['sb1'], video_asset_id='asset'))
        out = self.plan(extra=files, cfg=cfg)
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == 'k9' or x.get('campaign_id') == 'sb7'], [])
        self.assertEqual(out['summary'][0]['campaign_scope']['sb_multi'], [dict(id='sb7', name=pc['name'])])
        self.assertEqual(out['summary'][0]['coverage']['by_kind']['sb_campaign'].get('multi_asin'), 1)


class DisplayTest(Base):
    def test_an_idle_live_target_is_priced_and_a_vcpm_campaign_is_listed(self):
        name = P.SD_CAMPAIGN
        ads = [ad_row('601', name, [T.ASIN], 'SD'), ad_row('602', 'Display - Views', [T.ASIN], 'SD')]
        camps = [dict(campaignId='601', name=name, state='enabled', costType='cpc'),
                 dict(campaignId='602', name='Display - Views', state='enabled', costType='vcpm')]
        live = [dict(targetId='701', campaignId='601', adGroupId='g601', state='enabled', bid=1.80,
                     expression=[dict(type='asinSameAs', value='B0SAMP0036')]),
                dict(targetId='702', campaignId='602', adGroupId='g602', state='enabled', bid=9.00, expression=[dict(type='views')])]
        out = self.plan(extra={'ad_campaigns_p1.json': dict(data=ads), 'sd_targets_p1.json': dict(data=[]),
                               'sd_campaigns_p1.json': dict(items=camps), 'live_sd_targets_p1.json': dict(items=live)})
        row = T.one(out, 'Target bid change', target_id='701')
        self.assertEqual(row['ad_product'], 'SD')
        self.assertLess(row['new'], 1.80)
        self.assertEqual([x for x in out['changes'] if x.get('target_id') == '702'], [])
        by = out['summary'][0]['coverage']['by_kind']
        self.assertEqual(by['sd_campaign'], {'priced': 1, 'vcpm': 1})
        self.assertEqual(by['sd_target'], {'changed': 1, 'vcpm': 1})

    def test_live_sd_targets_not_read_are_asked_for(self):
        ads = [ad_row('601', P.SD_CAMPAIGN, [T.ASIN], 'SD')]
        camps = [dict(campaignId='601', name=P.SD_CAMPAIGN, state='enabled', costType='cpc')]
        out = self.plan(extra={'ad_campaigns_p1.json': dict(data=ads), 'sd_campaigns_p1.json': dict(items=camps)})
        self.assertIn('live_sd_targets', out['summary'][0]['coverage']['reads_missing'])
        need = planner.inventory_problem(self.run_dir, T.ASIN, T.shared_config())
        self.assertIn('live_sd_targets', json.dumps(need))


class StrategyTest(Base):
    def test_up_and_down_bidding_with_no_row_is_unowned(self):
        c = sp_campaign('501', OWN)
        c['optimizations']['bidSettings']['bidStrategy'] = 'SALES_UP_AND_DOWN'
        c['globalCampaignId'] = 'g501'    # a global campaign: the API can't change it, so nothing plans it
        ads = [ad_row('501', OWN, [T.ASIN])]
        out = self.plan(extra={'ad_campaigns_p1.json': dict(data=ads), 'own_campaigns.json': dict(items=[c])})
        cov = out['summary'][0]['coverage']
        self.assertIn(('sp_bidding_strategy', '501'), [(e['kind'], e['id']) for e in cov['unowned_rows']])
        self.assertIn('--accept-unowned', coverage.stop_reason(cov))

    def test_down_only_is_owned(self):
        out = self.plan()
        self.assertEqual(set(out['summary'][0]['coverage']['by_kind']['sp_bidding_strategy']), {'down_only'})


if __name__ == '__main__':
    unittest.main()
