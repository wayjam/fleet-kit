import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import deploy


class TargetSshPreflightTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace(
            data={
                "deploy_target": "aws-us1",
                "builder": {"name": "default"},
            }
        )

    @patch.object(deploy, "remote_shell")
    @patch.object(
        deploy,
        "host_deployment",
        return_value={"targetHost": "203.0.113.20", "targetPort": 2234, "targetUser": "root"},
    )
    def test_probes_from_builder_to_configured_target(self, _deployment, remote_shell):
        deploy._stage_target_ssh_preflight(self.ctx)

        command = remote_shell.call_args.args[1]
        self.assertIn("-p 2234", command)
        self.assertIn("root@203.0.113.20", command)
        self.assertTrue(command.endswith(" true"))

    @patch.object(
        deploy,
        "host_deployment",
        return_value={"targetHost": "203.0.113.20", "targetPort": 2234, "targetUser": "root"},
    )
    @patch.object(deploy, "remote_shell", side_effect=subprocess.CalledProcessError(255, "ssh"))
    def test_failure_explains_key_authorization_and_resume(self, _remote_shell, _deployment):
        with self.assertRaisesRegex(RuntimeError, "public key|public-key|public key"):
            deploy._stage_target_ssh_preflight(self.ctx)


if __name__ == "__main__":
    unittest.main()
