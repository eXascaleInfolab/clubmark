#!/bin/sh
#
# \description  Generate synthetic networks with shuffles and execute
# benchmarking for all algorithms on these networks.
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

# Note: pypy also can be used, but psutil should be installed there first, also as h5py
PYTHON=`whereis python3 | grep "/"`
if [ "$PYTHON" ]
then
	PYTHON="python3"
else 
	PYTHON="python"
fi
#echo "Starting under" $PYTHON

TIMEOUT=1d12h  # 36 hours per singe execution of any algorithm on any network
#DATASETS=syntnets
RESDIR=results  # Directory for the benchmarking results
EXECLOG=bench.log  # Log for the execution status
EXECERR=bench.err  # Log for execution errors

if [ ! -e $RESDIR ]
then
	mkdir $RESDIR
fi

echo "Starting the benchmark in the daemom mode under $PYTHON..."
#  -dw=${DATASETS}
nohup $PYTHON benchmark.py -g=3%5 -r -q  -i='realnets/*/' -t=$TIMEOUT \
  1>> $RESDIR/${EXECLOG} 2>> $RESDIR/${EXECERR} &

# utils/exectime -o=results/bench.rcp -n=netgen_3%5_pypy pypy benchmark.py -g=3%5 -th=8\
# 1>>results/bench.log 2>>results/bench.err

# Examples of the stand-alone execution:
# $ python3 benchmark.py -a="DaocA_s_r Daoc_s_r" -r -i="realnets/*/" -t=42h 1>>./results/bench.log 2>>./results/bench.err
