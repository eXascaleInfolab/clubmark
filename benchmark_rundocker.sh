#!/bin/sh
#
# \description  Starts benchmarking from the docker container environment
#
# The benchmarking is started under the current user on the current host
# directory, which is bound to the docker container directory.
# The specified arguments are passed to the benchmarking being run in the container.
#
# \author Artem V L <luart@ya.ru>

# Notes:
# - $@  - are the input arguments passed to the benchmark started from the container
# - $UID or `id -u $USER` - user id of the current user, otherwise 'root' is used.
# $UID might not be defined in "sh"

echo "Starting docker from \"`pwd`\" under user \"$USER\" with the benchmark arguments: $@"
WORK_DIR=/opt/pycabem  # Working directory of the benchmark
# Notes:
# - quoted $@ is required to retain internal quotation inside the arguments
# - python3 is used to run the benchmark instead of pypy to reduce the number of
# dependencies, because otherwise Python is also required to install the psutil
# via pip on pypy
docker run -it -u `id -u $USER` -w ${WORK_DIR} -v `pwd`:${WORK_DIR} --entrypoint python3 luaxi/pycabem:env-U16.04-v2.0 ./benchmark.py "$@"
# Or to open "bash" shell in the benchmarking directory:
# $ docker run -it -u `id -u $USER` -w ${WORK_DIR} -v `pwd`:${WORK_DIR} --entrypoint bash luaxi/pycabem:env-U16.04-v2.0
