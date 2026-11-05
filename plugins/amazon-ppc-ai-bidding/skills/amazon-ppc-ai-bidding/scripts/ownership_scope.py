"""Keep mixed-ASIN campaigns wholly outside a product's AI writes (Kim, 2026-10-23).

Opt-in product schema: ownership_scope = {mode: 'exclusive_campaigns', asin, approved_by: 'Kim',
approved_on: ISO date, excluded_campaign_ids: [...], excluded_ad_group_ids: [...]}.
An absent scope preserves the established product-wide workflow. A present but malformed scope fails closed.
Whole shared campaigns stay with SI, including paused groups. Exclusions apply to every write and approval path.

SI group operations need exact scope_entities [{campaign_id, ad_group_id}] (or those two fields on the row).
Product blacklist/whitelist changes additionally need shared_product_lists_unaffected=True and scope_evidence;
listing only exclusive groups cannot prove a product-level list change leaves shared SI consumers unaffected.
New campaign rows need the requested ASIN explicitly. Placeholder child rows need new_campaign_row_id linking
to such a parent in the same plan. This guard does not replace fresh live membership and eligibility checks.
"""
import datetime as dt

NEW_CAMPAIGNS = frozenset(('New exact campaign', 'New SB video campaign', 'New harvest campaign'))
SI_TYPES = frozenset(('Scale Insights rules', 'Scale Insights setup'))
ID_KEYS = {'campaign_id': 'campaign', 'campaignId': 'campaign',
           'ad_group_id': 'ad_group', 'adGroupId': 'ad_group'}


def _id(value):
    return str(value) if not isinstance(value, bool) and str(value).isdigit() and int(str(value)) > 0 else None


def _ids(value):
    if not isinstance(value, list) or any(_id(x) is None for x in value):
        raise ValueError('exclusion IDs must be lists of positive Amazon IDs')
    return {_id(x) for x in value}


def _scope(product):
    if 'ownership_scope' not in (product or {}):
        return None, None
    s = product['ownership_scope']
    try:
        if not isinstance(s, dict) or s.get('mode') != 'exclusive_campaigns':
            raise ValueError('mode must be exclusive_campaigns')
        if not s.get('asin') or s['asin'] != product.get('asin'):
            raise ValueError('scope ASIN must match the product')
        if s.get('approved_by') != 'Kim':
            raise ValueError('scope needs Kim approval')
        dt.date.fromisoformat(s['approved_on'])
        return dict(asin=s['asin'], campaign=_ids(s['excluded_campaign_ids']),
                    ad_group=_ids(s['excluded_ad_group_ids'])), None
    except (KeyError, TypeError, ValueError) as e:
        return None, f'ownership scope is unreadable: {e}'


def _references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ID_KEYS and item is not None:
                yield ID_KEYS[key], item
            elif isinstance(item, (dict, list)):
                yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def _advertised_asins(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'asin' and item:
                yield item
            elif key == 'asins':
                yield from item if isinstance(item, list) else [item]
            elif isinstance(item, (dict, list)):
                yield from _advertised_asins(item)
    elif isinstance(value, list):
        for item in value:
            yield from _advertised_asins(item)


def reason(row, product, changes=()):
    """Return a hard hold reason, or None. Never infer exclusivity from an ASIN in a campaign name."""
    scope, problem = _scope(product)
    if problem or scope is None:
        return problem
    if not isinstance(row, dict) or not row:
        return 'ownership scope: row is missing from the plan'
    if row.get('asin') and row['asin'] != scope['asin']:
        return 'ownership scope: row ASIN does not match the requested product'
    for kind, value in _references(row):
        if _id(value) in scope[kind]:
            return f'ownership scope: {kind} {value} remains solely SI-managed; no AI writes'
    typ = row.get('type')
    if typ in NEW_CAMPAIGNS:
        if row.get('asin') != scope['asin']:
            return 'ownership scope: new campaign needs the requested ASIN explicitly'
        if any(asin != scope['asin'] for asin in _advertised_asins(row)):
            return 'ownership scope: new campaign must advertise only the requested ASIN'
        return None
    if typ in SI_TYPES:
        text = ' '.join(str(row.get(k) or '') for k in ('keyword', 'item', 'how')).lower()
        if any(word in text for word in ('blacklist', 'whitelist', 'rescue')):
            if row.get('shared_product_lists_unaffected') is not True or not row.get('scope_evidence'):
                return 'ownership scope: product-list changes need proof that shared SI consumers are unaffected'
        entities = row.get('scope_entities')
        if entities is None and row.get('campaign_id') and row.get('ad_group_id'):
            entities = [row]
        if not isinstance(entities, list) or not entities:
            return 'ownership scope: broad SI operation needs exact scoped campaign and ad-group IDs'
        for entity in entities:
            if not isinstance(entity, dict) or not _id(entity.get('campaign_id')) or not _id(entity.get('ad_group_id')):
                return 'ownership scope: every SI entity needs exact campaign and ad-group IDs'
        return None
    if _id(row.get('campaign_id')):
        return None
    parent_id = row.get('new_campaign_row_id')
    parent = next((c for c in changes if parent_id and c.get('row_id') == parent_id), None)
    placeholders = all(value in ('<campaignId>', '<adGroupId>') for _, value in _references(row))
    existing_target = any(row.get(key) for key in ('keyword_id', 'target_id', 'ad_id'))
    if placeholders and not existing_target and parent and parent.get('type') in NEW_CAMPAIGNS and reason(parent, product) is None:
        if row.get('asin') == scope['asin']:
            return None
    return 'ownership scope: existing-entity write needs an exact campaign ID; unlinked placeholders are held'


def blocked_rows(changes, product):
    return {c.get('row_id'): why for c in changes if (why := reason(c, product, changes))}


def _target_references(value):
    keys = {'keywordId': 'keyword', 'keyword_id': 'keyword', 'targetId': 'target', 'target_id': 'target',
            'adId': 'ad', 'ad_id': 'ad'}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item is not None:
                yield keys[key], str(item)
            elif isinstance(item, (dict, list)):
                yield from _target_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _target_references(item)


def _skus(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'sku' and item is not None:
                yield item
            elif isinstance(item, (dict, list)):
                yield from _skus(item)
    elif isinstance(value, list):
        for item in value:
            yield from _skus(item)


def payload_reason(payload, product, changes):
    """Validate actual file IDs against scoped plan rows, including bid files with no parent IDs.

    These are scope checks, not a substitute for live readback. Unknown IDs cannot borrow a safe plan row's label.
    A raw placeholder is allowed only inside a matching same-ASIN planned new-campaign specification.
    """
    s, problem = _scope(product)
    if problem or s is None:
        return problem
    allowed = [c for c in changes if reason(c, product, changes) is None and not c.get('ownership_scope_blocked')]
    parents = {kind: {str(v) for c in allowed for k, v in _references(c) if k == kind and _id(v)}
               for kind in ('campaign', 'ad_group')}
    targets = {kind: {v for c in allowed for k, v in _target_references(c) if k == kind}
               for kind in ('keyword', 'target', 'ad')}
    creations = {c.get('campaign') for c in allowed if c.get('type') in NEW_CAMPAIGNS and c.get('campaign')}
    rows = payload if isinstance(payload, list) else [payload]
    if not rows:
        return None
    for row in rows:
        if not isinstance(row, dict) or not row:
            return 'ownership scope: actual payload has no identifiable write scope'
        if any(asin != s['asin'] for asin in _advertised_asins(row)):
            return 'ownership scope: actual payload advertises another ASIN'
        if any(sku != product.get('sku') for sku in _skus(row)):
            return 'ownership scope: actual payload has another or unverified SKU'
        if row.get('type') in SI_TYPES:
            if row.get('row_id') not in {c.get('row_id') for c in allowed}:
                return 'ownership scope: actual SI checklist row is not an allowed plan row'
            if problem := reason(row, product, changes):
                return problem
        campaign = row.get('campaign')
        new_name = (campaign.get('name') if isinstance(campaign, dict) else campaign) or row.get('name')
        new = isinstance(new_name, str) and new_name in creations
        references = list(_references(row))
        target_refs = list(_target_references(row))
        for kind, value in references:
            if _id(value) in s[kind]:
                return f'ownership scope: actual payload touches excluded {kind} {value}'
            if new and value in ('<campaignId>', '<adGroupId>'):
                continue
            if not _id(value) or str(value) not in parents[kind]:
                return f'ownership scope: actual payload {kind} {value} is not in an allowed plan row'
        for kind, value in target_refs:
            if value not in targets[kind]:
                return f'ownership scope: actual payload {kind} {value} has no allowed plan ownership'
        if not references and not target_refs and not new:
            return 'ownership scope: actual payload has no verified parent or planned creation'
    return None
