#!/bin/sh

PYTHON=`whereis pypy | grep "/"`
echo PYTHON1: $PYTHON
if [ "$PYTHON" ]
then
	PYTHON="pypy"
else 
	PYTHON="python"
fi

TIMEOUT=36
TIMEOUT_UNIT=h
DATASETS=syntnets
EXECLOG=hicbem.log  # Log for the execution status
EXECERR=hicbem.err  # Log for execution errors

echo 'Starting the benchmark in daemom mode ...'
nohup $PYTHON hicbem.py -gf -c -r -e -d ${DATASETS} -t$TIMEOUT_UNIT $TIMEOUT  1> ${EXECLOG} 2> ${EXECERR} &
