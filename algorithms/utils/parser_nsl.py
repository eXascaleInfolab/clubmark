#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: Implementation of the NSL (Network Specified By <Links>(Edges / Args)) parser
	NSL format is a generalizaiton of NCOL, SNAP and  and Edge/Arcs Graph formats.
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2016-07
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import os  # Pathes processing
from igraph import Graph


def asymnet(netext, asym=None):
	"""Whether the network is asymmetric (directed, specified by arcs rather than edges)

	netext  - network extension (starts with '.'): .nse or .nsa
	asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions

	return  - the networks is asymmetric (specified by arcs)
	"""
	return asym if netext not in ('.nse', '.nsa') else netext == '.nsa'


def dflnetext(asym):
	"""Get default networks extension for the network

	asym  - whether the network is asymmetric (directed) or symmetric (undirected)

	return  - respective extension of the network file having leading '.'
	"""
	return '.ns' + ('a' if asym else 'e')


def loadNsl(network, directed=None):
	"""Load the graph from NSL(nse, nsa) file"""
	if directed is None:
		directed = asymnet(os.path.splitext(network)[1])
		assert directed is not None, ('Nsl file with either standart extension or'
			' explicit network type specification is expected')

	graph = None
	with open(network) as finp:
		# Prase the header if exists
		ndsnum = 0  # The number of nodes
		#lnsnum = 0  # The number of links (edges or arcs)
		weighted = None  # The network is weighted
		for ln in finp:
			#ln = ln.lstrip()
			if not ln:
				continue
			if ln[0] == '#':
				ln = ln[1:].split(None, 6)
				if len(ln) >= 2 and ln[0].lower() == 'nodes:':
					ndsnum = int(ln[1].rstrip(','))
				# Parse arcs/edges number optionally
				i = 2
				if len(ln) >= i+2 and ln[i].lower() == ('arcs:' if directed else 'edges:'):
					#lnsnum = int(ln[3].rstrip(','))
					i += 2
				if len(ln) >= i+2 and ln[i].lower() == 'weighted:':
					weighted = bool(int(ln[5].rstrip(',')))  # Note: int() is required because bool('0') is True
			break

		links = []
		weights = []
		nodes = set()
		lastnode = None
		for ln in finp:
			# Skip empty lines and comments
			#ln = ln.lstrip()
			if not ln or ln[0] == '#':
				continue
			parts = ln.split(None, 2)
			if weighted is not None:
				if len(parts) != 2 + weighted:
					raise ValueError('Weights are inconsistent; weighted: {}, line: {}'
						.format(weighted, ' '.join(parts)))
			else:
				weighted = len(parts) == 3

			if lastnode != parts[0]:
				lastnode = parts[0]
				nodes.add(lastnode)
			links.append((parts[0], parts[1]))
			# Extend nodes with dest node for the undirected network
			if not directed:
				nodes.add(parts[1])
			if len(parts) > 2:
				weights.append(float(parts[2]))

		assert not ndsnum or len(nodes) == ndsnum, 'Validation of the number of nodes failed'
		if not ndsnum:
			ndsnum = len(nodes)
		#nodes = list(nodes)
		#nodes.sort()
		nodes = tuple(nodes)

		graph = Graph(n=ndsnum, directed=directed)
		graph.vs["name"] = nodes
		# Make a map from the input ids to the internal ids of the vertices
		ndsmap = {name: i for i, name in enumerate(nodes)}
		graph.add_edges([(ndsmap[ln[0]], ndsmap[ln[1]]) for ln in links])
		if weights:
			graph.es["weight"] = weights
	return graph
