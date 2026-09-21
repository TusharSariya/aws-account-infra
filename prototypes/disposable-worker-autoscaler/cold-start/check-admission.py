#!/usr/bin/env python3
"""Read-only live regression check after making pilot capacity available."""
import argparse
import json
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--kubeconfig',required=True);p.add_argument('--job',required=True);p.add_argument('--node',required=True)
a=p.parse_args();k=['kubectl','--kubeconfig',a.kubeconfig,'--request-timeout=10s']
def get(args):return json.loads(subprocess.check_output(k+args+['-o','json'],timeout=15))
node=get(['get','node',a.node]);job=get(['-n','prototype-slot','get','job',a.job])
pods=get(['-n','prototype-slot','get','pods','-l','job-name='+a.job])['items']
ready=any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions'])
result={'workerReady':ready,'jobSuspended':job['spec'].get('suspend',False),'podPhases':[x['status']['phase'] for x in pods]}
print(json.dumps(result))
assert ready and not result['jobSuspended'] and any(x['status']['phase']=='Running' and x['spec']['nodeName']==a.node for x in pods),'Ready worker has not received queued job'
