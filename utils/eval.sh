#!/bin/sh
#
# \description  Perform NMI or another evaluation of the resulting clusters
# located in the specified directory comparing to the specified groud truth.
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

DFL_EVALNAME=nmi  # Default name of the evaluation algorithm

if [ $# -lt 4 ]
then
	echo "Usage: $0 <evalbin> <src> <dst_dir> <algname> [<evalname>=$DFL_EVALNAME]\n"\
		" Evaluates files in the <dst_dir> (levels of the hierarchy),"\
		" selects the max value and stores it in the separate file."\
		"  evalbin  - file name of the evaluation application\n"\
		"  src  - file name of original network to be compared\n"\
		"  dst_dir  - directory name of the files to be compared to the origin\n"\
		"  algname  - name of the algorithm that produced the data under evaluation\n"\
		"  evalname  - name of the evaluation algorithm. Default: $DFL_EVALNAME\n"
	exit 0
fi


EVALNAME=${5:-$DFL_EVALNAME}
#echo "EVALNAME: $EVALNAME from $5"
FOUTP=$3_$4.$EVALNAME

if [ -f $FOUTP ]
then
	rm $FOUTP
fi

for f in `find $3 -type f`
do
	echo `LD_LIBRARY_PATH=. $1 $2 $f 2> /dev/null` "\t$f" >> $FOUTP
done

BESTVAL=`sort -g -r $FOUTP | head -n 1`
#echo "Best value for $3: $BESTVAL"

BASEDIR=`echo $3 | sed 's/\(.*\)\/\(.*\)/\1/'`
#echo  "BASEDIR: $BASEDIR from $3"

TASK=`echo $3 | sed "s/\(.*\)\/\(.*\)/\2/"`
FINFILE=`echo "$BASEDIR/$4.$EVALNAME"`
echo $BESTVAL | sed "s/\(.*\)/$TASK\t\1/" >> $FINFILE
#echo "Results for $TASK outputted into $FINFILE: $BESTVAL"
