{...}: {
  imports = [
    ./system.nix
    ./homebrew-mirror.nix
    ./apps.nix
    ./host-users.nix
  ];
}
