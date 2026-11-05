"""What people see of the review queue (decision 97, Kim 2026-10-22): decisions only, without the AI's research text."""
import copy
import unittest

import human_review


def item(phase, kind='listing', **extra):
    base = dict(id=f'{kind}-{phase}', kind=kind, title='Thinking of You cards: conversion below market',
                reason='9 sampled searches convert below the market.',
                action='AI first: classify query relevance and inspect Amazon competitors.',
                source='Scale Insights SQP', window='SQP up to 12 weeks', status='open',
                ai_review=dict(phase=phase, as_of='2026-10-22', missing=['Read live Amazon.com results for: thinking of you cards'],
                               assessment=dict(rationale='A long research rationale.', counterevidence='Long counterevidence.',
                                               recommendation='Refresh the slot-2 image to show the card designs.',
                                               confidence='medium', conversion_verdict='listing_candidate'),
                               opportunities=[dict(query='thinking of you cards', index=0.6)],
                               competitors=[dict(asin='B000000001')]))
    base.update(extra)
    return base


def bids():
    return dict(id='bids-2026-10-22', kind='bid', title='Bid changes, 2026-10-22', reason='Weekly run.',
                action=human_review.BIDS_ACTION, source='plan.json', window='weekly', status='open',
                ai_review=dict(phase='human_ready'),
                rows=[dict(row_id='r1', type='Bid change', approval_required='owner')])


class PeopleView(unittest.TestCase):
    def test_only_decisions_are_published(self):
        product = dict(human_review=[item('research'), item('monitor'), item('human_ready'), bids()])
        doc = {'card': {}}
        human_review.attach(doc, product)
        self.assertEqual([i['id'] for i in doc['human_review']], ['listing-human_ready', 'bids-2026-10-22'])
        self.assertEqual(doc['card']['human_review'], doc['human_review'])
        self.assertEqual(doc['card']['human_review_count'], 2)
        self.assertEqual(doc['card']['ai_research_count'], 1)

    def test_a_decision_shows_the_recommendation_not_the_research(self):
        shown = human_review.for_people(human_review.validate([item('human_ready')]))[0]
        self.assertEqual(shown['action'], 'Refresh the slot-2 image to show the card designs.')
        self.assertEqual(shown['ai_review'], dict(phase='human_ready', as_of='2026-10-22', missing=[],
                                                  assessment=dict(recommendation='Refresh the slot-2 image to show the card designs.',
                                                                  confidence='medium')))
        self.assertEqual(shown['approval_required'], 'Lee')

    def test_the_product_file_keeps_the_research(self):
        items = human_review.validate([item('human_ready')])
        before = copy.deepcopy(items)
        human_review.for_people(items)
        self.assertEqual(items, before)

    def test_a_decision_without_a_recommendation_keeps_its_action(self):
        bare = item('human_ready')
        del bare['ai_review']['assessment']['recommendation']
        shown = human_review.for_people(human_review.validate([bare]))[0]
        self.assertEqual(shown['action'], bare['action'])
        self.assertEqual(shown['ai_review']['assessment'], dict(confidence='medium'))

    def test_the_bids_item_is_shown_unchanged(self):
        items = human_review.validate([bids()])
        self.assertEqual(human_review.for_people(items), items)

    def test_closed_decisions_stay_for_history(self):
        closed = item('human_ready', status='resolved')
        shown = human_review.for_people(human_review.validate([closed]))
        self.assertEqual([i['status'] for i in shown], ['resolved'])
        doc = {'card': {}}
        human_review.attach(doc, dict(human_review=[closed]))
        self.assertEqual(doc['card']['human_review_count'], 0)


if __name__ == '__main__':
    unittest.main()
