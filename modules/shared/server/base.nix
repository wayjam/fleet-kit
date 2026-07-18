{
  config,
  lib,
  options,
  pkgs,
  ...
}: let
  cfg = config.my.server.base;
in {
  options.my.server.base = {
    enable = lib.mkEnableOption "shared base configuration for hosts";

    packages = lib.mkOption {
      type = with lib.types; listOf package;
      default = with pkgs; [
        curl
        wget
        rsync
        xz
        zstd
        gnugrep
        gnused
        gawk
        gnutar
        python3
        vim
        git
        htop
        jq
        lsof
        tcpdump
        mtr
        bind
        sudo
        zsh
      ];
      description = "Base packages installed on managed hosts.";
    };
  };

  config =
    lib.mkIf cfg.enable {
      environment.systemPackages = cfg.packages;

      nix.settings = {
        experimental-features = lib.mkDefault ["nix-command" "flakes"];
        builders-use-substitutes = lib.mkDefault true;
      };
    }
    // lib.optionalAttrs (options ? nix.optimise) {
      nix.optimise.automatic = lib.mkDefault true;
    };
}
