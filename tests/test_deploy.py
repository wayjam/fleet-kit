import subprocess
import unittest
from io import StringIO
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


class DbusPreflightTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace(
            data={"deploy_target": "aws-sg1"},
            args=SimpleNamespace(activation="switch"),
        )
        self.deployment = {"targetHost": "203.0.113.20", "targetPort": 2234, "targetUser": "root"}

    @patch.object(deploy, "eval_host_raw", return_value="broker")
    @patch.object(deploy, "_target_output", return_value="running_dbus=dbus\nrunning_dbus_exe=/nix/store/dbus-daemon")
    def test_blocks_online_implementation_transition(self, _probe, _eval):
        with self.assertRaisesRegex(RuntimeError, "--activation boot"):
            deploy._stage_dbus_preflight(self.ctx, self.deployment)

    @patch.object(deploy, "eval_host_raw", return_value="broker")
    @patch.object(deploy, "_target_output", return_value="running_dbus=dbus\nrunning_dbus_exe=/nix/store/dbus-daemon")
    def test_boot_activation_allows_transition_with_manual_reboot_warning(self, _probe, _eval):
        self.ctx.args.activation = "boot"
        with patch("sys.stderr", new_callable=StringIO) as stderr:
            deploy._stage_dbus_preflight(self.ctx, self.deployment)
        self.assertIn("reboot the host manually", stderr.getvalue())

    @patch.object(deploy, "eval_host_raw", return_value="broker")
    @patch.object(deploy, "_target_output", return_value="running_dbus=broker\nrunning_dbus_exe=/nix/store/dbus-broker-launch")
    def test_matching_implementation_allows_online_switch(self, _probe, _eval):
        deploy._stage_dbus_preflight(self.ctx, self.deployment)

    @patch.object(deploy, "eval_host_raw", return_value="broker")
    @patch.object(deploy, "_target_output", return_value="running_dbus=unknown\nrunning_dbus_exe=unknown")
    def test_unknown_process_is_not_misclassified_as_transition(self, _probe, _eval):
        with self.assertRaisesRegex(RuntimeError, "cannot identify the running D-Bus"):
            deploy._stage_dbus_preflight(self.ctx, self.deployment)


class PostApplyDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace(data={"deploy_target": "aws-sg1"})

    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "services.dbus.implementation": "broker",
        "system.build.toplevel": "/nix/store/target-system",
    }[path])
    @patch.object(
        deploy,
        "_target_output",
        return_value="generation=/nix/store/target-system\nsystem_profile=/nix/store/target-system\nrunning_dbus=dbus\nfailed_units=\nbus=ok",
    )
    def test_reports_reboot_required_only_if_target_generation_active(self, _probe, _eval, _deployment):
        result = deploy._post_apply_diagnostic(self.ctx, "exit 4")
        self.assertIn("controlled reboot required", result)

    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "services.dbus.implementation": "broker",
        "system.build.toplevel": "/nix/store/target-system",
    }[path])
    @patch.object(
        deploy,
        "_target_output",
        return_value="generation=/nix/store/old-system\nsystem_profile=/nix/store/old-system\nrunning_dbus=dbus\nfailed_units=\nbus=ok",
    )
    def test_does_not_recommend_reboot_when_target_generation_not_active(self, _probe, _eval, _deployment):
        result = deploy._post_apply_diagnostic(self.ctx, "exit 4")
        self.assertIn("target generation is not active", result)


class ApplyGuardTests(unittest.TestCase):
    def test_dbus_preflight_failure_cannot_be_continued_interactively(self):
        stage = deploy._dbus_preflight_stage("dbus-preflight", "check D-Bus", lambda _ctx: None)
        self.assertFalse(stage.continueable)
        self.assertFalse(stage.skippable)

    @patch.object(deploy, "remote_shell")
    @patch.object(deploy, "_stage_dbus_preflight", side_effect=RuntimeError("D-Bus transition blocked"))
    def test_resuming_directly_at_apply_cannot_bypass_dbus_preflight(self, _preflight, remote_shell):
        ctx = SimpleNamespace(
            data={
                "deploy_target": "aws-sg1",
                "builder": {"remote_root": "/root", "name": "default"},
            },
            config={"repos": {"inventory_name": "fleet-private"}},
            args=SimpleNamespace(activation="switch"),
        )
        with self.assertRaisesRegex(RuntimeError, "D-Bus transition blocked"):
            deploy._stage_apply_remote(ctx)
        remote_shell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
