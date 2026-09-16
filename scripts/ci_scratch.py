"""Recommend scratch from cold/warm observations; never silently adopt a budget."""
import argparse
import json
import math
import re
from pathlib import Path

GIB = 1024**3


def validate_measurement(item):
    """Reject incomplete receipts rather than turn estimates into catalog budgets."""
    for field in ('runner_id', 'evidence', 'job', 'platform', 'run_id'):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError('Measurement identity required: ' + field)
    if not re.fullmatch(r'[0-9a-f]{40}', item.get('source_revision', '')):
        raise ValueError('Full source revision required')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', item.get('image_digest', '')):
        raise ValueError('Immutable runner image digest required')
    for field in ('peak_bytes', 'memory_peak_bytes', 'upstream_bytes'):
        if type(item.get(field)) is not int or item[field] < 0:
            raise ValueError('Nonnegative measured bytes required: ' + field)
    for field in ('cpu_peak_cores', 'elapsed_seconds'):
        value = item.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Finite nonnegative measurement required: ' + field)
    if (item.get('success') is not True or
            item.get('scope') != 'whole-pod-including-images-layers-temporary-and-logs' or
            item.get('coverage') != 'before-checkout-through-cleanup'):
        raise ValueError('Successful whole-Pod measurement from before checkout through cleanup required')


def comparable(items):
    for field in ('source_revision', 'image_digest', 'job', 'platform'):
        if len({item[field] for item in items}) != 1:
            raise ValueError('Measurements must share ' + field)


def recommend(observations):
    if len(observations) != 3 or [x['cache'] for x in observations] != ['cold', 'warm', 'warm']:
        raise ValueError('One cold and two warm runs required, in that order')
    for item in observations:
        validate_measurement(item)
    comparable(observations)
    if len({x['runner_id'] for x in observations}) != 3:
        raise ValueError('Use three distinct fresh disposable runners')
    if not observations[0].get('cold_content_evidence'):
        raise ValueError('Evidence that tested content was absent from Nexus required')
    peak = max(item['peak_bytes'] for item in observations)
    # ceil((peak * 1.25 + 1 GiB) / GiB), with integer arithmetic.
    return max(2, (peak * 5 + 4 * GIB + 4 * GIB - 1) // (4 * GIB))


def validate_adoption(observations, verification):
    size = recommend(observations)
    validate_measurement(verification)
    comparable([*observations, verification])
    if verification['peak_bytes'] > size * GIB:
        raise ValueError('Verification exceeded the declared scratch limit')
    if (verification.get('success') is not True or not verification.get('evidence') or
            verification.get('declared_gib') != size or
            verification.get('runner_id') in {x['runner_id'] for x in observations} or
            not verification.get('runner_id')):
        raise ValueError('Successful fresh runner verification at the recommended limit required')
    return size * 1024


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    value = json.loads(args.evidence.read_text())
    result = {'recommended_gib': recommend(value['observations']), 'adoptable': False}
    if 'verification' in value:
        result.update(scratch_mib=validate_adoption(value['observations'], value['verification']), adoptable=True)
    print(json.dumps(result))
