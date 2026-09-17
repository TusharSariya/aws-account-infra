"""Observe terminal failed backup Jobs independently of the backup process."""
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import subprocess
import urllib.request
import boto3
from backup import AWS_CONFIG, metric


def recent_failure(jobs, now):
    return any(c.get('type') == 'Failed' and c.get('status') == 'True'
               and 0 <= (now - datetime.fromisoformat(c['lastTransitionTime'].replace('Z', '+00:00'))).total_seconds() <= 1800
               for job in jobs for c in job.get('status', {}).get('conditions', []))


def main():
    try:
        sa=Path('/var/run/secrets/kubernetes.io/serviceaccount')
        request=urllib.request.Request('https://kubernetes.default.svc/apis/batch/v1/namespaces/homelab-data/jobs?labelSelector=app%3Dapps-db-backup',
            headers={'Authorization':'Bearer '+(sa/'token').read_text().strip()})
        with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=str(sa/'ca.crt')), timeout=20) as response:
            jobs=json.load(response)['items']
        cw=boto3.Session(region_name='us-east-1').client('cloudwatch',config=AWS_CONFIG)
        metric(cw,'BackupFailure',int(recent_failure(jobs,datetime.now(timezone.utc))))
        expiry=subprocess.run(['openssl','x509','-in','/identity/client.crt','-noout','-checkend','2592000'],capture_output=True,timeout=15)
        metric(cw,'CertificateExpiring',int(expiry.returncode!=0))
        print('Backup Job and certificate monitoring completed')
        return 0
    except Exception:
        print('Backup monitoring failed; independent missing-success alarm remains active')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
