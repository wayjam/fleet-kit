{
  lib,
  pkgs,
  ...
}: {
  imports = [
    ./kvm-server.nix
  ];

  environment.systemPackages = with pkgs; [
    age
    git
    gnutar
    jq
    just
    nix
    openssh
    pciutils
    procps
    qemu_kvm
    sops
    util-linux
    xz
    zstd
  ];

  nix = {
    gc.automatic = lib.mkDefault true;
    optimise.automatic = lib.mkDefault true;
    settings = {
      experimental-features = lib.mkForce ["nix-command" "flakes"];
      builders-use-substitutes = lib.mkDefault true;
      trusted-users = lib.mkForce ["root" "@wheel"];
    };
  };
}
