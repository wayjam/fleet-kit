{
  nixpkgs,
  system,
  hostName,
  ...
}: let
  myvars = import ../../vars {inherit (nixpkgs) lib;};

  # user level
  mycfgs = {
  };
in {
  root = {
    system.stateVersion = "25.05";
  };

  inherit myvars;

  module = {
    config,
    pkgs,
    lib,
    impermanence,
    disko,
    ...
  }: {
    # sys level
    inherit (mycfgs);

    imports = [
      disko.nixosModules.disko

      ./boot.nix
      ./disko.nix
      ./network.nix
      ./ssh.nix

      ../../modules/nixos/server/ssh.nix
      ../../modules/nixos/server/firewall.nix
      ../../modules/nixos/server/disk-expansion.nix
    ];

    my.server = {
      firewall.enable = true;
      diskExpansion = {
        enable = true;
        rootPartitionNumber = 3;
      };
    };
  };
}
