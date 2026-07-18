{
  myvars,
  pkgs,
  ...
}:
###################################################################################
#
#  macOS's System configuration
#
#  All the configuration options are documented here:
#    https://daiderd.com/nix-darwin/manual/index.html#sec-options
#
###################################################################################
{
  system = {
    primaryUser = myvars.userName;

    # Re-apply settings that macOS often drops after darwin-rebuild / sleep.
    # nix-darwin's system.defaults / keyboard.userKeyMapping write prefs, but the
    # live session (hidutil mapping, trackpad daemon) needs an extra push.
    activationScripts.postActivation.text = ''
      user_uid="$(id -u ${myvars.userName} 2>/dev/null || true)"
      if [ -n "$user_uid" ] && [ "$user_uid" != "0" ]; then
        as_user() {
          launchctl asuser "$user_uid" sudo -u ${myvars.userName} --set-home "$@"
        }

        # --- Caps Lock ↔ Left Control (hidutil; survives better than only
        # system.keyboard.userKeyMapping when the HID stack resets) ---
        # 0x700000039 = Caps Lock, 0x7000000E0 = Left Control
        as_user hidutil property --set '{
          "UserKeyMapping":[
            {
              "HIDKeyboardModifierMappingSrc": 0x700000039,
              "HIDKeyboardModifierMappingDst": 0x7000000E0
            },
            {
              "HIDKeyboardModifierMappingSrc": 0x7000000E0,
              "HIDKeyboardModifierMappingDst": 0x700000039
            }
          ]
        }' || true

        # --- Three-finger drag (拖移样式 → 三指拖移) ---
        # Symptom we fix: System Settings already shows "三指拖移", but the
        # gesture does nothing until prefs are re-pushed AND Dock reloads.
        # Three-finger Mission Control / App Exposé swipes conflict with drag.
        for domain in \
          com.apple.AppleMultitouchTrackpad \
          com.apple.driver.AppleBluetoothMultitouch.trackpad
        do
          as_user defaults write "$domain" TrackpadThreeFingerDrag -int 1
          as_user defaults write "$domain" TrackpadThreeFingerHorizSwipeGesture -int 0
          as_user defaults write "$domain" TrackpadThreeFingerVertSwipeGesture -int 0
          as_user defaults write "$domain" TrackpadThreeFingerTapGesture -int 0
          # classic drag styles off so "拖移样式" is three-finger only
          as_user defaults write "$domain" Dragging -int 0
          as_user defaults write "$domain" DragLock -int 0
        done
        as_user defaults write NSGlobalDomain com.apple.trackpad.threeFingerDragGesture -bool true 2>/dev/null || true
        as_user defaults write com.apple.dock showMissionControlGestureEnabled -bool false 2>/dev/null || true
        as_user defaults write com.apple.dock showAppExposeGestureEnabled -bool false 2>/dev/null || true

        # Flush prefs cache, then force UI/trackpad stack to reread.
        killall -u ${myvars.userName} cfprefsd 2>/dev/null || true
        sleep 0.3
        # activateSettings must run in the user GUI session, not only as root.
        as_user /System/Library/PrivateFrameworks/SystemAdministration.framework/Resources/activateSettings -u 2>/dev/null || true
        # Dock owns many trackpad gesture bindings; restart it so three-finger
        # drag becomes live without logging out.
        killall -u ${myvars.userName} Dock 2>/dev/null || true
      else
        echo "darwin postActivation: user ${myvars.userName} not found (uid=$user_uid); skip per-user remap" >&2
      fi
    '';

    defaults = {
      menuExtraClock.Show24Hour = true; # show 24 hour clock

      # customize dock
      dock = {
        autohide = true;
        show-recents = false; # disable recent apps

        # customize Hot Corners(触发角, 鼠标移动到屏幕角落时触发的动作)
        wvous-tl-corner = 2; # top-left - Mission Control
        # wvous-tr-corner = 13; # top-right - Lock Screen
        wvous-bl-corner = 3; # bottom-left - Application Windows
        wvous-br-corner = 4; # bottom-right - Desktop
      };

      # customize finder
      finder = {
        _FXShowPosixPathInTitle = true; # show full path in finder title
        AppleShowAllExtensions = true; # show all file extensions
        FXEnableExtensionChangeWarning = false; # disable warning when changing file extension
        QuitMenuItem = true; # enable quit menu item
        ShowPathbar = true; # show path bar
        ShowStatusBar = true; # show status bar
      };

      # customize trackpad
      # 拖移样式 → 三指拖移. UI can show ON while gesture is dead until
      # postActivation reloads Dock (see activationScripts above).
      trackpad = {
        # tap - 轻触触摸板, click - 点击触摸板
        Clicking = true; # enable tap to click(轻触触摸板相当于点击)
        TrackpadRightClick = true; # enable two finger right click
        TrackpadThreeFingerDrag = true; # 三指拖移
      };

      # customize settings that not supported by nix-darwin directly
      # Incomplete list of macOS `defaults` commands :
      #   https://github.com/yannbertrand/macos-defaults
      NSGlobalDomain = {
        # `defaults read NSGlobalDomain "xxx"`
        "com.apple.swipescrolldirection" = true; # enable natural scrolling(default to true)
        "com.apple.sound.beep.feedback" = 0; # disable beep sound when pressing volume up/down key
        AppleKeyboardUIMode = 3; # Mode 3 enables full keyboard control.
        ApplePressAndHoldEnabled = true; # enable press and hold

        # If you press and hold certain keyboard keys when in a text area, the key’s character begins to repeat.
        # This is very useful for vim users, they use `hjkl` to move cursor.
        # sets how long it takes before it starts repeating.
        InitialKeyRepeat = 15; # normal minimum is 15 (225 ms), maximum is 120 (1800 ms)
        # sets how fast it repeats once it starts.
        KeyRepeat = 3; # normal minimum is 2 (30 ms), maximum is 120 (1800 ms)

        NSAutomaticCapitalizationEnabled = false; # disable auto capitalization(自动大写)
        NSAutomaticDashSubstitutionEnabled = false; # disable auto dash substitution(智能破折号替换)
        NSAutomaticPeriodSubstitutionEnabled = false; # disable auto period substitution(智能句号替换)
        NSAutomaticQuoteSubstitutionEnabled = false; # disable auto quote substitution(智能引号替换)
        NSAutomaticSpellingCorrectionEnabled = false; # disable auto spelling correction(自动拼写检查)
        NSNavPanelExpandedStateForSaveMode = true; # expand save panel by default(保存文件时的路径选择/文件名输入页)
        NSNavPanelExpandedStateForSaveMode2 = true;
      };

      # Customize settings that not supported by nix-darwin directly
      # see the source code of this project to get more undocumented options:
      #    https://github.com/rgcr/m-cli
      #
      # All custom entries can be found by running `defaults read` command.
      # or `defaults read xxx` to read a specific domain.
      CustomUserPreferences = {
        ".GlobalPreferences" = {
          # automatically switch to a new space when switching to the application
          AppleSpacesSwitchOnActivate = true;
        };
        NSGlobalDomain = {
          # Add a context menu item for showing the Web Inspector in web views
          WebKitDeveloperExtras = true;
        };
        "com.apple.AppleMultitouchTrackpad" = {
          TrackpadThreeFingerDrag = 1;
          TrackpadThreeFingerHorizSwipeGesture = 0;
          TrackpadThreeFingerVertSwipeGesture = 0;
          TrackpadThreeFingerTapGesture = 0;
          Dragging = 0;
          DragLock = 0;
        };
        "com.apple.driver.AppleBluetoothMultitouch.trackpad" = {
          TrackpadThreeFingerDrag = 1;
          TrackpadThreeFingerHorizSwipeGesture = 0;
          TrackpadThreeFingerVertSwipeGesture = 0;
          TrackpadThreeFingerTapGesture = 0;
          Dragging = 0;
          DragLock = 0;
        };
        "com.apple.finder" = {
          ShowExternalHardDrivesOnDesktop = true;
          ShowHardDrivesOnDesktop = true;
          ShowMountedServersOnDesktop = true;
          ShowRemovableMediaOnDesktop = true;
          _FXSortFoldersFirst = true;
          # When performing a search, search the current folder by default
          FXDefaultSearchScope = "SCcf";
        };
        "com.apple.desktopservices" = {
          # Avoid creating .DS_Store files on network or USB volumes
          DSDontWriteNetworkStores = true;
          DSDontWriteUSBStores = true;
        };
        "com.apple.spaces" = {
          "spans-displays" = 0; # Display have seperate spaces
        };
        "com.apple.WindowManager" = {
          EnableStandardClickToShowDesktop = 0; # Click wallpaper to reveal desktop
          StandardHideDesktopIcons = 0; # Show items on desktop
          HideDesktop = 0; # Do not hide items on desktop & stage manager
          StageManagerHideWidgets = 0;
          StandardHideWidgets = 0;
        };
        "com.apple.screensaver" = {
          # Require password immediately after sleep or screen saver begins
          askForPassword = 1;
          askForPasswordDelay = 0;
        };
        "com.apple.screencapture" = {
          location = "~/Desktop";
          type = "png";
        };
        "com.apple.AdLib" = {
          allowApplePersonalizedAdvertising = false;
        };
        # Prevent Photos from opening automatically when devices are plugged in
        "com.apple.ImageCapture".disableHotPlug = true;
      };

      loginwindow = {
        GuestEnabled = false; # disable guest user
        SHOWFULLNAME = true; # show full name in login window
      };
    };

    # keyboard settings is not very useful on macOS
    # the most important thing is to remap option key to alt key globally,
    # but it's not supported by macOS yet.
    keyboard = {
      enableKeyMapping = true; # enable key mapping so that we can use `option` as `control`

      remapCapsLockToControl = false; # handled by userKeyMapping below
      remapCapsLockToEscape = false;
      userKeyMapping = [
        {
          # Caps Lock -> Left Control
          HIDKeyboardModifierMappingSrc = 30064771129; # 0x700000039
          HIDKeyboardModifierMappingDst = 30064771344; # 0x7000000E0
        }
        {
          # Left Control -> Caps Lock
          HIDKeyboardModifierMappingSrc = 30064771344; # 0x7000000E0
          HIDKeyboardModifierMappingDst = 30064771129; # 0x700000039
        }
      ];

      # swap left command and left alt
      # so it matches common keyboard layout: `ctrl | command | alt`
      #
      # disabled, caused only problems!
      swapLeftCommandAndLeftAlt = false;
    };
  };

  # Add ability to used TouchID for sudo authentication
  security.pam.services.sudo_local.touchIdAuth = true;

  # Re-apply Caps Lock ↔ Control at every login (hidutil is session-scoped;
  # sleep/logout can drop the mapping even when prefs look correct).
  launchd.user.agents.caps-ctrl-swap = {
    serviceConfig = {
      Label = "org.fleetkit.caps-ctrl-swap";
      ProgramArguments = [
        "/usr/bin/hidutil"
        "property"
        "--set"
        ''{"UserKeyMapping":[{"HIDKeyboardModifierMappingSrc":0x700000039,"HIDKeyboardModifierMappingDst":0x7000000E0},{"HIDKeyboardModifierMappingSrc":0x7000000E0,"HIDKeyboardModifierMappingDst":0x700000039}]}''
      ];
      RunAtLoad = true;
    };
  };

  # Create /etc/zshrc that loads the nix-darwin environment.
  # this is required if you want to use darwin's default shell - zsh
  environment.shells = [
    pkgs.zsh
  ];
}
