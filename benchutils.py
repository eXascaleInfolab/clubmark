#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr:  Common routines of the modular benchmark (Python Clustering Algorithms BenchMark).

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-11
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import sys
import os
import glob
import shutil
import time
import tarfile
import re

from multiprocessing import Lock
from math import sqrt
from math import copysign


_BCKDIR = 'backup/'  # Backup directory
_REFLOAT = re.compile('[-+]?\d+\.?\d*([eE][-+]?\d+)?(?=\W)')  # Regular expression to parse float
_REINT = re.compile('[-+]?\d+(?=\W)')  # Regular expression to parse int
_SEPINST = '^'  # Network instances separator, must be a char
_SEPPARS = '!'  # Network parameters separator, must be a char
_SEPPATHID = '#'  # Network path id separator (to distinguish files with the same name from different dirs in the results), must be a char
_PATHID_FILE = 'f'  # File marker of the pathid (input file specified directly without the embracing dir), must be a char
# Note: '.' is used as network shuffles separator


def delPathSuffix(path, nameonly=False):
	"""Extracts base of the path skipping instance, shuffling and pathid suffixes

	path  - path to be processed WITHOUT the file extension
	nameonly  - process path as name only comonent (do not split the basedir)

	return  base of the path without suffixes

	>>> delPathSuffix('1K10^1!k7.1#1')
	'1K10'
	>>> delPathSuffix("1K10^1.2#1") == '1K10'
	True
	>>> delPathSuffix('2K5^1', False) == '2K5'
	True
	>>> delPathSuffix('scp/mod/2K5.1', True) == 'scp/mod/2K5'
	True
	>>> delPathSuffix('1K10!k5#1') == '1K10'
	True
	>>> delPathSuffix('1K10!k3') == '1K10'
	True
	>>> delPathSuffix('2K5') == "2K5"
	True
	>>> delPathSuffix('2K5.dhrh^1') == "2K5.dhrh"
	True

	#>>> delPathSuffix('2K5.dhrh^1.1.cnl', True) == '2K5.dhrh'
	#True
	#>>> delPathSuffix('scp/mod/1K10^1!k5#1.mod') == 'scp/mod/1K10'
	#True
	"""
	# Separate path into base dir and name
	if not nameonly:
		pdir, pname = os.path.split(path)
	else:
		pdir = None
		pname = path
	# Find position of the separator symbol, considering that it can't be begin of the name
	if len(pname) >= 2:
		# Note: +1 compensates start from the symbol at index 1. Also a separator can't be the first symbol
		poses = [pname[1:].rfind(c) + 1 for c in (_SEPINST, _SEPPATHID, '.')]  # Note: reverse direction to skip possible separator symbols in the name itself
		## Consider possible extension of the filename
		## Note: this handling is fine, but not reliable (part of the name of file extensoin can be handled as a shuffle index
		#pos = pname[1:].rfind('.') + 1
		#if pos and pos > max(poses):
		#	poses.append(pos)
		#	pos = pname[1:pos].rfind('.') + 1
		#	if pos:
		#		poses.append(pos)
		poses.append(pname[1:].find(_SEPPARS) + 1)  # Note: there can be a few parameters, position of the first one is requried
		# Filter out non-existent results: -1 -> 0
		poses = sorted(filter(lambda x: x >= 1, poses))
		#print('Initial poses: ', poses)
		while poses:
			pos = poses.pop(0)
			pose = poses[0] if poses else len(pname)  # Intex of the next separator or end of the name
			# Note: parameters can be any, but another suffixes are strictly specified
			# Valudate the suffix in case it is an instance or shuffle suffix
			j = 0
			if pname[pos] in (_SEPINST, _SEPPATHID, '.'):
				# Consider file pname id
				if pname[pos] == _SEPPATHID and len(pname) > pos + 1 and pname[pos + 1] == _PATHID_FILE:
					j = 1
				try:
					int(pname[pos + j + 1:pose])
				except ValueError as err:
					print('WARNING, invalid suffix or separator "{}" represents part of the path name "{}"'
						', exception: {}. Skipped.'.format(pname[pos], pname, err), file=sys.stderr)
					continue  # Check following separator candidate
			# Note: threat param separator as alvays valid
			pname = pname[:pos]
			#print('path: {}, pname: {}, pos: {}, poses: {}'.format(path, pname, pos, poses), file=sys.stderr)
			break  # Required pos is found

	return pname if not pdir else '/'.join((pdir, pname))


def parseName(path, nameonly=False):
	"""Fetch basename, instance id, algorithm params, shuffle id and path id

	path  - path to be processed WITHOUT the file extension
	nameonly  - process path as name only comonent (do not split the basedir)

	return
		basepath  - base path without suffixes, same as delPathSuffix(path, nameonly)
		insid  - instance id with separator or empty string
		apars  - algorithm parameters with separators or empty string
		shid  - shuffle id with separator or empty string
		pathid  - path id with separator or empty string

	>>> parseName('1K10^1!k7.1#1')
	('1K10', '^1', '!k7', '.1', '#1')
	>>> parseName("1K10^1.2#1") == ('1K10', '^1', '', '.2', '#1')
	True
	>>> parseName('2K5^1', False) == ('2K5', '^1', '', '', '')
	True
	>>> parseName('scp/mod/2K5.1', True) == ('scp/mod/2K5', '', '', '.1', '')
	True
	>>> parseName('1K10!k5#1') == ('1K10', '', '!k5', '', '#1')
	True
	>>> parseName('1K10!k3') == ('1K10', '', '!k3', '', '')
	True
	>>> parseName('2K5') == ("2K5", '', '', '', '')
	True
	>>> parseName('2K5.dhrh^1') == ("2K5.dhrh", '^1', '', '', '')
	True
	"""
	# Separate path into base dir and name
	if not nameonly:
		pdir, pname = os.path.split(path)
	else:
		pdir = None
		pname = path
	basename = pname
	insid = ''
	apars = ''
	shid = ''
	pathid = ''
	# Find position of the separator symbol, considering that it can't be begin of the name
	if len(pname) >= 2:
		# Note: +1 compensates start from the symbol at index 1. Also a separator can't be the first symbol
		poses = [pname[1:].rfind(c) + 1 for c in (_SEPINST, _SEPPATHID, '.')]  # Note: reverse direction to skip possible separator symbols in the name itself
		poses.append(pname[1:].find(_SEPPARS) + 1)  # Note: there can be a few parameters, position of the first one is requried
		# Filter out non-existent results: -1 -> 0
		poses = sorted(filter(lambda x: x >= 1, poses))
		#print('Initial poses: ', poses)
		while poses:
			pos = poses.pop(0)
			pose = poses[0] if poses else len(pname)  # Intex of the next separator or end of the name
			# Note: parameters can be any, but another suffixes are strictly specified
			# Valudate the suffix in case it is an instance or shuffle suffix
			j = 0
			if pname[pos] in (_SEPINST, _SEPPATHID, '.'):
				# Consider file pname id
				if pname[pos] == _SEPPATHID and len(pname) > pos + 1 and pname[pos + 1] == _PATHID_FILE:
					j = 1
				try:
					int(pname[pos + j + 1:pose])
				except ValueError as err:
					print('WARNING, invalid suffix or separator "{}" represents part of the path name "{}"'
						', exception: {}. Skipped.'.format(pname[pos], pname, err), file=sys.stderr)
					continue  # Check following separator candidate
			# Note: threat param separator as alvays valid
			if basename is pname:
				basename = pname[:pos]
			val = pname[pos:pose]
			if pname[pos] == _SEPINST:
				insid = val
			elif pname[pos] == _SEPPARS:
				apars = val
			elif pname[pos] == '.':
				shid = val
			else:
				assert pname[pos] == _SEPPATHID, 'pathid separator is expected instead of: {}'.format(val)
				pathid = val
		#print('path: {}, pname: {}, pos: {}, poses: {}'.format(path, pname, pos, poses), file=sys.stderr)

	return (basename if not pdir else '/'.join((pdir, basename)), insid, apars, shid, pathid)


class ItemsStatistic(object):
	"""Accumulates statistics over the added items of real values or their accumulated statistics"""
	def __init__(self, name, min0=1, max0=-1):
		"""Constructor

		name  - item name
		min0  - initial minimal value
		max0  - initial maximal value

		sum  - sum of all values
		sum2  - sum of squares of values
		min  - min value
		max  - max value
		count  - number of valid values
		invals  - number of invalid values
		invstats  - number of invaled statistical aggregations

		fixed  - whether all items are aggregated and summarization is performed
		avg  - average value for the finalized evaluations
		sd  - standard deviation for the finalized evaluations
			Note: sd = sqrt(var), avg +- sd covers 95% of the items in the normal distribution

		statCount  - total number of items in the aggregated stat items
		statDelta  - max stat delta (max - min)
		statSD  - average weighted (by the number of items) weighted stat SD
		"""
		self.name = name
		self.sum = 0
		self.sum2 = 0
		self.min = min0
		self.max = max0
		self.count = 0
		self.invals = 0
		self.invstats = 0

		self.fixed = False
		self.avg = None
		self.sd = None

		self.statCount = 0
		self.statDelta = None
		self.statSD = None


	def add(self, val):
		"""Add real value to the accumulating statistics"""
		assert not self.fixed, 'Only non-fixed items can be modified'
		if val is not None:
			self.sum += val
			self.sum2 += copysign(val*val, val)  # Note: copysign() also implicitly validates that val is a number
			if val < self.min:
				self.min = val
			if val > self.max:
				self.max = val
			self.count += 1
		else:
			self.invals += 1


	def addstat(self, val):
		"""Add accumulated statistics to the accumulating statistics"""
		assert not self.fixed, 'Only non-fixed items can be modified'
		if val is not None:
			self.sum += val.sum
			self.sum2 += self.sum2
			if val.min < self.min:
				self.min = val.min
			if val.max > self.max:
				self.max = val.max
			self.count += val.count
			self.invals += val.invals

			if self.statCount:
				if self.statDelta < val.max - val.min:
					self.statDelta = val.max - val.min
				if val.sd is not None:
					if self.statSD is None:
						self.statSD = 0
					self.statSD = (self.statSD * self.statCount + val.sd * val.count) / (self.statCount + val.count)
			else:
				self.statDelta = val.max - val.min
				self.statSD = val.sd
			self.statCount += val.count
		else:
			self.invstats += 1


	#def __lt__(self, stat):
	#	"""Operator <
	#
	#	stat  - comparing object
	#
	#	return  - True if the instance less than stat
	#	"""
	#	assert self.fixed and stat.fixed, 'Comparison should be called only for the fixed objects'
	#	return self.avg < stat.avg or (self.avg == stat.avg and self.sd is not None and self.sd < stat.sd)


	def fix(self):
		"""Fix (finalize) statistics accumulation and produce the summary of the results"""
		assert self.count >=0, 'Count must be non-negative'
		self.fixed = True
		self.avg = self.sum
		if self.count:
			self.avg /= float(self.count)
			if self.count >= 2:
				count = float(self.count)
				self.sd = sqrt(abs(self.sum2 * count - self.sum * self.sum)) / (count - 1)  # Note: corrected deviation for samples is employed


def envVarDefined(value, name=None, evar=None):
	"""Checks wether specified environment variable is already defined

	value  - value of the environmental variable to be checked
	name  - name of the environment var to be retrieved (required in evar is not specified)
	evar  - retrieved value of the environmental var to check inclusoin of the specified value

	return  True if the var is defined as specified, otherwise FALSE
	"""
	assert isinstance(value, str) and (name is None or isinstance(name, str)) and (
		evar is None or isinstance(evar, str)), 'Environmental vars are strings'
	if evar is None:
		assert name, 'Evnironmental variable name must be specified if the value is not provided'
		evar = os.environ.get(name, '')
	return evar and re.search('^(.+:)?{}(:.*)?$'.format(re.escape(value)), evar) is not None


def parseFloat(text):
	"""Parse float number from the text if exists and separated by non-alphabet symbols.

	return
		num  - parsed number or None
		pose  - position of the end of the match or 0

	>>> parseFloat('.3asdf')[0] is None
	True
	>>> parseFloat('0.3 asdf')[0]
	0.3
	>>> parseFloat("-324.65e-2;aset")[0] == -324.65e-2
	True
	>>> parseFloat('5.2sdf, 45')[0]
	5.0
	"""
	match = _REFLOAT.match(text)
	if match:
		num = match.group(0)
		return float(num), len(num)
	return None, 0


def parseInt(text):
	"""Parse int number from the text if exists and separated by non-alphabet symbols.

	return
		num  - parsed number or None
		pose  - position of the end of the match or 0

	>>> parseInt('3asdf')[0] is None
	True
	>>> parseInt('3 asdf')[0]
	3
	>>> parseInt("324e1;aset")[0] is None
	True
	>>> parseInt('5.2sdf, 45')[0]
	5
	"""
	match = _REINT.match(text)
	if match:
		num = match.group(0)
		return int(num), len(num)
	return None, 0


def escapePathWildcards(path):
	"""Escape wildcards in the path"""
	# TODO: Implement this manually if not supported by the current vresion of Python.
	# Though, it is not very important, because occurs extremely seldom
	return glob.escape(path) if hasattr(glob, 'escape') else path


def dirempty(dirpath):
	"""Whether specified directory is empty"""
	dirpath = escapePathWildcards(dirpath)
	if not os.path.isdir(dirpath):
		print('ERROR, Existent directory is expected instead of: ' + dirpath, file=sys.stderr)
		raise ValueError('Existent directory is expected')
	if not dirpath.endswith('/'):
		dirpath += '/'
	try:
		glob.iglob(dirpath + '*').next()
	except StopIteration:
		# Diretory is empty
		return True
	return False


def basePathExists(path):
	"""Whether there are any existent files/dirs with the specified base name.
		ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	"""
	try:
		glob.iglob(escapePathWildcards(path) + '*').next()
	except StopIteration:
		# No such files / dirs
		return False
	return True


class SyncValue(object):
	"""Interprocess synchronized value.
	Provides the single attribute: 'value', which should be used inside "with" statement
	if non-atomic operation is applied like +=.
	"""
	def __init__(self, val=None):
		"""Sync value constructor

		val  - initial value
		"""
		# Note: recursive lock occurs if normal attrib names are used because of __setattr__ definition
		object.__setattr__(self, 'value', val)
		# Private attributes
		object.__setattr__(self, '_lock', Lock())
		object.__setattr__(self, '_synced', 0)


	def __setattr__(self, name, val):
		if name != 'value':
			raise AttributeError('Attribute "{}" is not accessable'.format(name))
		if name != 'value' or object.__getattribute__(self, '_synced') > 0:
			object.__setattr__(self, name, val)
		else:
			with object.__getattribute__(self, '_lock'):
				object.__setattr__(self, name, val)


	def __getattribute__(self, name):
		if name != 'value':
			raise AttributeError('Attribute "{}" is not accessable'.format(name))
		if name != 'value' or object.__getattribute__(self, '_synced') > 0:
			return object.__getattribute__(self, name)
		with object.__getattribute__(self, '_lock'):
			return object.__getattribute__(self, name)


	def __enter__(self):
		# Do not lock when already synced
		if (not object.__getattribute__(self, '_synced')
		and not object.__getattribute__(self, '_lock').acquire()):
			raise ValueError('Lock timeout is exceeded')
		object.__setattr__(self, '_synced', object.__getattribute__(self, '_synced') + 1)
		return self


	def __exit__(self, exception_type, exception_val, trace):
		object.__setattr__(self, '_synced', object.__getattribute__(self, '_synced') - 1)
		# Unlock only when not synced
		if not object.__getattribute__(self, '_synced'):
			object.__getattribute__(self, '_lock').release()
		assert object.__getattribute__(self, '_synced') >= 0, 'Synchronization is broken'


	#def get_lock(self):
	#	"""Return synchronization lock"""
	#	self._synced = True
	#	return self._lock
	#
	#
	#def get_obj(self):
	#	self._synced = True
	#	return self._lock


def nameVersion(path, expand, synctime=None, suffix=''):
	"""Name the last path component basedon modification time and return this part

	path  - the path to be named with version.
		ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	expand  - whether to expand the path or use as it is
	synctime  - use the same time suffix for multiple paths when is not None,
		SyncValue is expected
	suffix  - suffix to be added to the backup name
	"""
	path = os.path.normpath(escapePathWildcards(path))
	name = os.path.split(path)[1]  # Extract dir of file name
	if not path:
		raise ValueError('Specified path is empty')
	# Prepend the suffix with separator
	if suffix:
		suffix = '_' + suffix
	# Check whether path exists and expand it if required
	if not os.path.exists(path):
		exists = False
		if expand:
			try:
				path = glob.iglob(path + '*').next()
				exists = True
			except StopIteration:
				pass
		if not exists:
			print('WARNING: specified path is not exist', file=sys.stderr)
			return name + suffix
	# Process existing path
	if synctime is not None:
		with synctime:
			if synctime.value is None:
				synctime.value = time.gmtime(os.path.getmtime(path))
			mtime = synctime.value
	else:
		mtime = time.gmtime(os.path.getmtime(path))
	mtime = time.strftime('_%y%m%d_%H%M%S', mtime)  # Modification time
	return ''.join((name, suffix, mtime))


def backupPath(basepath, expand=False, synctime=None, compress=True, suffix=''):  # basedir, name
	"""Backup all files and dirs starting from the specified basepath into backup/
	located in the parent dir of the basepath

	basepath  - path, last component of which (file or dir) is a template to backup
		all paths starting from it in the same location.
		ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	expand  - expand prefix, backup all paths staring from basepath, or basepath only
	synctime  - use the same time suffix for multiple paths when is not None,
		SyncValue is expected
	compress  - compress or just copy spesified paths
	suffix  - suffix to be added to the backup name

	ATTENTION: All paths are MOVED to the dedicated timestamped dir / archive
	"""
	# Check if there anything available to be backuped
	if (expand and not basePathExists(basepath)) or (not expand
	and (not os.path.exists(basepath) or (os.path.isdir(basepath) and dirempty(basepath)))):
		return
	#print('Backuping "{}"{}...'.format(basepath, 'with synctime' if synctime else ''))
	# Remove trailing path separator if exists
	basepath = os.path.normpath(escapePathWildcards(basepath))
	# Create backup/ if required
	basedir = '/'.join((os.path.split(basepath)[0], _BCKDIR))
	if not os.path.exists(basedir):
		os.mkdir(basedir)
	# Backup files
	rennmarg = 10  # Max number of renaming attempts
	basename = basedir + nameVersion(basepath, expand, synctime, suffix)  # Base name of the backup
	if compress:
		archname = basename + '.tar.gz'
		# Rename already existent archive if required
		if os.path.exists(archname):
			nametmpl = ''.join((basename, '-{}', '.tar.gz'))
			for i in range(rennmarg):
				bckname = nametmpl.format(i)
				if not os.path.exists(bckname):
					break
			else:
				print('WARNING: backup file "{}" is being rewritten'.format(bckname), file=sys.stderr)
			try:
				os.rename(archname, bckname)
			except StandardError as err:
				print('WARNING: removing backup file "{}", as its renaming failed: {}'
					.format(archname, err), file=sys.stderr)
				os.remove(archname)
		# Move data to the archive
		with tarfile.open(archname, 'w:gz', bufsize=64*1024, compresslevel=6) as tar:
			for path in glob.iglob(basepath + ('*' if expand else '')):
				tar.add(path, arcname=os.path.split(path)[1])
				# Delete the archived paths
				if os.path.isdir(path):
					shutil.rmtree(path)
				else:
					os.remove(path)
	else:
		# Rename already existent backup if required
		if os.path.exists(basename):
			nametmpl = basename + '-{}'
			for i in range(rennmarg):
				bckname = nametmpl.format(i)
				if not os.path.exists(bckname):
					break
			else:
				print('WARNING: backup dir "{}" is being rewritten'.format(bckname), file=sys.stderr)
				shutil.rmtree(bckname)
			try:
				os.rename(basename, bckname)
			except StandardError as err:
				print('WARNING: removing backup dir "{}", as its renaming failed: {}'
					.format(basename, err), file=sys.stderr)
				shutil.rmtree(basename)
		# Move data to the backup
		if not os.path.exists(basename):
			os.mkdir(basename)
		for path in glob.iglob(basepath + ('*' if expand else '')):
			shutil.move(path, '/'.join((basename, os.path.split(path)[1])))


if __name__ == '__main__':
	"""Doc tests execution"""
	import doctest
	#doctest.testmod()  # Detailed tests output
	flags = doctest.REPORT_NDIFF | doctest.REPORT_ONLY_FIRST_FAILURE
	failed, total = doctest.testmod(optionflags=flags)
	if failed:
		print("Doctest FAILED: {} failures out of {} tests".format(failed, total))
	else:
		print('Doctest PASSED')
