#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: copy network omitting some links

:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
:Date: 2015-06
"""
from __future__ import print_function, division  # Required for stderr output, must be the first import
try:
	# Required to efficiently traverse items of dictionaries in both Python 2 and 3
	from future.utils import viewitems
	from future.builtins import range
except ImportError as err:
	# Use own implementation of view methods
	def viewMethod(obj, method):
		"""Fetch view method of the object

		obj  - the object to be processed
		method  - name of the target method, str

		return  target method or AttributeError

		>>> callable(viewMethod(dict(), 'items'))
		True
		"""
		viewmeth = 'view' + method
		ometh = getattr(obj, viewmeth, None)
		if not ometh:
			ometh = getattr(obj, method)
		return ometh

	viewitems = lambda dct: viewMethod(dct, 'items')()

	# Replace range() implementation for Python2
	try:
		range = xrange
	except NameError:
		pass  # xrange is not defined in Python3, which is fine
from math import log10
import sys
import os
import random
import numpy as np


def outFile(filename, frac=''):
	"""Construct output file name from the input file name

	filename: str  - base file name
	frac: float|str  - fraction of the links to be reduced

	return str  - resulting file name
	"""
	name, ext = os.path.splitext(filename)  # Extract name and ext
	return ''.join((name, '_rl{:03}'.format(int(round(frac*1000))), ext))


def parseArgs(args):
	"""Parse user-specified parameters

	return
		linksNum  - number of links to be omitted (each link is omitted in both directions).
			Either absolute number or percent (0, 1)
		inpnet  - file name of the input network
		outnet  - file name of the output network
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	if len(args) < 2:
		raise ValueError('Unexpected number of arguments: {}' + len(args))
	linksNum = int(args[0]) if args[0][-1] != '%' else float(args[0][:-1]) / 100
	if linksNum <= 0 or (isinstance(linksNum, float) and linksNum >= 1):
		raise ValueError('linksNum is out of range: ' + str(linksNum))
	inpnet = args[1]
	outnet = outFile(inpnet, linksNum) if len(args) < 3 else args[2]
	return linksNum, inpnet, outnet


def remlinks(*args):
	"""Remove specified number of the network links

	Raises:
		ValueError  - invalid number of links to be removed is requested
	"""
	linksNum, inpnet, outnet = parseArgs(args)
	with open(inpnet, 'r') as finp:
		print(''.join(('Reading input network: ', inpnet, '...')))
		network = {}
		weighted = False
		netstat = {}  # Number of links for the node
		for line in finp:
			# Check for the leadig spaces
			i = 0
			lnlen = len(line)
			while(i < lnlen and line[i].isspace()):
				i += 1
			# Skip comments
			if i == lnlen or line[i] == '#':
				continue
			# Skip leading spaces
			if i != 0:
				line = line[i:]
			# Parse the line
			line = line.split()
			sid = int(line[0])
			did = int(line[1])
			if len(line) > 2:
				network[(sid, did)] = float(line[2])
				weighted = True
			else:
				network[(sid, did)] = 1
			count = netstat.get(sid, 0) + 1
			netstat[sid] = count
		# Remove specified number of lines
		linksCount = len(network)
		if isinstance(linksNum, float):
			linksNum = int(linksCount * linksNum)
		if linksNum * 2 >= linksCount:
			raise ValueError('Too many links is assumed to be removed: {} of {}'
			', less than 50% is expected.'.format(linksNum, linksCount))

		# Check whether the network directed or not
		directed = True
		sid, did = next(iter(network))
		if network.get((did, sid)) is None:
			directed = False  # Undirected
		else:
			linksNum /= 2  # Links on both directions should be removed
		# Generate links indices to be removed
		random.seed()
		# Note: the expected number of collisions is linksNum / linksCount, and the larger number of links the more precise this estimation
		expcolis = max(linksNum * (1 + min(0.35, 1 / log10(linksNum))) / linksCount, 16)
		omitls = np.unique(np.array([random.randint(0, linksCount-1) for _ in range(np.uint32(linksNum + expcolis + expcolis / linksCount))]
			, dtype=np.uint32))[:linksNum]  # Leaves unique links + sorts, take up to linksNum items
		# Get keys by indexes to consider also directed network if requried
		print('  linksCount: {}, unique omitls: {}'.format(linksCount, len(omitls)))
		assert len(omitls) >= linksNum * 0.95, ('The number of generated removing link indices is too small'
			', omitls num: {}, linksNum * 0.95: {}'.format(len(omitls), linksNum * 0.95))
		omitkeys = []
		irem = omitls[0]
		j = 1
		for i, key in enumerate(network):
			if i != irem:
				continue
			if netstat[key[0]] <= 1:
				irem = i + 1
				continue
			if j < len(omitls):
				irem = omitls[j]
				j += 1
				if irem <= i:
					irem = i + 1
			omitkeys.append(key)
			netstat[key[0]] -= 1
			if directed and netstat[key[1]] > 1:
				omitkeys.append((key[1], key[0]))
				netstat[key[1]] -= 1
		print('  {} {}directed links are going to be removed'.format(len(omitkeys), '' if directed else 'un'))
		for key in omitkeys:
			del network[key]
		del omitkeys
		# Copy all links excluding the omitting
		# Create the output dir if required
		outpath = os.path.split(outnet)[0]
		if outpath and not os.path.exists(outpath):
			os.makedirs(outpath)
		with open(outnet, 'w') as fout:
			print(''.join(('Forming output network: ', outnet, '...')))
			# Fetch keys (ids) via the lookup
			for key, val in viewitems(network):
				if weighted:
					fout.write('{} {} {:.6f}\n'.format(key[0], key[1], val))
				else:
					fout.write('{} {}\n'.format(key[0], key[1]))


if __name__ == '__main__':
	if len(sys.argv) > 2:
		remlinks(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} <num_links>[%] <inp_network> [<outp_network>]',
			'Copies dataset, omitting specified number / percent of links randomly, but avoiding hanging nodes.'
			'Network is specified via links: "<src_id: integer> <dst_id: integer> [<weight: float>]" respecting comments'
			' (#) and direction (the link in both directions is removed).',
			'  <num_links>[%]  - number / float percent of links to be omitted',
			'    Note: a link can be removed from the node only if it has more than one link, i.e. hanging nodes are not formed',
			'  <inp_network>  - file of the original network to be processed, format: <src_id> <dst_id> [<weight>]',
			'  <outp_network>  - file of the output network with omitted links in the same format as the input network',
			)).format(sys.argv[0]))
