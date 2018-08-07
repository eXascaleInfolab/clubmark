#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
:Description: Evaluation of results produced by each executed application.

	Resulting cluster/community structure is evaluated using extrinsic (NMI, NMI_s)
	and intrinsic (Q - modularity) measures considering overlaps.

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
# from collections import namedtuple
from subprocess import PIPE
# Queue is required to asynchronously save evaluated quality measures to the persistent storage
from multiprocessing import cpu_count, Process, Queue
try:
	import queue	# queue in Python3
except ImportError:  # Queue in Python2
	import Queue as queue


import h5py  # HDF5 storage
import numpy as np  # Required for the HDF5 operations

# from benchapps import  # funcToAppName,
from benchutils import viewitems, viewvalues, ItemsStatistic, parseFloat, parseName, \
	escapePathWildcards, envVarDefined, SyncValue, tobackup, \
	SEPPARS, SEPINST, SEPSHF, SEPPATHID, UTILDIR, ALGSDIR, \
	TIMESTAMP_START, TIMESTAMP_START_STR, TIMESTAMP_START_HEADER
from utils.mpepool import Task, Job, AffinityMask

# Identify type of the Variable-length ASCII (bytes) / UTF8 types for the HDF5 storage
try:
	# For Python3
	h5str = h5py.special_dtype(vlen=bytes)  # ASCII str, bytes
	h5ustr = h5py.special_dtype(vlen=str)  # UTF8 str
except NameError:  # bytes are not defined in Python2
	# For Python2
	h5str = h5py.special_dtype(vlen=str)  # ASCII str, bytes
	h5ustr = h5py.special_dtype(vlen=unicode)  #pylint: disable=E0602;  # UTF8 str

# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
RESDIR = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to ALGSDIR
CLSDIR = 'clusters/'  # Clusters directory for the resulting clusters of algorithms execution
# _QUALITY_STORAGE = 'quality.h5'  # Quality evaluation storage file name
_EXTERR = '.err'
#_EXTLOG = '.log'  # Extension for the logs
#_EXTELOG = '.elog'  # Extension for the unbuffered (typically error) logs
EXTEXECTIME = '.rcp'  # Resource Consumption Profile
EXTAGGRES = '.res'  # Aggregated results
EXTAGGRESEXT = '.resx'  # Extended aggregated results
SEPNAMEPART = '/'  # Job/Task name parts separator ('/' is the best choice, because it can not apear in a file name, which can be part of job name)

QMSRAFN = {}  # Specific affinity mask of the quality measures: str, AffinityMask;  qmsrAffinity
QMSINTRIN = set()  # Intrinsic quality measures requering input network instead of the ground-truth clustering
QMSRUNS = {}  # Run these stochastic quality measures specified number of times

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
# 		nmi_max  - NMI multiresolution overlapping (gecmi) normalized by max (default)
# 		nmi_sqrt  - NMI multiresolution overlapping (gecmi) normalized by sqrt
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


class QualityEntry(object):
	"""Quality evaluations etry to be saved to the persistent storage"""
	def __init__(self, measures, appname, inpnet, clsname):  #, appargs=None, level=0, instance=0, shuffle=0):
		"""Quality evaluations to be saved

		measures: dict  - quality measures to be saved
		appname: str  - application (clustering algorithm) name
		inpnet: str  - full network (dataset) name
		clsname: str:  - the file name of the evaluated clustering (including alg params, net inst, shuf, etc.)
		"""
		# appargs: str  - non-deault application parameters packed into ASCII encoded str if any
		# level: uint32  - index of the level to distinguish clustering hierarchy levels if any.
		# 	NOTE: For some algorithms levels are defined by the parameter(s) variation,
		# 	for example Ganxis varies r = 0.01 .. 0.5 by default
		# instance: unit8  - network instance if any, actual for the synthetic networks with the same params,
		# 	natural 0 number
		# shuffle: unit8  - network shuffle if any, actual for the shuffled networks, natural 0 number
		# assert (isinstance(measures, dict) and isinstance(appname, str) and isinstance(netname, str)
		# 	and (appargs is None or isinstance(appargs, str)) and isinstance(levhash, int)
		# 	and isinstance(instance, int) and instance >= 0 and isinstance(shuffle, int) and shuffle >= 0
		# 	), ('Parameters validation failed  measures type: {}, appname: {}, netname: {}, appargs: {}'
		# 	', levhash: {}, instance: {}, shuffle: {}'.format(type(measures)
		# 	, appname, netname, appargs, levhash, instance, shuffle))
		assert (isinstance(measures, dict) and isinstance(appname, str) and isinstance(inpnet, str)
			and isinstance(clsname, str)), ('Parameters validation failed;  measures type: {}'
			', appname: {}, inpnet: {}, clsname: {}'.format(type(measures).__name__, appname, inpnet, clsname))
		self.measures = measures
		self.appname = appname
		# self.inpdir =
		# self.netname =

		# self.appargs = appargs
		# self.level = level
		# self.instance = instance
		# self.shuffle = shuffle


	def __str__(self):
		"""String conversion"""
		return ', '.join((str(self.measures),
			', '.join([': '.join((name, str(val))) for name, val in viewitems(self.__dict__) if name != 'measures'])))


# class DataPool(object):

# 	def __init__(self, queue):
# 		self._queue = queue
# 		self._active = Value(ctypes.c_bool, True)


# 	def save(self, qualentry, timeout=None):  # appname, appargs
# 		"""Save evaluated quality measures to the persistent store

# 		qualentry  - evaluated quality measures by the specified app on the
# 			specified dataset to be saved
# 		timeout  - blocking timeout if the queue is full, None or >= 0 sec;
# 			None - wait forewer until the queue will have free slots
# 		"""
# 		assert isinstance(qualentry, QualityEntry), 'Unexpected type of the data'
# 		if not self._active.value:
# 			print('WARNING, the persistency layer is shutting down discarding'
# 				' the saving for ({}).'.format(str(qualentry)), file=sys.stderr)
# 			return
# 		try:
# 			self._queue.put(qualentry, timeout=timeout)  # Note: evaluators should not be delayed
# 		except Exception as err:
# 			print('WARNING, the quality entry ({}) saving is cancelled: {}'.format(str(qualentry), err))
# 			# Rerase the exception if interruption is not by the timeout
# 			if not (isinstance(err, queue.Full) or isinstance(err, AssertionError)):
# 				raise


# 	def deactivate(self):
# 		self._active.value = False


def saveQuality(qsqueue, qentry):
	"""Save quality entry int the Quality Saver queue

	Args:
		qsqueue: Queue  - quality saver queue
		qentry: QualityEntry  - quality entry to be saved
	"""
	assert isinstance(qsqueue, Queue) and isinstance(qentry, QualityEntry), 'Unexpected type of the arguments'
	try:
		qsqueue.put_nowait(qentry)  # Note: evaluators should not be delayed
	except Exception as err:
		print('WARNING, the quality entry ({}) saving is cancelled: {}'.format(str(qentry), err, file=sys.stderr))
		# Rerase the exception if interruption is not by the full filling
		# Note: IOError: Broken pipe is raised for the closed queue
		if not isinstance(err, queue.Full):
			raise


class QualitySaver(object):
	# Max number of the buffered items in the queue that have not been processed
	# before blocking the caller on appending more items
	# Should not be too much to save them into the persistent store on the
	# program termination or any external interruptions
	QUEUE_SIZEMAX = max(128, cpu_count() * 2)  # At least 128 or twice the number of the logical CPUs in the system
	# LATENCY = 1  # Latency in seconds

	"""Quality evaluations serializer to the persistent sotrage"""
	@staticmethod
	def __datasaver(qualsaver):
		"""Worker process function to save data to the persistent storage
	
		qualsaver  - quality saver wrapper containing the storage and queue
			of the evaluating measures
		"""
		while qualsaver._active or not qualsaver.queue.empty():
			# TODO: fetch QualityEntry item, not just Measures
			try:
				# qms = qualsaver.queue.get(True, LATENCY)  # Measures to be stored
				qms = qualsaver.queue.get()  # Measures to be stored
				assert isinstance(qms, QualityEntry), 'Unexpected type of the quality entry: ' + type(qms).__name__
			# for qname, qval in viewitems(qms.__dict__):
			# 	# Skip undefined quality measures nad store remained {qname: qval}
			# 	if qval is None:
			# 		continue
			# 	# TODO: save data to HDF5
			# 	# pscan01 = apps.require_dataset('Pscan01'.encode(),shape=(0,),dtype=h5py.special_dtype(vlen=bytes),chunks=(10,),maxshape=(None,),fletcher32=True)
			except Exception as err:
				# Note: IOError: Broken pipe is raised for the closed queue
				if not isinstance(err, queue.Empty):
					raise
				break
				

	def __init__(self, seed, update=False, timeout=None):  # algs, qms, nets=None,
		"""Creating or open HDF5 storage and prepare for the quality measures evaluations

		Check whether the storage exists, copy/move old storage to the backup and
		create the new one if the storage is not exist.

		Arguments:
			seed: uint64  - benchmarking seed, natural number
			update: bool  - update existing storage creating if not exists, or create a new one backing up the existent
			timeout: float  - global operational timeout in seconds, None means no timeout

		Members:
			_persister: Process  - persister worker process
			queue: Queue  - multiprocess queue whose items are saved (persisted)
			storage: h5py.File  - HDF5 storage
			mrescons: list(str)  - meta data of resource consumption
			irescons: dict(resname: str, resindex: uint)  - back mapping of the resource consumption metadata
			_active: bool  - the storage is operational (the requests can be processed)
		"""
		# algs: iterable(str)  - evaluating clustering algorithms (names of the algorithms)
		# qms: iterable(str)  - computing quality measurs (names)
		# nets: iterable(str)  - input network names with pathid to be indexed or None, which means
		# 	the networks will be specified sequentially on the intrinsic measures computations
		# assert (isinstance(algs[0], str) and isinstance(qms[0], str) and (nets is None or isinstance(nets[0], str))
		# 	and isinstance(seed, int)), ('Invalid data types, algs: {}, qms: {}, nets: {}, seed: {}'
		# 	.format(type(algs).__name__, type(qms).__name__, type(nets).__name__, type(seed).__name__, ))
		# assert (isinstance(algs[0], str) and isinstance(qms[0], str) and (nets is None or isinstance(nets[0], str))
		# 	and isinstance(seed, int)), ('Invalid data types, algs: {}, qms: {}, nets: {}, seed: {}'
		# 	.format(type(algs).__name__, type(qms).__name__, type(nets).__name__, type(seed).__name__, ))
		assert isinstance(seed, int) and (timeout is None or timeout >= 0), 'Invalid seed type: {}'.format(type(seed).__name__)
		# Open or init the HDF5 storage
		self.timeout = timeout
		self._persister = None
		self.queue = None
		self.storage = None  # Persistent storage object (file)
		timefmt = '%y%m%d-%H%M%S'  # Start time of the benchmarking, time format: YYMMDD_HHMMSS
		timestamp = time.strftime(timefmt, TIMESTAMP_START)  # Timestamp string
		seedstr = str(seed)
		storage = '/'.join((RESDIR, 'measures_', seedstr, '.h5'))  # File name of the HDF5.storage
		ublocksize = 512  # Userblock size in bytes
		ublocksep = ':'  # Userblock vals separator
		if os.path.isfile(storage):
			# Read userblock: seed and timestamps, validate new seed and estimate whether
			# there is enought space for one more timestamp
			if update:
				with open(storage, 'r+b') as fstore:  # Open file for R/W in binary mode
					# Note: userblock contains '<seed>:<timestamp1>:<timestamp2>...',
					# where timestamp has timefmt
					ublocksize = fstore.userblock_size
					ublock = fstore.read(ublocksize).rstrip('\0')
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
							fstore.write(ublocksep)  # Note: initially userblock is filled with 0
							fstore.write(timestamp)
						else:
							update = False
							print('WARNING, {} can not be updated because the userblock is already full.'
								' A new storage will be created.'.format(storage), file=sys.stderr)
			bcksftime = SyncValue(ubparts[-1])  # Use last benchmarking start time
			tobackup(storage, False, synctime=bcksftime, move=not update)  # Copy/move to the backup
		elif update:
			update = False
			print('WARNING, the storage does not exist and can not be updated, created:', storage, file=sys.stderr)
		if not update:
			# Create the storage, fail if exists ('w-' or 'x')
			self.storage = h5py.File(storage, mode='w-', driver='core', libver='latest', userblock_size=ublocksize)
			self.storage.close()
			# Write the userblock
			if (self.storage.userblock_size
			and len(seedstr) + len(ublocksep) + len(timestamp) <= self.storage.userblock_size):
				with open(storage, 'r+b') as fstore:  # Open file for R/W in binary mode
					fstore.write(seedstr)
					fstore.write(ublocksep)  # Note: initially userblock is filled with 0
					fstore.write(timestamp)
					# Fill remained part with zeros to be sure that userblock is zeroized
					fstore.write('\0' * (self.storage.userblock_size - (len(seedstr) + len(ublocksep) + len(timestamp))))
			else:
				raise RuntimeError('ERROR, the userblock creation failed in the {}, userblock_size: {}'
					', initial data size: {} (seed: {}, sep: {}, timestamp:{})'.format(storage
					, self.storage.userblock_size, len(seedstr) + len(ublocksep) + len(timestamp)
					, len(seedstr), len(ublocksep), len(timestamp)))

		# Note: append mode is the default one; core driver is a memory-mapped file, block_size is default (64 Kb)
		self.storage = h5py.File(storage, mode='a', driver='core', libver='latest', userblock_size=ublocksize)
		# Initialize or update metadata and groups
		# rescons meta data (h5str array)
		try:
			self.mrescons = [b.encode() for b in self.storage['rescons.inf'][()]]
		except IndexError:
			self.mrescons = ['ExecTime', 'CPU_time', 'RSS_peak']
			# Note: None in maxshape means resizable, fletcher32 used for the checksum
			self.storage.create_dataset('rescons.inf', shape=(len(self.mrescons),)
				, dtype=h5str, data=[s.decode() for s in self.mrescons], fletcher32=True)  # fillvalue=''
		# # Note: None in maxshape means resizable, fletcher32 used for the checksum,
		# # exact used torequire shape and type to match exactly
		# metares = self.storage.require_dataset('rescons.meta', shape=(len(self.mrescons),), dtype=h5str
		# 	, data=self.mrescons, exact=True, fletcher32=True)  # fillvalue=''
		#
		# rescons str to the index mapping
		self.irescons = {s: i for i, s in enumerate(self.mrescons)}

		self._active = True  # The storage is operational

		self.queue = None  # Multiprocess queue is created on the enter

		# self.algs = {alg: self.storage.require_group('algs/' + alg) for alg in algs}  # Datasets for each algorithm holding params
		# 
		# rcrows0 = 64
		# rccols = 6
		# appsdir = self.storage.require_group('apps')  # Applications / algorithms
		# for app in apps:
		# 	# Open or create dataset for each app
		# 	# Allocate chunks of 10 items starting with empty dataset and with possibility
		# 	# to resize up to 500 items (params combinations)
		# 	self.apps[app] = appsdir.require_dataset(app, shape=(0,), dtype=h5py.special_dtype(vlen=_h5str)
		# 		, chunks=(10,), maxshape=(500,))  # , maxshape=(None,), fletcher32=True
		# self.evals = self.storage.require_group('evals')  # Quality evaluations dir (group)


	def __del__(self):
		"""Destructor"""
		self._active = False
		if not self.queue.empty():
			print('WARNING, terminating the persistency layer with {} queued data entries, call stack: {}'
				.format(self.queue.qsize(), traceback.format_exc(5)), file=sys.stderr)
		try:
			self.queue.close()  # No more data can be put in the queue
			self._persister.join(self.timeout)
			self.queue.join_thread()
		finally:
			if self.storage is not None:
				self.storage.close()


	def __enter__(self):
		"""Context entrence"""
		self._active = True
		self.queue = Queue(self.QUEUE_SIZEMAX)  # Qulity measures persistance queue, data pool
		self._persister = Process(target=self.__datasaver, args=(self,))
		self._persister.start()
		return self


	def __exit__(self, etype, evalue, tracebk):
		"""Contex exit

		etype  - exception type
		evalue  - exception value
		tracebk  - exception traceback
		"""
		#self.apps.clear()
		#self.storage.close()
		self._active = False
		try:
			self.queue.close()  # No more data can be put in the queue
			self.queue.join_thread()
			self._persister.join(self.timeout)
		finally:
			self.storage.flush()  # Allow to reuse the instance in several context managers
		# Note: the exception (if any) is propagated if True is not returned here


def metainfo(afnmask=AffinityMask(1), intrinsic=False, multirun=1):
	"""Set some meta information for the executing evaluation measures

	afnstep: AffinityMask  - affinity mask
	intrinsic: bool  - whether the quality measure is intrinsic and requires input network
		instead of the ground-truth clustering
	multirun: uint8, >= 1  - perform multiple runs of this stochastic quality measure
	"""
	def decor(func):
		"""Decorator returning the original function"""
		assert isinstance(afnmask, AffinityMask) and multirun >= 1 and isinstance(multirun, int), (
			'Invalid arguments, affinity mask type: {}, multirun: {}'.format(type(afnmask).__name__, multirun))
		# QMSRAFN[funcToAppName(func)] = afnmask
		if afnmask.afnstep != 1:  # Save only quality measures with non-default affinity
			QMSRAFN[func] = afnmask
		if intrinsic:
			QMSINTRIN.add(func)
		if multirun >= 2:
			QMSRUNS[func] = multirun
		return func
	return decor


class NetParams(object):
	__slots__ = ('asym', 'pathid')

	def __init__(self, asym, pathid=''):
		"""Parameters of the input network

		asym: bool  - the input network might be assymetric (directed) and is specified by arcs ranther than edges
		pathid: str  - network path id
		"""
		assert isinstance(pathid, str), 'Unexpected format of the pathid: ' + type(pathid).__name__
		self.asym = asym
		self.pathid = pathid

	def __str__(self):
		"""String conversion"""
		return ', '.join([': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__])


# Note: default AffinityMask is 1 (logical CPUs, i.e. hardware threads)
def execXmeasures(execpool, args, qsqueue, cfname, inpfname, timeout
, cmres=False, netparams=None, irun=0, workdir=UTILDIR, task=None, seed=None):
	"""Quality measure executor

	execpool: ExecPool  - execution pool
	args: list(str)  - quality measures arguments
	qsqueue: Queue  - multiprocess queue of the quality results saver (persister)
	cfname: str  - filename of the clustering to be evaluated
	inpfname: str  - input dataset file name (ground-truth / input network for the ex/in-trinsic quality measure)
	timeout: uint  - execution timeout in seconds
	cmres: bool  - whether the cfname is a multi-resolution (multi-level) clusering
	netparams: NetParams  - network parameters, actual only if inpfname is the input network (for the intrinsic qmeasure)
	irun: uint8  - run id (iteration)
	workdir: str  - working directory of the quality measure (qmeasure location)
	task: Task  - owner (super) task
	seed: uint  - seed for the stochastic qmeasures
	"""
	#return jobsnum: uint  - the number of scheduled jobs
	assert execpool and isinstance(qsqueue, Queue) and isinstance(cfname, str
		) and isinstance(inpfname, str) and timeout >= 0 and (
		netparams is None or isinstance(netparams, NetParams)) and irun >= 0 and (
		task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\targs: {},\n\tqsqueue: {}'
		',\n\tcfname: {},\n\tinpfname: {},\n\ttimeout: {},\n\tcmres: {},\n\tnetparams: {}'
		',\n\tirun: {},\n\tworkdir: {},\n\ttask: {},\n\tseed: {}'
		.format(execpool, args, qsqueue, cfname, inpfname, timeout, cmres, netparams, irun, workdir, task, seed))
	pass


@metainfo(afnmask=AffinityMask(AffinityMask.NODE_CPUS, first=False), multirun=3)  # Note: multirun requires irun
def execGnmi(execpool, args, qualsaver, cfname, inpfname, timeout
, cmres=False, netparams=None, irun=0, workdir=UTILDIR, task=None, seed=None):
	"""Quality measure executor

	execpool: ExecPool  - execution pool
	args: list(str)  - quality measures arguments
	qualsaver: QualitySaver  - quality results saver (persister)
	cfname: str  - filename of the clustering to be evaluated
	inpfname: str  - input dataset file name (ground-truth / input network for the ex/in-trinsic quality measure)
	timeout: uint  - execution timeout in seconds
	cmres: bool  - whether the cfname is a multi-resolution (multi-level) clusering
	netparams: NetParams  - network parameters, actual only if inpfname is the input network (for the intrinsic qmeasure)
	irun: uint8  - run id (iteration)
	workdir: str  - working directory of the quality measure (qmeasure location)
	task: Task  - owner (super) task
	seed: uint  - seed for the stochastic qmeasures
	"""
	assert execpool and isinstance(qualsaver, QualitySaver) and isinstance(cfname, str
		) and isinstance(inpfname, str) and timeout >= 0 and (
		netparams is None or isinstance(netparams, NetParams)) and irun >= 0 and (
		task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\targs: {},\n\tqualsaver: {}'
		',\n\tcfname: {},\n\tinpfname: {},\n\ttimeout: {},\n\tcmres: {},\n\tnetparams: {}'
		',\n\tirun: {},\n\tworkdir: {},\n\ttask: {},\n\tseed: {}'
		.format(execpool, args, qualsaver, cfname, inpfname, timeout, cmres, netparams, irun, workdir, task, seed))


def execOnmi(execpool, args, qualsaver, cfname, inpfname, timeout
, cmres=False, netparams=None, irun=0, workdir=UTILDIR, task=None, seed=None):
	"""Quality measure executor

	execpool: ExecPool  - execution pool
	args: list(str)  - quality measures arguments
	qualsaver: QualitySaver  - quality results saver (persister)
	cfname: str  - filename of the clustering to be evaluated
	inpfname: str  - input dataset file name (ground-truth / input network for the ex/in-trinsic quality measure)
	timeout: uint  - execution timeout in seconds
	cmres: bool  - whether the cfname is a multi-resolution (multi-level) clusering
	netparams: NetParams  - network parameters, actual only if inpfname is the input network (for the intrinsic qmeasure)
	irun: uint8  - run id (iteration)
	workdir: str  - working directory of the quality measure (qmeasure location)
	task: Task  - owner (super) task
	seed: uint  - seed for the stochastic qmeasures
	"""
	assert execpool and isinstance(qualsaver, QualitySaver) and isinstance(cfname, str
		) and isinstance(inpfname, str) and timeout >= 0 and (
		netparams is None or isinstance(netparams, NetParams)) and irun >= 0 and (
		task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\targs: {},\n\tqualsaver: {}'
		',\n\tcfname: {},\n\tinpfname: {},\n\ttimeout: {},\n\tcmres: {},\n\tnetparams: {}'
		',\n\tirun: {},\n\tworkdir: {},\n\ttask: {},\n\tseed: {}'
		.format(execpool, args, qualsaver, cfname, inpfname, timeout, cmres, netparams, irun, workdir, task, seed))


@metainfo(intrinsic=True)  # Note: intrinsic causes interpretation of ifname as inpnet and reuqires netparams
def execImeasures(execpool, args, qualsaver, cfname, inpfname, timeout
, cmres=False, netparams=None, irun=0, workdir=UTILDIR, task=None, seed=None):
	"""Quality measure executor

	execpool: ExecPool  - execution pool
	args: list(str)  - quality measures arguments
	qualsaver: QualitySaver  - quality results saver (persister)
	cfname: str  - filename of the clustering to be evaluated
	inpfname: str  - input dataset file name (ground-truth / input network for the ex/in-trinsic quality measure)
	timeout: uint  - execution timeout in seconds
	cmres: bool  - whether the cfname is a multi-resolution (multi-level) clusering
	netparams: NetParams  - network parameters, actual only if inpfname is the input network (for the intrinsic qmeasure)
	irun: uint8  - run id (iteration)
	workdir: str  - working directory of the quality measure (qmeasure location)
	task: Task  - owner (super) task
	seed: uint  - seed for the stochastic qmeasures
	"""
	assert execpool and isinstance(qualsaver, QualitySaver) and isinstance(cfname, str
		) and isinstance(inpfname, str) and timeout >= 0 and (
		netparams is None or isinstance(netparams, NetParams)) and irun >= 0 and (
		task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\targs: {},\n\tqualsaver: {}'
		',\n\tcfname: {},\n\tinpfname: {},\n\ttimeout: {},\n\tcmres: {},\n\tnetparams: {}'
		',\n\tirun: {},\n\tworkdir: {},\n\ttask: {},\n\tseed: {}'
		.format(execpool, args, qualsaver, cfname, inpfname, timeout, cmres, netparams, irun, workdir, task, seed))


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
		assert name.count(SEPNAMEPART) == 2, 'Name format validatoin failed: ' + name
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
		# [Evaluate max avg among the aggregated level and transfer it to teh instagg as final result]
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
		# Update statiscit
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
		# #x and ^x are processed similary as instances.
		nameps = False  # Parameters are used in the name
		for inst in self.partaggs:
			if not inst.fixed:
				print('WARNING, shuffles aggregator for task "{}" was not fixed on final aggregation'
					.format(inst.name), file=sys.stderr)
				inst.fix()
			measure, algname, netname = inst.name.split(SEPNAMEPART)
			#print('Final aggregate over net: {}, pathid: {}'.format(netname, pathid))
			# Remove instance id if exists (initial name does not contain params and pathid)
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
							# where best is defined as higest average value among all levels in the shuffles.
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


def evalGeneric(execpool, measure, algname, basefile, measdir, timeout, evaljob, resagg, pathid='', tidy=True):
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
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs.
		Note: pathid includes pathid separator
	tidy  - delete previously existent results. Must be False if a few apps output results into the same dir
	"""
	assert execpool and basefile and measure and algname, 'Parameters must be defined'
	assert not pathid or pathid[0] == SEPPATHID, 'pathid must include pathid separator'
	# Fetch the task name and chose correct network filename
	taskcapt = os.path.splitext(os.path.split(basefile)[1])[0]  # Name of the basefile (network or ground-truth clusters)
	ishuf = None if taskcapt.find(SEPSHF) == -1 else taskcapt.rsplit(SEPSHF, 1)[1]  # Separate shuffling index (with possible pathid) if exists
	assert taskcapt and not ishuf, 'The base file name must exists and should not be shuffled, file: {}, ishuf: {}'.format(
		taskcapt, ishuf)
	# Define index of the task suffix (identifier) start
	tcapLen = len(taskcapt)  # Note: it never contains pathid
	#print('Processing {}, pathid: {}'.format(taskcapt, pathid))

	# Resource consumption profile file name
	rcpoutp = ''.join((RESDIR, algname, '/', measure, EXTEXECTIME))
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
		if pathid and not clsname.endswith(pathid):
			continue
		# Skip cases whtn processing clusters have unexpected pathid
		elif not pathid:
			icnpid = clsname.rfind(SEPPATHID)  # Index of pathid in clsname
			if icnpid != -1 and icnpid + 1 < clsnameLen:
				# Validate pathid
				try:
					int(clsname[icnpid + 1:])
				except ValueError as err:
					# This is not the pathid, or this pathid has invalid format
					print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
					.format(SEPPATHID, clsname, err), file=sys.stderr)
					# Continue processing as ordinary clusters wthout pathid
				else:
					# Skip this clusters having unexpected pathid
					continue
		icnpid = clsnameLen - len(pathid)  # Index of pathid in clsname

		# Filter out unexpected instances of the network (when then instance without id is processed)
		if clsnameLen > tcapLen and clsname[tcapLen] == SEPINST:
			continue

		# Fetch shuffling index if exists
		ish = clsname[:icnpid].rfind(SEPSHF) + 1  # Note: reverse direction to skip possible separator symbols in the name itself
		shuffle = clsname[ish:icnpid] if ish else ''
		# Validate shufflng index
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
			# Recover lost pathid if required
			if pathid:
				taskoutp += pathid
		taskoutp = '.'.join((taskoutp, measure))  # evalext  # Name of the file with modularity values for each level
		if tidy and os.path.exists(taskoutp):
			os.remove(taskoutp)

		#shuffagg = ShufflesAgg(resagg, name=SEPNAMEPART.join((measure, algname, taskcapt, pathid)))  # Note: taskcapt here without alg params
		taskname = os.path.splitext(os.path.split(taskoutp)[1])[0]
		shagg = ShufflesAgg(resagg, SEPNAMEPART.join((measure, algname, taskname)))
		task = Task(name=taskname, params=shagg, ondone=shagg.fix)  # , params=EvalState(taskcapt, )
		# Traverse over all resulting communities for each ground truth, log results
		for cfile in glob.iglob(escapePathWildcards(clsbase) + '/*'):
			if os.path.isdir(cfile):  # Skip dirs among the resulting clusters (extra/, generated by OSLOM)
				continue
			# Extract base name of the evaluating clusters level
			# Note: benchmarking algortihm output file names are not controllable and can be any, unlike the embracing folders
			jbasename = os.path.splitext(os.path.split(cfile)[1])[0]
			assert jbasename, 'The clusters name should exists'
			# Extand job caption with the executing task if not already contains and update the caption index
			# Skip pathid in clsname, because it is not present in jbasename
			pos = jbasename.find(clsname[:icnpid])
			# Define clusters level name as part of the jbasename
			if pos == -1:
				pos = 0
				jbasename = '_'.join((clsname[:icnpid], jbasename))  # Note: pathid is already included into clsname
			#elif pathid:
			#	jbasename += pathid
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


def evalAlgorithm(execpool, algname, basefile, measure, timeout, resagg, pathid=''):
	"""Evaluate the algorithm by the specified measure.
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
	measure  - target measure to be evaluated: {nmi, nmi_s, mod}
	timeout  - execution timeout for this task
	resagg  - results aggregator
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs
		Note: pathid includes pathid separator
	"""
	assert not pathid or pathid[0] == SEPPATHID, 'pathid must include pathid separator'
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

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			result = job.proc.communicate()[0]  # Read buffered stdout
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
			, stdout=PIPE, stderr=logsbase + _EXTERR)


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

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0]
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
			, stdout=PIPE, stderr=logsbase + _EXTERR)


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

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0]
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
			, stdout=PIPE, stderr=logsbase + _EXTERR)


	if measure == 'mod':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobMod, resagg, pathid)
	elif measure == 'nmi':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobNmi, resagg, pathid)
	elif measure == 'nmi_s':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobNmiS, resagg, pathid, tidy=False)
	else:
		raise ValueError('Unexpected measure: ' + measure)
