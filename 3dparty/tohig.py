#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: Datasets convertor from Pajek (and some other input formats) into HiReCS

Input formats:
	- Pajek: http://gephi.github.io/users/supported-graph-formats/pajek-net-format/
	- snap (undirected unweighted space sepaarated edges): https://snap.stanford.edu/data/index.html#communities
	- tsa (space/tab separated weighted arcs), used in LFR generated networks (graphs):
		https://sites.google.com/site/santofortunato/inthepress2
.hig format: http://www.lumais.com/docs/hig_format.hig

(c) HiReCS (High Resolution Hierarchical Clustering with Stable State library)
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2015-04
"""

import sys
import os

_inpfmts = ('snap', 'tsa')  # Possible formats of the input files:
# - snap  - space/tab separated unweighted edges with nodes header (#)
# - tsa  -  space/tab separated weighted arcs

def outName(finpName):
	"""Returns output filename by input filename"""
	return os.path.splitext(finpName)[0] + '.hig'

def formGraphHeader(fout, args):
	"""Parse command line arguments and write Graph header section"""
	weighted = True
	resdub = False  # Resolve duplications
	custfmt = False
	if args:
		assert isinstance(args, (tuple, list))
		# Parce args
		for arg in args:
			if arg[0] != '-':
				raise ValueError('Unexpected argument: ' + arg)
			
			if arg[1] == 'f':
				preflen = 3
				if len(arg) <= preflen or arg[preflen - 1] != '=' or arg[preflen:] not in _inpfmts:
					raise ValueError('Unexpected argument: ' + arg)
				custfmt = arg[preflen:].lower()
			elif arg[1] == 'u':
				weighted = False
			elif arg[1] == 'r':
				resdub = True
			else:
				raise ValueError('Unexpected argument: ' + arg)

		fout.write("/Graph weighted:{0}\n\n".format(int(weighted)))
	return weighted, resdub, custfmt

def saveNodes(fout, vertNum, startId=1):
	"""Write nodes header section (nodes number) to the .hgc file
		/Nodes [<nodes_number>  [<start_id>]]
		start_id is always 1 for pajek format
	"""
	if startId is not None:
		fout.write('/Nodes {} {}\n\n'.format(vertNum, startId))
	else:
		fout.write('/Nodes {}\n\n'.format(vertNum))		

def parseLink(link, weighted):
	"""Parse single link in Pajek format
	return (dest_id, weight)
	"""
	link = link.split()
	if not link or len(link) > 2:
		raise ValueError(' '.join(('Invalid format of the link specification:', link)))
	weight = '1'
	if weighted and len(link) > 1:
		weight = link[1]
	return (link[0], weight)

def parseLinks(links, weighted):
	"""Parse node links in Pajek format
	return [(dest_id, weight), ...]
	"""
	links = links.split()
	if weighted:
		links = [(v, 1) for v in links]
	return links

def saveLinks(fout, links, weighted):
	"""Save links to the current section"""
	for ndlinks in links.items():
		val = ndlinks[1]
		# Consider that duplicates might were resolved
		if isinstance(val, dict):
			val = val.items()

		if weighted:
			text = ' '.join([':'.join(v) for v in val])
		else:
			# Skip weights
			text = ' '.join([v[0] for v in val])
		fout.write('{0}> {1}\n'.format(ndlinks[0], text))

def tohig(finpName, *args):
	"""Convert Pajek file into the HiReCS input file format line by line,
	processing edges and arcs Pajek section as a single line in the .hgc
	"""
	#vertNum, edges, arcs = loadPajek()
	#saveHgc(foutName(finpName), vertNum, edges, arcs)
	with open(finpName, 'r') as finp:
		print('File {0} is opened, converting...'.format(finpName))
		# Create output file
		foutName = outName(finpName)
		with open(foutName, 'w') as fout:
			print('File {0} is created, filling...'.format(foutName))
			fout.write('# Converted from {0}\n'.format(finpName))
			weighted, resdub, custfmt = formGraphHeader(fout, args)
			# Sections Enumeration
			SECT_NONE = 0
			SECT_VRTS = 1
			SECT_EDGS = 2  # Single edge  per line
			SECT_ARCS = 3
			SECT_EDGL = 4  # Edges list
			SECT_ARCL = 5  # Arcs list

			def sectionName(sect):
				sections = ('<NONE>', 'vertices', 'edges', 'arcs', 'edgeslist', 'arcslist')
				return sections[sect] if sect < len(sections) else '<UNDEFINED>'

			sect = SECT_NONE
			vertNum = None  # Number of verteces
			links = {}  # {src: [(dst, weight), ...]}
			arcs = {}  # Selflinks in case of Edges processing

			# Outpurt sections
			OSECT_NONE = 0
			OSECT_NODES = 1
			OSECT_EDGS = 1
			OSECT_ARCS = 1
			outsect = OSECT_NONE
			cmtmark = '%' if not custfmt else '#'
			nodeshdr = False  # Nodes header is formed

			for ln in finp:
				# Skip comments
				ln = ln.lstrip()
				if not ln or ln.startswith(cmtmark):
					# Check for number of nodes for the custom format
					nodesmark = 'Nodes:';
					if not nodeshdr and custfmt and ln.find(nodesmark, 1) != -1:
						ln = ln[ln.find(nodesmark, 1) + len(nodesmark):].lstrip().split(None, 1)[0]
						try:
							vertNum = int(ln)
						except (ValueError, IndexError):
							raise SyntaxError('Number of vertices must be specified')
						saveNodes(fout, vertNum, None)
						nodeshdr = True
						fout.write('/Edges\n')
						sect = SECT_EDGS
					continue
				# Process content
				if ln[0] != '*':
					if custfmt and not nodeshdr:
						fout.write('/Edges\n' if custfmt == _inpfmts[0] else '/Arcs\n')
						sect = SECT_EDGS
						# Output nodes header
						nodeshdr = True
					# Process section body
					if sect == SECT_NONE:
						raise SyntaxError('Invalid file format: section header is expected')
					elif sect == SECT_VRTS:
						continue  # Skip vertices annotations
					else:
						# Body of the links section
						ln = ln.split(None, 1)
						if len(ln) < 2:
							raise SyntaxError(''.join(('At least 2 ids are expected in the "'
								, sectionName(sect), '" section items: ', ln)))
						node = int(ln[0])
						if sect == SECT_EDGS or sect == SECT_ARCS:
							#print('links: ', links)
							ndlinks = links.get(node, [] if not resdub else {})
							link = parseLink(ln[1], weighted)
							if sect == SECT_ARCS or link[0] != ln[0]:
								if not resdub:
									ndlinks.append(parseLink(ln[1], weighted))
								else:
									ndlinks[link[0]] = link[1]
							else:
								arcs[node] = (link,)  # Make a tuple
							if ndlinks:
								links[node] = ndlinks
						elif sect == SECT_EDGL or sect == SECT_ARCL:
							saveLinks(fout, {node: parseLinks(ln[1], weighted)}, weighted)
						else:
							raise RuntimeError(''.join(('Logical error: unexpected "'
								, sectsectionName(sect), '" section')))
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
									, sectsectionName(sect), '" section')))
							links = {}
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
							fout.write('\n/Edges\n')
							sect = SECT_EDGS
						elif sectName == 'arcs':
							fout.write('\n/Arcs\n')
							sect = SECT_ARCS
						elif sectName == 'edgeslist':
							fout.write('\n/Edges\n')
							sect = SECT_EDGL
						elif sectName == 'arcslist':
							fout.write('\n/Arcs\n')
							sect = SECT_ARCL
						else:
							raise ValueError('Unexpected section: ' + sectName)
			# Save remained parced data if required
			if links:
				if sect == SECT_EDGS or sect == SECT_ARCS:
					saveLinks(fout, links, weighted)
				else:
					raise RuntimeError(''.join(('Logical error: unsaved data in "'
						, sectsectionName(sect), '" section')))
				links = {}
			if arcs:
				fout.write('\n/Arcs\n')
				saveLinks(fout, arcs, weighted)
			print('{} -> {} conversion is completed'.format(finpName, foutName))


if __name__ == '__main__':
	if len(sys.argv) > 1:
		tohig(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} <network> [-ru] [-f={{{1}, {2}}}]',
			'  -r  - resolve duplicated links from the .pjk',
			'  -u  - force links to be unweighted even for the weighted input graph',
			'  -f=<format>  - custom non-pajek input format (default: pajek):',
			'    {1}  - SNAP format: space/tab separated unweighted edges with Nodes header (#)',
			'    {2}  - space/tab separated weighted arcs, used in LFR generated graphs',
			))
			.format(sys.argv[0], *_inpfmts))
