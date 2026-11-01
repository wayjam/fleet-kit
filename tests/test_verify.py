import unittest
from types import SimpleNamespace
from unittest.mock import patch

import deploy


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(host="aws-sg1", unit=["komari-agent.service"])
        self.config = {}

    def probe(self, *, generation="/nix/store/target-system", profile=None,
              running_dbus="broker", configured_dbus="broker",
              unit_state="active"):
        profile = profile or generation
        return (
            f"generation={generation}\n"
            f"system_profile={profile}\n"
            f"running_dbus={running_dbus}\n"
            "running_dbus_exe=/nix/store/dbus-broker-launch\n"
            f"configured_dbus={configured_dbus}\n"
            "configured_dbus_exe=/nix/store/dbus-broker-launch\n"
            "system_state=running\n"
            "failed_units=\n"
            "bus=ok\n"
            f"unit:komari-agent.service={unit_state}"
        )

    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "system.build.toplevel": "/nix/store/target-system",
        "services.dbus.implementation": "broker",
    }[path])
    @patch.object(
        deploy,
        "_target_output",
        return_value=(
            "generation=/nix/store/target-system\n"
            "system_profile=/nix/store/target-system\n"
            "running_dbus=broker\n"
            "running_dbus_exe=/nix/store/dbus-broker-launch\n"
            "configured_dbus=broker\n"
            "configured_dbus_exe=/nix/store/dbus-broker-launch\n"
            "system_state=running\nfailed_units=\nbus=ok\n"
            "unit:komari-agent.service=active"
        ),
    )
    def test_reports_healthy_host(self, _probe, _eval, _deployment):
        with patch("builtins.print") as output:
            deploy.cmd_verify(self.args, self.config)
        self.assertIn("fleet verify: OK for aws-sg1", str(output.call_args_list))

    @patch.object(deploy, "_target_output")
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "system.build.toplevel": "/nix/store/target-system",
        "services.dbus.implementation": "broker",
    }[path])
    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    def test_local_config_drift_is_warning_when_runtime_is_healthy(self, _deployment, _eval, probe):
        probe.return_value = self.probe(
            generation="/nix/store/old-system", profile="/nix/store/old-system"
        )
        with patch("builtins.print") as output:
            deploy.cmd_verify(self.args, self.config)
        self.assertIn("OK (runtime healthy; local config differs)", str(output.call_args_list))

    @patch.object(deploy, "_target_output")
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "system.build.toplevel": "/nix/store/target-system",
        "services.dbus.implementation": "broker",
    }[path])
    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    def test_strict_generation_fails_on_local_config_drift(self, _deployment, _eval, probe):
        self.args.strict_generation = True
        probe.return_value = self.probe(
            generation="/nix/store/old-system", profile="/nix/store/old-system"
        )
        with self.assertRaises(SystemExit) as raised:
            deploy.cmd_verify(self.args, self.config)
        self.assertEqual(raised.exception.code, 1)

    @patch.object(deploy, "_target_output")
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "system.build.toplevel": "/nix/store/target-system",
        "services.dbus.implementation": "broker",
    }[path])
    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    def test_fails_when_running_generation_differs_from_boot_profile(self, _deployment, _eval, probe):
        probe.return_value = self.probe(
            generation="/nix/store/old-system", profile="/nix/store/target-system"
        )
        with self.assertRaises(SystemExit) as raised:
            deploy.cmd_verify(self.args, self.config)
        self.assertEqual(raised.exception.code, 1)

    @patch.object(deploy, "_target_output")
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "system.build.toplevel": "/nix/store/target-system",
        "services.dbus.implementation": "broker",
    }[path])
    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    def test_fails_when_running_dbus_differs_from_active_unit(self, _deployment, _eval, probe):
        probe.return_value = self.probe(running_dbus="dbus", configured_dbus="broker")
        with self.assertRaises(SystemExit) as raised:
            deploy.cmd_verify(self.args, self.config)
        self.assertEqual(raised.exception.code, 1)

    @patch.object(deploy, "_target_output")
    @patch.object(deploy, "eval_host_raw", side_effect=lambda _host, path, _default: {
        "system.build.toplevel": "/nix/store/target-system",
        "services.dbus.implementation": "broker",
    }[path])
    @patch.object(deploy, "host_deployment", return_value={"targetHost": "203.0.113.20"})
    def test_fails_when_required_unit_is_inactive(self, _deployment, _eval, probe):
        probe.return_value = self.probe(unit_state="inactive")
        with self.assertRaises(SystemExit) as raised:
            deploy.cmd_verify(self.args, self.config)
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
