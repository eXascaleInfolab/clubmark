#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: Implementation of the Louvain algorithm using igraph framework with input/
	output formats adapted to the NMIs evaluation.
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2015-07
"""
from __future__ import print_function  # Required for stderr output, must be the first import
import sys
import os  # Pathes processing
import argparse
from igraph import Graph


def loadNsl(network, netfmt):
	"""Load the graph from NSL(nse, nsa) file"""
	assert netfmt in ('nsa', 'nse')

	graph = None
	with open(network) as finp:
		# Prase the header if exists
		ndsnum = 0  # The number of nodes
		#lnsnum = 0  # The number of links (edges or arcs)
		weighted = None  # The network is weighted
		directed = netfmt == 'nsa'
		for ln in finp:
			#ln = ln.lstrip()
			if not ln:
				continue
			if ln[0] == '#':
				ln = ln[1:].split(None, 6)
				if len(ln) >= 2 and ln[0].lower() == 'nodes:':
					ndsnum = int(ln[1])
				# Parse arcs/edges number optionally
				i = 2
				if len(ln) >= i+2 and ln[i].lower() == ('arcs:' if directed else 'edges:'):
					#lnsnum = int(ln[3])
					i += 2
				if len(ln) >= i+2 and ln[i].lower() == 'weighted:':
					weighted = bool(int(ln[5]))  # Note: int() is required because bool('0') is True
			break

		links = []
		weights = []
		nodes = set()
		nodename = None
		for ln in finp:
			# Skip empty lines and comments
			#ln = ln.lstrip()
			if not ln or ln[0] == '#':
				continue
			parts = ln.split(None, 2)
			if weighted is not None:
				if len(parts) != 2 + weighted:
					raise ValueError('Weights are inconsistent; weighted: {}, line: {}'.format(weighted, ' '.join(parts)))
			else:
				weighted = len(parts) == 3

			if nodename != parts[0]:
				nodename = parts[0]
				nodes.add(nodename)
			links.append((parts[0], parts[1]))
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


def louvain(args):
	"""Execute Louvain algorithm on the specified network and output resulting communities to the specified file

	args.network  - input network
	args.inpfmt  - format of the input network
	args.outpfile  - output file name WITHOUT extension
	args.outpext  - extension of the output file
	"""

	#args.inpfmt = args.inpfmt.lower()  # It should be already in the lower case
	print('Starting Louvain (igraph) clustering:'
		'\n\tnetwork: {}, format: {}'
		'\n\tperlev output: {}, communities: {}'
		.format(args.network, args.inpfmt, args.perlev, args.outpfile + args.outpext))
	# Load Data from simple real-world networks
	graph = None
	if args.inpfmt == 'ncol':  # Note: it's not clear whether .nce/.snap can be correctly readed as .ncol
		graph = Graph.Read_Ncol(args.network, directed=False)  # Weight are considered if present; .ncol format is always undirected
	elif args.inpfmt == 'pjk':
		graph = Graph.Read_Pajek(args.network)
	elif args.inpfmt == 'nse':
		graph = loadNsl(args.network, args.inpfmt)
	else:
		raise ValueError('Unknown network format: ' + args.inpfmt)

	#community_multilevel(self, weights=None, return_levels=False)
	#@param weights: edge attribute name or a list containing edge
	#  weights
	#@param return_levels: if C{True}, the communities at each level are
	#  returned in a list. If C{False}, only the community structure with
	#  the best modularity is returned.
	#@return: a list of L{VertexClustering} objects, one corresponding to
	#  each level (if C{return_levels} is C{True}), or a L{VertexClustering}
	#  corresponding to the best modularity.
	#edges, weights = [], []
	hier = graph.community_multilevel(weights='weight' if graph.is_weighted() else None, return_levels=True)
	# Output levels
	#fname = 'level'

	communs = []  # All distinct communities of the hierarchy
	descrs = set()  # Communs descriptors for the fast comparison
	props = 0  # Number of propagated (duplicated communities)

	# Create output dir if not exists
	outdir = os.path.split(args.outpfile)[0]
	if outdir and not os.path.exists(outdir):
		os.makedirs(outdir)

	named = 'name' in graph.vertex_attributes()
	for i, lev in enumerate(hier):
		# Output statistics to the stderr
		print('Q: {:.6f}, lev: {}. {}.'.format(hier[i].q, i, hier[i].summary()), file=sys.stderr)
		if args.perlev:
			with open('{}_{}{}'.format(args.outpfile, i, args.outpext), 'w') as fout:
				for cl in lev:
					if named:
						fout.write(' '.join([graph.vs[nid]['name'] for nid in cl]))
					else:
						fout.write(' '.join([str(nid) for nid in cl]))
					fout.write('\n')
		else:
			# Merge all hier levels excluding identical communities, use idNums comparison (len, sum, sum2)
			for cl in lev:
				clen = len(cl)
				csum = 0
				csum2 = 0
				for nid in cl:
					csum += nid
					csum2 += nid * nid
				dsr = (clen, csum, csum2)
				if i == 0 or dsr not in descrs:
					descrs.add(dsr)
					communs.append(cl)
				else:
					props += 1
	# Output communs
	del descrs
	if not args.perlev:
		if props:
			print('The number of propagated (duplicated) communities in the hieratchy: '
				+ str(props), file=sys.stderr)
		with open(args.outpfile + args.outpext, 'w') as fout:
			for cl in communs:
				if named:
					fout.write(' '.join([graph.vs[nid]['name'] for nid in cl]))
				else:
					fout.write(' '.join([str(nid) for nid in cl]))
				fout.write('\n')
	print('The hierarchy has been successfully outputted')


def parseArgs(params=None):
	"""Parse input parameters (arguments)

	params  - the list of arguments to be parsed (argstr.split()), sys.argv is used if args is None

	return args  - parsed arguments
	"""
	inpfmts = ('nse', 'pjk', 'ncol')  # Note: louvain_igraph supports only undirected input graph
	parser = argparse.ArgumentParser(description='Louvain Clustering of the undirected graph.')

	ipars = parser.add_argument_group('Input Network (Graph)')
	ipars.add_argument('network', help='input network (graph) filename.'
		' The following formats are supported: {{{inpfmts}}}.'
		' If the file has another extension then the format should be specified'
		' explicitly.'.format(inpfmts=' '.join(inpfmts)))
	ipars.add_argument('-i', '--inpfmt', dest='inpfmt', choices=inpfmts, help='input network (graph) format')

	outpext = '.cnl'  # Default extension of the output file
	opars = parser.add_argument_group('Output Network (Graph)')
	opars.add_argument('-o', '--outpfile', dest='outpfile'
		, help='output all distinct resulting communities to the <outpfile>'
		', default value is <network_name>{}'.format(outpext))
	opars.add_argument('-l', '--perlev', dest='perlev', action='store_true'
		, help='output communities of each hierarchy level to the separate file'
		' <outpfile_name>/<outpfile_name>_<lev_num>{}'.format(outpext))

	args = parser.parse_args()

	# Consider implicit default values
	netname, netext = os.path.splitext(args.network)

	if args.inpfmt is None and netext:
		args.inpfmt = netext[1:]  # Skip the leading point
	args.inpfmt = args.inpfmt.lower()
	if args.inpfmt not in inpfmts:
		raise ValueError('Invalid format of the input network "{}" specified: {}'.format(args.network, args.inpfmt))

	if args.outpfile is None:
		args.outpfile = netname
		args.outpext = outpext
	else:
		args.outpfile, args.outpext = os.path.splitext(args.outpfile)

	return args


if __name__ == '__main__':
	louvain(parseArgs())
