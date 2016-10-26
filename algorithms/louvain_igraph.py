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
import igraph as ig


inpfmt = 'ncol'  # NCOL input format
outpfile = "clusters.cnl"  # Default file for the communities output


def parseParams(args):
	"""Parse user-specified parameters

	return
		network  - input network
		dirnet  - whether the input network is directed (links are asymmetric,
			i.e. can have different in/outbound weights)
		perlev  - output communities per level instead of the solid hierarchy
		outpcoms  - base name of the output file
		outpext  - extension of the output file
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	network = None
	netfmt = inpfmt
	dirnet = False  # ~ Asymmetric links
	perlev = None
	outpcoms, outpext = os.path.splitext(outpfile)

	for arg in args:
		# Validate input format
		if arg[0] != '-':
			raise ValueError('Unexpected argument: ' + arg)

		if arg[1] == 'i':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'as=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			dirnet = arg[2] == 'a'
			network = arg[pos:]
			ext = os.path.splitext(network)[1]
			if ext and ext[1:] in ('pjk', 'pajek'):
				netfmt = 'pajek'
		elif arg[1] == 'f':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] != '=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			netfmt = arg[pos:]
			if netfmt not in ('ncol', 'pajek'):
				raise ValueError('Unknown network format: ' + netfmt)
		elif arg[1] == 'o':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'l=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			perlev = arg[2] == 'l'
			outpcoms, outpext = os.path.splitext(arg[pos:])
			# Create files in the folder if required
			if perlev:
				netname = os.path.split(outpcoms)[1]
				if not netname:
					raise ValueError('Unexpected argument: ' + arg)
				outpcoms = os.path.join(outpcoms, netname)
		else:
			raise ValueError('Unexpected argument: ' + arg)

	if not network:
		raise ValueError('Input network file name must be specified')

	return network, netfmt, dirnet, perlev, outpcoms, outpext


def louvain(*args):
	"""Execute Louvain algorithm on the specified network and output resulting communities to the specified file"""
	network, netfmt, dirnet, perlev, outpcoms, outpext = parseParams(args)

	print('Starting Louvain (igraph) clustering:'
		'\n\t{} network: {}'
		'\n\tnetwork format: {}'
		'\n\tperlev output: {}, communities: {}'
		.format('directed' if dirnet else 'undirected', network, netfmt
			, perlev, outpcoms + outpext))
	# Load Data from simple real-world networks
	graph = None
	if netfmt == 'ncol':  # Note: it's not clear whether .nce/.snap can be correctly readed as .ncol
		graph = ig.Graph.Read_Ncol(network, directed=dirnet)  # , weights=False
	elif netfmt == 'pajek':
		graph = ig.Graph.Read_Pajek(network)
	elif netfmt == 'nsl':
		raise NotImplementedError(".nsl/snap parsing has not been implemented yet")
		#edges, weights = [], []
		#for line in open("input_file.txt"):
		#	u, v, weight = line.split()
		#	edges.append((int(u), int(v)))
		#	weights.append(float(weight))
		#g = Graph(edges, edge_attrs={"weight": weights})
	else:
		raise ValueError('Unknown network format: ' + netfmt)

	hier = graph.community_multilevel(return_levels=True)
	# Output levels
	#fname = 'level'

	communs = []  # All distinct communities of the hierarchy
	descrs = set()  # Communs descriptors for the fast comparison
	props = 0  # Number of propagated (duplicated communities)


	# Create output dir if not exists
	outdir = os.path.split(outpcoms)[0]
	if outdir and not os.path.exists(outdir):
		os.makedirs(outdir)

	for i, lev in enumerate(hier):
		# Output statistics to the stderr
		print('Q: {:.6f}, lev: {}. {}.'.format(hier[i].q, i, hier[i].summary()), file=sys.stderr)
		if perlev:
			with open('{}_{}{}'.format(outpcoms, i, outpext), 'w') as fout:
				for cl in lev:
					fout.write(' '.join([graph.vs[nid]['name'] for nid in cl]))
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
	if not perlev:
		if props:
			print('Number of propagated (duplicated) communities in the hieratchy: '
				+ str(props), file=sys.stderr)
		with open(outpcoms + outpext, 'w') as fout:
			for cl in communs:
				fout.write(' '.join([graph.vs[nid]['name'] for nid in cl]))
				fout.write('\n')
	print('Hierarchy levels have been successfully outputted')


if __name__ == '__main__':
	if len(sys.argv) > 1:
		louvain(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {} -i[{{a, s}}]=<input_network> [-f={{ncol, pajek}}] [-o[l]=<output_communities>]',
			'  -i[X]=<input_network>  - file of the input network in the format: <src_id> <dst_id> [<weight>]',
			'    Xa  - asymmetric network links (in/outbound weights of the link migh differ), arcs',
			'    Xs  - symmetric network links, edges (but both directions can be specified in the input file). Default option.',
			'    Note:'
			'      - {{a, s}} are used only if the network file has no corresponding metadata (ncol format)',
			'      - Louvain igraph implementation does not support asymmetric clustering (directed network)',
			'  -f=<file_format>  - file format of the input network. Default: {}',
			'    ncol  - ncol format: <src_id> <dst_id> [<weight>]',
			'    pajek  - pajek format',
			'  -o[l]=<output_communities>  - output all distinct communities of the hierarchy to the <output_communities>. Default: {}',
			'    ol  - output all communities in each hier level to the seaparate file <output_communities>/<output_communities>_<lev_num>'
		)).format(sys.argv[0], inpfmt, outpfile))
