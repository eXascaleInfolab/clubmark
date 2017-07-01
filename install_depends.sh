#!/bin/sh
# Install all external libraries
# Note: this script is designed for Linux Ubuntu and might also work on Debian

sudo apt-get -y update

# Get errorcode of the last operation and terminate if the update failed
ERR=$?
if [ $ERR -ne 0 ]
then
	echo "ERROR, the dependencies installation terminated, \"apt-get update\" failed with the code $ERR"
	exit $ERR
fi

# Note: libstdc++6 version GLIBCXX_3.4.20+ is required only on the outdated Ubuntu (before 16.04)
sudo apt-get -y install libstdc++6
# sudo add-apt-repository ppa:ubuntu-toolchain-r/test

sudo apt-get -y install pypy
# TODO: install pip into pypy and python-igraph from the pypy_pip

# python-igraph for Louvain execution with NMI-compatible results output
sudo apt-get -y install libxml2-dev zlib1g-dev  # Required by python-igraph
sudo pip install python-igraph

# Install Java for GaNXIS
sudo apt-get -y install openjdk

# For RGMC
sudo apt-get -y install libboost-program-options1.58.0

# For gecmi (NMI ovp multi-resolution evaluation)
sudo apt-get -y install libtbb2
