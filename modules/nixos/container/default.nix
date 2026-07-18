{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.my.container;
in {
  options.my.dev = {
    enable = mkEnableOption "Container";
  };

  config = mkIf cfg.enable {
    virtualisation.containers.enable = true;
    virtualisation = {
      docker.enable = false;
      podman = {
        enable = true;

        # Create a `docker` alias for podman, to use it as a drop-in replacement
        dockerCompat = true;

        # Required for containers under podman-compose to be able to talk to each other.
        defaultNetwork.settings.dns_enabled = true;
      };
    };

    environment.systemPackages = with pkgs; [
      # podman-tui # status of containers in the terminal
      # docker-compose # start group of containers for dev
      podman-compose # start group of containers for dev
    ];

    users.users.myuser = {
      isNormalUser = true;
      extraGroups = ["podman"];
    };

    virtualisation.oci-containers.backend = "podman";
    # https://wiki.nixos.org/wiki/Podman
    # virtualisation.oci-containers.containers = {
    # container-name = {
    #   image = "container-image";
    #   autoStart = true;
    #   ports = ["127.0.0.1:1234:1234"];
    # };
    # };
  };
}
