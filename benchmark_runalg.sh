#!/bin/sh
#
# \description  Run benchmarking on the specified directories for the
# predefined algorithm
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

if [ $# -lt 2 ]
then
	echo "Usage: $0 <dir1> <dir2> ...\n"\
		" Executes and evaluates predefined algorithm on the specified input directories."
	exit 0
fi


PYTHON=`whereis pypy | grep "/"`
echo PYTHON1: $PYTHON
if [ "$PYTHON" ]
then
	PYTHON="pypy"
else 
	PYTHON="python"
fi

ALG="scp"  # Algorithm to be evaluated
TIMEOUT=3  # Hours
for dir in "$@"
do
	# Skip dir path, leaving only the name
	dirname=`echo $dir | sed 's/.*\/\([^/]*\)/\1/'`
	#echo $dirname
	nohup $PYTHON ./benchmark.py -i="$dir" -a=$ALG -e -th=$TIMEOUT > "results/${ALG}/bench_${dirname}.log" \
		2> "results/${ALG}/bench_${dirname}.err" &
done
