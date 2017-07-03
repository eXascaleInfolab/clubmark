#!/bin/sh
#
# \description  Install all external libraries for the PyCABeM
# Note: this script is designed for Linux Ubuntu and might also work on Debian
# or other Linuxes
#
# \author Artem V L <luart@ya.ru>

# Update packages information
sudo apt-get -y update
# Get errorcode of the last operation and terminate if the update failed
ERR=$?
if [ $ERR -ne 0 ]
then
	echo "ERROR, the dependencies installation terminated, \"apt-get update\" failed with the code $ERR"
	exit $ERR
fi

# Note: libstdc++6 version GLIBCXX_3.4.20+ is required only on the outdated Ubuntu (before 16.04)
# sudo add-apt-repository ppa:ubuntu-toolchain-r/test  # Required on the outdated Ubuntu (before 16.04)

# Install applications dependencies:
# "libxml2-dev zlib1g-dev python-pip" required for python-igraph, which is required for Louvain (igraph)
# "openjdk-8-jre" (java) is required for GaNXIS
# "libboost-program-options1.58.0" for RGMC
# "libtbb2" for gecmi (NMI ovp multi-resolution evaluation)
sudo apt-get -y install libstdc++6 pypy \
	libxml2-dev zlib1g-dev python-pip \
	openjdk-8-jre \
	libtbb2
