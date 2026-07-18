{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.proxy.singBox;

  inboundType = lib.types.submodule ({name, ...}: {
    options = {
      tag = lib.mkOption {
        type = lib.types.str;
        default = name;
        description = "Inbound tag for the generated sing-box configuration.";
      };

      listenAddress = lib.mkOption {
        type = lib.types.str;
        default = "0.0.0.0";
        description = "Address sing-box listens on.";
      };

      listenPort = lib.mkOption {
        type = lib.types.port;
        description = "Port sing-box listens on.";
      };

      openFirewall = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Open the listen port through my.server.firewall.";
      };

      method = lib.mkOption {
        type = lib.types.str;
        default = "2022-blake3-aes-128-gcm";
        description = "Shadowsocks method.";
      };

      passwordFile = lib.mkOption {
        type = lib.types.str;
        description = "Runtime file containing the Shadowsocks password.";
      };

      network = lib.mkOption {
        type = lib.types.enum ["tcp" "udp" "tcp,udp"];
        default = "tcp,udp";
        description = "Shadowsocks network mode.";
      };
    };
  });

  renderInbound = name: inbound: {
    inherit name;
    inherit
      (inbound)
      tag
      listenAddress
      listenPort
      method
      passwordFile
      network
      ;
  };

  renderedInbounds = lib.mapAttrsToList renderInbound cfg.shadowsocksInbounds;
  inboundsJson = pkgs.writeText "sing-box-shadowsocks-inbounds.json" (builtins.toJSON renderedInbounds);

  hasNetwork = needle: network:
    network == needle || network == "tcp,udp";

  tcpFirewallPorts =
    lib.unique
    (lib.concatMap
      (inbound:
        if inbound.openFirewall && hasNetwork "tcp" inbound.network
        then [inbound.listenPort]
        else [])
      (lib.attrValues cfg.shadowsocksInbounds));

  udpFirewallPorts =
    lib.unique
    (lib.concatMap
      (inbound:
        if inbound.openFirewall && hasNetwork "udp" inbound.network
        then [inbound.listenPort]
        else [])
      (lib.attrValues cfg.shadowsocksInbounds));

  script = pkgs.writeShellScript "render-sing-box-config" ''
    set -euo pipefail
    install -d -m 0755 /run/sing-box

    ${pkgs.python3}/bin/python3 - <<'PY'
    import json
    from pathlib import Path

    source_inbounds = json.loads(Path("${inboundsJson}").read_text())
    inbounds = []

    for source in source_inbounds:
      inbound = {
        "type": "shadowsocks",
        "tag": source["tag"],
        "listen": source["listenAddress"],
        "listen_port": source["listenPort"],
        "method": source["method"],
        "password": Path(source["passwordFile"]).read_text().strip(),
      }
      if source["network"] != "tcp,udp":
        inbound["network"] = source["network"]
      inbounds.append(inbound)

    config = {
      "log": {
        "level": "info",
        "timestamp": True,
      },
      "inbounds": inbounds,
      "outbounds": [
        {
          "type": "direct",
          "tag": "direct",
        },
      ],
      "route": {
        "final": "direct",
      },
    }

    Path("/run/sing-box/config.json").write_text(json.dumps(config, indent=2) + "\n")
    PY
  '';
in {
  options.my.proxy.singBox = {
    enable = lib.mkEnableOption "sing-box proxy service";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.sing-box;
      description = "sing-box package to run.";
    };

    shadowsocksInbounds = lib.mkOption {
      type = with lib.types; attrsOf inboundType;
      default = {};
      description = "Shadowsocks inbound services keyed by a stable name.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.shadowsocksInbounds != {};
        message = "my.proxy.singBox.shadowsocksInbounds must define at least one inbound when sing-box is enabled.";
      }
    ];

    environment.systemPackages = [cfg.package];

    systemd.services.sing-box = {
      description = "sing-box proxy service";
      wantedBy = ["multi-user.target"];
      after = ["network-online.target"];
      wants = ["network-online.target"];
      preStart = "${script}";
      serviceConfig = {
        ExecStart = "${cfg.package}/bin/sing-box run -c /run/sing-box/config.json";
        Restart = "on-failure";
        RestartSec = "5s";
        RuntimeDirectory = "sing-box";
        RuntimeDirectoryMode = "0755";
        NoNewPrivileges = true;
      };
    };

    my.server.firewall = {
      allowedTCPPorts = tcpFirewallPorts;
      allowedUDPPorts = udpFirewallPorts;
    };
  };
}
