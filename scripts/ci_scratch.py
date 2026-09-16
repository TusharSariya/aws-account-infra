"""Recommend scratch from cold/warm observations; never silently adopt a budget."""
import argparse
import json
from pathlib import Path

GIB = 1024**3


def recommend(observations):
    if len(observations) != 3 or [x['cache'] for x in observations] != ['cold', 'warm', 'warm']:
        raise ValueError('One cold and two warm runs required, in that order')
    if len({x['runner_id'] for x in observations}) != 3:
        raise ValueError('Use three distinct fresh disposable runners')
    for item in observations:
        if (item.get('success') is not True or not item.get('evidence') or
                type(item['peak_bytes']) is not int or item['peak_bytes'] < 0 or
                item.get('scope') != 'whole-pod-including-images-layers-temporary-and-logs'):
            raise ValueError('Successful whole-Pod measurement and evidence required')
    peak = max(item['peak_bytes'] for item in observations)
    # ceil((peak * 1.25 + 1 GiB) / GiB), with integer arithmetic.
    return max(2, (peak * 5 + 4 * GIB + 4 * GIB - 1) // (4 * GIB))


def validate_adoption(observations, verification):
    size = recommend(observations)
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
