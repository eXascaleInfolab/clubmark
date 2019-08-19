#!/bin/sh
#
# \description  Install all external libraries for the PyCABeM
# Note: this script is designed for Linux Ubuntu and might also work on Debian
# or other Linuxes
#
# \author Artem V L <luart@ya.ru>

# Repository for the latest pypy
sudo add-apt-repository -y ppa:pypy/ppa

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
# "hwloc" (includes lstopo) is required to identify enumeration type of CPUs
#  to perform correct CPU affinity masking
# "libxml2-dev zlib1g-dev python-pip" required for python-igraph, which is required for Louvain (igraph)
# "openjdk-8-jre" (java) is required for GaNXIS
# "libboost-program-options1.58.0" for RGMC
# "libtbb2" for gecmi (NMI ovp multi-resolution evaluation)
#
# Pypy related requirements to compile the benchmark:
# libhdf5-serial-dev  (contains hdf5.h but it can not be found during the compilation)
sudo apt-get install -y \
	hwloc \
	python3 python3-pip pypy-dev pypy3-dev \
	libxml2-dev zlib1g-dev \
	openjdk-8-jre \
	libboost-program-options1.58.0 \
	libtbb2

# Check and set locale if required
if [ "$LC_ALL" = '' ]
then
	export LC_ALL="en_US.UTF-8"
	export LC_CTYPE="en_US.UTF-8"
fi

# Note: Python3 and pip3 were installed on previous step
sudo pip3 install --upgrade pip

# Install Python dependencies
# louvain_igraph.py:  python-igraph ...
sudo pip3 install -r pyreqs.txt
