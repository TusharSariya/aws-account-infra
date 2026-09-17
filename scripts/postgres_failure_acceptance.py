#!/usr/bin/env python3
"""Inject pre-publication failures into disposable clones of the backup CronJob."""
import argparse
import copy
import json
import subprocess
import time


def run(args,data=None):
    result=subprocess.run(args,input=data,capture_output=True,timeout=240)
    if result.returncode:
        raise ValueError('Failure acceptance command failed; private diagnostics suppressed')
    return result.stdout


def version(bucket):
    return json.loads(run(['aws','--profile','admin','s3api','head-object','--bucket',bucket,'--key','apps-db/latest.tar.gz']))['VersionId']


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('failure',choices=['dump','upload','checksum']);args=p.parse_args()
    cron=json.loads(run(['kubectl','-n','homelab-data','get','cronjob','apps-db-backup','-o','json']))
    spec=copy.deepcopy(cron['spec']['jobTemplate']['spec']);spec.update(backoffLimit=0,activeDeadlineSeconds=180)
    container=spec['template']['spec']['containers'][0]
    bucket=next(x['value'] for x in container['env'] if x['name']=='BACKUP_BUCKET')
    before=version(bucket)
    if args.failure=='upload':
        next(x for x in container['env'] if x['name']=='BACKUP_BUCKET')['value']=bucket+'-failure-injection'
    else:
        function='command_to_file' if args.failure=='dump' else 'verify_object'
        container['command']=['python','-c',"import sys;sys.path.insert(0,'/code');import backup;"+f"backup.{function}=lambda *a,**k:(_ for _ in ()).throw(backup.BackupError('injected failure'));"+"sys.exit(backup.main())"]
    name='apps-db-test-'+args.failure+'-'+str(int(time.time()))
    job=dict(apiVersion='batch/v1',kind='Job',metadata=dict(name=name,namespace='homelab-data',labels={'app':'apps-db-backup'}),spec=spec)
    run(['kubectl','create','-f','-'],json.dumps(job).encode())
    run(['kubectl','-n','homelab-data','wait','job/'+name,'--for=condition=Failed','--timeout=200s'])
    after=version(bucket)
    if before!=after: raise ValueError('Failed run changed latest')
    print(json.dumps(dict(failure=args.failure,job=name,latest_unchanged=before,status='passed')))


if __name__=='__main__':
    main()
