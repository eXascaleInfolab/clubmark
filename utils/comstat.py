#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
\descr: Show statistics about communities specified in ncl file:
	- the number of communities
	- the number of distinct nodes
	- the number of overlaps
	...
\author: Artem Lutov <luart@ya.ru>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2016-11
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import argparse
import sys
import os  # fstat
from math import sqrt, log10
import numpy as np
import matplotlib.pyplot as plt


class OrderedRingBuffer(object):
	"""Acs Ordered Ring Buffer of the specified type (unsigned integer numbers by default)"""
	def __init__(self, capacity, val=None, inverse=False, etype=np.uint32):
		"""Constructor

		Parameters:
		capacity  - capacity of the array
		val  - initial value of the first member (unsigned int), otherwise the array will be empty
		inverse  - inverse ordering (desc for min items)
		etype  - type of the elements in the array

		Attributes:
		data  - internal buffer
		"""
		assert val is None or val >= 0, 'capacity should be positive and val should be a non-negative integer'
		if capacity <= 0:
			raise ValueError('capacity should be positive')
		self.inverse = inverse
		if self.inverse:
			self.data = np.full(capacity, np.iinfo(etype).max, dtype=etype)  # Create a zero initialized array
		else:
			self.data = np.zeros(capacity, dtype=etype)  # Create a zero initialized array
		if val is not None:
			self.data[-1] = val

	def add(self, val):
		"""Add new value keepeing the order"""
		assert val >= 0, 'uint is expected'
		if (not self.inverse and val <= self.data[0]) or (self.inverse and val >= self.data[0]):
			return
		#print(val)
		#data = self.data if not self.inverse else self.data[::-1]
		if not self.inverse:
			pos = np.searchsorted(self.data, val)  # Note: pos >= 1 here
		else:
			pos = self.data.size - np.searchsorted(self.data[::-1], val)  # Note: pos >= 1 here
		assert pos >= 1, 'pos < 1 was prefiltered'
		if pos >= 2:
			self.data[:pos-1] = self.data[1:pos]  # Move range to the left loosing the first item
		self.data[pos-1] = val


def comstat(communs, plotstat):
	""" Evaluate and display statistics for the specified communities

	communs  - communities (clusters) input stream (file)
	plotstat  - whether to plot the nodes and communities statistics
	"""
	#print('communs  type: {}, size: {}'.format(type(communs), os.fstat(communs.fileno()).st_size))
	cmsbytes = os.fstat(communs.fileno()).st_size  # The number of bytes in communities file
	# Estimated number of items (elements) in the file assuming that each following item has increasing id starting from 0.
	# Though, actually each item migh occur multiple times.
	magn = 10  # Decimal ids magnitude
	reminder = cmsbytes % magn
	elsnum = reminder / 2  # Consider delimiter after each item
	while cmsbytes >= magn:
		magn *= 10
		elsnum += (cmsbytes - reminder) % magn / 2
		reminder = cmsbytes % magn
	magn = log10(magn) / 4  # Consider repeating node ids in each cluster to some extend
	elsnum = round(elsnum / magn)

	topn = 7  # Number of top sizes of the communities to be listes
	etype = np.uint32  # Type of the elements in the array
	topcms = OrderedRingBuffer(topn, etype=etype)
	comsnum = 0  # The number of communities
	mbsnum = 0  # The accumulated number of member nodes in all communities
	mbsnum2 = 0  # Accumulated squared number of member nodes in all communities
	mbsmin = sys.maxsize
	mbsmax = 0
	# Preallocate space for all nodes
	# Do not zeroise since each item will be filled with id and the number of filled items is stored
	if plotstat:
		nodes = np.empty(elsnum, dtype=etype)
		inds = 0  # Index (position) for nodes
		comsizes = np.empty(round(sqrt(elsnum)), dtype=etype)  # Preallocate array of clusters
	for ln in communs:
		# Allow and skip line comments
		if not ln or ln[0] == '#':
			continue
		comnds = np.fromstring(ln, dtype=etype, sep=' \t')  # [int(v) for v in ln.split()]
		if not comnds.size:
			continue
		# Save community (cluster) size
		if plotstat:
			if comsizes.size < comsnum + comnds.size:
				comsizes.resize(round(comsizes.size * 1.2))
			comsizes[comsnum] = comnds.size
		comsnum += 1
		# Aggregate statistics
		mbsnum += comnds.size
		mbsnum2 += comnds.size*comnds.size
		if comnds.size < mbsmin:
			mbsmin = comnds.size
		#if comnds.size > mbsmax:
		#	mbsmax = comnds.size
		topcms.add(comnds.size)
		# Accumulate nodes
		if plotstat:
			if nodes.size < inds + comnds.size:
				nodes.resize(round(max(nodes.size * 1.2, inds + comnds.size)))
			nodes[inds : inds + comnds.size] = comnds
			inds += comnds.size

	if plotstat:
		print('# members resized from {} to {}: '.format(nodes.size, inds))  # Note: here each node id might present multiple times
		nodes.resize(inds)  # Trim unused part
		nodes, ndscounts = np.unique(nodes, return_counts=True)
		#nidmin = min(nodes)  # Minimal node id
		ndscounts.sort()  # Sort in place
		print('# communities resized from {} to {}: '.format(comsizes.size, comsnum))
		comsizes.resize(comsnum) # Trim unused part
		comsizes.sort()  # Sort in place
		print('Largest {} communities: {}, smallest: {}'.format(topn, comsizes[-topn:], comsizes[:topn]))

		plt.figure(1)
		plt.subplot(211)
		plt.plot(ndscounts)
		plt.ylabel('Frequency')
		plt.xlabel('Node')
		plt.yscale('log')
		plt.title('Node Statistics')

		plt.subplot(212)
		plt.plot(comsizes)
		plt.ylabel('Size')
		plt.xlabel('Community')
		plt.yscale('log')
		plt.title('Community Statistics')
		plt.subplots_adjust(top=0.94, bottom=0.09, left=0.092, right=0.95, hspace=0.38, wspace=0.35)
		plt.show()
	mbsmax = topcms.data[-1]
	mbssd = 0  # Standard deviation of the community size
	mbsmean = 0
	if comsnum:
		mbsmean = mbsnum / comsnum
		mbssd = sqrt((mbsnum2 - mbsmean * mbsmean) / comsnum)
	print('Communities (lines): {comsnum}\nMembers: {mbsnum},  min: {mbsmin}, mean: {mbsmean:.2f}'
		', max: {mbsmax},  SD: {mbssd:.5G},  largest {topn} communities: {tcs}'
		.format(comsnum=comsnum, mbsnum=mbsnum, mbsmin=mbsmin, mbsmean=mbsmean
		, mbsmax=mbsmax, mbssd=mbssd, topn=topn, tcs=np.array_str(topcms.data)
		))
	ndsnum = nodes.size if plotstat else None
	if ndsnum:
		print('Nodes: {ndsnum}, overlaps: {ovp:.4%}'.format(ndsnum=ndsnum
			, ovp=(mbsnum-ndsnum)/ndsnum))  # Note: it's fine that the nodes overlaps can be > 100%
	#if plotstat:
	#	top10min7 = OrderedRingBuffer(topn, etype=etype, inverse=True)
	#	for nd in comsizes[-10:]:
	#		top10min7.add(nd)
	#	print('top10min7: {}'.format(top10min7.data))
	#	assert np.all(top10min7.data == comsizes[-10:topn-10][::-1])


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Show community statistics.')

	parser.add_argument('communs', nargs='?', type=argparse.FileType('r')
		, default=sys.stdin, help='network communities in NCL format')
	parser.add_argument('-p', '--plot', action='store_true', help='show plots')

	args = parser.parse_args()

	comstat(args.communs, args.plot)
