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

from sys import executable as pyexec  # Full path to the current Python interpreter
from multiprocessing import Lock


_bckdir = 'backup/'  # Backup directory


def escapeWildcards(path):
	"""Escape wildcards in the path"""
	return glob.escape(path) if hasattr(glob, 'escape') else path


def dirempty(dirpath):
	"""Whether specified directory is empty"""
	dirpath = escapeWildcards(dirpath)
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
		glob.iglob(escapeWildcards(path) + '*').next()
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


def nameVersion(path, expand, synctime=None):
	"""Name the last path component basedon modification time and return this part

	path  - the path to be named with version.
		ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	expand  - whether to expand the path or use as it is
	synctime  - use the same time suffix for multiple paths when is not None,
		SyncValue is expected
	"""
	path = os.path.normpath(escapeWildcards(path))
	name = os.path.split(path)[1]  # Extract dir of file name
	if not path:
		raise ValueError('Specified path is empty')
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
			return name
	# Process existing path
	if synctime is not None:
		with synctime:
			if synctime.value is None:
				synctime.value = time.gmtime(os.path.getmtime(path))
			mtime = synctime.value
	else:
		mtime = time.gmtime(os.path.getmtime(path))
	mtime = time.strftime('_%y%m%d_%H%M%S', mtime)  # Modification time
	return name + mtime


def backupPath(basepath, expand=False, synctime=None, compress=True):  # basedir, name
	"""Backup all files and dirs starting from the specified basepath into backup/
	located in the parent dir of the basepath

	basepath  - path, last component of which (file or dir) is a template to backup
		all paths starting from it in the same location.
		ATTENTION: the basepathis escaped, i.e. wildcards are not supported
	expand  - expand prefix, backup all paths staring from basepath, or basepath only
	synctime  - use the same time suffix for multiple paths when is not None,
		SyncValue is expected
	compress  - compress or just copy spesified paths

	ATTENTION: All paths are MOVED to the dedicated timestamped dir / archive
	"""
	# Check if there anything available to be backuped
	if (expand and not basePathExists(basepath)) or (not expand and not os.path.exists(basepath)):
		return
	#print('Backuping "{}"{}...'.format(basepath, 'with synctime' if synctime else ''))
	# Remove trailing path separator if exists
	basepath = os.path.normpath(escapeWildcards(basepath))
	# Create backup/ if required
	basedir = '/'.join((os.path.split(basepath)[0], _bckdir))
	if not os.path.exists(basedir):
		os.mkdir(basedir)
	# Backup files
	rennmarg = 10  # Max number of renaming attempts
	if compress:
		archname = ''.join((basedir, nameVersion(basepath, expand, synctime), '.tar.gz'))
		# Rename already existent archive if required
		if os.path.exists(archname):
			nametmpl = ''.join((basedir, nameVersion(basepath, expand, synctime), '-{}', '.tar.gz'))
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
		basedir = ''.join((basedir, nameVersion(basepath, expand, synctime), '/'))
		# Rename already existent backup if required
		if os.path.exists(basedir):
			nametmpl = basedir + '-{}'
			for i in range(rennmarg):
				bckname = nametmpl.format(i)
				if not os.path.exists(bckname):
					break
			else:
				print('WARNING: backup dir "{}" is being rewritten'.format(bckname), file=sys.stderr)
				shutil.rmtree(bckname)
			try:
				os.rename(basedir, bckname)
			except StandardError as err:
				print('WARNING: removing backup dir "{}", as its renaming failed: {}'
					.format(basedir, err), file=sys.stderr)
				shutil.rmtree(basedir)
		# Move data to the backup
		if not os.path.exists(basedir):
			os.mkdir(basedir)
		for path in glob.iglob(basepath + ('*' if expand else '')):
			shutil.move(path, basedir + os.path.split(path)[1])