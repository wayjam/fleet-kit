{
  config,
  lib,
  ...
}: let
  cfg = config.my.server.ssh;
in {
  options.my.server.ssh = {
    enable = lib.mkEnableOption "hardened OpenSSH server";

    port = lib.mkOption {
      type = lib.types.port;
      default = 2234;
      description = "OpenSSH listen port.";
    };

    authorizedKeys = lib.mkOption {
      type = with lib.types; listOf str;
      default = [];
      description = "Public SSH keys installed for authorizedKeyUsers.";
    };

    authorizedKeyUsers = lib.mkOption {
      type = with lib.types; listOf str;
      default = ["root"];
      description = "Users that receive authorizedKeys.";
    };

    permitRootLogin = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Allow root login by SSH key for remote bootstrap and deployment.";
    };

    x11Forwarding = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable X11 forwarding.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.openssh = {
      enable = true;
      ports = [cfg.port];
      openFirewall = false;
      settings = {
        KbdInteractiveAuthentication = false;
        PasswordAuthentication = false;
        PermitRootLogin =
          if cfg.permitRootLogin
          then "prohibit-password"
          else "no";
        X11Forwarding = cfg.x11Forwarding;
      };
    };

    users.users = lib.genAttrs cfg.authorizedKeyUsers (_: {
      openssh.authorizedKeys.keys = cfg.authorizedKeys;
    });

    environment.enableAllTerminfo = true;
    my.server.firewall.allowedTCPPorts = [cfg.port];
  };
}
