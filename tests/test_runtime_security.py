import unittest

from autoresearch_flow.common import FlowError
from autoresearch_flow.runtime_security import (classify_sandbox_result, compatibility_identity,
                                               compose_security_options, docker_security_options)


class RuntimeSecurityTests(unittest.TestCase):
    def test_default_keeps_apparmor_and_seccomp_defaults(self):
        args = docker_security_options({'mode': 'default'})
        self.assertNotIn('apparmor=unconfined', args)
        self.assertFalse(any(x.startswith('seccomp=') for x in args))
        self.assertIn('no-new-privileges', args)
        self.assertIn('ALL', args)

    def test_exception_requires_current_explicit_authorization(self):
        for value in [{'mode': 'codex_nested'}, {'mode': 'codex_nested', 'authorization': ''},
                      {'mode': 'default', 'privileged': True}, {'mode': 'unconfined'}]:
            with self.assertRaises(FlowError):
                docker_security_options(value)

    def test_approved_mode_is_consistent_for_docker_and_compose(self):
        value = {'mode': 'codex_nested', 'authorization': '仅本次 CPU 合成验收'}
        args = docker_security_options(value)
        compose = compose_security_options(value)
        self.assertIn('apparmor=unconfined', args)
        self.assertIn('apparmor=unconfined', compose['security_opt'])
        self.assertEqual(compose['cap_drop'], ['ALL'])
        self.assertNotIn('--privileged', args)
        self.assertEqual(len(compatibility_identity(value)['seccomp_sha256']), 64)

    def test_stage_classification_is_factual_and_does_not_downgrade(self):
        for text, expected in [('unshare(CLONE_NEWUSER): Operation not permitted', 'namespace'),
                               ('bwrap: No permissions to create a new namespace', 'namespace'),
                               ('mount /workspace/.git: Permission denied', 'mount'),
                               ('open file: Permission denied', 'access'), ('unknown failure', 'unknown')]:
            self.assertEqual(classify_sandbox_result(1, '', text)['stage'], expected)
        self.assertEqual(classify_sandbox_result(0, '', '')['status'], 'succeeded')


if __name__ == '__main__':
    unittest.main()
