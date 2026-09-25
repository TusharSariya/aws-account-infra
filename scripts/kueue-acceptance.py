#!/usr/bin/env python3
"""Isolated live BestEffortFIFO/CPU/RAM/scratch/cancellation proof; deletes only this run's Pods."""
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
                    'nodeSelector': {'kubernetes.io/hostname': 'talos-worker-01'},
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
        from decimal import Decimal
        from kueue_capacity import quantity
        queue = json.loads(run(['get','clusterqueue','homelab-compute','-o','json']))
        if queue['spec']['queueingStrategy'] != 'BestEffortFIFO':
            raise ValueError('BestEffortFIFO must be active')
        flavor = next(f for g in queue['spec']['resourceGroups'] for f in g['flavors'] if f['name']=='homelab-worker')
        quotas = {r['name']: quantity(r['nominalQuota']) for r in flavor['resources']}
        tested = ['cpu','memory','ephemeral-storage'] if args.scenario=='combined' else [args.scenario]
        def fraction(part):
            resources = {'cpu':'100m','memory':'64Mi','ephemeral-storage':'16Mi'}
            for resource in tested:
                value = quotas[resource] * Decimal(part)
                resources[resource] = str(value.quantize(Decimal('.001')) if resource=='cpu' else int(value))
                if quantity(resources[resource]) < quantity({'cpu':'1','memory':'1Gi','ephemeral-storage':'1Gi'}[resource]):
                    raise ValueError('Insufficient measured capacity for contention proof')
            return tuple(resources[r] for r in ['cpu','memory','ephemeral-storage'])
        first, second = fraction('.5'), fraction('.75')
        blocker=create('blocker', *first[:2], scratch=first[2])
        wait(blocker,True)
        older=create('older', *second[:2], scratch=second[2])
        wait(older,False)
        # Kubernetes creationTimestamp has second resolution; avoid an ordering tie.
        time.sleep(2)
        later=create('later','100m','64Mi');wait(later,True)
        # Prove smaller work bypasses the larger pending workload.
        for _ in range(10):
            if observed(older) is not False or observed(later) is not True or observed(blocker) is not True:
                raise ValueError('BestEffortFIFO did not preserve running work and admit the fitting follower')
            time.sleep(2)
        delete(older)  # Cancel only the waiting workload; the smaller follower already runs.
        wait(later,True)
        delete(later)
        later=create('completion','100m','64Mi');wait(later,True)
        delete(blocker)
        delete(later)
        completed = create('normal', *first[:2], scratch=first[2], seconds=30)
        wait(completed, True)
        follower = create('after-normal', *second[:2], scratch=second[2])
        wait(follower, False)
        wait(follower, True)
        finished = json.loads(run(['get','pod',completed,'-n','homelab-jobs','-o','json']))
        if finished.get('status', {}).get('phase') != 'Succeeded':
            raise ValueError('Reservation released before observed successful termination')
        print('PASS: '+args.scenario+' exhaustion, BestEffortFIFO and queued cancellation observed')
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
