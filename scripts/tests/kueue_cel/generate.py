import copy,json,subprocess,yaml
from pathlib import Path
import os, sys
os.chdir(Path(__file__).resolve().parents[3])
policy=next(d for d in yaml.safe_load_all(subprocess.check_output(['helm','template','queue','charts/homelab-queue'])) if d and d['kind']=='ValidatingAdmissionPolicy')
def container(cpu='1',memory='1Gi',**kw):
 return dict(name='main',resources=dict(requests=dict(cpu=cpu,memory=memory)),**kw)
base=dict(metadata=dict(labels={'kueue.x-k8s.io/queue-name':'argo','kueue.x-k8s.io/workload-priority-class':'homelab-compute'}),spec=dict(serviceAccountName='homelab-job',containers=[container()],schedulingGates=[dict(name='kueue.x-k8s.io/admission')]))
request=dict(namespace='homelab-jobs',operation='CREATE',userInfo=dict(username='operator'))
cases=[]
def case(name,obj,allowed,req=None,old=None): cases.append(dict(name=name,object=obj,allowed=allowed,request=req or request,oldObject=old))
case('ordinary queued Pod',base,True)
for resource,value in [('cpu','36.001'),('memory','161Gi')]:
 obj=copy.deepcopy(base);obj['spec']['containers'][0]['resources']['requests'][resource]=value;case('oversized '+resource,obj,False)
obj=copy.deepcopy(base);obj['spec']['containers']=[container('18'),container('18.001')];case('aggregate exceeds pool',obj,False)
obj=copy.deepcopy(base);obj['spec']['initContainers']=[container('37')];case('init peak exceeds pool',obj,False)
obj=copy.deepcopy(base);obj['spec']['containers']=[container('35')];obj['spec']['initContainers']=[container('2',restartPolicy='Always')];case('sidecar aggregate exceeds pool',obj,False)
obj=copy.deepcopy(base);obj['spec']['containers']=[container('35')];obj['spec']['initContainers']=[container('1',restartPolicy='Always'),container('35')];case('exact sidecar/init peak fits',obj,True)
obj=copy.deepcopy(base);obj['spec']['initContainers']=[container('36'),container('1',restartPolicy='Always')];case('later sidecar not charged to earlier init',obj,True)
obj=copy.deepcopy(base);obj['spec']['schedulingGates']=[];case('missing gate',obj,False)
obj=copy.deepcopy(base);obj['metadata']['labels']={};case('missing queue',obj,False)
obj=copy.deepcopy(base);obj['spec']['nodeName']='talos-worker-01';case('direct binding',obj,False)
obj=copy.deepcopy(base);obj['spec']['serviceAccountName']='ai-operator-job';obj['metadata']['labels']={};obj['spec']['schedulingGates']=[];case('operator bypasses queue',obj,True)
obj=copy.deepcopy(base);obj['spec']['schedulingGates']=[];req=copy.deepcopy(request);req['operation']='UPDATE';case('unprivileged gate removal',obj,False,req,base)
req=copy.deepcopy(req);req['userInfo']['username']='system:serviceaccount:kueue-system:kueue-controller-manager';case('Kueue gate removal',obj,True,req,base)
Path(sys.argv[1]).write_text(json.dumps(dict(variables=policy['spec']['variables'],validations=policy['spec']['validations'],cases=cases)))
