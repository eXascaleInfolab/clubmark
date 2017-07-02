#!/bin/sh
#
# \description  Starts shell in the benchmarking from the docker container environment
#
# The benchmarking is started under the current user on the current host
# directory, which is bound to the docker container directory.
# The specified arguments are passed to the shell in the container.
#
# \author Artem V L <luart@ya.ru>

# Notes:
# - $@  - are the input arguments passed to the benchmark started from the container
# - $UID or `id -u $USER` - user id of the current user, otherwise 'root' is used.
# $UID might not be defined in the non-bash shell (sh, etc)

echo "Starting docker from \"`pwd`\" under user \"$USER\""
docker run -it -u `id -u $USER` -w /opt/benchmark -v `pwd`:/opt/benchmark --entrypoint "" luaxi/pycabem:env-U16.04-v2.0 $@
