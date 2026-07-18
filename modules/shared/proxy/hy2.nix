{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.proxy.hy2;
  boolJson = value: builtins.toJSON value;
  listen = ":${toString cfg.listenPort}";
  firewallUDPPorts =
    if cfg.openFirewall
    then [cfg.listenPort]
    else [];
  firewallUDPPortRanges =
    if cfg.openFirewall && cfg.portHopping.enable
    then [
      {
        inherit (cfg.portHopping) from to;
      }
    ]
    else [];
  redirectUDPPortRanges =
    if cfg.openFirewall && cfg.portHopping.enable
    then [
      {
        inherit (cfg.portHopping) from to;
        target = cfg.listenPort;
      }
    ]
    else [];
  obfsPasswordFile =
    if cfg.obfsPasswordFile == null
    then ""
    else cfg.obfsPasswordFile;
  script = pkgs.writeShellScript "render-hysteria2-config" ''
    set -euo pipefail
    install -d -m 0755 /run/hysteria2

    ${pkgs.python3}/bin/python3 - <<'PY'
    import json
    from pathlib import Path

    config = {
      "listen": "${listen}",
      "auth": {
        "type": "password",
        "password": Path("${cfg.passwordFile}").read_text().strip(),
      },
      "tls": {
        "cert": "${cfg.tls.certFile}",
        "key": "${cfg.tls.keyFile}",
      },
    }

    if json.loads('${boolJson (cfg.obfsPasswordFile != null)}'):
      config["obfs"] = {
        "type": "salamander",
        "salamander": {
          "password": Path("${obfsPasswordFile}").read_text().strip(),
        },
      }

    if "${cfg.masquerade.proxy.url}" != "":
      config["masquerade"] = {
        "type": "proxy",
        "proxy": {
          "url": "${cfg.masquerade.proxy.url}",
          "rewriteHost": json.loads('${boolJson cfg.masquerade.proxy.rewriteHost}'),
        },
      }

    Path("/run/hysteria2/config.json").write_text(json.dumps(config, indent=2) + "\n")
    PY
  '';
in {
  options.my.proxy.hy2 = {
    enable = lib.mkEnableOption "Hysteria 2 server";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.hysteria;
      description = "Hysteria package to run.";
    };

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 443;
      description = "UDP port Hysteria 2 listens on.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Open the Hysteria 2 UDP listen port through my.server.firewall.";
    };

    portHopping = {
      enable = lib.mkEnableOption "Hysteria 2 port hopping";

      from = lib.mkOption {
        type = lib.types.port;
        default = 20000;
        description = "First UDP port in the Hysteria 2 port hopping range.";
      };

      to = lib.mkOption {
        type = lib.types.port;
        default = 50000;
        description = "Last UDP port in the Hysteria 2 port hopping range.";
      };

      hopInterval = lib.mkOption {
        type = lib.types.str;
        default = "30s";
        description = "Client-side port hopping interval to show in generated profiles.";
      };
    };

    client.insecure = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether generated client profiles should skip TLS certificate verification.";
    };

    passwordFile = lib.mkOption {
      type = lib.types.str;
      description = "Runtime file containing the Hysteria 2 auth password.";
    };

    obfsPasswordFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional runtime file containing the salamander obfs password.";
    };

    tls = {
      certFile = lib.mkOption {
        type = lib.types.str;
        description = "TLS certificate path readable on the target host.";
      };

      keyFile = lib.mkOption {
        type = lib.types.str;
        description = "TLS private key path readable on the target host.";
      };
    };

    masquerade.proxy = {
      url = lib.mkOption {
        type = lib.types.str;
        default = "";
        description = "Optional proxy masquerade URL.";
      };

      rewriteHost = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Whether Hysteria rewrites the Host header for proxy masquerade.";
      };
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      assertions = [
        {
          assertion = cfg.passwordFile != "";
          message = "my.proxy.hy2.passwordFile must point to a runtime secret file.";
        }
        {
          assertion = cfg.tls.certFile != "" && cfg.tls.keyFile != "";
          message = "my.proxy.hy2.tls.certFile and tls.keyFile are required.";
        }
        {
          assertion = ! cfg.portHopping.enable || cfg.portHopping.from <= cfg.portHopping.to;
          message = "my.proxy.hy2.portHopping.from must be less than or equal to portHopping.to.";
        }
      ];

      environment.systemPackages = [cfg.package];

      systemd.services.hysteria2 = {
        description = "Hysteria 2 proxy service";
        wantedBy = ["multi-user.target"];
        after = ["network-online.target"];
        wants = ["network-online.target"];
        preStart = "${script}";
        serviceConfig = {
          ExecStart = "${cfg.package}/bin/hysteria server -c /run/hysteria2/config.json";
          Restart = "on-failure";
          RestartSec = "5s";
          RuntimeDirectory = "hysteria2";
          RuntimeDirectoryMode = "0755";
        };
      };
    }
    {
      my.server.firewall.allowedUDPPorts = firewallUDPPorts;
      my.server.firewall.allowedUDPPortRanges = firewallUDPPortRanges;
      my.server.firewall.redirectUDPPortRanges = redirectUDPPortRanges;
    }
  ]);
}
