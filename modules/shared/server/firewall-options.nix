{lib, ...}: {
  options.my.server.firewall = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable host firewall support when the target platform can enforce it.";
    };

    allowedTCPPorts = lib.mkOption {
      type = with lib.types; listOf port;
      default = [];
      description = "TCP ports declared by managed services.";
    };

    allowedUDPPorts = lib.mkOption {
      type = with lib.types; listOf port;
      default = [];
      description = "UDP ports declared by managed services.";
    };

    allowedUDPPortRanges = lib.mkOption {
      type = with lib.types; listOf (submodule {
        options = {
          from = lib.mkOption {
            type = port;
            description = "First UDP port in the allowed range.";
          };
          to = lib.mkOption {
            type = port;
            description = "Last UDP port in the allowed range.";
          };
        };
      });
      default = [];
      description = "UDP port ranges declared by managed services.";
    };

    redirectUDPPortRanges = lib.mkOption {
      type = with lib.types; listOf (submodule {
        options = {
          from = lib.mkOption {
            type = port;
            description = "First UDP port in the redirected range.";
          };
          to = lib.mkOption {
            type = port;
            description = "Last UDP port in the redirected range.";
          };
          target = lib.mkOption {
            type = port;
            description = "Local UDP port that receives redirected traffic.";
          };
        };
      });
      default = [];
      description = "UDP port ranges redirected to local UDP ports.";
    };

    allowPing = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Allow ICMP echo requests when firewall support is available.";
    };
  };
}
