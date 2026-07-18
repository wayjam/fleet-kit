{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.proxy.xray;

  inboundType = lib.types.submodule ({name, ...}: {
    options = {
      type = lib.mkOption {
        type = lib.types.enum ["vless" "shadowsocks"];
        description = "Inbound protocol type.";
      };

      tag = lib.mkOption {
        type = lib.types.str;
        default = name;
        description = "Inbound tag for the generated Xray configuration.";
      };

      listenAddress = lib.mkOption {
        type = lib.types.str;
        default = "0.0.0.0";
        description = "Address Xray listens on.";
      };

      listenPort = lib.mkOption {
        type = lib.types.port;
        description = "Port Xray listens on.";
      };

      openFirewall = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Open the listen port through my.server.firewall.";
      };

      uuidFile = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Runtime file containing the VLESS UUID.";
      };

      flow = lib.mkOption {
        type = lib.types.str;
        default = "";
        description = "VLESS flow value, for example xtls-rprx-vision.";
      };

      transport = lib.mkOption {
        type = lib.types.enum ["tcp" "grpc" "ws" "httpupgrade" "xhttp"];
        default = "tcp";
        description = "VLESS transport type.";
      };

      xhttp = {
        path = lib.mkOption {
          type = lib.types.str;
          default = "";
          description = "Plain xHTTP path. Prefer pathFile for production secrets.";
        };

        pathFile = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Runtime file containing the xHTTP path.";
        };

        host = lib.mkOption {
          type = lib.types.str;
          default = "";
          description = "Optional xHTTP host setting.";
        };

        mode = lib.mkOption {
          type = lib.types.str;
          default = "auto";
          description = "xHTTP mode.";
        };

        settings = lib.mkOption {
          type = with lib.types; attrsOf anything;
          default = {};
          description = "Raw xHTTP settings merged before first-class xHTTP options.";
        };
      };

      reality = {
        enable = lib.mkEnableOption "Reality transport security";

        privateKeyFile = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Runtime file containing the Reality private key.";
        };

        dest = lib.mkOption {
          type = lib.types.str;
          default = "www.microsoft.com:443";
          description = "Reality destination.";
        };

        serverNames = lib.mkOption {
          type = with lib.types; listOf str;
          default = ["www.microsoft.com"];
          description = "Reality server names.";
        };

        shortIds = lib.mkOption {
          type = with lib.types; listOf str;
          default = [""];
          description = "Reality short IDs.";
        };
      };

      method = lib.mkOption {
        type = lib.types.str;
        default = "2022-blake3-aes-128-gcm";
        description = "Shadowsocks method.";
      };

      passwordFile = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
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
      type
      tag
      listenAddress
      listenPort
      flow
      transport
      method
      network
      ;
    uuidFile =
      if inbound.uuidFile == null
      then ""
      else inbound.uuidFile;
    passwordFile =
      if inbound.passwordFile == null
      then ""
      else inbound.passwordFile;
    xhttp = {
      inherit (inbound.xhttp) path host mode settings;
      pathFile =
        if inbound.xhttp.pathFile == null
        then ""
        else inbound.xhttp.pathFile;
    };
    reality = {
      inherit (inbound.reality) enable dest serverNames shortIds;
      privateKeyFile =
        if inbound.reality.privateKeyFile == null
        then ""
        else inbound.reality.privateKeyFile;
    };
  };

  renderedInbounds = lib.mapAttrsToList renderInbound cfg.inbounds;
  inboundsJson = pkgs.writeText "xray-inbounds.json" (builtins.toJSON renderedInbounds);

  hasNetwork = needle: network:
    network == needle || network == "tcp,udp";

  tcpFirewallPorts =
    lib.unique
    (lib.concatMap
      (inbound:
        if ! inbound.openFirewall
        then []
        else if inbound.type == "vless"
        then [inbound.listenPort]
        else if hasNetwork "tcp" inbound.network
        then [inbound.listenPort]
        else [])
      (lib.attrValues cfg.inbounds));

  udpFirewallPorts =
    lib.unique
    (lib.concatMap
      (inbound:
        if inbound.openFirewall && inbound.type == "shadowsocks" && hasNetwork "udp" inbound.network
        then [inbound.listenPort]
        else [])
      (lib.attrValues cfg.inbounds));

  script = pkgs.writeShellScript "render-xray-config" ''
    set -euo pipefail
    install -d -m 0755 /run/xray

    ${pkgs.python3}/bin/python3 - <<'PY'
    import json
    from pathlib import Path

    source_inbounds = json.loads(Path("${inboundsJson}").read_text())
    inbounds = []

    for source in source_inbounds:
      if source["type"] == "vless":
        uuid = Path(source["uuidFile"]).read_text().strip()
        stream_settings = {
          "network": source["transport"],
          "security": "none",
        }

        if source["reality"]["enable"]:
          private_key = Path(source["reality"]["privateKeyFile"]).read_text().strip()
          stream_settings = {
            "network": source["transport"],
            "security": "reality",
            "realitySettings": {
              "dest": source["reality"]["dest"],
              "serverNames": source["reality"]["serverNames"],
              "privateKey": private_key,
              "shortIds": source["reality"]["shortIds"],
            },
          }

        if source["transport"] == "xhttp":
          xhttp = source["xhttp"]
          xhttp_settings = dict(xhttp["settings"])

          path = xhttp["path"]
          if xhttp["pathFile"]:
            path = Path(xhttp["pathFile"]).read_text().strip()
          if path:
            xhttp_settings["path"] = path
          if xhttp["host"]:
            xhttp_settings["host"] = xhttp["host"]
          xhttp_settings["mode"] = xhttp["mode"]

          stream_settings["xhttpSettings"] = xhttp_settings

        inbounds.append({
          "tag": source["tag"],
          "listen": source["listenAddress"],
          "port": source["listenPort"],
          "protocol": "vless",
          "settings": {
            "clients": [
              {
                "id": uuid,
                "flow": source["flow"],
              }
            ],
            "decryption": "none",
          },
          "streamSettings": stream_settings,
        })
      elif source["type"] == "shadowsocks":
        password = Path(source["passwordFile"]).read_text().strip()
        inbounds.append({
          "tag": source["tag"],
          "listen": source["listenAddress"],
          "port": source["listenPort"],
          "protocol": "shadowsocks",
          "settings": {
            "method": source["method"],
            "password": password,
            "network": source["network"],
          },
        })
      else:
        raise ValueError(f"Unsupported Xray inbound type: {source['type']}")

    config = {
      "log": {
        "loglevel": "${cfg.logLevel}",
      },
      "inbounds": inbounds,
      "outbounds": [
        {
          "tag": "direct",
          "protocol": "freedom",
        },
        {
          "tag": "blocked",
          "protocol": "blackhole",
        },
      ],
    }

    Path("/run/xray/config.json").write_text(json.dumps(config, indent=2) + "\n")
    PY
  '';
in {
  options.my.proxy.xray = {
    enable = lib.mkEnableOption "Xray proxy service";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.xray;
      description = "Xray package to run.";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum ["debug" "info" "warning" "error" "none"];
      default = "warning";
      description = "Xray log level.";
    };

    inbounds = lib.mkOption {
      type = with lib.types; attrsOf inboundType;
      default = {};
      description = "Xray inbound services keyed by a stable name.";
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      assertions =
        [
          {
            assertion = cfg.inbounds != {};
            message = "my.proxy.xray.inbounds must define at least one inbound when Xray is enabled.";
          }
        ]
        ++ lib.flatten (lib.mapAttrsToList (name: inbound: [
            {
              assertion = inbound.type != "vless" || inbound.uuidFile != null;
              message = "my.proxy.xray.inbounds.${name}.uuidFile is required for VLESS inbounds.";
            }
            {
              assertion = inbound.type != "vless" || (! inbound.reality.enable) || inbound.reality.privateKeyFile != null;
              message = "my.proxy.xray.inbounds.${name}.reality.privateKeyFile is required when Reality is enabled.";
            }
            {
              assertion =
                inbound.type
                != "vless"
                || inbound.transport != "xhttp"
                || inbound.xhttp.pathFile != null
                || inbound.xhttp.path != ""
                || inbound.xhttp.settings ? path;
              message = "my.proxy.xray.inbounds.${name}.xhttp.pathFile, xhttp.path, or xhttp.settings.path is required when transport is xhttp.";
            }
            {
              assertion = inbound.type != "shadowsocks" || inbound.passwordFile != null;
              message = "my.proxy.xray.inbounds.${name}.passwordFile is required for Shadowsocks inbounds.";
            }
          ])
          cfg.inbounds);

      environment.systemPackages = [cfg.package];

      systemd.services.xray = {
        description = "Xray proxy service";
        wantedBy = ["multi-user.target"];
        after = ["network-online.target"];
        wants = ["network-online.target"];
        preStart = "${script}";
        serviceConfig = {
          ExecStart = "${cfg.package}/bin/xray run -config /run/xray/config.json";
          Restart = "on-failure";
          RestartSec = "5s";
          RuntimeDirectory = "xray";
          RuntimeDirectoryMode = "0755";
        };
      };
    }
    {
      my.server.firewall.allowedTCPPorts = tcpFirewallPorts;
      my.server.firewall.allowedUDPPorts = udpFirewallPorts;
    }
  ]);
}
