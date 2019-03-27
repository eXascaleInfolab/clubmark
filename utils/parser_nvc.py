#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: Implementation of the NVC (Node Vectors by Clusters) parser
	NVC format is a compact readable format for the graph/network embedding vectors.
:Authors: Artem Lutov <luart@ya.ru>
:Organizations: eXascale lab <http://exascale.info/>, Lumais <http://www.lumais.com/>
:Date: 2019-03
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
from scipy.sparse import dok_matrix  #, coo_matrix
import numpy as np


def loadNvc(nvcfile):
	"""Load network embeddings from the specified file in the NVC format v1.1

	nvcfile: str  - file name

	return
		embeds: matrix  - embeddings matrix in the Dictionary Of Keys sparse matrix format
		dimwsim: array  - dimensions weights for the similarity or None
		dimwdis: array  - dimensions weights for the dissimilarity or None
	"""
	hdr = False  # Whether the header is parsed
	ftr = False # Whether the footer is parsed
	ndsnum = 0  # The number of nodes
	dimnum = 0  # The number of dimensions (reprsentative clusters)
	numbered = False
	dimwsim = None  # Dimension weights for the similarity
	dimwdis = None  # Dimension weights for the dissimilarity
	COMPR_NONE = 0
	COMPR_RLE = 1
	COMPR_SPARSE = 2
	COMPR_CLUSTER = 4  # Default
	compr = COMPR_CLUSTER  # Compression type
	VAL_BIT = 0
	VAL_UINT8 = 1
	VAL_UINT16 = 2
	VAL_FLOAT32 = 4
	valfmt = VAL_UINT8  # Falue format
	hdrvals = {'nodes:': None, 'dimensions:': None, 'value:': None, 'compression:': None, 'numbered:': None}
	irow = 0  # Payload line (matrix row) index (of either dimensions or nodes)
	nvec = None  # Node vectors matrix
	vqnorm = np.uint16(0xFF if valfmt == VAL_UINT8 else 0xFFFF)  # Normalization value for the vector quantification based compression

	with open(nvcfile, 'r') as fnvc:
		for ln in fnvc:
			if not ln:
				continue
			if ln[0] == '#':
				if not hdr:
					# Parse the header
					# Consider ',' separator besides the space
					ln = ' '.join(ln[1:].split(','))
					toks = ln.split(None, len(hdrvals) * 2)
					while toks:
						#print('toks: ', toks)
						key = toks[0].lower()
						isep = 0 if key.endswith(':') else key.find(':') + 1
						if isep:
							val = key[isep:]
							key = key[:isep]
						if key not in hdrvals:
							break
						hdr = True
						if isep:
							hdrvals[key] = val
							toks = toks[1:]
						elif len(toks) >= 2:
							hdrvals[key] = toks[1]
							toks = toks[2:]
						else:
							del toks[:]
					if hdr:
						print
						ndsnum = np.uint32(hdrvals.get('nodes:', ndsnum))
						dimnum = np.uint16(hdrvals.get('dimensions:', dimnum))
						numbered = int(hdrvals.get('numbered:', numbered))  # Note: bool('0') is True (non-empty string)
						comprstr = hdrvals.get('compression:', '').lower()
						if comprstr == 'none':
							compr = COMPR_NONE
						elif comprstr == 'rle':
							compr = COMPR_RLE
						elif comprstr == 'sparse':
							compr = COMPR_SPARSE
						elif comprstr == 'cluster':
							compr = COMPR_CLUSTER
						else:
							raise ValueError('Unknown compression format: ' + compr)
						valstr = hdrvals.get('value:', '').lower()
						if valstr == 'bit':
							valfmt = VAL_BIT
						elif valstr == 'uint8':
							valfmt = VAL_UINT8
						elif valstr == 'uint16':
							valfmt = VAL_UINT16
						elif valstr == 'float32':
							valfmt = VAL_FLOAT32
						else:
							raise ValueError('Unknown value format: ' + valstr)
						#print('hdrvals:',hdrvals, '\nnumbered:', numbered)
				elif not ftr:
					# Parse the footer
					vals = ln[1:].split(None, 1)
					if not vals or vals[0].lower() != 'diminfo>':
						continue
					ftr = True
					if len(vals) <= 1:
						continue
					vals = vals[1].split()
					idimw = vals[0].find(':') + 1
					if vals and idimw:
						# if valfmt == VAL_UINT8 or valfmt == VAL_UINT16:
						# 	dimwsim = np.array([np.float32(1. / np.uint16(v[v.find(':') + 1:])) for v in vals], dtype=np.float32)
						# else:
						if vals[0].find('/', idimw) == -1:
							dimwsim = np.array([np.float32(v[v.find(':') + 1:]) for v in vals], dtype=np.float32)
						else:
							dimwsim = np.array([np.float32(v[v.find(':') + 1:v.rfind('/')]) for v in vals], dtype=np.float32)
							dimwdis = np.array([np.float32(v[v.rfind('/')+1:]) for v in vals], dtype=np.float32)
				continue

			# Construct the matrix
			if not (ndsnum and dimnum):
				raise ValueError('Invalid file header, the number of nodes ({}) and dimensions ({}) should be positive'.format(ndsnum, dimnum))
			# TODO: Ensure that non-float format for bits does not affect the subsequent evaluations or use dtype=np.float32 for all value formats
			if nvec is None:
				nvec = dok_matrix((ndsnum, dimnum), dtype=np.float32 if valfmt != VAL_BIT else np.uint8)

			# Parse the body
			if numbered:
				# Omit the cluster or node id prefix of each row
				ln = ln.split('>', 1)[1]
			vals = ln.split()
			if compr == COMPR_CLUSTER:
				if valfmt == VAL_BIT:
					for nd in vals:
						nvec[np.uint32(nd), irow] = 1
				else:
					nids, vals = zip(*[v.split(':') for v in vals])
					if valfmt == VAL_UINT8 or valfmt == VAL_UINT16:
						# vals = [np.float32(1. / np.uint16(v)) for v in vals]
						vals = [np.float32(vqnorm - np.uint16(v) + 1) / vqnorm for v in vals]
					else:
						assert valfmt == VAL_FLOAT32, 'Unexpected valfmt'
					for i, nd in enumerate(nids):
						nvec[np.uint32(nd), irow] = vals[i]
			elif compr == COMPR_SPARSE:
				if valfmt == VAL_BIT:
					for dm in vals:
						nvec[irow, np.uint32(dm)] = 1
				else:
					dms, vals = zip(*[v.split(':') for v in vals])
					if valfmt == VAL_UINT8 or valfmt == VAL_UINT16:
						# vals = [np.float32(1. / np.uint16(v)) for v in vals]
						vals = [np.float32(vqnorm - np.uint16(v) + 1) / vqnorm for v in vals]
					else:
						assert valfmt == VAL_FLOAT32, 'Unexpected valfmt'
					for i, dm in enumerate(dms):
						nvec[irow, np.uint32(dm)] = vals[i]
			elif compr == COMPR_RLE:
				corr = 0  # RLE caused index correction
				for j, v in enumerate(vals):
					if v[0] != '0':
						if valfmt == VAL_UINT8 or valfmt == VAL_UINT16:
							# nvec[irow, j + corr] = 1. / np.uint16(v)
							nvec[irow, j + corr] = np.float32(vqnorm - np.uint16(v) + 1) / vqnorm
						else:
							assert valfmt == VAL_FLOAT32 or valfmt == VAL_BIT, 'Unexpected valfmt'
							nvec[irow, j + corr] = v
					elif len(v) >= 2:
						if v[1] != ':':
							raise ValueError('Invalid RLE value (":" separator is expected): ' + v);
						corr = np.uint16(v[2:]) + 1  # Length, the number of values to be inserted / skipped
					else:
						corr += 1
			else:
				assert compr == COMPR_NONE, 'Unexpected compression format'
				corr = 0  # 0 caused index correction
				for j, v in enumerate(vals):
					if v == '0':
						corr += 1
						continue
					if valfmt == VAL_UINT8 or valfmt == VAL_UINT16:
						# nvec[irow, j + corr] = 1. / np.uint16(v)
						nvec[irow, j + corr] = np.float32(vqnorm - np.uint16(v) + 1) / vqnorm
					else:
						assert valfmt == VAL_FLOAT32 or valfmt == VAL_BIT, 'Unexpected valfmt'
						nvec[irow, j + corr] = v
			irow += 1

	assert not dimnum or dimnum == irow, 'The parsed number of dimensions is invalid'
	assert len(dimwsim) == len(dimwdis), 'Parsed dimension weights are not synchronized'
	#print('nvec:\n', nvec, '\ndimwsim:\n', dimwsim, '\ndimwdis:\n', dimwdis)
	# Return node vecctors matrix in the Dictionary Of Keys based sparse format and dimension weights
	return nvec, dimwsim, dimwdis  # nvec.tocsc() - Compressed Sparse Column format
