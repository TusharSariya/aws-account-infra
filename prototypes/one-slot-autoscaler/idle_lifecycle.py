#!/usr/bin/env python3
"""Primary prototype idle retirement/recreation. No physical host power-off."""
import argparse
import fcntl
import json
import time
import reconcile as runtime
import consolidate as observer
import consolidation_policy as policy


class Cancelled(RuntimeError):
    pass


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write(path, value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)


def journal_path():return runtime.STATE/'retirement.json'


def pending():
    return policy.demand(observer.get('pods'),observer.get('workloads'))


class RetirementGate:
    def __init__(self,name,uid):
        if runtime.SLOT!='primary':raise RuntimeError('Automatic retirement is primary-prototype only')
        self.name=name;self.uid=uid
        self.state={'phase':'checking','name':name,'uid':uid,'rewakeQueued':False,
                    'trigger':'idle-window'}
        previous=read(journal_path())
        if previous.get('phase') in ('checking','shutdown-committed','blocked'):
            raise RuntimeError('Unfinished retirement requires operator review')

    def check(self):
        node=observer.get('node',name=self.name)
        if (node['metadata']['uid']!=self.uid or node['spec'].get('providerID')!=runtime.PROVIDER or
            'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels',{})):
            raise RuntimeError('Worker identity changed')
        blockers=[]
        if (not policy.ready(node) or not node['spec'].get('unschedulable') or
            node['metadata'].get('annotations',{}).get(policy.OWNER)!=self.uid):blockers.append('not-owned-ready-cordon')
        if (runtime.STATE/'maintenance').exists():blockers.append('maintenance')
        pods=observer.get('pods')
        if any(policy.active(p) and p['spec'].get('nodeName')==self.name and not policy.baseline(p) for p in pods):blockers.append('active-workloads')
        if any(v['spec']['nodeName']==self.name for v in observer.get('volumeattachments')):blockers.append('volume-attachments')
        blockers.extend(policy.demand(pods,observer.get('workloads')))
        idle=read(observer.STATE/'idle.json').get(runtime.SLOT,{})
        now=time.time()
        if (idle.get('uid')!=self.uid or idle.get('phase')!='retirement-eligible' or
                idle.get('idleSeconds')!=policy.IDLE_SECONDS or
                not 0<=now-idle.get('lastObserved',0)<=45 or
                not isinstance(idle.get('idleSince'),(int,float)) or
                now-idle['idleSince']<policy.IDLE_SECONDS or idle.get('blockers')):
            blockers.append('idle-window-not-proven')
        if blockers:raise Cancelled(','.join(blockers))

    def prepare(self):
        self.check();write(journal_path(),self.state)

    def commit(self):
        self.check()
        self.state['phase']='shutdown-committed'
        write(journal_path(),self.state)  # Persist before an ambiguous shutdown response is possible.

    def poll(self):
        if pending():
            self.state['rewakeQueued']=True
            write(journal_path(),self.state)

    def finish(self):
        self.poll()
        if self.state['rewakeQueued']:write(runtime.STATE/'desired.json',{'target':1})
        self.state['phase']='wake-requested' if self.state['rewakeQueued'] else 'retired'
        write(journal_path(),self.state)

    def fail(self,exc):
        if self.state['phase']=='shutdown-committed':
            self.state['phase']='blocked';self.state['error']=type(exc).__name__
            write(journal_path(),self.state)
            return
        # Before shutdown, release only the exact cordon we own. Failure is visible.
        node=observer.get('node',name=self.name)
        if node['metadata']['uid']==self.uid:observer.cordon(node,False)
        self.state['phase']='canceled' if isinstance(exc,Cancelled) else 'blocked'
        self.state['error']=str(exc);write(journal_path(),self.state)


def tick():
    if runtime.SLOT!='primary':raise RuntimeError('Continuous lifecycle is primary-prototype only')
    observer.check_cluster()
    candidate=None
    with (runtime.STATE/'lifecycle.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=read(journal_path());phase=state.get('phase')
        if phase in ('checking','shutdown-committed','blocked'):
            # A normal live retirement holds this lock. Acquiring it in an unfinished
            # phase means the operation was interrupted; never infer it is safe to retry.
            if phase!='blocked':write(journal_path(),{**state,'phase':'blocked','error':'interrupted-operation'})
            return
        if (runtime.STATE/'maintenance').exists():return
        target=read(runtime.STATE/'desired.json').get('target')
        if target==1 and phase in ('retired','wake-requested'):
            write(journal_path(),{**state,'phase':'creating'})
            try:
                runtime.reconcile()
                write(journal_path(),{**state,'phase':'ready','rewakeQueued':False})
            except Exception as exc:
                write(journal_path(),{**state,'phase':'blocked','error':type(exc).__name__})
                raise
            return
        if phase=='creating':
            write(journal_path(),{**state,'phase':'blocked','error':'interrupted-creation'});return
        idle=read(observer.STATE/'idle.json').get(runtime.SLOT,{})
        if target==1 and idle.get('phase')=='retirement-eligible':
            candidate=(idle['node'],idle['uid'])
    if candidate:
        # retire reacquires the same lifecycle lock and revalidates all observations.
        from retire import retire
        try:retire(*candidate,idle=True)
        except Cancelled:pass


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    while True:
        try:tick()
        except BlockingIOError:pass
        if args.once:break
        time.sleep(10)


if __name__=='__main__':
    # retire imports this module for its gate; keep one exception-class identity.
    from idle_lifecycle import main as canonical_main
    canonical_main()
