"""Weekly cycles, end to end (cross-task fix B8, M7, and fix C's runbook): every seam the per-module tests cover alone,
run in order.

  week 1: plan.py (shadow) -> publish (the merge into the product file) -> the team decides on the dashboard ->
          approvals -> applied -> log_invest -> publish --state applied
  week 2: dashboard.py reviews (saved into week 2's folder, that day) -> plan.py -> publish

The second cycle (test_last_week_is_settled_before_this_week_is_planned) follows fix C's runbook over three weeks:
settle last week first, then pull the data, save the decisions, plan, publish, apply and record (C1-C8).

Only the HTTP call is replaced, by an in-memory dashboard server; nothing here can reach the network or Amazon.
"""
import argparse
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

import dashboard
import log_invest
import plan as planner
import test_plan_lanes as T

ASIN = T.ASIN
W1, W2, W3 = '2026-10-19', '2026-10-26', '2026-11-02'
AT = '2026-10-19T02:00:00.000Z'  # 10:00 in Singapore on 19 October
BUNDLE = ['New exact campaign:::blank cards', 'Pause keyword:2', 'Negative exact:101:201:blank cards',
          'Negative exact:102:202:blank cards']
QUERIES = T.QUERIES + [T.query('zebra cards', 600, 240, 24, 20, 5)]  # a second promotion, which nobody decides
UNSEEN = 'Pause target:301'  # the row approved without `seen` in the three-week cycle
SUGGESTED = dict(T.SUGGESTED, **{'zebra cards': [0.40, 0.50, 0.70]})


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)


class FakeDashboard:
    """The dashboard server's routes this cycle uses, kept in memory: PUT/GET /api/products/<ASIN>, GET
    /api/reviews/<ASIN> and GET /api/items/<ASIN> (Growth's status clicks, which `reviews --save` saves beside the
    decisions; none in these cycles). decide() is a person's POST /api/reviews/<ASIN>/<item>: it is refused, as the server
    refuses it, when the published page doesn't hold the item. Any other call fails the test."""

    def __init__(self):
        self.pages, self.reviews, self.items, self.calls, self.version = {}, {}, {}, [], 0

    def __call__(self, method, path, body=None, base_version=None):
        self.calls.append((method, path))
        parts = path.strip('/').split('/')
        if method == 'PUT' and parts[:2] == ['api', 'products'] and len(parts) == 3:
            doc = json.loads(body)
            assert doc['asin'] == parts[2]
            self.version += 1
            self.pages[parts[2]] = doc
            return dict(ok=True, asin=parts[2], version=f'v{self.version}', published_at=f'{W1}T03:00:00Z',
                        published_by=doc.get('published_by'))
        if method == 'GET' and parts[:2] == ['api', 'reviews'] and len(parts) == 3:
            return copy.deepcopy(self.reviews.get(parts[2], []))
        if method == 'GET' and parts[:2] == ['api', 'items'] and len(parts) == 3:
            return copy.deepcopy(self.items.get(parts[2], []))
        if method == 'GET' and parts[:2] == ['api', 'products'] and len(parts) == 3:
            return copy.deepcopy(self.pages[parts[2]])
        raise AssertionError(f'the cycle made a call it should not: {method} {path}')

    def row(self, asin, item_id, row_id):
        item = next(i for i in self.pages[asin]['human_review'] if i['id'] == item_id)
        return next(r for r in item['rows'] if r['row_id'] == row_id)

    def decide(self, asin, item_id, row_id, decision, by='Lee', at=AT, seen=True):
        """What the dashboard's buttons send (6b): the decision, signed, with the numbers the person saw on the row (E2:
        its bids, and the budgets, boosts and monthly spend it carries; the server stores a missing one as null).
        seen=False is an older client, which sends no numbers."""
        row = self.row(asin, item_id, row_id)  # a KeyError/StopIteration here is the server's 404
        entry = dict(row_id=row_id, item_id=item_id, decision=decision, by=by, at=at, note=None)
        if seen:
            entry['seen'] = {k: row.get(k) for k in dashboard.SEEN_KEYS}
        self.reviews.setdefault(asin, []).append(entry)


class WeeklyCycleTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(self.tmp, 'data')
        self.product_file = os.path.join(self.data, 'asins', f'{ASIN}.json')
        self.shared = T.shared_config()
        self.server = FakeDashboard()
        patches = [unittest.mock.patch.object(dashboard, 'call', side_effect=self.server),
                   unittest.mock.patch.object(dashboard, 'config', return_value=self.shared),
                   unittest.mock.patch.object(dashboard.urllib.request, 'urlopen', side_effect=AssertionError('network'))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # --- the steps, each as its command line runs it ------------------------------------------------------------------
    def run_dir(self, week):
        return os.path.join(self.tmp, 'runs', week)

    def plan(self, week, extra=(), **run):
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir(week), '--data', self.data, '--today', week, *extra]
        monday = T.datetime.fromisoformat(f'{week}T15:00:00+00:00')  # 08:00 in Los Angeles: each week's apply_after is its own day
        mid = contextlib.nullcontext() if run.pop('mid', False) else T.without_mid()
        T.make_run(self.run_dir(week), **dict(dict(queries=QUERIES, suggested=SUGGESTED), **run))
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.planned_at(monday), mid:
            planner.main()
        return read_json(os.path.join(self.run_dir(week), 'plan.json'))

    def dashboard(self, *argv):
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', ['dashboard.py', *argv]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            dashboard.main()
        return json.loads(out.getvalue())

    def publish(self, week, state='proposed', date=None):
        return self.dashboard('publish', '--asin', ASIN, '--run', self.run_dir(week), '--state', state,
                              '--date', date or week, '--by', 'Kim', '--data', self.data)

    def refused(self, *argv):
        """A dashboard.py command that must refuse: its message."""
        with self.assertRaises(SystemExit) as cm:
            self.dashboard(*argv)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    def plan_refused(self, week, **run):
        with self.assertRaises(SystemExit) as cm:
            self.plan(week, **run)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    def approvals_args(self, week, now, *extra):
        return ('approvals', '--asin', ASIN, '--run', self.run_dir(week), '--data', self.data, '--now', now, *extra)

    def approvals(self, week, now, *extra):
        return self.dashboard(*self.approvals_args(week, now, *extra))

    def applied_args(self, week, folder, date, *extra):
        if '--dry-run' in extra and '--now' not in extra:
            extra = (*extra, '--now', f'{date}T15:00:00Z')  # E4: the check runs at 08:00 in Los Angeles on that day
        return ('applied', '--asin', ASIN, '--run', self.run_dir(week), '--data', self.data, '--folder', folder, '--date',
                date, *extra)

    def applied(self, week, folder, date, *extra):
        return self.dashboard(*self.applied_args(week, folder, date, *extra))

    def payload_rows(self, week, folder):
        """The row_ids behind payloads/<folder>/ of a week, from its rows.json ([] when it has none)."""
        path = os.path.join(self.run_dir(week), 'payloads', folder, 'rows.json')
        return [rid for ids in read_json(path).values() for rid in ids] if os.path.exists(path) else []

    def save_reviews(self, week, now=None):
        """`reviews --save` into the week's folder, on that week's day (09:00 in Singapore) unless `now` says otherwise."""
        clock = dashboard.dt.datetime.fromisoformat((now or f'{week}T01:00:00') + '+00:00')
        with unittest.mock.patch.object(dashboard, 'utc_now', return_value=clock):
            return self.dashboard('reviews', '--asin', ASIN, '--save', os.path.join(self.run_dir(week), 'reviews.json'))

    def log_invest(self, week, date):
        argv = ['log_invest.py', '--asin', ASIN, '--run', self.run_dir(week), '--data', self.data, '--date', date]
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(out):
            log_invest.main()
        return json.loads(out.getvalue())

    def product(self):
        return read_json(self.product_file)

    def item(self, plan):
        return next(i for i in plan['human_review'] if i['kind'] == 'bid')

    # --- the cycle --------------------------------------------------------------------------------------------------
    def test_one_week_of_decisions_carries_into_the_next_plan(self):
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest')}))
        item1 = f'bids-{W1}'

        # week 1: plan (shadow: every row is on the item) and publish
        plan1 = self.plan(W1, data_through='2026-10-12')
        self.assertEqual(self.item(plan1)['id'], item1)
        self.assertEqual(self.publish(W1)['version'], 'v1')
        self.assertEqual([i['status'] for i in self.product()['human_review'] if i['id'] == item1], ['open'])

        # the team decides on the dashboard: the blank cards promotion and the raise on keyword 4 (capped) are approved,
        # the cut on keyword 3 refused, the held raise on keyword 6 agreed with; nobody decides zebra cards
        for rid in BUNDLE + ['Bid change:4', 'Bid change:6']:
            self.server.decide(ASIN, item1, rid, 'approve')
        self.server.decide(ASIN, item1, 'Bid change:3', 'decline')

        # approvals: the approved rows to approved/, the decline to a lock; the held row is only agreed with
        out = self.approvals(W1, now='2026-10-19T15:00:00Z')
        self.assertEqual((out['mode'], out['skipped'], out['agreed_held']), ('normal', [], ['Bid change:6']))
        approved = os.path.join(self.run_dir(W1), 'payloads', 'approved')
        self.assertEqual(read_json(os.path.join(approved, '4_bids_01.json')),
                         [dict(type='sp_keywords', keywordId='4', bid=0.37)])  # at the auto lane's cap
        self.assertEqual(sorted(read_json(os.path.join(approved, 'rows.json'))),
                         ['1_new_campaigns.json', '1b_new_skc_specs.json', '3_pauses.json', '4_bids_01.json',
                          '6_negatives_01.json'])
        self.assertEqual({d['id']: d['what'] for d in self.product()['decisions']}, {'Bid change:3': 'decline'})

        # the approved folder goes out (a person applies it through MAP), and is recorded: now the approvals lock
        out = self.applied(W1, 'approved', date='2026-10-20')
        self.assertEqual(out['recorded'], 5)
        locks = {d['id']: d for d in self.product()['decisions']}
        self.assertEqual({k: v['what'] for k, v in locks.items()}, {'Bid change:3': 'decline', 'Bid change:4': 'approve',
                                                                    **{rid: 'approve' for rid in BUNDLE}})
        self.assertEqual((locks['Bid change:4']['direction'], locks['Bid change:4']['until']), ('up', '2026-11-17'))

        # the stop-loss clock starts only for the promotion that went out
        self.log_invest(W1, '2026-10-20')
        log = self.product()['invest_log']
        self.assertEqual(set(log), {'blank cards', 'thank you cards'})
        self.assertEqual(log['blank cards']['since'], '2026-10-20')
        self.assertEqual(log['thank you cards']['since'], '2026-10-05')  # live all along: its clock runs on
        self.assertNotIn('zebra cards', log)  # never decided, never applied

        # the applied page says what went out and why the rest didn't
        self.save_reviews(W1)
        self.publish(W1, state='applied', date='2026-10-20')
        page = self.server.pages[ASIN]
        status = {x['row_id']: row.get('status') for x, row in zip(plan1['changes'], page['run']['changes'])}
        went = BUNDLE + ['Bid change:4']
        self.assertEqual({rid: status[rid] for rid in went}, {rid: 'applied' for rid in went})
        self.assertEqual((status['Bid change:3'], status['Bid change:6'], status['New exact campaign:::zebra cards']),
                         ('declined', 'held', 'waiting for a person'))

        # week 2: the decisions are saved into its folder that day (C6), then it is planned. Keyword 4 has 40 clicks at
        # $0.37 and no order, so the planner wants it cut; keyword 3 still trails
        saved = self.save_reviews(W2)
        self.assertEqual((saved['decisions'], saved['declines']), (7, 1))
        keywords = ([k for k in T.KEYWORDS if k['KeywordId'] != '4']
                    + [T.keyword('4', 'cards', 'broad', T.BROAD, 0.37, 40, 0, 15)])
        plan2 = self.plan(W2, data_through='2026-10-19', keywords=keywords)
        rows2 = {r['row_id']: r for r in self.item(plan2)['rows']}
        by_id = {c['row_id']: c for c in plan2['changes']}
        refused = by_id['Bid change:3']
        self.assertEqual((refused['lane'], refused['lane_unlocked'], refused['decision'], refused['decided_by']),
                         ('human', 'auto', 'decline', 'Lee'))
        self.assertIn('Bid change:3', rows2)  # visible on week 2's item, with who refused it
        self.assertEqual(rows2['Bid change:3']['lock_by'], 'Lee')
        cut = by_id['Bid change:4']
        self.assertLess(cut['new'], cut['current'])
        self.assertEqual((cut['lane'], cut['lane_unlocked'], cut['decision']), ('human', 'auto', 'approve'))  # not automatic
        self.assertIn('Bid change:4', rows2)
        held = read_json(os.path.join(self.run_dir(W2), 'payloads', 'held', 'rows.json'))
        self.assertIn('Bid change:4', held['4_bids_01.json'])  # nothing can send the cut without a person
        review = read_json(os.path.join(self.run_dir(W2), 'payloads', 'review', 'rows.json'))
        self.assertNotIn('Bid change:4', [rid for ids in review.values() for rid in ids])

        # publishing week 2 supersedes week 1's item and keeps only its summary
        self.publish(W2)
        old = next(i for i in self.product()['human_review'] if i['id'] == item1)
        self.assertEqual((old['status'], old['resolution']), ('dismissed', f'Superseded by bids-{W2}'))
        self.assertNotIn('rows', old)
        self.assertEqual(old['rows_count'], len(self.item(plan1)['rows']))
        # and week 1's approvals can no longer go out: only its declines count
        out = self.approvals(W1, now='2026-10-26T15:00:00Z')
        self.assertEqual((out['mode'], out['approved'], out['declined']), ('decisions_only', 0, 1))

        # nothing but reads of the dashboard and page publishes: no other call was made
        self.assertEqual({m for m, _ in self.server.calls}, {'GET', 'PUT'})
        self.assertTrue(all(p == f'/api/products/{ASIN}' for m, p in self.server.calls if m == 'PUT'))


    # --- fix C: three weeks in the runbook's order -------------------------------------------------------------------
    def test_last_week_is_settled_before_this_week_is_planned(self):
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest')}))
        item1, item2, item3 = f'bids-{W1}', f'bids-{W2}', f'bids-{W3}'
        no_seen = "can't confirm what was approved (the decision doesn't say what the person saw)"

        # ---- week 1 (shadow): plan and publish; the team decides
        plan1 = self.plan(W1)
        self.publish(W1)
        for rid in BUNDLE + ['Bid change:4']:
            self.server.decide(ASIN, item1, rid, 'approve')
        self.server.decide(ASIN, item1, 'Bid change:3', 'decline')
        # the approval without `seen`: on the product-target pause, not on 'Bid change:1' (thank you cards' invest re-price),
        # which the merge of 2dcb21c no longer plans: thank you cards is in the invest log, so the visibility review keeps
        # it at its live bid for its own review (plan.py deferred_rank_terms)
        self.server.decide(ASIN, item1, UNSEEN, 'approve', seen=False)  # today's client: no `seen`

        # C1: the approval without `seen` never goes out
        out = self.approvals(W1, '2026-10-19T15:00:00Z')
        self.assertEqual(out['skipped'], [dict(row_id=UNSEEN, reason=no_seen)])
        handed = self.payload_rows(W1, 'approved')
        self.assertEqual(set(handed), set(BUNDLE + ['Bid change:4']))

        # C2: approved/ goes out through MAP; before `applied` runs, a teammate approves one more row. approvals refuses
        # to replace what went out unrecorded
        self.server.decide(ASIN, item1, 'Bid change:5', 'approve', at='2026-10-19T05:00:00.000Z')
        message = self.refused(*self.approvals_args(W1, '2026-10-19T16:00:00Z'))
        self.assertIn('payloads/approved/ still holds 5 rows not recorded as applied', message)
        self.assertEqual(self.payload_rows(W1, 'approved'), handed)

        # C4: the run is being decided row by row, so its review/ can't go out (the check before a whole-run apply)
        message = self.refused(*self.applied_args(W1, 'review', '2026-10-20', '--dry-run'))
        self.assertIn('this run is being decided row by row; apply approved/ instead', message)

        # record what went out; approvals then hands out the one new approval
        self.assertEqual(self.applied(W1, 'approved', '2026-10-20')['recorded'], 5)
        lock = {d['id']: d for d in self.product()['decisions']}[BUNDLE[0]]
        self.assertEqual((lock['kind'], lock['search'], lock['created_on'], lock['by']), ('create', 'blank cards',
                                                                                          '2026-10-20', 'Lee'))
        out = self.approvals(W1, '2026-10-20T15:00:00Z')
        self.assertEqual(self.payload_rows(W1, 'approved'), ['Bid change:5'])
        self.assertEqual(self.applied(W1, 'approved', '2026-10-21')['recorded'], 1)

        # the stop-loss clock of the promotion starts the day it went out (C7, N8), not log_invest's --date
        changes = self.log_invest(W1, '2026-10-22')['changes']
        self.assertIn('blank cards: started Invest on 2026-10-20', ' '.join(changes))
        log = self.product()['invest_log']
        self.assertEqual({t: e['since'] for t, e in log.items()}, {'thank you cards': '2026-10-05', 'blank cards': '2026-10-20'})
        self.save_reviews(W1, now=f'{W1}T09:00:00')
        self.publish(W1, state='applied', date='2026-10-21')
        status = {x['row_id']: r.get('status') for x, r in zip(plan1['changes'], self.server.pages[ASIN]['run']['changes'])}
        self.assertEqual({rid: status[rid] for rid in BUNDLE + ['Bid change:4', 'Bid change:5']},
                         {rid: 'applied' for rid in BUNDLE + ['Bid change:4', 'Bid change:5']})
        self.assertEqual((status['Bid change:3'], status[UNSEEN]), ('declined', 'waiting for a person'))

        # ---- week 2: settle last week first. Monday morning in Singapore is still Sunday evening in Los Angeles. Until
        # 2026-10-24 the US write window was shut then and approvals refused (R1); since Kim's call that day (execute
        # whenever the audit runs, weekends included; dashboard.write_window) it runs at once.
        # Nothing new was approved over the weekend: approved/ (recorded) is cleared and nothing is handed out, so `applied`
        # has nothing to record and says so (C7)
        out = self.approvals(W1, '2026-10-26T01:00:00Z')
        self.assertEqual((out['approved'], out['discarded']), (0, []))
        out = self.applied(W1, 'approved', W2)
        self.assertEqual((out['recorded'], out['note'][:18]), (0, 'Nothing to record:'))

        # C5: the product file holds a bids item, so the plan needs the saved decisions; C6: an old save is refused
        self.assertIn('Save the dashboard decisions first', self.plan_refused(W2))
        self.save_reviews(W2, now=f'{W1}T09:00:00')
        self.assertIn('save the dashboard decisions again', self.plan_refused(W2))
        self.save_reviews(W2)

        # this week's data was pulled before Amazon's reports show the blank cards campaign. Before the merge of 2dcb21c
        # the planner proposed it again and the create lock held it (N1, C3; CreationTest covers that path). Since the
        # merge, blank cards is in the invest log (log_invest above), so the visibility review keeps it as an existing
        # rank investment and nothing of its bundle is proposed at all: no row of it can go out again
        # fresh SQP for this week (since 2026-10-22 stale data holds every row in held/, so review/ would be empty)
        plan2 = self.plan(W2, data_through='2026-10-19')
        self.assertEqual([x['row_id'] for x in plan2['changes'] if x['row_id'] in BUNDLE], [])
        self.assertIn('blank cards', plan2['visibility_review']['retained_rank_searches'])
        for folder in ('review', 'held'):
            self.assertNotIn(BUNDLE[0], self.payload_rows(W2, folder))
        refused = next(x for x in plan2['changes'] if x['row_id'] == 'Bid change:3')
        self.assertEqual((refused['lane'], refused['decided_by']), ('human', 'Lee'))
        self.publish(W2)
        # the team decides a row of this week's item (it refuses the product-target raise): nothing goes out
        self.server.decide(ASIN, item2, 'Target bid change:302', 'decline', at='2026-10-26T03:00:00.000Z')
        out = self.approvals(W2, '2026-10-26T15:00:00Z')
        self.assertEqual((out['approved'], out['declined'], out['files']), (0, 1, {}))
        # and its review/ can't go out either: the run is being decided row by row (C4)
        self.assertIn('decided row by row', self.refused(*self.applied_args(W2, 'review', W2, '--dry-run')))
        # C8: week 1 went out, so its folder is never planned again
        self.assertIn('this run already went out (partly or whole); plan in a new run folder', self.plan_refused(W1))

        # ---- week 3: settle week 2 (nothing went out), then plan; Kim says yes to the whole run (the review/ route)
        self.assertEqual(self.approvals(W2, '2026-11-02T15:00:00Z')['approved'], 0)
        self.assertEqual(self.applied(W2, 'approved', W3)['recorded'], 0)
        self.save_reviews(W3)
        plan3 = self.plan(W3, data_through='2026-10-26')
        self.assertIn('Bid change:5', self.payload_rows(W3, 'review'))
        self.assertNotIn(BUNDLE[0], self.payload_rows(W3, 'review'))  # still created: held
        self.assertTrue(plan3)
        # after the plan, Lee refuses the cut on keyword 5 on last week's item: the whole-run yes must not send it
        self.server.decide(ASIN, item2, 'Bid change:5', 'decline', at='2026-11-02T02:00:00.000Z')
        message = self.refused(*self.applied_args(W3, 'review', W3, '--dry-run'))
        self.assertIn('declined on the dashboard after the plan: Bid change:5', message)
        # save the decisions and plan again (nothing of week 3 went out, so its folder may be planned again)
        self.save_reviews(W3, now=f'{W3}T03:00:00')
        self.plan(W3, data_through='2026-10-26')
        self.assertNotIn('Bid change:5', self.payload_rows(W3, 'review'))
        self.assertIn('Bid change:5', self.payload_rows(W3, 'held'))
        self.publish(W3)
        self.assertEqual(self.applied(W3, 'review', W3, '--dry-run')['dry_run'], True)  # the check passes
        out = self.applied(W3, 'review', '2026-11-03')  # review/ went out through MAP, and is recorded
        self.assertTrue(out['recorded'] > 0)
        zebra = {d['id']: d for d in self.product()['decisions']}['New exact campaign:::zebra cards']
        self.assertEqual((zebra['kind'], zebra['created_on'], 'by' in zebra), ('create', '2026-11-03', False))
        # C4: a row approved on week 3's item afterwards goes nowhere: the run went out whole
        self.server.decide(ASIN, item3, UNSEEN, 'approve', at='2026-11-03T02:00:00.000Z')
        self.assertIn('this run was applied whole on 2026-11-03', self.refused(*self.approvals_args(W3, '2026-11-03T15:00:00Z')))

        # nothing but reads of the dashboard and page publishes: no other call was made
        self.assertEqual({m for m, _ in self.server.calls}, {'GET', 'PUT'})
        self.assertTrue(all(p == f'/api/products/{ASIN}' for m, p in self.server.calls if m == 'PUT'))

    # --- fix D: the apply guards, in the order an operator meets them ----------------------------------------------------
    def test_a_stale_approved_folder_cannot_create_a_search_twice(self):
        """R2 (the re-review's q6): approvals ran inside the window, but the MAP apply was put off and `applied` never ran. The
        week carried on: week 2 was planned, Kim said yes to the whole run, and its review/ created 'blank cards'. When the
        old approved/ is applied after that, the check before the apply (and the record) refuse it, as they do for the other
        folders, instead of recording a second creation."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest')}))
        item1 = f'bids-{W1}'
        self.plan(W1)
        self.publish(W1)
        for rid in BUNDLE:
            self.server.decide(ASIN, item1, rid, 'approve')
        self.assertGreater(self.approvals(W1, '2026-10-19T15:00:00Z')['approved'], 0)  # inside the window; not applied yet
        handed = self.payload_rows(W1, 'approved')
        self.assertIn(BUNDLE[0], handed)

        # week 2 goes ahead without settling week 1 (nothing recorded, so no create lock): its review/ holds the creation
        self.save_reviews(W2)
        self.plan(W2, data_through='2026-10-19')  # fresh SQP: stale data would hold every row (2026-10-22)
        self.publish(W2)
        self.assertIn(BUNDLE[0], self.payload_rows(W2, 'review'))
        self.assertEqual(self.applied(W2, 'review', W2, '--dry-run')['dry_run'], True)  # the check passes: nothing made it yet
        self.assertGreater(self.applied(W2, 'review', '2026-10-27')['recorded'], 0)  # review/ went out, and was recorded

        # now the old approved/ is applied: it would make 'blank cards' a second time
        for extra in (('--dry-run',), ()):
            message = self.refused(*self.applied_args(W1, 'approved', '2026-10-27', *extra))
            self.assertIn(f'these rows of payloads/approved/ create a search already created: {BUNDLE[0]} (on 2026-10-27)',
                          message)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(W1), 'payloads', 'applied_rows.json')))
        self.assertEqual(self.payload_rows(W1, 'approved'), handed)  # nothing changed

    def test_a_declined_raise_replanned_as_a_cut_goes_out_in_the_whole_run_yes(self):
        """N-new-3 (the re-review's P3), in the runbook's own order: a raise on keyword 4 is declined, step 2 settles it (a
        lock that remembers it was a raise), and week 2 plans a cut on it, which is a new call. The check before the
        whole-run yes lets the cut through; a decline made after the plan still stops it."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
        item1, item2 = f'bids-{W1}', f'bids-{W2}'
        self.plan(W1)
        self.publish(W1)
        self.server.decide(ASIN, item1, 'Bid change:4', 'decline', at='2026-10-20T02:00:00.000Z')
        self.approvals(W1, '2026-10-26T15:00:00Z')  # step 2
        self.assertEqual({d['id']: (d['what'], d['direction']) for d in self.product()['decisions']},
                         {'Bid change:4': ('decline', 'up')})
        self.save_reviews(W2)
        keywords = ([k for k in T.KEYWORDS if k['KeywordId'] != '4']
                    + [T.keyword('4', 'cards', 'broad', T.BROAD, 0.37, 40, 0, 15)])
        plan2 = self.plan(W2, data_through='2026-10-19', keywords=keywords)
        cut = next(c for c in plan2['changes'] if c['row_id'] == 'Bid change:4')
        self.assertLess(cut['new'], cut['current'])
        self.assertNotIn('locked_until', cut)  # a declined raise does not hold a cut
        self.assertIn('Bid change:4', self.payload_rows(W2, 'review'))
        self.assertEqual(self.applied(W2, 'review', W2, '--dry-run')['dry_run'], True)  # the check passes
        # a decline on last week's item, made after the plan (before week 2 is published and supersedes it)
        self.server.decide(ASIN, item1, 'Bid change:4', 'decline', at='2026-10-27T02:00:00.000Z')
        message = self.refused(*self.applied_args(W2, 'review', W2, '--dry-run'))
        self.assertIn('declined on the dashboard after the plan: Bid change:4', message)
        self.assertNotIn(item2, message)

    # --- fix E ---------------------------------------------------------------------------------------------------------
    def test_a_budget_approved_then_replanned_is_not_applied(self):
        """E2 (I2's probe P2): the plan raises the thank you cards SKC from $10 to $15/day (a budget override). The card
        shows the budget and sends it as seen; Lee approves. The override then becomes $40 and the same folder (nothing
        went out) is planned again. Her approval doesn't count for $40, and approved/ writes no budget."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False), budget_overrides={'thank you cards': 15}))
        plan1 = self.plan(W1)
        row = next(r for r in self.item(plan1)['rows'] if r['type'] == 'Budget and top of search')
        self.assertEqual({k: row[k] for k in ('budget_now', 'budget', 'tos_now', 'tos')},
                         dict(budget_now=10, budget=15, tos_now=50, tos=50))
        self.publish(W1)
        self.server.decide(ASIN, f'bids-{W1}', row['row_id'], 'approve')
        self.assertEqual(self.server.reviews[ASIN][-1]['seen']['budget'], 15)
        product = self.product()
        product['budget_overrides'] = {'thank you cards': 40}
        write_json(self.product_file, product)
        self.save_reviews(W1)
        self.plan(W1)
        out = self.approvals(W1, '2026-10-19T15:00:00Z')
        self.assertEqual(out['skipped'], [dict(row_id=row['row_id'], reason='re-planned since it was approved (saw budget '
                                                                            '$15.00/day, now budget $40.00/day)')])
        self.assertEqual(out['approved'], 0)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(W1), 'payloads', 'approved', '5_campaign_updates.json')))

    def test_a_decline_is_approved_again_only_at_the_decliners_level(self):
        """E3 (I3's probe): Lee declines the raise on keyword 4 (an owner-level row) on week 1's item, and step 2 writes
        her decline lock. Week 2 holds the row, and its item says Lee must approve it. Sam, an owner, approving it on
        week 2's item is recorded but held; Lee approving it goes out. When Kim declined, Lee's approval is held."""
        for decliner, approver, level, goes in (('Lee', 'Sam', 'Lee', False), ('Lee', 'Lee', 'Lee', True),
                                                ('Kim', 'Lee', 'Kim', False)):
            with self.subTest(decliner=decliner, approver=approver):
                shutil.rmtree(os.path.join(self.tmp, 'runs'), ignore_errors=True)
                self.server.pages.clear()
                self.server.reviews.clear()
                write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
                self.plan(W1)
                self.publish(W1)
                self.server.decide(ASIN, f'bids-{W1}', 'Bid change:4', 'decline', by=decliner, at='2026-10-20T02:00:00.000Z')
                self.approvals(W1, '2026-10-26T15:00:00Z')  # step 2: the decline lock
                self.assertEqual([(d['id'], d['what'], d['by']) for d in self.product()['decisions']],
                                 [('Bid change:4', 'decline', decliner)])
                self.save_reviews(W2)
                plan2 = self.plan(W2)
                row = next(c for c in plan2['changes'] if c['row_id'] == 'Bid change:4')
                self.assertEqual((row['lane'], row['decided_by'], row['decision']), ('human', decliner, 'decline'))
                item_row = next(r for r in self.item(plan2)['rows'] if r['row_id'] == 'Bid change:4')
                self.assertEqual((item_row['approval_required'], item_row['lock_by']), (level, decliner))
                self.publish(W2)
                self.server.decide(ASIN, f'bids-{W2}', 'Bid change:4', 'approve', by=approver, at='2026-10-27T02:00:00.000Z')
                out = self.approvals(W2, '2026-10-27T15:00:00Z')
                bids = os.path.join(self.run_dir(W2), 'payloads', 'approved', '4_bids_01.json')
                if goes:
                    self.assertEqual((out['skipped'], read_json(bids)), ([], [dict(type='sp_keywords', keywordId='4', bid=0.62)]))
                else:
                    self.assertEqual(out['skipped'], [dict(row_id='Bid change:4', reason=(
                        f"needs {level}'s approval: {decliner} declined it (approved by {approver})"))])
                    self.assertFalse(os.path.exists(bids))
                    # the decline still holds the row: nothing released, so next week's plan holds it again
                    self.assertEqual([(d['id'], d['what'], d['by']) for d in self.product()['decisions']],
                                     [('Bid change:4', 'decline', decliner)])

    def test_a_decline_on_the_same_item_is_overturned_only_at_the_decliners_level(self):
        """F (concern 2 of fix E): the same rule inside one week's item. The decliner says no to the raise on keyword 4 (an
        owner-level row) and someone says yes after, on the same item. Sam, an owner, can't overturn Lee's decline, and
        Lee can't overturn Kim's: the approval is held and the decline lock is written. Lee overturns her own, and
        Sam his own."""
        for decliner, approver, goes in (('Lee', 'Sam', False), ('Lee', 'Lee', True), ('Kim', 'Lee', False),
                                         ('Sam', 'Sam', True)):
            with self.subTest(decliner=decliner, approver=approver):
                shutil.rmtree(os.path.join(self.tmp, 'runs'), ignore_errors=True)
                self.server.pages.clear()
                self.server.reviews.clear()
                write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
                self.plan(W1)
                self.publish(W1)
                self.server.decide(ASIN, f'bids-{W1}', 'Bid change:4', 'decline', by=decliner, at='2026-10-20T02:00:00.000Z')
                self.server.decide(ASIN, f'bids-{W1}', 'Bid change:4', 'approve', by=approver, at='2026-10-20T03:00:00.000Z')
                out = self.approvals(W1, '2026-10-20T15:00:00Z')
                bids = os.path.join(self.run_dir(W1), 'payloads', 'approved', '4_bids_01.json')
                locks = [(d['id'], d['what'], d['by']) for d in self.product().get('decisions') or []]
                if goes:
                    self.assertEqual((out['skipped'], out['declined'], locks), ([], 0, []))
                    self.assertEqual([r['keywordId'] for r in read_json(bids)], ['4'])
                else:
                    self.assertEqual(out['skipped'], [dict(row_id='Bid change:4', reason=(
                        f"declined by {decliner}; needs {decliner}'s approval to change it (approved by {approver})"))])
                    self.assertFalse(os.path.exists(bids))
                    self.assertEqual((out['declined'], locks), (1, [('Bid change:4', 'decline', decliner)]))

    def test_a_folder_that_partly_went_out_is_recorded_and_never_creates_twice(self):
        """E5 (I5's probe): approved/ holds the blank cards promotion and the raise on keyword 4. Through MAP the new
        campaign is created and its duplicate pause goes out, then the bid reads back wrong, so the apply stops. The rows
        that went out are recorded with --rows; the rest did not go out, so it is discarded. approvals hands out only the
        bid again, never the campaign, and the check before the apply passes."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
        self.plan(W1)
        self.publish(W1)
        for rid in BUNDLE + ['Bid change:4']:
            self.server.decide(ASIN, f'bids-{W1}', rid, 'approve')
        self.assertGreater(self.approvals(W1, '2026-10-20T15:00:00Z')['approved'], 0)
        went = [BUNDLE[0], BUNDLE[1]]  # 1_new_campaigns (and its spec), then 3_pauses; 4_bids read back wrong
        rest = [rid for rid in dict.fromkeys(self.payload_rows(W1, 'approved')) if rid not in went]
        self.assertEqual(sorted(rest), sorted(BUNDLE[2:] + ['Bid change:4']))
        out = self.applied(W1, 'approved', '2026-10-20', '--rows', ','.join(went))
        self.assertEqual((out['recorded'], out['left_unrecorded']), (2, rest))
        # the rest is not recorded, so approvals refuses until it is recorded or discarded
        self.assertIn('payloads/approved/ still holds 3 rows not recorded as applied',
                      self.refused(*self.approvals_args(W1, '2026-10-21T15:00:00Z')))
        out = self.approvals(W1, '2026-10-21T15:00:00Z', '--discard-unapplied')
        self.assertEqual(out['discarded'], rest)
        self.assertEqual(self.payload_rows(W1, 'approved'), ['Bid change:4'])  # never the campaign again
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(W1), 'payloads', 'approved', '1_new_campaigns.json')))
        reasons = {s['row_id']: s['reason'] for s in out['skipped']}
        self.assertEqual(reasons[BUNDLE[0]], 'already applied on 2026-10-20')
        self.assertEqual({reasons[r] for r in BUNDLE[2:]}, {'part of a promotion already applied on 2026-10-20: blank cards'})
        self.assertEqual(self.applied(W1, 'approved', '2026-10-21', '--dry-run')['rows'], 1)  # the check passes
        creates = [d for d in self.product()['decisions'] if d.get('kind') == 'create']
        self.assertEqual([(d['search'], d['created_on']) for d in creates], [('blank cards', '2026-10-20')])

    def test_no_reviews_holds_what_a_normal_week_holds(self):
        """N-new-4: the dashboard is down on week 2's planning day. --no-reviews sends every change to a person, but the row
        the planner holds every other week (monitor: keyword 6) stays in held/, so a whole-run yes can't apply it."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
        self.plan(W1)
        self.publish(W1)
        plan2 = self.plan(W2, data_through='2026-10-19', extra=('--no-reviews', 'the dashboard is down'))
        self.assertEqual([c['row_id'] for c in plan2['changes'] if c['lane'] == 'monitor'], ['Bid change:6'])
        self.assertIn('Bid change:6', self.payload_rows(W2, 'held'))
        self.assertNotIn('Bid change:6', self.payload_rows(W2, 'review'))
        self.assertTrue(self.payload_rows(W2, 'review'))  # the rest still waits for a person's yes

    # --- fix G ---------------------------------------------------------------------------------------------------------
    def test_an_invested_search_leaves_the_log_by_its_stop_loss_step_down(self):
        """G1 (N1, the re-review's probe), since autonomous runs (2026-10-22, decision 98): thank you cards is logged since
        2026-07-10, past its month 3 stop-loss checkpoint with no organic gain (decision 142), and slips to Hold. Its exact keyword already bids the Hold price, so its step-down (stop_loss.py) is its
        campaign's: top of search back to 0% and the $5 Hold budget, in the Auto lane. Until it goes out, log_invest keeps the
        search in the log (its spend stays in Kim's total, and next week's pause of it is flagged invested). Once the
        step-down is recorded as gone out from auto/, the search leaves the log."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True),
                                                invest_log={'thank you cards': dict(since='2026-07-10', role='Invest', organic_then=0)}))
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        # index about 0.83: a Hold search below the 1.0-1.1 Hold uplift band (decision 108), so its bid is its breakeven
        hold = T.query('thank you cards', 1500, 600, 60, 50, 4)

        def plan_week(week, query, bid, orders, today):
            return self.plan(week, data_through=today, queries=others + [query],
                             keywords=keywords + [T.keyword('1', 'thank you cards', 'exact', T.SKC, bid, 40, orders, 30)])
        probe = plan_week(W1, hold, 0.80, 1, W1)
        hold_bid = next(c['new'] for c in probe['changes'] if c['row_id'] == 'Bid change:1')
        shutil.rmtree(self.run_dir(W1))
        plan1 = plan_week(W1, hold, hold_bid, 1, W1)
        term = next(t for t in plan1['terms'] if t['term'] == 'thank you cards')
        self.assertEqual(term['role'], 'Hold')
        [step] = [c for c in plan1['changes'] if c.get('keyword') == 'thank you cards']
        self.assertEqual((step['type'], step['role'], step['tos'], step['budget'], step['lane']),
                         ('Budget and top of search', 'Hold', 0, 5, 'auto'))
        self.assertIs(step['stop_loss_step_down'], True)
        self.assertTrue(step['lane_reason'].startswith('invested 101 days (the month 3 checkpoint) with no gain since its start in '
                                                        'organic rank'), step['lane_reason'])
        self.assertEqual(plan1['stop_loss'][0]['step_down'], 'written')
        self.assertIn(step['row_id'], self.payload_rows(W1, 'auto'))
        self.assertFalse([c for c in plan1['changes'] if c['type'] == 'Stop-loss review'])
        # nothing recorded as gone out yet: the search stays logged, its step-down waiting
        out = self.log_invest(W1, W1)
        self.assertIn('thank you cards: kept as it was, its change this run has not gone out', out['changes'])
        self.assertIn('thank you cards', self.product()['invest_log'])

        # next week, still logged (week 1 not recorded yet): the pause of its keyword applies on its own and is the
        # step-down's bid row; its spend is still in Kim's total
        plan2 = plan_week(W2, T.query('thank you cards', 1500, 600, 60, 60, 0), hold_bid, 0, W2)
        pause = next(c for c in plan2['changes'] if c['row_id'] == 'Pause keyword:1')
        self.assertEqual((pause['lane'], pause['lane_unlocked'], pause.get('invested_search'), pause.get('stop_loss_step_down')),
                         ('auto', 'auto', True, True))
        self.assertIn('Pause keyword:1', self.payload_rows(W2, 'auto'))
        spend = next(t for t in plan2['terms'] if t['term'] == 'thank you cards')['ad_spend']
        self.assertGreater(spend, 0)
        self.assertEqual(plan2['summary'][0]['planned_invest_month_start'], round(spend / 3, 2))

        # week 1's auto/ goes out through MAP and is recorded: log_invest steps the search down
        self.assertEqual(self.applied(W1, 'auto', W1, '--dry-run')['dry_run'], True)
        self.assertGreater(self.applied(W1, 'auto', '2026-10-20')['recorded'], 0)
        out = self.log_invest(W1, '2026-10-20')
        self.assertIn(f"thank you cards: no longer invested (moved to invest_history: the stop-loss step-down {step['row_id']} "
                      f"went out on 2026-10-20 from payloads/auto/ ({step['stop_loss_reason']}))", out['changes'])
        self.assertNotIn('thank you cards', self.product()['invest_log'])
        self.assertEqual(self.product()['invest_history'][-1]['search'], 'thank you cards')

    def test_an_invested_search_whose_index_slips_under_0_8_steps_down_now(self):
        """Decision 182 (Kim, 2026-11-04): thank you cards is logged since 2026-10-05, two weeks before week 1, so no
        stop-loss checkpoint is due. Its index slips under 0.8 on 40 of our SQP clicks (Trim). It steps down this run: its
        keyword at no more than breakeven (the Trim price), its campaign at top of search 0% and the $5 Hold budget, in the
        Auto lane, and once that has gone out the search leaves the invest log."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest', organic_then=0)}))
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        slip = T.query('thank you cards', 1500, 600, 60, 40, 2)
        plan1 = self.plan(W1, data_through=W1, queries=others + [slip],
                          keywords=keywords + [T.keyword('1', 'thank you cards', 'exact', T.SKC, 1.20, 40, 1, 30)])
        term = next(t for t in plan1['terms'] if t['term'] == 'thank you cards')
        self.assertEqual(term['role'], 'Trim')
        [entry] = [s for s in plan1['stop_loss'] if s['keyword'] == 'thank you cards']
        self.assertEqual((entry['slip'], entry['step_down']), (True, 'written'))
        rows = [c for c in plan1['changes'] if c.get('keyword') == 'thank you cards']
        bid = next(c for c in rows if c['type'] == 'Bid change')
        self.assertIs(bid['stop_loss_step_down'], True)
        self.assertLess(bid['new'], 1.20)
        self.assertIn('decision 182', bid['stop_loss_reason'])
        camp = next(c for c in rows if c['type'] == 'Budget and top of search')
        self.assertEqual((camp['tos'], camp['budget'], camp['lane']), (0, 5, 'auto'))
        self.assertFalse([c for c in plan1['changes'] if c['type'] == 'Stop-loss review'])
        self.assertGreater(self.applied(W1, 'auto', '2026-10-20')['recorded'], 0)
        out = self.log_invest(W1, '2026-10-20')
        self.assertNotIn('thank you cards', self.product()['invest_log'], out['changes'])

    def test_a_validated_trim_on_under_15_clicks_does_not_step_down(self):
        """Decision 182 needs 15+ of our clicks: thank you cards, logged, has 2 orders on 12 of our SQP clicks at index
        under 0.8, so decision 177 calls it a validated Trim, but it keeps investing until it has the clicks
        (B0SAMP0001 "prayer bookmarks" was stepped down on 13 clicks, 2026-11-04)."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest', organic_then=0)}))
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        thin = T.query('thank you cards', 1500, 600, 240, 12, 2)
        os.makedirs(self.run_dir(W1), exist_ok=True)   # Amazon was tried: the mids are estimated, the run doesn't stop
        write_json(os.path.join(self.run_dir(W1), 'bid_sources_tried.json'), {'amazon': 'none (test)', 'soldscope': 'none (test)'})
        plan1 = self.plan(W1, data_through=W1, queries=others + [thin], mid=True,
                          keywords=keywords + [T.keyword('1', 'thank you cards', 'exact', T.SKC, 1.20, 12, 2, 10)])
        term = next(t for t in plan1['terms'] if t['term'] == 'thank you cards')
        self.assertEqual(term['role'], 'Trim', (term['index'], term['why'], term.get('sqp_our_clicks')))
        self.assertFalse([s for s in plan1['stop_loss'] if s['keyword'] == 'thank you cards' and s.get('slip')])
        self.assertFalse([c for c in plan1['changes'] if c.get('keyword') == 'thank you cards' and c.get('stop_loss_step_down')])

    def test_a_search_over_the_rank_volume_cap_is_never_a_rank_search(self):
        """Decision 182: thank you cards beats the market (about 1.8) but has about 21,000 searches a month, over the 3,000
        cap (4,000 at its index, decision 189). It is Defend at its breakeven, not Rank; when it is in the invest log it steps down this run."""
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        big = T.query('thank you cards', 60000, 600, 60, 50, 10)
        kw = T.keyword('1', 'thank you cards', 'exact', T.SKC, 1.20, 40, 6, 30)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True)))
        plan0 = self.plan(W1, data_through=W1, queries=others + [big], keywords=keywords + [kw])
        term = next(t for t in plan0['terms'] if t['term'] == 'thank you cards')
        self.assertEqual((term['role'], term['over_rank_cap']), ('Defend', True))
        self.assertIn('rank cap (own 21,429', term['why'])
        self.assertIn('decision 182', term['why'])
        self.assertFalse([c for c in plan0['changes'] if c.get('keyword') == 'thank you cards'
                          and c.get('type') in ('New exact campaign', 'Budget step')])
        shutil.rmtree(self.run_dir(W1))
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest', organic_then=0)}))
        plan1 = self.plan(W1, data_through=W1, queries=others + [big], keywords=keywords + [kw])
        [entry] = [s for s in plan1['stop_loss'] if s['keyword'] == 'thank you cards']
        self.assertEqual((entry['over_rank_cap'], entry['slip'], entry['step_down']), (True, False, 'written'))
        camp = next(c for c in plan1['changes'] if c.get('keyword') == 'thank you cards' and c['type'] == 'Budget and top of search')
        self.assertEqual((camp['tos'], camp['budget'], camp['lane']), (0, 5, 'auto'))
        self.assertIn('rank cap', camp['stop_loss_reason'])

    def test_a_step_down_over_the_rank_cap_never_cuts_under_the_suggested_low(self):
        """Decisions 182/183 (B0SAMP0035 "calendar for kids", 2026-11-04): a logged search over the cap whose live exact bid
        ($0.50) is already under its suggested low ($0.55) keeps that bid; the step-down only moves its campaign (top of
        search 0%, $5). Before the fix it went to breakeven, under the low."""
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        big = T.query('thank you cards', 60000, 600, 60, 50, 10)
        kw = T.keyword('1', 'thank you cards', 'exact', T.SKC, 0.50, 40, 6, 30)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True),
                                                invest_log={'thank you cards': dict(since='2026-10-05', role='Invest', organic_then=0)}))
        plan1 = self.plan(W1, data_through=W1, queries=others + [big], keywords=keywords + [kw])
        bids = [c for c in plan1['changes'] if c.get('keyword_id') == '1' and c['type'] == 'Bid change']
        self.assertFalse([c for c in bids if c['new'] < 0.50], bids)
        camp = next(c for c in plan1['changes'] if c.get('keyword') == 'thank you cards' and c['type'] == 'Budget and top of search')
        self.assertEqual((camp['tos'], camp['budget']), (0, 5))

    def test_the_rank_cap_cross_checks_datadive_volume(self):
        """Decision 182, cross-checked (Kim, 2026-11-04): SQP counts thank you cards at about 540 a month, under the cap,
        but the product file's Rank Radar says 5,000 a month (read as it is since decision 189: no 0.8 conversion). The
        highest reading wins: the search is over even its strong-index cap (4,000) and bids Defend, not Rank."""
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        small = T.query('thank you cards', 1500, 600, 60, 50, 10)
        kw = T.keyword('1', 'thank you cards', 'exact', T.SKC, 1.20, 40, 6, 30)
        rank = dict(source='DataDive Rank Radar', keywords=[dict(kw='thank you cards', sv=5000)])
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True)))
        plan0 = self.plan(W1, data_through=W1, queries=others + [small], keywords=keywords + [kw])
        term0 = next(t for t in plan0['terms'] if t['term'] == 'thank you cards')
        self.assertFalse(term0['over_rank_cap'])
        shutil.rmtree(self.run_dir(W1))
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True), rank=rank))
        plan1 = self.plan(W1, data_through=W1, queries=others + [small], keywords=keywords + [kw])
        term = next(t for t in plan1['terms'] if t['term'] == 'thank you cards')
        self.assertEqual((term['role'], term['over_rank_cap'], term['monthly_searches']), ('Defend', True, 5000))
        self.assertEqual(term['rank_cap_sources'][0], 'DataDive 5,000')

    def test_a_big_search_bids_its_suggested_low_and_a_product_can_raise_its_cap(self):
        """Decision 182 (Kim, 2026-11-04: "cut to amazon's suggested low .. instead of breakeven"): the exact keyword of a
        search over the cap is cut to its suggested low, never under breakeven and never raised. A product whose listing is
        ready for bigger searches carries its own cap (rank_max_monthly_searches): at 30,000 the same search is a rank
        search again."""
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        big = T.query('thank you cards', 60000, 600, 60, 50, 10)
        kw = T.keyword('1', 'thank you cards', 'exact', T.SKC, 1.20, 40, 6, 30)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True)))
        sug = dict(SUGGESTED, **{'thank you cards': [1.05, 1.15, 1.40]})   # low above breakeven (0.92)
        plan0 = self.plan(W1, data_through=W1, queries=others + [big], keywords=keywords + [kw], suggested=sug)
        row = next(c for c in plan0['changes'] if str(c.get('keyword_id')) == '1' and c['type'] == 'Bid change')
        term = next(t for t in plan0['terms'] if t['term'] == 'thank you cards')
        self.assertEqual(term['role'], 'Defend')
        self.assertEqual(row['new'], 1.05)
        self.assertIn('suggested low', row['why'] + (row.get('action') or ''))
        shutil.rmtree(self.run_dir(W1))
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True), rank_max_monthly_searches=30000))
        plan1 = self.plan(W1, data_through=W1, queries=others + [big], keywords=keywords + [kw], suggested=sug)
        term1 = next(t for t in plan1['terms'] if t['term'] == 'thank you cards')
        self.assertEqual((term1['role'], term1['over_rank_cap']), ('Rank', False))

    def test_a_strong_index_search_may_be_a_rank_search_up_to_4000(self):
        """Decision 189 (Kim, 2026-11-05: "3,000 cap; index 1.3+ to 4,000"): thank you cards at about 3,500 searches a
        month is over the 3,000 cap. At index 1.33 (1.3 or more) it is a rank search, held to the 4,000 strong-index cap; at
        index 1.17 it bids Defend. At about 4,500 a month even index 1.83 is over."""
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']
        kw = T.keyword('1', 'thank you cards', 'exact', T.SKC, 1.20, 40, 6, 30)
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True)))
        seen = {}
        for vol, purchases in ((9800, 7), (9800, 6), (8120, 6), (12600, 10)):
            plan = self.plan(W1, data_through=W1, queries=others + [T.query('thank you cards', vol, 600, 60, 50, purchases)],
                             keywords=keywords + [kw])
            term = next(t for t in plan['terms'] if t['term'] == 'thank you cards')
            seen[(vol, purchases)] = (term['role'], term['over_rank_cap'], term['rank_cap'], round(term['index'], 2))
            shutil.rmtree(self.run_dir(W1))
        self.assertEqual(seen[(9800, 7)], ('Rank', False, 4000.0, 1.33))
        self.assertEqual(seen[(9800, 6)], ('Defend', True, 3000.0, 1.17))
        self.assertEqual(seen[(8120, 6)][:3], ('Rank', False, 3000.0))     # about 2,900 a month: under the 3,000 cap
        self.assertEqual(seen[(12600, 10)][:3], ('Defend', True, 4000.0))  # about 4,500 a month

    def test_rank_cap_for_raises_the_cap_only_for_a_strong_index(self):
        import stage
        self.assertEqual(stage.rank_cap_for(3000, 1.3, 1.3, 4000), 4000.0)
        self.assertEqual(stage.rank_cap_for(3000, 1.29, 1.3, 4000), 3000)
        self.assertEqual(stage.rank_cap_for(3000, None, 1.3, 4000), 3000)
        self.assertEqual(stage.rank_cap_for(10000, 2.0, 1.3, 4000), 10000.0)   # a product's own higher cap is kept
        self.assertIsNone(stage.rank_cap_for(None, 2.0, 1.3, 4000))             # cap off stays off
        self.assertEqual(stage.rank_cap_for(3000, 2.0, None, None), 3000)

    def test_cap_volume_takes_the_highest_reading(self):
        import stage
        self.assertEqual(stage.cap_volume(500.0, 5000, None), (5000.0, ['DataDive 5,000', 'own 500']))
        self.assertEqual(stage.cap_volume(500.0, None, 125584)[0], 125584.0)
        self.assertEqual(stage.cap_volume(None, None, None), (None, []))
        self.assertEqual(stage.cap_volume(0.0, None, None), (0.0, []))

    def test_a_stop_loss_with_no_keyword_to_step_down_is_held_for_the_next_run(self):
        """Where the search's exact keyword is not in the run's keyword report, no step-down can be written: the run keeps a
        'Stop-loss review' row, held for the next run since decision 107 (a person's call until 2026-10-23). It is on no Bids
        item, and the search stays in the invest log until a step-down goes out."""
        write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=True),
                                                invest_log={'thank you cards': dict(since='2026-07-10', role='Invest', organic_then=0)}))
        others = [x for x in QUERIES if x['Query'] != 'thank you cards']
        keywords = [k for k in T.KEYWORDS if k['KeywordId'] != '1']   # no exact keyword of thank you cards at all
        plan1 = self.plan(W1, data_through=W1, queries=others + [T.query('thank you cards', 1500, 600, 60, 50, 4)],
                          keywords=keywords)
        [review] = [c for c in plan1['changes'] if c.get('keyword') == 'thank you cards']
        self.assertEqual((review['type'], review['lane']), ('Stop-loss review', 'monitor'))
        self.assertIn('the next run tries again', review['lane_reason'])
        self.assertIn("isn't in this run's keyword report", review['why'])
        self.assertEqual(plan1['stop_loss'][0]['step_down'], 'review')
        self.assertFalse([i for i in plan1['human_review'] if i['kind'] == 'bid'])
        self.assertIn('thank you cards', self.product()['invest_log'])

    def test_a_lower_decline_never_lowers_the_bar_across_weeks(self):
        """G2 (N2, the re-review's probe): two people decline the raise on keyword 4 (an owner-level row) on week 1's item,
        the higher-ranked first. Step 2's lock names the higher one, week 2's item row asks for that level, and the second
        decliner's approval on week 2 is held."""
        for first, second in (('Lee', 'Sam'), ('Kim', 'Lee')):
            with self.subTest(first=first, second=second):
                shutil.rmtree(os.path.join(self.tmp, 'runs'), ignore_errors=True)
                self.server.pages.clear()
                self.server.reviews.clear()
                write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
                self.plan(W1)
                self.publish(W1)
                self.server.decide(ASIN, f'bids-{W1}', 'Bid change:4', 'decline', by=first, at='2026-10-20T02:00:00.000Z')
                self.server.decide(ASIN, f'bids-{W1}', 'Bid change:4', 'decline', by=second, at='2026-10-20T03:00:00.000Z')
                self.approvals(W1, '2026-10-26T15:00:00Z')  # step 2
                self.assertEqual([(d['id'], d['what'], d['by']) for d in self.product()['decisions']],
                                 [('Bid change:4', 'decline', first)])
                self.save_reviews(W2)
                plan2 = self.plan(W2)
                item_row = next(r for r in self.item(plan2)['rows'] if r['row_id'] == 'Bid change:4')
                self.assertEqual((item_row['approval_required'], item_row['lock_by']), (first, first))
                self.publish(W2)
                self.server.decide(ASIN, f'bids-{W2}', 'Bid change:4', 'approve', by=second, at='2026-10-27T02:00:00.000Z')
                out = self.approvals(W2, '2026-10-27T15:00:00Z')
                self.assertEqual(out['skipped'], [dict(row_id='Bid change:4', reason=(
                    f"needs {first}'s approval: {first} declined it (approved by {second})"))])
                self.assertFalse(os.path.exists(os.path.join(self.run_dir(W2), 'payloads', 'approved', '4_bids_01.json')))

    def test_a_lower_decline_on_the_same_item_never_lowers_the_bar(self):
        """G2 (N2, the re-review's probe): on one item, a second, lower-ranked decline doesn't replace the first, so the
        second decliner's approval is held; the first decliner's goes out."""
        cases = (([('Lee', 'decline'), ('Sam', 'decline'), ('Sam', 'approve')], False, 'Lee'),
                 ([('Kim', 'decline'), ('Lee', 'decline'), ('Lee', 'approve')], False, 'Kim'),
                 ([('Lee', 'decline'), ('Sam', 'approve'), ('Sam', 'decline'), ('Sam', 'approve')], False, 'Lee'),
                 ([('Lee', 'decline'), ('Sam', 'decline'), ('Lee', 'approve')], True, None))
        for steps, goes, decliner in cases:
            with self.subTest(steps=steps):
                shutil.rmtree(os.path.join(self.tmp, 'runs'), ignore_errors=True)
                self.server.pages.clear()
                self.server.reviews.clear()
                write_json(self.product_file, T.product(auto=dict(T.AUTO, enabled=False)))
                self.plan(W1)
                self.publish(W1)
                for i, (by, what) in enumerate(steps):
                    self.server.decide(ASIN, f'bids-{W1}', 'Bid change:4', what, by=by, at=f'2026-10-20T0{2 + i}:00:00.000Z')
                out = self.approvals(W1, '2026-10-20T15:00:00Z')
                bids = os.path.join(self.run_dir(W1), 'payloads', 'approved', '4_bids_01.json')
                locks = [(d['id'], d['what'], d['by']) for d in self.product().get('decisions') or []]
                if goes:
                    self.assertEqual((out['skipped'], locks), ([], []))
                    self.assertEqual([r['keywordId'] for r in read_json(bids)], ['4'])
                else:
                    self.assertEqual(out['skipped'], [dict(row_id='Bid change:4', reason=(
                        f"declined by {decliner}; needs {decliner}'s approval to change it (approved by {steps[-1][0]})"))])
                    self.assertFalse(os.path.exists(bids))
                    self.assertEqual(locks, [('Bid change:4', 'decline', decliner)])


if __name__ == '__main__':
    unittest.main()
