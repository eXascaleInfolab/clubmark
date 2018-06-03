#!/bin/sh
#
# \description  Run benchmarking on the specified directories for the
# predefined algorithm
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

if [ $# -lt 1 ]
then
	echo "Usage: $0 <dir1> <dir2> ...\n"\
		" Executes and evaluates predefined algorithm on the specified input directories."
	exit 0
fi


# Note: pypy also can be used, but psutil should be installed there first, also as h5py
PYTHON=`whereis python3 | grep "/"`
if [ "$PYTHON" ]
then
	PYTHON="python3"
else 
	PYTHON="python"
fi
#echo "Starting under" $PYTHON

ALG="DaocA_s_r"  # Algorithm to be evaluated;  Scp;  DaocA, DaocA_s_r
TIMEOUT=3h  # Hours

mkdir "results/${ALG}" 2> /dev/null
for dir in "$@"
do
	# Skip dir path, leaving only the name
	dirname=`echo $dir | sed 's/.*\/\([^/]*\)/\1/'`
	#echo $dirname
	nohup $PYTHON ./benchmark.py -i="$dir" -a=$ALG -r -t=$TIMEOUT > "results/${ALG}/bench_${dirname}.log" \
		2> "results/${ALG}/bench_${dirname}.err" &
done
