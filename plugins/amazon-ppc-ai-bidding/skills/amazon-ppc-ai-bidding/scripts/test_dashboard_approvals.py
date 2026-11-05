"""dashboard.py approvals: the team's per-row approvals become payload files, and every decision becomes a lock.

Most tests plan a real run folder (the synthetic one test_plan_lanes builds) in shadow mode, where the Bids item holds
every row, write the product file with that item in it, and run cmd_approvals with the server patched out. A few use a
hand-built plan.json for row types the real fixture doesn't produce. Nothing here touches the network or Amazon.
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
from datetime import datetime, timezone

import dashboard
import human_review
import lanes
import plan as planner
import plan_lanes
import test_plan_lanes as T

ASIN = T.ASIN
ITEM = 'bids-2026-10-19'
MON = '2026-10-19T15:00:00Z'  # Monday 08:00 in Los Angeles: the planned run's apply_after day
SUN = '2026-10-18T20:00:00Z'  # Sunday 13:00 in Los Angeles
AT = '2026-10-19T02:00:00.000Z'  # a decision made at 10:00 Singapore time on 19 October
BUNDLE = ['New exact campaign:::blank cards', 'Pause keyword:2', 'Negative exact:101:201:blank cards',
          'Negative exact:102:202:blank cards']
NO_SEEN = "can't confirm what was approved (the decision doesn't say what the person saw)"


SHOWN = object()  # dec()'s default `seen`: what the dashboard showed for the row, read from the run's plan.json (resolve)


# the enabled fixture's row for a person since autonomous runs (2026-10-22): a $15 budget on 'thank you cards' (its funnel
# negative, the row for a person before, applies on its own now)
ODD_BUDGET = 'Budget and top of search:105::thank you cards'
HEAD_PROMOTION = 'New exact campaign:::notecards'   # a one-word search's promotion (T.HEAD_TERM): a person's call


def dec(row_id, decision, by='Lee', at=AT, item_id=ITEM, note=None, seen=SHOWN):
    """One entry of GET /api/reviews/<ASIN>, as the 6b buttons send it: with `seen` ({current, new, new_capped}), which
    defaults to the row's numbers in the plan (resolved when the command runs). seen=None leaves it out, as today's
    client does."""
    entry = dict(row_id=row_id, item_id=item_id, decision=decision, by=by, at=at, note=note)
    if seen is not None:
        entry['seen'] = seen
    return entry


def resolve(plan, entries):
    """`entries` with every SHOWN `seen` replaced by the row's current, new and new_capped in `plan` (its change row, else
    its bids item row): what the person saw on the page published from that plan."""
    if not isinstance(entries, list):
        return entries
    rows = {c.get('row_id'): c for c in (plan or {}).get('changes') or []}
    for item in (plan or {}).get('human_review') or []:
        if isinstance(item, dict) and item.get('kind') == 'bid':
            for r in item.get('rows') or []:
                rows.setdefault(r.get('row_id'), r)
    out = []
    for e in entries:
        if isinstance(e, dict) and e.get('seen') is SHOWN:
            row = rows.get(e.get('row_id')) or {}
            e = dict(e, seen={k: row.get(k) for k in dashboard.SEEN_KEYS})  # E2: every number the card shows
        out.append(e)
    return out


def seen_on(plan, row_id):
    """What the dashboard showed for a row of the plan's bids item: its current, new and new_capped, and (E2) the budgets,
    boosts and modelled monthly spend the row carries (None when it has none), as the card sends them."""
    item = next(i for i in plan['human_review'] if i['kind'] == 'bid')
    row = next(r for r in item['rows'] if r['row_id'] == row_id)
    return {k: row.get(k) for k in dashboard.SEEN_KEYS}


BID_SEEN = ('current', 'new', 'new_capped')  # what an approval said it saw before E2 (an older entry)


def write_json(path, data, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
        fh.write('\n')


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def bid_row(kid, current=0.4, new=0.5, **kw):
    return dict(type='Bid change', row_id=f'Bid change:{kid}', keyword=f'search {kid}', keyword_id=kid, campaign_id='C1',
                ad_group_id='A1', current=current, new=new, lane='human', **kw)


class Base(unittest.TestCase):
    # C2: a test that runs approvals again on one run folder, as though what approved/ held never went out, sets this:
    # every approvals run then passes --discard-unapplied
    rerun_as_unapplied = False

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.run_dir = os.path.join(self.tmp, 'run')
        self.data = os.path.join(self.tmp, 'data')
        self.product_file = os.path.join(self.data, 'asins', f'{ASIN}.json')
        self.shared = T.shared_config()

    # --- fixtures ---------------------------------------------------------------------------------------------
    def plan_run(self, shadow=True, run=None, **product_over):
        """Plan the synthetic run with main(), then store its Bids item in the product file as the dashboard would. `run`:
        make_run's arguments (an old data_through, say)."""
        T.make_run(self.run_dir, **(run or {}))
        auto = dict(T.AUTO, enabled=not shadow)
        auto.update(product_over.pop('auto', {}))
        cfg = T.product(auto=auto, **product_over)
        write_json(self.product_file, cfg)
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        real_read = planner.read_json

        def read(path, *a, **k):
            # the fixture's numbers are the ad-record prices: SQP pricing (decision 162) is off here, as in T.shared_config
            out = real_read(path, *a, **k)
            if os.path.basename(str(path)) == 'config.json' and isinstance(out, dict):
                out = T.no_mid(dict(out, pricing=dict(out.get('pricing') or {}, search_conversion='ad')))
            return out
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.planned_at(), \
                unittest.mock.patch.object(planner, 'read_json', read):
            planner.main()
        self.plan = read_json(os.path.join(self.run_dir, 'plan.json'))
        item = next((i for i in self.plan['human_review'] if i['kind'] == 'bid'), None)
        if item is None and not shadow:
            return self.plan  # autonomous runs (2026-10-22): an enabled run with no row for a person has no Bids item
        self.assertEqual(item['id'], ITEM)
        cfg['human_review'] = [item]
        write_json(self.product_file, cfg)
        return self.plan

    def synthetic_run(self, changes, apply_after='2026-10-19', levels=None, **product_over):
        """A hand-built plan.json whose Bids item lists every change (each 'owner' level unless `levels` says otherwise
        by row_id), and a product file holding that item."""
        rows = [dict(row_id=c['row_id'], type=c['type'], approval_required=(levels or {}).get(c['row_id'], 'owner'))
                for c in changes]
        item = dict(id=ITEM, kind='bid', title='x', reason='x', action='x', source='x', window='x', status='open',
                    rows=rows, shadow=True)
        self.plan = dict(summary=[dict(asin=ASIN, apply_after=apply_after, shadow=True)], changes=changes,
                         human_review=[human_review.validate([item])[0]])
        write_json(os.path.join(self.run_dir, 'plan.json'), self.plan)
        write_json(self.product_file, dict(T.product(**product_over), human_review=[self.plan['human_review'][0]]))
        return self.plan

    def edit_product(self, **fields):
        product = read_json(self.product_file)
        product.update(fields)
        write_json(self.product_file, product)

    def product(self):
        return read_json(self.product_file)

    def raw_product(self):
        with open(self.product_file, 'rb') as fh:
            return fh.read()

    # --- running the command ----------------------------------------------------------------------------------
    def args(self, live=None, now=MON, live_file=None, **over):
        a = argparse.Namespace(asin=ASIN, run=self.run_dir, data=self.data, live=live_file, now=now, dry_run=False,
                               discard_unapplied=self.rerun_as_unapplied)
        if live is not None:
            path = os.path.join(self.tmp, 'live.json')
            write_json(path, live)
            a.live = path
        for k, v in over.items():
            setattr(a, k, v)
        return a

    def run_cmd(self, entries, live=None, now=MON, **over):
        out, err = io.StringIO(), io.StringIO()
        entries = resolve(read_json(os.path.join(self.run_dir, 'plan.json')) if os.path.exists(
            os.path.join(self.run_dir, 'plan.json')) else None, entries)
        with unittest.mock.patch.object(dashboard, 'call', return_value=entries) as call, \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                dashboard.cmd_approvals(self.args(live, now, **over))
            finally:
                self.call = call
        self.stderr = err.getvalue()
        return json.loads(out.getvalue())

    def run_applied(self, folder, date='2026-10-20', entries=None, **over):
        # E4: the check before an apply (dry_run) runs on a US weekday inside the window unless a test says otherwise
        a = argparse.Namespace(asin=ASIN, run=self.run_dir, data=self.data, folder=folder, date=date, dry_run=False, now=MON,
                               rows=None)
        for k, v in over.items():
            setattr(a, k, v)
        out = io.StringIO()
        entries = resolve(read_json(os.path.join(self.run_dir, 'plan.json')), entries if entries is not None else [])
        with unittest.mock.patch.object(dashboard, 'call', return_value=entries) as call, \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                dashboard.cmd_applied(a)
            finally:
                self.applied_call = call
        return json.loads(out.getvalue())

    def refused(self, entries=None, live=None, **over):
        with self.assertRaises(SystemExit) as cm:
            self.run_cmd([] if entries is None else entries, live, **over)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    # --- reading what was written -----------------------------------------------------------------------------
    @property
    def approved_dir(self):
        return os.path.join(self.run_dir, 'payloads', 'approved')

    def approved_files(self):
        """The payload files in payloads/approved/, without its rows.json."""
        if not os.path.isdir(self.approved_dir):
            return {}
        return {n: read_json(os.path.join(self.approved_dir, n)) for n in sorted(os.listdir(self.approved_dir)) if n != 'rows.json'}

    def locks(self):
        return {d['id']: d for d in self.product().get('decisions', [])}

    def record(self):
        """payloads/approved_decisions.json: who approved each row approvals put in approved/."""
        path = os.path.join(self.run_dir, 'payloads', 'approved_decisions.json')
        return read_json(path) if os.path.exists(path) else {}


# =====================================================================================================================
class ApprovalsToPayloadsTest(Base):
    # --- the brief's three ----------------------------------------------------------------------------------------
    def test_only_approved_rows_written(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve'), dec('Bid change:5', 'decline')])
        self.assertEqual(self.approved_files(), {'4_bids_01.json': [dict(type='sp_keywords', keywordId='1', bid=0.98),
                                                                    dict(type='sp_keywords', keywordId='3', bid=0.1)]})
        self.assertEqual((out['approved'], out['declined'], out['skipped'], out['ignored']), (2, 1, [], []))
        self.assertEqual(out['files'], {'4_bids_01.json': 2})
        self.assertEqual([c.args[:2] for c in self.call.call_args_list], [('GET', f'/api/reviews/{ASIN}')])  # a read, nothing else
        self.assertEqual(set(self.locks()), {'Bid change:5'})  # B4: only the decline locks; an approval locks once applied

    def test_drifted_row_skipped(self):
        """Review Focus 3: the plan saw this bid at $0.50 and it is $0.55 now, so it is left out and listed."""
        plan = self.plan_run()
        row = next(x for x in plan['changes'] if x['row_id'] == 'Bid change:3')
        self.assertEqual((row['current'], row['new']), (0.5, 0.1))
        live = [dict(keywordId='3', bid=0.55, state='ENABLED'), dict(keywordId='1', bid=0.80, state='ENABLED')]
        out = self.run_cmd([dec('Bid change:3', 'approve'), dec('Bid change:1', 'approve')], live=live)
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:3', reason='changed since the plan: planned from $0.50, now $0.55')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['1'])
        self.assertIs(out['checked_live'], True)
        self.assertEqual(out['approved'], 1)
        # approvals write no approve lock (B4); the one that went nowhere will never get one
        self.assertEqual(self.locks(), {})

    def test_a_held_back_approval_releases_the_lock_an_earlier_decline_left(self):
        self.plan_run()
        stale = dict(id='Bid change:3', what='decline', by='Kim', until='2026-11-16')
        other = dict(id='keep me', what='approve', by='Lee', until='2026-12-01')
        self.edit_product(decisions=[stale, other])
        out = self.run_cmd([dec('Bid change:3', 'approve')], live=[dict(keywordId='3', bid=0.55, state='ENABLED')])
        self.assertEqual([s['row_id'] for s in out['skipped']], ['Bid change:3'])
        self.assertEqual(self.product()['decisions'], [other])  # the decline it reversed no longer holds the row out
        self.assertEqual(out['locks_released'], 1)

    def test_an_approve_lock_survives_a_later_drift_skip(self):
        """`applied` locked the row when it went out (B4); a later approvals run (fresh --live data, the apply not recorded
        in this run folder) finds it moved. Only a decline's lock is released for a held-back approval: this approve lock is
        the record that the row went out."""
        self.plan_run()
        sent = dict(id='Bid change:3', what='approve', by='Lee', on='2026-10-19', until='2026-11-17', direction='down')
        self.edit_product(decisions=[sent])  # as `applied` wrote it
        out = self.run_cmd([dec('Bid change:3', 'approve')], live=[dict(keywordId='3', bid=0.55, state='ENABLED')])
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:3', reason='changed since the plan: planned from $0.50, now $0.55')])
        self.assertEqual(self.locks()['Bid change:3'], sent)  # still there, unchanged
        self.assertEqual((out['locks_written'], out['locks_released']), (0, 0))

    def test_locks_written_for_4_weeks(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'decline', by='Lee', at=AT),
                      dec('Bid change:5', 'decline', by='Kim', at='2026-10-19T17:30:00.000Z')])  # 01:30 SGT on the 20th
        locks = self.locks()
        self.assertEqual(locks['Bid change:1'], dict(id='Bid change:1', what='decline', by='Lee', on='2026-10-19',
                                                     until='2026-11-16', direction='up'))
        self.assertEqual(locks['Bid change:5'], dict(id='Bid change:5', what='decline', by='Kim', on='2026-10-20',
                                                     until='2026-11-17', direction='down'))
        held, problem = plan_lanes.lock_table(self.product())  # the planner reads them back as locks
        self.assertIsNone(problem)
        self.assertEqual(plan_lanes._until(held[lanes.lock_key('Bid change:1')]), '2026-11-16')

    # --- R1: built from the plan, shaped by plan.payload_files ----------------------------------------------------
    def test_approving_everything_gives_the_runs_own_payloads(self):
        plan = self.plan_run()
        self.run_cmd([dec(r['row_id'], 'approve') for r in plan['human_review'][-1]['rows']])
        review = {n: read_json(os.path.join(self.run_dir, 'payloads', 'review', n))
                  for n in os.listdir(os.path.join(self.run_dir, 'payloads', 'review')) if n != 'rows.json'}
        # shadow's review/ holds the full set, so the shapes are identical by construction; the one difference is that a
        # bid the auto lane would cap is written at the cap (see test_an_approved_row_with_a_cap_is_written_at_the_cap)
        capped = {}
        for x in plan['changes']:
            if x.get('new_capped') is not None:
                capped[str(x.get('keyword_id') or x.get('target_id'))] = x['new_capped']
        self.assertEqual(sorted(capped), ['302', '4'])
        for rows in review.values():
            for row in rows:
                key = str(row.get('keywordId') or row.get('targetId'))
                if key in capped and 'bid' in row:
                    row['bid'] = capped[key]
        self.assertEqual(self.approved_files(), review)

    def test_approved_payloads_returns_files_and_skipped(self):
        changes = [bid_row('K1', current=0.40, new=0.50), bid_row('K2', current=0.30, new=0.35)]
        plan = self.synthetic_run(changes)
        live = [dict(keywordId='K1', bid=0.55, state='ENABLED'), dict(keywordId='K2', bid=0.30, state='ENABLED')]
        files, skipped = dashboard.approved_payloads(
            plan, resolve(plan, [dec('Bid change:K1', 'approve'), dec('Bid change:K2', 'approve')]), live, self.shared, ASIN)
        self.assertEqual(files, {'4_bids_01.json': [dict(type='sp_keywords', keywordId='K2', bid=0.35)]})
        self.assertEqual(skipped, [dict(row_id='Bid change:K1', reason='changed since the plan: planned from $0.40, now $0.55')])
        files, skipped = dashboard.approved_payloads(plan, resolve(plan, [dec('Bid change:K1', 'approve')]), None, self.shared,
                                                     ASIN)
        self.assertEqual((list(files), skipped), (['4_bids_01.json'], []))  # no live rows: nothing to drift against

    # --- R2: which decisions count --------------------------------------------------------------------------------
    def test_decisions_for_another_item_are_ignored(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:1', 'approve', item_id='bids-2026-10-12'), dec('Bid change:3', 'approve'),
                            dec('no-such-row', 'approve')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['3'])
        by_item = {g['item_id']: g for g in out['ignored']}
        self.assertEqual(set(by_item), {'bids-2026-10-12', ITEM})
        self.assertEqual(by_item['bids-2026-10-12']['count'], 1)
        self.assertIn('another item', by_item['bids-2026-10-12']['reason'])
        self.assertEqual(by_item[ITEM]['row_ids'], ['no-such-row'])
        self.assertIn("isn't in this run's bids item", by_item[ITEM]['reason'])
        self.assertEqual(self.locks(), {})  # an ignored decision locks nothing (and an approval locks only once applied)

    def test_the_latest_decision_wins(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:1', 'decline'),
                            dec('Bid change:3', 'decline'), dec('Bid change:3', 'approve'),
                            dec('Bid change:5', 'decline', at='2026-10-19T09:00:00.000Z'),  # listed first, decided later
                            dec('Bid change:5', 'approve', at='2026-10-19T03:00:00.000Z')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['3'])
        self.assertEqual((out['approved'], out['declined']), (1, 2))
        self.assertEqual({k: v['what'] for k, v in self.locks().items()}, {'Bid change:1': 'decline', 'Bid change:5': 'decline'})
        self.assertEqual(list(self.record()), ['Bid change:3'])  # the approval behind what went to approved/

    # --- B3 (I6, I1): approvals on a closed item -------------------------------------------------------------------
    def close_item(self, status, note):
        product = self.product()
        product['human_review'] = human_review.transition(product['human_review'], ITEM, status, None, note, '2026-10-26')
        write_json(self.product_file, product)

    def test_a_resolved_item_is_approved_as_usual(self):
        """A person closing the item is not a newer run: its approvals still go out and its declines still lock."""
        plan = self.plan_run()
        self.close_item('resolved', 'Every row decided on the dashboard')
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=seen_on(plan, 'Bid change:1')), dec('Bid change:5', 'decline')])
        self.assertEqual((out['mode'], out['item_status'], out['approved']), ('normal', 'resolved', 1))
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['1'])
        self.assertEqual(set(self.locks()), {'Bid change:5'})

    def test_a_superseded_item_records_its_declines_and_applies_nothing(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        os.makedirs(self.approved_dir)
        write_json(os.path.join(self.approved_dir, '4_bids_01.json'), [dict(type='sp_keywords', keywordId='1', bid=0.98)])
        notes = {'Superseded by bids-2026-10-26': 'superseded by bids-2026-10-26',
                 'Superseded by the run of 2026-10-26, which had nothing to decide':
                     'superseded by the run of 2026-10-26, which had nothing to decide',
                 'Not needed after the price change': 'dismissed (Not needed after the price change)'}
        for note, said in notes.items():
            with self.subTest(note=note):
                self.plan_run()
                self.close_item('dismissed', note)
                out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:5', 'decline', by='Kim')])
                self.assertEqual((out['mode'], out['item_status']), ('decisions_only', 'dismissed'))
                self.assertEqual(out['message'], f"This run's bids item was {said}: declines were recorded as locks, approvals "
                                                 'were not applied (approve the rows on the newest run)')
                self.assertIn(out['message'], self.stderr)
                self.assertEqual((out['approved'], out['files'], out['declined']), (0, {}, 1))
                self.assertEqual(self.approved_files(), {})  # nothing of a closed item may go out, not even an older file
                self.assertEqual(out['discarded'], ['4_bids_01.json (no rows.json)'] if note.startswith('Superseded by bids')
                                 else [])
                self.assertEqual(self.record(), {})
                self.assertEqual(self.locks()['Bid change:5'], dict(id='Bid change:5', what='decline', by='Kim', on='2026-10-19',
                                                                   until='2026-11-16', direction='down'))
                self.assertNotIn('Bid change:1', self.locks())
                self.assertNotIn('a newer run replaced it', json.dumps(out))

    def test_a_superseded_item_does_not_release_a_decline_an_approval_reversed(self):
        """Only the newest run's item can reverse a decline: on a closed item the approval isn't applied, so the row stays
        locked and reaches a person on the newest run."""
        self.plan_run()
        stale = dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        self.edit_product(decisions=[stale])
        self.close_item('dismissed', 'Superseded by bids-2026-10-26')
        out = self.run_cmd([dec('Bid change:3', 'approve')])
        self.assertEqual((out['locks_released'], self.locks()['Bid change:3']), (0, stale))

    def test_a_run_whose_item_the_product_file_does_not_hold_is_refused(self):
        self.plan_run()
        self.edit_product(human_review=[])
        self.assertIn(ITEM, self.refused([dec('Bid change:1', 'approve')]))
        self.assertFalse(os.path.exists(self.approved_dir))

    def test_a_plan_without_a_bids_item_is_refused(self):
        self.plan_run()
        self.plan['human_review'] = [i for i in self.plan['human_review'] if i['kind'] != 'bid']
        write_json(os.path.join(self.run_dir, 'plan.json'), self.plan)
        self.assertIn('no bids item', self.refused())

    def test_a_run_folder_for_another_product_is_refused(self):
        self.plan_run()
        other = os.path.join(self.data, 'asins', 'B0OTHER000.json')
        write_json(other, read_json(self.product_file))
        message = self.refused(asin='B0OTHER000')
        self.assertIn('B0OTHER000', message)
        self.assertIn(ASIN, message)
        self.assertFalse(os.path.exists(self.approved_dir))

    # --- R3: promotion bundles ------------------------------------------------------------------------------------
    def test_a_promotion_bundle_is_all_or_nothing(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        skipped_reason = "part of a promotion that isn't fully approved: blank cards"
        # one member undecided: nothing of the bundle goes out, everything of it is listed
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE[:3]] + [dec('Bid change:1', 'approve')])
        self.assertEqual(list(self.approved_files()), ['4_bids_01.json'])
        self.assertEqual({s['row_id'] for s in out['skipped']}, set(BUNDLE))
        self.assertEqual({s['reason'] for s in out['skipped']}, {skipped_reason})
        # approved but held back, so no lock: next week's planner plans the bundle again
        self.assertEqual(set(self.locks()) & set(BUNDLE), set())
        # one member declined: same, and only the decline locks
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE[:3]] + [dec(BUNDLE[3], 'decline')])
        self.assertEqual(self.approved_files(), {})
        self.assertEqual({s['row_id'] for s in out['skipped']}, set(BUNDLE))
        self.assertEqual({k: v['what'] for k, v in self.locks().items() if k in BUNDLE}, {BUNDLE[3]: 'decline'})
        # the promotion itself undecided; the declined member is approved now, so the decline it reversed no longer locks
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE[1:]])
        self.assertEqual(self.approved_files(), {})
        self.assertEqual({s['row_id'] for s in out['skipped']}, set(BUNDLE))
        self.assertEqual(set(self.locks()) & set(BUNDLE), set())
        # all four approved: the whole bundle goes out together; its rows lock once `applied` records it (B4)
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        files = self.approved_files()
        self.assertEqual(sorted(files), ['1_new_campaigns.json', '1b_new_skc_specs.json', '3_pauses.json', '6_negatives_01.json'])
        self.assertEqual(len(files['6_negatives_01.json']), 2)
        self.assertEqual(out['skipped'], [])
        self.assertEqual(set(self.locks()) & set(BUNDLE), set())
        self.assertEqual(set(self.record()), set(BUNDLE))

    def test_a_bundle_nobody_has_decided_is_pending_not_skipped(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        out = self.run_cmd([dec('Bid change:1', 'approve')])
        self.assertEqual(out['skipped'], [])  # like any undecided row, the promotion is simply waiting
        self.assertEqual(list(self.approved_files()), ['4_bids_01.json'])
        # one decision on any row of the bundle is enough to explain why the rest of it didn't go
        out = self.run_cmd([dec('Negative exact:101:201:blank cards', 'approve')])
        self.assertEqual({s['row_id'] for s in out['skipped']}, set(BUNDLE))

    # --- R4: the drift check --------------------------------------------------------------------------------------
    def test_a_bid_inside_half_a_cent_is_not_drift(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        for live_bid, goes in ((0.504, True), (0.495, True), (0.506, False), (0.494, False)):
            with self.subTest(live=live_bid):
                out = self.run_cmd([dec('Bid change:3', 'approve')], live=[dict(keywordId='3', bid=live_bid, state='ENABLED')])
                self.assertEqual(out['approved'], 1 if goes else 0)
                self.assertEqual(len(out['skipped']), 0 if goes else 1)

    def test_an_already_paused_row_is_skipped(self):
        self.plan_run()
        live = [dict(targetId='301', state='PAUSED'), dict(keywordId='3', bid=0.5, state='ENABLED')]
        out = self.run_cmd([dec('Pause target:301', 'approve'), dec('Bid change:3', 'approve')], live=live)
        self.assertEqual(out['skipped'], [dict(row_id='Pause target:301', reason='already paused')])
        self.assertEqual(list(self.approved_files()), ['4_bids_01.json'])

    def test_a_row_missing_from_live_is_skipped_and_ids_compare_as_strings(self):
        self.plan_run()
        live = [dict(keywordId=3, bid=0.5, state='ENABLED')]  # an int id still matches the plan's '3'
        out = self.run_cmd([dec('Bid change:3', 'approve'), dec('Pause target:301', 'approve')], live=live)
        self.assertEqual(out['skipped'], [dict(row_id='Pause target:301', reason='not found live')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['3'])

    def test_a_bid_row_no_longer_enabled_is_skipped(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:3', 'approve')], live=[dict(keywordId='3', bid=0.5, state='PAUSED')])
        self.assertEqual([s['row_id'] for s in out['skipped']], ['Bid change:3'])
        self.assertIn('no longer enabled', out['skipped'][0]['reason'])

    def test_live_file_shapes(self):
        self.plan_run()
        rows = [dict(keywordId='3', bid=0.55, state='ENABLED')]
        wrapped = [dict(type='text', text=json.dumps(rows))]  # the tool-result wrapper Claude Code saves big outputs in
        wrapped_data = [dict(type='text', text=json.dumps({'data': rows}))]
        for name, shape in (('list', rows), ('data', {'data': rows}), ('results', {'results': rows}), ('items', {'items': rows}),
                            ('tool-result', wrapped), ('tool-result data', wrapped_data)):
            with self.subTest(shape=name):
                out = self.run_cmd([dec('Bid change:3', 'approve')], live=shape)
                self.assertEqual([s['row_id'] for s in out['skipped']], ['Bid change:3'])

    def test_an_unreadable_live_file_is_refused(self):
        self.plan_run()
        path = os.path.join(self.tmp, 'bad.json')
        for text in ('{"nope": 1}', 'not json', '[1, 2]'):
            with self.subTest(text=text):
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(text)
                self.assertIn('--live', self.refused([dec('Bid change:6', 'approve')], live_file=path))
        self.assertIn('--live', self.refused([dec('Bid change:6', 'approve')], live_file=os.path.join(self.tmp, 'missing.json')))
        self.assertFalse(os.path.exists(self.approved_dir))

    def test_without_live_nothing_is_skipped_and_the_output_warns(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:3', 'approve')])
        self.assertIs(out['checked_live'], False)
        self.assertEqual(out['skipped'], [])
        self.assertEqual(out['approved'], 1)
        self.assertTrue(any('--live' in w for w in out['warnings']))
        self.assertIn('--live', self.stderr)

    def test_rows_with_no_live_id_are_not_checked_and_the_output_says_so(self):
        self.plan_run()
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE] + [dec('Bid change:3', 'approve')],
                           live=[dict(keywordId='3', bid=0.5, state='ENABLED'), dict(keywordId='2', bid=0.5, state='ENABLED')])
        self.assertEqual(out['skipped'], [])
        self.assertEqual(out['not_drift_checked'], {'New exact campaign': 1, 'Negative exact': 2})
        self.assertEqual(out['approved'], 1 + 2 + 1 + 1 + 1)  # the bid, the pause, two negatives, the campaign and its spec
        self.assertTrue(any('not checked' in w for w in out['warnings']))

    # --- R5: locks ------------------------------------------------------------------------------------------------
    def test_the_product_override_lock_weeks_wins(self):
        self.plan_run(auto=dict(T.AUTO, enabled=False, lock_weeks=2))
        self.run_cmd([dec('Bid change:1', 'decline')])
        self.assertEqual(self.locks()['Bid change:1']['until'], '2026-11-02')

    def test_a_missing_lock_weeks_is_refused(self):
        self.plan_run()
        self.shared['auto'] = {k: v for k, v in self.shared['auto'].items() if k != 'lock_weeks'}
        self.edit_product(auto={k: v for k, v in T.AUTO.items() if k != 'lock_weeks'})
        self.assertIn('lock_weeks', self.refused([dec('Bid change:1', 'approve')]))
        self.assertFalse(os.path.exists(self.approved_dir))

    def test_a_decision_without_a_date_locks_from_today_in_singapore(self):
        self.plan_run()
        e = dec('Bid change:1', 'decline')
        del e['at']
        self.run_cmd([e], now='2026-10-19T17:00:00Z')  # already the 20th in Singapore
        self.assertEqual((self.locks()['Bid change:1']['on'], self.locks()['Bid change:1']['until']), ('2026-10-20', '2026-11-17'))

    def test_a_decision_replaces_the_same_row_id_and_keeps_the_rest(self):
        self.plan_run()
        self.edit_product(decisions=[dict(id='Bid change:1', what='decline', by='Kim', until='2026-10-01'),
                                     dict(id='keep me', what='approve', by='Lee', until='2026-12-01')])
        self.run_cmd([dec('Bid change:1', 'decline', by='Lee'), dec('Bid change:3', 'decline')])
        self.run_cmd([dec('Bid change:1', 'decline', by='Lee'), dec('Bid change:3', 'decline')])  # twice: no duplicate
        ids = [d['id'] for d in self.product()['decisions']]
        self.assertEqual(sorted(ids), ['Bid change:1', 'Bid change:3', 'keep me'])
        self.assertEqual((self.locks()['Bid change:1']['by'], self.locks()['Bid change:1']['until']), ('Lee', '2026-11-16'))
        self.assertEqual(self.locks()['keep me'], dict(id='keep me', what='approve', by='Lee', until='2026-12-01'))

    def test_the_product_file_keeps_its_format(self):
        for indent in (1, 2):
            with self.subTest(indent=indent):
                self.plan_run()
                product = dict(self.product(), note='café, déjà vu')
                write_json(self.product_file, product, indent=indent)
                before = list(product)
                self.run_cmd([dec('Bid change:1', 'decline')])
                after = self.product()
                self.assertEqual(list(after), before + ['decisions'])  # key order kept, decisions at the end
                self.assertEqual({k: v for k, v in after.items() if k != 'decisions'}, product)
                with open(self.product_file, encoding='utf-8') as fh:
                    text = fh.read()
                self.assertEqual(text, json.dumps(after, indent=indent, ensure_ascii=False) + chr(10))
                self.assertIn('café, déjà vu', text)  # not escaped

    def test_an_unreadable_decisions_list_is_refused_and_nothing_is_written(self):
        self.plan_run()
        self.edit_product(decisions='garbage')
        before = self.raw_product()
        self.assertIn('decisions', self.refused([dec('Bid change:1', 'approve')]))
        self.assertFalse(os.path.exists(self.approved_dir))
        self.assertEqual(self.raw_product(), before)

    def test_a_dry_run_writes_nothing(self):
        self.plan_run()
        before = self.raw_product()
        out = self.run_cmd([dec('Bid change:1', 'approve')], dry_run=True)
        self.assertEqual(out['approved'], 1)
        self.assertIs(out['dry_run'], True)
        self.assertFalse(os.path.exists(self.approved_dir))
        self.assertEqual(self.raw_product(), before)

    # --- R6: output, stale files and the write window -------------------------------------------------------------
    def test_stale_files_in_approved_are_cleared(self):
        self.plan_run()
        os.makedirs(self.approved_dir)
        for name in ('4_bids_01.json', 'old_run.json'):
            write_json(os.path.join(self.approved_dir, name), [dict(type='sp_keywords', keywordId='999', bid=9.0)])
        write_json(os.path.join(self.approved_dir, 'rows.json'), {'4_bids_01.json': ['Bid change:99']})
        applied = os.path.join(self.run_dir, 'payloads', 'applied_rows.json')
        write_json(applied, {'Bid change:99': '2026-10-12'})  # `applied`'s record, beside the folders: never cleared
        self.run_cmd([dec('Pause target:301', 'approve')])  # what approved/ held went out and is recorded (C2)
        self.assertEqual(sorted(os.listdir(self.approved_dir)), ['9_target_pauses.json', 'rows.json'])
        self.assertEqual(read_json(os.path.join(self.approved_dir, 'rows.json')), {'9_target_pauses.json': ['Pause target:301']})
        # nothing approved this time (the pause did not go out): the payload files, rows.json and the approvals record are
        # cleared, none is written
        out = self.run_cmd([dec('Pause target:301', 'decline')], discard_unapplied=True)
        self.assertEqual(os.listdir(self.approved_dir), [])
        self.assertEqual(self.record(), {})
        self.assertEqual(read_json(applied), {'Bid change:99': '2026-10-12'})
        self.assertEqual((out['approved'], out['declined'], out['files']), (0, 1, {}))

    def test_no_approved_rows_writes_no_folder(self):
        self.plan_run()
        out = self.run_cmd([])
        self.assertFalse(os.path.exists(self.approved_dir))
        self.assertEqual((out['approved'], out['declined'], out['files']), (0, 0, {}))

    def test_write_window_open_on_a_sunday_vs_a_monday(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        self.assertEqual(self.plan['summary'][0]['apply_after'], '2026-10-19')
        # R1: a shut window refuses a real run (WriteWindowTest), so the flag is read from dry runs there
        out = self.run_cmd([dec('Bid change:1', 'approve')], now=SUN, dry_run=True)
        self.assertEqual((out['apply_after'], out['write_window_open']), ('2026-10-19', True))
        out = self.run_cmd([dec('Bid change:1', 'approve')], now=MON)
        self.assertEqual((out['apply_after'], out['write_window_open']), ('2026-10-19', True))
        out = self.run_cmd([dec('Bid change:1', 'approve')], now='2026-10-17T20:00:00Z', dry_run=True)  # a Saturday, before apply_after
        self.assertIs(out['write_window_open'], True)
        out = self.run_cmd([dec('Bid change:1', 'approve')], now='2026-10-20T15:00:00')  # naive times are read as UTC
        self.assertIs(out['write_window_open'], True)

    def test_a_plan_without_apply_after_runs_any_day(self):
        self.synthetic_run([bid_row('K1')], apply_after=None)
        out = self.run_cmd([dec('Bid change:K1', 'approve')], dry_run=True)  # R1: a real run is refused (WriteWindowTest)
        self.assertEqual((out['apply_after'], out['write_window_open']), (None, True))

    def test_approved_rows_with_no_payload_are_reported_not_dropped(self):
        stop = dict(type='Stop-loss review', row_id='Stop-loss review:::cards', keyword='cards', lane='human', current=None, new=None)
        self.synthetic_run([bid_row('K1'), stop])
        out = self.run_cmd([dec('Bid change:K1', 'approve'), dec('Stop-loss review:::cards', 'approve')])
        self.assertEqual(out['approved'], 1)
        self.assertEqual(out['no_payload'], [dict(row_id='Stop-loss review:::cards', type='Stop-loss review')])
        self.assertEqual(out['approved_rows'], 2)
        self.assertEqual(self.locks(), {})  # B4: an approval locks only once `applied` records it, and a manual row never is

    def test_a_pause_with_no_keyword_id_has_no_payload(self):
        pause = dict(type='Pause keyword', row_id='Pause keyword:C1:A1:cards', keyword='cards', match='exact', keyword_id=None,
                     campaign_id='C1', ad_group_id='A1', lane='human', current=0.4, new=None)
        self.synthetic_run([pause])
        out = self.run_cmd([dec('Pause keyword:C1:A1:cards', 'approve')], live=[])
        self.assertEqual((out['approved'], out['skipped']), (0, []))
        self.assertEqual([r['row_id'] for r in out['no_payload']], ['Pause keyword:C1:A1:cards'])

    def test_a_large_server_history_is_summarised_not_listed(self):
        self.plan_run()
        old = [dec(f'Bid change:{n}', 'approve', item_id='bids-2026-09-21') for n in range(300)]
        out = self.run_cmd(old + [dec('Bid change:1', 'approve')])
        (group,) = out['ignored']
        self.assertEqual((group['item_id'], group['count']), ('bids-2026-09-21', 300))
        self.assertNotIn('row_ids', group)  # other items' rows are expected history, not something to chase

    def test_malformed_server_entries_are_ignored(self):
        self.plan_run()
        out = self.run_cmd(['nope', dec('Bid change:1', 'maybe'), dict(row_id='Bid change:3', item_id=ITEM), dec('Bid change:5', 'approve')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['5'])
        self.assertEqual(sum(g['count'] for g in out['ignored']), 3)

    def test_the_server_answering_with_something_else_is_refused(self):
        self.plan_run()
        self.assertIn('/api/reviews', self.refused({'error': 'x'}))
        self.assertFalse(os.path.exists(self.approved_dir))

    def test_the_command_is_wired_into_the_cli(self):
        self.plan_run()
        argv = ['dashboard.py', 'approvals', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--now', MON]
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), \
                unittest.mock.patch.object(dashboard, 'call', return_value=resolve(self.plan, [dec('Bid change:1', 'approve')])), \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            dashboard.main()
        self.assertEqual(json.loads(out.getvalue())['approved'], 1)
        self.assertEqual(list(self.approved_files()), ['4_bids_01.json'])

    def test_enabled_mode_item_works_the_same(self):
        # since autonomous runs (2026-10-22) the enabled fixture's rows apply on their own; a one-word search's promotion
        # and its bundle are the rows for a person (decision 107; a $15 budget override was until 2026-10-23)
        plan = self.plan_run(shadow=False, run=T.HEAD_TERM)
        item = plan['human_review'][-1]
        human = [x['row_id'] for x in plan['changes'] if x['lane'] == 'human']
        self.assertIn(HEAD_PROMOTION, human)
        self.assertEqual(sorted(r['row_id'] for r in item['rows']), sorted(human))
        out = self.run_cmd([dec(rid, 'approve') for rid in human] + [dec('Bid change:1', 'approve')])
        self.assertIn('1_new_campaigns.json', self.approved_files())  # Bid change:1 is not on the enabled item
        self.assertEqual(out['approved_rows'], len(human))
        self.assertEqual([g['row_ids'] for g in out['ignored']], [['Bid change:1']])


# =====================================================================================================================
class CappedBidsTest(Base):
    def test_an_approved_row_with_a_cap_is_written_at_the_cap(self):
        plan = self.plan_run()
        row = next(x for x in plan['changes'] if x['row_id'] == 'Bid change:4')
        # keyword 4 bids its breakeven (a Discovery keyword; decision 157, 85% under decision 139), $0.62, past the +25% cap
        self.assertEqual((row['current'], row['new'], row['new_capped']), (0.3, 0.62, 0.37))
        out = self.run_cmd([dec('Bid change:4', 'approve'), dec('Target bid change:302', 'approve'), dec('Bid change:1', 'approve')])
        files = self.approved_files()
        self.assertEqual({r['keywordId']: r['bid'] for r in files['4_bids_01.json']}, {'4': 0.37, '1': 0.98})
        self.assertEqual({r['targetId']: r['bid'] for r in files['9_target_bids_01.json']}, {'302': 0.37})
        self.assertEqual(sorted(out['capped'], key=lambda c: c['row_id']),
                         [dict(row_id='Bid change:4', proposed=0.62, applied=0.37),
                          dict(row_id='Target bid change:302', proposed=0.74, applied=0.37)])
        self.assertEqual(read_json(os.path.join(self.run_dir, 'plan.json')), self.plan)  # the plan row itself is not changed

    def test_a_capped_row_held_back_is_not_reported_as_capped(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:4', 'approve')], live=[dict(keywordId='4', bid=0.5, state='ENABLED')])
        self.assertEqual((out['capped'], out['approved']), ([], 0))

    def test_approved_payloads_applies_the_cap_without_touching_the_plan(self):
        plan = self.synthetic_run([bid_row('K1', current=0.30, new=0.62, new_capped=0.37), bid_row('K2', current=0.30, new=0.35)])
        before = json.dumps(plan, sort_keys=True)
        files, skipped = dashboard.approved_payloads(
            plan, resolve(plan, [dec('Bid change:K1', 'approve'), dec('Bid change:K2', 'approve')]), None, self.shared, ASIN)
        self.assertEqual(files, {'4_bids_01.json': [dict(type='sp_keywords', keywordId='K1', bid=0.37),
                                                    dict(type='sp_keywords', keywordId='K2', bid=0.35)]})
        self.assertEqual(json.dumps(plan, sort_keys=True), before)

    def test_enabled_mode_reports_no_caps(self):
        self.plan_run(shadow=False, run=T.HEAD_TERM)
        out = self.run_cmd([dec(HEAD_PROMOTION, 'approve')])
        self.assertEqual(out['capped'], [])


# =====================================================================================================================
class ApprovalLevelsTest(Base):
    """R9: an approval counts only when its signer may give it (the row's approval_required, from the sweep playbook)."""

    rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
    LEVELS = {'Bid change:O': 'owner', 'Bid change:M': 'Lee', 'Bid change:K': 'Kim'}

    def setUp(self):
        super().setUp()
        self.synthetic_run([bid_row('O'), bid_row('M'), bid_row('K')], levels=self.LEVELS)

    def sent(self):
        return sorted(r['keywordId'] for r in self.approved_files().get('4_bids_01.json', []))

    def test_an_owner_row_accepts_any_signed_person(self):
        for who in ('Bob', 'lee', 'KIM'):
            with self.subTest(by=who):
                out = self.run_cmd([dec('Bid change:O', 'approve', by=who)])
                self.assertEqual((self.sent(), out['skipped']), (['O'], []))

    def test_a_lee_row_needs_lee_or_kim(self):
        # since 2026-10-22 no bid row starts at Lee's level: an item row says Lee when she declined it (propose_bids)
        out = self.run_cmd([dec('Bid change:M', 'approve', by='Bob')])  # an owner approving a Lee row
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:M', reason="needs Lee's approval (approved by Bob)")])
        self.assertEqual((self.sent(), out['approved']), ([], 0))
        self.assertNotIn('Bid change:M', self.locks())  # held back: no lock, so next week's plan has it again
        for who in ('Lee', ' lee  ', 'Kim', 'KIM'):
            with self.subTest(by=who):
                out = self.run_cmd([dec('Bid change:M', 'approve', by=who)])
                self.assertEqual((self.sent(), out['skipped']), (['M'], []))
                self.assertEqual(self.record()['Bid change:M']['by'], who.strip())

    def test_a_kim_row_needs_kim(self):
        for who in ('Bob', 'Lee', 'Kim Park'):
            with self.subTest(by=who):
                out = self.run_cmd([dec('Bid change:K', 'approve', by=who)])
                self.assertEqual(out['skipped'], [dict(row_id='Bid change:K', reason=f"needs Kim's approval (approved by {who})")])
                self.assertEqual((self.sent(), self.locks()), ([], {}))
        for who in ('Kim', ' kim', 'KIM '):
            with self.subTest(by=who):
                out = self.run_cmd([dec('Bid change:K', 'approve', by=who)])
                self.assertEqual((self.sent(), out['skipped']), (['K'], []))

    def test_a_decline_from_anyone_is_honoured_and_locks(self):
        out = self.run_cmd([dec('Bid change:K', 'decline', by='Bob'), dec('Bid change:M', 'decline', by='Bob')])
        self.assertEqual((out['declined'], out['skipped'], self.sent()), (2, [], []))
        self.assertEqual({k: v['what'] for k, v in self.locks().items()}, {'Bid change:K': 'decline', 'Bid change:M': 'decline'})

    def test_an_approval_that_cannot_count_does_not_cancel_one_that_can(self):
        out = self.run_cmd([dec('Bid change:M', 'approve', by='Lee', at='2026-10-19T02:00:00Z'),
                            dec('Bid change:M', 'approve', by='Bob', at='2026-10-19T03:00:00Z')])
        self.assertEqual((self.sent(), out['skipped']), (['M'], []))
        self.assertEqual(self.record()['Bid change:M']['by'], 'Lee')
        # and it doesn't undo a decline either: the decline stands (F: and the approval is listed as held, with who declined)
        out = self.run_cmd([dec('Bid change:K', 'decline', by='Kim', at='2026-10-19T02:00:00Z'),
                            dec('Bid change:K', 'approve', by='Bob', at='2026-10-19T03:00:00Z')])
        self.assertEqual((out['declined'], self.locks()['Bid change:K']['what']), (1, 'decline'))
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:K', reason=(
            "declined by Kim; needs Kim's approval to change it (approved by Bob)"))])

    def test_a_real_bundle_is_the_book_owners(self):
        # Kim, 2026-10-22: a promotion and its bundle are the book owner's to approve (decision 99: whatever it spends)
        plan = self.plan_run()
        item = next(i for i in plan['human_review'] if i['kind'] == 'bid')
        self.assertEqual({r['approval_required'] for r in item['rows'] if r['row_id'] in BUNDLE}, {'owner'})
        out = self.run_cmd([dec(r, 'approve', by='Bob') for r in BUNDLE])
        self.assertEqual(out['skipped'], [])
        self.assertIn('1_new_campaigns.json', self.approved_files())
        self.assertEqual({self.record()[r]['by'] for r in BUNDLE}, {'Bob'})

    def test_a_real_bundle_approved_by_the_wrong_signer_is_held_whole(self):
        # until 2026-10-22 a guide of $1 made the bundle Kim's (his $600 level, gone with decision 99); here one row of the
        # stored item asks for Kim's approval and Bob signs it
        self.plan_run()
        for r in bids_rows(self.plan):
            if r['row_id'] == BUNDLE[3]:
                r['approval_required'] = 'Kim'
        write_json(os.path.join(self.run_dir, 'plan.json'), self.plan)
        out = self.run_cmd([dec(r, 'approve', by='Kim') for r in BUNDLE[:3]] + [dec(BUNDLE[3], 'approve', by='Bob')])
        self.assertEqual(self.approved_files(), {})
        reasons = {s['row_id']: s['reason'] for s in out['skipped']}
        self.assertEqual(set(reasons), set(BUNDLE))
        self.assertEqual(reasons[BUNDLE[3]], "needs Kim's approval (approved by Bob)")
        self.assertEqual({reasons[r] for r in BUNDLE[:3]}, {"part of a promotion that isn't fully approved: blank cards"})
        self.assertEqual(set(self.locks()) & set(BUNDLE), set())

    def test_a_declined_row_is_approved_again_only_at_the_decliners_level(self):
        """E3 (I3): a row a decline holds is approved again only by a signer at its own level and at the decliner's (Kim
        when Kim declined, Lee when Lee did). approvals checks it from the plan's change row, so a plan whose item
        row still says 'owner' (made before E3) is held the same way."""
        declined = dict(locked_until='2026-11-16', decision='decline', decided_on='2026-10-20')
        self.synthetic_run([bid_row('A', decided_by='Lee', **declined), bid_row('B', decided_by='Kim', **declined),
                            bid_row('C', decided_by='Sam', **declined)])  # every item row says 'owner'
        out = self.run_cmd([dec('Bid change:A', 'approve', by='Sam'), dec('Bid change:B', 'approve', by='Lee'),
                            dec('Bid change:C', 'approve', by='Bob')])
        self.assertEqual(out['skipped'], [
            dict(row_id='Bid change:A', reason="needs Lee's approval: Lee declined it (approved by Sam)"),
            dict(row_id='Bid change:B', reason="needs Kim's approval: Kim declined it (approved by Lee)")])
        self.assertEqual(self.sent(), ['C'])  # an owner's decline: any signed person
        out = self.run_cmd([dec('Bid change:A', 'approve', by=' lee '), dec('Bid change:B', 'approve', by='Kim')])
        self.assertEqual((out['skipped'], self.sent()), ([], ['A', 'B']))

    def test_a_decline_on_the_same_item_is_overturned_only_at_the_decliners_level(self):
        """F: within one item a later approval replaces an earlier decline on the row only when its signer ranks at least as
        high as the decliner (Kim > Lee > owner) and meets the row's own level. Below that the decline stands (and
        its lock is written), the approval is held, and the row is listed with who declined it."""
        for row, decliner, approver, level in (('O', 'Lee', 'Sam', 'Lee'), ('O', 'Kim', 'Lee', 'Kim'),
                                               ('O', ' kim ', 'Bob', 'Kim'), ('M', 'Sam', 'Sam', 'Lee'),
                                               ('K', 'Lee', 'Lee', 'Kim'), ('K', 'Kim', 'Bob', 'Kim')):
            with self.subTest(row=row, decliner=decliner, approver=approver):
                self.edit_product(decisions=[])
                out = self.run_cmd([dec(f'Bid change:{row}', 'decline', by=decliner, at='2026-10-19T02:00:00Z'),
                                    dec(f'Bid change:{row}', 'approve', by=approver, at='2026-10-19T03:00:00Z')])
                self.assertEqual(out['skipped'], [dict(row_id=f'Bid change:{row}', reason=(
                    f"declined by {decliner.strip()}; needs {level}'s approval to change it (approved by {approver})"))])
                self.assertEqual((self.sent(), out['approved'], out['declined']), ([], 0, 1))
                lock = self.locks()[f'Bid change:{row}']
                self.assertEqual((lock['what'], lock['by']), ('decline', decliner.strip()))
        for row, decliner, approver in (('O', 'Lee', 'Lee'), ('O', 'Lee', ' KIM'), ('O', 'Sam', 'Sam'),
                                        ('O', 'Sam', 'Bob'), ('M', 'Lee', 'Lee'), ('M', 'Lee', 'Kim'),
                                        ('K', 'Kim', 'Kim'), ('K', 'Lee', 'Kim')):
            with self.subTest(row=row, decliner=decliner, approver=approver, goes=True):
                self.edit_product(decisions=[])
                out = self.run_cmd([dec(f'Bid change:{row}', 'decline', by=decliner, at='2026-10-19T02:00:00Z'),
                                    dec(f'Bid change:{row}', 'approve', by=approver, at='2026-10-19T03:00:00Z')])
                self.assertEqual((self.sent(), out['skipped'], out['declined']), ([row], [], 0))
                self.assertNotIn(f'Bid change:{row}', self.locks())  # no decline lock: the decline was reversed

    def test_the_latest_counting_decision_on_the_item_wins_around_a_held_approval(self):
        """F: a later decline from anyone replaces an earlier approval, and a held approval is no decision: it does not
        undo the decline before it, and it is forgotten once a decision after it settles the row."""
        row = 'Bid change:O'
        cases = (
            # the decline Lee's level holds, then Sam's approval (held), then Sam declines: G2, his lower decline doesn't
            # replace hers, so hers still stands (and names the lock); the held approval is stale, and the row is not listed
            ([('Lee', 'decline'), ('Sam', 'approve'), ('Sam', 'decline')], ([], [], 'Lee')),
            # ... and so Sam's own approval after it is still held (G2: fix F let it through)
            ([('Lee', 'decline'), ('Sam', 'approve'), ('Sam', 'decline'), ('Sam', 'approve')],
             ([], ["declined by Lee; needs Lee's approval to change it (approved by Sam)"], 'Lee')),
            # Kim's later approval settles it, and the held one before it is not listed
            ([('Lee', 'decline'), ('Sam', 'approve'), ('Kim', 'approve')], (['O'], [], None)),
            # an approval, then anyone's decline: a decline always replaces an approval
            ([('Kim', 'approve'), ('Sam', 'decline')], ([], [], 'Sam')),
            # a held approval, then Lee approves her own decline away
            ([('Lee', 'decline'), ('Sam', 'approve'), ('Lee', 'approve')], (['O'], [], None)),
            # two held approvals: the row is listed once, with the last one's signer
            ([('Kim', 'decline'), ('Sam', 'approve'), ('Lee', 'approve')],
             ([], ["declined by Kim; needs Kim's approval to change it (approved by Lee)"], 'Kim')))
        for n, (steps, (sent, reasons, locked_by)) in enumerate(cases):
            with self.subTest(case=n):
                self.edit_product(decisions=[])
                entries = [dec(row, what, by=by, at=f'2026-10-19T0{i + 1}:00:00Z') for i, (by, what) in enumerate(steps)]
                out = self.run_cmd(entries)
                self.assertEqual((self.sent(), [s['reason'] for s in out['skipped']]), (sent, reasons))
                lock = self.locks().get(row)
                self.assertEqual(lock['by'] if lock else None, locked_by)
        # an approval listed after the decline but made before it is not a later approval: it is not listed as held
        self.edit_product(decisions=[])
        out = self.run_cmd([dec(row, 'decline', by='Lee', at='2026-10-19T03:00:00Z'),
                            dec(row, 'approve', by='Sam', at='2026-10-19T02:00:00Z')])
        self.assertEqual((self.sent(), out['skipped'], self.locks()[row]['by']), ([], [], 'Lee'))

    def test_the_highest_ranked_decline_on_the_item_sets_the_bar(self):
        """G2 (N2): a later, lower-ranked decline never replaces an earlier, higher one. The higher decline stays the row's
        decision (its lock names that decliner), and an approval needs that decliner's rank. An equal or higher decline
        after it does replace it."""
        row = 'Bid change:O'
        cases = (
            ([('Lee', 'decline'), ('Sam', 'decline'), ('Sam', 'approve')],
             ([], ["declined by Lee; needs Lee's approval to change it (approved by Sam)"], 'Lee')),
            ([('Kim', 'decline'), ('Lee', 'decline'), ('Lee', 'approve')],
             ([], ["declined by Kim; needs Kim's approval to change it (approved by Lee)"], 'Kim')),
            ([('Lee', 'decline'), ('Sam', 'decline'), ('Lee', 'approve')], (['O'], [], None)),
            ([('Kim', 'decline'), ('Sam', 'decline'), (' lee ', 'decline')], ([], [], 'Kim')),
            # a higher decline after a lower one replaces it, and an equal one too (the later of the two names the lock)
            ([('Sam', 'decline'), ('Lee', 'decline'), ('Sam', 'approve')],
             ([], ["declined by Lee; needs Lee's approval to change it (approved by Sam)"], 'Lee')),
            ([('Bob', 'decline'), ('Sam', 'decline')], ([], [], 'Sam')),
            # a counting approval clears the bar: a lower decline after it is the one that stands
            ([('Kim', 'decline'), ('Kim', 'approve'), ('Sam', 'decline'), ('Sam', 'approve')], (['O'], [], None)))
        for n, (steps, (sent, reasons, locked_by)) in enumerate(cases):
            with self.subTest(case=n):
                self.edit_product(decisions=[])
                entries = [dec(row, what, by=by, at=f'2026-10-19T0{i + 1}:00:00Z') for i, (by, what) in enumerate(steps)]
                out = self.run_cmd(entries)
                self.assertEqual((self.sent(), [s['reason'] for s in out['skipped']]), (sent, reasons))
                lock = self.locks().get(row)
                self.assertEqual(lock['by'] if lock else None, locked_by)

    def test_a_lower_decline_on_a_row_a_higher_decline_holds_keeps_the_higher_decliner_on_its_lock(self):
        """G2 (N2), across weeks: the plan holds the row by Kim's decline from an earlier week (decided_by Kim). Lee
        declines it again on this week's item. The lock approvals writes still names Kim (on the day he declined), and
        holds from Lee's decline, so next week's plan still asks for Kim."""
        held = dict(locked_until='2026-11-09', decision='decline', decided_on='2026-10-12')
        self.synthetic_run([bid_row('A', decided_by='Kim', **held), bid_row('B', decided_by='Sam', **held),
                            bid_row('C', decided_by='Lee', **held)])
        out = self.run_cmd([dec('Bid change:A', 'decline', by='Lee', at='2026-10-20T02:00:00Z'),
                            dec('Bid change:B', 'decline', by='Lee', at='2026-10-20T02:00:00Z'),
                            dec('Bid change:C', 'decline', by='Lee', at='2026-10-20T02:00:00Z')])
        self.assertEqual(out['declined'], 3)
        locks = {rid: (d['by'], d['on'], d['until']) for rid, d in self.locks().items()}
        self.assertEqual(locks, {'Bid change:A': ('Kim', '2026-10-12', '2026-11-17'),     # Kim's decline still sets the bar
                                 'Bid change:B': ('Lee', '2026-10-20', '2026-11-17'),   # a higher decline replaces Sam's
                                 'Bid change:C': ('Lee', '2026-10-20', '2026-11-17')})  # her own again
        # her approval after her own decline on this item still meets Kim's bar on row A, and the reason names him
        out = self.run_cmd([dec('Bid change:A', 'decline', by='Lee', at='2026-10-20T02:00:00Z'),
                            dec('Bid change:A', 'approve', by='Lee', at='2026-10-20T03:00:00Z')])
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:A', reason=(
            "declined by Kim; needs Kim's approval to change it (approved by Lee)"))])
        self.assertEqual(self.locks()['Bid change:A']['by'], 'Kim')

    def test_a_row_with_no_readable_level_needs_kim(self):
        plan = self.synthetic_run([bid_row('X')])
        plan['human_review'][0]['rows'][0].pop('approval_required')  # a hand-edited plan: fail safe, to the highest level
        files, skipped = dashboard.approved_payloads(plan, resolve(plan, [dec('Bid change:X', 'approve', by='Lee')]), None,
                                                     self.shared, ASIN)
        self.assertEqual((files, [s['reason'] for s in skipped]), ({}, ["needs Kim's approval (approved by Lee)"]))


# =====================================================================================================================
class AlreadyAppliedTest(Base):
    """`applied` writes <run>/payloads/applied_rows.json (M8: it replaced payloads/approved/applied.json); approvals never
    does, and never re-emits what it lists."""

    def applied_file(self):
        return os.path.join(self.run_dir, 'payloads', 'applied_rows.json')

    def mark_applied(self, row_ids, applied_on='2026-10-19'):
        write_json(self.applied_file(), {rid: applied_on for rid in row_ids})

    def raw_applied(self):
        with open(self.applied_file(), 'rb') as fh:
            return fh.read()

    def test_an_applied_row_is_skipped_without_a_new_lock(self):
        self.plan_run()
        old = dict(id='Bid change:1', what='approve', by='Lee', until='2026-11-16')
        self.edit_product(decisions=[old])
        self.mark_applied(['Bid change:1'])
        before = self.raw_applied()
        out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve')])
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:1', reason='already applied on 2026-10-19')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['3'])
        self.assertEqual(self.locks()['Bid change:1'], old)  # the lock from when it was applied stays as it was
        self.assertEqual(self.raw_applied(), before)  # approvals never writes, changes or clears it
        self.assertEqual(out['approved_rows'], 1)

    def test_a_bundle_with_one_applied_member_is_skipped_whole_and_never_re_emitted(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        everything = [dec(r, 'approve') for r in BUNDLE]
        self.run_cmd(everything)
        self.assertIn('1_new_campaigns.json', self.approved_files())  # before anything is applied, it goes out
        self.edit_product(decisions=[])
        for applied in (['Pause keyword:2'], [BUNDLE[0]], BUNDLE):
            with self.subTest(applied=applied):
                self.mark_applied(applied, applied_on='2026-10-20')
                out = self.run_cmd(everything)
                self.assertEqual(self.approved_files(), {})  # no campaign, spec, pause or negative again
                self.assertEqual({s['row_id'] for s in out['skipped']}, set(BUNDLE))
                reasons = {s['row_id']: s['reason'] for s in out['skipped']}
                for rid in BUNDLE:
                    self.assertIn('applied on 2026-10-20', reasons[rid])
                self.assertEqual(reasons[applied[0]], 'already applied on 2026-10-20')
                self.assertEqual((out['approved'], out['approved_rows'], self.locks()), (0, 0, {}))

    def test_declines_still_lock_when_the_row_was_applied(self):
        self.plan_run()
        self.mark_applied(['Bid change:1'])
        out = self.run_cmd([dec('Bid change:1', 'decline')])
        self.assertEqual((out['declined'], out['skipped']), (1, []))
        self.assertEqual(self.locks()['Bid change:1']['what'], 'decline')

    def test_rows_not_in_applied_json_go_out_as_before(self):
        self.plan_run()
        self.mark_applied(['Bid change:99', 'something else'])
        out = self.run_cmd([dec('Bid change:1', 'approve')])
        self.assertEqual((out['approved'], out['skipped']), (1, []))

    def test_an_unreadable_applied_json_is_refused_and_nothing_is_written(self):
        self.plan_run()
        os.makedirs(self.approved_dir)
        stale = os.path.join(self.approved_dir, '4_bids_01.json')
        write_json(stale, [])
        before = self.raw_product()
        for text in ('not json', '[]', '{"applied_on": "2026-10-19", "row_ids": ["Bid change:1"]}', '{"Bid change:1": 5}',
                     '{"Bid change:1": "2026-13-45"}', '{"Bid change:1": ["2026-10-19"]}'):
            with self.subTest(text=text):
                with open(self.applied_file(), 'w', encoding='utf-8') as fh:
                    fh.write(text)
                self.assertIn('applied_rows.json', self.refused([dec('Bid change:1', 'approve')]))
                self.assertTrue(os.path.exists(stale))
                self.assertEqual(self.raw_product(), before)
                self.call.assert_not_called()

    def test_approved_payloads_takes_the_applied_rows(self):
        plan = self.synthetic_run([bid_row('K1'), bid_row('K2')])
        files, skipped = dashboard.approved_payloads(
            plan, resolve(plan, [dec('Bid change:K1', 'approve'), dec('Bid change:K2', 'approve')]), None, self.shared, ASIN,
            applied={'Bid change:K1': '2026-10-19'})
        self.assertEqual([r['keywordId'] for r in files['4_bids_01.json']], ['K2'])
        self.assertEqual(skipped, [dict(row_id='Bid change:K1', reason='already applied on 2026-10-19')])


# =====================================================================================================================
class DecisionEntryTest(Base):
    def test_unsigned_decisions_are_ignored_and_grouped(self):
        self.plan_run()
        missing = dec('Bid change:6', 'approve')
        del missing['by']
        out = self.run_cmd([dec('Bid change:1', 'approve', by=''), dec('Bid change:3', 'approve', by=None),
                            dec('Bid change:4', 'approve', by='   '), missing, dec('Bid change:5', 'approve', by='Lee')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['5'])
        (group,) = out['ignored']
        self.assertEqual((group['item_id'], group['reason'], group['count']), (ITEM, 'unsigned decision', 4))
        self.assertEqual(group['row_ids'], ['Bid change:1', 'Bid change:3', 'Bid change:4', 'Bid change:6'])
        self.assertEqual(list(self.record()), ['Bid change:5'])  # an unsigned decision counts for nothing

    def test_an_unsigned_entry_does_not_replace_a_signed_one(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve', by='Lee'), dec('Bid change:1', 'decline', by='')])
        self.assertEqual((self.record()['Bid change:1']['by'], self.locks()), ('Lee', {}))
        self.run_cmd([dec('Bid change:1', 'decline', by='Lee'), dec('Bid change:1', 'approve', by='')])
        self.assertEqual(self.locks()['Bid change:1']['what'], 'decline')

    def test_an_unparseable_time_falls_back_to_today_in_singapore_and_to_list_order(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'decline', at='not a date')], now='2026-10-19T17:00:00Z')  # the 20th in Singapore
        self.assertEqual(self.locks()['Bid change:1']['until'], '2026-11-17')
        out = self.run_cmd([dec('Bid change:3', 'approve', at='2026-10-19T09:00:00Z'), dec('Bid change:3', 'decline', at='garbage')])
        self.assertEqual(self.locks()['Bid change:3']['what'], 'decline')  # no time to compare: the list order decides
        self.assertEqual(out['declined'], 1)


# =====================================================================================================================
def promo(search, spend, opportunity, lane='human', **kw):
    """A promotion row as plan_lanes leaves it: its modelled monthly spend and its opportunity."""
    return dict(type='New exact campaign', row_id=f'New exact campaign:::{search}', keyword=search, role='Invest',
                campaign=f'Cards - {ASIN} - Exact SKC - {search}', budget=10, tos=0, current=None, new=0.7, lane=lane,
                opportunity=opportunity, modelled_spend_month=spend, **kw)


def member(search):
    return dict(type='Negative exact', row_id=f'Negative exact:101:201:{search}', keyword=search, campaign='STW',
                campaign_id='101', ad_group_id='201', lane='human')


def business(search, kid, spend, opportunity, **kw):
    """A Business invest row of B2B campaign 108 as plan_lanes leaves it: its own modelled monthly spend and its
    opportunity (the head of the campaign's business invests also carries group_spend_month, ruling 6)."""
    return dict(type='Business invest', row_id=f'Business invest:{kid}', keyword=search, keyword_id=kid, role='Invest',
                campaign='Cards - B2B Exact', campaign_id='108', ad_group_id='208', owner_kind='business', current=1.0,
                new=1.2, tos=50, budget=10, budget_now=10, campaign_tos=50, campaign_budget=10, lane='human',
                opportunity=opportunity, modelled_spend_month=spend, **kw)


def bids_rows(plan):
    return next(i for i in plan['human_review'] if i['kind'] == 'bid')['rows']


class NoMoneyLevelTest(Base):
    """B1 (C2) held an approved promotion that took the product past Kim's $600 a month unless Kim signed it. Kim,
    2026-10-22, decision 99: "we don't want to put a cap and hamper the autonomous engine. if spend is overboard, the
    humans will notice it and step in anyway." Approvals hold no promotion for money: an approval at the row's own level
    sends it, whatever it spends and whatever the product already invests."""

    def promos(self, changes, start=400.0, shadow=True, **product_over):
        plan = self.synthetic_run(changes, levels={c['row_id']: 'Lee' for c in changes}, **product_over)
        plan['summary'][0].update(planned_invest_month_start=start, shadow=shadow)
        if start is None:
            del plan['summary'][0]['planned_invest_month_start']
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        return plan

    def sent(self):
        return sorted(r['keyword'] for r in self.approved_files().get('1b_new_skc_specs.json', []))

    def test_approved_promotions_go_out_whatever_they_spend(self):
        self.promos([promo('a', 1500, 1000), promo('b', 900, 500)], start=1900.0)   # $4,300 a month after both
        out = self.run_cmd([dec('New exact campaign:::a', 'approve'), dec('New exact campaign:::b', 'approve')])
        self.assertEqual((self.sent(), out['skipped']), (['a', 'b'], []))
        self.assertFalse(hasattr(dashboard, 'hold_past_kim'))
        self.assertFalse(hasattr(dashboard, 'kim_month'))

    def test_unknown_numbers_hold_nothing(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        for over in (dict(changes=[promo('a', None, 1000)]), dict(changes=[promo('a', 50, 1000)], start=None)):
            with self.subTest(over=over):
                self.promos(**over)
                out = self.run_cmd([dec('New exact campaign:::a', 'approve')])
                self.assertEqual((self.sent(), out['skipped']), (['a'], []))

    def test_only_what_is_approved_goes_out(self):
        self.promos([promo('a', 150, 1000), promo('b', 100, 500)])
        out = self.run_cmd([dec('New exact campaign:::a', 'decline'), dec('New exact campaign:::b', 'approve')])
        self.assertEqual((self.sent(), out['skipped']), (['b'], []))

    def test_a_promotion_and_its_bundle_go_out_together(self):
        self.promos([promo('a', 2500, 1000), member('a')])
        rows = ['New exact campaign:::a', 'Negative exact:101:201:a']
        out = self.run_cmd([dec(r, 'approve') for r in rows])
        self.assertEqual((self.sent(), out['skipped']), (['a'], []))
        self.assertEqual(list(self.approved_files()), ['1_new_campaigns.json', '1b_new_skc_specs.json', '6_negatives_01.json'])

    def test_a_held_monitor_promotion_in_shadow_is_an_agreement_not_a_spend(self):
        self.promos([promo('a', 150, 1000, lane='monitor'), promo('b', 100, 500)])
        out = self.run_cmd([dec('New exact campaign:::a', 'approve'), dec('New exact campaign:::b', 'approve')])
        self.assertEqual((self.sent(), out['skipped'], out['agreed_held']), (['b'], [], ['New exact campaign:::a']))

    def test_a_campaign_s_business_invests_go_out_with_their_approvals(self):      # ruling 6 (approvals)
        rows = ['Business invest:902', 'Business invest:908', 'New exact campaign:::c']
        changes = [business('zebra cards', '902', 10, 1000, group_spend_month=30), business('office cards', '908', 20, 100),
                   promo('c', 40, 500)]
        self.promos(changes, start=1990.0)
        out = self.run_cmd([dec(r, 'approve') for r in rows])
        self.assertEqual(out['skipped'], [])
        self.assertEqual(sorted(r['keywordId'] for r in self.approved_files()['4_bids_01.json']), ['902', '908'])
        self.assertEqual(self.sent(), ['c'])

    def test_the_real_fixtures_promotion_goes_out(self):
        plan = self.plan_run()
        blank = next(x for x in plan['changes'] if x['row_id'] == BUNDLE[0])
        self.assertNotIn('past_kim_level', blank)
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        self.assertEqual(out['skipped'], [])
        self.assertIn('1_new_campaigns.json', self.approved_files())


# =====================================================================================================================
class BusinessInvestCardTest(Base):
    """Ruling 19 (final review I3, 2026-10-21): a business invest row's card shows the top of search and budget its
    campaign update writes (campaign_tos, campaign_budget), not its own role's, and an approval of what the card showed is
    checked against the same values, so it never fails as re-planned."""

    def test_a_mixed_group_s_prove_first_row_shows_and_passes_on_its_campaign_s_values(self):
        # office cards (Prove first, its own +30% and $10) rides zebra cards' Invest (+50%, a $25 budget override) in campaign
        # 108: the campaign update writes +50% and $25, so that is what the office cards card shows; the live values stay
        head = business('zebra cards', '902', 10, 1000, group_spend_month=30, tos_now=0)
        head.update(budget=25, campaign_budget=25)
        prove = business('office cards', '908', 20, 100, tos_now=0)
        prove.update(role='Prove first', tos=30, campaign_budget=25)
        changes = [head, prove]
        card = {c['row_id']: human_review._bid_row(c, 'Lee') for c in changes}
        self.assertEqual({k: card['Business invest:908'][k] for k in ('tos_now', 'tos', 'budget_now', 'budget')},
                         dict(tos_now=0, tos=50, budget_now=10, budget=25))
        plan = self.synthetic_run(changes, levels={c['row_id']: 'Lee' for c in changes})
        plan['summary'][0].update(planned_invest_month_start=0.0)
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        out = self.run_cmd([dec(rid, 'approve', seen={k: row.get(k) for k in dashboard.SEEN_KEYS}) for rid, row in card.items()])
        self.assertEqual((out['approved_rows'], out['skipped']), (2, []))
        self.assertEqual(sorted(r['keywordId'] for r in self.approved_files()['4_bids_01.json']), ['902', '908'])
        [update] = self.approved_files()['5_campaign_updates.json']
        self.assertEqual(update['budget'], dict(budget=25, budgetType='DAILY'))
        # what the row's own role says (+30%) is not what goes out, so an approval that saw it is re-planned
        own = dict({k: card['Business invest:908'].get(k) for k in dashboard.SEEN_KEYS}, tos=30)
        self.rerun_as_unapplied = True
        out = self.run_cmd([dec('Business invest:908', 'approve', seen=own)])
        self.assertEqual({x['row_id']: x['reason'] for x in out['skipped']}['Business invest:908'],
                         're-planned since it was approved (saw top of search 30%, now top of search 50%)')


# =====================================================================================================================
class MonitorAgreementTest(Base):
    """B6 (I7): in a shadow run, agreeing with a row the planner holds (monitor) means "keep holding", not "apply"."""

    def test_agreeing_with_a_held_row_in_shadow_writes_nothing(self):
        # a refused cut on the same keyword doesn't hold this raise (a different move), and agreeing to hold the raise
        # must not release that refusal either
        stale = dict(id='Bid change:6', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        plan = self.plan_run(decisions=[stale])
        row = next(x for x in plan['changes'] if x['row_id'] == 'Bid change:6')
        self.assertEqual((row['lane'], row['current'], row['new']), ('monitor', 0.4, 0.5))
        self.assertNotIn('locked_until', row)
        out =self.run_cmd([dec('Bid change:6', 'approve'), dec('Bid change:1', 'approve')],
                           live=[dict(keywordId='6', bid=0.55, state='ENABLED'), dict(keywordId='1', bid=0.8, state='ENABLED')])
        self.assertEqual(out['agreed_held'], ['Bid change:6'])
        self.assertEqual(out['skipped'], [])  # not drift-checked either: nothing of it goes out
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['1'])
        self.assertNotIn('Bid change:6', self.record())
        self.assertEqual((self.locks(), out['locks_released']), ({'Bid change:6': stale}, 0))

    def test_refusing_a_held_row_in_shadow_locks_it(self):
        """The person disagreed with holding it, so the next planner sees it as a person's call."""
        self.plan_run()
        out = self.run_cmd([dec('Bid change:6', 'decline')])
        self.assertEqual((out['agreed_held'], out['declined']), ([], 1))
        self.assertEqual(self.locks()['Bid change:6'], dict(id='Bid change:6', what='decline', by='Lee', on='2026-10-19',
                                                           until='2026-11-16', direction='up'))

    def test_an_enabled_run_approves_whatever_lane_a_row_has(self):
        row = dict(bid_row('K1'), lane='monitor')
        plan = self.synthetic_run([row])
        plan['summary'][0]['shadow'] = False
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        out = self.run_cmd([dec('Bid change:K1', 'approve')])
        self.assertEqual((out['agreed_held'], out['approved']), ([], 1))


# =====================================================================================================================
class SeenTest(Base):
    """B5 and C1 (I5, I6): an approval applies only to what the person saw, as `seen` says and plan.json checks; B9: a
    locked bid or pause row approved again is a new decision."""

    def replan_row(self, row_id, **fields):
        """A same-date re-plan of the run folder that moves one row, not published again (the product file keeps the old
        item): the review's I5 probe."""
        plan = read_json(os.path.join(self.run_dir, 'plan.json'))
        for row in plan['changes'] + next(i for i in plan['human_review'] if i['kind'] == 'bid')['rows']:
            if row.get('row_id') == row_id:
                row.update(fields)
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        self.plan = plan
        return plan

    def test_an_approval_goes_out_only_when_it_saw_the_plans_numbers(self):
        plan = self.plan_run()
        saw_3 = dict(seen_on(plan, 'Bid change:3'), new=0.2)  # the dashboard showed a cut to $0.20; the plan now says $0.10
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=seen_on(plan, 'Bid change:1')),
                            dec('Bid change:4', 'approve', seen=seen_on(plan, 'Bid change:4')),
                            dec('Bid change:3', 'approve', seen=saw_3)])
        self.assertEqual({r['keywordId']: r['bid'] for r in self.approved_files()['4_bids_01.json']}, {'1': 0.98, '4': 0.37})
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:3',
                                               reason='re-planned since it was approved (saw $0.50 → $0.20, now $0.50 → $0.10)')])
        self.assertNotIn('Bid change:3', self.record())
        self.assertEqual(self.locks(), {})

    def test_what_was_seen_is_compared_to_the_cent(self):
        self.rerun_as_unapplied = True  # C2: each approvals run here starts from an approved/ that never went out
        plan = self.plan_run()
        for new, goes in ((0.984, True), (0.976, True), (0.986, False), (0.97, False), (None, False)):
            with self.subTest(new=new):
                out = self.run_cmd([dec('Bid change:1', 'approve', seen=dict(seen_on(plan, 'Bid change:1'), new=new))])
                self.assertEqual(out['approved'], 1 if goes else 0)
        capped = seen_on(plan, 'Bid change:4')
        out = self.run_cmd([dec('Bid change:4', 'approve', seen=dict(capped, new_capped=None))])  # saw no cap: $0.62
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:4',
                                               reason='re-planned since it was approved (saw $0.30 → $0.62, now $0.30 → $0.37)')])

    def test_what_was_seen_that_cannot_be_read_does_not_count(self):
        plan = self.plan_run()
        for seen in ('0.98', [0.8, 0.98], dict(seen_on(plan, 'Bid change:1'), new='0.98')):
            with self.subTest(seen=seen):
                out = self.run_cmd([dec('Bid change:1', 'approve', seen=seen)])
                self.assertEqual((out['approved'], out['skipped'][0]['reason']),
                                 (0, "can't read what was seen when it was approved"))

    # --- C1 (I5, I6): an approval applies only with `seen`, checked against plan.json ---------------------------------
    def test_an_approval_without_seen_never_goes_out(self):
        """C1: today's client sends no `seen`, so none of its approvals can be confirmed: no payload, no record, and no
        release of an earlier decline. Its declines lock as always."""
        stale = dict(id='Bid change:5', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        self.plan_run(decisions=[stale])
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=None), dec('Bid change:5', 'approve', seen=None),
                            dec('Bid change:3', 'decline', seen=None)])
        self.assertEqual({s['row_id']: s['reason'] for s in out['skipped']}, {'Bid change:1': NO_SEEN, 'Bid change:5': NO_SEEN})
        self.assertEqual((self.approved_files(), self.record(), out['approved']), ({}, {}, 0))
        self.assertEqual(self.locks()['Bid change:5'], stale)  # not released: the approval isn't a decision
        self.assertEqual((self.locks()['Bid change:3']['what'], out['locks_released']), ('decline', 0))

    def test_a_replan_published_again_does_not_carry_an_approval_to_new_numbers(self):
        """I5 (the re-review's probe): Lee approved Bid change:1 shown as $0.80 → $0.98. The same folder was planned again
        that day with corrected suggested bids ($0.80 → $1.40, capped at $1.00) and published again, so the product file's
        copy of the item now matches the new plan. Without `seen` nothing confirms her approval; with it, it is judged on
        what she saw."""
        plan = self.plan_run()
        before = seen_on(plan, 'Bid change:1')
        self.assertEqual({k: before[k] for k in BID_SEEN}, dict(current=0.8, new=0.98, new_capped=None))
        replanned = self.replan_row('Bid change:1', new=1.4, new_capped=1.0)
        self.edit_product(human_review=[next(i for i in replanned['human_review'] if i['kind'] == 'bid')])  # published again
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=None)])
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:1', reason=NO_SEEN)])
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=before)])
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:1',
                                               reason='re-planned since it was approved (saw $0.80 → $0.98, now $0.80 → $1.00)')])
        self.assertEqual(self.approved_files(), {})

    def test_what_was_seen_is_checked_against_plan_json_not_the_product_file(self):
        """The product file's copy of the item is what a re-publish or a compaction changes; plan.json is what goes out."""
        plan = self.plan_run()
        product = self.product()
        for row in product['human_review'][0]['rows']:
            if row['row_id'] == 'Bid change:1':
                row['new'] = 1.2  # a copy that disagrees with the plan
        write_json(self.product_file, product)
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=seen_on(plan, 'Bid change:1'))])
        self.assertEqual((out['approved'], out['skipped']), (1, []))
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=dict(seen_on(plan, 'Bid change:1'), new=1.2))],
                           discard_unapplied=True)
        self.assertEqual(out['skipped'][0]['reason'], 're-planned since it was approved (saw $0.80 → $1.20, now $0.80 → $0.98)')

    def test_a_resolved_items_approvals_go_out_when_they_say_what_was_seen(self):
        """I6 (the re-review's probe): approve the capped raise on keyword 4, refuse the cut on keyword 3, then the owner
        closes the item with `review --status resolved`, which drops its rows from the product file. Approvals runs normally
        and checks what was seen against plan.json, so the approval goes out and the decline locks."""
        self.plan_run()
        product = self.product()
        product['human_review'] = human_review.transition(product['human_review'], ITEM, 'resolved', None, 'every row decided',
                                                          '2026-10-19')
        write_json(self.product_file, product)
        self.assertNotIn('rows', self.product()['human_review'][0])
        out = self.run_cmd([dec('Bid change:4', 'approve'), dec('Bid change:3', 'decline')])
        self.assertEqual((out['mode'], out['item_status'], out['skipped']), ('normal', 'resolved', []))
        self.assertEqual(self.approved_files(), {'4_bids_01.json': [dict(type='sp_keywords', keywordId='4', bid=0.37)]})
        self.assertEqual(self.locks()['Bid change:3']['what'], 'decline')
        # the same approval from today's client (no `seen`) can't be confirmed
        out = self.run_cmd([dec('Bid change:4', 'approve', seen=None)], discard_unapplied=True)
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:4', reason=NO_SEEN)])

    def test_a_skipped_approval_does_not_replace_an_earlier_decline(self):
        plan = self.plan_run()
        saw_old = dict(seen_on(plan, 'Bid change:3'), new=0.2)
        out = self.run_cmd([dec('Bid change:3', 'decline', at='2026-10-19T02:00:00Z'),
                            dec('Bid change:3', 'approve', at='2026-10-19T03:00:00Z', seen=saw_old)])
        self.assertEqual((out['declined'], out['skipped'], self.locks()['Bid change:3']['what']), (1, [], 'decline'))

    def test_a_decline_locks_whatever_it_saw(self):
        """A decline only ever sends its row to a person, so it locks even when the numbers moved (the planner would lock it
        from the saved decisions anyway, B2)."""
        plan = self.plan_run()
        out = self.run_cmd([dec('Bid change:3', 'decline', seen=dict(seen_on(plan, 'Bid change:3'), new=0.2))])
        self.assertEqual((out['declined'], self.locks()['Bid change:3']['what']), (1, 'decline'))

    # --- B9: a locked row approved again ---------------------------------------------------------------------------
    def test_a_locked_row_approved_again_goes_out_from_the_plan_and_locks_when_applied(self):
        refused = dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        plan = self.plan_run(decisions=[refused])
        row = next(r for r in next(i for i in plan['human_review'] if i['kind'] == 'bid')['rows'] if r['row_id'] == 'Bid change:3')
        self.assertEqual((row['lane'], row['lock_decision'], row['locked_until']), ('human', 'decline', '2026-11-09'))
        self.assertIn('"keywordId":"3"', json.dumps(read_json(os.path.join(self.run_dir, 'payloads', 'held', '4_bids_01.json')),
                                                    separators=(',', ':')))
        out = self.run_cmd([dec('Bid change:3', 'approve', by='Kim', seen=seen_on(plan, 'Bid change:3'))])
        self.assertEqual(self.approved_files(), {'4_bids_01.json': [dict(type='sp_keywords', keywordId='3', bid=0.1)]})
        self.assertEqual((out['locks_released'], self.locks()['Bid change:3']), (0, refused))  # until it has gone out
        self.run_applied('approved', date='2026-10-20')
        self.assertEqual(self.locks()['Bid change:3'], dict(id='Bid change:3', what='approve', by='Kim', on='2026-10-19',
                                                           until='2026-11-17', direction='down'))
        # the seen check applies to it like any other row
        out = self.run_cmd([dec('Bid change:3', 'approve', by='Kim', seen=dict(seen_on(plan, 'Bid change:3'), current=0.7))])
        self.assertEqual([s['row_id'] for s in out['skipped']], ['Bid change:3'])
        self.assertTrue(out['skipped'][0]['reason'].startswith('re-planned since it was approved'), out['skipped'])

    def test_a_decline_of_a_locked_row_refreshes_its_lock(self):
        refused = dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        self.plan_run(decisions=[refused])
        self.run_cmd([dec('Bid change:3', 'decline', by='Lee')])
        # it holds from her decline; G2: Kim's earlier decline, which the plan still holds the row by, names the lock
        self.assertEqual(self.locks()['Bid change:3'], dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-12',
                                                           until='2026-11-16', direction='down'))
        self.plan_run(decisions=[dict(refused, by='Sam')])  # a lower decliner's lock: hers replaces it
        self.run_cmd([dec('Bid change:3', 'decline', by='Lee')])
        self.assertEqual(self.locks()['Bid change:3'], dict(id='Bid change:3', what='decline', by='Lee', on='2026-10-19',
                                                           until='2026-11-16', direction='down'))


# =====================================================================================================================
class MoneySeenTest(Base):
    """E2 (I2): budgets, top-of-search boosts and a promotion's modelled monthly spend are shown on the row and covered by
    `seen`: an approval matches only when every one of them the plan row has equals what the person saw (money to the
    cent, a boost to the whole percent). A `seen` missing one the row has is a mismatch."""

    def budget_rid(self, plan):
        return next(c['row_id'] for c in plan['changes'] if c['type'] == 'Budget and top of search')

    def test_the_seen_keys_are_every_number_the_card_shows(self):
        self.assertEqual(dashboard.SEEN_KEYS, ('current', 'new', 'new_capped', 'budget_now', 'budget', 'tos_now', 'tos',
                                               'modelled_spend_month'))

    def test_a_budget_replanned_after_the_approval_is_skipped(self):
        """I2's probe: the thank you cards SKC goes from $10 to $15/day (a budget override), Lee approves it as shown,
        then the override becomes $40 and the same folder (nothing went out) is planned again. Her approval no longer
        counts, and nothing writes $40."""
        plan1 = self.plan_run(budget_overrides={'thank you cards': 15})
        rid = self.budget_rid(plan1)
        seen1 = seen_on(plan1, rid)
        self.assertEqual({k: seen1[k] for k in ('budget_now', 'budget', 'tos_now', 'tos')},
                         dict(budget_now=10, budget=15, tos_now=50, tos=50))
        plan2 = self.plan_run(budget_overrides={'thank you cards': 40})
        self.assertEqual(rid, self.budget_rid(plan2))
        out = self.run_cmd([dec(rid, 'approve', seen=seen1)])
        self.assertEqual(out['skipped'], [dict(row_id=rid, reason='re-planned since it was approved (saw budget $15.00/day, '
                                                                  'now budget $40.00/day)')])
        self.assertEqual((out['approved'], self.approved_files()), (0, {}))
        # as shown on the new plan, it goes out at $40
        out = self.run_cmd([dec(rid, 'approve', seen=seen_on(plan2, rid))])
        self.assertEqual(out['skipped'], [])
        self.assertEqual(self.approved_files()['5_campaign_updates.json'][0]['budget']['budget'], 40)

    def test_a_seen_without_the_money_keys_is_a_mismatch_on_a_row_that_has_them(self):
        """An older client sent only the bids: on a budget row its {current, new, new_capped} of nulls says nothing about
        the budget, so it can't count. On a plain bid row it still does (the row has no money keys)."""
        plan = self.plan_run(budget_overrides={'thank you cards': 15})
        rid = self.budget_rid(plan)
        bids_only = {k: seen_on(plan, rid)[k] for k in BID_SEEN}
        out = self.run_cmd([dec(rid, 'approve', seen=bids_only),
                            dec('Bid change:1', 'approve', seen={k: seen_on(plan, 'Bid change:1')[k] for k in BID_SEEN})])
        self.assertEqual([s['row_id'] for s in out['skipped']], [rid])
        self.assertEqual(out['skipped'][0]['reason'],
                         're-planned since it was approved (saw live budget none, budget none, live top of search none, top '
                         'of search none, now live budget $10.00/day, budget $15.00/day, live top of search 50%, top of '
                         'search 50%)')
        self.assertEqual(out['approved'], 1)  # Bid change:1

    def test_money_matches_to_the_cent_and_a_boost_to_the_whole_percent(self):
        self.rerun_as_unapplied = True  # each run starts from an approved/ that never went out
        plan = self.plan_run(budget_overrides={'thank you cards': 15})
        rid = self.budget_rid(plan)
        shown = seen_on(plan, rid)
        for over, goes in ((dict(budget=15.004), True), (dict(budget=15.01), False), (dict(budget_now=9.99), False),
                           (dict(tos=50.4), True), (dict(tos=51), False), (dict(tos_now=None), False),
                           (dict(modelled_spend_month=1.0), False)):
            with self.subTest(**over):
                out = self.run_cmd([dec(rid, 'approve', seen=dict(shown, **over))])
                self.assertEqual(out['approved'], 1 if goes else 0, out['skipped'])

    def test_a_promotions_budget_and_monthly_spend_are_covered_too(self):
        """A promotion commits a daily budget and its modelled monthly spend (the product's planned invest adds it up): both are on
        the row, and a re-plan that moves either stops an approval of what was seen."""
        plan = self.plan_run()
        promo = seen_on(plan, BUNDLE[0])
        change = next(c for c in plan['changes'] if c['row_id'] == BUNDLE[0])
        self.assertEqual((promo['budget'], promo['modelled_spend_month']), (10, change['modelled_spend_month']))
        self.assertIsNotNone(promo['modelled_spend_month'])
        for field, value in (('budget', 25), ('modelled_spend_month', change['modelled_spend_month'] + 50)):
            with self.subTest(field=field):
                self.plan_run()
                saw = dict(seen_on(read_json(os.path.join(self.run_dir, 'plan.json')), BUNDLE[0]), **{field: value})
                out = self.run_cmd([dec(BUNDLE[0], 'approve', seen=saw)] + [dec(r, 'approve') for r in BUNDLE[1:]])
                self.assertEqual(out['approved'], 0)
                reason = next(s['reason'] for s in out['skipped'] if s['row_id'] == BUNDLE[0])
                self.assertTrue(reason.startswith('re-planned since it was approved'), reason)
        self.plan_run()
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE])  # as shown
        self.assertEqual((out['skipped'], out['approved'] > 0), ([], True))

    def test_seen_with_a_key_that_is_not_a_shown_number_cannot_be_read(self):
        plan = self.plan_run()
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=dict(seen_on(plan, 'Bid change:1'), bid=0.98))])
        self.assertEqual(out['skipped'][0]['reason'], "can't read what was seen when it was approved")
        out = self.run_cmd([dec('Bid change:1', 'approve', seen=dict(seen_on(plan, 'Bid change:1'), budget='15'))])
        self.assertEqual(out['skipped'][0]['reason'], "can't read what was seen when it was approved")


# =====================================================================================================================
class ApplyRecordTest(Base):
    """B4 (I3c), M3, M8: approvals writes only decline locks; `applied` records what went out, in
    <run>/payloads/applied_rows.json, and writes the approve locks for rows applied from approved/."""

    def applied_refused(self, folder, **over):
        with self.assertRaises(SystemExit) as cm:
            self.run_applied(folder, **over)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    def applied_rows(self):
        return read_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'))

    def test_approvals_writes_only_decline_locks_with_the_day_and_the_way(self):
        self.plan_run()
        out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve'), dec('Bid change:5', 'decline')])
        self.assertEqual(out['approved'], 2)
        self.assertEqual(self.product()['decisions'],
                         [dict(id='Bid change:5', what='decline', by='Lee', on='2026-10-19', until='2026-11-16', direction='down')])
        held, problem = plan_lanes.lock_table(self.product(), 4)
        self.assertIsNone(problem)
        self.assertEqual(held[lanes.lock_key('Bid change:5')]['direction'], 'down')

    def test_approvals_names_the_row_behind_every_approved_payload_row(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve', by='Kim'), dec('Bid change:3', 'approve', at='2026-10-19T17:30:00Z')])
        self.assertEqual(read_json(os.path.join(self.approved_dir, 'rows.json')),
                         {'4_bids_01.json': ['Bid change:1', 'Bid change:3']})
        record = read_json(os.path.join(self.run_dir, 'payloads', 'approved_decisions.json'))
        self.assertEqual(record, {'Bid change:1': dict(by='Kim', on='2026-10-19', at=AT),
                                  'Bid change:3': dict(by='Lee', on='2026-10-20', at='2026-10-19T17:30:00Z')})

    def test_applied_from_approved_records_the_rows_and_writes_their_approve_locks(self):
        self.plan_run()
        self.edit_product(decisions=[dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-12', until='2026-11-09',
                                          direction='down')])
        self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve', by='Kim')])
        self.assertEqual(self.locks()['Bid change:3']['what'], 'decline')  # approving it again does not lock it yet (B9)
        out = self.run_applied('approved', date='2026-10-20')
        self.assertEqual(self.applied_rows(), {rid: dict(date='2026-10-20', folder='approved')
                                               for rid in ('Bid change:1', 'Bid change:3')})
        self.assertEqual(self.locks(), {
            'Bid change:1': dict(id='Bid change:1', what='approve', by='Lee', on='2026-10-19', until='2026-11-17', direction='up'),
            'Bid change:3': dict(id='Bid change:3', what='approve', by='Kim', on='2026-10-19', until='2026-11-17', direction='down')})
        self.assertEqual((out['recorded'], out['locks_written']), (2, 2))
        self.applied_call.assert_not_called()  # the approvals' own record names who approved: no read needed, no write ever

    def test_applied_from_auto_or_review_records_the_rows_and_locks_only_its_creations(self):
        """A whole-run yes (review/) or an automatic row (auto/) is not a person's decision on a row, so it locks nothing
        (B4), except a creation: C3 records that the search was created, so it is never created again."""
        for shadow, folder in ((True, 'review'), (False, 'auto')):
            with self.subTest(folder=folder):
                self.plan_run(shadow=shadow)
                rows = read_json(os.path.join(self.run_dir, 'payloads', folder, 'rows.json'))
                out = self.run_applied(folder, date='2026-10-21')
                every = {rid for ids in rows.values() for rid in ids}
                self.assertEqual(self.applied_rows(), {rid: dict(date='2026-10-21', folder=folder) for rid in every})
                self.assertIn(BUNDLE[0], every)
                self.assertEqual(self.product()['decisions'], [dict(
                    id=BUNDLE[0], what='approve', kind='create', search='blank cards', created_on='2026-10-21',
                    on='2026-10-21', until='2026-11-18', direction='other')])  # no `by`: nobody decided the row itself
                self.assertEqual((out['recorded'], out['locks_written']), (len(every), 1))
                # C4: before recording review/, it reads the dashboard to check nobody is deciding the run row by row
                self.assertEqual([c.args[:2] for c in self.applied_call.call_args_list],
                                 [('GET', f'/api/reviews/{ASIN}')] if folder == 'review' else [])
                os.remove(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'))

    def test_a_row_applied_twice_keeps_the_day_it_first_went_out(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve')])
        self.run_applied('approved', date='2026-10-20')
        out = self.run_applied('approved', date='2026-10-22')
        self.assertEqual(self.applied_rows(), {'Bid change:1': dict(date='2026-10-20', folder='approved')})
        self.assertEqual(self.locks()['Bid change:1']['until'], '2026-11-17')
        self.assertEqual(out['recorded'], 0)

    def test_an_approved_row_applied_from_review_is_not_emitted_again(self):
        """I2, C4: the preview's yes applied review/ and recorded it; a dashboard approval made afterwards sends nothing:
        approvals refuses a run that was applied whole."""
        self.plan_run()
        self.run_applied('review', date='2026-10-20')
        message = self.refused([dec('Bid change:1', 'approve')])
        self.assertIn('this run was applied whole on 2026-10-20', message)
        self.assertEqual(self.approved_files(), {})

    def test_applied_refuses_the_held_folder_and_a_folder_without_rows_json(self):
        self.plan_run()
        before = self.raw_product()
        self.assertIn('held', self.applied_refused('held'))
        os.remove(os.path.join(self.run_dir, 'payloads', 'review', 'rows.json'))
        self.assertIn('rows.json', self.applied_refused('review'))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
        self.assertEqual(self.raw_product(), before)

    def test_applied_on_an_empty_folder_records_nothing_and_does_not_fail(self):
        """C7 (I8): a week where nothing went out (approvals wrote nothing; an enabled run on stale data holds every row, so
        its auto/ is empty; an onboarding run's was until 2026-10-22) is a normal week: `applied` exits 0, says so, and
        writes nothing, so nothing reads as applied later."""
        for shadow, folder in ((True, 'approved'), (False, 'auto'), (True, 'auto')):
            with self.subTest(folder=folder, shadow=shadow):
                self.plan_run(shadow=shadow)
                if not shadow:   # an enabled run that sent nothing (stale data stops the run since decision 168)
                    auto_dir = os.path.join(self.run_dir, 'payloads', 'auto')
                    for name in os.listdir(auto_dir):
                        os.remove(os.path.join(auto_dir, name))
                before = self.raw_product()
                out = self.run_applied(folder)
                self.assertEqual((out['rows'], out['recorded'], out['locks_written']), (0, 0, 0))
                self.assertIn(f'Nothing to record: payloads/{folder}/ holds no payloads', out['note'])
                self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
                self.assertEqual(self.raw_product(), before)
        os.makedirs(self.approved_dir, exist_ok=True)
        write_json(os.path.join(self.approved_dir, 'rows.json'), {})  # a rows.json naming nothing is no different
        self.assertEqual(self.run_applied('approved')['recorded'], 0)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))

    def test_applied_refuses_a_bad_date(self):
        self.plan_run()
        self.assertIn('--date', self.applied_refused('review', date='20/10/2026'))

    def test_applied_falls_back_to_the_dashboard_for_who_approved(self):
        self.plan_run()
        decisions = [dec('Bid change:1', 'approve', by='Kim')]
        self.run_cmd(decisions)
        os.remove(os.path.join(self.run_dir, 'payloads', 'approved_decisions.json'))
        self.run_applied('approved', entries=decisions)
        self.assertEqual([c.args[:2] for c in self.applied_call.call_args_list], [('GET', f'/api/reviews/{ASIN}')])
        self.assertEqual((self.locks()['Bid change:1']['by'], self.locks()['Bid change:1']['on']), ('Kim', '2026-10-19'))
        # nobody to name: the row still went out, so it still locks
        self.run_applied('approved', entries=[])
        lock = self.locks()['Bid change:1']
        self.assertEqual((lock['what'], lock['on'], lock['until'], lock['direction']), ('approve', '2026-10-20', '2026-11-17', 'up'))
        self.assertNotIn('by', lock)

    def test_an_unreadable_applied_rows_file_stops_both_commands(self):
        self.plan_run()
        path = os.path.join(self.run_dir, 'payloads', 'applied_rows.json')
        before = self.raw_product()
        for text in ('not json', '[]', '{"Bid change:1": 5}', '{"Bid change:1": "last week"}'):
            with self.subTest(text=text):
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(text)
                self.assertIn('applied_rows.json', self.refused([dec('Bid change:1', 'approve')]))
                self.assertIn('applied_rows.json', self.applied_refused('review'))
                self.assertEqual(self.raw_product(), before)

    def test_locks_that_ended_over_90_days_ago_are_pruned_when_decisions_are_written(self):
        self.plan_run()
        old = dict(id='old', what='decline', by='Kim', until='2026-07-20')     # ended 91 days before 19 October
        recent = dict(id='recent', what='decline', by='Kim', until='2026-07-21')  # 90 days: kept
        odd = dict(id='odd', what='decline', by='Kim', until='further notice')  # can't be read: kept
        self.edit_product(decisions=[old, recent, odd])
        out = self.run_cmd([dec('Bid change:5', 'decline')])
        self.assertEqual([d['id'] for d in self.product()['decisions']], ['recent', 'odd', 'Bid change:5'])
        self.assertEqual(out['locks_pruned'], 1)
        self.edit_product(decisions=[old, recent, odd])
        self.run_cmd([dec('Bid change:1', 'approve')])
        out = self.run_applied('approved', date='2026-10-20')  # 2026-07-21 is 91 days before the 20th
        self.assertEqual([d['id'] for d in self.product()['decisions']], ['odd', 'Bid change:1'])
        self.assertEqual(out['locks_pruned'], 2)

    def test_the_applied_command_is_wired_into_the_cli(self):
        self.plan_run()
        argv = ['dashboard.py', 'applied', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--folder', 'review',
                '--date', '2026-10-20']
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), \
                unittest.mock.patch.object(dashboard, 'call', return_value=[]), \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            dashboard.main()
        self.assertGreater(json.loads(out.getvalue())['recorded'], 0)
        argv[argv.index('review')] = 'held'
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            dashboard.main()


# =====================================================================================================================
class ApprovedGuardTest(Base):
    """C2 (concern a, N2) and N9: approvals never clears or rewrites payloads/approved/ while it holds rows `applied` hasn't
    recorded, in either mode, unless told those rows did not go out (--discard-unapplied); and it never deletes an old
    approved/applied.json."""

    def snapshot(self):
        """Everything approvals could have changed: the approved/ folder, its record and the product file."""
        files = {}
        if os.path.isdir(self.approved_dir):
            for n in sorted(os.listdir(self.approved_dir)):
                with open(os.path.join(self.approved_dir, n), 'rb') as fh:
                    files[n] = fh.read()
        record = os.path.join(self.run_dir, 'payloads', 'approved_decisions.json')
        if os.path.exists(record):
            with open(record, 'rb') as fh:
                files['record'] = fh.read()
        return files, self.raw_product()

    def held_message(self, n):
        return (f'payloads/approved/ still holds {n} rows not recorded as applied. If they went out, run `python '
                f'scripts/dashboard.py applied --asin {ASIN} --run {self.run_dir} --folder approved` first. If they did '
                'not, re-run with --discard-unapplied.')

    def test_approvals_run_again_before_applied_is_refused(self):
        """The re-review's first probe: the bundle went to approved/ (and out through MAP), and a teammate approved one more
        row before `applied` ran. The second approvals must not write 'blank cards' again, nor anything else."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        self.assertIn('1_new_campaigns.json', self.approved_files())
        before = self.snapshot()
        message = self.refused([dec(r, 'approve') for r in BUNDLE] + [dec('Bid change:4', 'approve')])
        self.assertIn(self.held_message(4), message)
        for rid in BUNDLE:
            self.assertIn(rid, message)
        self.assertEqual(self.snapshot(), before)
        self.call.assert_not_called()  # refused before the dashboard was read

    def test_a_decline_after_an_unrecorded_apply_neither_empties_approved_nor_locks(self):
        """The second probe: a decline arrives on a bundle row whose pause already went out. Refused, so approved/ still
        names every row for `applied`, and no decline lock lands on a live pause."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        before = self.snapshot()
        self.refused([dec(r, 'approve') for r in BUNDLE] + [dec('Pause keyword:2', 'decline', at='2026-10-19T06:00:00Z')])
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('decisions', self.product())
        out = self.run_applied('approved', date='2026-10-20')
        self.assertEqual(out['recorded'], 4)  # every row that went out is recorded, and locks
        self.assertEqual({k: v['what'] for k, v in self.locks().items()}, {rid: 'approve' for rid in BUNDLE})

    def test_a_decisions_only_run_does_not_delete_an_unrecorded_approved_folder(self):
        """The third probe: the run was superseded before `applied` recorded its apply. Decisions-only mode clears
        approved/ and its record too, so it is refused the same way; once recorded, it runs."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        product = self.product()
        product['human_review'] = human_review.transition(product['human_review'], ITEM, 'dismissed', None,
                                                          'Superseded by bids-2026-10-26', '2026-10-26')
        write_json(self.product_file, product)
        before = self.snapshot()
        self.assertIn(self.held_message(4), self.refused([dec(r, 'approve') for r in BUNDLE]))
        self.assertEqual(self.snapshot(), before)
        self.run_applied('approved', date='2026-10-26')
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        self.assertEqual((out['mode'], out['approved'], self.approved_files(), self.record()), ('decisions_only', 0, {}, {}))

    def test_rows_recorded_as_applied_are_cleared_without_the_flag(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve')])
        self.run_applied('approved', date='2026-10-20')
        out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve')])
        self.assertEqual(out['discarded'], [])
        self.assertEqual(self.approved_files(), {'4_bids_01.json': [dict(type='sp_keywords', keywordId='3', bid=0.1)]})
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:1', reason='already applied on 2026-10-20')])

    def test_discard_unapplied_clears_the_rows_and_names_them(self):
        """Only for an approved/ that never went out: the operator says so, and the output names what was thrown away."""
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve')])
        out = self.run_cmd([dec('Bid change:5', 'approve')], discard_unapplied=True)
        self.assertEqual(out['discarded'], ['Bid change:1', 'Bid change:3'])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['5'])
        self.assertEqual(list(self.record()), ['Bid change:5'])
        out = self.run_cmd([], discard_unapplied=True)
        self.assertEqual((out['discarded'], self.approved_files(), self.record()), (['Bid change:5'], {}, {}))

    def test_payload_files_without_rows_json_are_refused_unless_discarded(self):
        """What such a folder handed out can't be told, so it can't be recorded either: only --discard-unapplied clears it."""
        self.plan_run()
        os.makedirs(self.approved_dir)
        write_json(os.path.join(self.approved_dir, '4_bids_01.json'), [dict(type='sp_keywords', keywordId='1', bid=0.98)])
        before = self.snapshot()
        message = self.refused([dec('Bid change:3', 'approve')])
        self.assertIn('payloads/approved/ holds payload files without rows.json', message)
        self.assertIn('--discard-unapplied', message)
        self.assertEqual(self.snapshot(), before)
        out = self.run_cmd([dec('Bid change:3', 'approve')], discard_unapplied=True)
        self.assertEqual(out['discarded'], ['4_bids_01.json (no rows.json)'])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['3'])

    def test_a_dry_run_is_refused_the_same_way(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve')])
        self.assertIn(self.held_message(1), self.refused([dec('Bid change:1', 'approve')], dry_run=True))

    def test_an_old_approved_applied_json_is_never_deleted(self):
        """N9: Task 7's record payloads/approved/applied.json is kept by every clear, with or without the flag."""
        self.plan_run()
        old = os.path.join(self.approved_dir, 'applied.json')
        write_json(old, dict(applied_on='2026-10-12', row_ids=['Bid change:1']))
        out = self.run_cmd([dec('Bid change:3', 'approve')])
        self.assertEqual(out['discarded'], [])
        self.assertTrue(os.path.exists(old))
        self.assertEqual(sorted(os.listdir(self.approved_dir)), ['4_bids_01.json', 'applied.json', 'rows.json'])
        self.run_applied('approved', date='2026-10-20')
        self.run_cmd([dec('Bid change:3', 'decline')], discard_unapplied=True)
        self.assertEqual(os.listdir(self.approved_dir), ['applied.json'])

    def test_the_flag_is_wired_into_the_cli(self):
        self.plan_run()
        self.run_cmd([dec('Bid change:1', 'approve')])
        argv = ['dashboard.py', 'approvals', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--now', MON,
                '--discard-unapplied']
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), \
                unittest.mock.patch.object(dashboard, 'call', return_value=[]), \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            dashboard.main()
        self.assertEqual(json.loads(out.getvalue())['discarded'], ['Bid change:1'])


# =====================================================================================================================
class ReviewRouteTest(Base):
    """C4 (N3): review/ (the preview's whole-run yes) and approved/ (row-by-row decisions) never both go out for one run.
    `applied --folder review` is also the check before review/ is applied (--dry-run)."""

    DECIDING = "this run is being decided row by row; apply approved/ instead"

    def applied_refused(self, folder, **over):
        with self.assertRaises(SystemExit) as cm:
            self.run_applied(folder, **over)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    def applied_rows_path(self):
        return os.path.join(self.run_dir, 'payloads', 'applied_rows.json')

    def test_review_is_refused_while_the_runs_item_has_any_decision(self):
        """The re-review's N3 probe 1: after the plan, Lee refused the cut on keyword 3. review/ still writes it, so the
        whole-run route is refused (dry run first, as the check before the apply, and the record itself)."""
        self.plan_run()
        decided = [dec('Bid change:3', 'decline', seen=None)]
        before = self.raw_product()
        for dry in (True, False):
            with self.subTest(dry_run=dry):
                self.assertIn(self.DECIDING, self.applied_refused('review', entries=decided, dry_run=dry))
        self.assertFalse(os.path.exists(self.applied_rows_path()))
        self.assertEqual(self.raw_product(), before)
        # an approval counts as deciding too, and so does a decision in the run's own saved reviews.json
        self.assertIn(self.DECIDING, self.applied_refused('review', entries=[dec('Bid change:1', 'approve', seen=None)]))
        write_json(os.path.join(self.run_dir, 'reviews.json'),
                   dict(asin=ASIN, saved_at='2026-10-19T09:00:00Z', entries=decided))
        self.assertIn(self.DECIDING, self.applied_refused('review', entries=[]))
        write_json(os.path.join(self.run_dir, 'reviews.json'), decided)  # a bare list, as an older save wrote it
        self.assertIn(self.DECIDING, self.applied_refused('review', entries=[]))

    def test_review_is_refused_after_approved_went_out(self):
        """N3 probe 2: approved/ (the blank cards bundle) was applied and recorded; review/ would create 'blank cards' again."""
        self.plan_run()
        decisions = [dec(r, 'approve') for r in BUNDLE]
        self.run_cmd(decisions)
        self.run_applied('approved', date='2026-10-20', entries=decisions)
        self.assertIn(self.DECIDING, self.applied_refused('review', entries=resolve(self.plan, decisions)))

    def test_review_is_refused_when_one_of_its_rows_was_declined_after_the_plan(self):
        """A decline on another item (the older run's) made after this plan: the row is in review/, so a person said no to
        what review/ would send. The rows are named, and the run must be planned again."""
        self.plan_run()
        later = [dec('Bid change:3', 'decline', item_id='bids-2026-10-12', at='2026-10-19T05:00:00Z', seen=None),
                 dec('Bid change:1', 'decline', item_id='bids-2026-10-12', at='2026-08-01T05:00:00Z', seen=None)]  # long over
        message = self.applied_refused('review', entries=later)
        self.assertIn('declined on the dashboard after the plan: Bid change:3.', message)
        self.assertNotIn('Bid change:1', message)
        self.assertIn('plan the run again', message)
        self.assertFalse(os.path.exists(self.applied_rows_path()))

    def test_a_declined_raise_replanned_as_a_cut_is_not_refused(self):
        """N-new-3 (the re-review's P3): a raise on keyword 3 was declined and settled (step 2 wrote a lock for raises); this
        run plans a cut on it, which the planner rightly sends to review/. The check builds its locks as the planner does
        (the product file's directional lock plus the dashboard's declines), so the old decline doesn't hold the cut, while
        a decline made after the plan still does."""
        lock = dict(id='Bid change:3', what='decline', by='Lee', on='2026-10-12', until='2026-11-09', direction='up')
        self.plan_run(decisions=[lock])
        cut = next(c for c in self.plan['changes'] if c['row_id'] == 'Bid change:3')
        self.assertLess(cut['new'], cut['current'])
        self.assertNotIn('locked_until', cut)  # the planner allows it
        rows = read_json(os.path.join(self.run_dir, 'payloads', 'review', 'rows.json'))
        self.assertIn('Bid change:3', [rid for ids in rows.values() for rid in ids])
        old = dec('Bid change:3', 'decline', item_id='bids-2026-10-12', at='2026-10-12T05:00:00Z', seen=None)
        later = dec('Bid change:3', 'decline', item_id='bids-2026-10-12', at='2026-10-19T05:00:00Z', seen=None)
        # a decline made after the plan still holds the row, whichever way it moves
        self.assertIn('declined on the dashboard after the plan: Bid change:3.',
                      self.applied_refused('review', date='2026-10-20', entries=[old, later]))
        self.assertFalse(os.path.exists(self.applied_rows_path()))
        for dry in (True, False):
            with self.subTest(dry_run=dry):
                out = self.run_applied('review', date='2026-10-20', entries=[old], dry_run=dry)
                self.assertGreater(out['rows'], 0)
        self.assertIn('Bid change:3', read_json(self.applied_rows_path()))

    def test_record_anyway_records_what_already_went_out(self):
        """When review/ already went out through MAP and a decision landed in the meantime, recording it is the safe side:
        nothing of it can then go out again."""
        self.plan_run()
        out = self.run_applied('review', date='2026-10-20', entries=[dec('Bid change:3', 'decline', seen=None)],
                               record_anyway=True)
        rows = read_json(os.path.join(self.run_dir, 'payloads', 'review', 'rows.json'))
        self.assertEqual(out['recorded'], len({rid for ids in rows.values() for rid in ids}))
        self.assertTrue(any('checks were skipped' in w for w in out['warnings']))
        self.applied_call.assert_not_called()

    def test_approvals_refuses_a_run_applied_whole(self):
        """After review/ went out whole, nothing of the run's bids item goes out from approved/, and nothing is written."""
        self.plan_run()
        self.run_applied('review', date='2026-10-20')
        before = self.raw_product()
        message = self.refused([dec('Bid change:1', 'approve'), dec('Bid change:5', 'decline')])
        self.assertIn('this run was applied whole on 2026-10-20', message)
        self.assertEqual((self.raw_product(), os.path.exists(self.approved_dir)), (before, False))

    def test_the_older_record_shape_is_read_with_its_folder_unknown(self):
        """{row_id: date} (before C4): never emitted again, never taken for a whole-run apply, and kept as it was."""
        self.plan_run()
        write_json(self.applied_rows_path(), {'Bid change:1': '2026-10-19'})
        out = self.run_cmd([dec('Bid change:1', 'approve'), dec('Bid change:3', 'approve')])
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:1', reason='already applied on 2026-10-19')])
        self.run_applied('approved', date='2026-10-20')
        self.assertEqual(read_json(self.applied_rows_path()),
                         {'Bid change:1': '2026-10-19', 'Bid change:3': dict(date='2026-10-20', folder='approved')})

    def test_a_record_that_names_an_unknown_folder_is_unreadable(self):
        self.plan_run()
        for bad in ({'Bid change:1': dict(date='2026-10-19', folder='held')}, {'Bid change:1': dict(folder='review')},
                    {'Bid change:1': dict(date='2026-10-19', folder='review', extra=1)}):
            with self.subTest(bad=bad):
                write_json(self.applied_rows_path(), bad)
                self.assertIn('applied_rows.json', self.refused([dec('Bid change:3', 'approve')]))


# =====================================================================================================================
class WriteWindowTest(Base):
    def test_approved_payloads_are_emitted_during_weekend_audit(self):
        self.plan_run()
        out=self.run_cmd([dec('Bid change:1','approve'),dec('Bid change:5','decline')],now=SUN)
        self.assertEqual(out['approved'],1)
        self.assertTrue(out['write_window_open'])
        self.assertEqual(list(self.approved_files()),['4_bids_01.json'])
        self.assertEqual(set(self.locks()),{'Bid change:5'})

    def test_legacy_future_date_does_not_hold_approved_changes(self):
        self.synthetic_run([bid_row('K1')],apply_after='2026-10-26')
        out=self.run_cmd([dec('Bid change:K1','approve')],now='2026-10-24T08:00:00Z')
        self.assertEqual(out['approved'],1)

    def test_absent_legacy_date_does_not_hold_approved_changes(self):
        self.synthetic_run([bid_row('K1')],apply_after=None)
        out=self.run_cmd([dec('Bid change:K1','approve')],now=SUN)
        self.assertEqual(out['approved'],1)

    def test_weekend_dry_run_does_not_write(self):
        self.plan_run()
        before=self.raw_product()
        out=self.run_cmd([dec('Bid change:1','approve')],now=SUN,dry_run=True)
        self.assertTrue(out['write_window_open'])
        self.assertEqual(self.raw_product(),before)
        self.assertFalse(os.path.exists(self.approved_dir))



# =====================================================================================================================
class CreationTest(Base):
    """C3 (N1): a search's creation (a new or reused exact campaign, a new Sponsored Brands video campaign, and the bundle
    that goes with it) that went out is never emitted again; and B9 (a locked row approved again) covers bid and pause
    rows only."""

    CREATED = 'already created on 2026-10-20; nothing to do'

    def apply_the_bundle(self):
        """Week 1: the blank cards bundle approved, emitted, applied through MAP and recorded on 2026-10-20."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        self.run_applied('approved', date='2026-10-20')
        return self.product()['decisions']

    def test_applied_writes_a_create_lock_on_a_creation(self):
        locks = {d['id']: d for d in self.apply_the_bundle()}
        self.assertEqual(locks[BUNDLE[0]], dict(id=BUNDLE[0], what='approve', by='Lee', on='2026-10-19', until='2026-11-17',
                                                direction='other', kind='create', search='blank cards',
                                                created_on='2026-10-20'))
        self.assertTrue(all('kind' not in locks[rid] for rid in BUNDLE[1:]))  # the pause and negatives are not creations

    def test_a_creation_already_made_is_held_by_the_next_plan_and_never_emitted_again(self):
        """N1 (the re-review's probe): week 2 was planned from data that predates the apply, so it would propose 'New exact
        campaign: blank cards' again. The planner holds it, read-only, and an approval of it sends nothing."""
        decisions = self.apply_the_bundle()
        self.run_dir = os.path.join(self.tmp, 'week 2')
        plan = self.plan_run(decisions=decisions)
        row = next(x for x in plan['changes'] if x['row_id'] == BUNDLE[0])
        self.assertEqual((row['lane'], row['decision'], row['locked_until']), ('human', 'approve', '2026-11-17'))
        self.assertTrue(row['lane_reason'].startswith('already created on 2026-10-20'), row['lane_reason'])
        item_row = next(r for r in plan['human_review'][-1]['rows'] if r['row_id'] == BUNDLE[0])
        self.assertTrue(item_row['lane_reason'].startswith('already created on 2026-10-20'))  # on the item, read-only
        held = read_json(os.path.join(self.run_dir, 'payloads', 'held', 'rows.json'))
        self.assertIn(BUNDLE[0], held['1_new_campaigns.json'])
        review = read_json(os.path.join(self.run_dir, 'payloads', 'review', 'rows.json'))
        self.assertNotIn(BUNDLE[0], [rid for ids in review.values() for rid in ids])
        out = self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        self.assertEqual(self.approved_files(), {})
        reasons = {s['row_id']: s['reason'] for s in out['skipped']}
        self.assertEqual(reasons[BUNDLE[0]], self.CREATED)
        self.assertEqual(set(reasons), set(BUNDLE))
        self.assertEqual((out['locks_released'], {d['id'] for d in self.product()['decisions']}), (0, set(BUNDLE)))

    def test_a_creation_is_matched_by_its_search_not_its_row_id(self):
        """A reused exact campaign for a search already created is a creation again; a Sponsored Brands video campaign
        for it is not the same creation."""
        reuse = dict(type='Reuse exact campaign', row_id='Reuse exact campaign:107::blank cards', keyword='blank cards',
                     campaign='Cards - Exact SKC - blank cards', campaign_id='107', role='Invest', new=0.7, budget=10, tos=0,
                     lane='human', modelled_spend_month=50, opportunity=100)
        video = dict(type='New SB video campaign', row_id='New SB video campaign:::blank cards', keyword='blank cards',
                     campaign='Cards - SB video 1', role='Invest', new=0.7, budget=10, lane='human')
        lock = dict(id='New exact campaign:::blank cards', what='approve', by='Lee', on='2026-10-19', until='2026-11-17',
                    direction='other', kind='create', search='blank cards', created_on='2026-10-20')
        plan = self.synthetic_run([reuse, video], decisions=[lock])
        plan['summary'][0]['planned_invest_month_start'] = 0.0  # what the product invests already; only C3 holds it
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        out = self.run_cmd([dec(reuse['row_id'], 'approve'), dec(video['row_id'], 'approve')])
        self.assertEqual(out['skipped'], [dict(row_id=reuse['row_id'], reason=self.CREATED)])
        self.assertEqual(list(self.approved_files()), ['7_sb_new_campaigns.json'])
        # once the lock has run out, the search is planned (and approved) as any other
        self.edit_product(decisions=[dict(lock, until='2026-10-18')])
        out = self.run_cmd([dec(reuse['row_id'], 'approve')], discard_unapplied=True)
        self.assertEqual((out['skipped'], list(self.approved_files())), ([], ['2_reuse_specs.json']))

    def test_a_creation_this_run_already_applied_is_never_emitted_again(self):
        """This run's own record counts by search too (a creation applied from auto/ or review/ has no row to match)."""
        reuse = dict(type='Reuse exact campaign', row_id='Reuse exact campaign:107::blank cards', keyword='blank cards',
                     campaign='Cards - Exact SKC - blank cards', campaign_id='107', role='Invest', new=0.7, budget=10, tos=0,
                     lane='human')
        new = dict(reuse, type='New exact campaign', row_id='New exact campaign:::blank cards', campaign_id=None)
        self.synthetic_run([new, reuse])
        write_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'),
                   {new['row_id']: dict(date='2026-10-20', folder='auto')})
        out = self.run_cmd([dec(reuse['row_id'], 'approve')])
        self.assertEqual(out['skipped'], [dict(row_id=reuse['row_id'], reason=self.CREATED)])

    def test_a_folder_that_would_create_a_search_already_created_is_refused_before_it_goes_out(self):
        """C3 with C4's check: last week's approvals were settled after this run was planned, so its auto/ or review/ still
        holds a creation `applied` has since locked. The check before the apply (--dry-run) refuses it; when it already
        went out, --record-anyway records it."""
        created = dict(id=BUNDLE[0], what='approve', by='Lee', on='2026-10-19', until='2026-11-17', direction='other',
                       kind='create', search='blank cards', created_on='2026-10-20')
        for shadow, folder in ((True, 'review'), (False, 'auto')):
            with self.subTest(folder=folder):
                self.plan_run(shadow=shadow)
                self.assertIn(BUNDLE[0], [r for ids in read_json(os.path.join(self.run_dir, 'payloads', folder,
                                                                               'rows.json')).values() for r in ids])
                self.edit_product(decisions=[created])
                for dry in (True, False):
                    with self.assertRaises(SystemExit) as cm:
                        self.run_applied(folder, date='2026-10-21', dry_run=dry)
                    message = str(cm.exception.code)
                    self.assertIn(f'these rows of payloads/{folder}/ create a search already created: {BUNDLE[0]} (on '
                                  '2026-10-20)', message)
                    self.assertIn('--record-anyway', message)
                self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
                out = self.run_applied(folder, date='2026-10-21', record_anyway=True)
                self.assertGreater(out['recorded'], 0)
                self.assertTrue(out['warnings'])
                os.remove(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'))

    def test_a_stale_approved_folder_cannot_create_a_search_twice(self):
        """R2 (the re-review's q6): the bundle sits in approved/, and meanwhile another folder created 'blank cards' and was
        recorded (a create lock). Applying approved/ now would create it twice, so the check before the apply (--dry-run)
        and the record itself refuse, as they do for auto/ and review/; --record-anyway records what already went out."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        made = dict(id=BUNDLE[0], what='approve', by='Lee', on='2026-10-20', until='2026-11-17', direction='other',
                    kind='create', search='blank cards', created_on='2026-10-21')
        self.edit_product(decisions=[made])
        before = self.raw_product()
        for dry in (True, False):
            with self.subTest(dry_run=dry):
                with self.assertRaises(SystemExit) as cm:
                    self.run_applied('approved', date='2026-10-22', dry_run=dry)
                message = str(cm.exception.code)
                self.assertIn(f'these rows of payloads/approved/ create a search already created: {BUNDLE[0]} (on 2026-10-21)',
                              message)
                self.assertIn('--record-anyway', message)
                self.assertIn('--discard-unapplied', message)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
        self.assertEqual(self.raw_product(), before)
        out = self.run_applied('approved', date='2026-10-22', record_anyway=True)
        self.assertEqual(out['recorded'], len(BUNDLE))
        self.assertTrue(any('checks were skipped' in w for w in out['warnings']))

    def test_approved_recorded_again_is_not_refused_for_its_own_creation(self):
        """The rows this run already recorded are exempt: its own create lock is not 'another folder made it'."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE])
        self.run_applied('approved', date='2026-10-20')
        out = self.run_applied('approved', date='2026-10-22')
        self.assertEqual((out['recorded'], out['already']), (0, len(BUNDLE)))
        # G4: the check before an apply refuses the folder that went out, though (it is never applied again)
        with self.assertRaises(SystemExit) as cm:
            self.run_applied('approved', date='2026-10-22', dry_run=True)
        self.assertIn('this folder went out on 2026-10-20', str(cm.exception.code))

    def test_a_locked_row_that_is_not_a_bid_or_pause_is_read_only(self):
        """B9 covers bid and pause rows only. A refused promotion stays on the item; approving it again sends nothing of its
        bundle (not even the pause, a pause row), and the refusal keeps holding."""
        refused = dict(id=BUNDLE[0], what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='other')
        self.plan_run(decisions=[refused])
        out = self.run_cmd([dec(r, 'approve', by='Kim') for r in BUNDLE])
        self.assertEqual(self.approved_files(), {})
        reasons = {s['row_id']: s['reason'] for s in out['skipped']}
        self.assertEqual(reasons[BUNDLE[0]], 'held by an earlier decision (declined by Kim on 2026-10-12) until 2026-11-09: '
                                             'only a bid or pause row can be approved again while it is held')
        # the negatives are read-only too (held with the promotion); the pause could be approved again alone, but not out
        # of its bundle
        self.assertEqual({reasons[rid] for rid in BUNDLE[2:]}, {reasons[BUNDLE[0]]})
        self.assertEqual(reasons['Pause keyword:2'], "part of a promotion that can't go out: blank cards")
        self.assertEqual((self.locks()[BUNDLE[0]], out['locks_released']), (refused, 0))

    def test_a_locked_bid_row_can_still_be_approved_again(self):
        refused = dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-12', until='2026-11-09', direction='down')
        self.plan_run(decisions=[refused])
        out = self.run_cmd([dec('Bid change:3', 'approve', by='Kim')])
        self.assertEqual((out['skipped'], out['approved']), ([], 1))


# =====================================================================================================================
class BusinessRecordTest(Base):
    """The product file's decisions keep a business row's shopper kind (final review, before-merge tests, 2026-10-21):
    approvals' decline locks (lock_entries) and applied's locks carry owner_kind 'business', and a business New exact
    keyword's creation is known by its search under the business prefix (created_searches, C3), so it holds only the
    business creation of that search, never the consumer one."""

    NEW_KEYWORD = dict(type='New exact keyword', row_id='New exact keyword:110:210:office cards', keyword='office cards',
                       match='exact', role='Invest', campaign='Cards - B2B - Search Terms with Sales - Exact - 1',
                       campaign_id='110', ad_group_id='210', owner_kind='business', current=None, new=1.2, tos=50, tos_now=0,
                       budget=10, budget_now=10, campaign_tos=50, campaign_budget=10, lane='human', modelled_spend_month=50,
                       opportunity=200)

    def run_with(self, changes, **product_over):
        plan = self.synthetic_run(changes, **product_over)
        plan['summary'][0]['planned_invest_month_start'] = 0.0  # what the product invests already; nothing else holds a row
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        return plan

    def test_a_business_decline_is_recorded_with_its_shopper_kind(self):
        self.run_with([business('zebra cards', '902', 10, 1000)])
        self.run_cmd([dec('Business invest:902', 'decline')])
        lock = self.locks()['Business invest:902']
        self.assertEqual((lock['what'], lock['by'], lock['owner_kind']), ('decline', 'Lee', 'business'))

    def test_a_business_keyword_creation_is_known_under_the_business_prefix(self):
        # week 1: the New exact keyword approved and applied: applied writes its create lock with owner_kind 'business'
        self.run_with([dict(self.NEW_KEYWORD)])
        self.run_cmd([dec(self.NEW_KEYWORD['row_id'], 'approve')])
        self.run_applied('approved', date='2026-10-20')
        lock = self.locks()[self.NEW_KEYWORD['row_id']]
        self.assertEqual((lock['kind'], lock['search'], lock['owner_kind'], lock['created_on']),
                         ('create', 'office cards', 'business', '2026-10-20'))
        self.assertEqual(dashboard.created_searches(self.product(), {}, {}, datetime(2026, 10, 21).date()),
                         {'created:keyword:business:office cards': '2026-10-20'})
        # week 2: the same keyword planned again is never emitted again; the consumer creation of office cards goes out
        decisions = self.product()['decisions']
        self.run_dir = os.path.join(self.tmp, 'week 2')
        consumer = promo('office cards', 50, 100)
        self.run_with([dict(self.NEW_KEYWORD), consumer], decisions=decisions)
        out = self.run_cmd([dec(self.NEW_KEYWORD['row_id'], 'approve'), dec(consumer['row_id'], 'approve')])
        self.assertEqual(out['skipped'], [dict(row_id=self.NEW_KEYWORD['row_id'], reason='already created on 2026-10-20; nothing to do')])
        self.assertEqual(sorted(self.approved_files()), ['1_new_campaigns.json', '1b_new_skc_specs.json'])


# =====================================================================================================================
class SavedReviewsTest(Base):
    """B2 (I1): `reviews` saves the dashboard's decisions into the next run's folder, for the planner."""

    NOW = datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc)  # 09:30 on the 19th in Singapore

    def run_reviews(self, entries, save):
        a = argparse.Namespace(asin=ASIN, save=save)
        out = io.StringIO()
        with unittest.mock.patch.object(dashboard, 'call', return_value=entries) as call, \
                unittest.mock.patch.object(dashboard, 'utc_now', return_value=self.NOW), \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), contextlib.redirect_stdout(out):
            dashboard.cmd_reviews(a)
        self.reviews_call = call
        return json.loads(out.getvalue())

    def test_reviews_saves_the_list_as_it_comes_with_the_product_and_the_time(self):
        """C6: the file says whose decisions they are and when they were read, so plan.py can refuse an old or foreign one."""
        entries = [dec('Bid change:1', 'approve', seen=None), dec('Bid change:3', 'decline', item_id='bids-2026-10-12', seen=None),
                   dec('Bid change:5', 'decline', seen=dict(current=1.5, new=0.25, new_capped=None))]
        save = os.path.join(self.tmp, 'next run', 'reviews.json')
        out = self.run_reviews(entries, save)
        self.assertEqual(read_json(save), dict(asin=ASIN, saved_at='2026-10-19T01:30:00Z', entries=entries))
        # the decisions, then Growth's status clicks (saved beside them as item_statuses.json; test_dashboard_growth)
        self.assertEqual([c.args[:2] for c in self.reviews_call.call_args_list],
                         [('GET', f'/api/reviews/{ASIN}'), ('GET', f'/api/items/{ASIN}')])
        self.assertEqual((out['saved'], out['saved_at'], out['decisions'], out['declines']), (save, '2026-10-19T01:30:00Z', 3, 2))
        self.assertEqual(out['items'], {ITEM: 2, 'bids-2026-10-12': 1})

    def test_reviews_refuses_an_answer_that_is_not_a_list(self):
        save = os.path.join(self.tmp, 'reviews.json')
        with self.assertRaises(SystemExit) as cm:
            self.run_reviews({'error': 'x'}, save)
        self.assertIn('/api/reviews', str(cm.exception.code))
        self.assertFalse(os.path.exists(save))

    def test_the_reviews_command_is_wired_into_the_cli(self):
        save = os.path.join(self.tmp, 'reviews.json')
        argv = ['dashboard.py', 'reviews', '--asin', ASIN, '--save', save]
        with unittest.mock.patch.object(sys, 'argv', argv), \
                unittest.mock.patch.object(dashboard, 'call', return_value=[]), \
                unittest.mock.patch.object(dashboard, 'utc_now', return_value=self.NOW), \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(io.StringIO()):
            dashboard.main()
        self.assertEqual(read_json(save), dict(asin=ASIN, saved_at='2026-10-19T01:30:00Z', entries=[]))


# =====================================================================================================================
class AppliedMarkingTest(Base):
    """B7 (I8): a page published --state applied marks only the rows that went out as applied; every other row says why
    it didn't, by its lane."""

    def build(self, state='applied'):
        with unittest.mock.patch.object(dashboard, 'config', return_value=self.shared):
            doc, _ = dashboard.build_doc(ASIN, self.run_dir, state, 'Weekly run', '2026-10-20', 'Kim', self.data)
        return doc

    def marks(self, doc):
        """{row_id: (status, note)}: the page's change rows are the plan's, in plan order."""
        text = doc['run']['text']
        out = {}
        for x, row in zip(self.plan['changes'], doc['run']['changes']):
            out[x['row_id']] = (row.get('status'), text[row['note']] if 'note' in row else None)
        return out

    def mark_applied(self, row_ids, day='2026-10-20'):
        write_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'), {rid: day for rid in row_ids})

    def test_a_shadow_run_marks_each_row_by_what_happened_to_it(self):
        lock = dict(id='Pause target:301', what='decline', by='Kim', on='2026-10-19', until='2026-11-16', direction='pause')
        self.plan_run(decisions=[lock])
        self.mark_applied(['Bid change:1', 'Bid change:3'])
        write_json(os.path.join(self.run_dir, 'reviews.json'), [dec('Bid change:5', 'decline', by='Lee', seen=None)])
        marks = self.marks(self.build())
        self.assertEqual(marks['Bid change:1'], ('applied', None))
        self.assertEqual(marks['Bid change:3'], ('applied', None))
        self.assertEqual(marks['Bid change:5'], ('declined', 'Not applied: declined by Lee'))
        self.assertEqual(marks['Bid change:6'], ('held', 'Not applied: held until the next run'))
        self.assertEqual(marks['Pause target:301'], ('held', 'Not applied: held by an earlier decision (Kim, 2026-10-19)'))
        waiting = ('waiting for a person', 'Not applied: waiting for a person')
        self.assertEqual(marks['Bid change:4'], waiting)  # a shadow run's automatic row needs a yes like any other
        self.assertEqual(marks['Negative exact:102:202:thank you cards'], waiting)
        doc = self.build()
        self.assertEqual(doc['just_changed']['headline'], 'Weekly run, applied Oct 20: 2 bid changes')

    def test_an_enabled_run_marks_automatic_rows_by_the_apply(self):
        self.plan_run(shadow=False, run=T.HEAD_TERM)
        auto = [rid for ids in read_json(os.path.join(self.run_dir, 'payloads', 'auto', 'rows.json')).values() for rid in ids]
        self.mark_applied([rid for rid in auto if rid != 'Bid change:5'])
        marks = self.marks(self.build())
        self.assertEqual(marks['Bid change:1'], ('applied', None))
        self.assertEqual(marks['Bid change:5'], ('not applied', 'Not applied: not recorded as applied'))
        self.assertEqual(marks[HEAD_PROMOTION], ('waiting for a person', 'Not applied: waiting for a person'))
        self.assertEqual(marks['Bid change:6'], ('held', 'Not applied: held until the next run'))

    def test_a_lanes_run_without_the_record_marks_nothing_applied(self):
        """C7 (I8, the re-review's probe): a shadow week where nobody approved anything has no applied_rows.json. Its page
        marks every row by its lane, none applied, and the headline doesn't count them as applied."""
        self.plan_run()
        doc = self.build()
        marks = self.marks(doc)
        self.assertNotIn('applied', {status for status, _ in marks.values()})
        self.assertEqual(marks['Bid change:6'], ('held', 'Not applied: held until the next run'))
        self.assertEqual(marks['New exact campaign:::blank cards'], ('waiting for a person', 'Not applied: waiting for a person'))
        self.assertNotIn('applied Oct 20', json.dumps(doc['just_changed']))

    def test_an_older_run_without_the_record_marks_every_row_applied(self):
        """A plan from before the lanes (no summary.lanes) keeps the old marking."""
        self.plan_run()
        del self.plan['summary'][0]['lanes']
        write_json(os.path.join(self.run_dir, 'plan.json'), self.plan)
        self.assertEqual({m for m in self.marks(self.build()).values()}, {('applied', None)})

    def test_a_proposed_page_is_proposed_whatever_was_recorded(self):
        self.plan_run()
        self.mark_applied(['Bid change:1'])
        self.assertEqual({m for m in self.marks(self.build('proposed')).values()}, {('proposed', None)})


# =====================================================================================================================
class GlobTest(Base):
    def test_stale_files_are_cleared_from_a_run_folder_with_glob_characters_in_its_name(self):
        self.run_dir = os.path.join(self.tmp, 'run [1]')
        self.synthetic_run([bid_row('K1')])
        approved = os.path.join(self.run_dir, 'payloads', 'approved')
        write_json(os.path.join(approved, 'stale.json'), [])
        write_json(os.path.join(approved, 'rows.json'), {})
        self.run_cmd([dec('Bid change:K1', 'decline')])
        self.assertEqual(os.listdir(approved), [])


# =====================================================================================================================
class AppliedWindowTest(Base):
    def test_all_payload_folders_pass_calendar_check_on_weekends_without_recording(self):
        for folder in ('auto','review','approved'):
            with self.subTest(folder=folder):
                shutil.rmtree(self.run_dir,ignore_errors=True)
                self.plan_run(shadow=folder!='auto')
                if folder=='approved':self.run_cmd([dec('Bid change:1','approve')])
                before=self.raw_product()
                out=self.run_applied(folder,dry_run=True,now='2026-10-24T08:00:00Z')
                self.assertGreater(out['recorded'],0)
                self.assertEqual(self.raw_product(),before)
                self.assertFalse(os.path.exists(os.path.join(self.run_dir,'payloads','applied_rows.json')))

    def test_future_or_missing_legacy_date_is_not_an_execution_hold(self):
        for stamp in ('2026-10-26',None):
            plan=self.plan_run()
            plan['summary'][0]['apply_after']=stamp
            write_json(os.path.join(self.run_dir,'plan.json'),plan)
            out=self.run_applied('review',dry_run=True,now='2026-10-24T08:00:00Z')
            self.assertGreater(out['recorded'],0)

    def test_invalid_cli_clock_still_rejected(self):
        self.plan_run()
        with self.assertRaises(SystemExit) as cm:
            self.run_applied('review',dry_run=True,now='Saturday')
        self.assertIn('--now must be an ISO time in UTC',str(cm.exception.code))



# =====================================================================================================================
class PartialRecordTest(Base):
    """E5 (I5): `applied --rows` records only the rows that went out (read back), a subset of the folder's rows.json, with
    their locks; the rest stays unrecorded, so approvals still refuses until it is recorded or discarded."""

    def hand_out(self):
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE] + [dec('Bid change:1', 'approve')])
        handed = [rid for ids in read_json(os.path.join(self.approved_dir, 'rows.json')).values() for rid in ids]
        self.assertEqual(sorted(set(handed)), sorted(BUNDLE + ['Bid change:1']))
        return list(dict.fromkeys(handed))

    def test_rows_records_only_the_named_rows_and_their_locks(self):
        handed = self.hand_out()
        out = self.run_applied('approved', date='2026-10-20', rows=[f'{BUNDLE[0]},{BUNDLE[1]}'])
        self.assertEqual(read_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')),
                         {rid: dict(date='2026-10-20', folder='approved') for rid in BUNDLE[:2]})
        self.assertEqual((out['rows'], out['recorded'], out['partial']), (2, 2, True))
        self.assertEqual(out['left_unrecorded'], [rid for rid in handed if rid not in BUNDLE[:2]])
        locks = self.locks()
        self.assertEqual(set(locks), set(BUNDLE[:2]))
        self.assertEqual((locks[BUNDLE[0]]['kind'], locks[BUNDLE[0]]['search']), ('create', 'blank cards'))
        self.assertEqual(locks[BUNDLE[1]]['what'], 'approve')
        # approvals still refuses: three rows of approved/ are not recorded
        self.assertIn('payloads/approved/ still holds 3 rows not recorded as applied', self.refused())
        # once the rest went out too, recording the folder takes them; the first two keep their day
        self.run_applied('approved', date='2026-10-21')
        record = read_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'))
        self.assertEqual({rid: e['date'] for rid, e in record.items()},
                         dict({rid: '2026-10-21' for rid in handed}, **{rid: '2026-10-20' for rid in BUNDLE[:2]}))

    def test_rows_may_be_given_as_separate_values(self):
        self.hand_out()
        out = self.run_applied('approved', date='2026-10-20', rows=[BUNDLE[0], ' ' + BUNDLE[1] + ' '])
        self.assertEqual(out['recorded'], 2)

    def test_rows_the_folder_does_not_hold_are_refused_and_nothing_is_written(self):
        self.hand_out()
        before = self.raw_product()
        for rows, says in (([f'{BUNDLE[0]},Bid change:999'], "--rows names rows payloads/approved/rows.json doesn't hold: "
                                                                 'Bid change:999'),
                           ([' , '], '--rows names no rows')):
            with self.subTest(rows=rows):
                with self.assertRaises(SystemExit) as cm:
                    self.run_applied('approved', date='2026-10-20', rows=rows)
                self.assertIn(says, str(cm.exception.code))
                self.assertTrue(str(cm.exception.code).endswith('Nothing recorded.'))
                self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
                self.assertEqual(self.raw_product(), before)

    def test_the_rows_flag_is_wired_into_the_cli(self):
        self.hand_out()
        argv = ['dashboard.py', 'applied', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--folder', 'approved',
                '--date', '2026-10-20', '--rows', f'{BUNDLE[0]},{BUNDLE[1]}']
        out = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), \
                unittest.mock.patch.object(dashboard, 'call', return_value=[]), \
                unittest.mock.patch.object(dashboard, 'config', return_value=self.shared), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            dashboard.main()
        self.assertEqual(json.loads(out.getvalue())['recorded'], 2)


# =====================================================================================================================
class FixGTest(Base):
    """Fix G: the residuals of the final re-review (G1 approvals' record, G3-G5)."""

    def applied_record(self):
        path = os.path.join(self.run_dir, 'payloads', 'applied_rows.json')
        return read_json(path) if os.path.exists(path) else {}

    def check_refused(self, folder, **over):
        with self.assertRaises(SystemExit) as cm:
            self.run_applied(folder, dry_run=True, **over)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    # --- G1 (N1): the stop-loss decision is on record for log_invest --------------------------------------------------
    def stop_loss_run(self):
        stop = dict(type='Stop-loss review', row_id='Stop-loss review:::gold cards', keyword='gold cards', role='Invest',
                    current=None, new=None, lane='human')
        self.synthetic_run([stop, bid_row('1')], levels={stop['row_id']: 'Lee'})
        return stop['row_id']

    def test_an_approved_row_with_no_payload_is_in_the_runs_approved_decisions(self):
        """A stop-loss review has no payload: approvals lists it under no_payload and now also records who approved it in
        payloads/approved_decisions.json, which log_invest reads as the person's step-down."""
        stop = self.stop_loss_run()
        out = self.run_cmd([dec(stop, 'approve', at='2026-10-20T02:00:00Z')])
        self.assertEqual((out['approved'], out['no_payload']), (0, [dict(row_id=stop, type='Stop-loss review')]))
        self.assertEqual(self.approved_files(), {})
        self.assertEqual(self.record(), {stop: dict(by='Lee', on='2026-10-20', at='2026-10-20T02:00:00Z')})
        # with a payload row too, both are recorded
        out = self.run_cmd([dec(stop, 'approve'), dec('Bid change:1', 'approve', by='Sam')], discard_unapplied=True)
        self.assertEqual(set(self.record()), {stop, 'Bid change:1'})

    def test_an_approval_that_does_not_count_is_not_recorded(self):
        stop = self.stop_loss_run()
        out = self.run_cmd([dec(stop, 'approve', by='Sam')])  # a Lee row
        self.assertEqual(out['skipped'], [dict(row_id=stop, reason="needs Lee's approval (approved by Sam)")])
        self.assertEqual(self.record(), {})
        out = self.run_cmd([dec(stop, 'approve')], dry_run=True)  # a dry run writes nothing
        self.assertEqual(self.record(), {})

    # --- G3 (N3): a Sponsored Brands video build is created once -------------------------------------------------------
    def sb_run(self):
        a = dict(type='New SB video campaign', row_id='New SB video campaign:::blank cards', keyword='blank cards',
                 campaign='Cards - SB video 1', role='Invest', new=0.7, budget=10, lane='human')
        b = dict(a, row_id='New SB video campaign:::zebra cards', keyword='zebra cards', new=0.6)
        c = dict(a, row_id='New SB video campaign:::gold cards', keyword='gold cards', new=0.5)  # same campaign, undecided
        self.synthetic_run([a, b, c])
        return a['row_id'], b['row_id'], c['row_id']

    def test_a_partly_recorded_sb_build_is_create_locked_whole_and_never_handed_out_again(self):
        """The re-review's probe (N3): approved/ holds one Sponsored Brands video build (its campaign, ad group, video ad
        and two keywords). Through MAP the campaign, ad group, ad and keyword A are made; keyword B fails. Recording A with
        --rows create-locks the whole build and says to add B by hand. The check refuses the folder, and
        --discard-unapplied hands out nothing of the build: not B, and not the third keyword of the same campaign."""
        a, b, c = self.sb_run()
        self.run_cmd([dec(a, 'approve'), dec(b, 'approve')])
        [spec] = self.approved_files()['7_sb_new_campaigns.json']
        self.assertEqual([k['keywordText'] for k in spec['keywords']], ['blank cards', 'zebra cards'])
        out = self.run_applied('approved', date='2026-10-20', rows=[a])
        self.assertEqual(out['add_by_hand'], [dict(campaign='Cards - SB video 1', keywords=['zebra cards'], row_ids=[b])])
        self.assertIn('add these keywords by hand to the campaign that now exists (Cards - SB video 1): zebra cards',
                      ' '.join(out['warnings']))
        self.assertEqual(self.applied_record(), {a: dict(date='2026-10-20', folder='approved')})
        creates = {d['id']: d for d in self.product()['decisions'] if d.get('kind') == 'create'}
        self.assertEqual(set(creates), {a, b})
        self.assertEqual({rid: (d['search'], d['campaign'], d['created_on'], d.get('by_hand')) for rid, d in creates.items()},
                         {a: ('blank cards', 'Cards - SB video 1', '2026-10-20', None),
                          b: ('zebra cards', 'Cards - SB video 1', '2026-10-20', True)})
        # the check refuses to apply the folder again (G4), whatever rows it is asked about
        for rows in (None, [b]):
            with self.subTest(rows=rows):
                self.assertIn('this folder partly went out on 2026-10-20', self.check_refused('approved', rows=rows,
                                                                                               date='2026-10-21'))
        # --discard-unapplied hands out nothing of the build
        out = self.run_cmd([dec(a, 'approve'), dec(b, 'approve'), dec(c, 'approve')], discard_unapplied=True)
        self.assertEqual(self.approved_files(), {})
        reasons = {s['row_id']: s['reason'] for s in out['skipped']}
        self.assertEqual(reasons[a], 'already applied on 2026-10-20')
        for rid in (b, c):
            self.assertEqual(reasons[rid], 'its campaign Cards - SB video 1 was created on 2026-10-20; add the keyword to it '
                                           'by hand (the build is never handed out again)')

    def test_a_build_whose_campaign_exists_is_refused_by_the_check_from_any_folder(self):
        """Another folder of the run holding a keyword of a campaign that now exists (here review/, by hand) is refused by
        the check before the apply: applying it would create the campaign a second time."""
        a, b, c = self.sb_run()
        self.run_cmd([dec(a, 'approve')])
        self.run_applied('approved', date='2026-10-20')
        review = os.path.join(self.run_dir, 'payloads', 'review')
        write_json(os.path.join(review, 'rows.json'), {'7_sb_new_campaigns.json': [c]})
        write_json(os.path.join(review, '7_sb_new_campaigns.json'), [{'campaign': {'name': 'Cards - SB video 1'}}])
        message = self.check_refused('review', date='2026-10-21')
        self.assertIn(f'{c} (its campaign Cards - SB video 1 was created on 2026-10-20)', message)

    def test_a_whole_sb_build_recorded_needs_nothing_by_hand(self):
        a, b, c = self.sb_run()
        self.run_cmd([dec(a, 'approve'), dec(b, 'approve')])
        out = self.run_applied('approved', date='2026-10-20')
        self.assertEqual((out['add_by_hand'], out['partial']), ([], False))
        self.assertFalse([d for d in self.product()['decisions'] if d.get('by_hand')])

    # --- G4 (m1): a partly recorded folder is never applied again -----------------------------------------------------
    def test_a_partly_recorded_folder_is_refused_by_the_check(self):
        """The re-review's probes (m1): a folder recorded in part with --rows still holds every row; its check refuses it, in
        auto/ and review/ as in approved/, and the record's warning no longer invites a re-apply."""
        for folder in ('auto', 'review', 'approved'):
            with self.subTest(folder=folder):
                shutil.rmtree(self.run_dir, ignore_errors=True)
                self.plan_run(shadow=folder != 'auto')
                if folder == 'approved':
                    self.run_cmd([dec(r, 'approve') for r in BUNDLE] + [dec('Bid change:1', 'approve')])
                rows = read_json(os.path.join(self.run_dir, 'payloads', folder, 'rows.json'))
                handed = list(dict.fromkeys(rid for ids in rows.values() for rid in ids))
                self.assertGreater(len(handed), 1)
                out = self.run_applied(folder, date='2026-10-20', rows=[handed[0]])
                warning = ' '.join(out['warnings'])
                self.assertNotIn('record them with --rows once they went out', warning)
                if folder == 'approved':
                    self.assertIn('If they did not go out, run approvals with --discard-unapplied', warning)
                else:
                    self.assertIn(f"Don't apply payloads/{folder}/ again: the rest waits for next week's plan", warning)
                before = self.raw_product()
                message = self.check_refused(folder, date='2026-10-21', now='2026-10-21T15:00:00Z')
                self.assertEqual(message, (
                    f"payloads/{folder}/: this folder partly went out on 2026-10-20; don't apply it again — re-plan in a new "
                    f'run folder or settle with approvals (1 of its {len(handed)} rows recorded in '
                    'payloads/applied_rows.json). Nothing recorded.'))
                self.assertEqual(self.raw_product(), before)
                self.assertEqual(list(self.applied_record()), [handed[0]])

    def test_a_folder_recorded_whole_is_refused_by_the_check_too(self):
        self.plan_run()
        self.run_applied('review', date='2026-10-20')
        message = self.check_refused('review', date='2026-10-21', now='2026-10-21T15:00:00Z')
        self.assertTrue(message.startswith("payloads/review/: this folder went out on 2026-10-20 (every row is recorded in "
                                           "payloads/applied_rows.json); don't apply it again."), message)

    def test_an_approved_folder_handed_out_again_after_a_partial_record_passes_the_check(self):
        """After --discard-unapplied, approved/ holds only the rows nobody recorded: that folder never went out."""
        self.plan_run()
        self.run_cmd([dec(r, 'approve') for r in BUNDLE] + [dec('Bid change:1', 'approve')])
        self.run_applied('approved', date='2026-10-20', rows=[BUNDLE[0], BUNDLE[1]])
        self.run_cmd([dec(r, 'approve') for r in BUNDLE] + [dec('Bid change:1', 'approve')], discard_unapplied=True)
        out = self.run_applied('approved', date='2026-10-21', dry_run=True, now='2026-10-21T15:00:00Z')
        self.assertEqual((out['rows'], out['already']), (1, 0))

    # --- G5 (m2): a rank-experiment hold can't be approved, even through the API -------------------------------------
    def test_an_approval_on_a_row_a_rank_experiment_holds_is_held(self):
        experiment = dict(locked_until='further notice', decision='experiment', decided_by=None, decided_on=None)
        pause = dict(type='Pause keyword', row_id='Pause keyword:2', keyword='search 2', keyword_id='2', campaign_id='C1',
                     ad_group_id='A1', current=0.4, new=None, lane='human', **experiment)
        self.synthetic_run([bid_row('1', **experiment), pause, bid_row('3')])
        self.edit_product(decisions=[dict(id='Bid change:1', what='decline', by='Sam', on='2026-10-12', until='2026-11-09')])
        out = self.run_cmd([dec('Bid change:1', 'approve', by='Kim'), dec('Pause keyword:2', 'approve', by='Kim'),
                            dec('Bid change:3', 'approve')])
        self.assertEqual(out['skipped'], [
            dict(row_id='Bid change:1', reason='a rank experiment holds this search until its review'),
            dict(row_id='Pause keyword:2', reason='a rank experiment holds this search until its review')])
        self.assertEqual([r['keywordId'] for r in self.approved_files()['4_bids_01.json']], ['3'])
        self.assertNotIn('3_pauses.json', self.approved_files())
        self.assertEqual(self.locks()['Bid change:1']['what'], 'decline')  # the held approval releases nothing
        # an item row that says the experiment holds it is enough (a plan change without the stamp)
        plan = read_json(os.path.join(self.run_dir, 'plan.json'))
        for c in plan['changes']:
            c.pop('decision', None)
        plan['human_review'][0]['rows'][0].update(locked_until='further notice', lock_decision='experiment')
        write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        out = self.run_cmd([dec('Bid change:1', 'approve', by='Kim')], discard_unapplied=True)
        self.assertEqual(out['skipped'], [dict(row_id='Bid change:1',
                                               reason='a rank experiment holds this search until its review')])


if __name__ == '__main__':
    unittest.main()
