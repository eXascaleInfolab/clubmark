#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
:Description: Evaluation of results produced by each executed application.

	Resulting cluster/community structure is evaluated using extrinsic (NMI, NMI_s)
	and intrinsic (Q - modularity) measures considering overlaps.


	def execQmeasure(execpool, qualsaver, smeta, qparams, cfpath, inpfpath, asym=False
	, timeout=0, seed=None, task=None, workdir=UTILDIR, revalue=True):
		Quality measure executor (stub)

		xmeasures  - various extrinsic quality measures

		execpool: ExecPool  - execution pool
		qualsaver: QualitySaver  - quality results saver (persister)
		smeta: SMeta - serialization meta data
		qparams: iterable(str)  - quality measures parameters (arguments excluding the clustering and network files)
		cfpath: str  - file path of the clustering to be evaluated
		inpfpath: str  - input dataset file path (ground-truth / input network for the ex/in-trinsic quality measure)
		asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
		timeout: uint  - execution timeout in seconds, 0 means infinity
		seed: uint  - seed for the stochastic qmeasures
		task: Task  - owner (super) task
		workdir: str  - working directory of the quality measure (qmeasure location)
		revalue: bool  - whether to revalue the existent results or omit such evaluations
			calculating and saving only the values which are not present in the dataset.
			NOTE: The default value is True because of the straight forward out of the box implementation.
			ATTENTION: Not all quality measure implementations might support early omission
				of the calculations on revalue=False, in which case a warning should be issued.

		return  jobsnum: uint  - the number of started jobs


:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
:Date: 2015-12
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import os
import shutil
import glob
import sys
import traceback  # Stack trace
import time
# Consider time interface compatibility for Python before v3.3
if not hasattr(time, 'perf_counter'):  #pylint: disable=C0413
	time.perf_counter = time.time

# from collections import namedtuple
from subprocess import PIPE
# Queue is required to asynchronously save evaluated quality measures to the persistent storage
from multiprocessing import cpu_count, Process, Queue, Value, sharedctypes
try:
	import queue	# queue in Python3
except ImportError:  # Queue in Python2
	import Queue as queue  # For exceptions handling: queue.Full, etc.

import h5py  # HDF5 storage
import numpy as np  # Required for the HDF5 operations

# from benchapps import  # funcToAppName,
from benchutils import viewitems, viewvalues, ItemsStatistic, parseFloat, parseName, syncedTime, \
	escapePathWildcards, envVarDefined, tobackup, funcToAppName, staticTrace, \
	SEPPARS, SEPINST, SEPSHF, SEPPATHID, UTILDIR, ALGSDIR, ALEVSMAX, ALGLEVS, \
	TIMESTAMP_START, TIMESTAMP_START_STR, TIMESTAMP_START_HEADER
from utils.mpepool import Task, Job, AffinityMask

# Identify type of the Variable-length ASCII (bytes) / UTF8 types for the HDF5 storage
try:
	# For Python3
	h5str = h5py.special_dtype(vlen=bytes)  # ASCII str, bytes
	h5ustr = h5py.special_dtype(vlen=str)  # UTF8 str
	# Note: str.encode() converts str to bytes, str.decode() converts bytes to (Unicode) str
except NameError:  # bytes are not defined in Python2
	# For Python2
	h5str = h5py.special_dtype(vlen=str)  # ASCII str, bytes
	h5ustr = h5py.special_dtype(vlen=unicode)  #pylint: disable=E0602;  # UTF8 str
	# Note: str.decode() converts bytes to Unicode str, str.encode() converts (Unicode) str to bytes

# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
RESDIR = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to ALGSDIR
CLSDIR = 'clusters/'  # Clusters directory for the resulting clusters of algorithms execution
QMSDIR = 'qmeasures/'  # Quality measures standard output and logs directory (QMSDIR/<basenet>/*.{log,err})
# _QUALITY_STORAGE = 'quality.h5'  # Quality evaluation storage file name
EXTLOG = '.log'  # Extension for the logs (stdout redirection and notifications)
EXTERR = '.err'  # Extension for the errors (stderr redirection and errors tracing)
#_EXTERR = '.elog'  # Extension for the unbuffered (typically error) logs
EXTRESCONS = '.rcp'  # Extension for the Resource Consumption Profile (made by the exectime app)
EXTAGGRES = '.res'  # Extension for the aggregated results
EXTAGGRESEXT = '.resx'  # Extension for the extended aggregated results
_EXTQDATASET = '.dat'  # Extension for the HDF5 datasets
# Job/Task name parts separator ('/' is the best choice because it can not appear in a file name,
# which can be part of job name)
SEPNAMEPART = '/'
_SEPQARGS = '_'  # Separator for the quality measure arguments to be shown in the monitoring and results
# Separetor for the quality measure from the processing file name.
# It is used for the file names and should follow restrictions on the allowed symbols.
_SEPQMS = ';'
_SUFULEV = '+u'  # Unified levels suffix of the HDF5 dataset (actual for DAOC)
_PREFMETR = ':'  # Metric prefix in the HDF5 dataset name
SATTRNINS = 'nins'  # HDF5 storage object attribute for the number of network instances
SATTRNSHF = 'nshf'  # HDF5 storage object attribute for the number of network instance shuffles
SATTRNLEV = 'nlev'  # HDF5 storage object attribute for the number of clustering levels

QMSRAFN = {}  # Specific affinity mask of the quality measures: str, AffinityMask;  qmsrAffinity
QMSINTRIN = set()  # Intrinsic quality measures requiring input network instead of the ground-truth clustering
QMSRUNS = {}  # Run the respective stochastic quality measures specified number of times
# Note: the metrics producing by the measure can be defined by the execution arguments
# QMSMTS = {}  # Metrics of the respective quality measures, omission means availability of the single metric with same name as the measuring executor

_DEBUG_TRACE = False  # Trace start / stop and other events to stderr


# # Accessory Routines -----------------------------------------------------------
# def toH5str(text):
# 	"""Convert text to the h5str
#
# 	text: str  - the text to be converted
#
# 	return  h5str  - the converted text
# 	"""
# 	return text.encode()  # Required for Python3, stub in Python2
#
#
# def toH5ustr(text):
# 	"""Convert text to the h5ustr
#
# 	text: str  - the text to be converted
#
# 	return  h5ustr  - the converted text
# 	"""
# 	return text.decode()  # Required for Python2, stub in Python3


# class Measures(object):
# 	"""Quality Measures"""
# 	def __init__(self, eval_num=None, nmi_max=None, nmi_sqrt=None, onmi_max=None, onmi_sqrt=None
# 	, f1p=None, f1h=None, f1s=None, mod=None, cdt=None):
# 		"""Quality Measures to be saved
#
# 		eval_num  - number/id of the evaluation to take average over multiple (re)evaluations
# 			(NMI from gecmi provides stochastic results), uint8 or None
# 		nmi_max  - NMI multi-resolution overlapping (gecmi) normalized by max (default)
# 		nmi_sqrt  - NMI multi-resolution overlapping (gecmi) normalized by sqrt
# 		onmi_max  - Overlapping nonstandard NMI (onmi) normalized by max (default)
# 		onmi_sqrt  - Overlapping nonstandard NMI (onmi) normalized by sqrt
# 		f1p  - F1p measure (harmonic mean of partial probabilities)
# 		f1h  - harmonic F1-score measure (harmonic mean of weighted average F1 measures)
# 		f1s  - average F1-score measure (arithmetic mean of weighted average F1 measures)
# 		mod  - modularity
# 		cdt  - conductance
# 		"""
# 		assert ((eval_num is None or (isinstance(eval_num, int) and 0 <= eval_num <= 0xFF)) and
# 			(nmi_max is None or 0. <= nmi_max <= 1.) and (nmi_sqrt is None or 0. <= nmi_sqrt <= 1.) and
# 			(onmi_max is None or 0. <= onmi_max <= 1.) and(onmi_sqrt is None or 0. <= onmi_sqrt <= 1.) and
# 			(f1p is None or 0. <= f1p <= 1.) and (f1h is None or 0. <= f1h <= 1.) and (f1s is None or 0. <= f1s <= 1.) and
# 			(mod is None or -0.5 <= mod <= 1.) and (cdt is None or 0. <= cdt <= 1.)), (
# 			'Parameters validation failed  nmi_max: {}, nmi_sqrt: {}, eval_num: {}, onmi_max: {}, onmi_sqrt: {}'
# 			', f1p: {}, f1h: {}, f1s: {}, q: {}, cdt: {}'.format(nmi_max, nmi_sqrt, eval_num
# 			, onmi_max, onmi_sqrt, f1p, f1h, f1s, mod, cdt))
# 		self._eval_num = eval_num  # Note: distinct attr name prefix ('_') is used to distinguish from the measure name
# 		self.nmi_max = nmi_max
# 		self.nmi_sqrt = nmi_sqrt
# 		self.onmi_max = onmi_max
# 		self.onmi_sqrt = onmi_sqrt
# 		self.f1p = f1p
# 		self.f1h = f1h
# 		self.f1s = f1s
# 		self.mod = mod  # Modularity
# 		self.cdt = cdt  # Conductance
#
#
# 	def __str__(self):
# 		"""String conversion"""
# 		return ', '.join([': '.join((name, str(val))) for name, val in viewitems(self.__dict__)])


# class NetParams(object):
# 	__slots__ = ('asym', 'pathidsuf')

# 	def __init__(self, asym, pathidsuf=''):
# 		"""Parameters of the input network

# 		asym: bool  - the input network might be asymmetric (directed) and is specified by arcs rather than edges
# 		pathidsuf: str  - network path id prepended with the path separator, used to distinguish nets
# 			with the same name located in different dirs
# 		"""
# 		assert not pathidsuf or pathidsuf.startswith(SEPPATHID), 'Ivalid pathidsuf: ' + pathidsuf
# 		self.asym = asym
# 		self.pathidsuf = pathidsuf

# 	def __str__(self):
# 		"""String conversion"""
# 		return ', '.join([': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__])


class NetInfo(object):
	"""Network Metainformation"""
	__slots__ = ('nins', 'nshf')  # , 'gvld'

	def __init__(self, nins=1, nshf=1):
		"""Network metainformation

		nins: uint8 >= 1  - the number of instances including the origin
		nshf: uint8 >= 1  - the number of shuffles including the origin
		"""
		# gvld: bool or None  - whether the respective HDF5 group entry attributes have been validated for this netinfo
		# 	(exception is raised on the failed validation)
		assert nins >= 1 and isinstance(nins, int) and nshf >= 1 and isinstance(nshf, int
			), 'Invalid arguments  nins: {}, nshf: {}'.format(nins, nshf)
		self.nins = nins
		self.nshf = nshf
		# self.gvld = False

	def __str__(self):
		"""String conversion"""
		return ', '.join([': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__])


class SMeta(object):
	"""Serialization meta information (data cell location)"""
	__slots__ = ('group', 'measure', 'ulev', 'iins', 'ishf', 'ilev', 'irun')

	def __init__(self, group, measure, ulev, iins, ishf, ilev=0, irun=0):
		"""Serialization meta information (location in the storage)
		
		group: str  - h5py.Group name where the target dataset is located: <algname>/<basenet><pathid>/
		measure: str  - name of the serializing evaluation measure
		ulev: bool  - unified levels, the clustering consists of the SINGLE (unified) level containing
			(representative) clusters from ALL (multiple) resolutions
		netinf: NetInfo  - network meta information (the number of network instances and shuffles, etc.)
		pathidsuf: str  - network path id prepended with the path separator
		ilev: uint  - index of the clustering level
		irun: uint8  - run id (iteration)
		"""
		# alg: str  - algorithm name, required to only to structure (order) the output results
		
		assert isinstance(group, str) and isinstance(measure, str
			) and iins >= 0 and isinstance(iins, int) and ishf >= 0 and isinstance(ishf, int
			) and ilev >= 0 and isinstance(ilev, int) and irun >= 0 and isinstance(irun, int
			), ('Invalid arguments:\n\tgroup: {group}\n\tmeasure: {measure}\n\tulev: {ulev}\n\t'
			'iins: {iins}\n\tishuf: {ishf}\n\tilev: {ilev}\n\tirun: {irun}'.format(
				group=group, measure=measure, ulev=ulev, iins=iins, ishf=ishf, ilev=ilev, irun=irun))
		self.group = group  # Group name since the opened group object can not be marshaled to another process
		self.measure = measure
		self.ulev = ulev
		self.iins = iins
		self.ishf = ishf
		self.ilev = ilev
		self.irun = irun

	def __str__(self):
		"""String conversion"""
		return ', '.join([': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__])


class QEntry(object):
	"""Quality evaluations etry to be saved to the persistent storage"""
	__slots__ = ('smeta', 'data')

	def __init__(self, smeta, data):  #, appargs=None, level=0, instance=0, shuffle=0):
		"""Quality evaluations to be saved

		smeta: SMeta  - serialization meta data
		data: dict(name: str, val: float32)  - serializing data
		"""
		assert isinstance(smeta, SMeta) and data and isinstance(data, dict), (
			'Invalid type of the arguments, smeta: {}, data: {}'.format(
			type(smeta).__name__, type(data).__name__))
		# # Validate first item in the data
		# name, val = next(iter(data))
		# assert isinstance(name, str) and isinstance(val, float), (
		# 	'Invalid type of the data items, name: {}, val: {}'.format(type(name).__name__, type(val).__name__)))
		self.smeta = smeta
		self.data = data

	def __str__(self):
		"""String conversion"""
		return ', '.join([': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__])


class QualitySaver(object):
	"""Quality evaluations saver to the persistent storage"""
	# Max number of the buffered items in the queue that have not been processed
	# before blocking the caller on appending more items
	# Should not be too much to save them into the persistent store on the
	# program termination or any external interruptions
	QUEUE_SIZEMAX = max(128, cpu_count() * 2)  # At least 128 or twice the number of the logical CPUs in the system
	# LATENCY = 1  # Latency in seconds

	# TODO: Efficient multiprocess implementation requires a single instance of the storage to not reload
	# the storage after each creation of a new group or dataset in it. So, group and dataset creation requests
	# should be performed via the queue together with the ordinary data entry creation requests implemented as follows.
	# @staticmethod
	# def __datasaver(qsqueue, syncstorage, active, timeout=None, latency=2.):
	# 	"""Worker process function to save data to the persistent storage
	#
	# 	qsqueue: Queue  - quality saver queue of QEntry items
	# 	syncstorage: h5py.File  - synchronized wrapper of the HDF5 storage
	# 	active: Value('B', lock=False)  - the saver process is operational (the requests can be processed)
	# 	timeout: float  - global operational timeout in seconds, None means no timeout
	# 	latency: float  - latency of the datasaver in sec, recommended value: 1-3 sec
	# 	"""
	# 	# def fetchAndSave():
	#
	# 	tstart = time.perf_counter()  # Global start time
	# 	tcur = tstart  # Start of the current iteration
	# 	while (active.value and (timeout is None or tcur - tstart < timeout)):
	# 		# Fetch and serialize items from the queue limiting their number
	# 		# (can be added in parallel) to avoid large latency
	# 		i = 0
	# 		while not qsqueue.empty() and i < QualitySaver.QUEUE_SIZEMAX:
	# 			i += 1
	# 			# qm = qsqueue.get(True, timeout=latency)  # Measures to be stored
	# 			qm = qsqueue.get_nowait()
	# 			assert isinstance(qm, QEntry), 'Unexpected type of the quality entry: ' + type(qm).__name__
	# 			# Save data elements (entries)
	# 			for metric, mval in  viewitems(qm.data):
	# 				try:
	# 					# Metric is  str (or can be unicode in Python2)
	# 					assert isinstance(mval, float), 'Invalid data type, metric: {}, value: {}'.format(
	# 						type(metric).__name__, type(mval).__name__)
	# 					# Construct dataset name based on the quality measure binary name and its metric name
	# 					# (in case of multiple metrics are evaluated by the executing app)
	# 					dsname = qm.smeta.measure if not metric else _PREFMETR.join((qm.smeta.measure, metric))
	# 					if qm.smeta.ulev:
	# 						dsname += _SUFULEV
	# 					dsname += _EXTQDATASET
	# 					# Open or create the required dataset
	# 					qmgroup = syncstorage.value[qm.smeta.group]
	# 					qmdata = None
	# 					try:
	# 						qmdata = qmgroup[dsname]
	# 					except KeyError:
	# 						# Such dataset does not exist, create it
	# 						nins = 1
	# 						nshf = 1
	# 						nlev = 1
	# 						if not qm.smeta.ulev:
	# 							nins = qmgroup.attrs[SATTRNINS]
	# 							nshf = qmgroup.attrs[SATTRNSHF]
	# 							nlev = qmgroup.parent.attrs[SATTRNLEV]
	# 						qmdata = qmgroup.create_dataset(dsname, shape=(nins, nshf, nlev, QMSRUNS.get(qm.smeta.measure, 1)),
	# 							# 32-bit floating number, checksum (fletcher32)
	# 							dtype='f4', fletcher32=True, fillvalue=np.float32(np.nan), track_times=True)
	# 							# NOTE: Numpy NA (not available) instead of NaN (not a number) might be preferable
	# 							# but it requires latest NumPy versions.
	# 							# https://www.numpy.org/NA-overview.html
	# 							# Numpy NAs (https://docs.scipy.org/doc/numpy-1.14.0/neps/missing-data.html):
	# 							# np.NA,  dtype='NA[f4]', dtype='NA', np.dtype('NA[f4,NaN]')
	# 					# Save data to the storage
	# 					with syncstorage.get_lock():
	# 						qmdata[qm.smeta.iins][qm.smeta.ishf][qm.smeta.ilev][qm.smeta.irun] = mval
	# 				except Exception as err:  #pylint: disable=W0703;  # queue.Empty as err:  # TypeError (HDF5), KeyError
	# 					print('ERROR, saving of {} in {}{}{} failed: {}. {}'.format(mval, qm.smeta.measure,
	# 						'' if not metric else _PREFMETR + metric, '' if not qm.smeta.ulev else _SUFULEV,
	# 						err, traceback.format_exc(5)), file=sys.stderr)
	# 				# alg = apps.require_dataset('Pscan01'.encode(),shape=(0,),dtype=h5py.special_dtype(vlen=bytes),chunks=(10,),maxshape=(None,),fletcher32=True)
	# 				# 	# Allocate chunks of 10 items starting with empty dataset and with possibility
	# 				# 	# to resize up to 500 items (params combinations)
	# 				# 	self.apps[app] = appsdir.require_dataset(app, shape=(0,), dtype=h5py.special_dtype(vlen=_h5str)
	# 				# 		, chunks=(10,), maxshape=(500,))  # , maxshape=(None,), fletcher32=True
	# 				# self.evals = self.storage.require_group('evals')  # Quality evaluations dir (group)
	# 		# Prepare for the next iteration considering the processing latency to reduce CPU loading
	# 		duration = time.perf_counter() - tcur
	# 		if duration < latency:
	# 			time.sleep(latency - duration)
	# 			duration = latency
	# 		tcur += duration
	# 	active.value = False
	# 	if not qsqueue.empty():
	# 		try:
	# 			print('WARNING QualitySaver, {} items remained unsaved in the terminating queue'
	# 				.format(qsqueue.qsize()))
	# 		except NotImplementedError:
	# 			print('WARNING QualitySaver, some items remained unsaved in the terminating queue')
	# 	# Note: qsqueue closing in the worker process (here) causes exception on the QualSaver destruction
	# 	# qsqueue.close()  # Close queue to prevent scheduling another tasks


	def __init__(self, seed, update=False):  # , timeout=None;  algs, qms, nets=None
		"""Creating or open HDF5 storage and prepare for the quality measures evaluations

		Check whether the storage exists, copy/move old storage to the backup and
		create the new one if the storage is not exist.

		seed: uint64  - benchmarking seed, natural number
		update: bool  - update existing storage creating if not exists, or create a new one backing up the existent

		Members:
			storage: h5py.File  - HDF5 storage with synchronized access
				ATTENTION: parallel write to the storage is not supported, i.e. requires synchronization layer
		"""
		# timeout: float  - global operational timeout in seconds, None means no timeout
		# Members:
		# 	_persister: Process  - persister worker process
		# 	queue: Queue  - multiprocess queue whose items are saved (persisted)
		# 	_active: Value('B')  - the storage is operational (the requests can be processed)

		# and (timeout is None or timeout >= 0)
		assert isinstance(seed, int), 'Invalid seed type: {}'.format(type(seed).__name__)
		# Open or init the HDF5 storage
		# self._tstart = time.perf_counter()
		# self.timeout = timeout
		timefmt = '%y%m%d-%H%M%S'  # Start time of the benchmarking, time format: YYMMDD_HHMMSS
		timestamp = time.strftime(timefmt, TIMESTAMP_START)  # Timestamp string
		seedstr = str(seed)
		qmsdir = RESDIR + QMSDIR  # Quality measures directory
		if not os.path.exists(qmsdir):
			os.makedirs(qmsdir)
		# HDF5 Storage: qmeasures_<seed>.h5
		storage = ''.join((qmsdir, 'qmeasures_', seedstr, '.h5'))  # File name of the HDF5.storage
		ublocksize = 512  # HDF5 .userblock size in bytes
		ublocksep = ':'  # Userblock values separator
		# try:
		if os.path.isfile(storage):
			# Read userblock: seed and timestamps, validate new seed and estimate whether
			# there is enought space for one more timestamp
			bcksftime = None
			if update:
				try:
					fstorage = h5py.File(storage, mode='r', driver='core', libver='latest')
					ublocksize = fstorage.userblock_size
					fstorage.close()
				except OSError:
					print('WARNING, can not open the file {}, default userblock size will be used.'.format(
						storage, file=sys.stderr))
				with open(storage, 'r+b') as fstore:  # Open file for R/W in binary mode
					# Note: userblock contains '<seed>:<timestamp1>:<timestamp2>...',
					# where timestamp has timefmt
					ublock = fstore.read(ublocksize).decode().rstrip('\0')
					ubparts = ublock.split(ublocksep)
					if len(ubparts) < 2:
						update = False
						print('ERROR, {} userblock should contain at least 2 items (seed and 1+ timestamp): {}.'
							' The new store will be created.'.format(storage, ublock), file=sys.stderr)
					if update and int(ubparts[0]) != seed:
						update = False
						print('WARNING, update is supported only for the same seed.'
							' Specified seed {} != {} storage seed. New storage will be created.'
							.format(seed, ubparts[0]), file=sys.stderr)
					# Update userblock if possible
					if update:
						if len(ublock) + len(ublocksep) + len(timestamp) <= ublocksize:
							fstore.seek(len(ublock))
							# Note: .encode() is required for the byte stream in Python3
							fstore.write(ublocksep.encode())  # Note: initially userblock is filled with 0
							fstore.write(timestamp.encode())
						else:
							update = False
							print('WARNING, {} can not be updated because the userblock is already full.'
								' A new storage will be created.'.format(storage), file=sys.stderr)
					bcksftime = syncedTime(time.strptime(ubparts[-1], timefmt), lock=False)  # Use last benchmarking start time
			tobackup(storage, False, synctime=bcksftime, move=not update)  # Copy/move to the backup
		elif update:
			update = False
			print('WARNING, the storage does not exist and can not be updated, created:', storage)
		# Create HFD5 storage if required
		if not update:
			# Create the storage, fail if exists ('w-' or 'x')
			fstorage = h5py.File(storage, mode='w-', driver='core', libver='latest', userblock_size=ublocksize)
			ubsize = fstorage.userblock_size  # Actual user block size of the storage
			fstorage.close()
			# Write the userblock
			if (ubsize
			and len(seedstr) + len(ublocksep) + len(timestamp) <= ubsize):
				with open(storage, 'r+b') as fstore:  # Open file for R/W in binary mode
					fstore.write(seedstr.encode())  # Note: .encode() is required for the byte stream in Python3
					fstore.write(ublocksep.encode())  # Note: initially userblock is filled with 0
					fstore.write(timestamp.encode())
					# Fill remained part with zeros to be sure that userblock is zeroed
					fstore.write(('\0' * (ubsize - (len(seedstr) + len(ublocksep) + len(timestamp)))).encode())
			else:
				raise RuntimeError('ERROR, the userblock creation failed in the {}, userblock_size: {}'
					', initial data size: {} (seed: {}, sep: {}, timestamp:{})'.format(storage
					, ubsize, len(seedstr) + len(ublocksep) + len(timestamp)
					, len(seedstr), len(ublocksep), len(timestamp)))
			# print('> HDF5 storage userblock created: ', seedstr, ublocksep, timestamp)
		# Note: append mode is the default one; core driver is a memory-mapped file, block_size is default (64 Kb)
		# Persistent storage object (file)
		self.storage = h5py.File(storage, mode='a', driver='core', libver='latest', userblock_size=ublocksize)
		# Add attributes if required
		dqrname = 'dims_qms_raw'
		if self.storage.attrs.get(dqrname) is None or update:
			# Describe dataset dimentions
			# Note: the dimension is implicitly omitted in the visualizing table if its size equals to 1
			dims_qms_raw = ('inst', 'shuf', 'levl', 'mrun')
			dqrlen = max((len(s) for s in dims_qms_raw)) + 1
			dqrtype = 'a' + str(dqrlen)  # Zero terminated bytes, fixed length
			self.storage.attrs.create(dqrname, data=np.array(dims_qms_raw, dtype=dqrtype))
				# shape=(len(dims_qms_raw),), dtype=dqrtype)
			# dims_qms_agg = ('net'): ('avg', 'var', 'num')  # 'dims_qms_agg'

		# except Exception as err:  #pylint: disable=W0703
		# 	print('ERROR, HDF5 storage creation failed: {}. {}'.format(err, traceback.format_exc(5)), file=sys.stderr)
		# 	raise
			
		# Initialize or update metadata and groups
		# # rescons meta data (h5str array)
		# try:
		# 	self.mrescons = [b.encode() for b in self.storage.value['rescons.inf'][()]]
		# except KeyError:  # IndexError
		# 	self.mrescons = ['ExecTime', 'CPU_time', 'RSS_peak']
		# 	# Note: None in maxshape means resizable, fletcher32 used for the checksum
		# 	self.storage.create_dataset('rescons.inf', shape=(len(self.mrescons),)
		# 		, dtype=h5str, data=[s.decode() for s in self.mrescons], fletcher32=True)  # fillvalue=''
		# # # Note: None in maxshape means resizable, fletcher32 used for the checksum,
		# # # exact used to require shape and type to match exactly
		# # metares = self.storage.require_dataset('rescons.meta', shape=(len(self.mrescons),), dtype=h5str
		# # 	, data=self.mrescons, exact=True, fletcher32=True)  # fillvalue=''
		# #
		# # rescons str to the index mapping
		# self.irescons = {s: i for i, s in enumerate(self.mrescons)}

		# self.queue = None  # Note: the multiprocess queue is created in the enter blocks
		# # The storage is not operational until the queue is created
		# # Note: a shared value for the active state is sufficient, exact synchronization is not required
		# self._active = Value('B', False, lock=False)
		# self._persister = None


	def __call__(self, qm):
		"""Worker process function to save data to the persistent storage

		qm: QEntry  - quality metric (data and metadata) to be saved into the persistent storage
		"""
		assert isinstance(qm, QEntry), 'Unexpected type of the quality entry: ' + type(qm).__name__
		# Save data elements (entries)
		for metric, mval in  viewitems(qm.data):
			try:
				# Metric is  str (or can be unicode in Python2)
				assert isinstance(mval, float), 'Invalid data type, metric: {}, value: {}'.format(
					type(metric).__name__, type(mval).__name__)
				# Construct dataset name based on the quality measure binary name and its metric name
				# (in case of multiple metrics are evaluated by the executing app)
				dsname = qm.smeta.measure if not metric else _PREFMETR.join((qm.smeta.measure, metric))
				if qm.smeta.ulev:
					dsname += _SUFULEV
				#print('> dsname: {}, metric: {}, mval: {}; location: {}'.format(dsname, metric, mval, qm.smeta))
				dsname += _EXTQDATASET
				# Open or create the required dataset
				qmgroup = self.storage[qm.smeta.group]
				qmdata = None
				try:
					qmdata = qmgroup[dsname]
				except KeyError:
					# Such dataset does not exist, create it
					nins = qmgroup.attrs[SATTRNINS]
					nshf = qmgroup.attrs[SATTRNSHF]
					nlev = 1 if qm.smeta.ulev else qmgroup.parent.attrs[SATTRNLEV]
					qmdata = qmgroup.create_dataset(dsname, shape=(nins, nshf, nlev, QMSRUNS.get(qm.smeta.measure, 1)),
						# 32-bit floating number, checksum (fletcher32)
						dtype='f4', fletcher32=True, fillvalue=np.float32(np.nan), track_times=True)
						# NOTE: Numpy NA (not available) instead of NaN (not a number) might be preferable
						# but it requires latest NumPy versions.
						# https://www.numpy.org/NA-overview.html
						# Numpy NAs (https://docs.scipy.org/doc/numpy-1.14.0/neps/missing-data.html):
						# np.NA,  dtype='NA[f4]', dtype='NA', np.dtype('NA[f4,NaN]')

				# Save data to the storage
				# with syncstorage.get_lock():
				# print('>> [{},{},{},{}]{}: {}'.format(qm.smeta.iins, qm.smeta.ishf, qm.smeta.ilev, qm.smeta.irun,
				# 	'' if not qm.smeta.ulev else 'u', mval))
				qmdata[qm.smeta.iins, qm.smeta.ishf, qm.smeta.ilev, qm.smeta.irun] = mval
			except Exception as err:  #pylint: disable=W0703;  # queue.Empty as err:  # TypeError (HDF5), KeyError
				print('ERROR, saving of {} into {}{}{}[{},{},{},{}] failed: {}. {}'.format(mval, qm.smeta.measure,
					'' if not metric else _PREFMETR + metric, '' if not qm.smeta.ulev else _SUFULEV,
					qm.smeta.iins, qm.smeta.ishf, qm.smeta.ilev, qm.smeta.irun,
					err, traceback.format_exc(5)), file=sys.stderr)
			# alg = apps.require_dataset('Pscan01'.encode(),shape=(0,),dtype=h5py.special_dtype(vlen=bytes),chunks=(10,),maxshape=(None,),fletcher32=True)
			# 	# Allocate chunks of 10 items starting with empty dataset and with possibility
			# 	# to resize up to 500 items (params combinations)
			# 	self.apps[app] = appsdir.require_dataset(app, shape=(0,), dtype=h5py.special_dtype(vlen=_h5str)
			# 		, chunks=(10,), maxshape=(500,))  # , maxshape=(None,), fletcher32=True
			# self.evals = self.storage.require_group('evals')  # Quality evaluations dir (group)


	def __del__(self):
		"""Destructor"""
		# self._active.value = False
		# try:
		# 	if self.queue is not None:
		# 		try:
		# 			if not self.queue.empty():
		# 				print('WARNING, terminating the persistency layer with {} queued data entries, call stack: {}'
		# 					.format(self.queue.qsize(), traceback.format_exc(5)), file=sys.stderr)
		# 		except OSError:   # The queue has been already closed from another process
		# 			pass
		# 		self.queue.close()  # No more data can be put in the queue
		# 		self.queue.join_thread()
		# 	if self._persister is not None:
		# 		self._persister.join(0)  # Note: timeout is 0 to avoid destructor blocking
		# finally:
		# 	if self.storage is None:
		# 		return
		# 	with self.storage.get_lock():
		# 		if self.storage.value is not None:
		# 			self.storage.close()

		if self.storage is not None:
			self.storage.close()


	def __enter__(self):
	# 	"""Context entrence"""
	# 	self.queue = Queue(self.QUEUE_SIZEMAX)  # Qulity measures persistence queue, data pool
	# 	self._active.value = True
	# 	# __datasaver(qsqueue, active, timeout=None, latency=2.)
	# 	self._persister = Process(target=self.__datasaver, args=(self.queue, self.storage, self._active, self.timeout))
	# 	self._persister.start()
		return self


	def __exit__(self, etype, evalue, tracebk):
		"""Contex exit
	
		etype  - exception type
		evalue  - exception value
		tracebk  - exception traceback
		"""
	# 	self._active.value = False
	# 	try:
	# 		self.queue.close()  # No more data can be put in the queue
	# 		self.queue.join_thread()
	# 		self._persister.join(None if self.timeout is None else self.timeout - self._tstart)
	# 	finally:
	# 		with self.storage.get_lock():
	# 			if self.storage.value is not None:
	# 				self.storage.value.flush()  # Allow to reuse the instance in several context managers
	# 	# Note: the exception (if any) is propagated if True is not returned here

		if self.storage is not None:
			self.storage.flush()  # Allow to reuse the instance in several context managers


def metainfo(afnmask=None, intrinsic=False, multirun=1):
	"""Set some meta information for the executing evaluation measures

	afnstep: AffinityMask  - affinity mask
	intrinsic: bool  - whether the quality measure is intrinsic and requires input network
		instead of the ground-truth clustering
	multirun: uint8, >= 1  - perform multiple runs of this stochastic quality measure
	"""
	# Note: the metrics producing by the measure can be defined by the execution arguments
	# metrics: list(str)  - quality metrics producing by the measure
	def decor(func):
		"""Decorator returning the original function"""
		assert (afnmask is None or isinstance(afnmask, AffinityMask)
			) and multirun >= 1 and isinstance(multirun, int), (
			'Invalid arguments, affinity mask type: {}, multirun: {}'.format(type(afnmask).__name__, multirun))
		# QMSRAFN[funcToAppName(func)] = afnmask
		if afnmask is not None and afnmask.afnstep != 1:  # Save only quality measures with non-default affinity
			QMSRAFN[func] = afnmask
		if intrinsic:
			QMSINTRIN.add(func)
		if multirun >= 2:
			# ATTENTION: function name is used to retrieve it from the value from the persister by the qmeasure name
			QMSRUNS[funcToAppName(func.__name__)] = multirun
		return func
	return decor


# def saveQuality(qsqueue, qentry):
# 	"""Save quality entry int the Quality Saver queue
#
# 	Args:
# 		qsqueue: Queue  - quality saver queue
# 		qentry: QEntry  - quality entry to be saved
# 	"""
# 	# Note: multiprocessing Queue is not a Python class, it is a function creating a proxy object
# 	assert isinstance(qentry, QEntry), ('Unexpected type of the arguments, qsqueue: {}, qentry: {}'
# 		.format(type(qsqueue).__name__, type(qentry).__name__))
# 	try:
# 		# Note: evaluators should not be delayed in the main thread
# 		# Anyway qsqueue is buffered and in theory serialization 
# 		qsqueue.put_nowait(qentry)
# 	except queue.Full as err:
# 		print('WARNING, the quality entry ({}) saving is cancelled because of the busy serialization queue: {}'
# 			.format(str(qentry), err, file=sys.stderr))

# Note: default AffinityMask is 1 (logical CPUs, i.e. hardware threads)
def qmeasure(qmapp, workdir=UTILDIR):
	"""Quality Measure exutor decorator

	qmapp: str  - quality measure application (binary) name (located in the ./utils dir)
	workdir: str  - current working directory from which the quality measure binare is called
	"""
	def wrapper(qmsaver):  # Actual decorator for the qmsaver func(Job)
		"""Actual decorator of the quality measure parcing saving function
		
		qmsaver: callable(job: Job)  - parcing and saving function of the quality measure,
			used as a Job.ondone() callback
		"""
		qmsname = None  # Name of the wrapping callable object (function or class instance)
		try:
			qmsname = qmsaver.__name__
		except AttributeError:  # The callable is not a function, so it should be a class object
			qmsname = qmsaver.__class__

		def executor(execpool, save, smeta, qparams, cfpath, inpfpath, asym=False
		, timeout=0, seed=None, task=None, workdir=workdir, revalue=True):
			"""Quality measure executor

			execpool: ExecPool  - execution pool
			save: QualitySaver or callable proxy to its persistance routine  - quality results saving function or functor
			smeta: SMeta - serialization meta data
			qparams: iterable(str)  - quality measures parameters (arguments excluding the clustering and network files)
			cfpath: str  - file path of the clustering to be evaluated
			inpfpath: str  - input dataset file path (ground-truth / input network for the ex/in-trinsic quality measure)
			asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
			timeout: uint  - execution timeout in seconds, 0 means infinity
			seed: uint  - seed for the stochastic qmeasures
			task: Task  - owner (super) task
			workdir: str  - working directory of the quality measure (qmeasure location)
			revalue: bool  - whether to revalue the existent results or omit such evaluations
				calculating and saving only the values which are not present in the dataset.
				NOTE: The default value is True because of the straight forward out of the box implementation.
				ATTENTION: Not all quality measure implementations might support early omission
					of the calculations on revalue=False, in which case a warning should be issued.

			return jobsnum: uint  - the number of started jobs
			"""
			if not revalue:
				# TODO: implement early exit on qualsaver.valueExists(smeta, metrics),
				# where metrics are provided by the quality measure app by it's qparams
				staticTrace(qmsname, 'Omission of the existent results is not supported yet')
			# qsqueue: Queue  - multiprocess queue of the quality results saver (persister)
			assert execpool and callable(save) and isinstance(smeta, SMeta
				) and isinstance(cfpath, str) and isinstance(inpfpath, str) and (seed is None
				or isinstance(seed, int)) and (task is None or isinstance(task, Task)), (
				'Invalid arguments, execpool type: {}, save() type: {}, smeta type: {}, cfpath type: {},'
				' inpfpath type: {}, timeout: {}, seed: {}, task type: {}'.format(type(execpool).__name__,
				type(save).__name__, type(smeta).__name__, type(cfpath).__name__, type(inpfpath).__name__,
				timeout, seed, type(task).__name__))

			# The task argument name already includes: QMeasure / BaseNet#PathId / Alg,
			# so here smeta parts and qparams should form the job name for the full identification of the executing job
			# Note: HDF5 uses Unicode for the file name and ASCII/Unicode for the group names
			algname, basenetp = smeta.group[1:].split('/')  # Omit the leading '/'; basenetp includes pathid
			# Note that evaluating file name might significantly differ from the network name, for example `tp<id>` produced by OSLOM
			cfname = os.path.splitext(os.path.split(cfpath)[1])[0]  # Evaluating file name (without the extension)
			measurep = SEPPARS.join((smeta.measure, _SEPQARGS.join(qparams)))  # Quality measure suffixed with its parameters
			taskname = _SEPQMS.join((cfname, measurep))

			# Evaluate relative size of the clusterings
			# Note: xmeasures takes inpfpath as the ground-truth clustering, so the asym parameter is not actual here
			clsize = os.path.getsize(cfpath) + os.path.getsize(inpfpath)

			# Define path to the logs relative to the root dir of the benchmark
			logsdir = ''.join((RESDIR, algname, '/', QMSDIR, basenetp, '/'))
			# Note: backup is not performed since it should be performed at most once for all logs in the logsdir
			# (staticExec could be used) and only if the logs are rewriting but they are appended.
			# The backup is not convenient here for multiple runs on various networks to get aggregated results
			if not os.path.exists(logsdir):
				os.makedirs(logsdir)
			errfile = taskname.join((logsdir, EXTERR))
			logfile = taskname.join((logsdir, EXTLOG))

			# Note: without './' relpath args do not work properly for the binaries located in the current dir
			relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
			# Evaluate relative paths
			# xtimebin = './exectime'  # Note: relpath(UTILDIR + 'exectime') -> 'exectime' does not work, it requires leading './'
			xtimebin = relpath(UTILDIR + 'exectime')
			xtimeres = relpath(''.join((RESDIR, algname, '/', QMSDIR, measurep, EXTRESCONS)))

			# The task argument name already includes: QMeasure / BaseNet#PathId / Alg
			# Note: xtimeres does not include the base network name, so it should be included into the listed taskname,
			args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', basenetp, SEPNAMEPART, cfname)), '-s=/etime_' + measurep, './' + qmapp]
			if qparams:
				args += qparams
			# Note: use first the ground-truth or network file and then the clustering file to perform sync correctly
			# for the xmeaseres (gecmi and onmi select the most reasonable direction automatically)
			args += (relpath(inpfpath), relpath(cfpath))
			# print('> Starting Xmeasures with the args: ', args)
			# print('> Starting {} for: {}, {}'.format(qmsname, args[-2], args[-1]))
			execpool.execute(Job(name=taskname, workdir=workdir, args=args, timeout=timeout
				, ondone=qmsaver, params={'save': save, 'smeta': smeta}
				# Note: poutlog indicates the output log file that should be formed from the PIPE output
				, task=task, category=measurep, size=clsize, stdout=PIPE, stderr=errfile, poutlog=logfile))
			return 1
		executor.__name__ = qmsname
		return executor
	return wrapper


def qmsaver(job):
	"""Default quality measure parser and serializer, used as Job ondone() callback

	job  - executed job, whose params contain:
		save: callable  - save(QEntry) routine to the persistant storage 
		smeta: SMeta  - metadata identifying location of the saving values in the storage dataset
	"""
	if not job.pipedout:
		# Note: any notice is redundant here since everything is automatically logged
		# to the Job log (at least the timestamp if the log body itself is empty)
		return
	save = job.params['save']
	smeta = job.params['smeta']
	# xmeasures output is performed either in the last string with metrics separated with ':'
	# from their values and {',', ';'} from each other, where Precision and Recall of F1_labels
	# are parenthesized.
	# The output is performed in 2 last strings only for a single measure with a single value,
	# where the measure name (with possible additional description) is on the pre-last string.
	#
	# Define the number of strings in the output counting the number of words in the last string
	# Identify index of the last non-empty line
	qmres = job.pipedout.rstrip().splitlines()[-2:]  # Fetch last 2 non-empty lines as a list(str)
	# print('Value line: {}, len: {}, sym1: {}'.format(qmres[-1], len(qmres[-1]), ord(qmres[-1][0])))
	if len(qmres[-1].split(None, 1)) == 1:
		# Metric name is None (the same as binary name) if not specified explicitly
		name = None if len(qmres) == 1 else qmres[0].split(None, 1)[0].rstrip(':')  # Omit ending ':' if any
		val = qmres[-1]  # Note: index -1 corresponds to either 0 or 1
		try:
			# qsqueue.put(QEntry(smeta, {name: float(val)}))
			# # , block=True, timeout=None if not timeout else max(0, timeout - (time.perf_counter() - job.tstart)))
			# saveQuality(qsqueue, QEntry(smeta, {name: float(val)}))
			# print('> Parsed data (single) from "{}", name: {}, val: {}; qmres: {}'.format(
			# 	' '.join(('' if len(qmres) == 1 else qmres[0], qmres[-1])), name, val, qmres))
			save(QEntry(smeta, {name: float(val)}))
		except ValueError as err:
			print('ERROR, metric "{}" serialization discarded of the job "{}" because of the invalid value format: {}. {}'
				.format(name, job.name, val, err), file=sys.stderr)
		# except queue.Full as err:
		# 	print('WARNING, results serialization discarded by the Job "{}" timeout'.format(job.name))
		return
	# Parse multiple names of the metrics and their values from the last string: <metric>: <value>{,;} ...
	# Note: index -1 corresponds to either 0 or 1
	metrics = [qmres[-1]]
	# Example of the parsing line: "F1_labels: <val> (Precision: <val>, ...)"
	for sep in ',;(':
		smet = []
		for m in metrics:
			smet.extend(m.split(sep))
		metrics = smet
	data = {}  # Serializing data
	for mt in metrics:
		name, val = mt.split(':', 1)
		try:
			data[name.lstrip()] = float(val.rstrip(' \t)'))
			# print('> Parsed data from "{}", name: {}, val: {}'.format(mt, name.lstrip(), data[name.lstrip()]))
		except ValueError as err:
			print('ERROR, metric "{}" serialization discarded of the job "{}" because of the invalid value format: {}. {}'
				.format(name, job.name, val, err), file=sys.stderr)
	if data:
		# saveQuality(qsqueue, QEntry(smeta, data))
		save(QEntry(smeta, data))


@qmeasure('xmeasures')
def execXmeasures(job):
	"""xmeasures  - various extrinsic quality measures"""
	qmsaver(job)


# Fully defined quality measure executor
# # Note: default AffinityMask is 1 (logical CPUs, i.e. hardware threads)
# def execXmeasures(execpool, save, smeta, qparams, cfpath, inpfpath, asym=False
# , timeout=0, seed=None, task=None, workdir=UTILDIR, revalue=True):
# 	"""Quality measure executor
#
# 	xmeasures  - various extrinsic quality measures
#
# 	execpool: ExecPool  - execution pool
# 	save: QualitySaver or callable proxy to its persistance routine  - quality results saving function or functor
# 	smeta: SMeta - serialization meta data
# 	qparams: iterable(str)  - quality measures parameters (arguments excluding the clustering and network files)
# 	cfpath: str  - file path of the clustering to be evaluated
# 	inpfpath: str  - input dataset file path (ground-truth / input network for the ex/in-trinsic quality measure)
# 	asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
# 	timeout: uint  - execution timeout in seconds, 0 means infinity
# 	seed: uint  - seed for the stochastic qmeasures
# 	task: Task  - owner (super) task
# 	workdir: str  - working directory of the quality measure (qmeasure location)
# 	revalue: bool  - whether to revalue the existent results or omit such evaluations
# 		calculating and saving only the values which are not present in the dataset.
# 		NOTE: The default value is True because of the straight forward out of the box implementation.
# 		ATTENTION: Not all quality measure implementations might support early omission
# 			of the calculations on revalue=False, in which case a warning should be issued.
#
# 	return jobsnum: uint  - the number of started jobs
# 	"""
# 	if not revalue:
# 		# TODO: implement early exit on qualsaver.valueExists(smeta, metrics),
# 		# where metrics are provided by the quality measure app by it's qparams
# 		staticTrace('execXmeasures', 'Omission of the existent results is not supported yet')
# 	# qsqueue: Queue  - multiprocess queue of the quality results saver (persister)
# 	assert execpool and callable(save) and isinstance(smeta, SMeta
# 		) and isinstance(cfpath, str) and isinstance(inpfpath, str) and (seed is None
# 		or isinstance(seed, int)) and (task is None or isinstance(task, Task)), (
# 		'Invalid arguments, execpool type: {}, save() type: {}, smeta type: {}, cfpath type: {},'
# 		' inpfpath type: {}, timeout: {}, seed: {}, task type: {}'.format(type(execpool).__name__,
# 		type(save).__name__, type(smeta).__name__, type(cfpath).__name__, type(inpfpath).__name__,
# 		timeout, seed, type(task).__name__))
#
# 	def saveEvals(job):
# 		"""Job ondone() callback to persist evaluated quality measurements"""
# 		if not job.pipedout:
# 			# Note: any notice is redundant here since everything is automatically logged
# 			# to the Job log (at least the timestamp if the log body itself is empty)
# 			return
# 		save = job.params['save']
# 		smeta = job.params['smeta']
# 		# xmeasures output is performed either in the last string with metrics separated with ':'
# 		# from their values and {',', ';'} from each other, where Precision and Recall of F1_labels
# 		# are parenthesized.
# 		# The output is performed in 2 last strings only for a single measure with a single value,
# 		# where the measure name (with possible additional description) is on the pre-last string.
# 		#
# 		# Define the number of strings in the output counting the number of words in the last string
# 		# Identify index of the last non-empty line
# 		qmres = job.pipedout.rstrip().splitlines()[-2:]  # Fetch last 2 non-empty lines as a list(str)
# 		# print('Value line: {}, len: {}, sym1: {}'.format(qmres[-1], len(qmres[-1]), ord(qmres[-1][0])))
# 		if len(qmres[-1].split(None, 1)) == 1:
# 			# Metric name is None (the same as binary name) if not specified explicitly
# 			name = None if len(qmres) == 1 else qmres[0].split(None, 1)[0].rstrip(':')  # Omit ending ':' if any
# 			val = qmres[-1]  # Note: index -1 corresponds to either 0 or 1
# 			try:
# 				# qsqueue.put(QEntry(smeta, {name: float(val)}))
# 				# # , block=True, timeout=None if not timeout else max(0, timeout - (time.perf_counter() - job.tstart)))
# 				# saveQuality(qsqueue, QEntry(smeta, {name: float(val)}))
# 				# print('> Parsed data (single) from "{}", name: {}, val: {}; qmres: {}'.format(
# 				# 	' '.join(('' if len(qmres) == 1 else qmres[0], qmres[-1])), name, val, qmres))
# 				save(QEntry(smeta, {name: float(val)}))
# 			except ValueError as err:
# 				print('ERROR, metric "{}" serialization discarded of the job "{}" because of the invalid value format: {}. {}'
# 					.format(name, job.name, val, err), file=sys.stderr)
# 			# except queue.Full as err:
# 			# 	print('WARNING, results serialization discarded by the Job "{}" timeout'.format(job.name))
# 			return
# 		# Parse multiple names of the metrics and their values from the last string: <metric>: <value>{,;} ...
# 		# Note: index -1 corresponds to either 0 or 1
# 		metrics = [qmres[-1]]
# 		# Example of the parsing line: "F1_labels: <val> (Precision: <val>, ...)"
# 		for sep in ',;(':
# 			smet = []
# 			for m in metrics:
# 				smet.extend(m.split(sep))
# 			metrics = smet
# 		data = {}  # Serializing data
# 		for mt in metrics:
# 			name, val = mt.split(':', 1)
# 			try:
# 				data[name.lstrip()] = float(val.rstrip(' \t)'))
# 				# print('> Parsed data from "{}", name: {}, val: {}'.format(mt, name.lstrip(), data[name.lstrip()]))
# 			except ValueError as err:
# 				print('ERROR, metric "{}" serialization discarded of the job "{}" because of the invalid value format: {}. {}'
# 					.format(name, job.name, val, err), file=sys.stderr)
# 		if data:
# 			# saveQuality(qsqueue, QEntry(smeta, data))
# 			save(QEntry(smeta, data))
#
# 	# The task argument name already includes: QMeasure / BaseNet#PathId / Alg,
# 	# so here smeta parts and qparams should form the job name for the full identification of the executing job
# 	# Note: HDF5 uses Unicode for the file name and ASCII/Unicode for the group names
# 	algname, basenetp = smeta.group[1:].split('/')  # Omit the leading '/'; basenetp includes pathid
# 	# Note that evaluating file name might significantly differ from the network name, for example `tp<id>` produced by OSLOM
# 	cfname = os.path.splitext(os.path.split(cfpath)[1])[0]  # Evaluating file name (without the extension)
# 	measurep = SEPPARS.join((smeta.measure, _SEPQARGS.join(qparams)))  # Quality measure suffixed with its parameters
# 	taskname = _SEPQMS.join((cfname, measurep))
#
# 	# Evaluate relative size of the clusterings
# 	# Note: xmeasures takes inpfpath as the ground-truth clustering, so the asym parameter is not actual here
# 	clsize = os.path.getsize(cfpath) + os.path.getsize(inpfpath)
#
# 	# Define path to the logs relative to the root dir of the benchmark
# 	logsdir = ''.join((RESDIR, algname, '/', QMSDIR, basenetp, '/'))
# 	# Note: backup is not performed since it should be performed at most once for all logs in the logsdir
# 	# (staticExec could be used) and only if the logs are rewriting but they are appended.
# 	# The backup is not convenient here for multiple runs on various networks to get aggregated results
# 	if not os.path.exists(logsdir):
# 		os.makedirs(logsdir)
# 	errfile = taskname.join((logsdir, EXTERR))
# 	logfile = taskname.join((logsdir, EXTLOG))
#
# 	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
# 	# Evaluate relative paths
# 	xtimebin = './exectime'  # Note: relpath(UTILDIR + 'exectime') -> 'exectime' does not work, it requires leading './'
# 	xtimeres = relpath(''.join((RESDIR, algname, '/', QMSDIR, measurep, EXTRESCONS)))
#
# 	# The task argument name already includes: QMeasure / BaseNet#PathId / Alg
# 	# Note: xtimeres does not include the base network name, so it should be included into the listed taskname,
# 	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', basenetp, SEPNAMEPART, cfname)), '-s=/etime_' + measurep, './xmeasures']
# 	if qparams:
# 		args += qparams
# 	args += (relpath(cfpath), relpath(inpfpath))
# 	# print('> Starting Xmeasures with the args: ', args)
# 	execpool.execute(Job(name=taskname, workdir=workdir, args=args, timeout=timeout
# 		, ondone=saveEvals, params={'save': save, 'smeta': smeta}
# 		# Note: poutlog indicates the output log file that should be formed from the PIPE output
# 		, task=task, category=measurep, size=clsize, stdout=PIPE, stderr=errfile, poutlog=logfile))
# 	return 1


@qmeasure('gecmi')
@metainfo(afnmask=AffinityMask(AffinityMask.NODE_CPUS, first=False), multirun=3)  # Note: multirun requires irun
def execGnmi(job):
	"""gnmi (gecmi)  - Generalized Normalized Mutual Information"""
	qmsaver(job)


@qmeasure('onmi')
def execOnmi(job):
	"""onmi  - Overlapping NMI"""
	qmsaver(job)


# @qmeasure('daoc', workdir=ALGSDIR + 'daoc/')
# @metainfo(intrinsic=True)  # Note: intrinsic causes interpretation of ifname as inpnet and requires netparams
# def execImeasures(job):
@metainfo(intrinsic=True)  # Note: intrinsic causes interpretation of ifname as inpnet and requires netparams
def execImeasures(execpool, save, smeta, qparams, cfpath, inpfpath, asym=False
		, timeout=0, seed=None, task=None, workdir=ALGSDIR + 'daoc/', revalue=True):
	"""imeasures (proxy for DAOC)  - executor of some intrinsic quality measures

	execpool: ExecPool  - execution pool
	save: QualitySaver or callable proxy to its persistance routine  - quality results saving function or functor
	smeta: SMeta - serialization meta data
	qparams: iterable(str)  - quality measures parameters (arguments excluding the clustering and network files)
	cfpath: str  - file path of the clustering to be evaluated
	inpfpath: str  - input dataset file path (ground-truth / input network for the ex/in-trinsic quality measure)
	asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
	timeout: uint  - execution timeout in seconds, 0 means infinity
	seed: uint  - seed for the stochastic qmeasures
	task: Task  - owner (super) task
	workdir: str  - working directory of the quality measure (qmeasure location)
	revalue: bool  - whether to revalue the existent results or omit such evaluations
		calculating and saving only the values which are not present in the dataset.
		NOTE: The default value is True because of the straight forward out of the box implementation.
		ATTENTION: Not all quality measure implementations might support early omission
			of the calculations on revalue=False, in which case a warning should be issued.

	return jobsnum: uint  - the number of started jobs
	"""
	if not revalue:
		# TODO: implement early exit on qualsaver.valueExists(smeta, metrics),
		# where metrics are provided by the quality measure app by it's qparams
		staticTrace('Imeasures', 'Omission of the existent results is not supported yet')
	# qsqueue: Queue  - multiprocess queue of the quality results saver (persister)
	assert execpool and callable(save) and isinstance(smeta, SMeta
		) and isinstance(cfpath, str) and isinstance(inpfpath, str) and (seed is None
		or isinstance(seed, int)) and (task is None or isinstance(task, Task)), (
		'Invalid arguments, execpool type: {}, save() type: {}, smeta type: {}, cfpath type: {},'
		' inpfpath type: {}, timeout: {}, seed: {}, task type: {}'.format(type(execpool).__name__,
		type(save).__name__, type(smeta).__name__, type(cfpath).__name__, type(inpfpath).__name__,
		timeout, seed, type(task).__name__))

	# The task argument name already includes: QMeasure / BaseNet#PathId / Alg,
	# so here smeta parts and qparams should form the job name for the full identification of the executing job
	# Note: HDF5 uses Unicode for the file name and ASCII/Unicode for the group names
	algname, basenetp = smeta.group[1:].split('/')  # Omit the leading '/'; basenetp includes pathid
	# Note that evaluating file name might significantly differ from the network name, for example `tp<id>` produced by OSLOM
	cfname = os.path.splitext(os.path.split(cfpath)[1])[0]  # Evaluating file name (without the extension)
	measurep = SEPPARS.join((smeta.measure, _SEPQARGS.join(qparams)))  # Quality measure suffixed with its parameters
	taskname = _SEPQMS.join((cfname, measurep))

	# Evaluate relative size of the clusterings
	# Note: xmeasures takes inpfpath as the ground-truth clustering, so the asym parameter is not actual here
	clsize = os.path.getsize(cfpath) + os.path.getsize(inpfpath)

	# Define path to the logs relative to the root dir of the benchmark
	logsdir = ''.join((RESDIR, algname, '/', QMSDIR, basenetp, '/'))
	# Note: backup is not performed since it should be performed at most once for all logs in the logsdir
	# (staticExec could be used) and only if the logs are rewriting but they are appended.
	# The backup is not convenient here for multiple runs on various networks to get aggregated results
	if not os.path.exists(logsdir):
		os.makedirs(logsdir)
	errfile = taskname.join((logsdir, EXTERR))
	logfile = taskname.join((logsdir, EXTLOG))

	# Note: without './' relpath args do not work properly for the binaries located in the current dir
	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	# xtimebin = './exectime'  # Note: relpath(UTILDIR + 'exectime') -> 'exectime' does not work, it requires leading './'
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', QMSDIR, measurep, EXTRESCONS)))

	# The task argument name already includes: QMeasure / BaseNet#PathId / Alg
	# Note: xtimeres does not include the base network name, so it should be included into the listed taskname,
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', basenetp, SEPNAMEPART, cfname)), '-s=/etime_' + measurep, './daoc']
	for qp in qparams:
		if qp.startswith('-e'):  #  Append filename of the evaluating clsutering
			qp = '='.join((qp, relpath(cfpath)))
		args.append(qp)
	# Note: use first the ground-truth or network file and then the clustering file to perform sync correctly
	# for the xmeaseres (gecmi and onmi select the most reasonable direction automatically)
	args.append(relpath(inpfpath))
	# print('> Starting Xmeasures with the args: ', args)
	# print('> Starting {} for: {}, {}'.format('Imeasures', args[-2], args[-1]))
	execpool.execute(Job(name=taskname, workdir=workdir, args=args, timeout=timeout
		, ondone=qmsaver, params={'save': save, 'smeta': smeta}
		# Note: poutlog indicates the output log file that should be formed from the PIPE output
		, task=task, category=measurep, size=clsize, stdout=PIPE, stderr=errfile, poutlog=logfile))
	return 1


class ShufflesAgg(object):
	"""Shuffles evaluations aggregator

	1. Best avg per level is defined as for all shuffles:
		sum value per each level is taken, highest sum / count is selected.
	2. For all instances average weighted among best levels (1) is taken
		(considering number of items in each best value).
	"""
	def __init__(self, evagg, name):
		"""Constructor

		evagg  - global evaluations aggregator, which traces this partial aggrigator
		name  - aggregator name in the format:  <measure>/<algname>/<netname>,
			<netname> includes pathid

		levels  - resulting aggregated evaluations for the cluster / community levels

		fixed  - whether all items are aggregated and summarization is performed
		bestlev  - cluster level with the best value, defined for the finalized evaluations
		"""
		assert name.count(SEPNAMEPART) == 2, 'Name format validation failed: ' + name
		self.name = name
		# Aggregation data
		self.levels = {}  # Name: LevelStat

		self.fixed = False  # All related jobs have been aggregated
		self.bestlev = None  # Best level, format: (name, value)

		# Register this aggregator in the global results aggregator
		evagg.register(self)  # shufagg: isfixed  - dict


	def addraw(self, resfile, lev, val):
		"""Add subsequent value to the aggregation

		resfile  - full file name of the processing evaluation result
		lev  - processing level (can be any string, which is a part of the file name)
		val  - the real value to be aggregated
		"""
		# Aggregate over cluster levels by shuffles distinguishing each set of algorithm params (if exists)
		# [Evaluate max avg among the aggregated level and transfer it to the instagg as final result]
		assert not self.fixed, 'Only non-fixed aggregator can be modified'
		# Validate lev to guarantee it does not contain shuffle part
		assert lev.find(SEPNAMEPART) == -1, 'Level name should not contain shuffle part'

		# Extract algorithm params if exist from the 'taskoutp' job param
		taskname = os.path.splitext(os.path.split(resfile)[1])[0]
		# Validate taskname, i.e. validate that shuffles aggregator is called for its network
		assert taskname == self.name[self.name.rfind('/') + 1:], (
			'taskname validation failed: "{}" does not belong to "{}"'.format(taskname, self.name))
		algpars = ''  # Algorithm params
		ipb = taskname.find(SEPPARS, 1)  # Index of params begin. Params separator can't be the first symbol of the name
		if ipb != -1 and ipb != len(taskname) - 1:
			# Find end of the params
			ipe = filter(lambda x: x >= 0, [taskname[ipb:].rfind(c) for c in (SEPINST, SEPPATHID, SEPSHF)])
			if ipe:
				ipe = min(ipe) + ipb  # Conside ipb offset
			else:
				ipe = len(taskname)
			algpars = taskname[ipb:ipe]
		# Update statistics
		levname = lev
		if algpars:
			levname = SEPNAMEPART.join((levname, algpars))  # Note: SEPNAMEPART never occurs in the filename, levname
		#print('addraw lev: {}, aps: {}, taskname: {}'.format(levname, algpars, taskname))
		levstat = self.levels.get(levname)
		if levstat is None:
			levstat = ItemsStatistic(levname)
			self.levels[levname] = levstat
		levstat.add(val)


	def stat(self):
		"""Accumulated statistics"""
		assert self.fixed, 'Only fixed aggregator has final statistics'
		return self.bestlev[1] if self.bestlev else None


	def fix(self, task=None):
		"""Fix (finalize) statistics accumulation and produce the summary of the results

		task  - the task that calls results fixation
		"""
		if self.levels:
			itlevs = iter(viewitems(self.levels))
			self.bestlev = itlevs.next()
			self.bestlev[1].fix()
			for name, val in itlevs:
				val.fix()
				if val.avg > self.bestlev[1].avg:
					self.bestlev = (name, val)
		self.fixed = True
		if self.bestlev is None or self.bestlev[1].avg is None:
			print('WARNING, "{}" has no defined results'.format(self.name))
		# Trace best lev value for debugging purposes
		elif _DEBUG_TRACE:
		#else:
			print('Best lev of {}:\t{} = {:.6f}'.format(
				self.name[self.name.rfind('/') + 1:], self.bestlev[0], self.bestlev[1].avg))
		##	val = self.bestlev[1]
		##	print('{} bestval is {}: {} (from {} up to {}, sd: {})'
		##		.format(self.name, self.bestlev[0], val.avg, val.min, val.max, val.sd))


class EvalsAgg(object):
	"""Evaluations aggregator for the specified measure"""
	def __init__(self, measure):
		"""Constractor

		measure  - target measure for this aggrigator

		partaggs  - partial aggregators to be processed
		aevals  - resulting algorithm evaluations
		"""
		self.measure = measure
		self.partaggs = []

		self.netsev = {}  # Global network evaluations in the format: net_name: alg_eval
		self.algs = set()


	def aggregate(self):
		"""Aggregate results over all partial aggregates and output them"""
		# Show warning for all non-fixed registered instances over what the aggregation is performed.
		# Evaluate max among all avg value among instances of each network with particular params. - 3rd element of the task name
		# Evaluate avg and range over all network instances with the same base name (and params),
		# #x and ^x are processed similarly as instances.
		nameps = False  # Parameters are used in the name
		for inst in self.partaggs:
			if not inst.fixed:
				print('WARNING, shuffles aggregator for task "{}" was not fixed on final aggregation'
					.format(inst.name), file=sys.stderr)
				inst.fix()
			measure, algname, netname = inst.name.split(SEPNAMEPART)
			#print('Final aggregate over net: {}, pathid: {}'.format(netname, pathid))
			# Remove instance id if exists (initial name does not contain params and pathid)
			# ATTENTION: fetched ids from the name include prefixes
			netname, apars, insid, shid, pathid = parseName(netname, True)
			assert not shid, 'Shuffles should already be aggregated'
			# Take average over instances and shuffles for each set of alg params
			# and the max for alg params among the obtained results
			if apars:
				nameps = True
				netname = SEPNAMEPART.join((netname, apars))
			# Maintain list of all evaluated algs to output results in the table format
			self.algs.add(algname)
			# Update global network evaluation results
			algsev = self.netsev.setdefault(netname, {})
			netstat = algsev.get(algname)
			if netstat is None:
				netstat = ItemsStatistic(algname)
				algsev[algname] = netstat
			netstat.addstat(inst.stat())  # Note: best result for each network with the same alg params can correspond to different levels
		# For each network retain only best result among all algorithm parameters
		naparams = {}  # Algorithm parameters for the network that correspond to the best result, format:  AlgName: AlgParams
		if nameps:
			netsev = {}
			for net, algsev in viewitems(self.netsev):
				# Cut params from the network name
				pos = net.find(SEPNAMEPART)
				if pos != -1:
					apars = net[pos+1:]
					net = net[:pos]
				else:
					apars = None
				# Sync processing network and alg params
				napars = naparams.setdefault(net, {})
				# Retain only the highest value among params
				uaev = netsev.setdefault(net, {})
				for alg, netstat in viewitems(algsev):
					netstat.fix()  # Process aggregated results
					uns = uaev.get(alg)
					#print('uns.avg: {:.6}, netstat.avg: {:.6}'.format(uns.avg if uns else None, netstat.avg))
					if not uns or uns.avg < netstat.avg:
						uaev[alg] = netstat
						napars[alg] = apars

			self.netsev = netsev
		# Remove partial aggregations
		self.partaggs = None

		# Order available algs names
		self.algs = sorted(self.algs)
		# Output aggregated results for this measure for all algorithms
		resbase = RESDIR + self.measure
		with open(resbase + EXTAGGRES, 'a') as fmeasev, open(resbase + EXTAGGRESEXT, 'a') as fmeasevx:
			# Append to the results and extended results
			#timestamp = datetime.utcnow()
			fmeasev.write('# --- {}, output:  Q_avg\n'.format(TIMESTAMP_START_STR))  # format = Q_avg: Q_min Q_max, Q_sd count;
			# Extended output has notations in each row
			# Note: print() unlike .write() outputs also ending '\n'
			print(TIMESTAMP_START_HEADER, file=fmeasevx)
			header = True  # Output header
			for net, algsev in viewitems(self.netsev):
				if header:
					fmeasev.write('# <network>')
					for alg in self.algs:
						fmeasev.write('\t{}'.format(alg))
					fmeasev.write('\n')
					# Brief header for the extended results
					fmeasevx.write('# <network>\n#\t<alg1_outp>\n#\t<alg2_outp>\n#\t...\n')
					header = False
				algsev = iter(sorted(viewitems(algsev), key=lambda x: x[0]))
				ialgs = iter(self.algs)
				firstcol = True
				# Algorithms and their params for the best values on this network
				algspars = naparams.get(net)
				# Output aggregated network evaluation for each algorithm
				for alg in ialgs:
					# Output row header it required
					if firstcol:
						fmeasev.write(net)
						fmeasevx.write(net)
						firstcol = False
					try:
						aev = algsev.next()
					except StopIteration:
						# Write separators till the end
						fmeasev.write('\t')
						for alg in ialgs:
							fmeasev.write('\t')
					else:
						# Check whether to show evaluated alg results now or later
						if aev[0] == alg:
							val = aev[1]
							if not val.fixed:
								val.fix()  # Process aggregated results
							fmeasev.write('\t{:.6f}'.format(val.avg))
							if algspars:
								napars = algspars.get(alg)
							else:
								napars = None
							# Q is taken as weighted average for best values per each instance,
							# where best is defined as highest average value among all levels in the shuffles.
							# Min is min best avg among shuffles for each instance, max is max best avg.
							# ATTENTION: values that can be None can't be represented as .6f, but can be as .6
							fmeasevx.write('\n\t{}>\tQ: {:.6f} ({:.6f} .. {:.6f}), s: {:.6}, count: {}, fails: {},'
								' d(shuf): {:.6}, s(shuf): {:.6}, count(shuf): {}, fails(shuf): {}'
								.format(alg + (napars.join((' (', ')')) if napars else '')
								, val.avg, val.min, val.max, val.sd, val.count, val.invals
								, val.statDelta, val.statSD, val.statCount, val.invstats))
						else:
							# Skip this alg
							fmeasev.write('\t')
				fmeasev.write('\n')
				fmeasevx.write('\n')


	def register(self, shfagg):
		"""Register new partial aggregator, shuffles aggregator"""
		measure = shfagg.name.split(SEPNAMEPART, 1)[0]
		assert measure == self.measure, (
			'This aggregator serves "{}" measure, but "{}" is registering'
			.format(self.measure, measure))
		self.partaggs.append(shfagg)


def aggEvaluations(respaths):
	"""Aggregate evaluations over speified paths of results.
	Results are appended to the files of the corresponding aggregated measures.

	respaths  - iterable container of evaluated reults paths
	"""
	print('Starting evaluation results aggregation ...')
	evalaggs = {}  # Evaluation aggregators per measures:  measure: evalagg
	# Process specified pahts
	for path in respaths:
		for resfile in glob.iglob(path):
			# Skip dirs if occurred
			if not os.path.isfile(resfile):
				continue
			## Fetch the measure be the file extension
			#measure = os.path.splitext(resfile)[1]
			#if not measure:
			#	print('WARNING, no any extension exists in the evaluatoin file: {}. Skipped.'.format(resfile))
			#	continue
			#measure = measure[1:]  # Skip extension separator

			# Fetch algname, measure, network name and pathid
			algname, measure, netname = resfile.rsplit('/', 2)
			algname = os.path.split(algname)[1]
			netname = os.path.splitext(netname)[0]
			assert measure in ('mod', 'nmi', 'nmi_s'), 'Invalid evaluation measure "{}" from file: {}'.format(measure, resfile)

			# Fetch corresponding evaluations aggregator
			eagg = evalaggs.get(measure)
			if not eagg:
				eagg = EvalsAgg(measure)
				evalaggs[measure] = eagg
			with open(resfile, 'r') as finp:
				partagg = ShufflesAgg(eagg, SEPNAMEPART.join((measure, algname, netname)))
				#print('Aggregating partial: ', partagg.name)
				for ln in finp:
					# Skip header
					ln = ln.lstrip()
					if not ln or ln[0] == '#':
						continue
					# Process values:  <value>\t<lev_with_shuffle>
					val, levname = ln.split(None, 1)
					levname = levname.split(SEPNAMEPART, 1)[0]  # Remove shuffle part from the levname if exists
					partagg.addraw(resfile, levname, float(val))
				partagg.fix()
	# Aggregate total statistics
	for eagg in viewvalues(evalaggs):
		eagg.aggregate()
	print('Evaluation results aggregation is finished.')


def evalGeneric(execpool, measure, algname, basefile, measdir, timeout, evaljob, resagg, pathidsuf='', tidy=True):
	"""Generic evaluation on the specified file
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	measure  - evaluating measure name
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
		Note: basefile itself never contains pathid
	measdir  - measure-identifying directory to store results
	timeout  - execution timeout for this task
	evaljob  - evaluatoin job to be performed on the evaluating file, signature:
		evaljob(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase)
	resagg  - results aggregator
	pathidsuf: str  - network path id prepended with the path separator
	tidy  - delete previously existent results. Must be False if a few apps output results into the same dir
	"""
	assert execpool and basefile and measure and algname, 'Parameters must be defined'
	assert not pathidsuf or pathidsuf[0] == SEPPATHID, 'pathidsuf must include separator'
	# Fetch the task name and chose correct network filename
	taskcapt = os.path.splitext(os.path.split(basefile)[1])[0]  # Name of the basefile (network or ground-truth clusters)
	ishuf = None if taskcapt.find(SEPSHF) == -1 else taskcapt.rsplit(SEPSHF, 1)[1]  # Separate shuffling index (with possible pathid) if exists
	assert taskcapt and not ishuf, 'The base file name must exists and should not be shuffled, file: {}, ishuf: {}'.format(
		taskcapt, ishuf)
	# Define index of the task suffix (identifier) start
	tcapLen = len(taskcapt)  # Note: it never contains pathid
	#print('Processing {}, pathidsuf: {}'.format(taskcapt, pathidsuf))

	# Resource consumption profile file name
	rcpoutp = ''.join((RESDIR, algname, '/', measure, EXTRESCONS))
	jobs = []
	# Traverse over directories of clusters corresponding to the base network
	for clsbase in glob.iglob(''.join((RESDIR, algname, '/', CLSDIR, escapePathWildcards(taskcapt), '*'))):
		# Skip execution of log files, leaving only dirs
		if not os.path.isdir(clsbase):
			continue
		# Note: algorithm parameters are present in dirs and handled here together with shuffles and sinstance / pathid
		clsname = os.path.split(clsbase)[1]  # Processing a cluster dir, which is a base name of the job, id part of the task name
		clsnameLen = len(clsname)

		# Skip cases when processing clusters does not have expected pathid
		if pathidsuf and not clsname.endswith(pathidsuf):
			continue
		# Skip cases when processing clusters have unexpected pathidsuf
		elif not pathidsuf:
			icnpid = clsname.rfind(SEPPATHID)  # Index of pathid in clsname
			if icnpid != -1 and icnpid + 1 < clsnameLen:
				# Validate pathid
				try:
					int(clsname[icnpid + 1:])
				except ValueError as err:
					# This is not the pathid, or this pathid has invalid format
					print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
					.format(SEPPATHID, clsname, err), file=sys.stderr)
					# Continue processing as ordinary clusters without pathid
				else:
					# Skip this clusters having unexpected pathid
					continue
		icnpid = clsnameLen - len(pathidsuf)  # Index of pathid in clsname

		# Filter out unexpected instances of the network (when then instance without id is processed)
		if clsnameLen > tcapLen and clsname[tcapLen] == SEPINST:
			continue

		# Fetch shuffling index if exists
		ish = clsname[:icnpid].rfind(SEPSHF) + 1  # Note: reverse direction to skip possible separator symbols in the name itself
		shuffle = clsname[ish:icnpid] if ish else ''
		# Validate shuffling index
		if shuffle:
			try:
				int(shuffle)
			except ValueError as err:
				print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
					.format(SEPSHF, clsname, err), file=sys.stderr)
				# Continue processing skipping such index
				shuffle = ''

		# Note: separate dir is created, because modularity is evaluated for all files in the target dir,
		# which are different granularity / hierarchy levels
		logsbase = clsbase.replace(CLSDIR, measdir)
		# Remove previous results if exist and required
		if tidy and os.path.exists(logsbase):
			shutil.rmtree(logsbase)
		if tidy or not os.path.exists(logsbase):
			os.makedirs(logsbase)

		# Skip shuffle indicator to accumulate values from all shuffles into the single file
		taskoutp = logsbase
		if shuffle:
			taskoutp = taskoutp.rsplit(SEPSHF, 1)[0]
			# Recover lost pathidsuf if required
			if pathidsuf:
				taskoutp += pathidsuf
		taskoutp = '.'.join((taskoutp, measure))  # evalext  # Name of the file with modularity values for each level
		if tidy and os.path.exists(taskoutp):
			os.remove(taskoutp)

		#shuffagg = ShufflesAgg(resagg, name=SEPNAMEPART.join((measure, algname, taskcapt, pathidsuf)))  # Note: taskcapt here without alg params
		taskname = os.path.splitext(os.path.split(taskoutp)[1])[0]
		shagg = ShufflesAgg(resagg, SEPNAMEPART.join((measure, algname, taskname)))
		task = Task(name=taskname, params=shagg, ondone=shagg.fix)  # , params=EvalState(taskcapt, )
		# Traverse over all resulting communities for each ground truth, log results
		for cfile in glob.iglob(escapePathWildcards(clsbase) + '/*'):
			if os.path.isdir(cfile):  # Skip dirs among the resulting clusters (extra/, generated by OSLOM)
				continue
			# Extract base name of the evaluating clusters level
			# Note: benchmarking algorithm output file names are not controllable and can be any, unlike the embracing folders
			jbasename = os.path.splitext(os.path.split(cfile)[1])[0]
			assert jbasename, 'The clusters name should exists'
			# Extand job caption with the executing task if not already contains and update the caption index
			# Skip pathid in clsname, because it is not present in jbasename
			pos = jbasename.find(clsname[:icnpid])
			# Define clusters level name as part of the jbasename
			if pos == -1:
				pos = 0
				jbasename = '_'.join((clsname[:icnpid], jbasename))  # Note: pathid is already included into clsname
			#elif pathidsuf:
			#	jbasename += pathidsuf
			clslev = jbasename[pos + icnpid:].lstrip('_-.')  # Note: clslev can be empty if jbasename == clsname[:icnpid]
			#print('Lev naming: clslev = {}, jbasename = {}'.format(clslev, jbasename))
			# Note: it is better to path clsname and shuffle separately to avoid redundant cut on evaluations processing
			#if shuffle:
			#	clslev = SEPNAMEPART.join((clslev, shuffle))

			#jobname = SEPNAMEPART.join((measure, algname, clsname))
			logfilebase = '/'.join((logsbase, jbasename))
			# pathid must be part of jobname, and  bun not of the clslev
			jobs.append(evaljob(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logfilebase))
	# Run all jobs after all of them were added to the task
	if jobs:
		for job in jobs:
			try:
				execpool.execute(job)
			except Exception as err:
				print('ERROR, "{}" job execution failed: {}. {}'
					.format(job.name, err, traceback.format_exc(8)), file=sys.stderr)
	else:
		print('WARNING, "{}" clusters from "{}" do not exist to be evaluated'
			.format(algname, basefile), file=sys.stderr)


def evalAlgorithm(execpool, algname, basefile, measure, timeout, resagg, pathidsuf=''):
	"""Evaluate the algorithm by the specified measure.
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
	measure  - target measure to be evaluated: {nmi, nmi_s, mod}
	timeout  - execution timeout for this task
	resagg  - results aggregator
	pathidsuf: str  - network path id prepended with the path separator
	"""
	assert not pathidsuf or pathidsuf.startswith(SEPPATHID), 'Ivalid pathidsuf: ' + pathidsuf
	if _DEBUG_TRACE:
		print('Evaluating {} for "{}" on base of "{}"...'.format(measure, algname, basefile))

	def evaljobMod(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase):
		"""Produce modularity evaluation job
		NOTE: all paths are given relative to the root benchmark directory.

		cfile  - clusters file to be evaluated
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		logsbase  - base part of the file name for the logs including errors

		return
			job  - resulting evaluating job
		"""
		#print('Starting evaljobMod with params:\t[basefile: {}]\n\tcfile: {}\n\tjobname: {}'
		#	'\n\ttask.name: {}\n\ttaskoutp: {}\n\tjobsuff: {}\n\tlogsbase: {}'
		#	.format(basefile, cfile, jobname, task.name, taskoutp, clslev, logsbase), file=sys.stderr)

		# Processing is performed from the algorithms dir
		args = ('./hirecs', '-e=../' + cfile, '../' + basefile)

		# Job post-processing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			result = job.proc.communicate()[0].decode()  # Read buffered stdout
			# Find require value to be aggregated
			targpref = 'mod: '
			# Match float number
			mod = parseFloat(result[len(targpref):])[0] if result.startswith(targpref) else None
			if mod is None:
				print('ERROR, job "{}" has invalid output format. Moularity value is not found in: {}'
					.format(job.name, result), file=sys.stderr)
				return

			# Transfer results to the embracing task if exists
			taskoutp = job.params['taskoutp']
			clslev = job.params['clslev']
			task.params.addraw(taskoutp, clslev, mod)  # Note: task.params is shuffles aggregator
			# Log results
			with open(taskoutp, 'a') as tmod:  # Append to the end
				if not os.fstat(tmod.fileno()).st_size:
					tmod.write('# Q\tlevel[/shuffle]\n')
					tmod.flush()
				# Define result caption
				shuffle = job.params['shuffle']
				if shuffle:
					clslev = SEPNAMEPART.join((clslev, shuffle))
				tmod.write('{}\t{}\n'.format(mod, clslev))

		return Job(name=SEPSHF.join((task.name, shuffle)), workdir=ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			# Output modularity to the proc PIPE buffer to be aggregated on postexec to avoid redundant files
			, stdout=PIPE, stderr=logsbase + EXTERR)


	def evaljobNmi(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase):
		"""Produce nmi evaluation job

		cfile  - clusters file to be evaluated
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		logsbase  - base part of the file name for the logs including errors

		return
			job  - resulting evaluating job


		Args example:
		[basefile: syntnets/networks/1K10/1K10.cnl]
		cfile: results/scp/clusters/1K10!k3/1K10!k3_1.cnl
		jobname: nmi_1K10!k3_1_scp
		task.name: nmi_1K10_scp
		taskoutp: results/scp/nmi/1K10!k3.nmi
		rcpoutp: results/scp/nmi.rcp
		clslev: 1
		shuffle:
		logsbase: results/scp/nmi/1K10!k3/1K10!k3_1
		"""
		# Update current environmental variables with LD_LIBRARY_PATH
		ldpname = 'LD_LIBRARY_PATH'
		ldpval = '.'
		ldpath = os.environ.get(ldpname, '')
		if not ldpath or not envVarDefined(value=ldpval, evar=ldpath):
			if ldpath:
				ldpath = ':'.join((ldpath, ldpval))
			else:
				ldpath = ldpval
			os.environ[ldpname] = ldpath

		# Processing is performed from the algorithms dir
		jobname = SEPSHF.join((task.name, shuffle))  # Name of the creating job
		args = ('../exectime', '-o=../' + rcpoutp, '-n=' + jobname, './gecmi', '../' + basefile, '../' + cfile)

		# Job post-processing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0].decode()
				nmi = float(result)  # Read buffered stdout
			except ValueError:
				print('ERROR, nmi evaluation failed for the job "{}": {}'
					.format(job.name, result), file=sys.stderr)
			else:
				# Transfer results to the embracing task if exists
				taskoutp = job.params['taskoutp']
				clslev = job.params['clslev']
				task.params.addraw(taskoutp, clslev, nmi)  # Note: task.params is shuffles aggregator
				# Log results
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.fstat(tnmi.fileno()).st_size:
						tnmi.write('# NMI\tlevel[/shuffle]\n')
						tnmi.flush()
					# Define result caption
					shuffle = job.params['shuffle']
					if shuffle:
						clslev = SEPNAMEPART.join((clslev, shuffle))
					tnmi.write('{}\t{}\n'.format(nmi, clslev))

		return Job(name=jobname, task=task, workdir=ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			, stdout=PIPE, stderr=logsbase + EXTERR)


	def evaljobNmiS(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase):
		"""Produce nmi_s evaluation job

		cfile  - clusters file to be evaluated
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		logsbase  - base part of the file name for the logs including errors

		return
			job  - resulting evaluating job
		"""
		# Processing is performed from the algorithms dir
		jobname = SEPSHF.join((task.name, shuffle))  # Name of the creating job
		args = ('../exectime', '-o=../' + rcpoutp, '-n=' + jobname, './onmi_sum', '../' + basefile, '../' + cfile)

		# Job post-processing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0].decode()
				nmi = float(result)  # Read buffered stdout
			except ValueError:
				print('ERROR, nmi_s evaluation failed for the job "{}": {}'
					.format(job.name, result), file=sys.stderr)
			else:
				# Transfer results to the embracing task if exists
				taskoutp = job.params['taskoutp']
				clslev = job.params['clslev']
				task.params.addraw(taskoutp, clslev, nmi)  # Note: task.params is shuffles aggregator
				# Log results
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.fstat(tnmi.fileno()).st_size:
						tnmi.write('# NMI_s\tlevel[/shuffle]\n')
						tnmi.flush()
					# Define result caption
					shuffle = job.params['shuffle']
					if shuffle:
						clslev = SEPNAMEPART.join((clslev, shuffle))
					tnmi.write('{}\t{}\n'.format(nmi, clslev))

		return Job(name=jobname, task=task, workdir=ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			, stdout=PIPE, stderr=logsbase + EXTERR)


	if measure == 'mod':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobMod, resagg, pathidsuf)
	elif measure == 'nmi':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobNmi, resagg, pathidsuf)
	elif measure == 'nmi_s':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobNmiS, resagg, pathidsuf, tidy=False)
	else:
		raise ValueError('Unexpected measure: ' + measure)
