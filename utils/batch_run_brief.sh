#! /bin/sh
# \descr Execute specified set of testcases and output brief statistics into the stdout
# \author Artem V L <luart@ya.ru>  http://lumais.com  http://exascale.info
# \copyright Apache License, Version 2.0: http://www.apache.org/licenses/LICENSE-2.0.html
# >	Simple explanation: https://tldrlegal.com/license/apache-license-2.0-(apache-2.0)

APP=daoc  # Executing app  // hirecs
TESTCASES=./testcases.txt  # Line separated testcasts to be executed with # comments
SHOW_USAGE=0

# Use 1+ argument - filterMarg
if [ $# -ge 1 ]
then
	if [ "$1" = "-h" ]
	then
		SHOW_USAGE=1
	fi
	
	TESTCASES=$1  # optional argument (fast strategy)
	# Use 2+ arguments
	if [ $# -ge 2 ]
	then
		# EARGS=${@:2}  # optional argument (fast strategy); Works in bash only
		shift  # Shift the first argument
		EARGS=$@	
	fi
else
	SHOW_USAGE=1
fi

if [ $SHOW_USAGE -eq 1 ]
then
	echo "Usage: $0 <testcases_file> [<filterMarg>]"
	exit 0
fi	

# Version of the app including clustering strategy
echo -n "=== $APP "`./$APP -v`", params: "
if [ "$EARGS" != "" ]
then
	echo -n $EARGS
else
	echo -n "DEFAULT"
fi
echo " ==="

while read -r tcase
do
	# Skip comments
	if [ "`echo $tcase | sed -r 's/^\s*(#)?.*/\1/'`" = "#" ] || [ "$tcase" = "" ]
	#if [ ${tcase:0:1} = "#" ]
	then
		continue
	fi
	# Extract the statistic only
	printf "# "$tcase | sed -r 's/.*\/(\w+)(\.\w+)?$/\1\t/'  # Extract name of the executing tescase
	# Skip ending comments in the testcases
	tcase=`printf $tcase | sed -r 's/(.*)\s*#.*/\1\t/'`
	#./exectime ./$APP -oc $EARGS $tcase 2>&1 1> /dev/null |
	./exectime -b ./$APP $EARGS $tcase 2>&1 | \
		sed -n "/(^$APP:)|(failed\$)|(core dumped\$)/p;\$!{/^\$/!h};\${G;p}"  # G <-> H;x
		#sed -n "/^$APP:/p;/(core dumped)$/p;\$!{/^\$/!h};\${G;p}"
		#tail -n 6 | sed -n -e 's/^Result:\s*\(.*\)/\1/p;$p'
		#sed -e ':a;N;$!ba;s/\n/ /' -r -e 's/.*(mod:[^\n]+).*(time: \w+\.\w+ sec).*(\w+\.\w+ Mb).*/\1;  \2, \3/'
	echo  # print newline
done < $TESTCASES

# hg identify  -n  - get current local revision
