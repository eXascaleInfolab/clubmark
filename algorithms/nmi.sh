#!/bin/sh
# \author Artem V L <luart@ya.ru>  http://exascale.info http://lumais.com

if [ $# -lt 4 ]
then
	echo "Usage: $0 <nmibin> <src> <dst_dir> <algorithm>"
	exit 0
fi

FOUTP=$3_$4.nmi

if [ -f $FOUTP ]
then
	rm $FOUTP
fi

for f in `find $3 -type f`
do
	LD_LIBRARY_PATH=. $1 $2 $f 2> /dev/null >> $FOUTP
done

BESTVAL=`sort -g -r $FOUTP | head -n 1`
echo "Best NMI for $3: $BESTVAL"

#echo "DestDir: $3"
BASEDIR=`echo $3 | sed 's/\(.*\)\/\w*/\1/'`
#echo  "BASEDIR: $BASEDIR"

TASK=`echo $3 | sed "s/\(.*\)\/\(\w*\)/\2/"`
FINFILE=`echo "$BASEDIR/$4.nmi"`
#echo "TASK: $TASK,  FINFILE:  $FINFILE"
echo $BESTVAL | sed "s/\(.*\)/$TASK\t\1/" >> $FINFILE
