"""notify.py: the one Slack message of an autonomous run (Kim, 2026-10-22, decision 98): a recap of what went out, tagging the
book owner, and a "For PPC" section only when something is parked, tagging whoever decides. Posted in #3d-ppc-standup
(C0EXAMPLE01) by the agent; notify.py only builds it."""
import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest

import notify
import plan as planner
import plan_lanes
import test_plan_lanes as T

SKILL = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((SKILL / 'config.json').read_text(encoding='utf-8'))
ASIN = T.ASIN
PEOPLE = {'Kim': 'U0EXAMPLE03', 'Lee': 'U0EXAMPLE04', 'Alex': 'U0EXAMPLE05', 'Sam': 'U0EXAMPLE06'}
SHARED = dict(T.shared_config(), notify=dict(CONFIG['notify']))


def tag(name):
    return f'<@{PEOPLE[name]}>'


class NotifyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.run_dir = os.path.join(self.tmp, 'run')

    def plan(self, cfg=None, **run):
        T.make_run(self.run_dir, **run)
        out = planner.build(ASIN, cfg or T.product(), SHARED, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        out['summary'][0]['review_date'] = T.TODAY
        return out

    def went_out(self, plan, lane='auto'):
        return {x['row_id']: dict(date='2026-10-20', folder='auto') for x in plan['changes'] if x['lane'] == lane}

    def test_the_config_names_the_standup_channel_and_the_people(self):
        n = CONFIG['notify']
        self.assertEqual((n['channel'], n['channel_id']), ('#3d-ppc-standup', 'C0EXAMPLE01'))
        self.assertEqual(n['people'], PEOPLE)
        self.assertEqual((n['fallback_owner'], n['dashboard_url']), ('Lee', 'https://your-dashboard.example.com/#/'))

    def test_a_run_with_nothing_applied_or_parked_still_gets_a_one_line_recap(self):
        plan = dict(summary=[dict(asin=ASIN, shadow=False, review_date=T.TODAY)], changes=[], human_review=[])
        msg = notify.message(plan, T.product(registry=dict(book_owner='Sam')), SHARED, ASIN, {}, T.TODAY)
        self.assertEqual(msg['text'], f"{tag('Sam')} PPC AI run: Test cards ({ASIN}), {T.TODAY}\nNo changes this run.\n"
                                      f'https://your-dashboard.example.com/#/{ASIN}')
        self.assertEqual((msg['channel'], msg['channel_id'], msg['mentions'], msg['owner']),
                         ('#3d-ppc-standup', 'C0EXAMPLE01', [tag('Sam')], 'Sam'))
        self.assertNotIn(notify.FOR_HUMAN, msg['text'])

    def test_the_recap_is_counts_and_money_only_and_tags_the_book_owner(self):
        plan = self.plan()
        applied = self.went_out(plan)
        msg = notify.message(plan, T.product(registry=dict(book_owner='Alex')), SHARED, ASIN, applied, T.TODAY)
        lines = msg['text'].split('\n')
        self.assertEqual(lines[0], f"{tag('Alex')} PPC AI run: Test cards ({ASIN}), {T.TODAY}")
        rows = [x for x in plan['changes'] if x['row_id'] in applied]
        bids = [x for x in rows if x['type'] in notify.BID_TYPES]
        down = sum(1 for x in bids if x['new'] < x['current'])
        self.assertIn(f'- Bids: {down} cut, {len(bids) - down} raised', lines)
        promo = T.one(plan, 'New exact campaign', keyword='blank cards')
        self.assertIn(f"- Rank campaigns: 1 new or promoted search at ${promo['budget']}/day (modelled "
                      f"${promo['modelled_spend_month']} a month)", lines)
        negs = sum(1 for x in rows if x['type'] == 'Negative exact')
        pauses = sum(1 for x in rows if x['type'] in notify.PAUSE_TYPES)
        self.assertIn(f'- Pauses: {pauses}; negatives: {negs}', lines)
        self.assertEqual(lines[-1] if notify.FOR_HUMAN not in msg['text'] else None, f'https://your-dashboard.example.com/#/{ASIN}')
        self.assertTrue(any(line.startswith('- Held: ') and 'close calls' in line for line in lines), lines)
        for word in ('index', 'SQP', 'converts', 'opportunity'):   # no research text
            self.assertNotIn(word, msg['text'])

    def test_for_human_routes_each_item_to_the_person_who_decides(self):
        # a price change (Kim), a listing item (Lee), low stock (the book owner), a borderline call (the book owner).
        # No item is parked for money since 2026-10-22 (decision 99): a promotion past the investment guide goes out
        cfg = T.product(auto=dict(T.AUTO, invest_guide_month=1), price_change={'from': 7.99, 'to': 8.99, 'why': 'test'},
                        registry=dict(bid_owner='AI', stage='ai', owner_since='2026-09-01', book_owner='Sam'))
        plan = self.plan(cfg=cfg)
        plan['summary'][0]['stock_reorder'] = dict(cover_days=9)
        plan['human_review'] = [dict(id='listing-conversion-gap', kind='listing', status='open', title='Improve the main image',
                                     action='research', ai_review=dict(phase='human_ready', assessment=dict(
                                         recommendation='Swap the hero image for the 50-design spread')))]
        borderline = dict(type='Bid change', row_id='Bid change:X', lane='human', keyword='x', current=0.5, new=0.9,
                          lane_reason='not enough proof to bid above breakeven; opportunity 450 (conversion index x monthly '
                                      'searches), so a person decides')
        plan['changes'].append(borderline)
        msg = notify.message(plan, cfg, SHARED, ASIN, {}, T.TODAY)
        text = msg['text']
        head, parked = text.split(f'*{notify.FOR_HUMAN}:*\n')
        lines = parked.split('\n')
        self.assertTrue(lines[0].startswith(f"- {tag('Kim')} "), lines)
        self.assertIn(f"- {tag('Kim')} price $7.99 -> $8.99: approve or decline on the dashboard", lines)
        self.assertFalse(any('$600' in line or 'level' in line for line in lines), lines)
        self.assertEqual(sum(1 for line in lines if line.startswith(f"- {tag('Kim')} ")), 1, lines)
        self.assertIn(f"- {tag('Lee')} Improve the main image: Swap the hero image for the 50-design spread", lines)
        self.assertIn(f"- {tag('Sam')} inventory alert: 9 days of cover left. Auto changes continue; manage stock and any reorder manually",
                      lines)
        self.assertIn(f"- {tag('Sam')} 1 x borderline call (short of the evidence ladder, big opportunity): approve or "
                      'decline on the dashboard', lines)
        order = [line.split(' ')[1] for line in lines]
        self.assertEqual(order, sorted(order, key=lambda t: {tag('Kim'): 0, tag('Lee'): 1}.get(t, 2)))
        self.assertEqual(set(msg['mentions']), {tag('Sam'), tag('Kim'), tag('Lee')})

    def test_verified_human_rows_do_not_request_approval_again(self):
        rows = [dict(type='Bid change', row_id=x, lane='human', keyword=x,
                     current=1.0, new=0.5, lane_reason='explicitly approved taper')
                for x in ('done', 'waiting')]
        plan = dict(summary=[dict(asin=ASIN, shadow=False, review_date=T.TODAY,
                                 stock_reorder=dict(cover_days=9))], changes=rows)
        applied = {'done': dict(date=T.TODAY, folder='review')}
        msg = notify.message(plan, T.product(registry=dict(book_owner='Sam')), SHARED, ASIN, applied, T.TODAY)
        self.assertIn('Bids: 1 cut, 0 raised', msg['text'])
        self.assertIn('1 x other call: approve or decline', msg['text'])
        self.assertNotIn('2 x other call', msg['text'])
        applied['waiting'] = dict(date=T.TODAY, folder='review')
        msg = notify.message(plan, T.product(registry=dict(book_owner='Sam')), SHARED, ASIN, applied, T.TODAY)
        self.assertNotIn('approve or decline', msg['text'])
        self.assertIn('inventory alert: 9 days of cover left. Auto changes continue', msg['text'])

    def test_the_recap_says_when_the_planned_invest_is_above_the_guide(self):
        # Kim, 2026-10-22, decision 99: $2,000 a month a product is a guide, not a gate. One recap line says so when the
        # plan is above it, for a person to step in; nothing is parked for it
        plan = self.plan(cfg=T.product(auto=dict(T.AUTO, invest_guide_month=1)))
        s = plan['summary'][0]
        self.assertIs(s['above_invest_guide'], True)
        msg = notify.message(plan, T.product(), SHARED, ASIN, self.went_out(plan), T.TODAY)
        lines = msg['text'].split('\n')
        self.assertIn(f"- Planned invest {notify.money(s['planned_invest_month'])}/month (above the $1 guide)", lines)
        self.assertNotIn(notify.FOR_HUMAN, msg['text'])
        # inside the guide: no line
        plan = self.plan()
        self.assertIs(plan['summary'][0]['above_invest_guide'], False)
        msg = notify.message(plan, T.product(), SHARED, ASIN, self.went_out(plan), T.TODAY)
        self.assertNotIn('guide', msg['text'])
        self.assertEqual(notify.guide_line(dict(planned_invest_month=2400.5, invest_guide_month=2000, above_invest_guide=True)),
                         'planned invest $2,400.50/month (above the $2,000 guide)')
        self.assertIsNone(notify.guide_line(dict(planned_invest_month=2400.5, invest_guide_month=2000)))

    def test_the_recap_names_promotions_past_the_band_or_the_loss_line(self):
        # Kim, 2026-10-22, decision 100: the product's investment band and the $60 loss line for one search are
        # information, not gates. A promotion past them goes out; the recap says so for a person to step in
        plan = self.plan(cfg=T.product(auto=dict(T.AUTO, max_loss_month=4.5)))
        s = plan['summary'][0]
        self.assertEqual(s['over_invest_band'], ['blank cards'])
        msg = notify.message(plan, T.product(), SHARED, ASIN, self.went_out(plan), T.TODAY)
        lines = msg['text'].split('\n')
        self.assertIn(f"- Past the product's {notify.money(s['invest_band_month'])}/month invest band: blank cards", lines)
        self.assertNotIn(notify.FOR_HUMAN, msg['text'])
        self.assertEqual(notify.band_lines(dict(over_loss_line=[dict(search='kids cards', modelled_net_month=-112.5),
                                                                dict(search='business:office cards', modelled_net_month=None)],
                                                loss_line_month=60)),
                         ['modelled to lose over the $60/month line for one search: kids cards ($112.50/month), '
                          'B2B office cards'])
        self.assertEqual(notify.band_lines(dict(over_invest_band=[], over_loss_line=[])), [])
        self.assertEqual(notify.band_lines({}), [])   # a plan made before decision 99

    def test_organic_lines_say_what_the_leak_check_did(self):   # decision 175
        org = dict(enabled=True, target_share=0.5, share=dict(share=0.38), non_rank_factor=1.0,
                   leak=dict(days=7, profit=-70, line=-10, tripped=True, acted=True, paused=['greeting cards']))
        self.assertEqual(notify.organic_lines(dict(organic=org)), [
            'leak check: the ordinary keywords lost $70 over the last 7 settled days: 1 keyword with 15+ clicks and no '
            'orders paused; rank bids, budgets and new Prove-first campaigns untouched'])
        empty = dict(org, leak=dict(org['leak'], acted=False, checked=True, paused=[]))
        self.assertIn('no keyword met the pause bar', ' '.join(notify.organic_lines(dict(organic=empty))))
        calm = dict(org, leak=dict(org['leak'], tripped=False, acted=False))
        self.assertEqual(notify.organic_lines(dict(organic=calm)), [])
        self.assertEqual(notify.organic_lines({}), [])   # a plan made before decision 143
        self.assertEqual(notify.organic_lines(dict(organic=dict(org, enabled=False))), [])

    def test_fallback_line_names_each_search_priced_without_amazon(self):   # decision 106
        fb = dict(tried={'amazon': 'rate limited'}, searches={'gold cards': dict(source='estimate', priced_on='x'),
                                                              'blank cards': dict(source='soldscope', priced_on='y')},
                  business_searches=['zebra cards'])
        self.assertEqual(notify.fallback_line(dict(bid_fallback=fb)),
                         "priced without Amazon's suggested bid: blank cards (SoldScope), gold cards (an estimate), "
                         'B2B zebra cards (the no-suggestion bid)')
        self.assertIsNone(notify.fallback_line(dict(bid_fallback=None)))
        self.assertIsNone(notify.fallback_line({}))
        plain = self.plan()
        self.assertNotIn('invest band', notify.message(plain, T.product(), SHARED, ASIN, self.went_out(plain), T.TODAY)['text'])

    def test_a_locked_row_is_held_not_parked(self):
        plan = self.plan(cfg=T.product(decisions=[dict(id='Bid change:5', what='decline', by='Lee', until='2026-11-16',
                                                        direction='down')]))
        self.assertEqual(T.one(plan, 'Bid change', keyword_id='5')['lane'], 'human')
        msg = notify.message(plan, T.product(), SHARED, ASIN, self.went_out(plan), T.TODAY)
        self.assertNotIn(notify.FOR_HUMAN, msg['text'])
        self.assertIn('1 (an earlier decision)', msg['text'])

    def test_an_auto_off_decision_opened_today_is_parked_for_the_owner(self):
        product = T.product(registry=dict(book_owner='Alex'), open_items=[dict(
            opened=T.TODAY, status='decision', short='Auto off: Read-back mismatch', text='x',
            workflow=dict(lane='human', action='Look at what tripped it; Kim turns Auto back on', kind='auto_off'))])
        plan = dict(summary=[dict(asin=ASIN, shadow=True, review_date=T.TODAY)], changes=[], human_review=[])
        msg = notify.message(plan, product, SHARED, ASIN, {}, T.TODAY)
        self.assertIn(f"- {tag('Alex')} Auto off: Read-back mismatch: Look at what tripped it; Kim turns Auto back on",
                      msg['text'])
        self.assertIn('Auto is off for this product', msg['text'])

    def test_the_book_owner_lookup(self):
        tiers = os.path.join(self.tmp, 'tiers.csv')
        with open(tiers, 'w', encoding='utf-8', newline='') as fh:
            fh.write('asin,sku,product,owner\nB0TEST0001,s,p,Alex\nB0TEST0002,s,p,Sam\n')
        books = notify.read_tiers(tiers)
        self.assertEqual(books, {'B0TEST0001': 'Alex', 'B0TEST0002': 'Sam'})
        shared = dict(SHARED, notify=dict(SHARED['notify'], book_owners={'B0TEST0002': 'Lee'}))
        self.assertEqual(notify.book_owner('B0TEST0001', {'registry': {'book_owner': 'Sam'}}, shared, books), 'Sam')
        self.assertEqual(notify.book_owner('B0TEST0002', {}, shared, books), 'Lee')   # the config wins over the list
        self.assertEqual(notify.book_owner('B0TEST0001', {}, shared, books), 'Alex')
        self.assertEqual(notify.book_owner('B0NOBODY01', {}, shared, books), 'Lee')   # the fallback
        self.assertEqual(notify.read_tiers(os.path.join(self.tmp, 'missing.csv')), {})
        # the repo's own book list names the AI products' owners (when the skill runs inside the repo)
        path = os.path.join(notify.REPO, CONFIG['notify']['tiers_csv'])
        if os.path.exists(path):
            repo = notify.read_tiers(path)
            self.assertEqual((repo.get('B0SAMP0001'), repo.get('B0SAMP0013')), ('Alex', 'Sam'))

    def test_the_cli_prints_the_message(self):
        data = os.path.join(self.tmp, 'data')
        T.write(os.path.join(data, 'asins', f'{ASIN}.json') if os.makedirs(os.path.join(data, 'asins')) is None else None,
                T.product(registry=dict(book_owner='Sam')))
        plan = self.plan()
        T.write(os.path.join(self.run_dir, 'plan.json'), plan)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            notify.main(['--asin', ASIN, '--run', self.run_dir, '--data', data, '--date', T.TODAY])
        msg = json.loads(out.getvalue())
        self.assertEqual((msg['channel_id'], msg['owner']), ('C0EXAMPLE01', 'Sam'))
        self.assertTrue(msg['text'].startswith(f"{tag('Sam')} PPC AI run: Test cards ({ASIN})"))

    # ---- the For Growth line (decision 124, 2026-10-25) ----------------------------------------------------------------
    def growth_run(self, trigger='first_pass'):
        item = {'id': 'for-growth', 'kind': 'growth', 'workflow': {'why': '2 proven SKC keywords the copy does not '
                                                                         'carry, for 2 runs: blank cards, thank you cards'},
                'growth': {'product': 'Test cards', 'pass': 'first listing optimization',
                           'weave_in': [{'term': 'thank you cards'}, {'term': 'blank cards'}]}}
        return {'asin': ASIN, 'trigger': trigger, 'trigger_reason': 'x', 'item': item if trigger else None}

    def test_the_config_names_the_marketing_traffic_channel(self):
        n = CONFIG['notify']
        self.assertEqual((n['growth_channel'], n['growth_channel_id']), ('#3-marketing-traffic', 'C0EXAMPLE02'))
        self.assertEqual((n['growth_monday_board'], n['growth_monday_status']), (9000000011, 'Optimise Listing'))
        self.assertEqual((n['growth_monday_group'], n['growth_monday_group_title'], n['growth_monday_if_missing']),
                         ('new_group3973', '[GROWTH TEAM] - For Listing Optimisation', 'create'))

    def test_a_raised_for_growth_item_gets_its_own_message_in_marketing_traffic(self):
        msg = notify.growth_message(self.growth_run(), T.product(), SHARED, ASIN)
        self.assertEqual((msg['channel'], msg['channel_id']), ('#3-marketing-traffic', 'C0EXAMPLE02'))
        lines = msg['text'].split('\n')
        self.assertEqual(lines[0], f'Ready for listing optimisation: Test cards ({ASIN}), first listing optimization')
        self.assertIn('2 proven SKC keywords', lines[1])
        self.assertIn('Seed keywords: thank you cards; blank cards', msg['text'])
        self.assertTrue(lines[-1].endswith(f'https://your-dashboard.example.com/#/{ASIN}'))
        self.assertEqual(msg['monday'], {'board': 9000000011, 'asin': ASIN, 'group': 'new_group3973',
                                         'group_title': '[GROWTH TEAM] - For Listing Optimisation',
                                         'status': 'Optimise Listing', 'if_missing': 'create',
                                         'item_name': f'Test cards ({ASIN})'})

    def test_no_for_growth_item_no_growth_message(self):
        self.assertIsNone(notify.growth_message(self.growth_run(trigger=None), T.product(), SHARED, ASIN))
        self.assertIsNone(notify.growth_message(None, T.product(), SHARED, ASIN))

    def test_the_cli_carries_the_growth_message(self):
        data = os.path.join(self.tmp, 'data')
        os.makedirs(os.path.join(data, 'asins'))
        T.write(os.path.join(data, 'asins', f'{ASIN}.json'), T.product(registry=dict(book_owner='Sam')))
        plan = self.plan()
        T.write(os.path.join(self.run_dir, 'plan.json'), plan)
        for growth_doc, want in ((None, None), (self.growth_run(), 'C0EXAMPLE02')):
            if growth_doc is not None:
                T.write(os.path.join(self.run_dir, 'growth.json'), growth_doc)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                notify.main(['--asin', ASIN, '--run', self.run_dir, '--data', data, '--date', T.TODAY])
            msg = json.loads(out.getvalue())
            self.assertEqual(msg['channel_id'], 'C0EXAMPLE01')
            self.assertEqual((msg['growth'] or {}).get('channel_id'), want)


if __name__ == '__main__':
    unittest.main()
