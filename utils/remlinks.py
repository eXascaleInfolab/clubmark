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
		raise ValueError('Unexpected number of arguments: ' + str(len(args)))
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
		isheader = True
		header = []
		weighted = False
		netstat = {}  # Number of links for the node
		try:
			for line in finp:
				# Check for the leadig spaces
				i = 0
				lnlen = len(line)
				while(i < lnlen and line[i].isspace()):
					i += 1
				# Skip comments except the header section
				if i == lnlen or line[i] == '#':
					if isheader:
						header.append(line)
					continue
				isheader = False
				# Skip leading spaces
				if i != 0:
					line = line[i:]
				# Parse the line
				line = line.split()
				sid = int(line[0])
				did = int(line[1])
				if len(line) > 2:
					# Note: float() conversion can be taken to insure correct values
					# and reduce the amount of recured RAM
					network[(sid, did)] = line[2]
					weighted = True
				else:
					network[(sid, did)] = '1'
				count = netstat.get(sid, 0) + 1
				netstat[sid] = count
		except ValueError as err:
			print('ERROR, the weight value is invalid in the line: {}. {}'.format(line, err))
		# Remove specified number of lines
		linksCount = len(network)
		if isinstance(linksNum, float):
			linksNum = int(linksCount * linksNum)
		if linksNum * 2 >= linksCount:
			raise ValueError('Too many links is assumed to be removed: {} of {}'
			', less than 50% is expected.'.format(linksNum, linksCount))

		# Check whether the network directed or not
		# Note: we assume that the network links are specified either by edges or by bidirected symmetric arcs
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
		omitls = np.unique(np.array([random.randint(0, linksCount-1) for _ in range(np.uint32(linksNum + expcolis + 1.25 * expcolis / linksCount))]
			, dtype=np.uint32))[:linksNum]  # Leaves unique links + sorts, take up to linksNum items
		# Get keys by indexes to consider also directed network if requried
		print('  linksCount: {}, unique omitls: {}'.format(linksCount, len(omitls)))
		assert len(omitls) >= linksNum * 0.9, ('The number of generated removing link indices is too small'
			', omitls num: {}, linksNum: {}'.format(len(omitls), round(linksNum * 0.9)))
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
			# Output the header if any correcting the number of nodes
			update = True  # Update the header
			for ln in header:
				if update:
					# Update the number of edges/arcs, the number of nodes remains permanent
					ll = ln.lower()
					iend = len(ll)  # End index in the line
					# Replace values of the specified header markers
					hmark = 'edges:' if not directed else 'arcs:'
					ihm = ll.find(hmark)
					if ihm:
						ihm += len(hmark)
						while ihm < iend and ll[ihm].isspace():
							ihm += 1
						ihme = ihm + 1
						# Find the ending index of the value
						while ihme < iend and not ll[ihme].isspace() and ll[ihme] != ',':
							ihme += 1
						if ihme < iend and ll[ihme] == ',':
							ihme += 1
						# Replace the fragment [ihm:ihme] with the updated value in the original line
						if ihme <= iend:
							ln = ''.join((ln[:ihm], str(len(network)) + ',', ln[ihme:]))
					update = False
				fout.write(ln)
			# Fetch keys (ids) via the lookup
			for key, val in viewitems(network):
				if weighted:
					# Note: the input values like 0.3 are represented ugly without the precision specification in case of float values
					fout.write('{}\t{}\t{}\n'.format(key[0], key[1], val))  # Note: :.6 ~ :.6g, .6f should no be used because it might zeroize lightweight links
				else:
					fout.write('{}\t{}\n'.format(key[0], key[1]))


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
