#!/bin/sh
# Install all external libraries
# Note: this script is designed for Linux Ubuntu and might also work on Debian

sudo apt-get -y install pypy
# TODO: install pip into pypy and python-igraph from the pypy_pip

# Install  libstdc++.so.6: version GLIBCXX_3.4.20  for hirecs and modularity evaluation
sudo add-apt-repository ppa:ubuntu-toolchain-r/test 
sudo apt-get -y update
sudo apt-get -y install libstdc++6

# python-igraph for Louvain execution with NMI-compatible results output
sudo pip install python-igraph

# Install Java for GaNXIS
sudo apt-get -y install openjdk
