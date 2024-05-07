#!/bin/sh -e

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)

source "$SCRIPT_DIR/entrypoint-common.sh"

cat > /etc/apt/apt.conf.d/10-ybox << EOF
APT::Get::Install-Recommends "0";
APT::Get::Install-Suggests "0";
APT::Install-Recommends "0";
APT::Install-Suggests "0";
EOF

export DEBIAN_FRONTEND=noninteractive

apt-get update

apt-get install -y lsb-release

rel_name=$(lsb_release -cs)

mv /etc/apt/sources.list /etc/apt/sources.list.bak

cat > /etc/apt/sources.list << EOF
deb http://us.archive.ubuntu.com/ubuntu/ $rel_name main restricted universe multiverse
deb http://us.archive.ubuntu.com/ubuntu/ $rel_name-updates main restricted universe multiverse
deb http://us.archive.ubuntu.com/ubuntu/ $rel_name-backports main restricted universe multiverse
deb http://us.archive.ubuntu.com/ubuntu/ $rel_name-security main restricted universe multiverse
EOF

echo_color "$fg_cyan" "Running unminimize" >> $status_file

yes | unminimize

echo_color "$fg_cyan" "Configuring locale" >> $status_file

apt-get install -y locales

# generate the configured locale and assume it is UTF-8
if [ -n "$LANG" ] && ! grep -q "^$LANG UTF-8" /etc/locale.gen; then
  echo "$LANG UTF-8" >> /etc/locale.gen
  # always add en_US.UTF-8 regardless since some apps seem to depend on it
  if [ "$LANG" != "en_US.UTF-8" ]; then
    echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
  fi
  if ! locale-gen; then
    echo_color "$fg_red" "FAILED to generate locale for $LANG, fallback to en_US.UTF-8" >> $status_file
    LANG=en_US.UTF-8
    LANGUAGE="en_US:en"
    export LANG LANGUAGE
  fi
  echo "LANG=$LANG" > /etc/default/locale
  if [ -n "$LANGUAGE" ]; then
    echo "LANGUAGE=\"$LANGUAGE\"" >> /etc/default/locale
  fi
fi

echo_color "$fg_cyan" "Setting up apt-fast and aria2c" >> $status_file

apt-get install -y curl gnupg ca-certificates

echo -e "deb [signed-by=/etc/apt/keyrings/apt-fast.gpg] http://ppa.launchpad.net/apt-fast/stable/ubuntu $rel_name main" > /etc/apt/sources.list.d/apt-fast.list
mkdir -p /etc/apt/keyrings
curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xA2166B8DE8BDC3367D1901C11EE2FF37CA8DA16B" | gpg --dearmor -o /etc/apt/keyrings/apt-fast.gpg

apt-get update
apt-get install -y aria2 apt-fast

echo_color "$fg_cyan" "Installing initial set of packages" >> $status_file

DOWNLOADBEFORE=true apt-fast install -y less man-db manpages bash-completion \
  git patch ed bc unzip fastjar wget openssh-client shared-mime-info \
  ubuntu-minimal iso-codes mesa-utils vainfo intel-media-va-driver-non-free \
  va-driver-all vulkan-tools mesa-vulkan-drivers ca-certificates python3-pip \
  pulseaudio-utils libsasl2-modules libldap-common manpages xdg-user-dirs xauth libgl1-amber-dri

echo_color "$fg_cyan" "Installing additional convenience packages" >> $status_file

DOWNLOADBEFORE=true apt-fast install -y neovim xsel btop kitty-terminfo autojump ncdu fd-find bat tree libtree exa

apt-fast clean
apt-get clean

echo -e '\nexport EDITOR=nvim\nexport VISUAL=nvim' >> /etc/bash.bashrc
echo -e 'export PAGER="less -RL"' >> /etc/bash.bashrc
lesspipe >> /etc/bash.bashrc

echo_color "$fg_cyan" "Installing Starship for fancy bash prompt" >> $status_file

curl -sSL https://starship.rs/install.sh -o starship-install.sh && \
  /bin/sh starship-install.sh -y && rm -f starship-install.sh

echo -e 'eval "$(starship init bash)"' >> /etc/bash.bashrc
