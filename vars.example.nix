{lib, ...}: rec {
  userName = "example";
  userFullName = "Example User";
  userEmail = "user@example.invalid";
  userSigningKey = "";
  networking = {
    # placeholder only — private inventory owns real networking vars
  };
  hashedPassword = null;
  sshAuthorizedKeys = [
    # "ssh-ed25519 AAAA... comment"
  ];
}
