#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: Implementation of the Louvain algorithm using igraph framework with input/
	output formats adapted to the NMIs evaluation.
:Authors: Artem Lutov <luart@ya.ru>
:Organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>,
	Lumais <http://www.lumais.com/>
:Date: 2015-07
"""
from __future__ import print_function, division  # Required for stderr output, must be the first import
import sys
import os  # Pathes processing
import argparse
from igraph import Graph
from .utils.parser_nsl import asymnet, loadNsl


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
		# Weight are considered if present; .ncol format is always undirected
		graph = Graph.Read_Ncol(args.network, directed=False)
	elif args.inpfmt == 'pjk':
		graph = Graph.Read_Pajek(args.network)  #pylint: disable=E1101
	elif args.inpfmt in ('nse', 'nsa'):
		graph = loadNsl(args.network, asymnet(os.path.splitext(args.network)[1].lower(), args.inpfmt == 'nsa'))
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
	inpfmts = ('nse', 'nsa', 'pjk', 'ncol')  # Note: louvain_igraph supports only undirected input graph
	parser = argparse.ArgumentParser(description='Louvain Clustering of the undirected graph.')

	ipars = parser.add_argument_group('Input Network (Graph)')
	ipars.add_argument('network', help='input network (graph) filename.'
	 ' The following formats are supported: {{{inpfmts}}}.'
	 ' If the file has another extension then the format should be specified'
	 ' explicitly.'.format(inpfmts=' '.join(inpfmts)))
	ipars.add_argument('-i', '--inpfmt', dest='inpfmt', choices=inpfmts
	 , help='input network (graph) format, required only for the non-standard extension')

	outpext = '.cnl'  # Default extension of the output file
	opars = parser.add_argument_group('Output Network (Graph)')
	opars.add_argument('-o', '--outpfile', dest='outpfile'
	 , help='output all distinct resulting communities to the <outpfile>'
	 ', default value is <network_name>{}'.format(outpext))
	opars.add_argument('-l', '--perlev', dest='perlev', action='store_true'
	 , help='output communities of each hierarchy level to the separate file'
	 ' <outpfile_name>/<outpfile_name>_<lev_num>{}'.format(outpext))

	args = parser.parse_args(params)

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
