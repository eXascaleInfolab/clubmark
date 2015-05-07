#!/bin/sh
# \author Artem V L <luart@ya.ru>  http://exascale.info http://lumais.com

DFL_EVALNAME=nmi  # Default name of the evaluation algorithm

if [ $# -lt 4 ]
then
	echo "Usage: $0 <evalbin> <src> <dst_dir> <algorithm> [<evalname>=$DFL_EVALNAME]\n"\
		"  evalbin  - filen ame of the evaluation application\n"\
		"  src  - file name of original network to be compared\n"\
		"  dst_dir  - directory name of the files to be compared to teh origin\n"\
		"  algorithm  - name of the algorithm that prodiced the data under evaluation\n"\
		"  evalname  - name of the evaluation algorithm. Default: $DFL_EVALNAME\n"
	exit 0
fi

EVALNAME=${5:-$DFL_EVALNAME}
#echo "EVALNAME: $EVALNAME"
FOUTP=$3_$4.$EVALNAME

if [ -f $FOUTP ]
then
	rm $FOUTP
fi

for f in `find $3 -type f`
do
	LD_LIBRARY_PATH=. $1 $2 $f 2> /dev/null >> $FOUTP
done

BESTVAL=`sort -g -r $FOUTP | head -n 1`
echo "Best value for $3: $BESTVAL"

#echo "DestDir: $3"
BASEDIR=`echo $3 | sed 's/\(.*\)\/\.*/\1/'`
#echo  "BASEDIR: $BASEDIR"

TASK=`echo $3 | sed "s/\(.*\)\/\(\.*\)/\2/"`
FINFILE=`echo "$BASEDIR/$4.$EVALNAME"`
#echo "TASK: $TASK,  FINFILE:  $FINFILE"
echo $BESTVAL | sed "s/\(.*\)/$TASK\t\1/" >> $FINFILE
