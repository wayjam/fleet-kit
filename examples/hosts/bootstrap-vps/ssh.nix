{
  lib,
  myvars,
  ...
}: {
  # Root 用户的密码和 SSH 密钥。如果网络配置有误，可以用此处的密码在控制台上登录进去手动调整网络配置。
  users.mutableUsers = false;

  users.users.root = lib.mkIf (myvars.hashedPassword != null) {
    hashedPassword = myvars.hashedPassword;
  };
  users.allowNoPasswordLogin = false;

  my.server.ssh = {
    enable = true;
    port = 2234;
    authorizedKeys = myvars.sshAuthorizedKeys;
    authorizedKeyUsers = ["root" myvars.userName];
    permitRootLogin = true;
  };
}
