#!/bin/sh
# Install all external libraries

#sudo apt-get install pypy
# TODO: install pip into pypy and python-igraph from the pypy_pip

# python-igraph for Louvain execution with NMI-compatible results output
sudo pip install python-igraph

# Install  libstdc++.so.6: version GLIBCXX_3.4.20
#sudo add-apt-repository ppa:ubuntu-toolchain-r/test 
#sudo apt-get update
#sudo apt-get install libstdc++6
