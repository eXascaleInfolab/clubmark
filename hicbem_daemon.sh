#!/bin/sh

PYTHON=`whereis pypy | grep "/"`
echo PYTHON1: $PYTHON
if [ "$PYTHON" ]
then
	PYTHON="pypy"
else 
	PYTHON="python"
fi

echo 'Running the benchmark: $ nohup '$PYTHON' hicbem.py &'
nohup $PYTHON hicbem.py snap   1> hichbem.log 2> hichbem.err &
