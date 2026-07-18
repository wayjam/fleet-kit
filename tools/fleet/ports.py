"""`fleet ports <host>` — print allowed TCP and UDP ports."""

import json

from common import capture


def cmd_ports(args, _config):
    tcp = json.loads(
        capture(
            [
                "nix",
                "eval",
                f".#nixosConfigurations.{args.host}.config.networking.firewall.allowedTCPPorts",
                "--json",
            ]
        )
    )
    udp = json.loads(
        capture(
            [
                "nix",
                "eval",
                f".#nixosConfigurations.{args.host}.config.networking.firewall.allowedUDPPorts",
                "--json",
            ]
        )
    )

    def _fmt(ports):
        return " ".join(str(p) for p in ports) if ports else "(none)"

    print(f"TCP: {_fmt(tcp)}")
    print(f"UDP: {_fmt(udp)}")
