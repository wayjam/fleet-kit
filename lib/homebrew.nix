# Homebrew helpers
{lib}: {
  # generate homebrew casks list from mycfgs
  # usage: mkBrewCasks lib mycfgs
  mkBrewCasks = mycfgs:
    (lib.optional (mycfgs.my.alacritty.enable or false) "alacritty")
    ++ (lib.optional (mycfgs.my.wezterm.enable or false) "wezterm")
    ++ (lib.optional (mycfgs.my.ghostty.enable or false) "ghostty");
}
