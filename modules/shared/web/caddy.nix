{
  config,
  lib,
  ...
}: let
  cfg = config.my.web.caddy;
in {
  options.my.web.caddy = {
    enable = lib.mkEnableOption "Caddy web server";

    virtualHosts = lib.mkOption {
      type = with lib.types;
        attrsOf (submodule {
          options = {
            extraConfig = lib.mkOption {
              type = lines;
              default = "";
              description = "Caddy virtual host extraConfig.";
            };
          };
        });
      default = {};
      description = "Caddy virtual hosts keyed by domain name.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Open HTTP and HTTPS through my.server.firewall.";
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      services.caddy = {
        enable = true;
        virtualHosts = cfg.virtualHosts;
      };
    }
    {
      my.server.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [80 443];
    }
  ]);
}
