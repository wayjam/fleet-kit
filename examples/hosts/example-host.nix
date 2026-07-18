{
  nixpkgs,
  system,
  hostName,
}: let
  myvars = {
    userName = "admin";
    userFullName = "Example Admin";
    userEmail = "admin@example.invalid";
    userSigningKey = "";
    networking = import ../vars/networking.nix {inherit (nixpkgs) lib;};
    hashedPassword = null;
    sshAuthorizedKeys = [];
  };
in {
  root = {
    system.stateVersion = "25.05";
    fileSystems."/" = {
      device = "/dev/disk/by-label/nixos";
      fsType = "ext4";
    };
    boot.loader.grub.devices = ["/dev/sda"];
  };

  inherit myvars;

  module = {
    config,
    lib,
    ...
  }: {
    imports = [
      ../modules/nixos/profiles/kvm-server.nix
      ../modules/shared/proxy/xray.nix
      ../modules/shared/proxy/hy2.nix
      ../modules/shared/proxy/realm.nix
      ../modules/shared/web/caddy.nix
      ../modules/nixos/vpn/wireguard.nix
    ];

    my.server.ssh = {
      port = 2234;
      authorizedKeys = myvars.sshAuthorizedKeys;
      authorizedKeyUsers = ["root" myvars.userName];
    };

    # Example only: real secret paths should come from the private inventory repo.
    my.proxy.xray = {
      enable = false;
      inbounds.vless-reality = {
        type = "vless";
        listenPort = 443;
        uuidFile = "/run/secrets/xray_uuid";
      };
    };

    my.proxy.hy2 = {
      enable = false;
      listenPort = 8443;
      passwordFile = "/run/secrets/hy2_password";
      tls = {
        certFile = "/var/lib/acme/example.invalid/fullchain.pem";
        keyFile = "/var/lib/acme/example.invalid/key.pem";
      };
    };
  };
}
