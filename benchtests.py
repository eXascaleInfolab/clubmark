#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
:Description:  Unit tests for the modular benchmark (Python Clustering Algorithms BenchMarking Framework).

:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>
:Date: 2018-06
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import unittest
import os
import glob
import tempfile
import shutil
# import sys
# from sys import executable as PYEXEC  # Full path to the current Python interpreter
from benchutils import SyncValue, nameVersion, tobackup
from benchapps import preparePath


class UtilsTest(unittest.TestCase):
	"""Tests for the Benchmark utilities"""
	__bdir = None  # Base directory for the tests


	@classmethod
	def setUpClass(cls):
		cls.__bdir = tempfile.mkdtemp(prefix='tmp_bmtests')


	@classmethod
	def tearDownClass(cls):
		if cls.__bdir is not None:
			shutil.rmtree(cls.__bdir)


	def test_nameVersion(self):
		"""test_nameVersion() tests"""
		# Test for the non-existent name
		randname = 's;35>.ds8u9'
		stval0 = None
		synctime = SyncValue(stval0)
		suffix = 'suf'  # Versioning suffix
		self.assertFalse(os.path.exists(randname))
		self.assertEqual(nameVersion(randname, False), randname)
		self.assertEqual(nameVersion(randname, False, suffix='suf'), '_'.join((randname, suffix)))
		# Consider path expansion with for the non-existent path
		self.assertRaises(StopIteration, next, glob.iglob(randname + '*'))
		self.assertEqual(nameVersion(randname, True), randname)
		# Check with Synctime
		self.assertEqual(nameVersion(randname, True, synctime), randname)
		self.assertEqual(synctime.value, stval0
			, 'synctime.value should not be changed for the non-existent path')
		# Check path expansion to the existent path
		path = next(glob.iglob('*'))
		self.assertNotEqual(nameVersion(path, True), path
			, 'Unexistent versioned name is expected for the existent path')
		# Check with Synctime
		# None value
		self.assertNotEqual(nameVersion(path, True, synctime), path)
		self.assertNotEqual(synctime.value, stval0
			, 'synctime.value should be initialized for the existent path')
		self.assertIn('_' + suffix, nameVersion(path, True, synctime, suffix=suffix))
		# Non None value
		stval = synctime.value  # Non None stval should be permanent
		self.assertNotEqual(nameVersion(path, True, synctime), path)
		self.assertEqual(synctime.value, stval, 'synctime.value should be permanent')


	# def test_tobackup(self):
	# 	# Create tmp dir to test backuping
	# 	bkdir = tempfile.mkdtemp(prefix='tmp_bmtests')
	# 	try:
	# 		clsdir
	# 		tobackup()
	# 	finally:
	# 		shutil.rmtree(bkdir)




if __name__ == '__main__':
	unittest.main()
	# if unittest.main().result:  # verbosity=2
	# 	print('Try to re-execute the tests (hot run) or set x2-3 larger TEST_LATENCY')
