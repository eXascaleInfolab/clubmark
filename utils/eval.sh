#!/bin/sh
#
# \description  Perform NMI or another evaluation of the resulting clusters
# located in the specified directory comparing to the specified groud truth.
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

DFL_EVALNAME=nmi  # Default name (and file extension) of the evaluation algorithm
DFL_ERRLOG=elog  # Default extension for the error log

# Parse eval app args if any (start with "-")
while [ $2 ]
do
	case $2 in
	-*)
		EOPTS="$EOPTS $2"  # Evalaution options
		shift
		;;
	*)
		break
		;;
	esac
done
#echo "EvalApp: $1, EvalOpts: $EOPTS, src: $2"
#exit 1

if [ $# -lt 4 ]
then
	echo "Usage: $0 <evalbin> [-eval_arg...] <src> <dst_dir> <algname> [<evalname>=$DFL_EVALNAME]\n"\
		" Evaluates files in the <dst_dir> (levels of the hierarchy),"\
		" selects the max value and stores it in the separate file."\
		"  evalbin  - file name of the evaluation application\n"\
		"  -eval_arg...  - evalaution app args having prefix '-'"\
		"  src  - file name of original network to be compared\n"\
		"  dst_dir  - directory name of the files to be compared to the origin\n"\
		"  algname  - name of the algorithm that produced the data under evaluation\n"\
		"  evalname  - name of the evaluation algorithm. Default: $DFL_EVALNAME\n"
	exit 0
fi

EVALNAME=${5:-$DFL_EVALNAME}
#echo "EVALNAME: $EVALNAME from $5"
FOUTP=$3_$4.$EVALNAME
FELOG=$3_$4.elog

# Append the timestamp If the output files exist
if [ -f $FOUTP -o -f $FELOG ]
then
	TIMESTAMP="\n--- "`date +"%Y-%m-%d %H:%M:%S UTC" -u`" ---"
	echo $TIMESTAMP >> $FOUTP
	echo $TIMESTAMP >> $FELOG
fi

for f in `find $3 -type f`
do
	#echo "Processing: $f"
	echo `LD_LIBRARY_PATH=. $1 $EOPTS $2 $f 2>> $FELOG | tail -n 1` "\t$f" >> $FOUTP  # 2> /dev/null
done

BESTVAL=`sort -g -r $FOUTP | head -n 1`
#echo "Best value for $3: $BESTVAL"

BASEDIR=`echo $3 | sed 's/\(.*\)\/\(.*\)/\1/'`
#echo  "BASEDIR: $BASEDIR from $3"

TASK=`echo $3 | sed "s/\(.*\)\/\(.*\)/\2/"`
FINFILE=`echo "$BASEDIR/$4.$EVALNAME"`
echo $BESTVAL | sed "s/\(.*\)/$TASK\t\1/" >> $FINFILE
#echo "Results for $TASK outputted into $FINFILE: $BESTVAL"
