#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: Produces rand disjoint communities (clusters) for the given network with sizes similar in the ground truth
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2015-07
"""
import sys
import os  # Pathes processing
import igraph as ig
import random as rand


# Default number of the resulting clusterings (partitions, i.e files that contain disjoint clusters)
resnum = 1

def parseParams(args):
	"""Parse user-specified parameters
	
	return
		groundtruth  - flile name of the ground truth clustering
		network  - flile name of the input network
		dirnet  - whether the input network is directed
		outnum  - number of the resulting clusterings
		outdir  - output directory
		outname  - base name of the output file based on the network name
		outext  - extenstion of the output files based on the groundtruth extension
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	groundtruth = None
	network = None
	dirnet = False
	outnum = 1
	randseed = None
	outdir = None
	outext = ''

	for arg in args:
		# Validate input format
		if arg[0] != '-':
			raise ValueError('Unexpected argument: ' + arg)
			
		preflen = 3
		if arg[1] == 'g':
			if len(arg) <= preflen or arg[:preflen] != '-g=':
				raise ValueError('Unexpected argument: ' + arg)
			groundtruth = arg[preflen:]
			outext = os.path.splitext(groundtruth)[1]
		elif arg[1] == 'i':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'ud=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			dirnet = arg[2] == 'd'
			network = arg[pos:]
			outname = os.path.split(os.path.splitext(network)[0])[1]
			if not outname:
				raise ValueError('Invalid network name (is a directory): ' + network)
		elif arg[1] == 'n':
			if len(arg) <= preflen or arg[:preflen] != '-n=':
				raise ValueError('Unexpected argument: ' + arg)
			outnum = int(arg[preflen:])
			assert outnum >= 1, "outnum must be a natural number" 
		elif arg[1] == 'r':
			if len(arg) <= preflen or arg[:preflen] != '-r=':
				raise ValueError('Unexpected argument: ' + arg)
			randseed = arg[preflen:]
		elif arg[1] == 'o':
			if len(arg) <= preflen or arg[:preflen] != '-o=':
				raise ValueError('Unexpected argument: ' + arg)
			outdir = arg[preflen:]
		else:
			raise ValueError('Unexpected argument: ' + arg)
		
	if not (groundtruth and network):
		raise ValueError('Input network and groundtruth file names must be specified')
	if not outdir:
		outdir = outname
	if not randseed:
		try:
			randseed = ''.join([str(ord(c)) for c in os.urandom(8)])
		except NotImplementedError:
			randseed = str(rand.random())
	
	return groundtruth, network, dirnet, outnum, randseed, outdir, outname, outext


def randcommuns(*args):
	"""Generate random clusterings for the specified network"""
	groundtruth, network, dirnet, outnum, randseed, outdir, outname, outext = parseParams(args)
	print('Starting randcommuns) clustering:'
		'\n\tgroundtruth: {}'
		'\n\t{} network: {}'
		'\n\t{} {} in {} with randseed: {}'
		.format(groundtruth, 'directed' if dirnet else 'undirected', network
			, outnum, outname + outext, outdir, randseed))
	# Load Data from simple real-world networks
	graph = ig.Graph.Read_Ncol(network, directed=dirnet)  # , weights=False
	
	# Load statistics from the ground thruth
	groundstat = []
	with open(groundtruth, 'r') as fground:
		for line in fground:
			groundstat.append(len(line.split()))

	# Create outpdir if required
	if outdir and not os.path.exists(outdir):
		os.makedirs(outdir)
	# Geneate rand clsuterings
	rand.seed(randseed)
	while outnum > 0:
		outnum -= 1
		actnodes = set(graph.vs.indices)  # Active (remained) nodes indices of the input network
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
				for nd in graph.vs[nodes[inds]].neighbors():
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
			clusters.append([graph.vs[ind]['name'] for ind in nodes])
		# Output resulting clusters
		with open(os.path.join(outdir, ''.join((outname, '_', str(outnum), outext))), 'w') as fout:
			for cl in clusters:
				fout.write(' '.join(cl))
				fout.write('\n')

	# Output randseed used for the generated clusterings
	with open(os.path.join(outdir, (outname + '.rseed')), 'w') as fout:
		fout.write(randseed)
	print('Random clusterings are successfully generated')


if __name__ == '__main__':
	if len(sys.argv) > 2:
		randcommuns(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {} -g=<ground_truth> -i[{{u, d}}]=<input_network> [-n=<res_num>] [-r=<rand_seed>] [-o=<outp_dir>]',
			'  -g=<ground_truth>  - ground truth clustering as a template for sizes of the resulting communities',
			'  -i[X]=<input_network>  - file of the input network in the format: <src_id> <dst_id> [<weight>]',
			'    Xu  - undirected input network (<src_id> <dst_id> implies also <dst_id> <src_id>). Default',
			'    Xd  - directed input network (both <src_id> <dst_id> and <dst_id> <src_id> are specified)',
			'  -n=<res_num>  - number of the resulting clusterings to generate. Default: {}',
			'  -r=<rand_seed>  - random seed, string. Default: value from the system rand source (otherwise current time)',
			'  -o=<output_communities>  - . Default: ./<input_network>/'
		)).format(sys.argv[0], resnum))