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


def secondsToHms(seconds):
	"""Convert seconds to hours, mins, secs
	
	seconds  - seconds to be converted
	
	return hours, mins, secs
	"""
	hours = int(seconds / 3600)
	mins = int((seconds - hours * 3600) / 60)
	secs = seconds - hours * 3600 - mins * 60
	return hours, mins, secs


def nameVersion(path):
	"""Name the last path component basedon modification time and return this part"""
	if not path:
		print('WARNING: specified path is empty', file=sys.stderr)
		return
	mtime = time.strftime('_%y%m%d_%M%S', time.gmtime(os.path.getmtime(path)))  # Modification time
	name = os.path.split(os.path.normpath(path))[1]  # Extract dir of file name
	return name + mtime
	
	
def backupPath(basepath, compress=True):  # basedir, name
	"""Backup all files and dirs started from the specified name in the specified path
	into backup/ dir inside the specified path
	
	basepath  - path, last component of which (file or dir) is a template to backup
		all paths starting from it in the same location
	compress  - compress or just copy spesified paths
	
	ATTENTION: All paths are MOVED to the dedicated timestamped dir / archive
	"""
	# Check if there anything available to be backuped
	if not os.path.exists(basepath):
		return
	# Remove trailing path separator if exists
	basepath = os.path.normpath(basepath)
	# Create backup/ if required
	basedir, basename = os.path.split(basepath)
	basedir += '/backup/'
	if not os.path.exists(basedir):
		os.mkdir(basedir)
	# Backup files
	rennmarg = 10  # Max number of renaming attempts
	if compress:
		archname = ''.join((basedir, nameVersion(basepath), '.tar.gz'))
		# Rename already existent archive if required
		if os.path.exists(archname):
			nametmpl = ''.join((basedir, nameVersion(basepath), '-{}', '.tar.gz'))
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
			for path in glob.iglob(basepath + '*'):
				tar.add(path, arcname=os.path.split(path)[1])
				# Delete the archived paths
				if os.path.isdir(path):
					shutil.rmtree(path)
				else:
					os.remove(path)
	else:
		basedir = ''.join((basedir, nameVersion(basepath), '/'))
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
		for path in glob.iglob(basepath + '*'):
			shutil.move(path, basedir + os.path.split(path)[1])