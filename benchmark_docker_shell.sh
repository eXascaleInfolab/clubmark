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
WORK_DIR=/opt/pycabem  # Working directory of the benchmark
# Note: quoted $@ is required to retain internal quotation inside the arguments
# Bind Doker :8080 to the host :80 for tcp. To bind with specific host IP: -p IP:8080:80/tcp
docker run -it -p 8080:8080/tcp -u `id -u $USER` -w ${WORK_DIR} -v `pwd`:${WORK_DIR} --entrypoint "bash" luaxi/pycabem:v3.0.0a-U16.04 "$@"

# Note: to redirect host:80 to :8080, where the benchmark WebUI is run:
# # iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
