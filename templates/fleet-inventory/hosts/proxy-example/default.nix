{
  config,
  inputs,
  pkgs,
  ...
}: let
  myvars = import ../../vars {inherit (pkgs) lib;};
in {
  imports = [
    inputs.sops-nix.nixosModules.sops
    inputs.fleetkit.nixosModules.profiles-kvm-server
    inputs.fleetkit.nixosModules.proxy-xray
    inputs.fleetkit.nixosModules.proxy-realm
    inputs.fleetkit.nixosModules.monitoring-komari-agent
    inputs.fleetkit.nixosModules.vpn-wireguard
  ];

  system.stateVersion = "25.05";

  sops.defaultSopsFile = ../../secrets/proxy-example.yaml;
  sops.secrets.xray_uuid = {};
  sops.secrets.xray_reality_private_key = {};
  sops.secrets.xray_xhttp_path = {};
  sops.secrets.komari_agent_token = {};
  sops.secrets.wg_private_key = {};

  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  boot.loader.grub.devices = ["/dev/sda"];

  users.mutableUsers = false;
  users.users = {
    root = {
      hashedPassword = myvars.hashedPassword;
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
    };
    admin = {
      isNormalUser = true;
      extraGroups = ["wheel"];
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
      shell = pkgs.zsh;
    };
  };
  programs.zsh.enable = true;

  my.server.ssh = {
    port = 2234;
    authorizedKeys = myvars.sshAuthorizedKeys;
    authorizedKeyUsers = ["root" "admin"];
  };

  my.proxy.xray = {
    enable = true;
    inbounds.vless-reality = {
      type = "vless";
      listenPort = 443;
      uuidFile = config.sops.secrets.xray_uuid.path;
      flow = "xtls-rprx-vision";
      transport = "xhttp";
      xhttp.pathFile = config.sops.secrets.xray_xhttp_path.path;
      reality = {
        enable = true;
        privateKeyFile = config.sops.secrets.xray_reality_private_key.path;
        dest = "www.example.invalid:443";
        serverNames = ["www.example.invalid"];
        shortIds = ["0123456789abcdef"];
      };
    };
  };

  my.proxy.realm = {
    enable = true;
    forwards.ssh-relay = {
      listenPort = 10022;
      remote = "127.0.0.1:22";
      protocol = "tcp";
    };
  };

  my.monitoring.komariAgent = {
    enable = false;
    endpoint = "https://komari.example.invalid";
    tokenFile = config.sops.secrets.komari_agent_token.path;
  };

  my.vpn.wireguard = {
    enable = false;
    interfaces.wg0 = {
      ips = ["10.7.0.1/24"];
      listenPort = 51820;
      privateKeyFile = config.sops.secrets.wg_private_key.path;
      peers = [
        {
          publicKey = "replace-with-peer-public-key";
          allowedIPs = ["10.7.0.2/32"];
          persistentKeepalive = 25;
        }
      ];
    };
  };
}
