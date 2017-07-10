#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
\descr: Datasets converter from Pajek, Metis and .nsl formats (including .ncol,
Stanford SNAP and Edge/Arcs Graph) to .nsl (.nse/a that are more common than .ncol,
i.e. the output can be stanford .snap and .ncol) and .rcg (Readable Compact Graph,
former .hig; used by DAOC / HiReCS libs) formats.

Input formats:
	- pajek network format: http://gephi.github.io/users/supported-graph-formats/pajek-net-format/
	- metis graph (network) format: http://people.sc.fsu.edu/~jburkardt/data/metis_graph/metis_graph.html
		http://glaros.dtc.umn.edu/gkhome/fetch/sw/metis/manual.pdf
	- nse  - nodes are specified in lines consisting of the single Space/tab
		separated, possibly weighted Edge (undirected link, i.e. either AB or BA is
		specified):  <src_id> <dst_id> [<weight>]
		with '#' comments and selflinks, without backward direction specification. Nodes have unsigned id,
		the starting id is not fix. Ids might form non-soild range, e.g. {2,4,5,8}.
		The specializations are:
		Link List format (http://www.mapequation.org/code.html#Link-list-format)
		also known as Stanford SNAP format: https://snap.stanford.edu/data/index.html#communities
		and [Weighted] Edge Graph (https://www.cs.cmu.edu/~pbbs/benchmarks/graphIO.html)
		where node ids start from 1 and form a single solid range. Edge Graph format does not include comments.
	- nsa  - nodes are specified in lines consisting of the single Space/tab
		separated, possibly weighted Arc (directed link): <src_id> <dst_id> <weight>
		with '#' comments, selflinks and backward direction specification that is
		a [Weighted] Arcs Graph, a generalization of the LFR Benchmark generated networks:
		https://sites.google.com/site/santofortunato/inthepress2

Output formats:
	- rcg format: http://www.lumais.com/docs/format.rcg  (hig_format.hig)
	- nsl (stands for nse/nsa)
	
Note: works on both Python3 and Python2 / pypy

(c) RCG (Readable Compact Graph)
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2016-10
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
# Required to efficiently traverse items of dictionaries in both Python 2 and 3
try:
	from future.utils import viewitems, viewkeys, viewvalues  # External package: pip install future
	from future.builtins import range
except ImportError:
	def viewMethod(obj, method):
		"""Fetch view method of the object

		obj  - the object to be processed
		method  - name of the target method, str

		return  target method or AttributeError

		>>> callable(viewMethod(dict(), 'items'))
		True
		"""
		viewmeth = 'view' + method
		ometh = getattr(obj, viewmeth, None)
		if not ometh:
			ometh = getattr(obj, method)
		return ometh

	viewitems = lambda dct: viewMethod(dct, 'items')()
	viewkeys = lambda dct: viewMethod(dct, 'keys')()
	viewvalues = lambda dct: viewMethod(dct, 'values')()
	
	# Replace range() implementation for Python2
	try:
		range = xrange
	except NameError:
		pass  # xrange is not defined in Python3, which is fine
import sys
import os
import argparse
import time  # Required when the file should be renamed


# Approximate block size in links (at list this number of links if not interrupted by the section completion)
DEFAULT_BLOCK_LINKS = 2048  # Page size is 4K, 1024 anyway will take more than 4K


# Input Files Parsing ----------------------------------------------------------
def outName(finpName, outfmt):
	"""Returns output filename by input filename

	finpName  - input file name
	outfmt  - output file format
	"""
	assert isinstance(outfmt, FormatSpec) and outfmt.native()
	return '.'.join((os.path.splitext(finpName)[0], outfmt.id))


def parseSingleLink(line):
	"""Parse a single link havein th format: src dst [weight]

	line  - non-empty line of the input text that starts from a non-space symbol

	return  [src_str, dst_str, weight_str | None],
	"""
	line = line.split(None, 3)  # Ending comments are not allowed, but required unweighed link might contain input weight
	assert len(line) >= 2 and  line[0][0].isdigit() and line[1][0].isdigit(), (
		'src and dst must exist and be digits')
	if len(line) == 2:
		line.append(None)
	else:
		assert line[2][0].isdigit() or line[2][0] == '.', 'Weight should be a float number'

	return line


def parseBlockNsl(directed):
	"""Parse NSE or NSA input block
	directed  - arcs (nsa), otherwise edges (nse)
	"""
	assert isinstance(directed, bool)
	def parser(inpfmt, finp, unweight, blsnum=DEFAULT_BLOCK_LINKS):
		"""NSL(E/A) format parser

		inpfmt  - input format
		finp  - input stream
		unweight  - omit weights
		blsnum  - approximate block size in links (at list this number of links
			if not interrupted by the section completion)

		return parsing  - whether the parsng is not completed yet
		"""
		# NSL[A,E] format:
		# # Comments are marked with '#' symbol
		# # Optional Header:
		# # [Nodes: <nodes_num>	<Links>: <links_num> [Weighted: {0, 1}]]
		# # Body, links_num lines (not considering comments that might be present)
		# <src_id> <dst_id> [<weight>]
		# ...
		# where:
		#  nodes_num  - the number of nodes (vertices) in the network (graph)
		#  Links  - are either Edges (for the undirected network) or Arcs (for the direted network)
		#  links_num  - the number of <links> (edges or arcs) in the network
		#  weighted = {0, 1}  - wether the network is weighted or not, default: 1
		#
		#  src_id  - source node id >=0
		#  dst_id  - destination node id >=0
		#  weight  - weight in case the network is weighted, non-negative floating point number

		# Parse initial header
		snd = None  # Source node
		slinks = []  # Source node links
		if inpfmt.parsed.directed is None:
			assert not inpfmt.parsed.links, 'There should not be any parsed links on start'
			# Consider input parameters
			inpfmt.parsed.directed = directed
			inpfmt.parsed.newsection = True
			hdrmark = 'nodes:'  # Header marker
			for ln in finp:
				#ln = ln.lstrip()
				if not ln:
					continue
				# Check for the header
				if ln[0] == inpfmt.symcmt:
					ln = ln[1:].lstrip()
					# Fetch the number of nodes
					word = ln[:len(hdrmark)].lower()
					if word == hdrmark and len(ln) > len(hdrmark):
						ln = ln[len(hdrmark):]
						# Consider commas if present (allow both comma and space separators)
						# and convert them to spaces for the unified provessing
						ln = ' '.join(ln.split(',', 2))
						# Replace ':' -> ': ' to allow Nodes:<nodes_num> having unified parsing
						ln = ': '.join(ln.split(':', 2))
						ln = ln.split(None, 5)  # Up to 5 parts (1 + 2 pairs) + ending strip
						if ln:
							inpfmt.parsed.ndsnum = int(ln[0])
						# Fetch the number of links
						i = 1  # part index
						if len(ln) > i+1:
							if ln[i].lower() == ('arcs:' if inpfmt.parsed.directed else 'edges:'):
								inpfmt.parsed.lnsnum = int(ln[i+1])
								i += 2
							# Check the Weighted flag
							if len(ln) > i+1:
								if ln[i].lower() == 'weighted:':
									inpfmt.parsed.weighted = bool(int(ln[i+1]))  # Note: bool('0') is True
								elif len(ln) > i:
									raise ValueError('The header is invalid or inconsistent with the file type ({}): {}'
										.format('nsa' if inpfmt.parsed.directed else 'nse', ' '.join(ln)))
						# Note: the links will be paesed in the payload
				else:
					# This is the first link, define whether all links weighted using it
					ln = parseSingleLink(ln)
					# ATTENTION: even if weight '0' is specified then the links are weighted
					inpfmt.parsed.weighted = bool(ln[2])  # Note: bool('0') is True
					# Save the link
					if unweight:
						ln[2] = None
					snd = ln[0]
					slinks = inpfmt.parsed.links.setdefault(snd, [])
					slinks.append(ln[1:])
				break
		else:
			inpfmt.parsed.newsection = False
			assert inpfmt.parsed.nextlink and len(inpfmt.parsed.nextlink) == 3, (
				'Next parsing block should be already preparsed and should have'
				' the following format: [src, dst, weight]')
			inpfmt.parsed.links.clear()  # Note: .clear() for arrays only is not compatible with Python2
			snd = inpfmt.parsed.nextlink[0]
			slinks = inpfmt.parsed.links.setdefault(snd, [])
			slinks.append(inpfmt.parsed.nextlink[1:])

		# Parse payload block
		lnsformed = len(slinks)  # The number of formed links
		for ln in finp:
			#ln = ln.lstrip()
			# Skip empty lines and comments except the header
			if not ln or ln[0] == inpfmt.symcmt:
				continue
			# Parse: src dst [weight] block having the same src
			ln = parseSingleLink(ln)
			if unweight:
				ln[2] = None
			# Add the link
			if ln[0] == snd or not snd or lnsformed < blsnum:
				if ln[0] != snd:
					snd = ln[0]
					slinks = inpfmt.parsed.links.setdefault(snd, [])
				slinks.append(ln[1:])
				lnsformed += 1
			else:
				inpfmt.parsed.nextlink = ln
				#print('Parsed {} links, newsection: {}, return TRUE'.format(lnsformed, inpfmt.parsed.newsection))
				return True

		#print('Parsed {} links, newsection: {}, return FALSE'.format(lnsformed, inpfmt.parsed.newsection))
		return False  # The parsing is fully completed

	return parser


def parseBlockMetis(inpfmt, finp, unweight, blsnum=DEFAULT_BLOCK_LINKS):
	"""Meits format parser

	inpfmt  - input format
	finp  - input stream
	unweight  - omit weights
	blsnum  - approximate block size in links (at list this number of links
		if not interrupted by the section completion)

	return parsing  - whether the parsng is not completed yet
	"""
	# Metis format of the input graph (.graph):
	# % Comments are marked with '%' symbol
	# % Header:
	# <vertices_num> <endges_num> [<format_bin> [vwnum]]
	# % Body, vertices_num lines without the comments:
	# [vsize] [vweight_1 .. vweight_vwnum] vid1 [eweight1]  vid2 [eweight2] ...
	# ...
	#
	# where:
	#  vertices_num  - the number of vertices in the network (graph)
	#  endges_num  - the number of edges (not directed, A-B and B-A counted
	#      as a single edge).
	#  	ATTENTION: the edges are conunted only once, but specified in each direction.
	#		The arcs must exist in both directions and their weights are symmetric, i.e. edges.
	#  format_bin - up to 3 digits {0, 1}: <vsized><vweighted><eweighted>
	#      vsized  - whether the size of each vertex is specified (vsize), usually 0
	#      vweighted  - whether the vertex weights are specified (vweight_1 .. vweight_vmnum)
	#      eweighted  - whether edges weights are specified eweight<i>
	#  	ATTENTION: when the fmt parameter is not provided, it is assumed that the
	#  		vertex sizes, vertex WEIGHTS, and edge weights are all equal to 1 and NOT present in the file
	#  vwnum  - the number of weights in each vertex (not the same as the number of edges), >= 0
	#      Note: if vwnum > 0 then format_bin.vweighted should be 1
	#
	#  vsize  - size of the vertex, integer >= 0. NOTE: does not used normally
	#  vweight  - weight the vertex, integer >= 0
	#  vid  - vertex id, integer >= 1. ATTENTION: can't be equal to 0
	#  eweight  - edge weight, integer >= 1

	# Parse initial header
	iparsed = inpfmt.parsed
	if iparsed.directed is None:
		assert not iparsed.links, 'There should not be any parsed links on start'
		# ATTENTION: Metis links are treated specially here: they are specified as arcs,
		# but interntionally reduced to the edges with correspondance to the format specificaiton.
		iparsed.directed = False  # Treat links as edges even considering that they are specified in both directions because the weights in Metis are always symmentric
		iparsed.startid = 1  # ATTENTION: vertices id in Metis start from 1
		iparsed.newsection = True
		# Identify whether edges or links are specified
		for ln in finp:
			#ln = ln.lstrip()
			if not ln:
				continue
			# Parse the header
			ln = ln.split(None, 3)
			assert ln and len(ln) >= 2, 'The header is invalid (too long): ' + ' '.join(ln)
			iparsed.ndsnum = int(ln[0])
			iparsed.lnsnum = int(ln[1]) * (1 + iparsed.directed)  # Noe: links number is specified in edges and is corrected for the arcs
			# Parse inpfmt
			if len(ln) > 2:
				fmt = ln[2]
				assert len(fmt) <= 4, 'Invalid attribute, "format" field is too long: ' + fmt
				iparsed.weighted = fmt[-1] == '1'

				if len(fmt) >= 2:
					iparsed._selfweight = fmt[-2] == '1'  # Extra attribute, private
				else:
					iparsed._selfweight = False

				if len(fmt) >= 3:
					iparsed._selfsize = fmt[-3] == '1'  # Extra attribute, private
				else:
					iparsed._selfsize = int(iparsed._selfweight)

				# Parse number of the vertex weights
				if len(ln) > 3:
					iparsed._swsize = int(ln[3])  # Extra attribute, private
				else:
					iparsed._swsize = int(iparsed._selfweight)
				iparsed._frcsln = False  # Do not force the self link, private
			else:
				iparsed.weighted = False
				iparsed._selfweight = False
				iparsed._selfsize = False
				iparsed._swsize = 0
				iparsed._frcsln = False  # Force the self link to have node weight equal to 1 (see the specification), private
			break
		print('Metis format  weighted: {}, selfweights: {}'.format(iparsed.weighted, iparsed._swsize))
		iparsed._sid = 1  # Source node id, private
	else:
		iparsed.newsection = False

	# Clear output data
	iparsed.links.clear()  # Clear links parsed on the previous iteration
	snd = str(iparsed._sid)  # Source node
	lnsformed = 0  # The number of formed links
	# Parse payload block
	for ln in finp:
		slinks = iparsed.links.setdefault(snd, [])  # Source node links
		#ln = ln.lstrip()
		# Skip empty lines and comments except the header
		if not ln or ln[0] == inpfmt.symcmt:
			continue
		# Note: iparsed.nextlink is not nesessary here, because each line represents the block
		ln = ln.split()
		assert len(ln) >= iparsed._selfsize + iparsed._swsize
		i = 0  # Index in the line tokens
		# Skip the node (vernex) size if exist
		if iparsed._selfsize:
			i += 1
		# Parse vertex weights
		if iparsed._selfweight:
			sweight = 0
			if not unweight:
				for j in range(iparsed._swsize):
					sweight += float(ln[i + j])
			slinks.append((snd, str(sweight)))
			lnsformed += 1
			i += iparsed._swsize
		elif iparsed._frcsln:
			# Add default selfweight if required
			slinks.append((snd, None))
			lnsformed += 1
		# Parse links
		didval = True  # Dest id or weight value
		did = -1  # Dest id
		dest = None  # Destination id and weight
		for v in ln[i:]:
			if didval:
				if not iparsed.directed:
					did = int(v)
				dest = [v, None]
			elif not unweight:
				dest[1] = v

			if iparsed.weighted:
				didval = not didval
			# ATTENTION: filter out lower des id for the edges parsing
			if didval and (iparsed.directed or iparsed._sid <= did):
				slinks.append(dest)
		# Remove empty entries
		if not slinks:
			del iparsed.links[snd]
		# Finalize the sting parcing
		iparsed._sid += 1
		if lnsformed < blsnum:
			snd = str(iparsed._sid)
		else:
			return True

	return False  # The parsing is fully completed


def parseBlockPajek(inpfmt, finp, unweight, blsnum=DEFAULT_BLOCK_LINKS):
	"""Meits format parser

	inpfmt  - input format
	finp  - input stream
	unweight  - omit weights
	blsnum  - approximate block size in links (at list this number of links
		if not interrupted by the section completion)

	return parsing  - whether the parsng is not completed yet
	"""
	# Parse a new Pajek Section / Header
	hdrsym = '*'  # Header symbol
	snd = None  # Source node
	slinks = []  # Source node links
	iparsed = inpfmt.parsed
	if iparsed.newsection is None:
		for ln in finp:
			# Skip empty lines and comments except the header
			#ln = ln.lstrip()
			if not ln or ln[0] == inpfmt.symcmt:
				continue
			if ln[0] != hdrsym:
				raise ValueError('The section header is missed: ' + line)
			# Parse initialization header (*Vertices setion)
			ln = ln.split(None, 2)
			ln[0] = ln[0].lower()
			if iparsed.newsection is None:
				# *Vertices <vnum>,
				assert not iparsed.links, 'There should not be any parsed links on start'
				iparsed.startid = 1  # ATTENTION: vertices id in Pajek start from 1
				# The number of Vertices if specified
				if ln[0] == '*vertices':
					iparsed.ndsnum = int(ln[1])
					# Skip this section
					for ln in finp:
						#ln = ln.lstrip()
						if not ln or ln[0] != hdrsym:
							continue
						break
					if not ln:
						return False  # End of the file
					ln = ln.rsplit(None, 1)
					ln[0] = ln[0].lower()
			iparsed._nexthdr = ln[0]
			break

	# Parse the following section if required
	if iparsed._nexthdr:
		iparsed.newsection = True
		# Valid sections:  *arcs, *Edges, *edgeslist, *Arcslist
		if iparsed._nexthdr.startswith('*arcs'):
			iparsed.directed = True
		elif iparsed._nexthdr.startswith('*edges'):
			iparsed.directed = False
		else:
			raise ValueError('Invalid section header: ' + ln[0])
		# Identify whether the section has a list-type
		if iparsed._nexthdr.endswith('list'):
			iparsed.weighted = False
			iparsed._list = True  # The list section, private
		else:
			iparsed.weighted = None
			iparsed._list = False
		iparsed._nexthdr = None
	else:
		iparsed.newsection = False

	# Parse the payload
	iparsed.links.clear()  # Clear links parsed on the previous iteration
	lnsformed = 0  # The number of formed links
	snd = None  # Source node
	for ln in finp:
		#ln = ln.lstrip()
		if not ln or ln[0] == inpfmt.symcmt:
			continue
		# Check for the following section
		if ln[0] == hdrsym:
			iparsed._nexthdr = ln.split(None, 1)[0].lower()  # Next header, private
			return True
		# Parse current section
		if iparsed._list:
			# Format:	src_id dst1_id dst2_id ...
			ln = ln.split()
			slinks = iparsed.links.setdefault(ln[0], [])  # Source node links
			slinks.extend([(v, None) for v in ln[1:]])
			lnsformed += len(ln) - 1
			if lnsformed >= blsnum:
				return True
		else:
			# Format:	src_id dst_id [weight]
			ln = parseSingleLink(ln)
			if unweight:
				ln[2] = None
			if ln[0] == snd or not snd or lnsformed < blsnum:
				if ln[0] != snd:
					snd = ln[0]
					slinks = iparsed.links.setdefault(snd, [])  # Source node links
				slinks.append(ln[1:])
				lnsformed += 1
			else:
				iparsed.nextlink = ln  # Source node links
				return True

	return False


# Accessory Data of the Data Format --------------------------------------------
class ParsedData(object):
	"""Parsed data: incremental blocks and intermediate state data"""
	def __init__(self):
		self.newsection = None  # New section (optional header with data or distinct type of data) is parsed
		self.ndsnum = 0  # The number of nodes (total in the network)
		self.lnsnum = 0  # The number of links in the processed section
		self.directed = None  # The network is directed (arcs), undirected (edges) or not yet defined (None)
		# ATTENTION: initial weighted = None for ParsedData, BUT True for the PrintedData
		self.weighted = None  # The network is weighted, unweighted or not yet defined; Optional, can be filled for some formats (.pajek, etc.)
		self.startid = None  # The lowest node (vertex) id in the input network
		# Payload data. Note: cleared in the parser and should not be modified outside it
		self.links = {}  # src links: list(list(<dest_str>, <weight_str> | None), ...), not dict() because we do not know the output type on input
		# Prepased data for the following iteration
		self.nextlink = []  # list(<src_str>, <dst_str>, <weight_str> | None)


class PrintedData(object):
	"""Printed data: state data between the incremental prints"""
	def __init__(self):
		# ATTENTION: directed and weighted shuold be set only once for .nsl, but can vary for .rcg
		self.directed = None  # Whether the previously printed section was directed (applies to the whole file for .nsl)
		# Accumulated data to be printed, actual only when remdub (duplicates removement is performed)
		# ATTENTION: initial weighted = None for ParsedData, BUT True for the PrintedData
		self.weighted = True  # Whether the output file is globally weighted; True if ParsedData.weighted is None
		self.ndslinks = {}  # Nodes and links, dict of dict
		self.arcstot = 0  # The total number of arcs in the formed network (edges * 2 for the sections with edges)


# Output File Printers ---------------------------------------------------------
def printLinks(outfmt, printer, parsed, remdub, final):
	"""Print block of links

	outfmt  - output format
	printer  - links printer
	parsed  - parsed data
	remdub  - remove duplicated links
	final  - final block
	"""
	# Print the body (payload) block
	assert printer and callable(printer)
	# ATTENTION: all links are stored globally in the pinted.ndslinks only when remdub
	# Print already accumulated links if a new section is started
	if parsed.newsection and outfmt.printed.ndslinks:
		printer(outfmt.printed.ndslinks)
		outfmt.printed.ndslinks.clear()

	if parsed.links:
		# For arcs -> edges: skip lower dest for AB, but consider BA to make the edge in case the back link does not exist
		reminder = []  # Additional links to be outputted <dst> <src> <weight> if dst_id < src_id
		if not outfmt.printed.directed and (parsed.directed or remdub):
			# ATTENTION: full arc weight is used for the edge, so the edge weight is doubled if the back arc does not exist
			# Note: parsed.links are modified
			postdel = []  # Postponed deletion
			for ndls in viewitems(parsed.links):
				edges = []
				sid = int(ndls[0])
				for ln in ndls[1]:
					if sid <= int(ln[0]):
						edges.append(ln)
					elif remdub:
						reminder.append((ln[0], ndls[0], ln[1]))
				if edges:
					parsed.links[ndls[0]] = edges
				else:
					postdel.append(ndls[0])
			# Delete items that copied all the content to the reminder
			for sid in postdel:
				del parsed.links[sid]

		# Accumulate or print the links
		if remdub:
			for ndls in viewitems(parsed.links):
				slinks = outfmt.printed.ndslinks.setdefault(ndls[0], {})
				for link in ndls[1]:
					slinks[link[0]] = link[1]  # Overwrite dest if exists
			for xlink in reminder:
				outfmt.printed.ndslinks.setdefault(xlink[0], {})[xlink[1]] = xlink[2]  # Overwrite dest if exists
		else:
			# Print result to the output file
			for ndls in viewitems(parsed.links):
				printer(ndls[1], ndls[0], not parsed.directed and outfmt.printed.directed)
				# Note: the reminer is skipped here, this edges will be constructed by the backlinks
				# Update the total number of outputted arcs
				outfmt.printed.arcstot += len(ndls[1]) * (1 + (not outfmt.printed.directed or not parsed.directed))

	# Print the accumulated links
	if final:
		if outfmt.printed.ndslinks:
			printer(outfmt.printed.ndslinks)
			# Update the total number of outputted arcs
			remnum = 0
			for ndls in viewvalues(outfmt.printed.ndslinks):
				remnum += len(ndls)
			outfmt.printed.arcstot += remnum * (1 + (not outfmt.printed.directed))
		#outfmt.printed.ndslinks.clear()
		printer(None)


def printBlockRcg(outfmt, fout, parsed, remdub, frcedg, commented, unweight, final=False):  # outfmt, fout, finp, consweight, remdub, frcedg, inpfmt):
	"""Print RCG output block

	outfmt  - output format
	fout  - output stream
	parsed  - parsed data
	remdub  - remove duplicated links
	frcedg  - force edges output (undirected links) even when arcs in the input (should exist in both directions)
	commented  - allow comments in the output file, i.e. headers in the .nsl format
	unweight  - omit weights
	final  - final block
	"""
	# Print the parsed header if required
	if parsed.newsection is None or parsed.newsection:
		# Allow implicit conversion of edges into arcs by the output format specification,
		# however this requires arcs accumulation if dublicates check is required
		if parsed.directed and frcedg:
			print('WARNING, arcs -> edges conversion will be inaccurate in case arcs'
				  ' have distinct forth and back weights', file=sys.stderr)
		# Print the initial header only once
		if outfmt.printed.directed is None:
			# Update PtindedData parameters
			outfmt.printed.directed = parsed.directed and not frcedg
			print('Parsed weighted: {}, newsection: {}'.format(parsed.weighted, parsed.newsection))
			if unweight or parsed.weighted is not None:
				outfmt.printed.weighted = not unweight and parsed.weighted
			fout.write("/Graph weighted:{} validated:{}\n\n".format(int(outfmt.printed.weighted), int(remdub)))
			if parsed.ndsnum:
				if parsed.startid is not None:
					fout.write('/Nodes {} {}\n'.format(parsed.ndsnum, parsed.startid))
				else:
					fout.write('/Nodes {}\n'.format(parsed.ndsnum))
		# Each section is either edges or arcs
		fout.write('\n/{}\n'.format('Arcs' if outfmt.printed.directed else 'Edges'))

	def printLinksRcg(links, src=None, makeback=False):
		"""RCG links printer

		links  - the links to be printed, either list of (dest, weight), or dict of dict.
			None is used as a special value to output the ending commnet (number of arcs, etc.)
		src  - source id if links are list, otherwise None
		makeback  - add backlink (when edges are conveted to the arcs)
		"""
		def linkToStream(fout, link):
			fout.write(' ')
			if link[1] and link[1] != '1':  # float(link[1]) != 1
				fout.write(':'.join((link[0], link[1])))
			else:
				fout.write(link[0])

		if src:
			# Links are a list of (dest, weight)
			fout.write(src + '>')
			for link in links:
				linkToStream(fout, link)
				# Note: links uniques and existence of the back links is validated on the insertion (links with lower src than dst are omitted for the edges)!
			fout.write('\n')
			# Make back links for the edges -> arcs
			if makeback:
				assert outfmt.printed.directed, 'Incompatible flags used flags'
				for link in links:
					ndls = outfmt.printed.ndslinks.setdefault(link[0], {})
					ndls[src] = link[1]  # Overwrite dest if exists
		elif links is not None:
			# ATTENTION: backlinks are already considered in the accumulated links
			# Accumulated links of the whole nework are dict of dict
			for ndls in viewitems(links):
				fout.write(ndls[0] + '>')
				for link in viewitems(ndls[1]):
					linkToStream(fout, link)
				fout.write('\n')
		elif commented:
			# Print total number of arcs as a comment (edges * 2 for the sections with edges)
			fout.write('\n# Arcs: {}\n'.format(outfmt.printed.arcstot))

	# Print the body (payload) block
	# ATTENTION: all links are stored globally in the outfmt.pinted.ndslinks only when remdub
	printLinks(outfmt, printLinksRcg, parsed, remdub, final)


def printBlockNsl(directed):
	"""Print NSE or NSA output block
	directed  - arcs (nsa), otherwise edges (nse)
	"""
	assert isinstance(directed, bool)
	def printer(outfmt, fout, parsed, remdub, frcedg, commented, unweight, final=False):  # , initial
		"""Node Space-separated Links (both NSE and NSL) output formats printer

		outfmt  - output format
		fout  - output stream
		parsed  - parsed data
		remdub  - remove duplicated links
		frcedg  - force edges output (undirected links) even when arcs in the input (should exist in both directions)
		commented  - allow comments in the output file, i.e. headers in the .nsl format
		unweight  - omit weights
		final  - final block
		"""
		# Implicitly force remdub if required
		if parsed.directed and not directed and not remdub:
			if outfmt.printed.directed is None:  # Print it only once
				print('WARNING, duplicates removement is not specified for the arcs -> edges'
					' conversion and is forced implicitly to not produce any duplicated edges', file=sys.stderr)
			remdub = True
		# Print the parsed header if required
		if parsed.newsection is None or parsed.newsection:
			# Allow implicit conversion of edges <-> arcs
			if (outfmt.printed.directed is None or parsed.newsection) and (not directed and parsed.directed):
				print('WARNING, arcs -> edges conversion will be inaccurate in case arcs'
					  ' have distinct forth and back weights', file=sys.stderr)
			# Print the header only once for .nsl
			if outfmt.printed.directed is None:
				if frcedg and directed:
					raise ValueError('Edges output can not be forced into the Arcs output'
						' file and vice versa, frcedg: {}, directed: {}'.format(frcedg, directed))
				# Update PtindedData parameters
				outfmt.printed.directed = directed
				if unweight or parsed.weighted is not None:
					assert outfmt.printed.weighted, 'A graph should be weighted by default'
					outfmt.printed.weighted = not unweight and parsed.weighted
				# Output the dataset desciption (initializeing header)
				if parsed.ndsnum and commented:
					fout.write('{} Nodes: {}'.format(outfmt.symcmt, parsed.ndsnum))
					if parsed.lnsnum:  # not outfmt.printing.initialized and
						linksnum = parsed.lnsnum
						if parsed.directed != outfmt.printed.directed:
							if outfmt.printed.directed:
								linksnum *= 2
							else:
								if linksnum % 2:
									print('WARNING, odd number of links is converted'
										' to the edges', file=sys.stderr)
									linksnum = linksnum // 2 + linksnum % 2
								else:
									linksnum /= 2
						fout.write('\t{}: {}\tWeighted: {}'.format(
							'Arcs' if outfmt.printed.directed else 'Edges'
							, linksnum, int(outfmt.printed.weighted)))
					# ATTENTION: Header should be without empty lines, only comments,
					# othewise some algorithms (GANXiS) fails to parse it
					fout.write('\n')
				# Output the dataset format notation
				if commented:
					fout.write('{0}\n{0} src\tdst{1}\n'.format(outfmt.symcmt, '\tweight'
						# ATTENTION: weighted might be None, which should be counted as default True
						if outfmt.printed.weighted != False else ''))
			else:
				# Update outputting section if required
				print('WARNING, the number of links in the output header is'
					' not accurate because the input file has multiple sections'
					' unlike the output file', file=sys.stderr)

		def printLinksNsl(links, src=None, makeback=False):
			"""NSL(E/A) links printer

			links  - the links to be printed, either list of (dest, weight), or dict of dict.
				None is used as a special value to output the ending commnet (number of arcs, etc.)
			src  - source id if links are list, otherwise None
			makeback  - add backlink (when edges are conveted to the arcs)
			"""
			def linkToStr(src, link):
				if(outfmt.printed.weighted):
					line = ' '.join((src, link[0], link[1] or '1'))
				else:
					line = ' '.join((src, link[0]))
				line += '\n'
				return line

			if src:
				# Links are a list of (dest, weight)
				fout.writelines([linkToStr(src, link) for link in links])
				# Make back links for the edges -> arcs
				if makeback:
					assert outfmt.printed.directed, 'Incompatible flags used flags'
					fout.writelines([linkToStr(link[0], (src, link[1])) for link in links])
			elif links is not None:
				# ATTENTION: backlinks are already considered in the accumulated links
				# Accumulated links of the whole nework are dict of dict
				for ndls in viewitems(links):
					fout.writelines([linkToStr(ndls[0], link) for link in viewitems(ndls[1])])
			elif commented:
				# Print total number of arcs as a comment (edges * 2 for the sections with edges)
				fout.write('# Arcs: {}\n'.format(outfmt.printed.arcstot))  # ATTENTION: some algorithms (GANXiS) do not accept empty lines

		# Print the body (payload) block
		# ATTENTION: all links are stored globally in the outfmt.pinted.ndslinks only when remdub
		printLinks(outfmt, printLinksNsl, parsed, remdub, final)

	return printer


def convertStream(fout, outfmt, finp, inpfmt, unweight, remdub, frcedg, commented):
	"""Build output file from the input file according to the specified formats

	fout  - output stream
	outfmt  - output format
	finp  - input stream
	inpfmt  - input format
	unweight  - omit weights even if exist
	remdub  - remove duplicated links
	frcedg  - force edges output (undirected links) even when arcs in the input (should exist in both directions)
	commented  - allow comments in the output file, i.e. headers in the .nsl format
	"""
	# Note: Both .rcg and .nsl(e/a) output formats can contain links in the
	# arbitrary order, so the per-block input parcing with per-block output forming
	# are appropriate.

	# Parse header only if exists and form resutls considering for the (un)directed case
	assert inpfmt.parsed.directed is None and outfmt.printed.directed is None, 'Inicialization validation failed'

	# Parse the remained part(s) of the input file and build the output
	while(inpfmt.parseBlock(finp, unweight)):  # DEFAULT_BLOCK_LINKS
		outfmt.printBlock(fout, inpfmt.parsed, remdub, frcedg, commented, unweight)
	# Finalize the outut
	outfmt.printBlock(fout, inpfmt.parsed, remdub, frcedg, commented, unweight, True)


# Data Format Specification ----------------------------------------------------
class FormatSpec(object):
	"""Input data format (network/graph) specification and description"""
	def __init__(self, fid, symcmt, descr, parser=None, printer=None, fmt=None, fmtdescr=None, exts=None):
		"""Initialization of the format specification:

		id  - format id, should be a unique string. preferaly readable and meaningful
		symcmt  - comment symbol
		descr  - format description
		parser  - function that parses this format
		printer  - function that prints this format
		fmt  - formal self specification of the format
		fmtdescr  - desription of the formal specification
		exts  - tuple of extensions of the files without the leading '.'. Default: (<id>,)
		"""
		assert (isinstance(fid, str) and isinstance(descr, str) and (fmt is None or isinstance(fmt, str))
			and (fmtdescr is None or isinstance(fmtdescr, str))), ('FormatSpec(), parameters validation failed:'
			'  id: {}, descr: {}, fmt: {}, fmtdescr: {}'.format(fid, descr, fmt, fmtdescr))
		self.id = fid
		self.descr = descr
		self.fmt = fmt
		self.fmtdescr = fmtdescr

		assert isinstance(symcmt, str) and len(symcmt) == 1
		self.symcmt = symcmt  # Comment (reminder) symbol

		assert parser is None or callable(parser)
		self.__parser = parser
		assert printer is None or callable(printer)
		self.__printer = printer
		assert exts is None or isinstance(exts, (tuple, list))
		self.exts = exts if exts else (self.id,)

		# Accessory data
		self.parsed = ParsedData()	# Data parsed by the parser, incrementally rewritten
		self.printed = PrintedData()  # Printing data, state data between the incremental prints

	def __str__(self):
		"""Readable string representation"""
		inpoutp = ''
		if self.__parser:
			inpoutp = 'INP'
		if self.__printer:
			if inpoutp:
				inpoutp += ', '
			inpoutp += 'OUTP'
		intro = '{} ({inpoutp})  - {descr}. File extensions: {exts}'.format(self.id
			, inpoutp=inpoutp, descr=self.descr, exts=', '.join(self.exts))
		if self.fmt :
			intro += '. Specification:' + self.fmt
			if self.fmtdescr:
				intro = '{base}\n  Notations:\n{fmtdescr}'.format(base=intro, fmtdescr=self.fmtdescr)
		return intro

	def __repr__(self):
		"""Unique string representation"""
		return self.id

	def parseBlock(self, *args):
		if self.__parser:
			return self.__parser(self, *args)
		else:
			raise AttributeError('The parser was not set')

	def printBlock(self, *args):
		if self.__printer:
			return self.__printer(self, *args)
		else:
			raise AttributeError('The printer was not set')

	def native(self):
		"""Natively supported format, i.e. also an output format"""
		return self.__printer is not None


def inputFormats():
	"""Specification of the supporting input formats

	return inpfmts  - map of the file formats by id
	"""
	ntspan = '  '  # Left span for the formal description

	pjk = FormatSpec('pjk', '%', 'pajek network format: https://gephi.org/users/supported-graph-formats/pajek-net-format/. '
		' Node ids started with 1, both [weighted] arcs and edges might be present.'
		, parser=parseBlockPajek, exts=('pjk', 'pajek', 'net', 'pjn'))

	nse = FormatSpec('nse', '#'
		, 'nodes are specified in lines consisting of the single Space/tab separated, possibly weighted Edge (undirected link).'
		' It is similar to the .ncol format (http://lgl.sourceforge.net/#FileFormat) and'
		' [Weighted] Edge Graph (https://www.cs.cmu.edu/~pbbs/benchmarks/graphIO.html),'
		' but self-edges are allowed to represent node weights and the line comment is allowed using "#" symbol.'
		, parser=parseBlockNsl(False), printer=printBlockNsl(False), fmt=
"""
{0}# Comments start with '#', the header is optional:
{0}# Nodes: <nodes_num>	Edges: <edges_num>
{0}<from_id> <to_id> [<weight>]
{0}...
""".format(ntspan)
		, fmtdescr=
"""{0}The header is optional. The edges (undirected links) are unique, i.e. either
{0}    AB or BA is specified.
{0}Id is a positive integer number (>= 1), id range is solid.
{0}Weight is a non-negative floating point number.""".format(ntspan)
		, exts=('nse', 'snap', 'ncol'))

	nsa = FormatSpec('nsa', '#'
		, 'nodes are specified in lines consisting of the single Space/tab separated, possibly weighted Arc (directed link)'
		', a self-arc can be used to represent the node weight and the line comment is allowed using "#" symbol.'
		, parser=parseBlockNsl(True), printer=printBlockNsl(True), fmt=
"""
{0}# Comments start with '#', the header is optional:
{0}# Nodes: <nodes_num>	Arcs: <arcs_num>
{0}<from_id> <to_id> [<weight>]
{0}...
""".format(ntspan)
		, fmtdescr=
"""{0}The header is optional. The arcs (directed links) are unique and always in pairs, i.e. BA should be specified until it's weight is zero if AB is specified.
{0}Id is a positive integer number (>= 1), id range is solid.
{0}Weight is a non-negative floating point number.""".format(ntspan))

	mts = FormatSpec('mts', '%'
		, 'metis graph (network) format: http://glaros.dtc.umn.edu/gkhome/fetch/sw/metis/manual.pdf'
		, parser=parseBlockMetis, fmt=
"""
{0}% Comments start with '%' symbol
{0}% Header:
{0}<vertices_num> <endges_num> [<format_bin> [vwnum]]
{0}% Body, vertices_num lines without the comments:
{0}[vsize] [vweight_1 .. vweight_vwnum] vid1 [eweight1]  vid2 [eweight2] ...
{0}...
""".format(ntspan)
		, fmtdescr=
"""{0}vertices_num  - the number of vertices in the network (graph)
{0}endges_num  - the number of edges (not directed, A-B and B-A counted
{0}    as a single edge)
{0}      ATTENTION: the edges are conunted only once, but specified in each
{0}        direction. The arcs must exist in both directions and their weights
{0}        are symmetric, i.e. edges.
{0}format_bin - up to 3 digits {{0, 1}}: <vsized><vweighted><eweighted>
{0}    vsized  - whether the size of each vertex is specified (vsize)
{0}    vweighted  - whether the vertex weights are specified
{0}        (vweight_1 .. vweight_vmnum)
{0}    eweighted  - whether edges weights are specified eweight<i>
{0}      ATTENTION: when the fmt parameter is not provided, it is assumed that
{0}        the vertex sizes, vertex WEIGHTS, and edge weights are all equal to 1
{0}        and NOT present in the file
{0}vm_num  - the number of weights in each vertex (not the number of edges)

{0}vsize  - size of the vertex, integer >= 0. NOTE: do not used normally
{0}vweight  - weight the vertex, integer >= 0
{0}vid  - vertex id, integer >= 1. ATTENTION: can't be equal to 0
{0}eweight  - edge weight, integer >= 1""".format(ntspan)
  		, exts=('graph', 'mtg', 'met'))

	#print('Formats formed: ' +  ','.join(viewkeys(inpfmts)))
	return {fmt.id: fmt for fmt in (pjk, nse, nsa, mts)}


# Exporting Logic --------------------------------------------------------------
def convert(args):
	"""Convert input network (graph) to the required format

	args.network  - input network(graph)
	args.inpfmt  - format of the input network, FormatSpec

	args.remdup  - remove duplicated links
	args.frcedg  - force edges output
	args.unweight  - force unweighing (omit weights)
	args.commented  - allow comments in the output file (default: True). Note:
		these comments might for the header (.nsl formats) and contain provenance

	args.outfmt  - output format for the network, FormatSpec
	args.resolve  - resolution strategy in case the output file already exists
	"""
	# Convert the input network
	with open(args.network, 'r') as finp:
		print('File "{}" is opened, converting...\n\tunweight: {}\n\tremdub: {}'
			'\n\tfrcedg: {}\n\tinpfmt: {}\n\tresolve: {}\n\toutfmt: {}\n\tcommented: {}'
			.format(args.network, args.unweight, args.remdub, args.frcedg, args.inpfmt.id
				, args.resolve, args.outfmt.id, args.commented))
		if args.frcedg:
			args.remdub = True  # Forse in case of frcedg
		foutName = outName(args.network, args.outfmt)
		# Check whether output file exists
		exists = os.path.exists(foutName)
		if exists:
			act = None
			if args.resolve == 'o':
				act = 'overwriting...'
			elif args.resolve == 'r':
				mtime = time.strftime('_%y%m%d_%M%S', time.gmtime(os.path.getmtime(foutName)))
				renamed = foutName + mtime
				os.rename(foutName, renamed)
				act = 'renaming the old one into {}...'.format(renamed)
			elif args.resolve == 's':
				act = 'the conversion is skipped'
			else:
				raise ValueError('Unchown action to be done with the existent file: ' + args.resolve)
			print('WARNING, the output file "{}" already exists, {}'.format(foutName, act), file=sys.stderr)
			if args.resolve == 's':
				return
		try:
			# Create output file
			with open(foutName, 'w') as fout:
				print('File {} is created, filling...'.format(foutName))
				# Write provenance to the forming file as a comment
				if args.commented:
					fout.write('{} Converted from {}\n'.format(args.outfmt.symcmt, args.network))
				#outfmt.convertStream(fout, finp, unweight, remdub, frcedg, inpfmt)
				convertStream(fout, args.outfmt, finp, args.inpfmt, args.unweight, args.remdub
					, args.frcedg, args.commented)
				print('{} -> {} conversion is completed'.format(args.network, foutName))
		except StandardError:
			# Remove incomplete output file
			if os.path.exists(foutName):
				os.remove(foutName)
			raise


def parseArgs(params=None):
	"""Parse input parameters (arguments)

	params  - the list of arguments to be parsed (argstr.split()), sys.argv is used if args is None

	return args  - parsed arguments
	"""
	# Initialize I/O formats
	inpfmts = inputFormats()
	# TODO: add link to the convert/format.rcg and update the file with the selflink
	rcg = FormatSpec('rcg', '#', 'readable compact graph format (former hig), native'
		' input format of DAOC. This format is similar to Pajek, but ids can start'
		' from any non-negative number and might not form a solid range. RCG is a'
		' readable and compact network format suitable for the evolving networks.'
# Headers have weighted attribute to represented optinally weighted lists of links (edges or arvs).
# Node weigh is specidied via selflink(s). Weights are explicitly separated from ids for the readability.', printer=printBlockRcg
		, printer=printBlockRcg, exts=('rcg', 'hig'))

	# Specify and process input arguments
	parser = argparse.ArgumentParser(description='Convert format of the specified network (graph).'
		#, formatter_class=argparse.RawTextHelpFormatter
		)
	exclpars = parser.add_mutually_exclusive_group(required=True)
	exclpars.add_argument('-f', '--showfmt', dest='showfmt', action='store_true'
		, help='show supporting I/O formats description and exit')
	exclpars.add_argument('network', nargs='?'#, type=str, default=''
		, help='the network (graph) to be converted')

	ipars = parser.add_argument_group('Input Format')
	# Note: to init with the FormatSpec use argparse.Action(option_strings, dest, nargs=None
	# , const=None, default=None, type=None, choices=None, required=False, help=None, metavar=None)
	ipars.add_argument('-i', '--inpfmt', dest='inpfmt', choices=viewkeys(inpfmts)
		, help='input network (graph) format')  # , default='pjk'

	mpars = parser.add_argument_group('Additional Modifiers')
	mpars.add_argument('-d', '--remdup', dest='remdub', action='store_true'
		, help='remove duplicated links to have unique ones')
	mpars.add_argument('-e', '--frcedg', dest='frcedg', action='store_true'
		, help='force edges output even in case of ars input: the output edge'
		' is created by the first occurrance of the input link (edge/arc) and has'
		' weight of this link omitting the subsequent back link (if exists)')
	mpars.add_argument('-u', '--unweight', dest='unweight', action='store_true'
		, help='force links to be unweighted instead of having the input weights')
	mpars.add_argument('-c', '--nocoms', dest='commented', action='store_false'
		, help='clear (avoid) comments in the output file (conversion provenance'
		' is not added, headers for .nsX are omitted, etc.). Can be useful when'
		' .ncol file should be produces instead of the Stanford SNAP-like format')

	opars = parser.add_argument_group('Output Format')
	opars.add_argument('-o', '--outfmt', dest='outfmt'
		, choices=[x.id for x in viewvalues(inpfmts) if x.native()] + [rcg.id]
		, default=rcg.id, help='output format for the network (graph)')
	opars.add_argument('-r', '--resolve', dest='resolve', choices=('o', 'r', 's')
		, default='o', help='resolution strategy in case the output file is already exists:'
		' o  - overwrite the output file,'
		' r  - rename the existing output file and create the new one,'
		' s  - skip processing if such output file already exists')

	args = parser.parse_args()
	#print('Args: ' + ' '.join(dir(args)))

	# Show detailed format specifiction and exit if required
	if args.showfmt:
		allfmts = [rcg]
		allfmts.extend(viewvalues(inpfmts))
		print('Supported I/O formats:\n\n> {}'.format('\n\n> '.join(
			[str(x) for x in allfmts])))
		sys.exit(0)

	# Convert I/O formats to FormatSpec from the string id
	if not args.inpfmt:
		# Infer the file format from the file extension
		ext = os.path.splitext(args.network)[1]
		if ext:
			ext = ext[1:]
			if ext:
				allfmts = [rcg]
				allfmts.extend(viewvalues(inpfmts))
				for fmt in allfmts:
					if ext in fmt.exts:
						args.inpfmt = fmt
						break
		if not args.inpfmt:
			raise ValueError('The format of the input network is not specified and'
				' can not be inferred from the extension: ' + os.path.split(args.network)[1])
	else:
		args.inpfmt = inpfmts[args.inpfmt]
	args.outfmt = rcg if args.outfmt == rcg.id else inpfmts[args.outfmt]

	return args


if __name__ == '__main__':
	convert(parseArgs())


__all__ = [convert, FormatSpec]
