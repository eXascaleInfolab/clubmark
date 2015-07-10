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
import igraph as ig


def parseParams(args):
	"""Parse user-specified parameters
	
	return
		network  - input network
		perlev  - output communities per level instead of the solid hierarchy
		outpcoms  - output file/dir
	"""


def louvain(*args):
	"""Execute Louvain algorithm on the specified network and output resulting communities to the specified file"""
	network, perlev, outpcoms = parseParams(args)
	
	print('Starting Louvain (igraph) clustering: \n\tnetwork: {}\n\tperlev output: {}\n\tcommunities: ')
	## Load Data from simple real-world networks
	graph = ig.Graph.Read_Ncol(network, directed=False)  # , weights=False
	hier = graph.community_multilevel(return_levels=True)
	# Output levels
	#fname = 'level'
	communs = []
	descrs = set()
	i = 0
	for lev in hier:
		# Output statistics to the stderr
		print('Q: {:.6f}. {}.'.format(hier[lev].q, hier[lev].summary()), file=sys.stderr)
		if perlev:
			with open('level{}.cnl'.format(i), 'w') as fout:
				for cl in lev:
					fout.write(' '.join([str(nid) for nid in cl]))
					fout.write('\n')
				i += 1
		else:
			# Merge all hier levels excluding identical communities, use idNums comparison (len, sum, sum2)
			for cl in lev:
				clen = len(cl)
				csum = 0
				csum2 = 0
				for nid in cl:
					csum += nid
					csum2 += nid * nid
				descr = (clen, csum, csum2)
				if descr not in descrs:
					descrs.add(descrs)
					communs.append(cl)
	# Output communs
	del descrs
	if not perlev:
		with open(outpcoms, 'w') as fout:
			for cl in communs:
				fout.write(' '.join([str(nid) for nid in cl]))
				fout.write('\n')
	print('Hierarchy levels have been successfully outputted')


if __name__ == '__main__':
	if len(sys.argv) > 1:
		louvain(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} -i{u,d}=<input_network> -o[l]=<output_communities>',
			'  -iX=<input_network>  - file of the input network in the format: <src_id> <dst_id> [<weight>]',
			'    Xu  - undirected input network (<src_id> <dst_id> implies also <dst_id> <src_id>)',
			'    Xd  - directed input network (both <src_id> <dst_id> and <dst_id> <src_id> are specified)',
			'  -o[l]=<output_communities>  - output all distinct communities of the hierarchy to the <output_communities>',
			'    ol  - output all communities in each hier level to the seaparate file <output_communities>_<lev_num>'
		)).format(sys.argv[0]))