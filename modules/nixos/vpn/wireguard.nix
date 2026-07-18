{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.vpn.wireguard;

  peerType = lib.types.submodule {
    options = {
      publicKey = lib.mkOption {
        type = lib.types.str;
        description = "Peer public key.";
      };

      presharedKeyFile = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional runtime file containing the peer preshared key.";
      };

      allowedIPs = lib.mkOption {
        type = with lib.types; listOf str;
        default = [];
        description = "Allowed IP CIDRs for this peer.";
      };

      endpoint = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional peer endpoint in host:port form.";
      };

      persistentKeepalive = lib.mkOption {
        type = lib.types.nullOr lib.types.int;
        default = null;
        description = "Optional persistent keepalive interval in seconds.";
      };
    };
  };

  interfaceType = lib.types.submodule {
    options = {
      ips = lib.mkOption {
        type = with lib.types; listOf str;
        default = [];
        description = "Interface addresses, for example 10.0.0.1/24.";
      };

      listenPort = lib.mkOption {
        type = lib.types.nullOr lib.types.port;
        default = null;
        description = "Optional UDP listen port.";
      };

      privateKeyFile = lib.mkOption {
        type = lib.types.str;
        description = "Runtime file containing the interface private key.";
      };

      mtu = lib.mkOption {
        type = lib.types.nullOr lib.types.int;
        default = null;
        description = "Optional interface MTU.";
      };

      peers = lib.mkOption {
        type = with lib.types; listOf peerType;
        default = [];
        description = "WireGuard peers.";
      };

      openFirewall = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Open listenPort through my.server.firewall.";
      };
    };
  };

  enabledInterfaces = lib.mapAttrs (_: interface:
    {
      inherit (interface) ips privateKeyFile peers;
    }
    // lib.optionalAttrs (interface.listenPort != null) {
      listenPort = interface.listenPort;
    }
    // lib.optionalAttrs (interface.mtu != null) {
      mtu = interface.mtu;
    })
  cfg.interfaces;

  firewallPorts =
    lib.unique
    (lib.concatMap
      (interface:
        if interface.openFirewall && interface.listenPort != null
        then [interface.listenPort]
        else [])
      (lib.attrValues cfg.interfaces));
in {
  options.my.vpn.wireguard = {
    enable = lib.mkEnableOption "WireGuard interfaces";

    interfaces = lib.mkOption {
      type = with lib.types; attrsOf interfaceType;
      default = {};
      description = "WireGuard interfaces keyed by interface name.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.interfaces != {};
        message = "my.vpn.wireguard.interfaces must define at least one interface when WireGuard is enabled.";
      }
    ];

    environment.systemPackages = [pkgs.wireguard-tools];
    networking.wireguard.interfaces = enabledInterfaces;
    my.server.firewall.allowedUDPPorts = firewallPorts;
  };
}
