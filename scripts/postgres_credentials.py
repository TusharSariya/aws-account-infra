"""Dedicated PostgreSQL secrets delivered through the existing protected writer."""
import base64
import json
import os
import re

NAME = 'POSTGRES_BACKUP_CREDENTIALS_B64'


def credentials():
    try:
        values = json.loads(base64.b64decode(os.environ[NAME], validate=True))
        if set(values) != {'password', 'client.crt', 'client.key'}:
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', values['password']):
            raise ValueError()
        if 'BEGIN CERTIFICATE' not in values['client.crt'] or 'PRIVATE KEY' not in values['client.key']:
            raise ValueError()
        return values
    except (KeyError, ValueError, TypeError):
        raise ValueError('Dedicated PostgreSQL password and leaf certificate/key required') from None


def reconcile(kubectl, writer):
    values = credentials()
    writer(kubectl, dict(apiVersion='v1', kind='Namespace', metadata=dict(name='homelab-data', labels={
        'pod-security.kubernetes.io/enforce': 'restricted', 'pod-security.kubernetes.io/enforce-version': 'v1.36'})))
    for name, data in [('apps-db-backup-db', {'username': 'apps_backup', 'password': values['password']}),
                       ('apps-db-backup-identity', {k: values[k] for k in ('client.crt', 'client.key')})]:
        writer(kubectl, dict(apiVersion='v1', kind='Secret', metadata=dict(name=name, namespace='homelab-data', labels={'cnpg.io/reload': 'true'}),
            type='kubernetes.io/basic-auth' if name.endswith('-db') else 'Opaque',
            data={k: base64.b64encode(v.encode()).decode() for k, v in data.items()}))
