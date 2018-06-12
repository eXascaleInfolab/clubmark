#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Brief: Produces rand disjoint communities (clusters) for the given network with sizes similar in the ground truth.
:Description:
	Takes number of the resulting communities and their sizes from the specified groundtruth (actually any sample
	of the community structure, the real ground truth is not required) and fills stubs of the clusters with
	randomly selected nodes from the input network with all their neighbors.
	Note: Produced result is a random disjoint partitioning, so if the 'ground truth' had overlapping clusters, then
	the number of nodes in the last cluster will be less than in the sample.

:Authors: Artem Lutov <luart@ya.ru>
:Organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>,
	Lumais <http://www.lumais.com/>
:Date: 2015-07
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import sys
import os  # Pathes processing
#import igraph as ig
import random as rand
try:
	# ATTENTION: Python3 newer treats imports as realtive and results in error here unlike Python2
	from utils.parser_nsl import asymnet, loadNsl  #pylint: disable=E0611,E0401
except ImportError:
	# Note: this case should be the second because explicit relative imports cause various errors
	# under Python2 and Python3, which complicates thier handling
	from .utils.parser_nsl import asymnet, loadNsl  #pylint: disable=E0611,E0401

# Default number of the resulting clusterings (partitions, i.e files that contain disjoint clusters)
_RESNUM = 1


class Params(object):
	"""Input parameters (arguments)"""
	def __init__(self):
		"""Parameters:
		groundtruth  - flile name of the ground truth clustering
		network  - flile name of the input network
		dirnet  - whether the input network is directed
		outnum  - number of the resulting clusterings
		randseed  - seed for the clustering generation (automatically generated if not specified)
		outpseed  - whether to output the seed (automatically set to True on if the seed is generated automatically)
		outdir  - output directory
		outname  - base name of the output file based on the network name
		outext  - extenstion of the output files based on the groundtruth extension
		"""
		self.groundtruth = None
		self.network = None
		self.dirnet = False
		self.outnum = _RESNUM
		self.randseed = None
		self.outpseed = False
		self.outdir = None
		self.outname = None
		self.outext = ''


def parseParams(args):
	"""Parse user-specified parameters

	returns  - parsed input arguments, Params()
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	prm = Params()

	for arg in args:
		# Validate input format
		preflen = 3
		if arg[0] != '-' or len(arg) <= preflen:
			raise ValueError('Unexpected argument: ' + arg)

		if arg[1] == 'g':
			prm.groundtruth = arg[preflen:]
			prm.outext = os.path.splitext(prm.groundtruth)[1]
		elif arg[1] == 'i':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'ud=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			prm.network = arg[pos:]
			prm.outname, netext = os.path.splitext(os.path.split(prm.network)[1])
			prm.dirnet = asymnet(netext.lower(), arg[2] == 'd')
			if not prm.outname:
				raise ValueError('Invalid network name (is a directory): ' + prm.network)
		elif arg[1] == 'n':
			prm.outnum = int(arg[preflen:])
			assert prm.outnum >= 1, 'outnum must be a natural number'
		elif arg[1] == 'r':
			prm.randseed = arg[preflen:]
		elif arg[1] == 'o':
			prm.outdir = arg[preflen:]
		else:
			raise ValueError('Unexpected argument: ' + arg)

	if not (prm.groundtruth and prm.network):
		raise ValueError('Input network and groundtruth file names must be specified')
	if not prm.outdir:
		prm.outdir = os.path.split(prm.network)[0]
		if not prm.outdir:
			prm.outdir = '.'
	if not prm.randseed:
		try:
			prm.randseed = ''.join([str(ord(c)) for c in os.urandom(8)])
		except NotImplementedError:
			prm.randseed = str(rand.random())
		prm.outpseed = True

	return prm


def randcommuns(*args):
	"""Generate random clusterings for the specified network"""
	prm = parseParams(args)
	print('Starting randcommuns clustering:'
	 '\n\tgroundtruth: {}'
	 '\n\t{} network: {}'
	 '\n\t{} cls of {} in {} with randseed: {}'
	 .format(prm.groundtruth, 'directed' if prm.dirnet else 'undirected', prm.network
	  , prm.outnum, prm.outname + prm.outext, prm.outdir, prm.randseed))
	# Load Data from simple real-world networks
	graph = loadNsl(prm.network, prm.dirnet)  # ig.Graph.Read_Ncol(network, directed=dirnet)  # , weights=False

	# Load statistics from the ground thruth
	groundstat = []
	with open(prm.groundtruth, 'r') as fground:
		for line in fground:
			groundstat.append(len(line.split()))

	# Create outpdir if required
	if prm.outdir and not os.path.exists(prm.outdir):
		os.makedirs(prm.outdir)
	# Geneate rand clsuterings
	rand.seed(prm.randseed)
	while prm.outnum > 0:
		prm.outnum -= 1
		# Active (remained) nodes indices of the input network
		actnodes = set(graph.vs.indices)  #pylint: disable=E1101
		clusters = []  # Forming clusters
		# Reference size of the ground truth clusters (they migh have overlaps unlike the current partitioning)
		for clmarg in groundstat:
			nodes = []  # Content of the current cluster
			# Check whether all nodes of the initial network are mapped
			if not actnodes:
				break
			# Select subsequent rand node
			ind = rand.sample(actnodes, 1)[0]
			actnodes.remove(ind)
			nodes.append(ind)
			inds = 0  # Index of the node in the current cluster
			# Select neighbors of the selected nodes to fill the clusters
			while len(nodes) < clmarg and actnodes:
				for nd in graph.vs[nodes[inds]].neighbors():  #pylint: disable=E1136
					if nd.index not in actnodes:
						continue
					actnodes.remove(nd.index)
					nodes.append(nd.index)
					if len(nodes) >= clmarg or not actnodes:
						break
				inds += 1
				if inds >= len(nodes) and len(nodes) < clmarg and actnodes:
					ind = rand.sample(actnodes, 1)[0]
					actnodes.remove(ind)
					nodes.append(ind)

			# Use original labels of the nodes
			clusters.append([graph.vs[ind]['name'] for ind in nodes])  #pylint: disable=E1136
		# Output resulting clusters
		with open('/'.join((prm.outdir, ''.join((prm.outname, '_', str(prm.outnum), prm.outext)))), 'w') as fout:
			for cl in clusters:
				fout.write(' '.join(cl))
				fout.write('\n')

	# Output randseed used for the generated clusterings
	# Output to the dir above if possible to not mix cluster levels with rand seed
	if prm.outpseed:
		with open('/'.join((prm.outdir, (os.path.splitext(prm.outname)[0] + '.seed'))), 'w') as fout:
			fout.write(prm.randseed)
	print('Random clusterings are successfully generated')


if __name__ == '__main__':
	if len(sys.argv) > 2:
		randcommuns(*sys.argv[1:])
	else:
		print('\n'.join(('Produces random disjoint partitioning (clusters are formed with rand nodes and their neighbors)'
			' for the input network specified in the NSL format (generalizaiton of NCOL, SNAP, etc.)\n',
			'Usage: {app} -g=<ground_truth> -i[{{u, d}}]=<input_network> [-n=<res_num>] [-r=<rand_seed>] [-o=<outp_dir>]',
			'',
			'  -g=<ground_truth>  - ground truth clustering as a template for sizes of the resulting communities',
			'  -i[X]=<input_network>  - file of the input network in the format: <src_id> <dst_id> [<weight>]',
			'    Xu  - undirected input network (<src_id> <dst_id> implies also <dst_id> <src_id>). Default',
			'    Xd  - directed input network (both <src_id> <dst_id> and <dst_id> <src_id> are specified)',
			'    NOTE: (un)directed flag is considered only for the networks with non-NSL file extension',
			'  -n=<res_num>  - number of the resulting clusterings to generate. Default: {resnum}',
			'  -r=<rand_seed>  - random seed, string. Default: value from the system rand source (otherwise current time)',
			'  -o=<output_communities>  - . Default: ./<input_network>/'
		)).format(app=sys.argv[0], resnum=_RESNUM))
