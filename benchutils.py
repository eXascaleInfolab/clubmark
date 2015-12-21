#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr:  Common routines for the benchmarking framework.

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-11
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import sys
import os
import glob
import shutil
import time
import tarfile
import re

from multiprocessing import Lock


_BCKDIR = 'backup/'  # Backup directory
_REFLOAT = re.compile('[-+]?\d+\.?\d*([eE][-+]?\d+)?(?=\W)')  # Regular expression to parse float
_REINT = re.compile('[-+]?\d+(?=\W)')  # Regular expression to parse int


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
	return glob.escape(path) if hasattr(glob, 'escape') else path


def dirempty(dirpath):
	"""Whether specified directory is empty"""
	dirpath = escapePathWildcards(dirpath)
	assert os.path.isdir(dirpath), 'Existent directory is expected'
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
			print('WARNING: specified path is not exist empty', file=sys.stderr)
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


if __name__ == "__main__":
	"""Doc tests execution"""
	import doctest
	flags = doctest.REPORT_NDIFF | doctest.REPORT_ONLY_FIRST_FAILURE
	failed, total = doctest.testmod(optionflags=flags)
	if failed:
		print("FAILED: {} failures out of {} tests".format(failed, total))
	else:
		print('PASSED')
