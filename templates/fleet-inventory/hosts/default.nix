{
  inputs,
  pkgs,
  ...
}: {
  nixos = {
    proxy-example = {
      path = ./proxy-example;

      deployment = {
        targetHost = "203.0.113.10";
        targetPort = 2234;
        targetUser = "root";
        buildOnTarget = true;
        tags = ["proxy" "kvm" "example"];
      };
    };

    image-example = {
      image = true;
      path = ./image-example;

      deployment = {
        targetHost = "203.0.113.20";
        targetPort = 2234;
        targetUser = "root";
        buildOnTarget = true;
        tags = ["image" "kvm" "example"];
      };
    };
  };

  system = {
    lxc-example = {
      path = ../lxc/lxc-example/system.nix;
    };
  };
}
