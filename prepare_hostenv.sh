#!/bin/sh
#
# \description  Prepares host environment for the benchmarking execution.
# Notes:
# - The made setting are reseted on restart
# - Should be called only on the main host even if the benchmark is executed in
#  the docker container. Should not be called in the container.
#
# \author Artem V L <luart@ya.ru>

# Max number of the opened files in the system
MAX_FILES=1048576
# Max number of the opened files by the process
UL_FILES=32768
# Max swappiness, should be 1..10 (low swappiness to hold most of data in RAM)
MAX_SWAP=5


if [ `cat /proc/sys/fs/file-max` -lt $MAX_FILES ]
then
	sudo sysctl -w fs.file-max=$MAX_FILES
	echo "fs.file-max set to $MAX_FILES"
fi

# Max number of the opened files by the process
if [ `ulimit -n` -lt $UL_FILES ]
then
	UHLIMIT=`ulimit -Hn`  # Max allowed hard limit of the opened files
	if [ $UL_FILES -gt $UHLIMIT ]
	then
		UL_FILES=$UHLIMIT
	fi
	ulimit -n $UL_FILES
	echo "ulimit files set to $UL_FILES"
fi

if [ `cat /proc/sys/vm/swappiness` -gt $MAX_SWAP ]
then
	sudo sysctl -w vm.swappiness=$MAX_SWAP
	echo "vm.swappiness set to $MAX_SWAP"
fi

# Note: to set these parameters permanently, add them to the /etc/sysctl.conf

# Optionally, prepare dedirection from :8080 to :80 (works for actual IPs, not for the localhos/loopback):
# sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080

