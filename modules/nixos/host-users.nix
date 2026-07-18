{
  hostName,
  myvars,
  pkgs,
  ...
}:
#############################################################
#
#  Host & Users configuration
#
#############################################################
{
  networking.hostName = hostName;

  users.users."${myvars.userName}" = {
    description = myvars.userName;
    isNormalUser = true;
    extraGroups = ["networkmanager" "wheel"]; # 'wheel' for sudo on NixOS
    shell = pkgs.zsh; # Default shell for the user
  };

  programs.zsh.enable = true;
  nix.settings.trusted-users = [myvars.userName];
}
