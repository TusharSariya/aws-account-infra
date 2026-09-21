from placement import priorities


def test_known_awake_beats_sleeping_even_secondary_tie_break():
    p=priorities({'primary':'on','secondary':'off'})
    assert p['prototype-primary']>p['prototype-secondary']


def test_awake_secondary_beats_sleeping_primary():
    p=priorities({'primary':'off','secondary':'on'})
    assert p['prototype-secondary']>p['prototype-primary']


def test_unknown_never_scores_like_known_awake_or_off():
    p=priorities({'primary':'off','secondary':'unknown'})
    assert p['prototype-primary']>p['prototype-secondary']>0


def test_deterministic_tie_prefers_secondary():
    for state in ('on','off','unknown'):
        p=priorities({'primary':state,'secondary':state})
        assert p['prototype-secondary']>p['prototype-primary']
