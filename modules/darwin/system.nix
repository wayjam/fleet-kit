{
  myvars,
  pkgs,
  ...
}: {
  # Wire the inventory's configured user into nix-darwin's shared system setup.
  system.primaryUser = myvars.userName;

  # Make zsh available for macOS's default shell environment under nix-darwin.
  environment.shells = [pkgs.zsh];
}
