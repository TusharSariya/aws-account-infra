"""Disposable real PostgreSQL tests; deliberately not live TLS/network evidence."""
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
sys.path[:0] = ['/repo/apps/platform/postgres', '/repo/scripts']
import psycopg
from psycopg import sql
import backup
import restore
from postgres_onboard import statements


def connect(host, user='postgres', database='postgres'):
    return psycopg.connect(host=host, user=user, dbname=database, autocommit=True)


def denied(connection, query):
    try:
        connection.execute(query)
    except psycopg.errors.InsufficientPrivilege:
        return
    raise AssertionError('Unexpected grant: ' + query)


def main():
    source = os.environ['SOURCE_HOST']
    targets = os.environ['TARGET_HOSTS'].split(',')
    for host in [source] + targets:
        for attempt in range(30):
            try:
                with connect(host): pass
                break
            except psycopg.OperationalError:
                time.sleep(1)
        else:
            raise AssertionError('Disposable database did not become ready')
    with connect(source) as c:
        c.execute('CREATE ROLE apps_owner NOLOGIN')
        c.execute('CREATE ROLE cnpg_metrics_exporter NOLOGIN')
        c.execute('CREATE DATABASE apps OWNER apps_owner')
    with connect(source, database='apps') as c:
        for statement in json.load(open('/tmp/bootstrap.json')):
            c.execute(statement)
        for app in ['one', 'two']:
            c.execute(statements(app))
            c.execute(f"ALTER ROLE app_{app}_runtime VALID UNTIL 'infinity'")
        c.execute('CREATE TABLE shared.reference (id integer PRIMARY KEY)')
        c.execute('ALTER TABLE shared.reference OWNER TO apps_owner')
        c.execute('INSERT INTO shared.reference VALUES (42)')
    for app in ['one','two']:
        with connect(source, f'app_{app}_migration', 'apps') as c:
            c.execute(f'CREATE TABLE app_{app}.items (id integer PRIMARY KEY, value text)')
    def write(app):
        with connect(source, f'app_{app}_runtime', 'apps') as c:
            for i in range(30):
                c.execute(f'INSERT INTO app_{app}.items VALUES (%s,%s)', (i, app))
            assert c.execute(f'SELECT count(*) FROM app_{app}.items').fetchone()[0] == 30
            other = 'two' if app == 'one' else 'one'
            denied(c, f'SELECT * FROM app_{other}.items')
            denied(c, f'CREATE TABLE app_{app}.forbidden (id integer)')
            denied(c, 'SELECT * FROM shared.reference')
    with concurrent.futures.ThreadPoolExecutor() as pool:
        list(pool.map(write, ['one','two']))
    with connect(source, database='apps') as c:
        c.execute('GRANT USAGE ON SCHEMA shared TO app_one_runtime')
        c.execute('GRANT SELECT ON shared.reference TO app_one_runtime')
        c.execute('ALTER TABLE app_one.items ENABLE ROW LEVEL SECURITY')
        c.execute('ALTER TABLE app_one.items FORCE ROW LEVEL SECURITY')
        c.execute('CREATE POLICY hide_rows ON app_one.items USING (false)')
    with connect(source, 'app_one_runtime', 'apps') as c:
        assert c.execute('SELECT id FROM shared.reference').fetchone()[0] == 42
        assert c.execute('SELECT count(*) FROM app_one.items').fetchone()[0] == 0
    os.environ.update(PGHOST=source, PGUSER='apps_backup', PGDATABASE='apps', PGSSLMODE='disable')
    archives=[]
    with tempfile.TemporaryDirectory() as root:
        for number in [0,1]:
            directory=Path(root)/str(number);directory.mkdir()
            if number:
                with connect(source, database='apps') as c:
                    c.execute("INSERT INTO app_two.items VALUES (100,'newer')")
            with psycopg.connect('', autocommit=True) as c:
                assert c.execute('SELECT count(*) FROM app_one.items').fetchone()[0] == 30
                c.execute('SELECT pg_advisory_lock(%s)', (backup.LOCK,))
                archive = backup.archive(c, directory)
            archives.append(archive)
        for index,target in enumerate(targets):
            os.environ.update(PGHOST=target, PGUSER='postgres', PGDATABASE='postgres')
            directory=Path(root)/('restore'+str(index));directory.mkdir()
            import shutil
            shutil.copyfile(archives[index], directory/'backup.tar.gz')
            inventory=json.loads((archives[index].parent/'roles.json').read_text())
            passwords={r['name']:secrets.token_urlsafe(32) for r in inventory if r['login']}
            restore.restore(directory,passwords)
            with connect(target, database='apps') as c:
                assert c.execute('SELECT count(*) FROM app_one.items').fetchone()[0] == 30
                assert c.execute('SELECT count(*) FROM app_two.items').fetchone()[0] == 30+index
                assert c.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='app_two.items'::regclass").fetchone()[0]=='app_two_migration'
            with connect(target,'app_one_runtime','apps') as c:
                denied(c,'SELECT * FROM app_two.items')
                assert c.execute('SELECT id FROM shared.reference').fetchone()[0]==42
                assert c.execute('SELECT count(*) FROM app_one.items').fetchone()[0]==0
            with connect(target,'app_two_runtime','apps') as c:
                denied(c,'SELECT * FROM shared.reference')
            try:
                retry=Path(root)/('retry'+str(index));retry.mkdir();shutil.copyfile(archives[index],retry/'backup.tar.gz')
                restore.restore(retry,passwords)
            except backup.BackupError:
                pass
            else:
                raise AssertionError('Existing database overwrite not rejected')
    print('PASS: concurrent private DML, denied cross-schema/DDL, explicit shared access, RLS-inclusive dumps, two-version data/ownership/grant restore, overwrite refusal')


if __name__=='__main__':
    main()
