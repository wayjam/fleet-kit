{
  hostName,
  myvars,
  ...
}:
#############################################################
#
#  Host & Users configuration
#
#############################################################
{
  networking.hostName = hostName;
  networking.computerName = hostName;
  system.defaults.smb.NetBIOSName = hostName;

  users.users."${myvars.userName}" = {
    home = "/Users/${myvars.userName}";
    description = myvars.userName;
  };

  nix.settings.trusted-users = [myvars.userName];
}
