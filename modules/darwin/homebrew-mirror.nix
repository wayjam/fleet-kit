{
  config,
  lib,
  ...
}: let
  cfg = config.my.homebrew.chinaMirror;

  # USTC Homebrew mirrors — only applied when enable = true.
  homebrew_mirror_env = {
    HOMEBREW_API_DOMAIN = "https://mirrors.ustc.edu.cn/homebrew-bottles/api";
    HOMEBREW_BOTTLE_DOMAIN = "https://mirrors.ustc.edu.cn/homebrew-bottles";
    HOMEBREW_BREW_GIT_REMOTE = "https://mirrors.ustc.edu.cn/brew.git";
    HOMEBREW_CORE_GIT_REMOTE = "https://mirrors.ustc.edu.cn/homebrew-core.git";
    HOMEBREW_PIP_INDEX_URL = "https://mirrors.ustc.edu.cn/pypi/simple";
  };
in {
  options.my.homebrew.chinaMirror = {
    enable = lib.mkEnableOption "Homebrew USTC (China) mirrors for bottles/API/git remotes";
  };

  config = lib.mkIf cfg.enable {
    # Set variables for you to manually install homebrew packages.
    environment.variables = homebrew_mirror_env;

    # Set environment variables for nix-darwin before run `brew bundle`.
    system.activationScripts.homebrew.text = let
      env_script = lib.attrsets.foldlAttrs (acc: name: value: acc + "\nexport ${name}=${value}") "" homebrew_mirror_env;
    in
      lib.mkBefore ''
        echo >&2 '${env_script}'
        ${env_script}
      '';
  };
}
