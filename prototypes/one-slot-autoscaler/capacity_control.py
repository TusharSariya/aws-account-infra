#!/usr/bin/env python3
"""Persist pause intent; explicitly arm primary cold resume without immediately waking it."""
import argparse
from contextlib import ExitStack
import fcntl
import json
import uuid
import consolidate as cluster
import consolidation_policy as policy
import reconcile as runtime
import cold_start


def control(action,slots):
    cluster.check_cluster()
    if action=='resume' and slots!=['primary']:
        raise RuntimeError('Only primary cold resume is implemented; secondary stays paused')
    directories={'primary':cluster.BASE/'slot-primary','secondary':cluster.BASE/'slot-state'}
    with ExitStack() as stack:
        for slot in sorted(slots):
            lock=stack.enter_context((directories[slot]/'lifecycle.lock').open('a'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if action=='pause':
            for slot in slots:(directories[slot]/'maintenance').touch(mode=0o600)
            return {'paused':slots}
        if runtime.SLOT!='primary':raise RuntimeError('Select HOMELAB_PROTOTYPE_SLOT=primary')
        journal=runtime.STATE/'retirement.json'
        previous=json.loads(journal.read_text()) if journal.exists() else {}
        if previous.get('phase') in ('checking','shutdown-committed','creating','blocked') or cold_start.read().get('phase') in ('waking','blocked'):
            raise RuntimeError('Unfinished operation requires operator review')
        if json.loads((runtime.STATE/'desired.json').read_text()).get('target')!=1:
            raise RuntimeError('Cold resume requires a preserved worker target')
        node=policy.selected_nodes(cluster.get('nodes')).get('primary')
        if node is None:raise RuntimeError('Preserved primary node missing')
        state={'phase':'armed','name':node['metadata']['name'],'uid':node['metadata']['uid'],
               'systemUUID':str(uuid.UUID(node['status']['nodeInfo']['systemUUID']))}
        power=runtime.PowerController(runtime.CONFIG,'primary').get_power().power
        if power!='off':raise RuntimeError('Cold resume requires confirmed powered-off host')
        cold_start.save(state)
        (runtime.STATE/'maintenance').unlink(missing_ok=True)
        return {'resumed':['primary'],'mode':'wait-for-matching-demand'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('pause','resume'))
    parser.add_argument('--slot',choices=('primary','secondary','all'),default='all')
    args=parser.parse_args();slots=['primary','secondary'] if args.slot=='all' else [args.slot]
    print(json.dumps(control(args.action,slots)))


if __name__=='__main__':main()
