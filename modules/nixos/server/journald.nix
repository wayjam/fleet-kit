{
  config,
  lib,
  ...
}: let
  cfg = config.my.server.journald;
in {
  options.my.server.journald = {
    persistent = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Keep systemd journal logs across reboots.";
    };

    runtimeMaxUse = lib.mkOption {
      type = lib.types.str;
      default = "128M";
      description = "Maximum journal size when logs are stored in volatile runtime storage.";
    };

    systemMaxUse = lib.mkOption {
      type = lib.types.str;
      default = "256M";
      description = "Maximum journal size when logs are stored persistently on disk.";
    };

    rateLimitInterval = lib.mkOption {
      type = lib.types.str;
      default = "30s";
      description = "Time interval used by journald rate limiting.";
    };

    rateLimitBurst = lib.mkOption {
      type = lib.types.int;
      default = 1000;
      description = "Maximum number of messages accepted during the rate limit interval.";
    };
  };

  config.services.journald = {
    storage =
      if cfg.persistent
      then "persistent"
      else "volatile";
    rateLimitInterval = cfg.rateLimitInterval;
    rateLimitBurst = cfg.rateLimitBurst;
    extraConfig =
      if cfg.persistent
      then "SystemMaxUse=${cfg.systemMaxUse}"
      else "RuntimeMaxUse=${cfg.runtimeMaxUse}";
  };
}
