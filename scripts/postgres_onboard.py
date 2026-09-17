#!/usr/bin/env python3
"""Idempotently onboard an app schema; deliver distinct secrets without Tofu state."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess

LOCK = 748930126


def run(command, data=None):
    result = subprocess.run(command, input=data, capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Onboarding command failed; private diagnostics suppressed')
    return result.stdout


def statements(app):
    if not re.fullmatch('[a-z][a-z0-9_]{0,24}', app):
        raise ValueError('Use a lowercase app identifier, at most 25 characters')
    schema, migration, runtime = 'app_' + app, 'app_' + app + '_migration', 'app_' + app + '_runtime'
    # Identifiers are restricted above; all values below are generated identifiers.
    return f'''BEGIN;
SELECT pg_advisory_xact_lock({LOCK});
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{migration}') THEN
    CREATE ROLE {migration} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{runtime}') THEN
    CREATE ROLE {runtime} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;
GRANT CONNECT ON DATABASE apps TO {migration}, {runtime};
CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {migration};
REVOKE ALL ON SCHEMA {schema} FROM PUBLIC;
GRANT USAGE ON SCHEMA {schema} TO {runtime};
ALTER ROLE {migration} IN DATABASE apps SET search_path = {schema}, pg_catalog;
ALTER ROLE {runtime} IN DATABASE apps SET search_path = {schema}, pg_catalog;
ALTER DEFAULT PRIVILEGES FOR ROLE {migration} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE {migration} REVOKE USAGE ON TYPES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE {migration} IN SCHEMA {schema}
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {runtime};
ALTER DEFAULT PRIVILEGES FOR ROLE {migration} IN SCHEMA {schema}
  GRANT USAGE, SELECT ON SEQUENCES TO {runtime};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {runtime};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {runtime};
COMMIT;
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app')
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--credentials', type=Path, required=True, help='Private JSON with runtime and migration passwords')
    args = parser.parse_args()
    os.umask(0o077)
    sql = statements(args.app)
    if args.credentials.stat().st_mode & 0o077:
        raise ValueError('Credential file must be private')
    values = json.loads(args.credentials.read_text())
    if set(values) != {'runtime', 'migration'} or any(not re.fullmatch(r'[A-Za-z0-9_-]{43}', v) for v in values.values()) or len(set(values.values())) != 2:
        raise ValueError('Two independent 256-bit passwords required')
    # Onboarding is an explicit operator action using the same server-side secret
    # delivery pattern: credentials only on stdin, no last-applied annotation/state.
    ca = json.loads(run(['kubectl', '-n', 'homelab-data', 'get', 'secret', 'apps-db-ca', '-o', 'json']))['data']['ca.crt']
    for kind in ('runtime', 'migration'):
        name = 'app-' + args.app.replace('_', '-') + '-' + kind
        role = 'app_' + args.app + '_' + kind
        data = {'username': base64.b64encode(role.encode()).decode(),
                'password': base64.b64encode(values[kind].encode()).decode(), 'ca.crt': ca}
        for namespace in {'homelab-data', args.namespace}:
            manifest = dict(apiVersion='v1', kind='Secret', type='kubernetes.io/basic-auth',
                metadata=dict(name=name, namespace=namespace, labels={'cnpg.io/reload': 'true'}), data=data)
            run(['kubectl', 'apply', '--server-side', '--field-manager=homelab-postgres-credentials', '-f', '-'], json.dumps(manifest).encode())
        manifest = dict(apiVersion='postgresql.cnpg.io/v1', kind='DatabaseRole',
            metadata=dict(name=name, namespace='homelab-data'),
            spec=dict(cluster=dict(name='apps-db'), name=role, login=True, superuser=False,
                      createdb=False, createrole=False, replication=False, bypassrls=False,
                      passwordSecret=dict(name=name)))
        run(['kubectl', 'apply', '--server-side', '--field-manager=homelab-postgres-onboarding', '-f', '-'], json.dumps(manifest).encode())
    primary = json.loads(run(['kubectl', '-n', 'homelab-data', 'get', 'cluster', 'apps-db', '-o', 'json']))['status']['currentPrimary']
    run(['kubectl', '-n', 'homelab-data', 'exec', '-i', primary, '-c', 'postgres', '--',
         'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'apps'], sql.encode())
    print('Onboarded schema and separate credentials; explicit client network policy labels and shared-table grants remain required.')


if __name__ == '__main__':
    main()
