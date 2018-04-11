#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: Reduces produced communities to top N with optional synchronization in terms of cooccurances

:Authors: Artem Lutov <luart@ya.ru>
:Organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>,
	Lumais <http://www.lumais.com/>
:Date: 2015-07
"""
import sys
import os  # Pathes processing


def parseParams(args):
	"""Parse user-specified parameters

	return
		comsnum  - number of the largest communities to retain
		resname  - file name of the output
		unique  - output top N communities without duplicates
	"""
	comsnum = 0
	resname = None
	unique = False

	for arg in args:
		# Validate input format
		preflen = 3
		if arg[0] != '-' or (len(arg) <= preflen and arg != '-u'):
			raise ValueError('Unexpected argument: ' + arg)

		if arg[1] == 'n':
			comsnum = int(arg[preflen:])
		elif arg[1] == 'o':
			resname = arg[preflen:]
		elif arg[1] == 'u':
			if arg != '-u':
				raise ValueError('Unexpected argument: ' + arg)
			unique = True
		else:
			raise ValueError('Unexpected argument: ' + arg)

	if not comsnum:
		raise ValueError('The number of resulting communities is not specified')
	return comsnum, resname, unique


def topcommuns(communs, *args):
	"""Fetch out top N largest communities
		communs  - initial communities
	"""
	comsnum, resname, unique = parseParams(args)
	if not resname:
		resname, resext = os.path.splitext(communs)
		resname = ''.join((resname, '_top', str(comsnum), '-u' if unique else '', resext))
	print('Starting topcommuns:'
		'\n\tcommuns: {}'
		'\n\tcomsnum: {}'
		'\n\tresname: {}'
		).format(communs, comsnum, resname)

	allcms = []
	with open(communs, 'r') as fcs:
		for line in fcs:
			allcms.append((len(line.split()), line))
	# Sort allcms by decreasing number of embracing nodes
	allcms.sort(key=lambda x: x[0], reverse=True)
	# Output result
	topcms = set()
	with open(resname, 'w') as fout:
		for cm in allcms[:comsnum]:
			cm = cm[1]
			if unique:
				if cm in topcms:
					continue
				topcms.add(cm)
			fout.write(cm)
	print('Top {} communities are successfully extracted into the {}'.format(comsnum, resname))


if __name__ == '__main__':
	if len(sys.argv) > 2:
		topcommuns(sys.argv[1], *sys.argv[2:])
	else:
		print('\n'.join(('Fetches top n largest communities and stores them in the specified file\n',
			'Usage: {} <allcommuns> -n=<limit> [-u] [-o=<topcommuns>]',  #  [[-s{ig}] -g=<ground_truth>]
			'  -i=<allcommuns>  - file of the produced communities (clusters). Format:'
			' space/tab separated list of nodes (each line is a cluster, where all corresponding nodes are listed)',
			'  -n=<limit>  - number of the top (largest) communities to output',
			'  -u  - guarantee that the fetched top N communities are unique'
			'  -o=<topcommuns>  - file name of the resulting top n communities. Default: <allcommuns>_top<n>'
		)).format(sys.argv[0]))
		