{...}: {
  imports = [
    ../server/base.nix
    ../server/firewall-options.nix
  ];

  my.server.base.enable = true;
}
