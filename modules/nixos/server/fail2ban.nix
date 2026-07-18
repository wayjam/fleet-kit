{
  config,
  lib,
  ...
}: let
  cfg = config.my.server.fail2ban;
in {
  options.my.server.fail2ban = {
    enable = lib.mkEnableOption "fail2ban SSH protection";

    maxretry = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "Failed SSH attempts before banning.";
    };

    bantime = lib.mkOption {
      type = lib.types.str;
      default = "1h";
      description = "fail2ban ban duration.";
    };

    findtime = lib.mkOption {
      type = lib.types.str;
      default = "10m";
      description = "fail2ban failure search window.";
    };

    ignoreIP = lib.mkOption {
      type = with lib.types; listOf str;
      default = [];
      description = "IP addresses or CIDRs never banned by fail2ban.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.fail2ban = {
      enable = true;
      ignoreIP = cfg.ignoreIP;
      jails.sshd.settings = {
        enabled = true;
        filter = "sshd";
        port = toString config.my.server.ssh.port;
        maxretry = cfg.maxretry;
        bantime = cfg.bantime;
        findtime = cfg.findtime;
      };
    };
  };
}
