#!/usr/bin/env python3
"""Temporary app probes against the deployed primary; writes only fixture schemas."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
NAMESPACE='apps-db-acceptance'
APPS=('acceptance_a','acceptance_b')


def run(args,data=None,check=True):
    result=subprocess.run(['kubectl','--request-timeout=30s',*args],input=data,capture_output=True,timeout=180)
    if check and result.returncode:
        raise ValueError('Acceptance Kubernetes operation failed; private diagnostics suppressed')
    return result


def apply(obj):
    run(['apply','--server-side','--field-manager=postgres-acceptance','-f','-'],json.dumps(obj).encode())


def admin(statement):
    cluster=json.loads(run(['-n','homelab-data','get','cluster','apps-db','-o','json']).stdout)
    run(['-n','homelab-data','exec','-i',cluster['status']['currentPrimary'],'-c','postgres','--',
         'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','apps'],statement.encode())


def client(app,statement,*,success=True,tls=True):
    args=['-n',NAMESPACE,'exec',app.replace('_','-'),'--','psql','-X','-tA','-v','ON_ERROR_STOP=1']
    if not tls: args+=['--dbname','sslmode=disable']
    result=run(args+['-c',statement],check=False)
    if success != (result.returncode==0):
        raise ValueError('Unexpected database authorization result')
    return result.stdout.decode().strip()


def setup():
    apply(dict(apiVersion='v1',kind='Namespace',metadata=dict(name=NAMESPACE,labels={
        'homelab/apps-db-client':'true','pod-security.kubernetes.io/enforce':'restricted'})))
    for app in APPS:
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'credentials.json';path.write_text(json.dumps({k:secrets.token_urlsafe(32) for k in ('runtime','migration')}));path.chmod(0o600)
            subprocess.run(['python3',str(ROOT/'scripts/postgres_onboard.py'),app,'--namespace',NAMESPACE,'--credentials',str(path)],check=True,capture_output=True)
        name=app.replace('_','-');secret='app-'+name+'-runtime'
        pod=dict(apiVersion='v1',kind='Pod',metadata=dict(name=name,namespace=NAMESPACE,labels={'homelab/apps-db-client':'true'}),spec=dict(
            nodeSelector={'kubernetes.io/hostname':'talos-worker-01'},automountServiceAccountToken=False,restartPolicy='Never',
            securityContext=dict(runAsNonRoot=True,runAsUser=26,runAsGroup=26,seccompProfile=dict(type='RuntimeDefault')),
            containers=[dict(name='client',image='ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:ebf3919504d7523a63e8e2fee9b051211de714644b36469275558c624afd50ec',command=['sleep','3600'],
                resources=dict(requests={'cpu':'50m','memory':'64Mi'},limits={'cpu':'50m','memory':'64Mi'}),
                securityContext=dict(allowPrivilegeEscalation=False,readOnlyRootFilesystem=True,capabilities=dict(drop=['ALL'])),
                env=[dict(name=k,value=v) for k,v in dict(PGHOST='apps-db-rw.homelab-data.svc.cluster.local',PGDATABASE='apps',PGSSLMODE='verify-full',PGSSLROOTCERT='/ca/ca.crt',PGCONNECT_TIMEOUT='5').items()]+[
                    dict(name='PGUSER',valueFrom=dict(secretKeyRef=dict(name=secret,key='username'))),dict(name='PGPASSWORD',valueFrom=dict(secretKeyRef=dict(name=secret,key='password')))],
                volumeMounts=[dict(name='ca',mountPath='/ca',readOnly=True)])],
            volumes=[dict(name='ca',secret=dict(secretName=secret,items=[dict(key='ca.crt',path='ca.crt')]))]))
        apply(pod)
        run(['-n',NAMESPACE,'wait','pod/'+name,'--for=condition=Ready','--timeout=120s'])
        # Allow independent role reconciliation to install the Secret password.
        for attempt in range(30):
            try:
                client(app,'SELECT 1');break
            except ValueError:
                time.sleep(2)
        else: raise ValueError('Runtime credentials not reconciled')
        admin(f'SET ROLE app_{app}_migration; CREATE TABLE app_{app}.probe (id integer PRIMARY KEY, value text); RESET ROLE;')
    admin('SET ROLE apps_owner; CREATE TABLE shared.acceptance_probe (id integer PRIMARY KEY); INSERT INTO shared.acceptance_probe VALUES (42); RESET ROLE;')


def verify():
    admin('REVOKE ALL ON shared.acceptance_probe FROM app_acceptance_a_runtime; REVOKE USAGE ON SCHEMA shared FROM app_acceptance_a_runtime;')
    run(['-n',NAMESPACE,'label','pod',APPS[1].replace('_','-'),'homelab/apps-db-client=true','--overwrite'])
    for attempt in range(30):
        try:
            client(APPS[1],'SELECT 1');break
        except ValueError:
            time.sleep(2)
    else: raise ValueError('Client policy did not converge')
    def writes(app):
        for i in range(10):
            client(app,f"INSERT INTO app_{app}.probe VALUES ({i}, 'fixture') ON CONFLICT DO NOTHING")
        assert client(app,f'SELECT count(*) FROM app_{app}.probe')=='10'
    with concurrent.futures.ThreadPoolExecutor() as pool:
        list(pool.map(writes,APPS))
    for app,other in zip(APPS,APPS[::-1]):
        client(app,f'SELECT * FROM app_{other}.probe',success=False)
        client(app,f'CREATE TABLE app_{app}.forbidden (id integer)',success=False)
        client(app,'SELECT 1',success=False,tls=False)
        client(app,'SELECT * FROM shared.acceptance_probe',success=False)
    admin('GRANT USAGE ON SCHEMA shared TO app_acceptance_a_runtime; GRANT SELECT ON shared.acceptance_probe TO app_acceptance_a_runtime;')
    assert client(APPS[0],'SELECT id FROM shared.acceptance_probe')=='42'
    client(APPS[1],'SELECT * FROM shared.acceptance_probe',success=False)
    run(['-n',NAMESPACE,'label','pod',APPS[1].replace('_','-'),'homelab/apps-db-client-'])
    try:
        for attempt in range(30):
            try:
                client(APPS[1],'SELECT 1',success=False);break
            except ValueError:
                time.sleep(2)
        else: raise ValueError('Unlabeled client was not denied after policy convergence')
    finally:
        run(['-n',NAMESPACE,'label','pod',APPS[1].replace('_','-'),'homelab/apps-db-client=true','--overwrite'])
    print(json.dumps({'concurrent_dml':'passed','cross_schema':'denied','runtime_ddl':'denied','plaintext':'denied','unlabeled_network_client':'denied','explicit_shared_grant':'passed'}))


def persistence():
    cluster=json.loads(run(['-n','homelab-data','get','cluster','apps-db','-o','json']).stdout)
    primary=cluster['status']['currentPrimary']
    before=json.loads(run(['-n','homelab-data','get','pod',primary,'-o','json']).stdout)['metadata']['uid']
    run(['-n','homelab-data','delete','pod',primary,'--wait=true'])
    for attempt in range(60):
        result=run(['-n','homelab-data','get','pod',primary,'-o','json'],check=False)
        if result.returncode==0 and json.loads(result.stdout)['metadata']['uid']!=before:
            try:
                if client(APPS[0],'SELECT count(*) FROM app_acceptance_a.probe')=='10':
                    print(json.dumps({'restart_persistence':'passed','previous_pod_uid':before,'new_pod_uid':json.loads(result.stdout)['metadata']['uid']}));return
            except ValueError: pass
        time.sleep(3)
    raise ValueError('Post-restart data verification failed')


def cleanup():
    for app in APPS:
        for kind in ('runtime','migration'):
            name='app-'+app.replace('_','-')+'-'+kind
            run(['-n','homelab-data','delete','databaserole',name,'--ignore-not-found'])
            run(['-n','homelab-data','delete','secret',name,'--ignore-not-found'])
        admin(f'DROP SCHEMA IF EXISTS app_{app} CASCADE; DROP OWNED BY app_{app}_runtime, app_{app}_migration; DROP ROLE app_{app}_runtime, app_{app}_migration;')
    admin('DROP TABLE IF EXISTS shared.acceptance_probe;')
    run(['delete','namespace',NAMESPACE,'--wait=false','--ignore-not-found'])
    print('Temporary app fixtures removed')


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['setup','verify','restart','cleanup']);args=parser.parse_args()
    {'setup':setup,'verify':verify,'restart':persistence,'cleanup':cleanup}[args.operation]()


if __name__=='__main__':
    main()
