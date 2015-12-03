#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: Datasets convertor from Pajek (and some other input formats) into HiReCS

Input formats:
	- pajek: http://gephi.github.io/users/supported-graph-formats/pajek-net-format/
	- nse  - newline / space/tab separated possibly weighted edges (undirected links)), lines of:  <src_id> <dst_id>
		without backward directoin specification, including SNAP format: https://snap.stanford.edu/data/index.html#communities
	- nsa  - newline / space/tab separated possibly weighted arcs, used in LFR generated networks (graphs), line of:  <src_id> <dst_id> <weight>
		with backward directoin specification: https://sites.google.com/site/santofortunato/inthepress2
.hig format: http://www.lumais.com/docs/hig_format.hig

(c) HiReCS (High Resolution Hierarchical Clustering with Stable State library)
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2015-04
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import sys
import os
import time  # Required when the file should be renamed


_inpfmts = ('nse', 'nsa')  # Possible formats of the input files:
# - nse  - newline / space/tab separated possibly edges with nodes header (#; network links are symmetric)
# - nsa  -  newline / space/tab separated possibly weighted arcs (network links can be asymmetric)


def outName(finpName):
	"""Returns output filename by input filename"""
	return os.path.splitext(finpName)[0] + '.hig'


def parseArgs(args):
	weighted = True  # Force the graph to be unweighted or treat it as weighted
	resdub = False  # Resolve duplications
	custfmt = False  # Custom graph format
	overwrite = 'f'  # Force overwrite, Rename, Skip
	if args:
		assert isinstance(args, (tuple, list))
		# Parce args
		for arg in args:
			# Allow empty args
			if not arg:
				continue
			if arg[0] != '-':
				raise ValueError('Unexpected argument: ' + arg)
			
			if arg[1] == 'f':
				preflen = 3
				if len(arg) <= preflen or arg[preflen - 1] != '=' or arg[preflen:] not in _inpfmts:
					raise ValueError('Unexpected argument: ' + arg)
				custfmt = arg[preflen:]
			elif arg[1] == 'u':
				weighted = False
			elif arg[1] == 'r':
				resdub = True
			elif arg[1] == 'o':
				preflen = 2
				if len(arg) <= preflen or arg[preflen] not in 'frs':
					raise ValueError('Unexpected argument: ' + arg)
				overwrite = arg[preflen]
			else:
				raise ValueError('Unexpected argument: ' + arg)
	
	return weighted, resdub, custfmt, overwrite


def saveNodes(fout, vertNum, startId=1):
	"""Write nodes header section (nodes number) to the .hgc file
		/Nodes [<nodes_number>  [<start_id>]]
		start_id is always 1 for pajek format
	"""
	if startId is not None:
		fout.write('/Nodes {} {}\n'.format(vertNum, startId))
	else:
		fout.write('/Nodes {}\n'.format(vertNum))		


def parseLink(link, weighted):
	"""Parse single link in Pajek format
	link  - string in the format: <src_id> <dst_id> [<weight>]
	weighted  - wether to consider weight
	
	return (dest_id, weight)
	"""
	link = link.split()
	if not link or len(link) > 2:
		raise ValueError(' '.join(('Invalid format of the link specification:', link)))
	weight = None
	if weighted and len(link) > 1:
		weight = link[1]
	return (link[0], weight)


def parseLinksList(links, weighted, resdub):
	"""Parse node links in Pajek format
	links  - links string: <did1> <did2> ...
	weighted  - generate weighted / unweighted links
	resdub  - resolve dublicates
	return [(dest_id, weight), ...]
	"""
	links = links.split()
	if weighted:
		if resdub:
			links = {v: '1' for v in links}
		else:
			links = [(v, '1') for v in links]
	elif resdub:
		links = list(set(links))
	
	return links


def saveLinks(fout, links, weighted):
	"""Save links to the current section"""
	for ndlinks in links.items():
		val = ndlinks[1]
		assert val, "Nodes can't be specified without links"
		# Consider that links are dict if duplicates were resolved
		if isinstance(val, dict):
			val = val.items()

		if weighted and val[0][1] is not None:
			text = ' '.join([':'.join(v) for v in val])
		else:
			# Skip weights
			text = ' '.join([v[0] for v in val])
		fout.write('{0}> {1}\n'.format(ndlinks[0], text))


def tohig(finpName, *args):
	"""Convert Pajek file into the HiReCS input file format line by line,
	processing edges and arcs Pajek section as a single line in the .hgc
	"""
	with open(finpName, 'r') as finp:
		weighted, resdub, custfmt, overwrite = parseArgs(args)
		print('File {} is opened, converting...\n\tweighted: {}\n\tresdub: {}\n\tcustfmt: {}\n\toverwrite: {}'
			  .format(finpName, weighted, resdub, custfmt, overwrite))
		foutName = outName(finpName)
		# Check whether output file exists
		exists = os.path.exists(foutName)
		if exists:
			act = None
			if overwrite == 'f':
				act = 'overwriting...'
			elif overwrite == 'r':
				mtime = time.strftime('_%y%m%d_%M%S', time.gmtime(os.path.getmtime(foutName)))
				renamed = foutName + mtime
				os.rename(foutName, renamed)
				act = 'renaming the old one into {}...'.format(renamed)
			elif overwrite == 's':
				act = 'the conversion is skipped'
			else:
				raise ValueError('Unchown action to be done with the existent file: ' + overwrite)
			print('WARNING: the output file "{}" already exists, {}'.format(foutName, act), file=sys.stderr)
			if overwrite == 's':
				return
		try:
			# Create output file
			with open(foutName, 'w') as fout:
				print('File {0} is created, filling...'.format(foutName))
				fout.write('# Converted from {0}\n'.format(finpName))
				fout.write("/Graph weighted:{} validated:{}\n".format(int(weighted), int(resdub)))

				# Sections Enumeration
				SECT_NONE = 0
				SECT_VRTS = 1
				SECT_EDGS = 2  # Single edge  per line
				SECT_ARCS = 3
				SECT_EDGL = 4  # Edges list
				SECT_ARCL = 5  # Arcs list
				
				sectName = {
					SECT_NONE: 'SECT_NONE',
					SECT_VRTS: 'SECT_VRTS',
					SECT_EDGS: 'SECT_EDGS',
					SECT_ARCS: 'SECT_ARCS',
					SECT_EDGL: 'SECT_EDGL',
					SECT_ARCL: 'SECT_ARCL'
				}
	
				def sectionName(sect):
					sections = ('<NONE>', 'vertices', 'edges', 'arcs', 'edgeslist', 'arcslist')
					return sections[sect] if sect < len(sections) else '<UNDEFINED>'
	
				sect = SECT_NONE
				vertNum = None  # Number of verteces
				links = {}  # {src: [(dst, weight), ...]}
				arcs = {}  # Selflinks in case of Edges processing
	
				# Outpurt sections
				cmtmark = '%' if not custfmt else '#'
				nodeshdr = False  # Nodes header is formed
	
				for ln in finp:
					# Skip comments
					ln = ln.lstrip()
					if not ln or ln.startswith(cmtmark):
						# Check for number of nodes for the custom format
						# and add it to the forming file if exists
						nodesmark = 'Nodes:';
						if not nodeshdr and custfmt and ln.find(nodesmark, 1) != -1:
							ln = ln[ln.find(nodesmark, 1) + len(nodesmark):].lstrip().split(None, 1)[0]
							try:
								vertNum = int(ln)
							except (ValueError, IndexError):
								raise SyntaxError('Number of vertices must be specified')
							saveNodes(fout, vertNum, None)
						continue
					# Process content
					if ln[0] != '*':
						# Process section body
						if not custfmt:
							if sect == SECT_NONE:
								raise SyntaxError('Invalid file format: section header is expected')
							elif sect == SECT_VRTS:
								continue  # Skip vertices annotations
						# Write the section header if required
						if not nodeshdr:
							if not custfmt:
								if sect == SECT_EDGS or sect == SECT_EDGL:
									fout.write('\n/Edges\n')
								elif sect == SECT_ARCS or sect == SECT_ARCL:
									fout.write('\n/Arcs\n')
								else:
									raise ValueError('Unexpected section: ' + sectName[sect])
							else:
								if custfmt == _inpfmts[0]:
									sect = SECT_EDGS
									fout.write('\n/Edges\n')
								else:
									sect = SECT_ARCS
									fout.write('\n/Arcs\n')
							nodeshdr = True
	
						# Body of the links section
						ln = ln.split(None, 1)
						if len(ln) < 2:
							raise SyntaxError(''.join(('At least 2 ids are expected in the "'
								, sectionName(sect), '" section items: ', ln)))
						node = int(ln[0])
						if sect == SECT_EDGS or sect == SECT_ARCS:
							#print('links: ', links)
							link = parseLink(ln[1], weighted)
							# Process self links separately
							if sect == SECT_ARCS or link[0] != ln[0]:
								# Fetch or construct node links
								ndlinks = links.get(node, [] if not resdub else {})
								if not resdub:
									if not ndlinks:
										links[node] = ndlinks
									ndlinks.append(link)
								else:
									# Check existance of the back link for Edges
									dest = None if sect != SECT_EDGS else links.get(int(link[0]))
									if not dest or not dest.get(node):
										if not ndlinks:
											links[node] = ndlinks
										ndlinks[link[0]] = link[1]
							else:
								# Always specify self weight via Arcs
								arcs[node] = tuple(link)  # Make a tuple
						elif sect == SECT_EDGL or sect == SECT_ARCL:
							saveLinks(fout, {node: parseLinksList(ln[1], weighted, resdub)}, weighted)
						else:
							raise RuntimeError(''.join(('Logical error: unexpected "'
								, sectName[sect], '" section')))
					else:
						# Process section header
						ln = ln[1:].strip().split(None, 2)
						if not ln:
							raise ValueError('Invalid section name (empty)')
						sectName = ln[0].lower()
						if sect == SECT_NONE and sectName != 'vertices':
							raise ValueError(''.join(('Invalid section: "', sectName
								, '", "vertices" is expected')))
						elif sect != SECT_NONE and sectName == 'vertices':
							raise ValueError('Invalid section, "vertices" is not expected')
						else:
							# Save parced data if required
							if links:
								if sect == SECT_EDGS or sect == SECT_ARCS:
									saveLinks(fout, links, weighted)
								else:
									raise RuntimeError(''.join(('Logical error: unsaved data in "'
										, sectName[sect], '" section')))
								links.clear()
							# Set working section
							if sectName == 'vertices':
								sect = SECT_VRTS
								#if len(ln) > 1:
								try:
									vertNum = int(ln[1])
								except (ValueError, IndexError):
									raise SyntaxError('Number of vertices must be specified')
								saveNodes(fout, vertNum, None)
							elif sectName == 'edges':
								sect = SECT_EDGS
							elif sectName == 'arcs':
								sect = SECT_ARCS
							elif sectName == 'edgeslist':
								sect = SECT_EDGL
							elif sectName == 'arcslist':
								sect = SECT_ARCL
							else:
								raise ValueError('Unexpected section: ' + sectName)
							nodeshdr = False
				# Save remained parced data if required
				if links:
					if sect == SECT_EDGS or sect == SECT_ARCS:
						saveLinks(fout, links, weighted)
					else:
						raise RuntimeError(''.join(('Logical error: unsaved data in "'
							, sectName[sect], '" section')))
					links.clear()
				if arcs:
					fout.write('\n/Arcs\n')
					saveLinks(fout, arcs, weighted)
				print('{} -> {} conversion is completed'.format(finpName, foutName))
		except StandardError:
			# Remove incomplete output file
			if os.path.exists(foutName):
				os.remove(foutName)
			raise


if __name__ == '__main__':
	if len(sys.argv) > 1:
		tohig(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} <network> [-ru] [-f={{{1}, {2}}}] [-o{{f,r,s}}]',
			'  -r  - resolve (remove) duplicated links to be unique',
			'  -u  - force links to be unweighted even for the weighted input graph.'
			' Generates weighted links by default (only for the weighted graphs)',
			'  -f=<format>  - custom non-pajek input format (default: pajek):',
			'    {1}  - newline / space/tab separated possible weighted edges with optional Nodes header and comments (#).'
			' It includes SNAP format',
			'    {2}  - newline / space/tab separated possible weighted arcs with optional Nodes header and comments (#).'
			' It is used in LFR generated graphs (but they are symmetric)',
			'  -o[X]  - strategy of the output file creation when it already exists. Always warn the user. Default: overwrite',
			'    Xf  - forced overwriting of the output file',
			'    Xr  - rename the already existent output file and create the new one',
			'    Xs  - skip processing if such output file already exists',
			''
			'  Note: node weigh (selflink) is always specified by Arcs in the produced .hig'
			))
			.format(sys.argv[0], *_inpfmts))
