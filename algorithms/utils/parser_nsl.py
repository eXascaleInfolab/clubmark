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
try:
	from igraph import Graph
except ImportError:
	Graph = None  # Note: for some functions the Graph class is not required

_DEBUG_TRACE = False  # Trace start / stop and other events to stderr;  1 - brief, 2 - detailed, 3 - in-cycles


def asymnet(netext, asym=None):
	"""Whether the network is asymmetric (directed, specified by arcs rather than edges)
	Note: file extension based value overwrites asym parameter for the known extensions

	netext  - network extension (starts with '.'): .nse or .nsa
	asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions

	return  - the networks is asymmetric (specified by arcs)
	"""
	return asym if netext not in ('.nse', '.nsa') else netext == '.nsa'


def dflnetext(asym):
	"""Get default file extension for the inptut network

	asym  - whether the network is asymmetric (directed) or symmetric (undirected)

	return  - respective extension of the network file having leading '.'
	"""
	return '.ns' + ('a' if asym else 'e')


class NetInfo(object):
	"""Network information (description) encoded in the file header"""
	def __init__(self, directed, ndsnum, lnsnum, weighted):
		"""Network information attributes

		directed  - the input network is directed (can me asymmetric),
			None  - not specified explicitly (symmetric, undirected by default)
		ndsnum  - the number of nodes in the network
		lnsnum  - the number of links (arcs if directed, otherwise edges) in the network
		weighted  - the network is weighted, None means undefined
		"""
		assert ((directed is None or isinstance(directed, bool)) and isinstance(ndsnum, int)
			and isinstance(lnsnum, int) and (weighted is None or isinstance(weighted, bool))
			), ('Invalid type of arguments:  directed: {}, ndsnum: {}, lnsnum: {}, weighted: {}'
			.format(directed, ndsnum, lnsnum, weighted))
		self.directed = directed
		self.ndsnum = ndsnum
		self.lnsnum = lnsnum
		self.weighted = weighted


def parseHeaderNsl(network, directed=None):
	"""Load the header of NSL(nse, nsa) file

	network  - file name of the input network
	directed  - whether the input network is directed
		None  - define automatically by the file extension

	return NetInfo  - network information fetched from the header
	"""
	directed = asymnet(os.path.splitext(network)[1].lower())
	#assert directed is not None, ('Nsl file with either standart extension or'
	#	' explicit network type specification is expected')

	with open(network) as finp:
		# Prase the header if exists
		ndsnum = 0  # The number of nodes
		lnsnum = 0  # The number of links (edges or arcs)
		weighted = None  # The network is weighted
		# Marker of the header start
		mark = 'nodes:'
		marklen = len(mark)
		for ln in finp:
			#ln = ln.lstrip()
			if not ln:
				continue
			if ln[0] == '#':
				# The header should start whith the mark
				if ln[1:].lstrip()[:marklen].lower() != mark:
					continue
				try:
					ln = ln[1:].split(None, 6)
					for sep in ':,':
						lnx = []
						for part in ln:
							lnx.extend(part.rstrip(sep).split(sep, 3))
						ln = lnx
					if _DEBUG_TRACE:
						print('  "{}" header tokens: {}'.format(network, ln))
					if len(ln) >= 2 and ln[0].lower() == 'nodes':
						ndsnum = int(ln[1])
					# Parse arcs/edges number optionally
					i = 2
					if len(ln) >= i+2 and ln[i].lower() == ('arcs' if directed else 'edges'):
						lnsnum = int(ln[3])
						i += 2
					if len(ln) >= i+2 and ln[i].lower() == 'weighted':
						weighted = bool(int(ln[5]))  # Note: int() is required because bool('0') is True
				except ValueError as err:
					# Part of the attributes could be initialized, others just have initial values
					print('WARNING, NSL header is corrupted: ', err)  # Note: this is a minor issue
			break

	return NetInfo(directed=directed, ndsnum=ndsnum, lnsnum=lnsnum, weighted=weighted)


def loadNsl(network, directed=None):
	"""Load the graph from NSL(nse, nsa) file

	network  - file name of the input network
	directed  - whether the input network is directed
		None  - define automatically by the file extension
	"""
	if Graph is None:
		raise ImportError('ERROR, the igraph.Graph is required to be imported')

	graph = None
	with open(network) as finp:
		# Prase the header if exists
		netinfo = parseHeaderNsl(finp, directed)
		directed = netinfo.directed
		weighted = netinfo.weighted

		# ATTENTION: links and weights should be synchronized
		links = []  # Pairs (tuples) of links
		weights = []  # Weight for each pair of links
		nodes = set()
		lastnode = None
		for ln in finp:
			# Skip empty lines and comments
			# Note: only whole line comments are allowed
			#ln = ln.lstrip()
			if not ln or ln[0] == '#':
				continue
			parts = ln.split(None, 2)
			if weighted is None:
				weighted = len(parts) == 3
			elif len(parts) != 2 + weighted:
				raise ValueError('Weights are inconsistent; weighted: {}, line: {}'
					.format(weighted, ' '.join(parts)))

			if lastnode != parts[0]:
				lastnode = parts[0]
				nodes.add(lastnode)
			links.append((parts[0], parts[1]))
			# Extend nodes with dest node for the undirected network to not miss the nodes
			if not directed:
				nodes.add(parts[1])
			if weighted:
				weights.append(float(parts[2]))

		assert not netinfo.ndsnum or len(nodes) == netinfo.ndsnum, 'Validation of the number of nodes failed'
		if not netinfo.ndsnum:
			netinfo.ndsnum = len(nodes)
		#nodes = list(nodes)
		#nodes.sort()
		nodes = tuple(nodes)

		graph = Graph(n=netinfo.ndsnum, directed=directed)
		graph.vs["name"] = nodes
		# Make a map from the input ids to the internal ids of the vertices
		ndsmap = {name: i for i, name in enumerate(nodes)}
		graph.add_edges([(ndsmap[ln[0]], ndsmap[ln[1]]) for ln in links])
		if weights:
			assert len(links) == len(weights), 'Weights are not synchronized with links'
			graph.es["weight"] = weights
	return graph
