import unittest
from argparse import Namespace
from unittest.mock import patch

import build


class BuildCommandTests(unittest.TestCase):
    def test_no_kvm_removes_kvm_feature_from_builder_spec(self):
        builder = {
            "name": "default",
            "alias": "fleet-builder-default",
            "ssh_key": "-",
            "use_kvm": True,
        }
        args = Namespace(
            builder="default",
            host="aws-us1",
            dry_run=True,
            no_kvm=True,
            kvm=False,
        )

        with (
            patch.object(build, "builder_config", return_value=builder),
            patch.object(build, "nix_ssh_env", return_value={}),
            patch.object(build, "run") as run,
        ):
            build.cmd_build(args, {})

        command = run.call_args.args[0]
        builders = command[command.index("--builders") + 1]
        self.assertTrue(builders.endswith(" 1 1 - -"), builders)
        self.assertEqual(
            command[-1],
            ".#nixosConfigurations.aws-us1.config.system.build.toplevel",
        )

    def test_default_builder_kvm_feature_is_preserved(self):
        builder = {
            "name": "default",
            "alias": "fleet-builder-default",
            "ssh_key": "-",
            "use_kvm": True,
        }
        args = Namespace(
            builder="default",
            host="aws-us1",
            dry_run=True,
            no_kvm=False,
            kvm=False,
        )

        with (
            patch.object(build, "builder_config", return_value=builder),
            patch.object(build, "nix_ssh_env", return_value={}),
            patch.object(build, "run") as run,
        ):
            build.cmd_build(args, {})

        command = run.call_args.args[0]
        builders = command[command.index("--builders") + 1]
        self.assertTrue(builders.endswith(" 1 1 kvm -"), builders)
        self.assertEqual(
            command[-1],
            ".#nixosConfigurations.aws-us1.config.system.build.toplevel",
        )

    def test_dry_run_builds_system_closure(self):
        args = Namespace(
            builder="",
            host="tencent-sg1",
            dry_run=True,
        )

        with patch.object(build, "run") as run:
            build.cmd_build(args, {})

        run.assert_called_once_with(
            [
                "nix",
                "build",
                "--dry-run",
                ".#nixosConfigurations.tencent-sg1.config.system.build.toplevel",
            ]
        )


if __name__ == "__main__":
    unittest.main()
