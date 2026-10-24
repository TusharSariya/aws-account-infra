import subprocess
import unittest
import yaml


class ChartTests(unittest.TestCase):
    def render(self, enabled=False):
        args=['helm','template','apps-db','charts/homelab-postgres']
        if enabled:
            args += ['--set','backup.enabled=true','--set','backupImage=example.invalid/backup@sha256:'+'a'*64,
                     '--set','backup.trustAnchorArn=anchor,backup.profileArn=profile,backup.roleArn=role']
        return [x for x in yaml.safe_load_all(subprocess.check_output(args)) if x]

    def test_one_primary_tls_storage_and_no_plaintext_credentials(self):
        docs=self.render()
        spec=next(x for x in docs if x['kind']=='Cluster')['spec']
        self.assertEqual(spec['instances'],1)
        self.assertEqual(spec['storage']['size'],'32Gi')
        self.assertFalse(spec['storage']['resizeInUseVolumes'])
        self.assertEqual(spec['postgresql']['pg_hba'][0],'hostnossl all all all reject')
        self.assertEqual(spec['managed']['services']['disabledDefaultServices'],['r','ro'])
        self.assertEqual(spec['resources']['requests'],{'cpu':'1','memory':'4Gi'})
        self.assertFalse(any(x['kind']=='Secret' for x in docs))
        self.assertEqual(next(x for x in docs if x['kind']=='PersistentVolumeClaim')['spec']['resources']['requests']['storage'],'64Gi')

    def test_backup_boundaries(self):
        docs=self.render(True)
        job=next(x for x in docs if x['kind']=='CronJob')['spec']
        self.assertEqual(job['schedule'],'30 8 * * *')
        self.assertEqual(job['timeZone'],'Etc/UTC')
        self.assertEqual(job['concurrencyPolicy'],'Forbid')
        self.assertEqual(job['jobTemplate']['spec']['activeDeadlineSeconds'],7200)
        pod=job['jobTemplate']['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['containers'][0]['resources']['requests'],{'cpu':'500m','memory':'1Gi'})
        ca=next(x for x in pod['volumes'] if x['name']=='ca')['secret']
        self.assertEqual(ca['items'],[{'key':'ca.crt','path':'ca.crt'}])
        self.assertNotIn('emptyDir',next(x for x in pod['volumes'] if x['name']=='scratch'))


if __name__=='__main__':
    unittest.main()
