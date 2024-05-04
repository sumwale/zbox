# Completions for zbox commands, a "Manage containers hosting Linux distributions and apps"

function __fish_zbox_complete_containers
  zbox-ls --format="{{ .Names }}"
end

function __fish_zbox_complete_all_containers
  zbox-ls --all --format="{{ .Names }}"
end

function __fish_zbox_complete_distributions
  set user_supported ~/.config/zbox/distros/supported.list
  set sys_supported ~/.local/lib/python3*/site-packages/zbox/conf/distros/supported.list
  if test -r $user_supported
    /usr/bin/cat $user_supported
  else if test -r $sys_supported 2>/dev/null
    /usr/bin/cat $sys_supported
  end
end

complete -f -c zbox-create -s h -l help -d "show help"
complete -c zbox-create -s n -l name -d "name of the zbox container" -r
complete -c zbox-create -s d -l docker-path -d "path of docker/podman if not in /usr/bin" -r
complete -f -c zbox-create -n "not __fish_seen_subcommand_from (__fish_zbox_complete_distributions)" -a "(__fish_zbox_complete_distributions)"

complete -f -c zbox-destroy -s h -l help -d "show help"
complete -f -c zbox-destroy -s f -l force -d "force destroy the container using SIGKILL if required"
complete -c zbox-destroy -s d -l docker-path -d "path of docker/podman if not in /usr/bin" -r
complete -f -c zbox-destroy -n "not __fish_seen_subcommand_from (__fish_zbox_complete_all_containers)" -a "(__fish_zbox_complete_all_containers)"

complete -f -c zbox-logs -s h -l help -d "show help"
complete -f -c zbox-logs -s f -l follow -d "follow log output like 'tail -f'"
complete -c zbox-logs -s d -l docker-path -d "path of docker/podman if not in /usr/bin" -r
complete -f -c zbox-logs -n "not __fish_seen_subcommand_from (__fish_zbox_complete_all_containers)" -a "(__fish_zbox_complete_all_containers)"

complete -f -c zbox-ls -s h -l help -d "show help"
complete -f -c zbox-ls -s a -l all -d "show all containers including stopped"
complete -c zbox-ls -s d -l docker-path -d "path of docker/podman if not in /usr/bin" -r
complete -f -c zbox-ls -s f -l filter -d "filter in <key>=<value> format" -r
complete -f -c zbox-ls -s s -l format -d "format output using a JSON/Go template string" -r
complete -f -c zbox-ls -s l -l long-format -d "show more extended information"

complete -f -c zbox-restart -s h -l help -d "show help"
complete -c zbox-restart -s d -l docker-path -d "path of docker/podman if not in /usr/bin" -r
complete -f -c zbox-restart -n "not __fish_seen_subcommand_from (__fish_zbox_complete_containers)" -a "(__fish_zbox_complete_all_containers)"

complete -f -c zbox-cmd -s h -l help -d "show help"
complete -c zbox-cmd -s d -l docker-path -d "path of docker/podman if not in /usr/bin" -r
complete -f -c zbox-cmd -n "not __fish_seen_subcommand_from (__fish_zbox_complete_containers)" -a "(__fish_zbox_complete_containers)"


set -l pkg_commands install uninstall update list info search mark clean repair

complete -f -c zbox-pkg -n "not __fish_seen_subcommand_from $pkg_commands" -a install -d "install a package with dependencies"
complete -f -c zbox-pkg -n "not __fish_seen_subcommand_from $pkg_commands" -a uninstall -d "uninstall a package and optionally its dependencies"
complete -f -c zbox-pkg -n "not __fish_seen_subcommand_from $pkg_commands" -a update -d "update some or all packages"
complete -f -c zbox-pkg -n "not __fish_seen_subcommand_from $pkg_commands" -a list -d "list installed packages"
complete -f -c zbox-pkg -n "not __fish_seen_subcommand_from $pkg_commands" -a search -d "search repositories"
