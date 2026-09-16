#!/usr/bin/env python3
"""Isolated live FIFO/CPU/RAM/cancellation proof; deletes only this run's Pods."""
import argparse
import json
import subprocess
import time
import uuid

IMAGE = 'python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--scenario', choices=['cpu','memory','ephemeral-storage','combined'], required=True)
    args = parser.parse_args()
    kube = ['kubectl','--kubeconfig',args.kubeconfig,'--request-timeout=30s']
    run_id = uuid.uuid4().hex[:12]
    created = []
    def run(arguments, value=None):
        return subprocess.check_output(kube + arguments, input=None if value is None else json.dumps(value).encode(), timeout=180)
    def workloads():
        return json.loads(run(['get','workloads.kueue.x-k8s.io','-A','-o','json']))['items']
    # This acceptance window must be explicitly quiesced first.
    if any(not any(c['type']=='Finished' and c['status']=='True' for c in w.get('status',{}).get('conditions',[])) for w in workloads()):
        raise ValueError('Quiesce AI, ARC and Argo before the contention acceptance window')
    def create(suffix, cpu, memory, seconds=600, scratch="16Mi"):
        name = 'queue-proof-' + run_id + '-' + suffix
        pod = {'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':'homelab-jobs','labels':{
            'homelab/acceptance-run':run_id,'kueue.x-k8s.io/queue-name':'argo','kueue.x-k8s.io/workload-priority-class':'homelab-compute'}},
            'spec':{'restartPolicy':'Never','terminationGracePeriodSeconds':1,'automountServiceAccountToken':False,'serviceAccountName':'homelab-job',
                    'schedulingGates':[{'name':'kueue.x-k8s.io/admission'}],
                    'securityContext':{'runAsNonRoot':True,'runAsUser':8737,'seccompProfile':{'type':'RuntimeDefault'}},
                    'containers':[{'name':'proof','image':IMAGE,'command':['python','-B','-c',f'import time; time.sleep({seconds})'],
                    'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                    'resources':{'requests':{'cpu':cpu,'memory':memory,'ephemeral-storage':scratch},'limits':{'cpu':cpu,'memory':memory,'ephemeral-storage':scratch}}}]}}
        obj = json.loads(run(['create','-f','-','-o','json'],pod));created.append((name,obj['metadata']['uid']))
        return name
    def observed(name):
        uid = dict(created)[name]
        owned = [w for w in workloads() if any(o['uid']==uid for o in w['metadata'].get('ownerReferences',[]))]
        if len(owned)!=1: return None
        w=owned[0]
        return any(c['type']=='Admitted' and c['status']=='True' for c in w.get('status',{}).get('conditions',[]))
    def wait(name, admitted):
        deadline=time.monotonic()+120
        while observed(name) is not admitted:
            if time.monotonic()>deadline: raise ValueError('Admission expectation not observed for '+name)
            time.sleep(2)
    def delete(name):
        run(['delete','pod',name,'-n','homelab-jobs','--wait=true','--timeout=90s'])
    try:
        budgets = {
            'cpu': [('4', '1Gi', '16Mi'), ('33.25', '77Gi', '16Mi')],
            'memory': [('100m', '32Gi', '16Mi'), ('100m', '140Gi', '16Mi')],
            'ephemeral-storage': [('100m', '64Mi', '30Gi'), ('100m', '64Mi', '40Gi')],
            'combined': [('4', '32Gi', '30Gi'), ('33.25', '140Gi', '40Gi')],
        }
        first, second = budgets[args.scenario]
        blocker=create('blocker', *first[:2], scratch=first[2])
        wait(blocker,True)
        older=create('older', *second[:2], scratch=second[2])
        wait(older,False)
        # Kubernetes creationTimestamp has second resolution; avoid an ordering tie.
        time.sleep(2)
        later=create('later','100m','64Mi');wait(later,False)
        # Observe head-of-line blocking across several reconciliation cycles.
        for _ in range(10):
            if observed(older) is not False or observed(later) is not False or observed(blocker) is not True:
                raise ValueError('StrictFIFO did not preserve existing work and block later work')
            time.sleep(2)
        delete(older)  # Cancels a waiting workload and allows the smaller follower.
        wait(later,True)
        delete(later)
        later=create('completion','100m','64Mi');wait(later,True)
        delete(blocker)
        delete(later)
        completed = create('normal', '33.25', '77Gi', seconds=30)
        wait(completed, True)
        follower = create('after-normal', '4', '16Gi')
        wait(follower, False)
        wait(follower, True)
        finished = json.loads(run(['get','pod',completed,'-n','homelab-jobs','-o','json']))
        if finished.get('status', {}).get('phase') != 'Succeeded':
            raise ValueError('Reservation released before observed successful termination')
        print('PASS: '+args.scenario+' exhaustion, strict FIFO and queued cancellation observed')
    finally:
        # Retain the UIDs to detect leaked Kueue reservations after Pod deletion.
        for name, _ in created:
            run(['delete','pod',name,'-n','homelab-jobs','--ignore-not-found=true','--wait=true','--timeout=90s'])
        uids={uid for _,uid in created}
        deadline=time.monotonic()+120
        while any(any(o['uid'] in uids for o in w['metadata'].get('ownerReferences',[])) for w in workloads()):
            if time.monotonic()>deadline: raise ValueError('Leaked acceptance Workload; retain run ID '+run_id)
            time.sleep(2)
        print('PASS: all acceptance Pods and Workloads removed; run '+run_id)

if __name__ == '__main__': main()
