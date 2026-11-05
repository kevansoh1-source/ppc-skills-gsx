"""si_changes.py: the morning check for hand changes in Scale Insights on AI products (decision 155, 2026-10-27)."""
import json
import os
import tempfile
import unittest

import si_changes


def change(asin, action='bid', source='manual', actor='teammate1@example.com', delta=0.05, t='2026-10-27T02:26:00Z'):
    return dict(TimestampUtc=t, Source=source, Actor=actor, Action=action, Asin=asin, Delta=delta)


class SiChangesTest(unittest.TestCase):
    products = {'B0AI000001': 'Bookmarks', 'B0AI000002': 'Pens'}

    def test_a_manual_import_on_an_ai_product_is_flagged(self):
        page = dict(Changes=[change('B0AI000001', 'import'), change('B0AI000001', 'bid', delta=-0.1),
                             change('B0AI000001', 'bid', source='automation'),       # a rule: the 202 Brake or 203 dayparting
                             change('B0SIRULED1', 'import'),                          # a Scale Insights product: not ours
                             change('B0AI000002', 'other', actor='teammate2@example.com')])   # a list edit: counted only
        out = si_changes.check([page, page], self.products)    # a page read twice is counted once
        self.assertEqual(sorted(out['flagged']), ['B0AI000001'])
        f = out['flagged']['B0AI000001']
        self.assertEqual((f['changes'], f['actions'], f['raised'], f['lowered']), (2, {'import': 1, 'bid': 1}, 1, 1))
        self.assertEqual(out['lists_only'], {'B0AI000002': 1})
        self.assertIn('B0AI000001 Bookmarks: 2 (1 bid, 1 import) by teammate1@example.com', si_changes.message(out))

    def test_since_and_nothing_flagged(self):
        page = dict(Changes=[change('B0AI000001', t='2026-10-20T00:00:00Z')])
        out = si_changes.check([page], self.products, since='2026-10-26')
        self.assertEqual((out['flagged'], si_changes.message(out)), ({}, ''))

    def test_the_ai_products_come_from_the_product_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'asins'))
            for asin, reg in (('B0AI000001', dict(bid_owner='AI')), ('B0SIRULED1', dict(stage='queued'))):
                with open(os.path.join(d, 'asins', asin + '.json'), 'w') as fh:
                    json.dump(dict(asin=asin, name='x', registry=reg), fh)
            self.assertEqual(list(si_changes.ai_products(d)), ['B0AI000001'])


if __name__ == '__main__':
    unittest.main()
