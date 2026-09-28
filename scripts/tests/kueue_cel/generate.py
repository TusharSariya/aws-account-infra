import copy,json,subprocess,yaml
from pathlib import Path
import os, sys
os.chdir(Path(__file__).resolve().parents[3])
policy=next(d for d in yaml.safe_load_all(subprocess.check_output(['helm','template','queue','charts/homelab-queue'])) if d and d['kind']=='ValidatingAdmissionPolicy')
def container(cpu='1',memory='1Gi',**kw):
 return dict(name='main',resources=dict(requests={'cpu':cpu,'memory':memory,'ephemeral-storage':'16Mi'}),**kw)
base=dict(metadata=dict(labels={'kueue.x-k8s.io/queue-name':'argo','kueue.x-k8s.io/workload-priority-class':'homelab-compute'}),spec=dict(serviceAccountName='homelab-job',containers=[container()],schedulingGates=[dict(name='kueue.x-k8s.io/admission')]))
request=dict(namespace='homelab-jobs',operation='CREATE',userInfo=dict(username='operator'))
cases=[]
def case(name,obj,allowed,req=None,old=None): cases.append(dict(name=name,object=obj,allowed=allowed,request=req or request,oldObject=old))
case('ordinary queued Pod',base,True)
for resource,value in [('cpu','31.251'),('memory','85Gi'),('ephemeral-storage','241Gi')]:
 obj=copy.deepcopy(base);obj['spec']['containers'][0]['resources']['requests'][resource]=value;case('large '+resource+' waits for dynamic quota',obj,True)
obj=copy.deepcopy(base);obj['spec']['containers'][0]['resources']['requests']['ephemeral-storage']='240Gi';case('exact scratch pool fits',obj,True)
obj=copy.deepcopy(base);obj['spec']['containers']=[container('15.625'),container('15.626')];case('aggregate waits for dynamic quota',obj,True)
obj=copy.deepcopy(base);obj['spec']['initContainers']=[container('34')];case('init peak waits for dynamic quota',obj,True)
obj=copy.deepcopy(base);obj['spec']['containers']=[container('30.25')];obj['spec']['initContainers']=[container('2',restartPolicy='Always')];case('sidecar aggregate waits for dynamic quota',obj,True)
obj=copy.deepcopy(base);obj['spec']['containers']=[container('30.25')];obj['spec']['initContainers']=[container('1',restartPolicy='Always'),container('30.25')];case('exact sidecar/init peak fits',obj,True)
obj=copy.deepcopy(base);obj['spec']['initContainers']=[container('31.25'),container('1',restartPolicy='Always')];case('later sidecar not charged to earlier init',obj,True)
obj=copy.deepcopy(base);obj['spec']['schedulingGates']=[];case('missing gate',obj,False)
obj=copy.deepcopy(base);obj['metadata']['labels']={};case('missing queue',obj,False)
obj=copy.deepcopy(base);obj['spec']['nodeName']='talos-worker-01';case('direct binding',obj,False)
obj=copy.deepcopy(base);obj['spec']['serviceAccountName']='ai-operator-job';obj['metadata']['labels']={};obj['spec']['schedulingGates']=[];case('operator bypasses queue',obj,True)
hook=copy.deepcopy(base)
hook['metadata']['labels']={}
hook['metadata']['ownerReferences']=[dict(apiVersion='batch/v1',kind='Job',name='argo-workflows-crd-install')]
hook['spec']['serviceAccountName']='argo-workflows-crd-install'
hook['spec']['schedulingGates']=[]
case('named Argo CRD hook is operational',hook,True)
obj=copy.deepcopy(hook);obj['metadata']['ownerReferences'][0]['name']='ordinary-job';case('hook account alone cannot bypass',obj,False)
obj=copy.deepcopy(hook);obj['spec']['serviceAccountName']='homelab-job';case('hook name alone cannot bypass',obj,False)
req=copy.deepcopy(request);req['namespace']='homelab-models';case('hook cannot bypass in another namespace',hook,False,req)
obj=copy.deepcopy(hook);obj['metadata']['labels']=copy.deepcopy(base['metadata']['labels']);case('operational hook must stay outside queue',obj,False)
obj=copy.deepcopy(base);obj['spec']['schedulingGates']=[];req=copy.deepcopy(request);req['operation']='UPDATE';case('unprivileged gate removal',obj,False,req,base)
req=copy.deepcopy(req);req['userInfo']['username']='system:serviceaccount:kueue-system:kueue-controller-manager';case('Kueue gate removal',obj,True,req,base)
gateway=dict(metadata=dict(labels={'app':'wake-ollama'},ownerReferences=[dict(apiVersion='apps/v1',kind='ReplicaSet',name='wake-ollama-abc',controller=True)]),spec=dict(serviceAccountName='wake-ollama',nodeSelector={'node-role.kubernetes.io/control-plane':''},containers=[container()]))
gateway_req=copy.deepcopy(request);gateway_req['namespace']='homelab-models'
case('registered always-on gateway',gateway,True,gateway_req)
for field,value in [('serviceAccountName','default'),('nodeSelector',{'kubernetes.io/hostname':'talos-worker-01'})]:
 obj=copy.deepcopy(gateway);obj['spec'][field]=value;case('gateway wrong '+field,obj,False,gateway_req)
obj=copy.deepcopy(gateway);obj['metadata']['labels']['app']='other';case('gateway wrong label',obj,False,gateway_req)
obj=copy.deepcopy(gateway);obj['metadata']['ownerReferences'][0]['name']='other-abc';case('gateway wrong owner',obj,False,gateway_req)
case('gateway wrong namespace',gateway,False)
obj=copy.deepcopy(gateway);obj['metadata']['labels']['app']='wake-playground';obj['metadata']['ownerReferences'][0]['name']='wake-playground-abc';obj['spec']['serviceAccountName']='wake-playground';case('playground gateway is operational',obj,True,gateway_req)
service=dict(metadata=dict(labels={'app':'playground-router'},ownerReferences=[dict(apiVersion='apps/v1',kind='ReplicaSet',name='playground-router-abc',controller=True)]),spec=dict(serviceAccountName='playground-router',nodeSelector={'kubernetes.io/hostname':'talos-worker-01'},containers=[container()]))
case('playground service on the worker is operational',service,True,gateway_req)
obj=copy.deepcopy(service);obj['spec']['serviceAccountName']='default';obj['metadata']['labels']['app']='default';case('service under the default account',obj,False,gateway_req)
obj=copy.deepcopy(service);obj['spec']['nodeSelector']={'kubernetes.io/hostname':'talos-worker-02'};case('service off the worker',obj,False,gateway_req)
obj=copy.deepcopy(service);obj['metadata']['ownerReferences'][0]['name']='other-abc';case('service wrong owner',obj,False,gateway_req)
case('service wrong namespace',service,False)
filler=dict(metadata=dict(name='ai-resource-filler',labels={'app':'ai-maintenance'}),spec=dict(serviceAccountName='default',nodeSelector={'kubernetes.io/hostname':'talos-worker-01'},containers=[container('3','32Mi')]))
admin_req=copy.deepcopy(gateway_req);admin_req['userInfo']=dict(username='admin',groups=['system:masters','system:authenticated'])
case('maintenance filler placed by cluster-admin is operational',filler,True,admin_req)
case('maintenance filler without the admin group is compute',filler,False,gateway_req)
obj=copy.deepcopy(filler);obj['metadata']['name']='other';case('admin cannot bypass with another name',obj,False,admin_req)
obj=copy.deepcopy(filler);obj['metadata']['labels']['app']='other';case('admin cannot bypass with another label',obj,False,admin_req)
case('maintenance filler wrong namespace',filler,False,dict(admin_req,namespace='homelab-jobs'))
for name in ('ai-snapshot','ai-isolated-restore'):
 obj=copy.deepcopy(filler);obj['metadata']['name']=name;case('backup rehearsal '+name+' placed by cluster-admin is operational',obj,True,admin_req)
 case('backup rehearsal '+name+' without the admin group is compute',obj,False,gateway_req)
 labelled=copy.deepcopy(obj);labelled['metadata']['labels'].update(base['metadata']['labels']);case('backup rehearsal '+name+' must stay outside queue',labelled,False,admin_req)
Path(sys.argv[1]).write_text(json.dumps(dict(variables=policy['spec']['variables'],validations=policy['spec']['validations'],cases=cases)))
