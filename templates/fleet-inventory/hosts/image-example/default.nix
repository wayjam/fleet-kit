{
  inputs,
  lib,
  pkgs,
  ...
}: let
  myvars = import ../../vars {inherit (pkgs) lib;};
in {
  imports = [
    inputs.disko.nixosModules.disko
    inputs.fleetkit.nixosModules.profiles-kvm-server
    inputs.fleetkit.nixosModules.proxy-realm
  ];

  system.stateVersion = "25.05";
  networking.hostName = "image-example";

  disko = {
    enableConfig = true;
    devices.disk.main = {
      device = "/dev/vda";
      type = "disk";
      # Raw image size built locally. Keep it small enough to upload/dd quickly,
      # but large enough for the NixOS closure and preinstalled services.
      imageSize = "4G";
      content = {
        type = "gpt";
        partitions = {
          bios_boot = {
            size = "1M";
            type = "EF02";
            priority = 0;
          };
          root = {
            name = "NIXROOT";
            size = "100%";
            content = {
              type = "filesystem";
              format = "ext4";
              mountpoint = "/";
            };
          };
        };
      };
    };
  };

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

  my.proxy.realm = {
    enable = true;
    forwards.web-relay = {
      listenPort = 8080;
      remote = "198.51.100.10:80";
      protocol = "tcp";
    };
  };
}
