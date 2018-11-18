#!/bin/sh
#
# \description  Unpacking and preparation of the SNAP networks for the benchmarking
#
# The input networks together with ground-truth communities can be downloaded from
# https://snap.stanford.edu/data/#communities to some folder, which should be
# supplied to this script for the archives unpacking and networks renaming.
# Note: the benchmark requires the same file name with different extensions for
# the networks and their ground-truth communities.

WDIR='.'  # Working Directory (current by default)

if [ $# ]
then
	if [ "${1}" = "-h" ]
	then
		echo "Usage: $0 [<snap_dir>]\n"\
			"\nUnpacks and renames SNAP networks and ground-truth communities to"\
			 " have the required file names for the benchmarking."\
			 "\n<snap_dir>  - directory with SNAP datasets, \"$WDIR\" by default."
		exit 0
	fi
	WDIR=${1}
fi

# Unpack
gunzip ${WDIR}/*.gz  2> /dev/null

# Rename networks and clustering
for ext in ".nse" ".cnl"
do
	if [ $ext = ".nse" ]
	then
		SUF='.ungraph.txt'	# Unordered network
	else
		SUF='.all.cmty.txt'	# Fround-truth clustering
	fi
		
	for file in $(find ${WDIR} -type f -name "*$SUF")
	do
		mv -v ${file} `echo ${file} | sed "s/\(.*\)$SUF/\1$ext/"`
	done
done

# TODO: Remove Duplicates
