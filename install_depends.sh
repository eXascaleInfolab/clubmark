#!/bin/sh
# Install all external libraries
# Note: this script is designed for Linux Ubuntu and might also work on Debian

# Install  libstdc++.so.6
#
# libstdc++.so.6: version GLIBCXX_3.4.20  for hirecs and modularity evaluation is require in Ubuntu 14.04.
# degault libstdc++6 is fine on Ubuntu 16.04+
# sudo add-apt-repository ppa:ubuntu-toolchain-r/test

sudo apt-get -y update
sudo apt-get -y install libstdc++6

sudo apt-get -y install pypy
# TODO: install pip into pypy and python-igraph from the pypy_pip

# python-igraph for Louvain execution with NMI-compatible results output
sudo apt-get install libxml2-dev  # Required by python-igraph
sudo pip install python-igraph

# Install Java for GaNXIS
sudo apt-get -y install openjdk
