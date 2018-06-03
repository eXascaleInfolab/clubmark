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

echo "Ensuring the required host environment..."
CALLDIR=`dirname $0`  # Calling directory (base path) of this script
CALLDIR=`readlink -f ${CALLDIR}`  # Conver path to the absolute canonical path (docker requires the absolute path)
${CALLDIR}/prepare_hostenv.sh

echo "Starting docker from \"`pwd`\" under user \"$USER\""
WORK_DIR=/opt/clubmark  # Working directory of the benchmark inside the Docker container (may not exist on the host)
# Note: quoted $@ is required to retain internal quotation inside the arguments
# Bind Doker :8080 to the host :80 for tcp. To bind with specific host IP: -p IP:8080:80/tcp
# -rm is used to automaticaly clean up the executed container and remove the virtual file system on exit
# Note: the container is not automatically removed after the execution
# and the default loggin is retained and accessible via `docker logs <container>`
docker run -it -p 8080:8080/tcp -u `id -u $USER` -w ${WORK_DIR} -v ${CALLDIR}:${WORK_DIR} --entrypoint "bash" luaxi/clubmark-env:v3.0-U16.04 "$@"

# Note: to redirect host:80 to :8080, where the benchmark WebUI is run:
# # iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
