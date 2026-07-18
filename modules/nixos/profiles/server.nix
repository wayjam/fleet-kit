{
  inputs,
  lib,
  ...
}: {
  imports = [
    inputs.sops-nix.nixosModules.sops
    ../../nix-core.nix
    ../../shared/server/base.nix
    ../secrets/sops-age-key.nix
    ../server/ssh.nix
    ../server/firewall.nix
    ../server/fail2ban.nix
    ../server/tuning.nix
  ];

  documentation = {
    enable = lib.mkDefault false;
    doc.enable = lib.mkDefault false;
    info.enable = lib.mkDefault false;
    man.enable = lib.mkDefault false;
    nixos.enable = lib.mkDefault false;
  };

  environment.defaultPackages = lib.mkDefault [];

  my.server = {
    base.enable = true;
    ssh.enable = true;
    firewall.enable = true;
    fail2ban.enable = true;
    tuning.enable = true;
  };
}
