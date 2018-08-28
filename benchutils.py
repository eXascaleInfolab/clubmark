#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
:Description:  Common routines of the modular benchmark (Python Clustering Algorithms BenchMark).

:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
:Date: 2015-11
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import sys
import os
import glob
import shutil
import time
import tarfile
import re

from multiprocessing import RLock, Value
from math import sqrt, copysign
from calendar import timegm  # time.struct_time -> float (seconds since the epoch)

_PREFINTERNDIR = '-'  # Internal directory prefix
_BCKDIR = _PREFINTERNDIR + 'backup/'  # Backup directory
ORIGDIR = _PREFINTERNDIR + 'orig/'  # Backup directory
_REFLOAT = re.compile(r'[-+]?\d+\.?\d*([eE][-+]?\d+)?(?=\W)')  # Regular expression to parse float
_REINT = re.compile(r'[-+]?\d+(?=\W)')  # Regular expression to parse int
SEPPARS = '!'  # Network parameters separator, must be a char
SEPINST = '^'  # Network instances separator, must be a char
SEPSHF = '%'  # Network shuffles separator, must be a char; ~
SEPPATHID = '#'  # Network path id separator (to distinguish files with the same name from different dirs in the results), must be a char
SEPSUBTASK = '>'  # Sub-task separator
UTILDIR = 'utils/'  # Utilities directory with external applications for quality evaluation and other things
ALGSDIR = 'algorithms/'  # Default directory of the benchmarking algorithms
TIMESTAMP_START = time.gmtime()  # struct_time
TIMESTAMP_START_STR = time.strftime('%Y-%m-%d %H:%M:%S', TIMESTAMP_START)
TIMESTAMP_START_HEADER = ' '.join(('# ---', TIMESTAMP_START_STR, '-'*32))
PREFEXEC = 'exec'  # Prefix of the executing application / algorithm
# Maximal number of the levels considered for the evaluation in the multi-scale or hierarchical clustering
ALEVSMAX = 10  # Use 10 scale levels as in Ganxis by default
ALGLEVS = {}  # Max number of levels for the algorithm if does not correspond to the ALEVSMAX, dict(str: uint16)
_STATIC_TRACE = set()  # A set of markers for the static tracing (once per multiple calls)

# Consider Python2
if not hasattr(glob, 'escape'):
	# r'(?<!/)[?*[]'
	_RE_GLOBESC = re.compile(r'[?*[]')  # Escape all special characters ('?', '*' and '[') not in the UNC (path)

	def globesc(mobj):
		r"""Escape the special symbols ('?', '*' and '[') not in UNC (path)

		Args:
			mobj (re.MatchObject): matched RE object (not None)

		Returns: replacement string

		>>> globesc(re.match('\?', '?'))
		'[?]'
		>>> globesc(re.match('a', 'b'))
		''
		"""
		if mobj is None:
			return ''
		return mobj.group().join(('[', ']')) if mobj.group() else ''

_DEBUG_TRACE = False  # Trace start / stop and other events to stderr


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


# Define viewXXX functions to efficiently traverse items of dictionaries in both Python 2 and 3
# Note: depends on viewMethod()
try:
	# External package: pip install future
	from future.utils import viewitems, viewkeys, viewvalues  #pylint: disable=W0611
except ImportError:
	viewitems = lambda dct: viewMethod(dct, 'items')()  #pylint: disable=W0611
	viewkeys = lambda dct: viewMethod(dct, 'keys')()  #pylint: disable=W0611
	viewvalues = lambda dct: viewMethod(dct, 'values')()  #pylint: disable=W0611


def staticTrace(func, msg, marker=None, fout=sys.stdout):
	"""Trace the message once independently on the number of calls for each marker

	ATTENTION: If several functions share a marker then only a single trace will be issues for all of them.
		So, typically, a marker should either include the function name or have the default value.

	msg: str  - message to be prepended with the WARNING prefix and traced to the fout
	func: str  - name of the function, which issued this message
	marker  - a marker for the unique tracing, only once a message with each marker is shown,
		None value is automatically replaced with the value of func to have a single trace per each function
	fout: file  - output file
	"""
	if marker is None:
		marker = func
	if marker not in _STATIC_TRACE:
		print('WARNING {}(), {}'.format(func, msg), file=fout)
		_STATIC_TRACE.add(marker)


def secDhms(seconds):
	"""Convert seconds to duration of days/hours/minuts/secs in the string format

	seconds: float, >=0  - seconds to be converted

	return  duration: str  - resulting duration in the format:
		[<days:int>d][<hours:int>h][<minutes:int>m][<seconds:float>]

	>>> secDhms(10)
	'10'
	>>> secDhms(60)
	'1m'
	>>> secDhms(65.7818934)
	'1m5.782'
	>>> secDhms(3725)
	'1h2m5'
	>>> secDhms(50*3600)
	'2d2h'
	>>> secDhms(24*3600+2)
	'1d0h0m2'
	"""
	days = int(seconds // (24 * 3600))
	seconds -= days * 24 * 3600
	hours = int(seconds // 3600)
	seconds -= hours * 3600
	mins = int(seconds // 60)
	secs = seconds - mins * 60

	res = '' if not days else str(days) + 'd'
	if not (hours or mins or secs):
		return res
	if res or hours:
		res += str(hours) + 'h'
	if not (mins or secs):
		return res
	if res or mins:
		res += str(mins) + 'm'
	return res if not secs else '{}{:.4g}'.format(res, secs)


def dhmsSec(dhms):
	"""Convert dhms string duration to seconds

	dhms  - duration given as string in the format:
		[<days:int>d][<hours:int>h][<minutes:int>m][<seconds:float>]

	return  secs: uint  - seconds, unsigned int

	>>> dhmsSec('10')
	10
	>>> dhmsSec('1m')
	60
	>>> dhmsSec('1m5.782')
	65.782
	>>> dhmsSec('1h2m5')
	3725
	>>> dhmsSec('2d2h')
	180000
	>>> dhmsSec('1d0h0m2')
	86402
	"""
	sec = 0
	# Parse days
	isep = dhms.find('d')
	ibeg = 0
	if isep != -1:
		sec += int(dhms[:isep]) * 24 * 3600
		ibeg = isep + 1
	# Parse hours
	isep = dhms.find('h', ibeg)
	if isep != -1:
		sec += int(dhms[ibeg:isep]) * 3600
		ibeg = isep + 1
	# Parse mins
	isep = dhms.find('m', ibeg)
	if isep != -1:
		sec += int(dhms[ibeg:isep]) * 60
		ibeg = isep + 1
	# Parse secs
	dhms = dhms[ibeg:]
	if dhms:
		if dhms.find('.') == -1:
			sec += int(dhms)
		else:
			sec += float(dhms)
	return sec


def timeSeed():
	"""Generate time seed as uint64_t

	>>> timeSeed() > 20170526191034 and len(str(timeSeed())) == len('20170526191034')
	True
	"""
	t = time.gmtime()
	return t.tm_sec + 100*(t.tm_min + 100*(t.tm_hour + 100*(t.tm_mday + 100*(t.tm_mon + 100*t.tm_year))))   # 2017'05'26'21'10'34


def delPathSuffix(path, nameonly=False):
	"""Extracts base of the path skipping instance, shuffling and pathid suffixes

	path  - path to be processed WITHOUT the file extension
	nameonly  - process path as name only component (do not split the basedir)

	return  base of the path without suffixes

	>>> delPathSuffix('1K10!k7^1%1#1')
	'1K10'
	>>> delPathSuffix('1K10!k7^1%1#1', True)
	'1K10'
	>>> delPathSuffix("1K10^1%2#f1") == '1K10'
	True
	>>> delPathSuffix('../syntnets/networks/5K75^1') == '../syntnets/networks/5K75'
	True
	>>> delPathSuffix('2K5^1', False) == '2K5'
	True
	>>> delPathSuffix('scp/mod/2K5%1', True) == 'scp/mod/2K5'
	True
	>>> delPathSuffix('1K10!k5#1') == '1K10'
	True
	>>> delPathSuffix('1K10!k3') == '1K10'
	True
	>>> delPathSuffix('2K5') == "2K5"
	True
	>>> delPathSuffix('2K5.dhrh^1') == "2K5.dhrh"
	True

	#>>> delPathSuffix('2K5.dhrh^1%1.cnl', True) == '2K5.dhrh'
	#True
	#>>> delPathSuffix('scp/mod/1K10^1!k5#1.mod') == 'scp/mod/1K10'
	#True
	"""
	path = path.rstrip('/')  # Allow dir name processing (at least for the path id extraction)
	# Separate path into base dir and name
	if not nameonly:
		pdir, pname = os.path.split(path)
	else:
		pdir = None
		pname = path
	# Find position of the separator symbol, considering that it can't be begin of the name
	if len(pname) >= 2:
		# Note: +1 compensates start from the symbol at index 1. Also a separator can't be the first symbol
		poses = [pname[1:].rfind(c) + 1 for c in (SEPINST, SEPPATHID, SEPSHF)]  # Note: reverse direction to skip possible separator symbols in the name itself
		## Consider possible extension of the filename
		## Note: this handling is fine, but not reliable (part of the name of file extension can be handled as a shuffle index
		#pos = pname[1:].rfind('.') + 1
		#if pos and pos > max(poses):
		#	poses.append(pos)
		#	pos = pname[1:pos].rfind('.') + 1
		#	if pos:
		#		poses.append(pos)
		poses.append(pname[1:].find(SEPPARS) + 1)  # Note: there can be a few parameters, position of the first one is required
		# Filter out non-existent results: -1 -> 0
		poses = sorted(filter(lambda x: x >= 1, poses))
		#print('Initial poses: ', poses)
		while poses:
			pos = poses.pop(0)
			pose = poses[0] if poses else len(pname)  # Index of the next separator or end of the name
			# Note: parameters can be any, but another suffixes are strictly specified
			# Validate the suffix in case it is an instance or shuffle suffix
			if pname[pos] in (SEPINST, SEPPATHID, SEPSHF):
				try:
					int(pname[pos + 1:pose])
				except ValueError as err:
					print('WARNING, invalid suffix or separator "{}" represents part of the path name "{}"'
						', exception: {}. Skipped.'.format(pname[pos], pname, err), file=sys.stderr)
					continue  # Check following separator candidate
			# Note: threat param separator as always valid
			pname = pname[:pos]
			#print('path: {}, pname: {}, pos: {}, poses: {}'.format(path, pname, pos, poses), file=sys.stderr)
			break  # Required pos is found

	return pname if not pdir else '/'.join((pdir, pname))


def parseName(path, nameonly=False):
	"""Fetch basename, instance id, algorithm params, shuffle id and path id
	NOTE: the fetched components are prepended with their separators

	path  - path to be processed WITHOUT the file extension
	nameonly  - process path as name only component (do not split the basedir)

	return
		basepath  - base path without suffixes, same as delPathSuffix(path, nameonly)
		apars  - algorithm parameters with separators or empty string
		insid  - instance id with separator or empty string
		shid  - shuffle id with separator or empty string
		pathid  - path id with separator or empty string

	>>> parseName('1K10!k7^1%1#1')
	('1K10', '!k7', '^1', '%1', '#1')
	>>> parseName("1K10^1%2#1") == ('1K10', '', '^1', '%2', '#1')
	True
	>>> parseName('2K5^1', False) == ('2K5', '', '^1', '', '')
	True
	>>> parseName('scp/mod/2K5%1', True) == ('scp/mod/2K5', '', '', '%1', '')
	True
	>>> parseName('1K10!k3') == ('1K10', '!k3', '', '', '')
	True
	>>> parseName('2K5') == ("2K5", '', '', '', '')
	True
	>>> parseName('2K5.dhrh^1') == ("2K5.dhrh", '', '^1', '', '')
	True
	"""
	path = path.rstrip('/')  # Allow dir name processing (at least for the path id extraction)
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
		poses = [pname[1:].rfind(c) + 1 for c in (SEPINST, SEPSHF, SEPPATHID)]  # Note: reverse direction to skip possible separator symbols in the name itself
		poses.append(pname[1:].find(SEPPARS) + 1)  # Note: there can be a few parameters, position of the first one is required
		# Filter out non-existent results: -1 -> 0
		poses = sorted(filter(lambda x: x >= 1, poses))
		#print('Initial poses: ', poses)
		while poses:
			pos = poses.pop(0)
			pose = poses[0] if poses else len(pname)  # Index of the next separator or end of the name
			# Note: parameters can be any, but another suffixes are strictly specified
			# Validate the suffix in case it is an instance or shuffle suffix
			if pname[pos] in (SEPINST, SEPSHF, SEPPATHID):
				try:
					int(pname[pos + 1:pose])
				except ValueError as err:
					print('WARNING, invalid suffix or separator "{}" represents part of the path name "{}"'
						', exception: {}. Skipped.'.format(pname[pos], pname, err), file=sys.stderr)
					continue  # Check following separator candidate
			# Note: threat param separator as always valid
			if basename is pname:
				basename = pname[:pos]
			val = pname[pos:pose]
			if pname[pos] == SEPPARS:
				apars = val
			elif pname[pos] == SEPINST:
				insid = val
			elif pname[pos] == SEPSHF:
				shid = val
			else:
				assert pname[pos] == SEPPATHID, 'pathid separator is expected instead of: {}'.format(val)
				pathid = val
		#print('path: {}, pname: {}, pos: {}, poses: {}'.format(path, pname, pos, poses), file=sys.stderr)

	return (basename if not pdir else '/'.join((pdir, basename)), apars, insid, shid, pathid)


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
		invstats  - number of invalid statistical aggregations

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
		assert self.count >= 0, 'Count must be non-negative'
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
		assert name, 'Environmental variable name must be specified if the value is not provided'
		evar = os.environ.get(name, '')
	return evar and re.search('^(.+:)?{}(:.*)?$'.format(re.escape(value)), evar) is not None


def funcToAppName(funcname):
	"""Fetch name of the execution application by the function name

	funcname  - name of the executing function

	returns  - name of the algorithm
	"""
	assert funcname.startswith(PREFEXEC), 'Executing application is expected instead of "{}"'.format(funcname)
	return funcname[len(PREFEXEC):]  # .lower()


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
	"""Escape all special characters ('?', '*' and '[') not in the UNC path

	path  - the path tobescaped

	return  escaped path

	>>> escapePathWildcards('//?Quo va?dis[?].txt')
	'//[?]Quo va[?]dis[[][?]].txt'
	"""
	return glob.escape(path) if hasattr(glob, 'escape') else re.sub(_RE_GLOBESC, globesc, path)


def dirempty(dirpath):
	"""Whether specified directory is empty"""
	dirpath = escapePathWildcards(dirpath)
	if not os.path.isdir(dirpath):
		print('ERROR, Existent directory is expected instead of: ', dirpath, file=sys.stderr)
		raise ValueError('Existent directory is expected')
	if not dirpath.endswith('/'):
		dirpath += '/'
	try:
		next(glob.iglob(dirpath + '*'))
	except StopIteration:
		# Directory is empty
		return True
	return False


def basePathExists(path):
	"""Whether there are any existent files/dirs with the specified base name.
	ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	"""
	try:
		next(glob.iglob(escapePathWildcards(path) + '*'))
	except StopIteration:
		# No such files / dirs
		return False
	return True


class SyncValue(object):
	"""Interprocess synchronized value.
	Provides a single attribute 'value' that should be used inside "with" statement.

	ATTENTION: SyncValue() is initialized only once (on construction) and the assigned value can not be changed,
	this value is COPIED to to the local context of other processes and access to the local copies of the value
	is assumed to be performed via the shared RLock.
	NOTE: Use multiprocessing.sharedctypes.Value() or ...synchronized()if a synchronized variable is required.

	>>> sv = SyncValue(None); print(sv.value)
	None
	>>> with sv: sv.value = 1; print(sv.value)
	Traceback (most recent call last):
	...
	ValueError: Sync value can be set only once (on the initialization)
	>>> with sv: print(sv.value);
	None
	"""
	def __init__(self, val=None):
		"""Sync value constructor

		val  - initial value
		"""
		# Note: recursive lock occurs if normal attribute names are used because of __setattr__ definition
		object.__setattr__(self, 'value', val)
		# Private attributes
		object.__setattr__(self, '_lock', RLock())  # Use reentrant lock (can be acquired multiple times by the same thread)


	def __setattr__(self, name, val):
		if name != 'value':
			raise AttributeError('Attribute "{}" is not accessible'.format(name))
		raise ValueError('Sync value can be set only once (on the initialization)')
		# with object.__getattribute__(self, '_lock'):
		# 	object.__setattr__(self, name, val)


	def __getattribute__(self, name):
		if name != 'value':
			raise AttributeError('Attribute "{}" is not accessible'.format(name))
		with object.__getattribute__(self, '_lock'):
			return object.__getattribute__(self, name)


	def __enter__(self):
		if not object.__getattribute__(self, '_lock').acquire():
			raise ValueError('Lock timeout is exceeded')
		return self


	def __exit__(self, exception_type, exception_val, trace):
		object.__getattribute__(self, '_lock').release()


	def get_lock(self):
		"""Get synchronization lock"""
		return object.__getattribute__(self, '_lock')


	#def get_obj(self):
	#	self._synced = True
	#	return self._lock


def syncedTime(value=None, lock=True):
	"""Modifiable synchronized time

	value: time.struct_time  - value to be stored in the optionally synchronized shared memory.
		None is replaced with time.gmtime(0), which is stored as float value 0.
	lock: Lock, RLock or bool  - lock if required, True means RLock

	ATTENTION: shared time of ctypes.c_double rather than Value is yielded without the lock,
		both c_double and Value have the .value attribute.
	"""
	assert value is None or isinstance(value, time.struct_time), 'Invalid value type: ' + type(value).__name__
	return Value('d', 0 if value is None else timegm(value), lock=lock)  # 'd' - double (f64): https://docs.python.org/2/library/array.html


def nameVersion(path, expand, synctime=None, suffix=''):
	"""Name the last path component based on modification time and returns this part

	path  - the path to be named with version.
		ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	expand  - threat path as a prefix and expend it to the first matching item (file/dir)
	synctime: Value(time: float) or c_double  - use the same time suffix for multiple paths when is not None
	suffix  - suffix to be added to the backup name before the time suffix
	"""
	# Note: normpath() may change semantics in case symbolic link is used with parent dir:
	# base/linkdir/../a -> base/a, which might be undesirable
	path = escapePathWildcards(path).rstrip('/')  # os.path.normpath(escapePathWildcards(path))
	if not path:
		raise ValueError('Specified path is empty')
	name = os.path.split(path)[1]  # Extract dir of file name
	# Prepend the suffix with separator
	if suffix:
		suffix = '_' + suffix
	# Check whether path exists and expand it if required
	if not os.path.exists(path):
		exists = False
		if expand:
			try:
				path = next(glob.iglob(path + '*'))
				exists = True
			except StopIteration:
				pass
		if not exists:
			# print('WARNING nameVersion(), specified path does not exist: ' + path)
			return name + suffix
	# Process existing path
	if synctime is not None:
		# Note: Value is not a class but has .get_lock() unlike c_double
		if hasattr(synctime, 'get_lock'):
			with synctime.get_lock():
				if not synctime.value:
					synctime.value = os.path.getmtime(path)
		elif not synctime.value:
			synctime.value = os.path.getmtime(path)
		mtime = synctime.value
	else:
		mtime = os.path.getmtime(path)
	assert (synctime is None or hasattr(synctime, 'value')) and isinstance(mtime, float
		), 'Unexpected type of the argument, synctime: {}, mtime: {}'.format(
		type(synctime).__name__, type(mtime).__name__)
	mtstr = time.strftime('_%y%m%d_%H%M%S', time.gmtime(mtime))  # Modification time
	return ''.join((name, suffix, mtstr))


def tobackup(basepath, expand=False, synctime=None, compress=True, xsuffix='', move=True, relpath=True):  # basedir, name
	"""MOVE or copy all files and dirs starting from the specified basepath into _BCKDIR
	located in the parent dir of the basepath with optional compression.

	basepath: str  - path, last component of which (file or dir) is a name for the backup
		ATTENTION: the basepath is escaped, i.e. wildcards are NOT supported
	expand: bool  - expand prefix, back up all paths staring from basepath VS basepath only
	synctime: Value(time:float or c_double  - use the same time suffix for multiple paths if not None
	compress: bool  - compress or just copy spesified paths
	xsuffix: str  - extra suffix to be added to the backup name before the time suffix
	move: bool  - whether to move or copy the data to the backup
	relpath: bool  - convert the basepath to the relative one to its parent dir,
		which makes the archive portable to other machines

	return  bckpath: str  - path of the made archive / backup dir or None
	"""
	# Check if there anything available to be backed up
	if (expand and not basePathExists(basepath)) or (not expand
	and (not os.path.exists(basepath) or (os.path.isdir(basepath) and dirempty(basepath)))):
		return None
	#print('Backuping "{}"{}...'.format(basepath, 'with synctime' if synctime else ''))
	# Remove trailing path separator if exists
	# Note: normpath() may change semantics in case symbolic link is used with parent dir:
	# base/linkdir/../a -> base/a, which might be undesirable
	basepath = escapePathWildcards(basepath).rstrip('/')  # os.path.normpath(escapePathWildcards(basepath))
	# Create the backup if required
	basedir, srcname = os.path.split(basepath)  # ATTENTION: basedir might be empty
	# Consider relative path to current dir to not write to the root (/)
	if not basedir:  # ATTENTION: required independently on the value of relpath
		basedir = '.'
		basepath = './' + basepath
	# origdir = ORIGDIR if not basedir else '/'.join((basedir, ORIGDIR))
	# bckdir = _BCKDIR if not basedir else '/'.join((basedir, _BCKDIR))
	origdir = '/'.join((basedir, ORIGDIR))
	bckdir = '/'.join((basedir, _BCKDIR))
	if not os.path.exists(bckdir):
		os.mkdir(bckdir)
	# Backup files
	basename = bckdir + nameVersion(basepath, expand, synctime, xsuffix)  # Base name of the backup
	bckname = '-'.join((basename, str(timeSeed())))
	# Consider orig dir if required
	basepaths = [basepath]
	origname = origdir + srcname
	if (expand and basePathExists(origname)) or (not expand and os.path.exists(origname)):
		basepaths.append(origname)
	# print('>> tobackup(), origname:', origname, ', expand:', expand, 'basePathExists(origname):'
	# 	, basePathExists(origname), ', basepaths:', basepaths)
	if compress:
		archname = basename + '.tar.gz'
		# Rename already existent archive if required
		if os.path.exists(archname):
			bckname += '.tar.gz'
			if os.path.exists(bckname):
				print('WARNING, backup file "{}" is being rewritten'.format(bckname), file=sys.stderr)
			try:
				os.rename(archname, bckname)
			except OSError as err:
				print('WARNING, removing old backup file "{}", as its renaming failed: {}'
					.format(archname, err), file=sys.stderr)
				os.remove(archname)
		# Move data to the archive
		with tarfile.open(archname, 'w:gz', bufsize=128*1024, compresslevel=6) as tar:
			for basesrc in basepaths:
				for path in glob.iglob(basesrc + ('*' if expand else '')):
					# Skip empty dirs, which should be RETAINED (not moved) as they might be
					# just created for the batch backup of other paths
					if os.path.isdir(path) and dirempty(path):
						continue
					# print('>> tobackup(), Archiving: ', path, ', basesrc: ', basesrc)
					if relpath:
						# Omit the basedir to have relative path
						tar.add(path, path[len(basedir) + 1:])
					else:
						tar.add(path)
					# Delete the archived paths if required
					if move:
						#if _DEBUG_TRACE:
						#	print('>> moving path: ', path, file=sys.stderr)
						if os.path.isdir(path) and not os.path.islink(path):
							shutil.rmtree(path)
						else:
							os.remove(path)
		return archname
	else:
		# Rename already existent backup if required
		if os.path.exists(basename):
			if os.path.exists(bckname):
				print('WARNING, backup dir "{}" is being rewritten'.format(bckname), file=sys.stderr)
				shutil.rmtree(bckname)
			try:
				os.rename(basename, bckname)
			except OSError as err:
				print('WARNING, removing old backup dir "{}", as its renaming failed: {}'
					.format(basename, err), file=sys.stderr)
				shutil.rmtree(basename)
		# Move data to the backup
		if not os.path.exists(basename):
			os.mkdir(basename)
		sbasedir = os.path.split(basepath)[0]  # Base src dir
		for basesrc in basepaths:
			for path in glob.iglob(basesrc + ('*' if expand else '')):
				# Skip empty dirs, which should be RETAINED (not moved) as they might be
				# just created for the batch backup of other paths
				if os.path.isdir(path) and dirempty(path):
					continue
				bckop = shutil.move if move else (shutil.copy2 if
					os.path.islink(path) or not os.path.isdir() else shutil.copytree)
				# Destination depending on basesrc: dst VS ORIGDIR/dst
				bckop(path, bckdir + path.replace(sbasedir, '', 1))
		return basename


if __name__ == '__main__':
	# Doc tests execution
	import doctest
	#doctest.testmod()  # Detailed tests output
	flags = doctest.REPORT_NDIFF | doctest.REPORT_ONLY_FIRST_FAILURE
	failed, total = doctest.testmod(optionflags=flags)
	if failed:
		print("Doctest FAILED: {} failures out of {} tests".format(failed, total))
	else:
		print('Doctest PASSED')
