# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Small, shared article contract. Task-specific design never relaxes college rules."""
REVIEW_ROLES = ('编辑', '校对', '审阅')
BODY_ROLES = {'body', 'callout', 'card-panel'}
IMAGE_ROLES = {'brand-header', 'brand-closing', 'brand-footer', 'content-image', 'card-badge'}
KNOWN_ROLES = BODY_ROLES | IMAGE_ROLES | {'image', 'blank', 'heading', 'title', 'subtitle', 'kicker', 'caption', 'credit', 'credit-note', 'divider-mark', 'endnote', 'callout-head', 'card-number', 'card-ribbon'}
PLACEHOLDERS = {'', '待确认', '待补充', '待填写', '未定', '姓名', 'TBD', 'None'}


def credit_contract(data):
    raw = data.get('credit_rows', data.get('credits'))
    if isinstance(raw, dict):
        if set(raw) != set(REVIEW_ROLES):
            raise ValueError('Exactly 编辑、校对、审阅 are required')
        rows = [{'label': role, 'value': raw[role]} for role in REVIEW_ROLES]
        extra = data.get('extra_credits', [])
    elif isinstance(raw, list):
        rows, extra = raw[:3], raw[3:] + data.get('extra_credits', [])
    else:
        raise ValueError('credits must identify the three review roles')
    if len(rows) != 3 or [x.get('label') for x in rows] != list(REVIEW_ROLES):
        raise ValueError('Review roles must be 编辑、校对、审阅 in order')
    mode = data.get('mode', 'final')
    if mode not in ('draft', 'final'):
        raise ValueError('mode must be draft or final')
    clean, missing = [], []
    for row in rows + extra:
        label, value = row.get('label'), row.get('value')
        if not isinstance(label, str) or not label.strip() or not isinstance(value, str):
            raise ValueError('Credit labels and values must be strings')
        label, value = label.strip(), value.strip()
        if len(clean) >= 3 and label in REVIEW_ROLES:
            raise ValueError('Additional credit notes cannot duplicate a review role')
        if value in PLACEHOLDERS:
            missing.append(label)
            if mode == 'final':
                raise ValueError('Unconfirmed credit: ' + label)
        clean.append({'label': label, 'value': value})
    return clean[:3], clean[3:], missing
