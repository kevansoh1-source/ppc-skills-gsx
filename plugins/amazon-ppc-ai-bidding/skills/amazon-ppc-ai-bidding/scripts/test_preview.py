"""preview.py (C9, N7): the approval page shows what would go out, not the plan's raw proposals.

A shadow run's review/ writes a capped raise at the cap and never writes a held row (monitor, or locked), so the page
says so on those rows. Each test plans the synthetic run test_plan_lanes builds, then reads the data the page embeds.
"""
import contextlib
import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock

import plan as planner
import preview
import test_plan_lanes as T

ASIN = T.ASIN


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


class PreviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.run_dir = os.path.join(self.tmp, 'run')
        self.data = os.path.join(self.tmp, 'data')

    def plan(self, **product_over):
        T.make_run(self.run_dir)
        os.makedirs(os.path.join(self.data, 'asins'), exist_ok=True)
        T.write(os.path.join(self.data, 'asins', f'{ASIN}.json'), T.product(**product_over))
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.without_mid():
            planner.main()
        return read_json(os.path.join(self.run_dir, 'plan.json'))

    def page_rows(self):
        """{row_id: row} of the changes the preview page embeds, built by preview.py's main()."""
        return {r['row_id']: r for r in self.page_data()['changes']}

    def page_data(self):
        """The data the preview page embeds (changes, notes, ...), built by preview.py's main()."""
        out = os.path.join(self.tmp, 'preview.html')
        argv = ['preview.py', '--out', out, os.path.join(self.run_dir, 'plan.json')]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            preview.main()
        with open(out, encoding='utf-8') as fh:
            page = fh.read()
        script = re.findall(r'<script>(.*?)</script>', page, re.S)[0]
        return json.loads(re.search(r'const DATA = (\{.*?\});\n', script, re.S).group(1).replace('<\\/', '</'))

    def test_the_notes_say_business_rows_follow_the_same_lanes(self):
        """The standing notes the approver reads name the Amazon Business campaigns next to the audience ones: business rows
        take the same lanes as consumer rows, and a business invest happens inside the team's own B2B campaign."""
        self.plan(auto=dict(T.AUTO, enabled=False))
        notes = ' '.join(self.page_data()['notes'])
        self.assertIn('Amazon Business (B2B) campaigns are priced on their own conversion', notes)
        self.assertIn("business rows follow the same lanes as consumer rows, judged on the B2B keyword's own evidence", notes)
        self.assertIn("Business invests happen inside the team's B2B campaigns", notes)
        self.assertNotIn('until the Nov 9 gate', notes)

    def business_page(self):
        """The preview data of the business fixture (test_business_roles): its B2B campaigns live at a $7/day budget and
        +100% top of search, as the team's run (+95-105% on 2026-10-21), so the first business invest cuts the boost."""
        import test_business_roles as R
        campaigns = [dict(T.campaign(n, budget=7, tos=100), siteRestrictions=['AMAZON_BUSINESS'])
                     for n in (R.B.B2B_EXACT, R.B.B2B_STWS, R.B2B_STWS_EXACT, R.B2B_EXACT2)]
        T.make_run(self.run_dir, extra={'suggested_bids_business.json': R.SUGGESTED_B}, queries=R.QUERIES,
                   search_terms=R.SEARCH_TERMS, keywords=R.KEYWORDS, more_campaigns=campaigns, suggested=R.SUGGESTED)
        out = planner.build(ASIN, R.product(), R.shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        T.write(os.path.join(self.run_dir, 'plan.json'), json.loads(json.dumps(out, default=str)))
        return self.page_data()

    def test_a_business_invest_shows_its_campaign_s_top_of_search_and_budget_from_and_to(self):
        """Spec 4b: the first Business invest on a B2B campaign cuts top of search for every keyword in it, so its table
        shows the campaign's top of search and budget from and to (tos_now -> campaign_tos, budget_now -> campaign_budget)."""
        rows = [r for r in self.business_page()['changes'] if r['type'] == 'Business invest']
        row = next(r for r in rows if r['keyword'] == 'zebra cards')
        self.assertEqual((row['tos_now'], row['campaign_tos'], row['budget_now'], row['campaign_budget']), (100, 50, 7, 10))
        self.assertEqual((row['tos_change'], row['budget_change']), ('+100% → +50%', '$7 → $10/day'))

    def test_a_new_keyword_without_its_ad_group_says_it_writes_nothing(self):   # final review M1
        """A business New exact keyword whose ad group is unknown has no payload (plan.payload_entries), so its table says
        so instead of a top of search and budget change that would never go out."""
        row = preview.as_previewed(dict(type='New exact keyword', owner_kind='business', keyword='office cards', campaign_id='110',
                                        ad_group_id=None, tos_now=100, tos=50, budget_now=7, budget=10, new=1.2, why=''))
        self.assertEqual((row['tos_change'], row['budget_change']),
                         ('no payload: ad group unknown', 'no payload: ad group unknown'))

    def test_business_rerank_rows_carry_a_b2b_label(self):
        """The budget table lists a business invest next to the consumer one of the same search: a 'B2B' label tells
        them apart (owner_kind 'business'); a consumer row has none."""
        rerank = [r for r in self.business_page()['rerank'] if r['keyword'] == 'zebra cards']
        self.assertEqual(sorted(((r.get('owner_kind'), r.get('label')) for r in rerank), key=str),
                         sorted([('business', 'B2B'), (None, None)], key=str))

    def test_a_capped_shadow_row_shows_the_bid_approving_writes(self):
        """N7: keyword 4's raise to $0.62 (its breakeven, decision 157) goes past the +25% cap; review/ (and an approval) write $0.37."""
        plan = self.plan(auto=dict(T.AUTO, enabled=False))
        self.assertEqual(plan['summary'][0]['max_raise_pct'], 25)
        row = self.page_rows()['Bid change:4']
        self.assertEqual((row['current'], row['new'], row['change']), (0.3, 0.37, 0.233))
        self.assertTrue(row['why'].startswith('$0.62 → $0.37 (the +25% cap; approving writes $0.37). '), row['why'])
        target = self.page_rows()['Target bid change:302']
        self.assertTrue(target['why'].startswith('$0.74 → $0.37 (the +25% cap; approving writes $0.37). '), target['why'])

    def test_held_rows_say_they_are_not_in_this_apply(self):
        """A monitor row and a row a person's decision locks are in held/, never in review/."""
        refused = dict(id='Bid change:5', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        created = dict(id='New exact campaign:::blank cards', what='approve', by='Lee', on='2026-10-19', until='2026-11-17',
                       direction='other', kind='create', search='blank cards', created_on='2026-10-20')
        self.plan(auto=dict(T.AUTO, enabled=False), decisions=[refused, created])
        rows = self.page_rows()
        for rid in ('Bid change:6', 'Bid change:5', 'Pause keyword:2'):
            self.assertTrue(rows[rid]['why'].startswith('held: not in this apply. '), (rid, rows[rid]['why']))
        # a promotion's table shows its evidence, not a why
        self.assertTrue(rows['New exact campaign:::blank cards']['evidence'].startswith('held: not in this apply. '))
        self.assertFalse(rows['Bid change:1']['why'].startswith('held'))  # a row that goes out is shown as it is

    def without_lane(self, row):
        """The row as the page embeds it, less the lane line E9 adds at the end of its Why (or Evidence)."""
        field = 'evidence' if row.get('type') in preview.EVIDENCE_TYPES else 'why'
        text = row[field]
        cut = text.rindex('Lane: ')
        return dict(row, **{field: text[:cut].rstrip() or None}) if cut else dict(row, **{field: None})

    def test_rows_that_go_out_as_planned_are_unchanged(self):
        plan = self.plan(auto=dict(T.AUTO, enabled=False))
        rows = self.page_rows()
        for x in plan['changes']:
            if not (x.get('locked_until') or x.get('lane') == 'monitor' or x.get('new_capped') is not None):
                field = 'evidence' if x.get('type') in preview.EVIDENCE_TYPES else 'why'
                self.assertEqual(self.without_lane(rows[x['row_id']]), dict(x, **{field: x.get(field) or None}))

    def test_an_enabled_auto_row_already_shows_its_cap(self):
        """Enabled, the auto lane writes the cap into `new` itself (new_proposed keeps the proposal): nothing to relabel."""
        plan = self.plan()
        x = next(c for c in plan['changes'] if c['row_id'] == 'Bid change:4')
        self.assertEqual((x['new'], x.get('new_capped')), (0.37, None))
        self.assertEqual(self.without_lane(self.page_rows()['Bid change:4']), x)

    def test_an_older_plan_without_the_cap_in_its_summary_says_the_per_run_cap(self):
        row = dict(type='Bid change', row_id='Bid change:4', current=0.3, new=0.62, new_capped=0.37, change=1.067, why='x',
                   lane='auto')
        self.assertEqual(preview.as_previewed(row, None)['why'],
                         '$0.62 → $0.37 (the per-run cap; approving writes $0.37). x Lane: would apply automatically '
                         '(shadow run).')  # a plan that doesn't say otherwise is a shadow plan
        self.assertTrue(preview.as_previewed(row, None, shadow=False)['why'].endswith(' x Lane: applies automatically.'))

    # --- E9 (M1): the page says which lane each row is in, and when a promotion is past Kim's level ----------------
    def lane_of(self, row):
        """The lane line the page adds at the end of a row's Why (Evidence for a promotion)."""
        text = row['evidence'] if row.get('type') in preview.EVIDENCE_TYPES else row['why']
        self.assertIn(' Lane: ', ' ' + text)
        return text[text.rindex('Lane: '):]

    def test_every_row_says_its_lane(self):
        refused = dict(id='Bid change:5', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        # enabled; a price change is the human row (since autonomous runs, 2026-10-22, it is one of the few left)
        plan = self.plan(decisions=[refused], price_change=dict({'from': 7.99, 'to': 8.99, 'why': 'test'}))
        rows = self.page_rows()
        self.assertEqual(self.lane_of(rows['Bid change:3']), 'Lane: applies automatically.')    # a cut
        self.assertEqual(self.lane_of(rows['Bid change:6']), 'Lane: held.')                     # monitor
        self.assertEqual(self.lane_of(rows['Bid change:5']), 'Lane: held.')                     # a decline holds it
        human = next(x for x in plan['changes'] if x['lane'] == 'human' and not x.get('locked_until'))
        self.assertEqual(self.lane_of(rows[human['row_id']]), 'Lane: waits for a person.')
        self.assertEqual(self.lane_of(rows['New exact campaign:::blank cards']), 'Lane: applies automatically.')
        for x in plan['changes']:
            self.assertEqual(rows[x['row_id']]['lane'], x['lane'])  # only the words change

    def test_a_shadow_row_says_it_would_apply_automatically(self):
        self.plan(auto=dict(T.AUTO, enabled=False))
        rows = self.page_rows()
        self.assertEqual(self.lane_of(rows['Bid change:3']), 'Lane: would apply automatically (shadow run).')
        self.assertEqual(self.lane_of(rows['Bid change:6']), 'Lane: held.')

    def test_the_stage_note_names_the_counts_and_the_volatile_week(self):
        """Rulebook 10.1: one note per product when its data stage is not mature, with the three counts and, after them,
        the volatile-week text; a mature product gets no stage note (final review, 2026-10-22)."""
        plan = self.plan()
        self.assertEqual(plan['summary'][0]['stage']['stage'], 'mature')
        self.assertEqual([n for n in self.page_data()['notes'] if 'data stage' in n], [])
        plan['summary'][0]['stage'] = dict(stage='early', sqp_queries=231, observed_days=21, trusted_queries=13,
                                           reason='early: 21 observed days, 13 trusted queries, 231 SQP queries with impressions',
                                           left_launch_this_run=False)
        plan['summary'][0]['volatile_week'] = ('volatile SQP week: the SQP since 2026-10-10 (through 2026-10-17) added 389 of '
                                               'our clicks, more than the 214 of all earlier weeks')
        T.write(os.path.join(self.run_dir, 'plan.json'), plan)
        notes = [n for n in self.page_data()['notes'] if 'data stage' in n]
        self.assertEqual(notes, [f"{plan['summary'][0]['product']}: data stage early (21 observed days, 13 trusted queries, "
                                 '231 SQP queries with impressions); volatile SQP week: the SQP since 2026-10-10 (through '
                                 '2026-10-17) added 389 of our clicks, more than the 214 of all earlier weeks'])

    def test_a_promotion_past_kims_level_says_so(self):
        # since 2026-10-22 (decision 99) no plan flags a promotion past a money level: the guide is information only
        plan = self.plan(auto=dict(T.AUTO, invest_guide_month=10))
        self.assertNotIn('kim_product_month', plan['summary'][0])
        self.assertIs(plan['summary'][0]['above_invest_guide'], True)
        rows = self.page_rows()
        promo = rows['New exact campaign:::blank cards']
        self.assertNotIn('past_kim_level', promo)
        self.assertEqual(self.lane_of(promo), 'Lane: applies automatically.')
        # an older plan's flagged row still says so, without a number
        row = dict(type='New exact campaign', row_id='p', lane='human', past_kim_level=True, evidence='x')
        self.assertEqual(preview.as_previewed(row, None)['evidence'], "x Lane: waits for a person · past Kim's monthly level.")


class StandingPolicyCopyTest(unittest.TestCase):
    """The copy the preview's rules table (preview.RULES) and the dashboard's verdict legend (dashboard.verdicts) give for a
    rank campaign's top of search: the standing policy (Kim, 2026-10-20), not "0%" or "no boost"."""

    def rule(self, role):
        return next(r for r in preview.RULES if r['role'] == role)

    def test_the_rules_table_says_rank_top_of_search_is_standing_policy(self):
        invest, prove = (' '.join(str(v) for v in self.rule(role).values()) for role in ('Invest', 'Prove first'))
        self.assertIn('top of search +50%', invest)
        self.assertIn('top of search +30%', prove)
        for text in (invest, prove):
            self.assertIn('standing policy', text)
            self.assertIn('Kim 2026-10-20', text)
            self.assertNotIn('start at 0%', text)
            self.assertNotIn('no automatic placement boost', text)

    def test_the_verdict_legend_follows_the_standing_policy_flag(self):
        import dashboard
        config = copy.deepcopy(T.CONFIG)
        by_id = lambda cfg: {v[0]: v[2] for v in dashboard.verdicts(cfg)}
        on = by_id(config)  # the live config has the flag on, +50 / +30
        self.assertIn('top of search +50% (standing policy, Kim 2026-10-20)', on['invest'])
        self.assertIn('top of search +30% (standing policy, Kim 2026-10-20)', on['prove'])
        self.assertNotIn('no automatic placement boost', on['prove'])
        self.assertNotIn('placements reviewed separately', on['invest'])
        # the figures come from the config, and the flag off gives the old copy
        config['placement'].update(invest_tos_pct=60, prove_tos_pct=20)
        self.assertIn('top of search +60%', by_id(config)['invest'])
        self.assertIn('top of search +20%', by_id(config)['prove'])
        config['placement']['rank_tos_standing']['approved'] = False
        off = by_id(config)
        self.assertIn('placements reviewed separately', off['invest'])
        self.assertIn('no automatic placement boost', off['prove'])
        self.assertNotIn('standing policy', off['invest'] + off['prove'])


class GrowthLineTest(unittest.TestCase):
    """R32: the For Growth item is not a Needs-human item. The preview's Needs-human area shows no tile for it, only one
    line pointing at the For Growth tab; every other item keeps its tile."""

    @unittest.skip('needs files from the original account')
    def test_a_growth_item_is_one_line_not_a_needs_human_tile(self):
        import growth
        import test_growth as G
        item = growth.build_item(G.GEL, G.gel_plan(), G.gel_product(), G.CFG, G.gel_listing(), '2026-11-20', 'first_pass',
                                 produced='2026-11-20 10:00 SGT')
        gap = dict(id='listing-conversion-gap', kind='listing', title='Assess query fit', reason='x', action='y', source='z',
                   window='w', status='open', ai_review=dict(phase='human_ready'))
        page = preview.human_review_html([('Pastel Gel Pens · B0SAMP0012', [item, gap], 'first_pass')])
        self.assertIn('For Growth: first listing optimization block produced (see the For Growth tab)', page)
        self.assertEqual(page.count('For Growth: first listing optimization block produced'), 1)
        self.assertNotIn('Growth review', page)                     # no tile of its own
        self.assertNotIn(item['title'], page)
        self.assertNotIn('/growth-listing-optimizer', page)
        self.assertIn('Assess query fit', page)                     # the other items keep their tiles
        # decisions only (decision 97, merged 2026-10-22): the line sits in a For Growth part of its own, after the
        # decisions, never inside the Human decisions section
        sections = dict(re.findall(r'<section id="([^"]+)">(.*?)</section>', page))
        self.assertEqual(list(sections), ['needs-human', 'for-growth'])
        self.assertIn('For Growth: first listing optimization block produced', sections['for-growth'])
        self.assertNotIn('For Growth:', sections['needs-human'])
        self.assertIn('Assess query fit', sections['needs-human'])
        # a closed growth item carried by the plan says nothing
        closed = dict(item, status='resolved', resolved_on='2026-11-27')
        self.assertNotIn('For Growth', preview.human_review_html([('Pastel Gel Pens · B0SAMP0012', [closed, gap], None)]))

    @unittest.skip('needs files from the original account')
    def test_a_carried_item_says_open_since_not_produced(self):
        """M3: "block produced" only when this run raised the item (summary[0].growth_trigger); an active item the plan
        only carries says it is open, its status and the day its pass opened."""
        import growth
        import test_growth as G
        item = growth.build_item(G.GEL, G.gel_plan(), G.gel_product(), G.CFG, G.gel_listing(), '2026-11-20', 'first_pass',
                                 produced='2026-11-20 10:00 SGT')
        label = 'Pastel Gel Pens · B0SAMP0012'
        carried = preview.human_review_html([(label, [dict(item, status='in_progress')], None)])
        self.assertIn(f'{label} · For Growth: open (picked up) since 2026-11-20 (see the For Growth tab)', carried)
        self.assertNotIn('block produced', carried)
        self.assertIn('For Growth: open (not picked up yet) since 2026-11-20',
                      preview.human_review_html([(label, [item], None)]))
        self.assertIn('For Growth: open (copy pushed) since 2026-11-20',
                      preview.human_review_html([(label, [dict(item, status='copy_pushed')], None)]))
        # main() reads the trigger from the plan's summary
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        def page(trigger, status='open'):
            plan_path, out = os.path.join(tmp.name, 'plan.json'), os.path.join(tmp.name, 'preview.html')
            doc = {'summary': [{'product': 'Pastel Gel Pens', 'asin': G.GEL, 'growth_trigger': trigger}], 'changes': [],
                   'rerank': [], 'human_review': [dict(item, status=status)]}
            with open(plan_path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh)
            argv = ['preview.py', '--out', out, plan_path]
            with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                preview.main()
            with open(out, encoding='utf-8') as fh:
                return fh.read()
        self.assertIn('For Growth: first listing optimization block produced (see the For Growth tab)', page('first_pass'))
        quiet = page(None, 'in_progress')
        self.assertIn('For Growth: open (picked up) since 2026-11-20 (see the For Growth tab)', quiet)
        self.assertNotIn('block produced', quiet)


if __name__ == '__main__':
    unittest.main()
