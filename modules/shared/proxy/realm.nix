{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.proxy.realm;

  forwardType = lib.types.submodule {
    options = {
      listenAddress = lib.mkOption {
        type = lib.types.str;
        default = "0.0.0.0";
        description = "Address Realm listens on.";
      };

      listenPort = lib.mkOption {
        type = lib.types.port;
        description = "Port Realm listens on.";
      };

      remote = lib.mkOption {
        type = lib.types.str;
        description = "Remote target in host:port form.";
      };

      protocol = lib.mkOption {
        type = lib.types.enum ["tcp" "udp" "tcp+udp"];
        default = "tcp";
        description = "Forwarding protocol.";
      };

      through = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional source IP or address for outbound connections.";
      };

      interface = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional outbound interface.";
      };

      listenInterface = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional listen interface.";
      };

      nofile = lib.mkOption {
        type = lib.types.nullOr lib.types.int;
        default = null;
        description = "Optional nofile limit passed to Realm.";
      };

      extraArgs = lib.mkOption {
        type = with lib.types; listOf str;
        default = [];
        description = "Additional Realm CLI arguments.";
      };

      openFirewall = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Open listenPort through my.server.firewall.";
      };
    };
  };

  protocolArgs = protocol:
    {
      tcp = [];
      udp = ["--udp" "--ntcp"];
      "tcp+udp" = ["--udp"];
    }
    .${protocol};

  optionalArg = flag: value:
    if value == null
    then []
    else [flag value];

  mkService = name: forward: {
    description = "Realm port forward ${name}";
    wantedBy = ["multi-user.target"];
    after = ["network-online.target"];
    wants = ["network-online.target"];
    serviceConfig = {
      ExecStart = lib.escapeShellArgs ([
          "${cfg.package}/bin/realm"
          "--listen"
          "${forward.listenAddress}:${toString forward.listenPort}"
          "--remote"
          forward.remote
        ]
        ++ protocolArgs forward.protocol
        ++ optionalArg "--through" forward.through
        ++ optionalArg "--interface" forward.interface
        ++ optionalArg "--listen-interface" forward.listenInterface
        ++ optionalArg "--nofile" (
          if forward.nofile == null
          then null
          else toString forward.nofile
        )
        ++ forward.extraArgs);
      Restart = "on-failure";
      RestartSec = "5s";
      DynamicUser = true;
      AmbientCapabilities = ["CAP_NET_BIND_SERVICE"];
      CapabilityBoundingSet = ["CAP_NET_BIND_SERVICE"];
      NoNewPrivileges = true;
    };
  };

  forwards = lib.attrValues cfg.forwards;

  tcpFirewallPorts =
    lib.unique
    (lib.concatMap
      (forward:
        if forward.openFirewall && (forward.protocol == "tcp" || forward.protocol == "tcp+udp")
        then [forward.listenPort]
        else [])
      forwards);

  udpFirewallPorts =
    lib.unique
    (lib.concatMap
      (forward:
        if forward.openFirewall && (forward.protocol == "udp" || forward.protocol == "tcp+udp")
        then [forward.listenPort]
        else [])
      forwards);
in {
  options.my.proxy.realm = {
    enable = lib.mkEnableOption "Realm port forwarding";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.realm;
      description = "Realm package to run.";
    };

    forwards = lib.mkOption {
      type = with lib.types; attrsOf forwardType;
      default = {};
      description = "Realm forward services keyed by a stable name.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.forwards != {};
        message = "my.proxy.realm.forwards must define at least one forward when Realm is enabled.";
      }
    ];

    environment.systemPackages = [cfg.package];
    systemd.services = lib.mapAttrs' (name: forward:
      lib.nameValuePair "realm-${name}" (mkService name forward))
    cfg.forwards;

    my.server.firewall = {
      allowedTCPPorts = tcpFirewallPorts;
      allowedUDPPorts = udpFirewallPorts;
    };
  };
}
