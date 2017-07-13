#!/bin/sh
#
# \description  Removes path id suffixes from dirs and files leaving the extension

if [ !$# ]
then
	if [ "${1}" = "-h" ]
	then
		echo "Usage: $0 [<basedir>]\n"\
			"\nRecursively Removes path id suffixes from dirs and files leaving the extension."\
			 "\n<basedir>  - base directory to start."
		exit 0
	fi
	WDIR=${1}  # Working Directory
fi

# Rename items removing the path id suffix leaving the extension
for file in $(find ${WDIR} -name "*#*")
do
	mv -v ${file} `echo ${file} | sed 's/\(.*\)#[0-9]*\(.*\)/\1\2/'`
done
