#!/bin/sh -e

export DEBIAN_FRONTEND=noninteractive

apt-get update

apt-get install -y apt-utils

apt-get install -y sudo dbus

apt-get clean
