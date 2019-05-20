#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description:  Multi-Process Execution Pool to schedule Jobs execution with per-job timeout,
optionally grouping them into Tasks and specifying optional execution parameters
considering NUMA architecture:
	- automatic rescheduling and *load balancing* (reduction) of the worker processes
		and on low memory condition for the *in-RAM computations* (requires
		[psutil](https://pypi.python.org/pypi/psutil), can be disabled)
	- *chained termination* of the related worker processes (started jobs) and
		non-started jobs rescheduling to satisfy *timeout* and *memory limit* constraints
	- automatic CPU affinity management and maximization of the dedicated CPU cache
		vs parallelization for a worker process
	- *timeout per each Job* (it was the main initial motivation to implement this
		module, because this feature is not provided by any Python implementation out of the box)
	- onstart/ondone *callbacks*, ondone is called only on successful completion
		(not termination) for both Jobs and Tasks (group of jobs)
	- stdout/err output, which can be redirected to any custom file or PIPE
	- custom parameters for each Job and respective owner Task besides the name/id

	Flexible API provides optional automatic restart of jobs on timeout, access to job's process,
	parent task, start and stop execution time and much more...


	Core parameters specified as global variables:
	_LIMIT_WORKERS_RAM  - limit the amount of memory consumption (<= RAM) by worker processes,
		requires psutil import
	_CHAINED_CONSTRAINTS  - terminate related jobs on terminating any job by the execution
		constraints (timeout or RAM limit)

	The load balancing is enabled when global variables _LIMIT_WORKERS_RAM and _CHAINED_CONSTRAINTS
	are set, jobs categories and relative size (if known) specified. The balancing is performed
	to use as much RAM and CPU resources as possible performing in-RAM computations and meeting
	timeout, memory limit and CPU cache (processes affinity) constraints.
	Large executing jobs are rescheduled for the later execution with less number of worker
	processes after the completion of smaller jobs. The number of workers is reduced automatically
	(balanced) on the jobs queue processing. It is recommended to add jobs in the order of the
	increasing memory/time complexity if possible to reduce the number of worker process
	terminations for the jobs execution postponing on rescheduling.

:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>,
	ScienceWise <http://sciencewise.info/>
:Date: 2015-07 v1, 2017-06 v2
"""
# Possible naming: pyexpool / mpepool

from __future__ import print_function, division  # Required for stderr output, must be the first import
import sys
import os
import time
# import ctypes  # Required for the multiprocessing Value definition
import types  # Required for instance methods definition
import traceback  # stacktrace
# To print a stacktrace fragment:
# traceback.print_stack(limit=5, file=sys.stderr) or
# print(traceback.format_exc(5), file=sys.stderr)
import subprocess
import errno
# # Async Tasks management
# import threading  # Used only for the concurrent Tasks termination by timeout
# import signal  # Required for the correct handling of KeyboardInterrupt: https://docs.python.org/2/library/thread.html
import itertools  # chain

from multiprocessing import cpu_count, Lock  #, Queue  #, active_children, Value, Process
from collections import deque
from math import sqrt

# Consider time interface compatibility with Python before v3.3
if not hasattr(time, 'perf_counter'):
	time.perf_counter = time.time

# Required to efficiently traverse items of dictionaries in both Python 2 and 3
try:
	from future.utils import viewvalues, viewitems  #, viewkeys, viewvalues  # External package: pip install future
	from future.builtins import range  #, list
except ImportError:
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

	viewitems = lambda dct: viewMethod(dct, 'items')()
	#viewkeys = lambda dct: viewMethod(dct, 'keys')()
	viewvalues = lambda dct: viewMethod(dct, 'values')()

	# Replace range() implementation for Python2
	try:
		range = xrange
	except NameError:
		pass  # xrange is not defined in Python3, which is fine
# Optional Web User Interface
_WEBUI = True
__imperr = None  # Import error
if _WEBUI:
	try:
		# ATTENTION: Python3 newer treats imports as relative and results in error here if mpewui is a local module
		from mpewui import WebUiApp, UiCmdId, UiResOpt, UiResCol, SummaryBrief
	except ImportError as wuerr:
		try:
			# Note: this case should be the second because explicit relative imports cause various errors
			# under Python2 and Python3, which complicates their handling
			from .mpewui import WebUiApp, UiCmdId, UiResOpt, UiResCol, SummaryBrief
		except ImportError as wuerr:
			__imperr = wuerr  # Note: exceptions are local in Python 3
			_WEBUI = False

# Limit the amount of memory consumption by worker processes.
# NOTE:
#  - requires import of psutils
#  - automatically reduced to the RAM size if the specified limit is larger
_LIMIT_WORKERS_RAM = True
if _LIMIT_WORKERS_RAM:
	try:
		import psutil
	except ImportError as lwerr:
		__imperr = lwerr  # Note: exceptions are local in Python 3
		_LIMIT_WORKERS_RAM = False


def timeheader(timestamp=time.gmtime()):
	"""Timestamp header string

	timestamp  - timestamp

	return  - timestamp string for the file header
	"""
	assert isinstance(timestamp, time.struct_time), 'Unexpected type of timestamp'
	# ATTENTION: MPE pool timestamp [prefix] intentionally differs a bit from the
	# benchmark timestamp to easily find/filter each of them
	return time.strftime('# ----- %Y-%m-%d %H:%M:%S ' + '-'*30, timestamp)


# Note: import occurs before the execution of the main application, so show
# the timestamp to outline when the error occurred and separate re-executions
if not (_WEBUI and _LIMIT_WORKERS_RAM):
	print(timeheader(), file=sys.stderr)
	if not _WEBUI:
		print('WARNING, Web UI is disabled because the "bottle" module import failed: '
			, __imperr, file=sys.stderr)
	if not _LIMIT_WORKERS_RAM:
		print('WARNING, RAM constraints are disabled because the "psutil" module import failed: '
			, __imperr, file=sys.stderr)


# Use chained constraints (timeout and memory limitation) in jobs to terminate
# also related worker processes and/or reschedule jobs, which have the same
# category and heavier than the origin violating the constraints
_CHAINED_CONSTRAINTS = True

_RAM_SIZE = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024.**3  # RAM (physical memory) size in GB
# Dedicate at least 256 MB for the OS consuming not more than 98% of RAM
_RAM_LIMIT = _RAM_SIZE * 0.98 - 0.25  # Maximal consumption of RAM in GB (< _RAM_SIZE to avoid/reduce swapping)
# System app to set CPU affinity if required, should be preliminary installed
# (taskset is present by default on NIX systems)
_AFFINITYBIN = 'taskset'
_DEBUG_TRACE = False  # Trace start / stop and other events to stderr;  1 - brief, 2 - detailed, 3 - in-cycles


def secondsToHms(seconds):
	"""Convert seconds to hours, mins, secs

	seconds  - seconds to be converted, >= 0

	return hours, mins, secs
	"""
	assert seconds >= 0, 'seconds validation failed'
	hours = int(seconds // 3600)
	mins = int((seconds - hours * 3600) // 60)
	secs = seconds - hours * 3600 - mins * 60
	return hours, mins, secs


def inGigabytes(nbytes):
	"""Convert bytes to gigabytes"""
	return nbytes / (1024. ** 3)


def inBytes(gb):
	"""Convert bytes to gigabytes"""
	return gb * 1024. ** 3


def tblfmt(v, strpad=0):
	"""Table-like formatting of the value

	strpad: int  - string padding
	"""
	if isinstance(v, float):
		return '{:.3f}'.format(v)
	elif isinstance(v, int):
		return str(strpad).join(('{:', '}')).format(v)
	if v is None:
		v = '-'
	elif not isinstance(v, str):
		v = str(v)
	return v.rjust(strpad)


def applyCallback(callback, owner):
	"""Process the callback call

	Args:
		callback: function  - callback (self.onXXX)
		owner: str  - owner name of the callback (self.name), required only for tracing
	"""
	#assert callable(callback) and isinstance(owner, str), 'A valid callback and owner name are expected'
	try:
		callback()
	except Exception as err:  #pylint: disable=W0703
		print('ERROR in {}() callback of the "{}": {}, discarded. {}'
			.format(callback.__name__, owner, err, traceback.format_exc(5)), file=sys.stderr)


# NOTE: additional parameter(s) can be added to output additional virtual properties like duration,
# which can be implemented as bool parameter to emulate properties specified by propflt
def infodata(obj, propflt=None, objflt=None):
	"""Convert the object to the tuple filtering specified properties and itself

	Args:
		obj: XobjInfo  - the object to be filtered and converted to the tuple, supposed
			to be decorated with `propslist`
		propflt: tuple(prop: str)  - property filter to include only the specified properties
		objflt: dict(prop: str, val: UiResFilterVal)  - include the item
			only if the specified properties belong to the specified range,
			member items are processed irrespectively of the item inclusion

		NOTE: property names should exactly match the obj properties (including __slots__)

	Returns:
		tuple  - filtered properties of the task or None

	Raises:
		AttributeError  - propflt item does not belong to the JobInfo slots
	"""
	assert hasattr(obj, '__slots__'), 'The object should contain slots'
	# Pass the objflt or return None
	if objflt:
		for prop, pcon in viewitems(objflt):  # Property name and constraint
			# print('>>> prop: {}, cpon: {}; objname: {}, objpv: {}'.format(prop, pcon, obj.name, obj.__getattribute__(prop)))
			#assert isinstance(prop, str) and isinstance(pcon, UiResFilterVal
			# 	), 'Invalid type of arguments:  prop: {}, pflt: {}'.format(
			# 	type(prop).__name__, type(pcon).__name__)
			pval = None if prop not in obj else obj.__getattribute__(prop)
			# Use task name for the task property
			# Note: task resolution is required for the proper filtering
			if isinstance(pval, Task):
				pval = pval.name
			if _DEBUG_TRACE and pval is None:
				print('  WARNING, objflt item does not belong to the {}: {}'.format(
					type(obj).__name__, prop), file=sys.stderr)
			# Note: pcon is None requires non-None pval
			if (pcon is None and pval is None) or (pcon is not None and (
			(not pcon.opt and prop not in obj) or (pcon.end is None and pval != pcon.beg)
			or pcon.end is not None and (pval < pcon.beg or pval >= pcon.end))):
				# print('>>> ret None, 1:', prop not in obj, '2:', pcon.end is None and pval != pcon.beg
				# 	, '3:', pcon.end is not None, '4:', pval < pcon.beg or pval >= pcon.end)
				return None
	return tuple([tblfmt(obj.__getattribute__(prop)) for prop in (propflt if propflt else obj.iterprop())])  #pylint: disable=C0325


def infoheader(objprops, propflt):
	"""Form filtered header of the properties of the ObjInfo

	Args:
		objprops: iterable(str)  - object properties
		propflt: list(str) - properties filter

	Returns:
		tuple(str)  - filtered property names
	"""
	if propflt:
		opr = set(objprops)
		return tuple([h for h in propflt if h in opr])
	return tuple([h for h in objprops])
	# return tuple([h for h in objprops if not propflt or h in propflt])


def propslist(cls):
	"""Extends the class with properties listing capabilities
	ATTENTION: slots are listed in the order of declaration (to control the output order),
	computed properties are listed afterwards in the alphabetical order.

	Extensions:
	- _props: set  - all public attributes of the class
		and all __slots__ members even if the latter are underscored
	- `in` operator support added to test membership in the _props
	- json  - dict representation for the JSON serialization
	- iterprop() method to iterate over the properties present in _props starting
		from __slots__ in the order of declaration and then over the computed properties
		in the alphabetical order
	"""
	def contains(self, prop):
		"""Whether the specified property is present"""
		assert len(self._props) >= 2, 'At least 2 properties are expected'
		return self._props.endswith(' ' + prop) or self._props.find(prop + ' ') != -1  #pylint: disable=W0212


	def json(self):
		"""Serialize self to the JSON representation"""
		return {p: self.__getattribute__(p) if p != 'task' else self.__getattribute__(p).name for p in self.iterprop()}


	def iterprop(cls):
		"""Properties generator/iterator"""
		ib = 0
		ie = cls._props.find(' ')  #pylint: disable=W0212
		while ie != -1:
			yield cls._props[ib:ie]  #pylint: disable=W0212
			ib = ie + 1
			ie = cls._props.find(' ', ib)  #pylint: disable=W0212
		yield cls._props[ib:]  #pylint: disable=W0212

	# List all public properties in the _props:str attribute retaining the order of __slots__
	# and then defined computed properties.
	# Note: double underscored attribute can't be defined externally
	# since internally it is interpreted as _<ClsName>_<attribute>.
	#assert hasattr(cls, '__slots__'), 'The class should have slots: ' + cls.__name__
	cslots = set(cls.__slots__)
	cls._props = ' '.join(itertools.chain(cls.__slots__,  #pylint: disable=W0212
		[m for m in dir(cls) if not m.startswith('_') and m not in cslots]))  # Note: dir() list also slots
	# Define required methods
	# ATTENTION: the methods are bound automatically to self (but not to the cls in Python2)
	# since they are defined before the class is created.
	cls.__contains__ = contains
	cls.json = json
	cls.iterprop = types.MethodType(iterprop, cls)  # Note: required only in Python2 for the static methods
	return cls


@propslist
class JobInfo(object):
	"""Job information to be reported by the request

	ATTENTION: the class should not contain any public methods except the properties
		otherwise _props should be computed differently

	# Check `_props` definition
	>>> JobInfo(Job('tjob'))._props
	'name pid code tstart tstop memsize memkind task category duration'

	# Check `contains` binding
	>>> 'pid' in JobInfo(Job('tjob'))
	True
	>>> 'pi' in JobInfo(Job('tjob'))
	False

	# Check `iterprop` binding
	>>> JobInfo(Job('tjob')).iterprop().next() == 'name'
	True

	# Check `iterprop` execution (generated iterator)
	>>> ' '.join([p for p in JobInfo(Job('tjob')).iterprop()]) == JobInfo(Job('tjob'))._props
	True
	"""
	__slots__ = ('name', 'pid', 'code', 'tstart', 'tstop', 'memsize', 'memkind', 'task', 'category')

	def __init__(self, job, tstop=None):
		"""JobInfo initialization

		Args:
			job: Job  - a job from which the info is fetched
			tstop: float  - job termination time, actual for the terminating deferred jobs
		"""
		assert isinstance(job, Job), 'Unexpected type of the job: ' +  type(job).__name__
		self.name = job.name
		self.pid = None if not job.proc else job.proc.pid
		self.code = None if not job.proc else job.proc.returncode
		self.tstart = job.tstart
		self.tstop = job.tstop if job.tstop is not None else tstop
		# ATTENTION; JobInfo definitions should be synchronized with Job
		# Note: non-initialized slots are still listed among the attributes but yield `AttributeError` on access,
		# so they always should be initialized at least with None to sync headers with the content
		if _LIMIT_WORKERS_RAM:
			self.memsize = job.mem
			self.memkind = job.memkind
		else:
			self.memsize = None
			self.memkind = None
		self.task = job.task
		self.category = None if not _CHAINED_CONSTRAINTS else job.category
		# rsrtonto  # Restart on timeout
		# if _LIMIT_WORKERS_RAM:
		# 	wkslim  #wksmax


	@property
	def duration(self):
		"""Execution duration"""
		if self.tstop is not None:
			tlast = self.tstop
		else:
			tlast = time.perf_counter()
		return None if self.tstart is None else tlast - self.tstart


@propslist
class TaskInfo(object):
	"""Task information to be reported by the request

	ATTENTION: the class should not contain any public methods except the properties
		otherwise _props should be computed differently
	"""
	__slots__ = ('name', 'tstart', 'tstop', 'numadded', 'numdone', 'numterm', 'task')

	def __init__(self, task):
		"""TaskInfo initialization

		Args:
			task: Task  - a task from which the info is fetched
		"""
		assert isinstance(task, Task), 'Unexpected type of the task: ' + type(task).__name__
		self.name = task.name
		self.tstart = task.tstart
		self.tstop = task.tstop
		self.numadded = task.numadded
		self.numdone = task.numdone
		self.numterm = task.numterm
		self.task = task.task  # Owner (super) task


	@property
	def duration(self):
		"""Execution duration"""
		return None if self.tstart is None else (self.tstop if self.tstop is not None
			else time.perf_counter()) - self.tstart


class TaskInfoExt(object):
	"""Task information extended with member items (subtasks/jobs)"""
	__slots__ = ('props', 'jobs', 'subtasks')

	def __init__(self, props, jobs=None, subtasks=None):
		"""Initialization of the extended task information

		Args:
			props: tuple(header: iterable, values: iterable)  - task properties
			jobs: list(header: iterable, values1: iterable, values: iterable...)  - member jobs properties
			subtasks: list(TaskInfoExt)  - member tasks (subtasks) info
		"""
		self.props = props
		self.jobs = jobs
		self.subtasks = subtasks


def tasksInfoExt(tinfe0, propflt=None, objflt=None):
	"""Form hierarchy of the extended information about the tasks

	Args:
		tinfe0: dict(Task, TaskInfoExt)  - bottom level of the hierarchy (tasks having jobs)
		propflt: list(str)  - properties filter
		objflt: dict(str, UiResFilterVal)  - objects (tasks/jobs) filter

	Returns:
		dict(Task, TaskInfoExt)  - resulting hierarchy of TaskInfoExt
	"""
	ties = dict()  # dict(Task, TaskInfoExt) - Tasks Info hierarchy
	for task, tie in viewitems(tinfe0):
		# print('> Preparing for the output task {} (super-task: {}), tie {} jobs and {} subtasks'.format(
		# 	task.name, '-' if not task.task else task.task.name,  0 if not tie.jobs else len(tie.jobs)
		# 	, 0 if not tie.subtasks else len(tie.subtasks))
		# 	, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		if task.task is None:
			# Add or extend with jobs a root task
			# Note: the task can be already initialized if it has subtasks
			tinfe = ties.get(task)
			if tinfe is None:
				ties[task] = tie
			else:
				tinfe.jobs = tie.jobs
				assert tinfe.props[1] == tie.props[1], task.name + ' task properties desynchronized'
		else:
			# print('>> task {} (super-task: {})'.format(task.name, task.task.name), file=sys.stderr)
			while task.task is not None:
				task = task.task
				newtie = ties.get(task)
				if newtie is None:
					# Add new super-task to the hierarchy
					# Note: infodata() should not yield None here
					newtie = tinfe0.get(task)
					# It is possible that the super-task has no any [failed] jobs
					# and, hence, is not present in tinfe0
					if newtie:
						assert newtie.subtasks is None, (
							'New super-task {} should not have any subtasks yet'.format(task.name))
						newtie.subtasks = [tie]
					else:
						tdata = infodata(TaskInfo(task), propflt, objflt)
						newtie = TaskInfoExt(props=None if not tdata else
							(infoheader(TaskInfo.iterprop(), propflt), tdata)  #pylint: disable=E1101
							, subtasks=[tie])
					ties[task] = newtie
					# print('>> New subtask {} added to {}'.format(tie.props[1][0], task.name)
					# 	, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
				else:
					# Note: subtasks can be None if this task contains jobs
					if newtie.subtasks is None:
						newtie.subtasks = [tie]
					else:
						newtie.subtasks.append(tie)  # Omit the header
					# print('>> Subtask {} added to {}: {}'.format(tie.props[1][0], task.name, tie.subtasks)
					# 	, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
				tie = newtie
	return ties


def printDepthFirst(tinfext, cindent='', indstep='  ', colsep=' '):
	"""Print TaskInfoExt hierarchy using the depth first traversing

	Args:
		tinfext: TaskInfoExt  - extended task info to be unfolded and printed
		cindent: str  - current indent for the output hierarchy formatting
		indstep: str  - indent step for each subsequent level of the hierarchy
		colsep: str  - column separator for the printing variables (columns)
	"""
	strpad = 9  # Padding of the string cells
	# Print task properties (properties header and values)
	for props in tinfext.props:
		print(cindent, colsep.join([tblfmt(v, strpad) for v in props]), sep=''
			, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
	# assert isinstance(tinfext, TaskInfoExt), 'Unexpected type of tinfext: ' + type(tinfext).__name__
	# Print task jobs and subtasks
	cindent += indstep
	if tinfext.jobs:  # Consider None
		for tie in tinfext.jobs:
			print(cindent, colsep.join([tblfmt(v, strpad) for v in tie]), sep=''
				, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
	# print('>> Outputting task {} with {} subtasks'.format(tinfext.props[1][0]
	# 	, 0 if not tinfext.subtasks else len(tinfext.subtasks)), file=sys.stderr)
	if tinfext.subtasks:  # Consider None
		for tie in tinfext.subtasks:
			printDepthFirst(tie, cindent=cindent, indstep=indstep, colsep=colsep)


class TaskInfoPrefmt(object):
	"""Preformatted Task info"""
	__slots__ = ('compound', 'ident', 'data')

	def __init__(self, data, ident=0, compound=None):
		"""Initialization of the pre-formated task info:

		data: list  - data to be displayed (property name/value)
		ident: uint  - current indentation
		compound: bool  - whether the item is a header of the compound item (task),
			None means that the item is not a header at all
		"""
		# header: bool  - whether the vals represent a header or a payload data
		self.compound = compound
		self.ident = ident
		self.data = data


	def json(self):
		"""Serialize self to the JSON representation"""
		return {p: self.__getattribute__(p) for p in self.__slots__}


def unfoldDepthFirst(tinfext, indent=0):
	"""Print TaskInfoExt hierarchy using the depth first traversing

	Args:
		tinfext: TaskInfoExt  - extended task info to be unfolded and printed
		indent: int  - current indent for the output hierarchy formatting
	return  - list(hdr, indent, list(vals)), maxindent:
		hdr: bool  - whether the row is a header
		indent: uint  - current indentation
		vals  - outputting values
		wide: uint  - [max] output wide in items/cols considering the indentation
	"""
	wide = indent
	res = []
	# Print task properties (properties header and values)
	# Format task's job properties header
	if tinfext.props:
		assert len(tinfext.props) == 2, (
			'Task properties should contain the header and value rows: ' + str(len(tinfext.props)))
		res.append(TaskInfoPrefmt(compound=True, ident=indent, data=tinfext.props[0]))
		wide = indent + len(res[-1].data)
		res.append(TaskInfoPrefmt(compound=None, ident=indent, data=[tblfmt(v) for v in tinfext.props[1]]))
	# assert isinstance(tinfext, TaskInfoExt), 'Unexpected type of tinfext: ' + type(tinfext).__name__
	# Format task's jobs' properties
	indent += 1
	if tinfext.jobs:  # Consider None
		res.append(TaskInfoPrefmt(compound=False, ident=indent, data=[tblfmt(v) for v in tinfext.jobs[0]]))
		wide = indent + len(res[-1].data)
		for tie in tinfext.jobs[1:]:
			res.append(TaskInfoPrefmt(compound=None, ident=indent, data=[tblfmt(v) for v in tie]))
	# Unfold subtasks
	# print('>> Outputting task {} with {} subtasks'.format(tinfext.props[1][0]
	# 	, 0 if not tinfext.subtasks else len(tinfext.subtasks)), file=sys.stderr)
	if tinfext.subtasks:  # Consider None
		for tie in tinfext.subtasks:
			sres, wide = unfoldDepthFirst(tie, indent=indent)
			res.extend(sres)
	return res, wide


class Task(object):
	"""Task is a managing container for subtasks and Jobs"""

	# _tasks = []
	# _taskManager = None
	# _taskManagerLock = threading.Lock()
	#
	# @staticmethod
	# def _taskTerminator(*args, **kwargs):
	# 	tasks = kwargs['tasks']
	# 	latency = kwargs['latency']
	# 	lock = kwargs['lock']
	# 	ctime = time.perf_counter()
	# 	with lock:
	# 		for task in tasks:
	# 			if task.timeout and ctime - task.tstart >= task.timeout:
	# 				task.terminate()

	def __init__(self, name, timeout=0, onstart=None, ondone=None, onfinish=None, params=None
		, task=None, latency=1.5, stdout=sys.stdout, stderr=sys.stderr):
		"""Initialize task, which is a group of subtasks including jobs to be executed

		Note: the task is considered to be failed if at least one subtask / job is failed
		(terminated or completed with non-zero return code).

		name: str  - task name
		timeout  - execution timeout in seconds. Default: 0, means infinity. ATTENTION: not implemented
		onstart  - a callback, which is executed on the task start (before the subtasks/jobs execution
			started) in the CONTEXT OF THE CALLER (main process) with the single argument,
			the task. Default: None
			ATTENTION: must be lightweight
		ondone  - a callback, which is executed on the SUCCESSFUL completion of the task in the
			CONTEXT OF THE CALLER (main process) with the single argument, the task. Default: None
			ATTENTION: must be lightweight
		onfinish  - a callback, which is executed on either completion or termination of the task in the
			CONTEXT OF THE CALLER (main process) with the single argument, the task. Default: None
			ATTENTION: must be lightweight
		params  - additional parameters to be used in callbacks
		task: Task  - optional owner super-task
		latency: float  - lock timeout in seconds: None means infinite,
			<= 0 means non-bocking, > 0 is the actual timeout
		stdout  - None or file name or PIPE for the buffered output to be APPENDED
		stderr  - None or file name or PIPE or STDOUT for the unbuffered error output to be APPENDED
			ATTENTION: PIPE is a buffer in RAM, so do not use it if the output data is huge or unlimited

		Automatically initialized and updated properties:
		tstart  - start time is filled automatically on the execution start (before onstart). Default: None
		tstop  - termination / completion time after ondone.
		numadded: uint  - the number of direct added subtasks
		numdone: uint  - the number of completed DIRECT subtasks
			(each subtask may contain multiple jobs or sub-sub-tasks)
		numterm: uint  - the number of terminated direct subtasks (including jobs) that are not restarting
			numdone + numterm <= numadded
		"""
		assert isinstance(name, str) and (latency is None or latency >= 0) and (
			task is None or (isinstance(task, Task) and task != self)), (
			'Task arguments are invalid, name: {}, latency: {}, task type: {} (valid: {})'
			.format(name, latency, type(task).__name__, task != self))
		self._lock = Lock()  # Lock for the included jobs
		# dict(subtask: Task | Job, accterms: uint)
		# # Dictionary of non-completed (but can be terminated) subtasks with the direct termination counter
		# self._items = dict()
		# Set of non-finished (and possibly restarting) subtasks
		self._items = set()
		self.name = name
		# Add member handlers if required
		# types.MethodType binds the callback to the object
		self.onstart = None if not callable(onstart) else types.MethodType(onstart, self)
		self.ondone = None if not callable(ondone) else types.MethodType(ondone, self)
		self.onfinish = None if not callable(onfinish) else types.MethodType(onfinish, self)
		# self.timeout = timeout
		self.params = params
		self._latency = latency
		self.task = task
		self.stdout = stdout
		self.stderr = stderr
		# Automatically initialized attributes
		self.tstart = None
		self.tstop = None  # Termination / completion time after ondone
		self.numadded = 0  # The number of added direct subtasks, the same subtask/job can be re-added several times
		self.numdone = 0  # The number of completed direct subtasks
		self.numterm = 0  # Total number of terminated direct subtasks that are not restarting
		# Update the task if any with this subtask
		if self.task:
			self.task.add(self)
		# Consider subtasks termination by timeout
		# if self.timeout:
		# 	if not _tasks:
		# 		_tasks.append(self)
		# 		Task._taskManager = threading.Thread(name="TaskManager", target=Task._taskTerminator
		# 			, kwargs={'tasks': Task._tasks, 'latency': latency})


	def __str__(self):
		"""A string representation, which is the .name if defined"""
		return self.name if self.name is not None else self.__repr__()


	def add(self, subtask):
		"""Add one more subtask to the task

		Args:
			subtask: Job|Task  - subtask of the current task

		Raises:
			RuntimeError  - lock acquisition failed
		"""
		assert isinstance(subtask, Job) or isinstance(subtask, Task), 'Unexpected type of the subtask'
		if self.tstart is None:
			self.tstart = time.perf_counter()
			# Consider onstart callback
			if self.onstart:
				applyCallback(self.onstart, self.name)
			# Consider super-task
			if self.task:
				self.task.add(self)
		elif subtask in self._items:  # Omit calls from the non-first subsubtask of the subtask
			return
		if self._lock.acquire(timeout=self._latency):
			self._items.add(subtask)
			self.numadded += 1
			self._lock.release()
		else:
			raise RuntimeError('Lock acquisition failed on add() in "{}"'.format(self.name))


	def finished(self, subtask, succeed):
		"""Complete subtask

		Args:
			subtask: Job | Task  - finished subtask
			succeed: bool  - graceful successful completion or termination

		Raises:
			RuntimeError  - lock acquisition failed
		"""
		if not self._lock.acquire(timeout=self._latency):
			raise RuntimeError('Lock acquisition failed in the task "{}" finished'.format(self.name))
		try:
			self._items.remove(subtask)
			if succeed:
				self.numdone += 1
			else:
				self.numterm += 1
		except KeyError as err:
			print('ERROR in "{}" succeed: {}, the finishing "{}" should be among the active subtasks: {}. {}'
				.format(self.name, succeed, subtask, err, traceback.format_exc(5), file=sys.stderr))
		finally:
			self._lock.release()
		# Consider onfinish callback
		if self.numdone + self.numterm == self.numadded:
			assert not self._items, 'All subtasks should be already finished;  remained {} items: {}'.format(
				len(self._items), ', '.join([st.name for st in self._items]))
			self.tstop = time.perf_counter()
			if self.numdone == self.numadded and self.ondone:
				applyCallback(self.ondone, self.name)
			if self.onfinish:
				applyCallback(self.onfinish, self.name)
			# Consider super-task
			if self.task:
				self.task.finished(self, self.numdone == self.numadded)


	def uncompleted(self, recursive=False, header=False, pid=False, tstart=False
	, tstop=False, duration=False, memory=False):
		"""Fetch names of the uncompleted tasks

		Args:
			recursive (bool, optional): Defaults to False. Fetch uncompleted subtasks recursively.
			header (bool, optional): Defaults to False. Include header for the displaying attributes.
			pid (bool, optional): Defaults to False. Show process id of for the job, None for the task.
			tstart (bool, optional): Defaults to False. Show tstart of the execution.
			tstop (bool, optional): Defaults to False. Show tstop of the execution.
			duration (bool, optional): Defaults to False. Show duration of the execution.
			memory (bool, optional): Defaults to False. Show memory consumption the job, None for the task.
				Note: the value as specified by the Job.mem, which is not the peak RSS.

		Returns:
			hierarchical dictionary of the uncompleted task names and other attributes, each items is tuple or str

		Raises:
			RuntimeError: lock acquisition failed
		"""
		extinfo = pid or duration or memory
		if duration:
			ctime = time.perf_counter()  # Current time

		# Form the Header if required
		res = []
		if header:
			if extinfo:
				hdritems = ['Name']
				if pid:
					hdritems.append('PID')
				if tstart:
					hdritems.append('Tstart')
				if tstop:
					hdritems.append('Tstop')
				if duration:
					hdritems.append('Duration')
				if memory:
					hdritems.append('Memory')
				res.append(hdritems)
			else:
				res.append('Name')

		def subtaskInfo(subtask):
			"""Subtask tracing

			Args:
				subtask (Task | Job): subtask to be traced

			Returns:
				str | list: subtask information
			"""
			isjob = isinstance(subtask, Job)
			assert isjob or isinstance(subtask, Task), 'Unexpected type of the subtask: ' + type(subtask).__name__
			if extinfo:
				res = [subtask.name]
				if pid:
					res.append(None if not isjob or subtask.proc is None else subtask.proc.pid)
				if tstart:
					res.append(subtask.tstart)
				if tstop:
					res.append(subtask.tstop)
				if duration:
					res.append(None if subtask.tstart is None else ctime - subtask.tstart)
				if memory:
					res.append(None if not isjob else subtask.mem)
				return res
			return subtask.name

		if not self._lock.acquire(timeout=self._latency):
			raise RuntimeError('Lock acquisition failed on task uncompleted() in "{}"'.format(self.name))
		try:
			# List should be generated on place while all the tasks are present
			# Note: list extension should prevent lazy evaluation of the list generator
			# otherwise the explicit conversion to the list should be performed here (within the lock)
			res += [subtaskInfo(subtask) if not recursive or isinstance(subtask, Job)
				else subtask.uncompleted(recursive) for subtask in self._items]
		finally:
			self._lock.release()
		return res


class Job(object):
	"""Job is executed in a separate process via Popen or Process object and is
	managed by the Process Pool Executor
	"""
	# Note: the same job can be executed as Popen or Process object, but ExecPool
	# should use some wrapper in the latter case to manage it

	_RTM = 0.85  # Memory retention ratio, used to not drop the memory info fast on temporal releases, E [0, 1)
	assert 0 <= _RTM < 1, 'Memory retention ratio should E [0, 1)'

	# NOTE: keyword-only arguments are specified after the *, supported only since Python 3
	def __init__(self, name, workdir=None, args=(), timeout=0, rsrtonto=False, task=None #,*
	, startdelay=0., onstart=None, ondone=None, onfinish=None, params=None, category=None, size=0, slowdown=1.
	, omitafn=False, memkind=1, memlim=0., stdout=sys.stdout, stderr=sys.stderr, poutlog=None, perrlog=None):
		"""Initialize job to be executed

		Main parameters:
		name: str  - job name
		workdir  - working directory for the corresponding process, None means the dir of the benchmarking
		args  - execution arguments including the executable itself for the process
			NOTE: can be None to make make a stub process and execute the callbacks
		timeout  - execution timeout in seconds. Default: 0, means infinity
		rsrtonto  - restart the job on timeout, Default: False. Can be used for
			non-deterministic Jobs like generation of the synthetic networks to regenerate
			the network on border cases overcoming getting stuck on specific values of the rand variables.
		task: Task  - origin task if this job is a part of the task
		startdelay  - delay after the job process starting to execute it for some time,
			executed in the CONTEXT OF THE CALLER (main process).
			ATTENTION: should be small (0.1 .. 1 sec)
		onstart  - a callback, which is executed on the job starting (before the execution
			started) in the CONTEXT OF THE CALLER (main process) with the single argument,
			the job. Default: None.
			If onstart() raises an exception then the job is completed before been started (.proc = None)
			returning the error code (can be 0) and tracing the cause to the stderr.
			ATTENTION: must be lightweight
			NOTE:
				- It can be executed several times if the job is restarted on timeout
				- Most of the runtime job attributes are not defined yet
		ondone  - a callback, which is executed on successful completion of the job in the
			CONTEXT OF THE CALLER (main process) with the single argument, the job. Default: None
			ATTENTION: must be lightweight
		onfinish  - a callback, which is executed on either completion or termination of the job in the
			CONTEXT OF THE CALLER (main process) with the single argument, the job. Default: None
			ATTENTION: must be lightweight
		params  - additional parameters to be used in callbacks
		stdout  - None, stdout, stderr, file name or PIPE for the buffered output to be APPENDED.
			The path is interpreted in the CALLER CONTEXT
		stderr  - None, stdout, stderr, file name or PIPE for the unbuffered error output to be APPENDED
			ATTENTION: PIPE is a buffer in RAM, so do not use it if the output data is huge or unlimited.
			The path is interpreted in the CALLER CONTEXT
		poutlog: str  - file name to log non-empty piped stdout pre-pended with the timestamp. Actual only if stdout is PIPE.
		perrlog: str  - file name to log non-empty piped stderr pre-pended with the timestamp. Actual only if stderr is PIPE.

		Scheduling parameters:
		omitafn  - omit affinity policy of the scheduler, which is actual when the affinity is enabled
			and the process has multiple treads
		category  - classification category, typically semantic context or part of the name,
			used to identify related jobs;
			requires _CHAINED_CONSTRAINTS
		size  - expected relative memory complexity of the jobs of the same category,
			typically it is size of the processing data, >= 0, 0 means undefined size
			and prevents jobs chaining on constraints violation;
			used on _LIMIT_WORKERS_RAM or _CHAINED_CONSTRAINTS
		slowdown  - execution slowdown ratio, >= 0, where (0, 1) - speedup, > 1 - slowdown; 1 by default;
			used for the accurate timeout estimation of the jobs having the same .category and .size.
			requires _CHAINED_CONSTRAINTS
		memkind  - kind of memory to be evaluated (average of virtual and resident memory
			to not overestimate the instant potential consumption of RAM):
			0  - mem for the process itself omitting the spawned sub-processes (if any)
			1  - mem for the heaviest process of the process tree spawned by the original process
				(including the origin itself)
			2  - mem for the whole spawned process tree including the origin process
		memlim: float  - max amount of memory in GB allowed for the job execution, 0 - unlimited

		Execution parameters, initialized automatically on execution:
		tstart  - start time, filled automatically on the execution start (before onstart). Default: None
		tstop  - termination / completion time after ondone
			NOTE: onstart() and ondone() callbacks execution is included in the job execution time
		proc  - process of the job, can be used in the ondone() to read its PIPE
		pipedout  - contains output from the PIPE supplied to stdout if any, None otherwise
			NOTE: pipedout is used to avoid a deadlock waiting on the process completion having a piped stdout
			https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
		pipederr  - contains output from the PIPE supplied to stderr if any, None otherwise
			NOTE: pipederr is used to avoid a deadlock waiting on the process completion having a piped stderr
			https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
		mem  - consuming memory (smooth max of average of VMS and RSS, not just the current value)
			or the least expected value inherited from the jobs of the same category having non-smaller size;
			requires _LIMIT_WORKERS_RAM
		terminates  - accumulated number of the received termination requests caused by the constraints violation
			NOTE: > 0 (1 .. ExecPool._KILLDELAY) for the apps terminated by the execution pool
				(resource constrains violation or ExecPool exception),
				== 0 for the crashed apps
		wkslim  - worker processes limit (max number) on the job postponing if any,
			the job is postponed until at most this number of worker processes operate;
			requires _LIMIT_WORKERS_RAM
		chtermtime  - chained termination: None - disabled, False - by memory, True - by time;
			requires _CHAINED_CONSTRAINTS
		"""
		assert isinstance(name, str) and timeout >= 0 and (task is None or isinstance(task, Task)
			) and size >= 0 and slowdown > 0 and memkind in (0, 1, 2) and memlim >= 0 and (
			poutlog is None or isinstance(poutlog, str)) and (perrlog is None or isinstance(perrlog, str)
			), ('Job arguments are invalid, name: {}, timeout: {}, task type: {}, size: {}'
			', slowdown: {}, memkind: {}, memlim: {}, poutlog: {}, perrlog: {}'.format(
			name, timeout, type(task).__name__, size, slowdown, memkind, memlim, poutlog, perrlog))
		#if not args:
		#	args = ("false")  # Create an empty process to schedule its execution

		# Properties specified by the input parameters -------------------------
		self.name = name
		self.workdir = workdir
		self.args = args
		self.params = params
		self.timeout = timeout
		self.rsrtonto = rsrtonto
		self.task = task
		# Delay in the callers context after starting the job process. Should be small.
		self.startdelay = startdelay  # 0.2  # Required to sync sequence of started processes
		# Callbacks ------------------------------------------------------------
		self.onstart = None if not callable(onstart) else types.MethodType(onstart, self)
		self.ondone = None if not callable(ondone) else types.MethodType(ondone, self)
		self.onfinish = None if not callable(onfinish) else types.MethodType(onfinish, self)
		# I/O redirection ------------------------------------------------------
		self.stdout = stdout
		self.stderr = stderr
		self.poutlog = poutlog
		self.perrlog = perrlog
		# Internal properties --------------------------------------------------
		self.tstart = None  # start time is filled automatically on the execution start, before onstart. Default: None
		self.tstop = None  # Termination / completion time after ondone
		# Internal attributes
		self.proc = None  # Process of the job, can be used in the ondone() to read its PIPE
		self.pipedout = None
		self.pipederr = None
		self.terminates = 0  # Accumulated number of the received termination requests caused by the constraints violation
		# Process-related unified logging descriptors of file / system output channel / PIPE related system object
		self._stdout = None
		self._stderr = None
		# Omit scheduler affinity policy (actual when some process is computed on all treads, etc.)
		self._omitafn = omitafn
		# Whether the job is restarting (in process) on timeout or because of the
		# GROUP memory limit violation (where the job itself does not violate any constraints);
		# required to be aware whether to complete the owner task
		self._restarting = False
		if _LIMIT_WORKERS_RAM:
			# Note: wkslim is used only internally for the cross-category ordering
			# of the jobs queue by reducing resource consumption
			self.wkslim = None  # Worker processes limit (max number) on the job postponing if any
			self.memkind = memkind
			self.memlim = memlim
			# Consumed implementation-defined type of memory on execution in gigabytes or the least expected
			# (inherited from the related jobs having the same category and non-smaller size)
			self.mem = 0.
		if _CHAINED_CONSTRAINTS:
			self.category = category  # Job name
			self.slowdown = slowdown  # Execution slowdown ratio, >= 0, where (0, 1) - speedup, > 1 - slowdown
			self.chtermtime = None  # Chained termination by time: None, False - by memory, True - by time
		if _LIMIT_WORKERS_RAM or _CHAINED_CONSTRAINTS:
			# Note: it makes sense to compare jobs by size only in the same category,
			# used for both timeout and memory constraints
			self.size = size  # Expected memory complexity of the job, typically its size of the processing data
		# Update the task if any with this Job
		if self.task:
			self.task.add(self)


	def __str__(self):
		"""A string representation, which is the .name if defined"""
		return self.name if self.name is not None else self.__repr__()


	def _updateMem(self):
		"""Update memory consumption (implementation-defined type) using smooth max

		Actual memory (not the historical max) is retrieved and updated
		using:
		a) smoothing filter in case of the decreasing consumption and
		b) direct update in case of the increasing consumption.

		Prerequisites: job must have defined proc (otherwise AttributeError is raised)
			and psutil should be available (otherwise NameError is raised)

		self.memkind defines the kind of memory to be evaluated:
			0  - mem for the process itself omitting the spawned sub-processes (if any)
			1  - mem for the heaviest process of the process tree spawned by the original process
				(including the origin)
			2  - mem for the whole spawned process tree including the origin process

		return  - smooth max of job mem
		"""
		if not _LIMIT_WORKERS_RAM:
			return 0
		# Current consumption of memory by the job
		curmem = 0  # Evaluating memory
		try:
			up = psutil.Process(self.proc.pid)
			pmem = up.memory_info()
			# Note: take weighted average of mem and rss to not over/under reserve RAM especially for Java apps
			wrss = 0.9  # Weight of the rss: 0.5 .. 0.98
			curmem = pmem.vms * (1 - wrss) + pmem.rss * wrss
			if self.memkind:
				amem = curmem  # Memory consumption of the whole process tree
				xmem = curmem  # Memory consumption of the heaviest process in the tree
				for ucp in up.children(recursive=True):  # Note: fetches only children processes
					pmem = ucp.memory_info()
					mem = pmem.vms * (1 - wrss) + pmem.rss * wrss  # MB
					amem += mem
					if xmem < mem:
						xmem = mem
				curmem = amem if self.memkind == 2 else xmem
		except psutil.Error as err:
			# The process is finished and such pid does not exist
			print('WARNING, _updateMem() failed, current proc mem set to 0: {}. {}'.format(
				err, traceback.format_exc(5)), file=sys.stderr)
		# Note: even if curmem = 0 update mem smoothly to avoid issues on internal
		# fails of psutil even thought they should not happen
		curmem = inGigabytes(curmem)
		self.mem = max(curmem, self.mem * Job._RTM + curmem * (1-Job._RTM))
		return self.mem


	def lessmem(self, job):
		"""Whether the [estimated] memory consumption is less than in the specified job

		job  - another job for the .mem or .size comparison

		return  - [estimated] mem is less or None (unknown)
		"""
		assert _LIMIT_WORKERS_RAM, 'lessmem() is sensible only for the defined _LIMIT_WORKERS_RAM'
		# assert _LIMIT_WORKERS_RAM and self.category is not None and self.category == job.category, (
		# 	'Only jobs of the same initialized category can be compared')
		if self.mem and job.mem:
			return self.mem < job.mem
		elif self.size and job.size and self.category == job.category:
			return self.size < job.size
		return None


	def fetchPipedData(self, timeout=None):
		"""Fetch PIPED data from the job if PIPEs are used

		This function should be called before waiting on the process completion
		otherwise .wait() it may cause a deadlock:
		https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait

		timeout: float or None  - waiting timeout, None means infinity, 0 means immediately

		return  fetched: bool - whether any data is fetched
		"""
		if (self.stdout is not subprocess.PIPE and self.stderr is not subprocess.PIPE
		# Consider that the data can be already fetched and should not be rewritten with None
		) or self.pipedout is not None or self.pipederr is not None:
			return
		# NOTE: .communicate() waits until the pipe is closed, which can be performed
		# on the process completion but may be also performed earlier:
		# https://docs.python.org/3/library/subprocess.html#subprocess.Popen.communicate
		self.pipedout, self.pipederr = (None if v is None else v.decode() for v in self.proc.communicate(timeout))


	def complete(self, graceful=None):
		"""Completion function
		ATTENTION: This function is called AFTER the destruction of the job-associated process
		to perform cleanup in the context of the caller (main thread).
		In the abnormal case of existing the job process, it is killed.

		graceful  - the job is successfully completed or it was terminated / crashed, bool.
			None means use "not self.proc.returncode" (i.e. whether errcode is 0)
		"""
		# Fetch piped data if any, required to be done before the proc.wait to avoid deadlocks:
		# https://docs.python.org/3/library/subprocess.html#subprocess.Popen.waithttps://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
		self.fetchPipedData(0)
		timestamp = None
		# Persist the piped output if required
		for pout, plog in ((self.pipedout, self.poutlog), (self.pipederr, self.perrlog)):
			if not pout or plog is None:  # Omit production of the empty logs
				continue
			# Ensure existence of the parent directory for the filename
			customfile = isinstance(plog, str)
			if customfile:
				basedir = os.path.split(plog)[0]
				if basedir and not os.path.exists(basedir):
					os.makedirs(basedir)
			# Append to the file
			flog = None
			# First, add a timestamp even if the log body is empty to be aware about the logging fact
			try:
				flog = plog if not customfile else open(plog, 'a')
			except IOError as err:
				print('ERROR on opening the piped log "{}" for "{}": {}. Default output channel is used.'
					.format(plog, self.name, err), file=sys.stdout)
				if plog is self.poutlog:
					flog = sys.stdout
				if plog is self.perrlog:
					flog = sys.stderr
			try:
				# Add a timestamp if the file is not empty to distinguish logs
				## not customfile or
				if customfile and os.fstat(flog.fileno()).st_size:  # Add timestamp only to the non-empty file
					if timestamp is None:
						timestamp = time.gmtime()
					print(timeheader(timestamp), file=flog)  # Note: prints also newline unlike flog.write()
				# Append the log body itself if any
				flog.write(pout)  # Write the piped output
				# # Flush the file buffer if required
				# if customfile:
				# 	flog.flush()
				# 	# Note: the file is automatically closed by the object destructor,
				# 	# moreover some system files like devnull should not be closed by the user
				# 	# flog.close()
			except IOError as err:
				print('ERROR on logging piped data "{}" for "{}": {}'
					.format(plog, self.name, err), file=sys.stdout)

		if self.proc is not None:
			ecode = self.proc.poll()
			# Note: the job killing is already performed if the termination has not helped
			# but just in case do it again
			if ecode is None:
				self.proc.kill()
				time.sleep(0)  # Switch the context to give a time for the job killing
			#	print('WARNING, completion of the non-finished process is called for "{}", killed'
			#		.format(self.name), file=sys.stderr)
			# if ecode is not None and ecode < 0:  # poll() None means the process has not been terminated / completed
			# Note: in theory ecode could still be None if the job is killed (not just terminated) but it is better to
			# retain a zombie than to hang on completion
			#if ecode is None or ecode < 0:  # poll() None means the process has not been terminated / completed
			# Note: ecode < 0 typically means forced termination by the signal
			if ecode is not None and ecode < 0:  # poll() None means the process has not been terminated / completed
				# Explicitly join the completed process to remove the entry from the children table and avoid zombie
				# in case signal.signal(signal.SIGCHLD, signal.SIG_DFL) has not been set.
				# Note that SIG_IGN unlike SIG_DFL affects the return code of the former zombies, resetting it to 0
				ecw = self.proc.wait()
				print('{} finished on termination: {} (initial: {})'.format(self.name, ecw, ecode))

		# Note: files should be closed before any assertions or exceptions
		assert self.tstop is None and self.tstart is not None, (  # and self.proc.poll() is not None
			'A job ({}) should be already started and can be completed only once, tstart: {}, tstop: {}'
			.format(self.name, self.tstart, self.tstop))
		# Job-related post execution
		if graceful is None:
			graceful = self.proc is not None and not self.proc.returncode
		if graceful and self.ondone:
			applyCallback(self.ondone, self.name)
		if self.onfinish:
			applyCallback(self.onfinish, self.name)
		# Clean up empty logs (can be left for the terminating process to avoid delays)
		# Remove empty logs skipping the system devnull
		tpaths = []  # Base dir of the output
		if (self.stdout and isinstance(self.stdout, str) and self.stdout != os.devnull
		and os.path.exists(self.stdout) and os.path.getsize(self.stdout) == 0):
			tpath = os.path.split(self.stdout)[0]
			if tpath:
				tpaths.append(tpath)
			os.remove(self.stdout)
		if (self.stderr and isinstance(self.stderr, str) and self.stderr != os.devnull
		and os.path.exists(self.stderr) and os.path.getsize(self.stderr) == 0):
			tpath = os.path.split(self.stderr)[0]
			if tpath and (not tpaths or tpath not in tpaths):
				tpaths.append(tpath)
			os.remove(self.stderr)
		# Also remove the directory if it is empty
		for tpath in tpaths:
			try:
				os.rmdir(tpath)
			except OSError:
				pass  # The dir is not empty, just skip it
		# Updated execution status
		self.tstop = time.perf_counter()
		# Call owner task finalization for the non-restarting jobs
		if (graceful or not self._restarting) and self.task:
			self.task.finished(self, graceful)
		#if _DEBUG_TRACE:  # Note: terminated jobs are traced in __reviseWorkers()
		print('Completed {} "{}" #{} with errcode {}, executed {} h {} m {:.4f} s'
			.format('gracefully' if graceful else '(ABNORMALLY)'
			, self.name, '-' if self.proc is None else str(self.proc.pid)
			, '-' if self.proc is None else str(self.proc.returncode)
			, *secondsToHms(self.tstop - self.tstart))
			, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		# Note: the call stack is shown on the termination
		#traceback.print_stack(limit=5, file=sys.stderr)


def ramfracs(fracsize):
	"""Evaluate the minimal number of RAM fractions of the specified size in GB

	Used to estimate the reasonable number of processes with the specified minimal
	dedicated RAM.

	fracsize  - minimal size of each fraction in GB, can be a fractional number
	return the minimal number of RAM fractions having the specified size in GB
	"""
	return int(_RAM_SIZE / fracsize)


def cpucorethreads():
	"""The number of hardware treads per a CPU core

	Used to specify CPU affinity dedicating the maximal amount of CPU cache L1/2.
	"""
	# -r or -E  - extended regex syntax, -n  - quiet output, /p  - print the match
	return int(subprocess.check_output(
		[r"lscpu | sed -rn 's/^Thread\(s\).*(\w+)$/\1/p'"], shell=True))


def cpunodes():
	"""The number of NUMA nodes, where physical CPUs are located.

	Used to evaluate CPU index from the affinity table index considering the
	NUMA architecture.
	Usually NUMA nodes = physical CPUs.
	"""
	return int(subprocess.check_output(
		[r"lscpu | sed -rn 's/^NUMA node\(s\).*(\w+)$/\1/p'"], shell=True))


def cpusequential(ncpunodes=cpunodes()):
	"""Enumeration type of the logical CPUs: cross-nodes or sequential

	The enumeration can be cross-nodes starting with one hardware thread per each
	NUMA node, or sequential by enumerating all cores and hardware threads in each
	NUMA node first.
	For two hardware threads per a physical CPU core, where secondary HW threads
	are taken in brackets:
		Crossnodes enumeration, often used for the server CPUs
		NUMA node0 CPU(s):     0,2(,4,6)		=> PU L#1 (P#4)
		NUMA node1 CPU(s):     1,3(,5,7)
		Sequential enumeration, often used for the laptop CPUs
		NUMA node0 CPU(s):     0(,1),2(,3)		=> PU L#1 (P#1)  - indicates sequential
		NUMA node1 CPU(s):     4(,5),6(,7)
	ATTENTION: `hwloc` utility is required to detect the type of logical CPUs
	enumeration:  `$ sudo apt-get install hwloc`
	See details: http://www.admin-magazine.com/HPC/Articles/hwloc-Which-Processor-Is-Running-Your-Service

	ncpunodes  - the number of CPU nodes in the system to assume sequential
		enumeration for multi-node systems only; >= 1

	return  - enumeration type of the logical CPUs, bool or None:
		False  - cross-nodes
		True  - sequential
	"""
	# Fetch index of the second hardware thread / CPU core / CPU on the first NUMA node
	res = subprocess.check_output(
		[r"lstopo-no-graphics | sed -rn 's/\s+PU L#1 \(P#([0-9]+)\)/\1/p'"], shell=True)
	try:
		return int(res) == 1
	except ValueError as err:
		# res is not a number, i.e. hwloc (lstopo*) is not installed
		print('WARNING, "lstopo-no-graphics ("hwloc" utilities) call failed: {}'
			', assuming that multi-node systems have nonsequential CPU enumeration.', err, file=sys.stderr)
	return ncpunodes == 1


class AffinityMask(object):
	"""Affinity mask

	Affinity table is a reduced CPU table by the non-primary HW treads in each core.
	Typically, CPUs are enumerated across the nodes:
	NUMA node0 CPU(s):     0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30
	NUMA node1 CPU(s):     1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31
	In case the number of HW threads per core is 2 then the physical CPU cores are 1 .. 15:
	NUMA node0 CPU(s):     0,2,4,6,8,10,12,14	(16,18,20,22,24,26,28,30  - 2nd HW treads)
	NUMA node1 CPU(s):     1,3,5,7,9,11,13,15	(17,19,21,23,25,27,29,31  - 2nd HW treads)
	But the enumeration can be also sequential:
	NUMA node0 CPU(s):     0,(1),2,(3),...
	...

	Hardware threads share all levels of the CPU cache, physical CPU cores share only the
	last level of the CPU cache (L2/3).
	The number of worker processes in the pool should be equal to the:
	- physical CPU cores for the cache L1/2 maximization
	- NUMA nodes for the cache L2/3 maximization

	NOTE: `hwloc` utility can be used to detect the type of logical CPUs enumeration:
	`$ sudo apt-get install hwloc`
	See details: http://www.admin-magazine.com/HPC/Articles/hwloc-Which-Processor-Is-Running-Your-Service

	# Doctests -----------------------------------------------------------------
	# Mask for all sequential logical CPU having index #1
	>>> AffinityMask(1, False, sequential=True)(1) == \
		str(AffinityMask.CORE_THREADS if AffinityMask.NODES == 1 else AffinityMask.NODE_CPUS)
	True

	# Mask for the first cross-node logical CPU in the group #1
	>>> AffinityMask(AffinityMask.CORE_THREADS, sequential=False)(1) == '1'
	True

	# Mask for all cross-node logical CPUs in the group #1
	>>> AffinityMask(AffinityMask.CORE_THREADS, first=False, sequential=False)(1) == \
		','.join([str(1 + c*(AffinityMask.CPUS // (AffinityMask.NODES * AffinityMask.CORE_THREADS))) \
		for c in range(AffinityMask.CORE_THREADS)])
	True

	# Mask for all sequential logical CPUs in the group #1
	>>> AffinityMask(AffinityMask.CORE_THREADS, False, sequential=True)(1) == \
		'-'.join([str(1*(AffinityMask.CPUS // (AffinityMask.NODES * AffinityMask.CORE_THREADS)) + c) \
		for c in range(AffinityMask.CORE_THREADS)])
	True

	# Mask for all cross-node logical CPU on the NUMA node #0
	>>> AffinityMask(AffinityMask.CPUS // AffinityMask.NODES, False, sequential=False)(0) == \
		','.join(['{}-{}'.format(c*(AffinityMask.CPUS // AffinityMask.CORE_THREADS) \
		, (c+1)*(AffinityMask.CPUS // AffinityMask.CORE_THREADS) - 1) for c in range(AffinityMask.CORE_THREADS)])
	True

	# Mask for all sequential logical CPU on the NUMA node #0
	>>> AffinityMask(AffinityMask.CPUS // AffinityMask.NODES, first=False, sequential=True)(0) == \
		'0-{}'.format(AffinityMask.NODE_CPUS-1)
	True

	# Exception on too large input index
	>>> AffinityMask(AffinityMask.CPUS // AffinityMask.NODES, False, sequential=False)(100000)
	Traceback (most recent call last):
	IndexError

	# Exception on float afnstep
	>>> AffinityMask(2.1, False)(1)
	Traceback (most recent call last):
	AssertionError

	# Exception on afnstep not multiple to the CORE_THREADS
	>>> AffinityMask(AffinityMask.CORE_THREADS + 1, False)(0)
	Traceback (most recent call last):
	AssertionError
	"""
	# Logical CPUs: all hardware threads in all physical CPU cores in all physical CPUs in all NUMA nodes
	CPUS = cpu_count()
	NODES = cpunodes()  # NUMA nodes (typically, physical CPUs)
	CORE_THREADS = cpucorethreads()  # Hardware threads per CPU core
	SEQUENTIAL = cpusequential(NODES)  # Sequential enumeration of the logical CPUs or cross-node enumeration

	CORES = CPUS//CORE_THREADS  # Total number of physical CPU cores
	NODE_CPUS = CPUS//NODES  # Logical CPUs per each NUMA node
	#CPU_CORES = NODE_CPUS//CORE_THREADS  # The number of physical cores in each CPU
	if NODE_CPUS*NODES != CPUS or CORES*CORE_THREADS != CPUS:
		raise ValueError('Only uniform NUMA nodes are supported:'
			'  CORE_THREADS: {}, CORES: {}, NODE_CPUS: {}, NODES: {}, CPUS: {}'
			.format(CORE_THREADS, CORES, NODE_CPUS, NODES, CPUS))

	def __init__(self, afnstep, first=True, sequential=SEQUENTIAL):
		"""Affinity mask initialization

		afnstep: int  - affinity step, integer if applied, allowed values:
			1, CORE_THREADS * n,  n E {1, 2, ... CPUS / (NODES * CORE_THREADS)}

			Used to bind worker processes to the logical CPUs to have warm cache and,
			optionally, maximize cache size per a worker process.
			Groups of logical CPUs are selected in a way to maximize the cache locality:
			the single physical CPU is used taking all its hardware threads in each core
			before allocating another core.

			Typical Values:
			1  - maximize parallelization for the single-threaded apps
				(the number of worker processes = logical CPUs)
			CORE_THREADS  - maximize the dedicated CPU cache L1/2
				(the number of worker processes = physical CPU cores)
			CPUS / NODES  - maximize the dedicated CPU cache L3
				(the number of worker processes = physical CPUs)
		first  - mask the first logical unit or all units in the selected group.
			One unit per the group maximizes the dedicated CPU cache for the
			single-threaded worker, all units should be used for the multi-threaded
			apps.
		sequential  - sequential or cross nodes enumeration of the CPUs in the NUMA nodes:
			None  - undefined, interpreted as cross-nodes (the most widely used on servers)
			False  - cross-nodes
			True  - sequential

			For two hardware threads per a physical CPU core, where secondary HW threads
			are taken in brackets:
			Crossnodes enumeration, often used for the server CPUs
			NUMA node0 CPU(s):     0,2(,4,6)
			NUMA node1 CPU(s):     1,3(,5,7)
			Sequential enumeration, often used for the laptop CPUs
			NUMA node0 CPU(s):     0(,1),2(,3)
			NUMA node1 CPU(s):     4(,5),6(,7)
		"""
		assert ((afnstep == 1 or (afnstep >= self.CORE_THREADS
			and not afnstep % self.CORE_THREADS)) and isinstance(first, bool)
			and (sequential is None or isinstance(sequential, bool))
			), ('Arguments are invalid:  afnstep: {}, first: {}, sequential: {}'
			.format(afnstep, first, sequential))
		self.afnstep = int(afnstep)  # To convert 2.0 to 2
		self.first = first
		self.sequential = sequential


	def __call__(self, i):
		"""Evaluate CPUs affinity mask for the specified group index of the size afnstep

		i  - index of the selecting group of logical CPUs
		return  - mask of the first or all logical CPUs
		"""
		if i < 0 or (i + 1) * self.afnstep > self.CPUS:
			raise IndexError('Index is out of range for the given affinity step:'
				'  i: {}, afnstep: {}, cpus: {} vs {} (afnstep * (i+1))'
				.format(i, self.afnstep, self.CPUS, i * self.afnstep))

		inode = i % self.NODES  # Index of the NUMA node
		if self.afnstep == 1:
			if self.sequential:
				# 1. Identify shift inside the NUMA node traversing over the same number of
				# the hardware threads in all physical cores starting from the first HW thread
				indcpu = i//self.NODES * self.CORE_THREADS  # Traverse with step = CORE_THREADS
				indcpu = indcpu%self.NODE_CPUS + indcpu//self.NODE_CPUS  # Normalize to fit the actual indices
				# 2. Identify index of the NUMA node and convert it to the number of logical CPUs
				#indcpus = inode * self.NODE_CPUS
				i = inode*self.NODE_CPUS + indcpu
				assert i < self.CPUS, 'Index out of range: {} >= {}'.format(i, self.CPUS)
			cpumask = str(i)
		else:  # afnstep = CORE_THREADS * n,  n E N
			if self.sequential:
				# NUMA node0 CPU(s):     0(,1),2(,3)
				# NUMA node1 CPU(s):     4(,5),6(,7)

				# 1. Identify index of the NUMA node and convert it to the number of logical CPUs
				#indcpus = inode * self.NODE_CPUS
				i = (inode*self.NODE_CPUS
					# 2. Identify shift inside the NUMA node traversing over the same number of
					# the hardware threads in all physical cores starting from the first HW thread
					+ i//self.NODES * self.afnstep)
				assert i + self.afnstep <= self.CPUS, ('Mask out of range: {} > {}'
					.format(i + self.afnstep, self.CPUS))
				if self.first:
					cpumask = str(i)
				else:
					cpumask = '{}-{}'.format(i, i + self.afnstep - 1)
			else:
				# NUMA node0 CPU(s):     0,2,4,6,8,10,12,14	(16,18,20,22,24,26,28,30  - 2nd HW treads)
				# NUMA node1 CPU(s):     1,3,5,7,9,11,13,15	(17,19,21,23,25,27,29,31  - 2nd HW treads)
				# afnstep <= 1 or hwthreads = 1  -> direct mapping
				# afnstep = 2 [th=2]  -> 0,16; 1,17; 2,18; ...
				#
				# NUMA node0 CPU(s):     0,3,6,9	(12,15,18,21  - 2nd HW treads)
				# NUMA node1 CPU(s):     1,4,7,10	(13,16,19,22  - 2nd HW treads)
				# NUMA node2 CPU(s):     2,5,8,11	(14,17,20,23  - 2nd HW treads)
				# afnstep = 3 [th=2]  -> 0,12,3; 1,13,4; ... 15,6,18;
				#
				# NUMA node0 CPU(s):     0,3,6,9	(12,15,18,21  24... ...45)
				# NUMA node1 CPU(s):     1,4,7,10	(13,16,19,22  25... ...46)
				# NUMA node2 CPU(s):     2,5,8,11	(14,17,20,23  26... ...47)
				# afnstep = 3 [th=4]  -> 0,12,24,36; ... 4,16,28,40; ...
				ncores = self.afnstep//self.CORE_THREADS  # The number of physical cores to dedicate
				# Index of the logical CPU (1st HW thread of the physical core) with shift of the NUMA node
				indcpu = i//self.NODES * self.NODES * ncores + inode
				cpus = []
				for hwt in range(self.CORE_THREADS):
					# Index of the logical cpu:
					# inode + ihwthread_shift
					i = indcpu + hwt * self.CORES
					cpus.append(str(i) if ncores <= 1 else '{}-{}'.format(i, i + ncores-1))
					if self.first:
						break
				assert i + ncores <= self.CPUS, (
					'Index is out of range for the given affinity step:'
					'  i: {}, afnstep: {}, ncores: {}, imapped: {}, CPUS: {}'
					.format(i, self.afnstep, ncores, i + ncores, self.CPUS))
				cpumask = ','.join(cpus)
		return cpumask


class ExecPool(object):
	"""Multi-process execution pool of jobs

	A worker in the pool executes only a single job, a new worker is created for
	each subsequent job.
	"""
	_CPUS = cpu_count()  # The number of logical CPUs in the system
	_KILLDELAY = 3  # 3 cycles of self.latency, termination wait time
	_MEMLOW = _RAM_SIZE - _RAM_LIMIT  # Low RAM(RSS) memory condition
	assert _MEMLOW >= 0, '_RAM_SIZE should be >= _RAM_LIMIT'
	_GOLDEN = (1 + 5 ** 0.5) * 0.5  # Golden section const: 1.618
	_JMEMLIMH = _GOLDEN  # Hihg memory limit ratio for the jobs restart, recommended: 1.2 .. 2
	_JMEMLIML = 1 / _GOLDEN  # Low memory limit ratio for the jobs restart
	# Memory threshold ratio, multiplier for the job to have a gap and
	# reduce the number of reschedules, recommended value: 1.2 .. 1.6
	_JMEMTRR = 3 - _GOLDEN  # 1.382; 1.5
	assert _JMEMTRR >= 1, 'Memory threshold ratio should be >= 1'

	def __init__(self, wksnum=max(_CPUS-1, 1), afnmask=None, memlimit=0., latency=0., name=None, webuiapp=None):
		# afnstep=None, uidir=None
		"""Execution Pool constructor

		wksnum: int  - number of resident worker processes, >=1. The reasonable
			value <= logical CPUs (returned by cpu_count()) = NUMA nodes * node CPUs,
			where node CPUs = CPU cores * HW treads per core.
			The recommended value is max(cpu_count() - 1, 1) to leave one logical
			CPU for the benchmarking framework and OS applications.

			To guarantee minimal average RAM per a process, for example 2.5 GB
			without _LIMIT_WORKERS_RAM flag (not using psutil for the dynamic
			control of memory consumption):
				wksnum = min(cpu_count(), max(ramfracs(2.5), 1))
		afnmask  - affinity mask for the worker processes, AffinityMask
			None if not applied
		memlimit  - limit total amount of Memory (automatically reduced to
			the amount of physical RAM if the larger value is specified) in gigabytes
			that can be used by worker processes to provide in-RAM computations, >= 0.
			Dynamically reduces the number of workers to consume not more memory
			than specified. The workers are rescheduled starting from the
			most memory-heavy processes.
			NOTE:
				- applicable only if _LIMIT_WORKERS_RAM
				- 0 means unlimited (some jobs might be [partially] swapped)
				- value > 0 is automatically limited with total physical RAM to process
					jobs in RAM almost without the swapping
		latency  - approximate minimal latency of the workers monitoring in sec, float >= 0;
			0 means automatically defined value (recommended, typically 2-3 sec)
		name  - name of the execution pool to distinguish traces from subsequently
			created execution pools (only on creation or termination)
		webuiapp: WebUiApp  - WebUI app to inspect load balancer remotely

		Internal attributes:
		alive  - whether the execution pool is alive or terminating, bool.
			Should be reseted to True on reuse after the termination.
			NOTE: should be reseted to True if the execution pool is reused
			after the joining or termination.
		failures: [JobInfo]  - failed (terminated or crashed) jobs with timestamps.
			NOTE: failures contain both terminated, crashed jobs that jobs completed with non-zero return code
			excluding the jobs terminated by timeout that have set .rsrtonto (will be restarted)
		jobsdone: uint  - the number of successfully completed (non-terminated) jobs with zero code
		tasks: set(Task)  - tasks associated with the scheduled jobs
		"""
		assert (wksnum >= 1 and (afnmask is None or isinstance(afnmask, AffinityMask))
			and memlimit >= 0 and latency >= 0 and (name is None or isinstance(name, str))
			), ('Arguments are invalid:  wksnum: {}, afnmask: {}, memlimit: {}'
			', latency: {}, name: {}'.format(wksnum, afnmask, memlimit, latency, name))
		self.name = name

		# Verify and update wksnum and afnstep if required
		if afnmask:
			# Check whether _AFFINITYBIN exists in the system
			try:
				with open(os.devnull, 'wb') as fdevnull:
					subprocess.call([_AFFINITYBIN, '-V'], stdout=fdevnull)
				if afnmask.afnstep * wksnum > afnmask.CPUS:
					print('WARNING{}, the number of worker processes is reduced'
						' ({wlim0} -> {wlim} to satisfy the affinity step'
						.format('' if not self.name else ' ' + self.name
						, wlim0=wksnum, wlim=afnmask.CPUS//afnmask.afnstep), file=sys.stderr)
					wksnum = afnmask.CPUS // afnmask.afnstep
			except OSError as err:
				afnmask = None
				print('WARNING{}, {afnbin} does not exists in the system to fix affinity: {err}'
					.format('' if not self.name else ' ' + self.name
					, afnbin=_AFFINITYBIN, err=err), file=sys.stderr)
		self._wkslim = wksnum  # Max number of resident workers
		self._workers = set()  # Scheduled and started jobs, i.e. worker processes:  {executing_job, }
		self._jobs = deque()  # Scheduled jobs that have not been started yet:  deque(job)
		self._tstart = None  # Start time of the execution of the first task
		# Affinity scheduling attributes
		self._afnmask = afnmask  # Affinity mask functor
		self._affinity = None if not self._afnmask else [None]*self._wkslim
		assert (self._wkslim * (1 if not self._afnmask else self._afnmask.afnstep)
			<= self._CPUS), ('_wkslim or afnstep is too large:'
			'  _wkslim: {}, afnstep: {}, CPUs: {}'.format(self._wkslim
			, 1 if not self._afnmask else self._afnmask.afnstep, self._CPUS))
		# Execution rescheduling attributes
		self.memlimit = 0. if not _LIMIT_WORKERS_RAM else max(0, min(memlimit, _RAM_LIMIT))  # in GB
		self.latency = latency if latency else 1 + (self.memlimit != 0.)  # Seconds of sleep on pooling
		# Predefined private attributes
		self._termlatency = max(0.01, min(0.2, self.latency))  # 200 ms, job process (worker) termination latency
		# Lock for the __terminate() to avoid simultaneous call by the signal and normal execution flow
		self.__termlock = Lock()
		self.alive = True  # The execution pool is in the working state (has not been terminated)
		self.failures = []  # Failed jobs (terminated or having non-zero return code)
		self.jobsdone = 0  # The number of successfully completed jobs (non-terminated and with zero return code)
		self.tasks = set()

		if self.memlimit and self.memlimit != memlimit:
			print('WARNING{}, total memory limit is reduced to guarantee the in-RAM'
				' computations: {:.6f} -> {:.6f} GB'.format('' if not self.name else ' ' + self.name
				, memlimit, self.memlimit), file=sys.stderr)

		# Initialize WebUI if it has been supplied
		self._uicmd = None
		global _WEBUI  #pylint: disable=W0603
		if _WEBUI and webuiapp is not None:
			# ATTENTION: Python3 includes the path to the instance type check, which
			# affects the relative imports (importing mpepool as a sub-package):
			# <class 'utils.mpewui.WebUiApp'> != <class 'mpewui.WebUiApp'>...
			if _DEBUG_TRACE:
				assert isinstance(webuiapp, WebUiApp) or type(webuiapp).__name__ == WebUiApp.__name__, (
					'Unexpected type of webuiapp: ' + type(webuiapp).__name__)
			#uiapp = WebUiApp(host='localhost', port=8080, name='MpepoolWebUI', daemon=True)
			self._uicmd = webuiapp.cmd
			if WebUiApp.RAM is None:
				# Note: it is more reasonable to display the specified RAM limit than available memory
				WebUiApp.RAM = _RAM_LIMIT  # _RAM_SIZE
			if WebUiApp.LCPUS is None:
				WebUiApp.LCPUS = AffinityMask.CPUS
			if WebUiApp.CPUCORES is None:
				WebUiApp.CPUCORES = AffinityMask.CORES
			if WebUiApp.CPUNODES is None:
				WebUiApp.CPUNODES = AffinityMask.NODES  # NUMA nodes (typically, physical CPUs)
			if WebUiApp.WKSMAX is None:
				WebUiApp.WKSMAX = wksnum
			if not webuiapp.is_alive():
				try:
					webuiapp.start()
				except RuntimeError as err:
					print('WARNING, webuiapp can not be started. Disabled: {}. {}'.format(
						err, traceback.format_exc(5)), file=sys.stderr)
					_WEBUI = False


	def __str__(self):
		"""A string representation, which is the .name if defined"""
		return self.name if self.name is not None else self.__repr__()


	def __reviseUi(self):
		"""Check and handle UI commands

		The command id is set to None and
		the result is formed in the following .data attributes:
		- errmsg: str  - error message if any
		- summary: SummaryBrief  - execution pool summary
		- workersInfo: list  - information about the workers (executing jobs)
		- jobsInfo: list  - information about the [failed/deferred] jobs not associated to any tasks
		- tasksInfo: list  - hierarchical information about the [failed/available] jobs with their tasks
			starting from the root tasks
		"""
		# Process on the next iteration if the client request is not ready
		if self._uicmd.id is None or not self._uicmd.cond.acquire(blocking=False):
			return
		WUIJOBS_LIMIT = 50  # Default max number of jobs (including task members) to be listed in the WebUI
		try:
			# self.summary()  # TODO: implement each command in the dedicated function
			# Read command parameters from the .data
			data = self._uicmd.data
			if data:
				propflt = data.get(UiResOpt.cols)  # Properties (colons header)
				# Be sure that the job/task name column is always included
				# Note: at least on Python2 if enum has 'name' member then
				# its .name attribute changes semantic => _name_ should be used
				# print('>>> name:', UiResCol.name._name_, file=sys.stderr)
				if propflt and UiResCol.name._name_ not in propflt:  # Note: .name attribute of the name col
					# Add name column as the first one
					try:
						propflt.insert(0, UiResCol.name._name_)
					except AttributeError as err:
						data.clear()
						self._uicmd.data['errmsg'] = ('Unexpected type of the UiResOpt.cols'
							' filter values (not a list): ' + type(propflt).__name__)
						raise
				objflt = data.get(UiResOpt.flt)
				lim = int(data.get(UiResOpt.lim, WUIJOBS_LIMIT))
			else:
				propflt = None
				objflt = None
				lim = WUIJOBS_LIMIT
			if _DEBUG_TRACE:
				print("> uicmd.id: {}, propflt: {}, objflt: {}".format(
					self._uicmd.id, propflt, objflt), file=sys.stderr)
			# Prepare .data for the response results
			data.clear()
			# Set CPU and RAM consumption statistics
			if _LIMIT_WORKERS_RAM:
				data['cpuLoad'] = psutil.cpu_percent() / 100.  # float E[0, 1]
				data['ramUsage'] = inGigabytes(psutil.virtual_memory().used)  # float E [0, 1]
			else:
				data['cpuLoad'] = 0
				data['ramUsage'] = 0
			# Set the actual Jobs limit value
			data[UiResOpt.lim] = lim
			# Summary of the execution pool:
			# Note: executed in the main thread, so the lock check is required only
			# to check for the termination
			acqlock = self.__termlock.acquire(True, 0.01)  # 10 ms
			if not acqlock or not self.alive:
				if acqlock:
					self.__termlock.release()
				# Note: it just interrupts job start, but does not cause termination
				# of the whole (already terminated) execution pool
				print("WARNING, The execution pool{} is terminated and can't response the UI command: {}"
					.format('' if not self.name else ' ' + self.name, self._uicmd.id.name, file=sys.stderr))
				return
			smr = None
			try:
				smr = SummaryBrief(workers=len(self._workers), jobs=len(self._jobs)
					, jobsDone=self.jobsdone, jobsFailed=len(self.failures), tasks=len(self.tasks))
			finally:
				self.__termlock.release()
			# Evaluate remained vars
			# Evaluate tasksFailed and tasksRootFailed from failures
			tasksRootFailed = 0
			tasksFailed = set()
			for fji in self.failures:
				task = fji.task
				while task:
					if task not in tasksFailed:
						if task.task is None:
							tasksRootFailed += 1
						tasksFailed.add(task)
					task = task.task
			smr.tasksRootFailed = tasksRootFailed
			smr.tasksFailed = len(tasksFailed)
			# Evaluate tasksRoot from tasks
			tasksRoot = 0
			for task in self.tasks:
				if task.task is None:
					tasksRoot += 1
			smr.tasksRoot = tasksRoot
			data['summary'] = smr

			# Form command-specific data
			jnum = 0  # The number of showing jobs without the tasks, to be <= lim
			tjnum = 0  # The number of showing jobs having tasks and showing tasks, to be <= lim
			if self._uicmd.id == UiCmdId.FAILURES:
				# Fetch info about the failed jobs considering the filtering
				jobsInfo = None  # Information about the failed jobs not assigned to any tasks
				tinfe0 = dict()  # dict(Task, TaskInfoExt)  - Task information extended, bottom level of the hierarchy
				header = True  # Add jobs header
				for fji in self.failures:
					# Note: check for the termination in all cycles
					if not self.alive:
						return
					jdata = infodata(fji, propflt, objflt)
					if fji.task is None:
						if not jdata or (lim and jnum >= lim):
							continue
						if header:
							jobsInfo = [infoheader(JobInfo.iterprop(), propflt)]  #pylint: disable=E1101
							header = False
						jobsInfo.append(jdata)
						jnum += 1
					elif not lim or tjnum < lim:
						tie = tinfe0.get(fji.task)
						if tie is None:
							tdata = infodata(TaskInfo(fji.task), propflt, objflt)
							if not tdata:
								continue
							tie = tinfe0.setdefault(fji.task, TaskInfoExt(props=None if not tdata else
								(infoheader(TaskInfo.iterprop(), propflt), tdata)  #pylint: disable=E1101
								, jobs=None if not jdata else [infoheader(JobInfo.iterprop(), propflt)]))  #pylint: disable=E1101
							tjnum += 1
						if jdata:
							# tie.jobs might be None if the task created before any of its DIRECT jobs failed
							if tie.jobs is None:
								tie.jobs = [infoheader(JobInfo.iterprop(), propflt)]  #pylint: disable=E1101
							tie.jobs.append(jdata)
							tjnum += 1
					if lim and jnum >= lim and tjnum >= lim:
						break
				# List jobs only if any payload exists besides the header
				if jobsInfo:
					# Note: jobsInfo should include at least a header and one job if not empty
					assert len(jobsInfo) >= 2, 'Unexpected length of jobsInfo'
					data['jobsInfo'] = jobsInfo
				if not tinfe0:
					return

				# Iteratively form the hierarchy of tasks from the bottom level
				ties = tasksInfoExt(tinfe0, propflt, objflt)
				if ties:
					tasksInfo = []
					tixwide = 0  # tasksInfo max wide
					for task, tie in viewitems(ties):
						# Omit repetitive listing of sub-hierarchies (they are listed from the root task)
						if task.task is not None:
							continue
						tls, twide = unfoldDepthFirst(tie, indent=0)
						tasksInfo.extend(tls)
						if twide > tixwide:
							tixwide = twide
					tls = None
					data['tasksInfo'] = tasksInfo  # list(viewvalues(ties))
					data['tasksInfoWide'] = tixwide
			elif self._uicmd.id == UiCmdId.LIST_JOBS:
				# Remained Jobs
				if (not self._workers and not self._jobs) or not self.alive:
					return
				# Flat workers listing
				jobsInfo = None  # Information about the workers
				header = True  # Add jobs header
				for job in self._workers:
					# Note: check for the termination in all cycles
					if not self.alive:
						return
					jdata = infodata(JobInfo(job), propflt, objflt)
					if not jdata:
						continue
					if header:
						jobsInfo = [infoheader(JobInfo.iterprop(), propflt)]  #pylint: disable=E1101
						header = False
					jobsInfo.append(jdata)
				if jobsInfo:
					data['workersInfo'] = jobsInfo
				# List the upcoming jobs up to the specified limit
				jobsInfo = None  # Information about the jobs
				header = True  # Add jobs header
				jnum = 0  # Counter of the showing jobs
				for job in self._jobs:
					# Note: check for the termination in all cycles
					if not self.alive:
						return
					jdata = infodata(JobInfo(job), propflt, objflt)
					if not jdata:
						continue
					if header:
						jobsInfo = [infoheader(JobInfo.iterprop(), propflt)]  #pylint: disable=E1101
						header = False
					jobsInfo.append(jdata)
					jnum += 1  # Note: only the filtered jobs are considered
					if lim and jnum >= lim:
						break
				if jobsInfo:
					data['jobsInfo'] = jobsInfo
					jobsInfo = None
			elif self._uicmd.id == UiCmdId.LIST_TASKS:
				# Tasks for the remained Jobs
				if (not self._workers and not self._jobs) or not self.alive:
					return
				# List the tasks with their jobs up to the specified limit of covered jobs
				tinfe0 = dict()  # dict(Task, TaskInfoExt)  - Task information extended, bottom level of the hierarchy
				tjnum = 0  # The number of showing jobs having tasks and showing tasks, to be <= lim
				for jobs in (self._workers, self._jobs):
					for job in jobs:
						# Note: check for the termination in all cycles
						if not self.alive:
							return
						if job.task is None:
							continue
						# print('>>> Non-zero task: {}'.format(job.task.name))
						jdata = infodata(JobInfo(job), propflt, objflt)
						tie = tinfe0.get(job.task)
						if tie is None:
							tdata = infodata(TaskInfo(job.task), propflt, objflt)
							if not tdata:
								continue
							tie = tinfe0.setdefault(job.task, TaskInfoExt(props=None if not tdata else
								(infoheader(TaskInfo.iterprop(), propflt), tdata)  #pylint: disable=E1101
								, jobs=None if not jdata else [infoheader(JobInfo.iterprop(), propflt)]))  #pylint: disable=E1101
							tjnum += 1
						if jdata:
							# tie.jobs might be None if the task created before any of its DIRECT jobs created
							if tie.jobs is None:
								tie.jobs = [infoheader(JobInfo.iterprop(), propflt)]  #pylint: disable=E1101
							tie.jobs.append(jdata)
							tjnum += 1
						if lim and tjnum >= lim:
							break
				if not tinfe0:
					return
				# Iteratively form the hierarchy of tasks from the bottom level
				ties = tasksInfoExt(tinfe0, propflt, objflt)
				# if ties:
				# 	data['tasksInfo'] = list(viewvalues(ties))
				if ties:
					# print('>>> ties size: {}'.format(len(ties)))
					tasksInfo = []
					tixwide = 0  # tasksInfo max wide
					for task, tie in viewitems(ties):
						# Omit repetative listing of subhierarchies (they are listed from the root task)
						if task.task is not None:
							continue
						tls, twide = unfoldDepthFirst(tie, indent=0)
						tasksInfo.extend(tls)
						if twide > tixwide:
							tixwide = twide
					tls = None
					data['tasksInfo'] = tasksInfo  # list(viewvalues(ties))
					data['tasksInfoWide'] = tixwide
			else:
				self._uicmd.data['errmsg'] = 'Unknown UI command: ' + self._uicmd.id.name
				print('WARNING, Unknown command requested:', self._uicmd.id.name, file=sys.stderr)
		except Exception as err:  #pylint: disable=W0703
			errmsg = 'ERROR, UI command processing failed: {}. {}'.format(
				err, traceback.format_exc(5))
			self._uicmd.data['errmsg'] = errmsg
			print(errmsg, file=sys.stderr)
		finally:
			if (not self._workers and not self._jobs) or not self.alive:
				errmsg = self._uicmd.data.get('errmsg', '')
				errmsg = '{}The execution pool{} is not alive'.format(
					'' if not errmsg else '. ' + errmsg, '' if not self.name else ' ' + self.name)
				self._uicmd.data['errmsg'] = errmsg
			self._uicmd.id = None  # Reset command id for the completed command
			self._uicmd.cond.notify()
			self._uicmd.cond.release()


	def __enter__(self):
		"""Context entrance"""
		# Reuse execpool if possible
		if not self.alive:
			self.clear()
		return self


	def __exit__(self, etype, evalue, trcbck):
		"""Context exit

		etype  - exception type
		evalue  - exception value
		trcbck  - exception trcbck
		"""
		self.__terminate()
		# Note: the exception (if any) is propagated if True is not returned here


	def __del__(self):
		"""Destructor"""
		self.__terminate()


	def __finalize__(self):
		"""Late clear up called after the garbage collection (unlikely to be used)"""
		self.__terminate()


	def __terminate(self):
		"""Force termination of the pool"""
		# Wait for the new worker registration on the job starting if required,
		# which should be done << 10 ms
		acqlock = self.__termlock.acquire(True)  # , 0.05 50 ms
		self.alive = False  # The execution pool is terminating, should be always set on termination
		# The lock can't be acquired (takes more than 10 ms) only if the termination was already called
		if not acqlock or not (self._workers or self._jobs):
			if acqlock:
				self.__termlock.release()
			return
		try:
			tcur = time.perf_counter()  # Current time
			print('WARNING{}, terminating the execution pool with {} non-started jobs and {} workers'
				', executed {} h {} m {:.4f} s, call stack:'
				.format('' if not self.name else ' ' + self.name, len(self._jobs), len(self._workers)
				, *secondsToHms(0 if self._tstart is None else tcur - self._tstart)), file=sys.stderr)
			traceback.print_stack(limit=5, file=sys.stderr)

			# Shut down all [non-started] jobs
			for job in self._jobs:
				# Note: the restarting jobs are also terminated here without the owner task notification
				# since there is no time to execute the task handlers
				# Add terminating deferred job to the list of failures
				self.failures.append(JobInfo(job, tstop=tcur))
				# Note: only executing jobs, i.e. workers might have activated affinity
				print('  Scheduled non-started "{}" is removed'.format(job.name), file=sys.stderr)
			self._jobs.clear()

			# Shut down all workers
			active = False
			for job in self._workers:
				if job.proc.poll() is None:  # poll None means the process has not been terminated / completed
					job.terminates += 1
					print('  Terminating "{}" #{} ...'.format(job.name, job.proc.pid), file=sys.stderr)
					job.proc.terminate()
					active = True
			# Wait a few sec for the successful process termination before killing it
			i = 0
			while active and i < self._KILLDELAY:
				time.sleep(self._termlatency)
				i += 1
				active = False
				for job in self._workers:
					if job.proc.poll() is None:  # poll None means the process has not been terminated / completed
						job.terminates += 1
						job.proc.terminate()
						active = True

			# Kill non-terminated processes
			if active:
				for job in self._workers:
					if job.proc.poll() is None:
						print('  Killing "{}" #{} ...'.format(job.name, job.proc.pid), file=sys.stderr)
						job.proc.kill()
			# Tidy jobs
			for job in self._workers:
				self.__complete(job, False)
			self._workers.clear()
			## Set _wkslim to 0 to not start any jobs
			#self._wkslim = 0  # ATTENTION: reset of the _wkslim can break silent subsequent reuse of the execution pool
			self._traceFailures()
		except BaseException as err:
			print('ERROR on the pool "{}" termination occurred: {}. {}'.format(
				self.name, err, traceback.format_exc(5)), file=sys.stderr)
		finally:
			self.__termlock.release()


	def _traceFailures(self):
		"""Trace failed tasks with their jobs and jobs not belonging to any tasks and clean this list afterwards"""
		# Note: the lock for failures had to be used if the ExecPool would not be finished (unexpected)
		assert not (self._workers or self._jobs), (
			'Failures tracing is expected to be called after the ExecPool is finished')
		if not self.failures:
			return
		print('WARNING, {} jobs are failed in the ExecPool {}'.format(
			len(self.failures), '' if not self.name else self.name)
			, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		indent = '  '  # Indent for each level of the Task/Jobs tree
		colsep = ' '  # Table column separator
		tinfe0 = dict()  # dict(Task, TaskInfoExt)  - Task information extended, bottom level of the hierarchy
		# Print jobs properties as a table or fetch them to compose failed tasks hierarchy
		header = True  # Show header for the initial output
		strpad = 9  # Padding of the string cells
		for fji in self.failures:
			data = infodata(fji)
			# Note: data should not be None here
			# if data is None:
			# 	continue
			if fji.task is None:
				if header:
					print('\nFAILED jobs not assigned to any tasks:', file=sys.stderr if _DEBUG_TRACE else sys.stdout)
					# Header of the jobs
					print(colsep.join([tblfmt(h, strpad) for h in JobInfo.iterprop()])  #pylint: disable=E1101
						, file=sys.stderr if _DEBUG_TRACE else sys.stdout)  #pylint: disable=E1101
					header = False
				print(colsep.join([tblfmt(v, strpad) for v in data]), file=sys.stderr if _DEBUG_TRACE else sys.stdout)
			else:
				tie = tinfe0.get(fji.task)
				if tie is None:
					tie = tinfe0.setdefault(fji.task, TaskInfoExt(props=(TaskInfo.iterprop()  #pylint: disable=E1101
						, infodata(TaskInfo(fji.task))), jobs=[JobInfo.iterprop()]))  #pylint: disable=E1101
				tie.jobs.append(data)
		del self.failures[:]  # Required to avoid repetative tracing of the failures
		if not tinfe0:
			return

		# Iteratively form the hierarchy of failed tasks from the bottom level
		ties = tasksInfoExt(tinfe0)

		# Print failed tasks statistics
		print('\nFAILED root tasks ({} failed root / {} failed total / {} total):'.format(
			len(viewvalues(ties)), len(tinfe0), len(self.tasks)), file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		tinfe0 = None  # Release the initial dictionary
		# List names of the root failed tasks
		print(' '.join([tk.name for tk in ties]), file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		# Print hierarchy of the failed tasks from the root (top) level
		print('\nFAILED tasks with their jobs:', file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		for task, tie in viewitems(ties):
			# Omit repetitive listing of sub-hierarchies (they are listed from the root task)
			if task.task is None:
				printDepthFirst(tie, cindent='', indstep=indent, colsep=colsep)


	def __postpone(self, job, priority=False):
		"""Schedule this job for the later execution

		Schedule this job for the later execution if it does not violates timeout
		and memory limit (if it was terminated because of the group violation made
		not by a single worker process).

		job  - postponing (rescheduling) job
		priority  - priority scheduling (to the queue begin instead of the end).
			Used only when the job should should be started, but was terminated
			earlier (because of the timeout with restart or group memory limit violation)
		"""
		if not self.alive:
			print('WARNING, postponing of the job "{}" is canceled because'
				' the execution pool is not alive'.format(job.name))
			return
		# Note:
		# - postponing jobs are terminated jobs only, can be called for !_CHAINED_CONSTRAINTS;
		# - wksnum < self._wkslim
		# wksnum = len(self._workers)  # The current number of worker processes
		assert self._workers and ((job.terminates or job.tstart is None)
			# and _LIMIT_WORKERS_RAM and job not in self._workers and job not in self._jobs
			# # Note: self._jobs scanning is time-consuming
			and (not self.memlimit or job.mem < self.memlimit)  # and wksnum < self._wkslim
			and (job.tstart is None) == (job.tstop is None) and (not job.timeout
			or (True if job.tstart is None else job.tstop - job.tstart < job.timeout)
			) and (not self._jobs or not self.memlimit or self._jobs[0].wkslim >= self._jobs[-1].wkslim)), (
			'A terminated non-rescheduled job is expected that doest not violate constraints.'
			' "{}" terminates: {}, started: {}, jwkslim: {} vs {} pwkslim, priority: {}, {} workers, {} jobs: {};'
			'\nmem: {:.4f} / {:.4f} GB, exectime: {:.4f} ({} .. {}) / {:.4f} sec'.format(
			job.name, job.terminates, job.tstart is not None, '-' if not self.memlimit else job.wkslim, self._wkslim
			, priority, len(self._workers), len(self._jobs)
			, ', '.join(['#{} {}'.format(ij, j.name) for ij, j in enumerate(self._jobs)]) if self.memlimit else (
			', '.join(['#{} {}: {}'.format(ij, j.name, j.wkslim) for ij, j in enumerate(self._jobs)]))
			, 0 if not self.memlimit else job.mem, self.memlimit
			, 0 if job.tstop is None else job.tstop - job.tstart, job.tstart, job.tstop, job.timeout))
		# Postpone only the group-terminated jobs by memory limit, not a single worker
		# that exceeds the (time/memory) constraints (except the explicitly requested
		# restart via rsrtonto, which results the priority rescheduling)
		# Note: job wkslim should be updated before adding to the _jobs to handle
		# correctly the case when _jobs were empty
		# print('>  Nonstarted initial jobs: ', ', '.join(['{} ({})'.format(pj.name, pj.wkslim) for pj in self._jobs]))
		#
		# Note: terminate time is reseted on job start in case of restarting
		## Reset job.proc to remove it from the sub-processes table and avoid zombies for the postponed jobs
		## - it does not impact on the existence of zombie procs
		#if job.terminates:
		#	job.proc = None  # Reset old job process if any
		i = len(self._jobs)  # ATTENTION: required for _CHAINED_CONSTRAINTS processing
		if not self.memlimit or not self._jobs or self._jobs[-1].wkslim > job.wkslim or (
		self._jobs[-1].wkslim == job.wkslim and not priority):
			self._jobs.append(job)
		else:
			jobsnum = i
			i = 0
			if priority:
				# Add to the begin of jobs with the same wkslim
				while i < jobsnum and self._jobs[i].wkslim > job.wkslim:
					i += 1
			else:
				# Add to the end of jobs with the same wkslim
				i = jobsnum - 1
				while i >= 0 and self._jobs[i].wkslim < job.wkslim:
					i -= 1
				i += 1
			# Note: i < jobsnum due to the top if branch
			#if i != jobsnum:
			self._jobs.rotate(-i)
			self._jobs.appendleft(job)
			self._jobs.rotate(i)
			#else:
			#	self._jobs.append(job)

		# Update limit of the worker processes of the other larger non-started jobs
		# of the same category as the added job has
		if _CHAINED_CONSTRAINTS and job.category is not None:
			k = 0
			kend = i
			while k < kend:
				pj = self._jobs[k]
				if pj.category == job.category and pj.size >= job.size:
					# Set mem for the related non-started heavier jobs
					if self.memlimit and pj.mem < job.mem:
						pj.mem = job.mem
					if job.wkslim < pj.wkslim:  # Note: normally this never happens
						pj.wkslim = job.wkslim
						# Update location of the jobs in the queue, move the updated
						# job to the place before the origin
						if kend - k >= 2:  # There is no sense to reschedule pair of subsequent jobs
							self._jobs.rotate(-k)
							# Move / reschedule the job
							jmv = self._jobs.popleft()  # == pj; -1
							assert jmv is pj, ('The rescheduling is invalid, unexpected job is removed:'
								' {} instead of {}'.format(jmv.name, pj.name))
							self._jobs.rotate(1 + k-i)  # Note: 1+ because one job is removed
							self._jobs.appendleft(pj)
							self._jobs.rotate(i-1)
							kend -= 1  # One more job is added before i
							k -= 1  # Note: k is incremented below
				k += 1
		# print('>  Nonstarted updated jobs: ', ', '.join(['{} ({})'.format(pjob.name, pjob.wkslim) for pjob in self._jobs]))


	def __start(self, job, concur=True):
		"""Start the specified job by one of the worker processes

		job  - the job to be executed, instance of Job
		concur  - concurrent execution or wait till the job execution completion
		return  - 0 on successful execution, proc.returncode otherwise
		"""
		assert isinstance(job, Job) and (job.tstop is None or job.terminates), (
			'The starting job "{}" is expected to be non-completed'.format(job.name))
		wksnum = len(self._workers)  # The current number of worker processes
		if (concur and wksnum >= self._wkslim) or not self._wkslim or not self.alive:
			# Note: can be cause by the execution pool termination
			raise ValueError('Free workers should be available ({} busy workers of {}), alive: {}'
				.format(wksnum, self._wkslim, self.alive))
		#if _DEBUG_TRACE:
		print('Starting "{}"{}, workers: {} / {}...'.format(job.name, '' if concur else ' in sequential mode'
			, wksnum, self._wkslim), file=sys.stderr if _DEBUG_TRACE else sys.stdout)

		# Reset automatically defined values for the restarting job, which is possible only if it was terminated
		if job.terminates:
			job.terminates = 0  # Reset termination requests counter
			job.proc = None  # Reset old job process if any
			job.pipedout = None  # Reset piped stdout if any
			job.pipederr = None  # Reset piped stderr if any
			job.tstop = None  # Reset the completion / termination time
			job._restarting = False
			# Note: retain previous value of mem for better scheduling, it is the valid value for the same job
		# Update execution pool tasks, should be done before the job.onstart()
		# Note: the lock is not required here because tasks are also created in the main thread
		# Consider all supertasks
		jst = job.task
		# Note: `jst not in self.tasks` whould prevent super-tasks extension after the jobs started
		# because a task starts when its first job starts.
		while jst is not None:
			self.tasks.add(jst)
			jst = jst.task
		job.tstart = time.perf_counter()
		if job.onstart:
			# print('>  Starting onstart() for job "{}"'.format(job.name), file=sys.stderr)
			try:
				job.onstart()
			except Exception as err:  #pylint: disable=W0703
				print('ERROR in onstart() callback of "{}": {}, the job is discarded. {}'
					.format(job.name, err, traceback.format_exc(5)), file=sys.stderr)
				errinf = getattr(err, 'errno', None)
				return -1 if errinf is None else errinf.errorcode
		# Consider custom output channels for the job
		job._stdout = None
		job._stderr = None
		acqlock = False  # The lock is acquired and should be released
		try:
			# Initialize job._stdout/err by the required output channel
			timestamp = None
			for joutp in (job.stdout, job.stderr):
				if joutp and isinstance(joutp, str):
					basedir = os.path.split(joutp)[0]
					if basedir and not os.path.exists(basedir):
						os.makedirs(basedir)
					try:
						fout = None
						if joutp is job.stdout:
							fout = open(joutp, 'a')  # Note: the file is closed by the ExecPool on the job worker completion
							job._stdout = fout  #pylint: disable=W0212
							outcapt = 'stdout'
						elif joutp is job.stderr:
							fout = open(joutp, 'a')  # Note: the file is closed by the ExecPool on the job worker completion
							job._stderr = fout  #pylint: disable=W0212
							outcapt = 'stderr'
						else:
							raise ValueError('Invalid output stream value: ' + str(joutp))
						# Add a timestamp if the FILE is not empty to distinguish logs
						if fout is not None and os.fstat(fout.fileno()).st_size:
							if timestamp is None:
								timestamp = time.gmtime()
							print(timeheader(timestamp), file=fout)  # Note: prints also newline unlike fout.write()
					except IOError as err:
						print('ERROR on opening custom {} "{}" for "{}": {}. Default is used.'
							.format(outcapt, joutp, job.name, err), file=sys.stderr)
						if joutp is job.stdout:
							job._stdout = sys.stdout
						if joutp is job.stderr:
							job._stderr = sys.stderr
				else:
					if joutp is job.stdout:
						job._stdout = joutp
					elif joutp is job.stderr:
						job._stderr = joutp
					else:
						raise ValueError('Invalid output stream channel: ' + str(joutp))

			# print('> "{}" output channels:\n\tstdout: {}\n\tstderr: {}'.format(job.name
			# 	, job.stdout, job.stderr))  # Note: write to log, not to the stderr
			if job.args:
				# Consider CPU affinity
				# Note: the exception is raised by .index() if the _affinity table
				# is corrupted (doesn't have the free entry)
				# Index in the affinity table to bind process to the CPU/core
				iafn = -1 if not self._affinity or job._omitafn else self._affinity.index(None)  #pylint: disable=W0212
				if iafn >= 0:
					job.args = [_AFFINITYBIN, '-c', self._afnmask(iafn)] + list(job.args)
				# print('>  Opening proc for "{}" with:\n\tjob.args: {},\n\tcwd: {}'.format(job.name
				# 	, ' '.join(job.args), job.workdir), file=sys.stderr)
				acqlock = self.__termlock.acquire(False, 0.01)  # 10 ms
				if not acqlock or not self.alive:
					if acqlock:
						self.__termlock.release()
					# Note: it just interrupts job start, but does not cause termination
					# of the whole (already terminated) execution pool
					raise EnvironmentError((errno.EINTR,  # errno.ERESTART
						'Jobs can not be started because the execution pool has been terminated'))
				# bufsize=-1 - use system default IO buffer size
				job.proc = subprocess.Popen(job.args, bufsize=-1, cwd=job.workdir, stdout=job._stdout, stderr=job._stderr)
				# Update job logging descriptors in case of PIPEs to the actual system objects
				if job._stdout is subprocess.PIPE:
					job._stdout = job.proc.stdout
				if job._stderr is subprocess.PIPE:
					job._stderr = job.proc.stderr
				if concur:
					self._workers.add(job)
				# ATTENTION: the exception can be raised before the lock releasing on process creation
				self.__termlock.release()
				# Note: an exception can be thrown below, but the lock is already
				# released and should not be released again
				acqlock = False
				if iafn >= 0:
					try:
						self._affinity[iafn] = job.proc.pid
						print('"{jname}" #{pid}, iafn: {iafn} (CPUs #: {icpus})'
							.format(jname=job.name, pid=job.proc.pid, iafn=iafn
							, icpus=self._afnmask(iafn)))  # Note: write to log, not to the stderr
					except IndexError as err:
						# Note: BaseException is used to terminate whole execution pool
						raise BaseException('Affinity table is inconsistent: {}'.format(err))
				# Wait a little bit to start the process besides its scheduling
				if job.startdelay > 0:
					time.sleep(job.startdelay)
		except BaseException as err:  # Should not occur: subprocess.CalledProcessError
			# ATTENTION: the exception could be raised on process creation or on not self.alive
			# with acquired lock, which should be released
			if acqlock:
				self.__termlock.release()
			print('ERROR on "{}" start occurred: {}, the job is discarded. {}'.format(
				job.name, err, traceback.format_exc(5)), file=sys.stderr)
			# Note: process-associated file descriptors are closed in complete()
			if job.proc is not None and job.proc.poll() is None:  # Note: this is an extra rare, but possible case
				# poll None means the process has not been terminated / completed,
				# which can be if sleep() generates exception or if the system
				# interrupted called [and the sequential] process already created
				active = True
				i = 0
				while active and i < self._KILLDELAY:
					i += 1
					active = False
					if job.proc.poll() is None:  # poll None means the process has not been terminated / completed
						job.terminates += 1
						job.proc.terminate()
						active = True
					time.sleep(self._termlatency)
				# Kill non-terminated process
				if active:
					if job.proc.poll() is None:
						print('  Killing ~hanged "{}" #{} ...'.format(job.name, job.proc.pid), file=sys.stderr)
						job.proc.kill()
			self.__complete(job, False)
			# ATTENTION: re-raise exception for the BaseException but not Exception sub-classes
			# to have termination of the whole pool by the system interruption
			if not isinstance(err, Exception):
				raise
		else:
			if concur:
				return 0
			# Sequential non-concurrent job processing
			err = None
			try:
				# Before waiting on the process its output should be fetched if PIPE is used
				# otherwise it may cause a deadlock:
				# https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
				if job.stdout is subprocess.PIPE or job.stderr is subprocess.PIPE:
					# Note: .fetchPipedData() waits by default until the pipe is closed, which
					# happens on the process completion but also can be performed earlier
					job.fetchPipedData()
				job.proc.wait()
			except BaseException as err:  # Should not occur: subprocess.CalledProcessError
				print('ERROR on the sequential execution of "{}" occurred: {}, the job is discarded. {}'
					.format(job.name, err, traceback.format_exc(5)), file=sys.stderr)
			finally:
				self.__complete(job, not job.terminates and not job.proc.returncode)
			# ATTENTION: re-raise exception for the BaseException but not Exception sub-classes
			# to have termination of the whole pool by the system interruption
			if err and not isinstance(err, Exception):
				raise err
		if job.proc.returncode:
			print('WARNING, "{}" failed to start, errcode: {}'.format(job.name, job.proc.returncode), file=sys.stderr)
		return job.proc.returncode


	def __complete(self, job, graceful=None):
		"""Complete the job tidying affinity if required

		job  - the job to be completed
		graceful  - the completion is graceful (job was not terminated internally
			due to some error or externally).
			None means unknown and should be identified automatically.
		"""
		if self._affinity and not job._omitafn and job.proc is not None:  #pylint: disable=W0212
			try:
				self._affinity[self._affinity.index(job.proc.pid)] = None
			except ValueError:
				print('WARNING, affinity cleanup is requested to the job "{}" without the activated affinity'
					.format(job.name), file=sys.stderr)
				# Do nothing if the affinity is not set for this process
		if graceful is None:
			graceful = not job.terminates and job.proc is not None and not job.proc.returncode
		# Note: job completion also calls finalization of the owner task and
		# may communicate with the process to fetch the PIPE output
		try:
			job.complete(graceful)
		except Exception as err:  #pylint: disable=W0703
			print('ERROR, job "{}" completion failed: {}. {}'.format(
				job.name, err, traceback.format_exc(5)), file=sys.stderr)
		# Close process-related file/object descriptors
		# ATTENTION: PIPEd channels should be closed only AFTER the job.complete(),
		# which redirects their output to the log files if required.
		#
		# I case of Pipes:
		# Finalize the output channels for the PIPEs, which is essential if they are used as input channels
		# to another processes since in such case it yields SIGPIPE:
		# https://docs.python.org/3/library/subprocess.html#subprocess.Popen.stdout
		# Note: proc.stdout and/or proc.stderr are not None only if the PIPEs are used
		# for pout in (job.proc.stdout, job.proc.stderr):
		#
		# Note: here pout can be a file, system output object or system pipe related object
		for pout in (job._stdout, job._stderr):
			if pout not in (None, sys.stdout, sys.stderr):
				try:
					pout.close()
				except AttributeError:  # .close() method does not exist in this object
					pass
				except IOError as err:
					print('ERROR, job "{}" I/O closing failed: {}. {}'.format(
						job.name, err, traceback.format_exc(5)), file=sys.stderr)
		job._stdout = None
		job._stderr = None

		# Update failures list skipping automatically restarting tasks
		if graceful:
			self.jobsdone += 1
		elif not job._restarting:
			self.failures.append(JobInfo(job))  # Note: job.tstop should be defined here


	def __reviseWorkers(self):
		"""Revise the workers

		Check for the completed jobs and their timeouts, update corresponding
		workers and start the non-started jobs if possible.
		Apply chained termination and rescheduling on timeout and memory
		constraints violation if _CHAINED_CONSTRAINTS.
		NOTE: This function is not termination safe (might yield exceptions) but it doesn't matter.
		"""
		# Process completed jobs, check timeouts and memory constraints matching
		completed = set()  # Completed workers:  {proc,}
		memall = 0.  # Consuming memory by workers
		jtorigs = {}  # Timeout caused terminating origins (jobs) for the chained termination, {category: lightweightest_job}
		jmorigs = {}  # Memory limit caused terminating origins (jobs) for the chained termination, {category: smallest_job}
		terminating = False  # At least one worker is terminating
		tcur = time.perf_counter()  # Current timestamp
		for job in self._workers:
			# Note: check for the termination in all cycles
			if not self.alive:
				return
			if job.proc.poll() is not None:  # Not None means the process has been terminated / completed
				completed.add(job)
				continue

			exectime = tcur - job.tstart
			# Update memory statistics (if required) and skip jobs that do not exceed the specified time/memory constraints
			if not job.terminates and (not job.timeout or exectime < job.timeout
			# Note: self.memlimit indicates that ExecPool tracs the memory consumption (sets job.mem)
			) and (not self.memlimit or (job.mem < self.memlimit and (not job.memlim or job.mem < job.memlim))):
				# Update memory consumption statistics if applicable
				if self.memlimit:
					# NOTE: Evaluate memory consumption for the heaviest process in the process tree
					# of the origin job process to allow additional intermediate apps for the evaluations like:
					# ./exectime ./clsalg ca_prm1 ca_prm2
					job._updateMem()  #pylint: disable=W0212;  Consider mem consumption of the past runs if any
					if job.mem < self.memlimit:
						memall += job.mem  # Consider mem consumption of past runs if any
						#if _DEBUG_TRACE >= 3:
						#	print('>  "{}" consumes {:.4f} GB, memall: {:.4f} GB'.format(job.name, job.mem, memall), file=sys.stderr)
						continue
					# The memory limits violating worker will be terminated
				else:
					continue

			# Terminate the worker because of the timeout/memory constraints violation
			terminating = True
			job.terminates += 1
			# Save the most lightweight terminating chain origins for timeouts and memory overuse by the single process
			if _CHAINED_CONSTRAINTS and job.category is not None and job.size:
				# ATTENTION: do not terminate related jobs of the process that should be restarted by timeout,
				# because such processes often have non-deterministic behavior and specially scheduled to be
				# re-executed until success
				if job.timeout and exectime >= job.timeout and not job.rsrtonto:
					# Timeout constraints
					jorg = jtorigs.get(job.category, None)
					if jorg is None or job.size * job.slowdown < jorg.size * jorg.slowdown:
						jtorigs[job.category] = job
				# Note: self.memlimit indicates that ExecPool tracs the memory consumption (sets job.mem)
				elif self.memlimit and (job.mem >= self.memlimit or (job.memlim and job.mem >= job.memlim)):
					# Memory limit constraints
					jorg = jmorigs.get(job.category, None)
					if jorg is None or job.size < jorg.size:
						jmorigs[job.category] = job
				# Otherwise this job is terminated because of multiple processes together overused memory,
				# it should be rescheduled, but not removed completely

			# Force killing when the termination does not work
			if job.terminates >= self._KILLDELAY:
				job.proc.kill()
				completed.add(job)
				if _DEBUG_TRACE:  # Note: anyway completing terminated jobs are traced
					print('WARNING, "{}" #{} is killed because of the {} violation'
						' consuming {:.4f} GB with timeout of {:.4f} sec, executed: {:.4f} sec ({} h {} m {:.4f} s)'
						.format(job.name, job.proc.pid
						, 'timeout' if job.timeout and exectime >= job.timeout else (
							('' if not self.memlimit or job.mem >= self.memlimit
								or (job.memlim and job.mem >= job.memlim) else 'group ') + 'memory limit')
						, 0 if not self.memlimit else job.mem
						, job.timeout, exectime, *secondsToHms(exectime)), file=sys.stderr)
			else:
				job.proc.terminate()  # Schedule the worker completion to the next revise

		# Terminate chained related workers and jobs of the single jobs that violate timeout/memory constraints
		if _CHAINED_CONSTRAINTS and (jtorigs or jmorigs):
			# Traverse over the workers with defined job category and size
			for job in self._workers:
				# Note: check for the termination in all cycles
				if not self.alive:
					return
				# Note: even in the seldom case of the terminating job, it should be marked if chained-dependent
				# of the constraints violating job, to not be restarted (by request on timeout) or postponed
				if job.category is not None and job.size:
					# Travers over the chain origins and check matches skipping the origins themselves
					# Timeout chains
					for jorg in viewvalues(jtorigs):
						# Note: job !== jorg, because jorg terminates and job does not
						if (job.category == jorg.category  # Skip already terminating items
						and job is not jorg
						and job.size * job.slowdown >= jorg.size * jorg.slowdown):
							job.chtermtime = True  # Chained termination by time
							terminating = True
							if job.terminates:
								break  # Switch to the following job
							# Terminate the worker
							job.terminates += 1
							job.proc.terminate()  # Schedule the worker completion to the next revise
							if self.memlimit:
								memall -= job.mem  # Reduce total memory consumed by the active workers
							break  # Switch to the following job
					else:
						# Memory limit chains
						for jorg in viewvalues(jmorigs):
							# Note: job !== jorg, because jorg terminates and job does not
							if (job.category == jorg.category  # Skip already terminating items
							and job is not jorg
							and job.lessmem(jorg) is False):
								job.chtermtime = False  # Chained termination by memory
								terminating = True
								if job.terminates:
									break  # Switch to the following job
								# Terminate the worker
								job.terminates += 1
								job.proc.terminate()  # Schedule the worker completion to the next revise
								memall -= job.mem  # Reduce total memory consumed by the active workers
								break  # Switch to the following job
			# Traverse over the non-started jobs with defined job category and size removing too heavy jobs
			# if _DEBUG_TRACE >= 2:
			# 	print('>  Updating chained constraints in non-started jobs: ', ', '.join([job.name for job in self._jobs]))
			jrot = 0  # Accumulated rotation
			ij = 0  # Job index
			while ij < len(self._jobs) - jrot:  # Note: len(jobs) catches external jobs termination / modification
				job = self._jobs[ij]
				if job.category is not None and job.size:
					# Travers over the chain origins and check matches skipping the origins themselves
					# Time constraints
					for jorg in viewvalues(jtorigs):
						if (job.category == jorg.category
						and job.size * job.slowdown >= jorg.size * jorg.slowdown):
							# Remove the item adding it to the list of failed jobs
							self._jobs.rotate(-ij)
							jrot += ij
							# Notify owner task of the failed restarting jobs
							jrm = self._jobs.popleft()
							if jrm._restarting and jrm.task:
								jrm.task.finished(self, False)
							self.failures.append(JobInfo(jrm, tcur))
							ij = -1  # Later +1 is added, so the index will be 0
							print('WARNING, non-started "{}" with weight {} is canceled by timeout chain from "{}" with weight {}'.format(
								job.name, job.size * job.slowdown, jorg.name, jorg.size * jorg.slowdown), file=sys.stderr)
							break
					else:
						# Memory limit constraints
						for jorg in viewvalues(jmorigs):
							if (job.category == jorg.category
							and job.lessmem(jorg) is False):
								# Remove the item adding it to the list of failed jobs
								self._jobs.rotate(-ij)
								jrot += ij
								# Notify owner task of the failed restarting jobs
								jrm = self._jobs.popleft()
								if jrm._restarting and jrm.task:
									jrm.task.finished(self, False)
								self.failures.append(JobInfo(jrm, tcur))
								ij = -1  # Later +1 is added, so the index will be 0
								print('WARNING, non-started "{}" with size {} is canceled by memory limit chain from "{}" with size {}'
									' and mem {:.4f}'.format(job.name, job.size, jorg.name, jorg.size, jorg.mem), file=sys.stderr)
								break
				ij += 1
			# Recover initial order of the jobs
			self._jobs.rotate(jrot)
		# check for the external termination
		if not self.alive:
			return
		# Remove terminated/completed jobs from worker processes
		# ATTENTINON: it should be done after the _CHAINED_CONSTRAINTS check to
		# mark the completed dependent jobs to not be restarted / postponed
		# Note: jobs complete execution relatively seldom, so set with fast
		# search is more suitable than full scan of the list
		for job in completed:
			self._workers.remove(job)

		# Check memory limitation fulfilling for all remained processes and resource consumption counters
		if self.memlimit:
			# Amount of free RAM (RSS) in GB; skip it if memlimit is not requested
			memfree = inGigabytes(psutil.virtual_memory().available)
		# Jobs should use less memory than the limit
		# Consider terminatin of all executing workers by the constraints violation
		if self._workers and self.memlimit and (memall >= self.memlimit or memfree <= self._MEMLOW):
			# Terminate the largest workers and reschedule jobs or reduce the workers number
			wksnum = len(self._workers)
			# Overused memory with some gap (to reschedule less) to be released by worker(s) termination
			memov = memall - self.memlimit * (wksnum / (wksnum + 1.)
				) if memall >= self.memlimit else (self._MEMLOW + self.memlimit / (wksnum + 1.))
			pjobs = set()  # The heaviest jobs to be postponed to satisfy the memory limit constraint
			# Remove the heaviest workers until the memory limit constraints are satisfied
			hws = []  # Heavy workers
			# ATTENTION: at least one worker should be remained after the reduction
			# Note: at least one worker should be remained
			# Note: memory overuse should be negative, i.e. underuse to start any another job,
			# 0 in practice is insufficient of the subsequent execution
			while memov >= 0 and wksnum - len(pjobs) > 1:
				# Reinitialize the heaviest remained jobs and continue
				for job in self._workers:
					if not self.alive or (not job.terminates and job not in pjobs):
						hws.append(job)  # Take the first appropriate executing job as a heavy one
						break
				assert hws, 'Non-terminated heavy worker processes must exist here: {} / {}'.format(
					len(hws), wksnum)
				# Allow x times longer running jobs to use sqrt(x) more RAM
				hwdur = sqrt(tcur - hws[-1].tstart)
				for job in self._workers:
					# Note: check for the termination in all cycles
					if not self.alive:
						return
					# Extend the heavy jobs list with more heavy items than the already present there
					# Note: use some threshold for mem evaluation and consider starting time on scheduling
					# to terminate first the least worked processes (for approximately the same memory consumption)
					# dr = 0.1  # Threshold parameter ratio, recommended value: 0.05 - 0.15; 0.1 means delta of 10%
					# if not job.terminates and ((job.mem * (1 - dr) >= hws[-1].mem and job.tstart > hws[-1].tstart)
					# or job.mem * (1 + dr/2) >= hws[-1].mem) and job not in pjobs:
					jdur = sqrt(tcur - job.tstart)
					if not job.terminates and job.mem * min(max(hwdur / jdur, self._JMEMLIML), self._JMEMLIMH
					) >= hws[-1].mem and job not in pjobs:
						hws.append(job)
						hwdur = jdur
				# Move the largest jobs to postponed until memov is negative
				while memov >= 0 and hws and wksnum - len(pjobs) > 1:  # Retain at least a single worker
					job = hws.pop()
					pjobs.add(job)
					memov -= job.mem
				if _DEBUG_TRACE:
					print('  Group mem limit violation removing jobs: {}, remained: {} (from the end)'
						.format(', '.join([j.name for j in pjobs]), ', '.join([j.name for j in hws])))
			# Terminate and remove worker processes of the postponing jobs
			# New workers limit for the postponing job  # max(self._wkslim, len(self._workers))
			wkslim = self._wkslim - len(pjobs)
			assert wkslim >= 1, 'The number of workers should not be less than 1'
			if pjobs and self.alive:
				terminating = True
				while pjobs:
					job = pjobs.pop()
					# Update amount of the estimated memall
					memall -= job.mem
					# Terminate the worker (postponing the job on the next iteration)
					job.terminates += 1
					job._restarting = True
					# Schedule the worker completion (including removal from the workers) to the next revise
					job.proc.terminate()
					# Update wkslim
					job.wkslim = wkslim
				assert memall > 0, ('The workers should remain and consume some memory'
					', memall: {:.4f}, jmem: {:.4f} ({}), {} pjobs, {} workers, self._wkslim: {} / {}'
					.format(memall, job.mem, job.name, len(pjobs), wksnum, wkslim, self._wkslim))
		elif not self._workers:
			wkslim = self._wkslim
			memall = 0.

		# Process completed (and terminated) jobs: execute callbacks and remove the workers
		for job in completed:
			# Note: check for the termination in all cycles, gracefull jobs completion is not mandatory here
			# since the completed app cleans them
			if not self.alive:
				return
			# The completion is graceful only if the termination requests were not received
			self.__complete(job, not job.terminates and not job.proc.returncode)
			exectime = job.tstop - job.tstart
			# Restart the job if it was terminated and should be restarted
			if not job.terminates:
				continue
			print('WARNING, "{}" #{} is terminated because of the {} violation'
				', chtermtime: {}, consumes {:.4f} / {:.4f} GB, timeout {:.4f} sec, executed: {:.4f} sec ({} h {} m {:.4f} s)'
				.format(job.name, job.proc.pid
				, 'timeout' if job.timeout and exectime >= job.timeout else (
					('' if not self.memlimit or job.mem >= self.memlimit
						or (job.memlim and job.mem >= job.memlim) else 'group ') + 'memory limit')
				, None if not _CHAINED_CONSTRAINTS else job.chtermtime
				, 0 if not self.memlimit else job.mem, self.memlimit
				, job.timeout, exectime, *secondsToHms(exectime)), file=sys.stderr)
			# Skip memory limit and timeout violating jobs that do not require auto-restart (applicable only for the timeout)
			if (job.timeout and exectime >= job.timeout and not job.rsrtonto) or (_CHAINED_CONSTRAINTS
			# Note: self.memlimit indicates that ExecPool tracs the memory consumption (sets job.mem)
			and job.chtermtime is not None) or (self.memlimit and (job.mem >= self.memlimit
			or (job.memlim and job.mem >= job.memlim))):
				continue
			# Reschedule job having the group violation of the memory limit
			# if timeout is not violated or restart on timeout is requested
			# Note: self._workers to not postpone the single existing job
			if self._workers and self.memlimit and (
			memall + job.mem * self._JMEMTRR >= self.memlimit
			or memfree - job.mem * self._JMEMTRR <= self._MEMLOW) and (
			# Note: use priority restart below for job.rsrtonto
			not job.timeout or exectime < job.timeout):
				self.__postpone(job)
			# Restart the job if the workers are empty or on timeout by the REQUEST (rsrtonto)
			elif not self._workers or (job.rsrtonto and exectime >= job.timeout):
				# Note: if the job was terminated by timeout then memory limit was not met
				# Note: earlier executed job might not fit into the RAM now because of
				# the increasing mem consumption by the workers
				#if _DEBUG_TRACE >= 3:
				#	print('  "{}" is being rescheduled, workers: {} / {}, estimated mem: {:.4f} / {:.4f} GB'
				#		.format(job.name, len(self._workers), self._wkslim, memall + job.mem, self.memlimit)
				#		, file=sys.stderr)
				#assert not self.memlimit or memall + job.mem * self._JMEMTRR < self.memlimit, (
				#	'Group exceeding of the memory limit should be already processed')
				if not self.__start(job) and self.memlimit:  # Note: successful start returns 0
					memall += job.mem  # Reuse .mem from the previous run if exists
				# Note: do not call complete() on failed restart
			else:
				assert self._workers and (not job.timeout or exectime < job.timeout
					), 'Timeout violating jobs should be already skipped and workers should exist'
				# The job was terminated (by group violation of memory limit or timeout with restart),
				# but now can be started successfully and will be started soon
				self.__postpone(job, True)
		# Note: the number of workers is not reduced to less than 1

		# Note: active_children() does not impact on the existence of zombie procs,
		# proc table clearup implemented in complete() using wait()
		#if cterminated:
		#	# Note: required to join terminated child procs and avoid zombies
		#	# Return list of all live children of the current process,joining any processes which have already finished
		#	active_children()

		# Start subsequent job or postpone it further
		# if _DEBUG_TRACE >= 2:
		# 	print('  Nonstarted jobs: ', ', '.join(['{} ({})'.format(job.name, job.wkslim) for job in self._jobs]))
		if not terminating or not self._workers:  # Start only after the terminated jobs terminated and released the memory
			while self._jobs and len(self._workers) < self._wkslim and self.alive:
				#if _DEBUG_TRACE >= 3:
				#	print('  "{}" (expected totmem: {:.4f} / {:.4f} GB) is being rescheduled, {} non-started jobs: {}'
				#		.format(self._jobs[0].name, 0 if not self.memlimit else memall + job.mem, self.memlimit
				#		, len(self._jobs), ', '.join([j.name for j in self._jobs])), file=sys.stderr)
				job = self._jobs[0]
				# Jobs should use less memory than the limit, a worker process violating
				# (time/memory) constraints are already filtered out
				# Note: self._workers to not postpone the single existing job
				if self.memlimit:
					# Extended estimated job mem
					jmemx = (job.mem if job.mem else memall / (1 + len(self._workers))) * self._JMEMTRR
				if self._workers and self.memlimit and ((memall + jmemx >= self.memlimit
				# Note: omit the low memory condition for a single worker, otherwise the pool can't be executed
				) or (memfree - jmemx <= self._MEMLOW)):  # (memfree - jmemx <= self._MEMLOW and self._workers)
					# Note: only restarted jobs have defined mem
					# Postpone the job updating its workers limit
					assert job.mem < self.memlimit and (not job.memlim or job.mem < job.memlim
						), 'The workers exceeding memory constraints were already filtered out'
					if job.mem:
						self.__postpone(self._jobs.popleft())
					break
				elif not self.__start(self._jobs.popleft()):  # Note: successful start returns 0
					if self.memlimit:
						memall += job.mem  # Reuse .mem from the previous run if exists
					# If the jobs terminated and workers became empty then only a single worker should be created
					if terminating:
						break
		assert (self._workers or not self._jobs) and self._wkslim and (
			len(self._workers) <= self._wkslim), (
			'Worker processes should always exist if non-started jobs are remained:'
			'  workers: {}, wkslim: {}, jobs: {}'.format(len(self._workers)
			, self._wkslim, len(self._jobs)))


	def clear(self):
		"""Clear execution pool to reuse it

		Raises:
			ValueError: attempt to clear a terminating execution pool
		"""
		if not self._workers and not self._jobs:
			print('WARNING{}, a dirty execution pool is cleared'
				.format('' if not self.name else ' ' + self.name)
				, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
			self._tstart = None
			self.alive = True
			del self.failures[:]
			self.tasks.clear()
		else:
			raise ValueError('Terminating dirty execution pool can not be reseted:'
				'  alive: {}, {} workers, {} jobs'.format(self.alive
				, len(self._workers), len(self._jobs)))


	def execute(self, job, concur=True):
		"""Schedule the job for the execution

		job: Job  - the job to be executed, instance of Job
		concur: bool  - concurrent execution or wait until execution completed
			 NOTE: concurrent tasks are started at once
		return int  - 0 on successful execution, process return code otherwise
		"""
		if not self.alive:
			print('WARNING, scheduling of the job "{}" is canceled because'
				' the execution pool is not alive'.format(job.name)
				, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
			return errno.EINTR
		#assert isinstance(job, Job) and job.name, ('The job "{}" has invalid type'
		# ' or not initialized: '.format(job.name, type(job).__name__))
		# Note: _wkslim an be 0 only on/after the termination
		assert len(self._workers) <= self._wkslim and self._wkslim >= 1, (
			'Number of workers exceeds the limit or the pool has been terminated:'
			'  workers: {}, wkslim: {}, alive: {}'
			.format(len(self._workers), self._wkslim, self.alive))

		# if _DEBUG_TRACE >= 2:
		# 	print('Scheduling the job "{}" with timeout {}'.format(job.name, job.timeout))
		errcode = 0
		# Start the execution timer
		if self._tstart is None:
			self._tstart = time.perf_counter()
		# Initialize the [latest] value of job workers limit
		if self.memlimit and not job.wkslim:
			# Consider earlier executed jobs and updated execution pool
			job.wkslim = self._wkslim if not job.wkslim else min(job.wkslim, self._wkslim)
		if concur:
			# Evaluate total memory consumed by the worker processes
			if self.memlimit:
				memall = 0.
				for wj in self._workers:
					memall += wj.mem
				# Amount of free RAM (RSS) in GB; skip it if memlimit is not requested
				memfree = inGigabytes(psutil.virtual_memory().available)
				# Extended estimated job mem
				jmemx = (job.mem if job.mem else memall / (1 + len(self._workers))) * self._JMEMTRR
			# Schedule the job, postpone it if already non-started jobs exist or there are no any free workers
			if self._workers and (self._jobs or len(self._workers) >= self._wkslim or (
			self.memlimit and ((memall + jmemx >= self.memlimit
			# Note: omit the low memory condition for a single worker, otherwise the pool can't be executed
			) or (memfree - jmemx <= self._MEMLOW)))):  # (memfree - jmemx <= self._MEMLOW and self._workers)
				# if _DEBUG_TRACE >= 2:
				# 	print('  Postponing "{}", {} jobs, {} workers, {} wkslim'
				# 		', group memlim violation: {}, lowmem: {}'.format(job.name, len(self._jobs)
				# 		, len(self._workers), self._wkslim, self.memlimit and (memall and memall + (job.mem if job.mem else
				# 		memall / (1 + len(self._workers))) * self._JMEMTRR >= self.memlimit)
				# 		, self.memlimit and (memfree - jmemx <= self._MEMLOW and self._workers)))
				if not self.memlimit or not self._jobs or self._jobs[-1].wkslim >= job.wkslim:
					self._jobs.append(job)
				else:
					jobsnum = len(self._jobs)
					# Add to the end of jobs with the same wkslim
					i = jobsnum - 1
					while i >= 0 and self._jobs[i].wkslim < job.wkslim:
						i -= 1
					i += 1
					# Note: i < jobsnum in the else branch
					self._jobs.rotate(-i)
					self._jobs.appendleft(job)
					self._jobs.rotate(i)
				#self.__reviseWorkers()  # Anyway the workers are revised if exist in the working cycle
			else:
				if _DEBUG_TRACE >= 2:
					print('  Starting "{}", {} jobs, {} workers, {} wkslim'.format(job.name, len(self._jobs)
						, len(self._workers), self._wkslim))
				errcode = self.__start(job)
		else:
			errcode = self.__start(job, False)
			# Note: sequential non-concurrent job is completed automatically on any fails
		return errcode


	def join(self, timeout=0.):
		"""Execution cycle

		timeout: int  - execution timeout in seconds before the workers termination, >= 0.
			0 means unlimited time. The time is measured SINCE the first job
			was scheduled UNTIL the completion of all scheduled jobs.
		return bool  - True on graceful completion, False on termination by the specified
			constraints (timeout, memory limit, etc.)
		"""
		#assert timeout >= 0., 'timeout validation failed'
		if self._tstart is None:
			assert not self._jobs and not self._workers, (
				'Start time should be defined for non-empty execution pool')
			return False

		self.__reviseWorkers()
		while self.alive and (self._jobs or self._workers):
			if timeout and time.perf_counter() - self._tstart > timeout:
				print('WARNING, the execution pool is terminated on timeout', file=sys.stderr)
				self.__terminate()
				return False
			time.sleep(self.latency)
			self.__reviseWorkers()
			# Revise UI command(s) if the WebUI app has been connected
			if self._uicmd is not None:
				self.__reviseUi()
		with self.__termlock:  # , 0.05 50 ms
			self._traceFailures()
		print('The execution pool{} is completed, duration: {} h {} m {:.4f} s'.format(
			'' if self.name is None else ' ' + self.name
			, *secondsToHms(time.perf_counter() - self._tstart))
			, file=sys.stderr if _DEBUG_TRACE else sys.stdout)
		self._tstart = None  # Be ready for the following execution

		assert not self._jobs and not self._workers, 'All jobs should be finished'
		return True


if __name__ == '__main__':
	# Doc tests execution
	import doctest
	#doctest.testmod()  # Detailed tests output
	flags = doctest.REPORT_NDIFF | doctest.REPORT_ONLY_FIRST_FAILURE | doctest.IGNORE_EXCEPTION_DETAIL
	failed, total = doctest.testmod(optionflags=flags)
	if failed:
		print("Doctest FAILED: {} failures out of {} tests".format(failed, total), file=sys.stderr)
	else:
		print('Doctest PASSED')
	# Note: to check specific testcase use:
	# $ python -m unittest mpepool.TestExecPool.test_jobTimeoutChained
	if len(sys.argv) <= 1:
		try:
			import mpetests
			suite = mpetests.unittest.TestLoader().loadTestsFromModule(mpetests)
			if mpetests.mock is not None:
				print('')  # Indent from doctests
				if not mpetests.unittest.TextTestRunner().run(suite).wasSuccessful():  # TextTestRunner(verbosity=2)
				#if unittest.main().result:  # verbosity=2
					print('Try to re-execute the tests (hot run) or set x2-3 larger TEST_LATENCY')
			else:
				print('WARNING, the unit tests are skipped because the mock module is not installed', file=sys.stderr)
		except ImportError as err:
			print('WARNING, Unit tests skipped because of the failed import: ', err, file=sys.stderr)
