{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.nix-remote-builder;
in {
  options.my.nix-remote-builder = {
    enable = lib.mkEnableOption "remote Nix builder baseline";

    trustedUsers = lib.mkOption {
      type = with lib.types; listOf str;
      default = ["root"];
      description = "Users allowed to perform trusted Nix operations on the remote builder.";
    };

    packages = lib.mkOption {
      type = with lib.types; listOf package;
      default = with pkgs; [
        nix
        openssh
      ];
      description = "Minimal packages required for remote Nix builder access.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = cfg.packages;

    nix.settings = {
      experimental-features = lib.mkDefault ["nix-command" "flakes"];
      builders-use-substitutes = lib.mkDefault true;
      trusted-users = lib.mkDefault cfg.trustedUsers;
    };
  };
}
