#!/bin/sh
#
# \description  Generate synthetic networks with shuffles and execute
# benchmarking for all algorithms on these networks.
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

# Note: pypy also can be used, but psutil should be installed there first
PYTHON=`whereis python3 | grep "/"`
if [ "$PYTHON" ]
then
	PYTHON="python3"
else 
	PYTHON="python"
fi
#echo "Starting under" $PYTHON

TIMEOUT=36  # 36 hours per singe execution of any algorithm on any network
TIMEOUT_UNIT=h
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
nohup $PYTHON benchmark.py -g=3%5 -r -q -t$TIMEOUT_UNIT=$TIMEOUT\
 --stderr-stamp 1>> $RESDIR/${EXECLOG} 2>> $RESDIR/${EXECERR} &

# utils/exectime -o=results/bench.rcp -n=netgen_3%5_pypy pypy benchmark.py -g=3%5 -th=8\
# --stderr-stamp 1>>results/bench.log 2>>results/bench.err
