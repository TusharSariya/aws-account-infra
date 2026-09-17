"""Restore recorded real S3 versions into two disposable, isolated instances."""
import contextlib
import json
import os
from pathlib import Path
import secrets
import sys
import tarfile
import tempfile
import time
sys.path.insert(0,'/repo/apps/platform/postgres')
import boto3
import psycopg
import backup
import restore


def main():
    records=json.load(open('/versions.json'))
    s3=boto3.Session(region_name='us-east-1').client('s3',config=backup.AWS_CONFIG)
    results=[]
    for index,(record,host) in enumerate(zip(records,['restore-old','restore-current'])):
        for _ in range(30):
            try:
                with psycopg.connect(host=host,user='postgres',dbname='postgres'):pass
                break
            except psycopg.OperationalError:time.sleep(1)
        os.environ.update(PGHOST=host,PGUSER='postgres',PGDATABASE='postgres',PGSSLMODE='disable')
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            obj=s3.get_object(Bucket='homelab-postgres-992382747916-us-east-1',Key=backup.KEY,VersionId=record['version_id'])
            with contextlib.closing(obj['Body']) as body,(directory/'backup.tar.gz').open('xb') as target:
                checksum,_=backup.bounded_copy(body,target,backup.MAX_ARCHIVE)
            assert obj['VersionId']==record['version_id'] and checksum==record['sha256']==obj['Metadata']['sha256']
            with tarfile.open(directory/'backup.tar.gz') as archive:
                roles=json.load(archive.extractfile('roles.json'))
            passwords={r['name']:secrets.token_urlsafe(32) for r in roles if r['login']}
            restore.restore(directory,passwords)
            with psycopg.connect(host=host,user='postgres',dbname='apps',autocommit=True) as c:
                counts=c.execute('SELECT (SELECT count(*) FROM app_acceptance_a.probe), (SELECT count(*) FROM app_acceptance_b.probe)').fetchone()
                assert counts==(10,10+index)
                assert c.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='app_acceptance_a.probe'::regclass").fetchone()[0]=='app_acceptance_a_migration'
                assert c.execute("SELECT bool_and(rolpassword LIKE 'SCRAM-SHA-256$%') FROM pg_authid WHERE rolcanlogin AND rolname LIKE 'app%'").fetchone()[0]
            for app in ['a','b']:
                role='app_acceptance_'+app+'_runtime'
                with psycopg.connect(host=host,user=role,password=passwords[role],dbname='apps',autocommit=True) as c:
                    try:c.execute('SELECT * FROM app_acceptance_'+('b' if app=='a' else 'a')+'.probe')
                    except psycopg.errors.InsufficientPrivilege:pass
                    else:raise AssertionError('Cross-schema grant survived incorrectly')
                    if app=='a':
                        assert c.execute('SELECT count(*) FROM app_acceptance_a.probe').fetchone()[0]==0
                        assert c.execute('SELECT id FROM shared.acceptance_probe').fetchone()[0]==42
                    else:
                        try:c.execute('SELECT * FROM shared.acceptance_probe')
                        except psycopg.errors.InsufficientPrivilege:pass
                        else:raise AssertionError('Unexpected shared grant')
                try:
                    psycopg.connect(host=host,user=role,password='deliberately-wrong',dbname='apps').close()
                except psycopg.OperationalError:pass
                else:raise AssertionError('Wrong runtime password accepted')
            results.append(dict(version_id=record['version_id'],sha256=checksum,rows=list(counts),ownership='passed',schema_isolation='passed',shared_grants='passed',rls='passed',fresh_scram_authentication='passed'))
    print(json.dumps({'execution':'local disposable PostgreSQL instances; production TLS verified separately','s3_restores':results}))


if __name__=='__main__':main()
