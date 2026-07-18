{
  config,
  lib,
  ...
}: let
  cfg = config.my.server.tuning;
in {
  options.my.server.tuning = {
    enable = lib.mkEnableOption "general host network and resource tuning";

    enableBbr = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable BBR congestion control and fq queue discipline.";
    };

    fileMax = lib.mkOption {
      type = lib.types.int;
      default = 1048576;
      description = "System-wide file handle limit.";
    };

    nofile = lib.mkOption {
      type = lib.types.int;
      default = 1048576;
      description = "Default systemd NOFILE limit.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.kernel.sysctl =
      {
        "fs.file-max" = cfg.fileMax;
        "net.core.somaxconn" = 65535;
        "net.core.netdev_max_backlog" = 16384;
        "net.ipv4.tcp_fastopen" = 3;
        "net.ipv4.tcp_keepalive_time" = 600;
        "net.ipv4.tcp_keepalive_intvl" = 30;
        "net.ipv4.tcp_keepalive_probes" = 5;
        "net.ipv4.tcp_max_syn_backlog" = 8192;
        "net.ipv4.tcp_fin_timeout" = 15;
        "net.ipv4.tcp_tw_reuse" = 1;
      }
      // lib.optionalAttrs cfg.enableBbr {
        "net.core.default_qdisc" = "fq";
        "net.ipv4.tcp_congestion_control" = "bbr";
      };

    systemd.extraConfig = ''
      DefaultLimitNOFILE=${toString cfg.nofile}
    '';
  };
}
