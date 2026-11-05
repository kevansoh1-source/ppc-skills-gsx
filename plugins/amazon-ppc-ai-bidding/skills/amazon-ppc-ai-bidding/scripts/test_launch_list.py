"""launch_list.py: the launch block from the DataDive niche (docs/superpowers/specs/2026-10-21-keyword-selection-by-data-stage-
design.md, section 4.3).

The niche is fixtures/niche_gel_pens.json: 30 rows cut from the gel pens niche (PCAEwf4c8H, dived 2026-08-19) as
`get_niche_keywords` returns them, relevancy kept as DataDive's k/13 fractions, plus one planted row, the one-word head
`pens` (100000 searches, relevancy 0.85), so the head-term rule has something to skip.
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock

import launch_list as L

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixtures', 'niche_gel_pens.json')
TODAY = '2026-10-22'
NICHE_ID = 'PCAEwf4c8H'

CFG = {'launch': {'rank_count': 5, 'sqp_min_queries': 10, 'min_relevancy': 0.5, 'amazon_top_rank': 20}}


def niche(without=()):
    """The fixture as the saved get_niche_keywords response; `without` drops rows by keyword."""
    with open(FIXTURE, encoding='utf-8') as fh:
        saved = json.load(fh)
    saved['keywords'] = [k for k in saved['keywords'] if k['keyword'] not in without]
    return saved


def rec(keyword, rank):
    """One get_amazon_ads_ad_group_keyword_recs row, as far as the launch list reads it."""
    return {'keyword': keyword, 'translation': keyword, 'userSelectedKeyword': False, 'searchTermImpressionRank': rank,
            'searchTermImpressionShare': 1.0, 'recId': 'x', 'bidInfo': []}


def by_search(block):
    return {s['search']: s for s in block['searches']}


class LaunchListTests(unittest.TestCase):
    def block(self, **kw):
        return L.build_block(niche(), CFG, TODAY, **kw)

    def test_order_is_volume_times_relevancy(self):
        # the planted head 'pens' (100000 x 0.85 = 85000) leads the full list; without it the real first two are
        # colorful pens (63688 x 8/13 = 39192) and pens colored (19872 x 12/13 = 18343)
        full = self.block()['searches']
        self.assertEqual([(s['search'], s['score']) for s in full[:3]],
                         [('pens', 85000), ('colorful pens', 39192), ('pens colored', 18343)])
        rest = L.build_block(niche(without=('pens',)), CFG, TODAY)['searches']
        self.assertEqual([(s['search'], s['score']) for s in rest[:2]],
                         [('colorful pens', 39192), ('pens colored', 18343)])
        scores = [s['score'] for s in rest]
        self.assertEqual(scores, sorted(scores, reverse=True))
        first = rest[0]
        self.assertEqual((first['volume'], first['source']), (63688, 'datadive'))
        self.assertAlmostEqual(first['relevancy'], 8 / 13)

    def test_min_relevancy_leaves_out(self):
        block = self.block()
        out = {r['search']: r['why_out'] for r in block['left_out']}
        self.assertEqual(out['smooth writing pens no smudge'], 'relevancy 0.308 under 0.5')
        self.assertEqual(out['retractable gel pens'], 'relevancy 0.385 under 0.5')
        listed = by_search(block)
        for gone in out:
            self.assertNotIn(gone, listed)
        for s in block['searches']:
            self.assertGreaterEqual(s['relevancy'], 0.5)

    def test_variants_fold_to_highest_volume(self):
        # the keeper is the spelling with the higher score (volume x relevancy): 'gel pens colored' has the most volume
        # of the pair (23683 against 21729) but scores 14574 against 15043, so it folds into 'colored gel pens'
        listed = by_search(self.block())
        self.assertNotIn('gel pens colored', listed)
        self.assertEqual(listed['colored gel pens']['folded'], ['gel pens colored'])
        self.assertNotIn('colored pen', listed)
        self.assertEqual(listed['pens colored']['folded'], ['colored pen'])
        self.assertEqual(listed['colorful pens']['folded'], [])
        # a plural is a variant too, and the fold is not a left-out
        self.assertNotIn('gel pens colored', [r['search'] for r in self.block()['left_out']])

    def test_median_set_skips_heads_and_variants(self):
        block = self.block()
        searches = block['searches']
        self.assertEqual(searches[0]['search'], 'pens')   # first by score, yet never in the median set
        median = [s['search'] for s in searches if s['set'] == 'median']
        self.assertEqual(median, ['colorful pens', 'pens colored', 'colored gel pens', 'colored ink pens',
                                  'colored pens for note taking'])
        head = by_search(block)['pens']
        self.assertEqual(head['set'], 'shared')
        self.assertIn('one token', head['why'])
        self.assertTrue(all(s['set'] == 'shared' for s in searches if s['search'] not in median))
        self.assertNotIn('why', by_search(block)['colorful pens'])

    def test_amazon_adds_to_shared_only(self):
        recs = [rec('gel pens multicolor', 4),     # two tokens, top 20, not listed: joins
                rec('pen', 2),                     # one token
                rec('colored gel pens', 3),        # already listed
                rec('gel pens colored', 5),        # a variant of a listed search (the folded one)
                rec('neon pens', 25),              # ranked 25: beyond the top 20
                rec('metallic pens', None),        # no impression rank: never qualifies
                rec('glitter gel pens', 20)]       # the 20th is still in
        block = self.block(recs=recs)
        added = [s for s in block['searches'] if s['set'] == 'amazon']
        self.assertEqual([s['search'] for s in added], ['gel pens multicolor', 'glitter gel pens'])
        for s in added:
            self.assertEqual((s['source'], s['volume'], s['relevancy'], s['score']), ('amazon', None, None, None))
        # Amazon's rows come after the niche rows and change nothing before them
        plain = self.block()['searches']
        self.assertEqual(block['searches'][:len(plain)], plain)
        self.assertEqual(sum(s['set'] == 'median' for s in block['searches']), 5)

    def test_amazon_never_re_adds_a_left_out_search(self):
        # the niche list ranks above Amazon's (spec 4.2): 'retractable gel pens' is left out at relevancy 0.385, so Amazon's
        # rank 3 does not bring it back, nor does a close variant of it ('gel pens retractable', a reorder)
        block = self.block(recs=[rec('retractable gel pens', 3), rec('gel pens retractable', 6),
                                 rec('gel pens multicolor', 4)])
        self.assertIn('retractable gel pens', [r['search'] for r in block['left_out']])
        listed = by_search(block)
        self.assertNotIn('retractable gel pens', listed)
        self.assertNotIn('gel pens retractable', listed)
        self.assertEqual([s['search'] for s in block['searches'] if s['set'] == 'amazon'], ['gel pens multicolor'])

    def test_negated_rec_not_added(self):
        recs = [rec('blue gel pens', 7), rec('gel pens multicolor', 4)]
        negate = lambda t: 'wrong colour: blue only' if t == 'blue gel pens' else None
        without = self.block(recs=recs)
        self.assertIn('blue gel pens', by_search(without))
        with_negate = self.block(recs=recs, negate=negate)
        self.assertNotIn('blue gel pens', by_search(with_negate))
        self.assertIn('gel pens multicolor', by_search(with_negate))

    def test_roots_proposal(self):
        block = self.block()
        # the rows at 0.9 or more are pens colored, colored ink pens and gel pens colored ink: they share 'pens'
        # ('pens' and 'pen' read alike) and 'colored'
        self.assertEqual(L.propose_roots(block['searches']), ['pens', 'colored'])
        self.assertEqual(block['roots'], ['pens', 'colored'])
        self.assertEqual(self.block(roots=['gel', 'ink'])['roots'], ['gel', 'ink'])
        self.assertEqual(L.propose_roots([{'search': 'pens', 'relevancy': 0.85}]), [])

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, 'launch_block.json')
        self.run_cli(tmp.name, '--out', out, '--roots', 'pens|ink')
        with open(out, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['roots'], ['pens', 'ink'])

    def test_block_shape_and_source(self):
        block = self.block(niche_id=NICHE_ID)
        self.assertEqual(list(block), ['date', 'source', 'niche_id', 'dive_date', 'searches', 'left_out', 'roots',
                                       'qualifiers'])
        self.assertIsNone(block['date'])
        self.assertEqual(block['niche_id'], NICHE_ID)
        self.assertEqual(block['dive_date'], '2026-08-19')
        for part in (NICHE_ID, '2026-08-19', TODAY):
            self.assertIn(part, block['source'])
        self.assertEqual(block['qualifiers'], [])
        for s in block['searches']:
            self.assertEqual(set(s) - {'why'}, {'search', 'volume', 'relevancy', 'score', 'set', 'source', 'folded'})
        self.assertIn('niche id not given', self.block()['source'])
        self.assertIsNone(self.block()['niche_id'])

    def test_sheet_rows_compete_by_volume_alone(self):
        extra = [{'search': 'gel pens for school', 'volume': 20000, 'source': 'Launch Targets tab'},
                 {'search': 'colored pens', 'volume': 1000, 'source': 'Launch Targets tab'}]
        block = self.block(extra=extra)
        listed = by_search(block)
        row = listed['gel pens for school']
        self.assertEqual((row['source'], row['relevancy'], row['score'], row['volume']), ('sheet', None, 20000, 20000))
        # 20000 beats pens colored (18343) and takes the second median slot; the planted head still leads
        self.assertEqual([s['search'] for s in block['searches'][:3]], ['pens', 'colorful pens', 'gel pens for school'])
        self.assertEqual(row['set'], 'median')
        # 'colored pens' (1000) is a plural of 'colored pen' (6501) and a reorder of 'pens colored' (18343): it folds
        # under the better spelling, whichever source it came from
        self.assertNotIn('colored pens', listed)
        self.assertEqual(listed['pens colored']['folded'], ['colored pen', 'colored pens'])
        self.assertIn('Launch Targets tab', block['source'])
        # a sheet row has no relevancy, so it is never left out for it, and never counts toward the roots
        self.assertEqual(block['roots'], ['pens', 'colored'])

    def run_cli(self, tmp, *extra_args, recs=None, relevance=None):
        """main() on the fixture, with a temp data folder holding a product file whose relevance block negates 'blue'."""
        data = os.path.join(tmp, 'data')
        os.makedirs(os.path.join(data, 'asins'), exist_ok=True)
        with open(os.path.join(data, 'asins', 'B0TESTASIN.json'), 'w', encoding='utf-8') as fh:
            json.dump({'relevance': relevance or {'negate_phrase': {'blue': 'wrong colour: blue only'}}}, fh)
        argv = ['launch_list.py', '--asin', 'B0TESTASIN', '--niche', FIXTURE, '--niche-id', NICHE_ID, '--today', TODAY,
                '--data', data]
        if recs is not None:
            recs_path = os.path.join(tmp, 'keyword_recs.json')
            with open(recs_path, 'w', encoding='utf-8') as fh:
                json.dump([{'type': 'text', 'text': json.dumps(recs)}], fh)  # the tool-result wrapper
            argv += ['--recs', recs_path]
        argv += list(extra_args)
        buf = io.StringIO()
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(buf):
            L.main()
        return buf.getvalue()

    def test_cli_writes_the_block_and_prints_the_table(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, 'run', 'launch_block.json')
        printed = self.run_cli(tmp.name, '--out', out, '--extra', 'gel pens for school:20000',
                               recs=[rec('blue gel pens', 7), rec('gel pens multicolor', 4)])
        with open(out, encoding='utf-8') as fh:
            block = json.load(fh)
        self.assertEqual(block['niche_id'], NICHE_ID)
        listed = by_search(block)
        self.assertIn('gel pens multicolor', listed)        # Amazon's addition
        self.assertNotIn('blue gel pens', listed)           # negated through the product file's relevance block
        self.assertEqual(listed['gel pens for school']['source'], 'sheet')
        lines = printed.splitlines()
        header = next(line for line in lines if line.startswith('search'))
        columns = header.split()
        self.assertEqual(columns[:5], ['search', 'volume', 'relevancy', 'score', 'set'])
        row = next(line for line in lines if re.match(r'colorful pens\s{2,}\d', line))
        for cell in ('63688', '0.615', '39192', 'median'):
            self.assertIn(cell, row)
        self.assertIn('Left out', printed)
        left = next(line for line in lines if 'retractable gel pens' in line and 'under' in line)
        self.assertIn('relevancy 0.385 under 0.5', left)
        self.assertIn('pens, colored', printed)             # the proposed roots

    def test_cli_refuses_a_file_that_is_not_the_pull(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, 'launch_block.json')
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(tmp.name, '--out', out, recs={'items': []})       # a dict where the list should be
        self.assertIn('not a saved get_amazon_ads_ad_group_keyword_recs', str(caught.exception))
        self.assertFalse(os.path.exists(out))
        bad_niche = os.path.join(tmp.name, 'niche.json')
        with open(bad_niche, 'w', encoding='utf-8') as fh:
            json.dump([{'keyword': 'pens'}], fh)
        with self.assertRaises(SystemExit) as caught:
            L.load_niche(bad_niche)
        self.assertIn('not a saved get_niche_keywords response', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
