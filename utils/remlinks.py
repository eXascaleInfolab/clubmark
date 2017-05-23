#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: copy network omitting some links

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2015-06
"""
import sys
import os
import random
import numpy as np


def outFile(filename, num=''):
	"""Construct output file name from the input file name"""
	name, ext = os.path.splitext(filename)  # Extract name and ext
	return ''.join((name, '_rl', str(num), ext))
	

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
		if linksNum >= linksCount / 2:
			raise ValueError('Too many links is assumed to be removed: {} of {}'
			', less than 50% is expected.'.format(linksNum, linksCount))
		
		# Check whether the network directed or not
		directed = True
		sid, did = next(iter(network))
		if network.get((did,sid)) is None:
			directed = False  # Undirected
		else:
			linksNum /= 2  # Links on both directions should be removed
		# Generate links indices to be removed
		random.seed()
		omitls = np.array([random.randint(0, linksCount-1) for i in range(linksNum)], dtype=np.uint32)
		omitls = np.unique(omitls)  # Leaves unique links + sorts
		linksNum -= len(omitls)
		# Extend omitls up to specified number of links
		remlinks = linksNum
		linksNum = len(omitls)
		while remlinks:
			reminder = np.array([random.randint(0, linksCount-1) for i in range(remlinks)], dtype=np.uint32)
			remlinks = 0
			insinds = np.searchsorted(omitls, reminder)
			for i, ins in enumerate(insinds):
				if ins < linksNum and reminder[i] == omitls[ins]:
					remlinks += 1  # This index is already selected
					continue
				np.insert(omitls, ins, reminder[i])
		# Get keys by indexes to consider also directed network if requried
		print('linksCount: {}, unique omitls: {}'.format(linksCount, len(omitls)))
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
		print('{} {}directed links are going to be removed'.format(len(omitkeys), '' if directed else 'un'))
		for key in omitkeys:
			del network[key]
		del omitkeys
		# Copy all links excluding the omitting
		with open(outnet, 'w') as fout:
			print(''.join(('Forming output network: ', outnet, '...')))
			# Fetch keys (ids) via the lookup
			for key, val in network.items():
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
			'Network is specified via links: "<src_id: integer> <dst_id: integer> [<weight: float>]" respecting comments (#) and direction (the link in both directions is removed).',
			'  <num_links>[%]  - number / float percent of links to be omitted',
			'    Note: a link can be removed from the node only if it has more than one link, i.e. hanging nodes are not formed',
			'  <inp_network>  - file of the original network to be processed, format: <src_id> <dst_id> [<weight>]',
			'  <outp_network>  - file of the output network with omitted links in the same format as the input network',
			)).format(sys.argv[0]))
