"""Bind reset authorization to a fresh completed live maintenance proof."""
import hashlib
import json


def template_revision(templates):
    return hashlib.sha256(json.dumps(templates, sort_keys=True).encode()).hexdigest()


def require_proof(record, revision, filesystem, node, now):
    if (record.get('phase') != 'completed' or record.get('revision') != revision
            or record.get('filesystem') != filesystem or record.get('node_uid') != node['metadata']['uid']
            or record.get('boot_after') != node['status']['nodeInfo']['bootID']
            or record.get('boot_before') == record.get('boot_after')
            or not any(value.get('type') == 'Ready' and value.get('status') == 'True'
                       for value in node['status'].get('conditions', []))
            or type(record.get('completed_at')) not in (int, float)
            or not 0 <= now - record['completed_at'] <= 86400):
        raise ValueError('A fresh successful quota/user-namespace/reboot proof is required before reset')
