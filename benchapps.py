#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: List of the clustering algorithms to be executed by the benchmark and accessory routines.

	Execution function for each algorithm must be named "exec<Algname>" and have the following signature:

	def execAlgorithm(execpool, netfile, asym, odir, timeout, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):
		Execute the algorithm (stub)

		execpool: ExecPool  - execution pool of worker processes
		netfile: str  - the input network to be clustered
		asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
		odir: bool  - whether to output results to the dedicated dir named by the network instance name,
			which is actual for the shuffles with non-flat structure
		timeout: ufloat32  - processing (clustering) timeout of the input file, 0 means infinity
		memlim: ufloat32  - max amount of memory in GB allowed for the algorithm execution, 0 - unlimited
		seed: uint64 or None  - random seed, uint64_t
		task: Task  - owner task
		pathidsuf: str  - network path id prepended with the path separator
		workdir: str  - relative working directory of the app, actual when the app contains libs

		return  njobs: uint  - number of performed executions (started jobs)

:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>,
	ScienceWise <http://sciencewise.info/>
:Date: 2015-07
"""
from __future__ import print_function, division  # Required for stderr output, must be the first import
# Required to efficiently traverse items of dictionaries in both Python 2 and 3
try:
	from future.builtins import range
except ImportError:
	# Replace range() implementation for Python2
	try:
		range = xrange
	except NameError:
		pass  # xrange is not defined in Python3, which is fine
import os
import shutil
import glob
import sys
import inspect  # To automatically fetch algorithm name
import traceback  # Stacktrace
import subprocess

from numbers import Number  # To verify that a variable is a number (int or float)
from sys import executable as PYEXEC  #pylint: disable=C0412;  # Full path to the current Python interpreter
from benchutils import viewitems, delPathSuffix, ItemsStatistic, parseName, dirempty, funcToAppName \
	, tobackup, escapePathWildcards, UTILDIR, ALGSDIR, ORIGDIR, TIMESTAMP_START_HEADER \
	, SEPPARS, SEPSUBTASK, SEPPATHID, ALEVSMAX, ALGLEVS
from benchevals import SEPNAMEPART, RESDIR, CLSDIR, EXTRESCONS, EXTLOG, EXTERR, EXTAGGRES, EXTAGGRESEXT
from utils.mpepool import Job, Task
from algorithms.utils.parser_nsl import parseHeaderNslFile  #, asymnet


# Note: currently the output level are limited only for the algorithms that may produce more than 10 levels
assert ALEVSMAX >= 10, 'The number of levels limitation should be added to GANXiS and some others'
EXTCLSNDS = '.cnl'  # Clusters (Communities) Nodes Lists
# reFirstDigits = re.compile(r'\d+')  # First digit regex
_DEBUG_TRACE = False  # Trace start / stop and other events to stderr


def aggexec(apps):
	"""Aggregate execution statistics

	Aggregate execution results of all input datasets (considering instances and shuffles)
	and output average, and avg, min, max values for each input dataset per each app.

	Expected format of the aggregating files:
	# ExecTime(sec)	CPU_time(sec)	CPU_usr(sec)	CPU_kern(sec)	RSS_RAM_peak(Mb)	TaskName
	0.550262	0.526599	0.513438	0.013161	2.086	syntmix/1K10/1K10^1=k7.1#1
	...

	apps  - apps were executed, whose resource consumption  should be aggregated

	#>>> aggexec(['scp', 'ganxis']) is None
	#True
	"""
	#exectime = {}  # inpname: [app1_stat, app2_stat, ...]
	# ATTENTION: for the correct output memory must be the last one
	mnames = ('exectime', 'cputime', 'rssmem')  # Measures names
	measures = [{}, {}, {}]  # execitem, cputime, rssmem
	mapps = []  # Measured apps
	iapp = 0  # Algorithm index
	for app in apps:
		appesfile = ''.join((RESDIR, app, '/', app, EXTRESCONS))
		try:
			with open(appesfile, 'r') as aest:
				mapps.append(app)
				for ln in aest:
					# Strip leading spaces
					ln = ln.lstrip()
					# Skip comments
					if not ln or ln[0] == '#':
						continue
					# Parse the content
					fields = ln.split(None, 6)
					# Note: empty and spaces strings were already excluded
					# 6 fields in the old format without the rcode
					assert 6 <= len(fields) <= 7, (
						'Invalid format of the resource consumption file "{}": {}'.format(appesfile, ln))
					# Fetch and accumulate measures
					# Note: rstrip() is required, because fields[-1] can ends with '\n';  os.path.split(...)[1]
					dataset = delPathSuffix(fields[-1].rstrip(), True)  # Note: name can't be a path here
					#print('> dataset: >>>{}<<< from >{}<'.format(dataset, fields[5]), file=sys.stderr)
					assert dataset, 'Dataset name must exist'
					etime = float(fields[0])
					ctime = float(fields[1])
					rmem = float(fields[4])
					#rcode = float(fields[5])  # Note: in the old format 5-th field is the last and is the app name
					for imsr, val in enumerate((etime, ctime, rmem)):
						dstats = measures[imsr].setdefault(dataset, [])
						if len(dstats) <= iapp:
							assert len(dstats) == iapp, ('Network statistics are not synced with apps:'
								' iapp={}, dataset: {}, dstats: {}'.format(iapp, dataset, dstats))
							dstats.append(ItemsStatistic('_'.join((app, dataset)), val, val))
						dstats[-1].add(val)
		except IOError:
			print('WARNING, resource consumption results for "{}" do not exist, the aggregation is discarded.'.format(app), file=sys.stderr)
		else:
			iapp += 1
	# Check number of the apps to be outputted
	if not mapps:
		print('WARNING, there are no any resource consumption results to be aggregated.', file=sys.stderr)
		return
	# Output results
	for imsr, measure in enumerate(mnames):
		resfile = ''.join((RESDIR, measure, EXTAGGRES))
		resxfile = ''.join((RESDIR, measure, EXTAGGRESEXT))
		try:
			with open(resfile, 'a') as outres, open(resxfile, 'a') as outresx:
				# The header is unified for multiple outputs only for the outresx
				if not os.fstat(outresx.fileno()).st_size:
					# ExecTime(sec), ExecTime_avg(sec), ExecTime_min	ExecTime_max
					outresx.write('# <dataset>\n#\t<app1_outp>\n#\t<app2_outp>\n#\t...\n')
				# Output timestamp
				# Note: print() unlike .write() outputs also ending '\n'
				print(TIMESTAMP_START_HEADER, file=outres)
				print(TIMESTAMP_START_HEADER, file=outresx)
				# Output header, which might differ for distinct runs by number of apps
				outres.write('# <dataset>')
				for app in mapps:
					outres.write('\t{}'.format(app))
				outres.write('\n')
				# Output results for each dataset
				for dname, dstats in viewitems(measures[imsr]):
					outres.write(dname)
					outresx.write(dname)
					for iapp, stat in enumerate(dstats):
						if not stat.fixed:
							stat.fix()
						# Output sum for time, but avg for mem
						val = stat.sum if imsr < len(mnames) - 1 else stat.avg
						outres.write('\t{:.3f}'.format(val))
						outresx.write('\n\t{}>\ttotal: {:.3f}, per_item: {:.6f} ({:.6f} .. {:.6f})'
							.format(mapps[iapp], val, stat.avg, stat.min, stat.max))
					outres.write('\n')
					outresx.write('\n')
		except IOError as err:
			print('ERROR, "{}" resources consumption output is failed: {}. {}'
				.format(measure, err, traceback.format_exc(5)), file=sys.stderr)


def preparePath(taskpath):  # , netshf=False
	"""Create the path if required, otherwise move existent data to backup.
	All instances and shuffles of each network are handled all together and only once,
	even on calling this function for each shuffle.

	taskpath  - the path to be prepared
	"""
	# netshf  - whether the task is a shuffle processing in the non-flat dir structure
	#
	# Backup existent files & dirs with such base only if this path exists and is not empty
	# ATTENTION: do not use only basePathExists(taskpath) here to avoid movement to the backup
	# processing paths when xxx.mod.net is processed before the xxx.net (has the same base)
	# Create target path if not exists
	# print('> preparePath(), for: {}'.format(taskpath))
	if not os.path.exists(taskpath):
		os.makedirs(taskpath)
	elif not dirempty(taskpath):  # Back up all instances and shuffles once per execution in a single archive
		# print('> preparePath(), backing up: {}, content: {}'.format(taskpath, os.listdir(taskpath)))
		mainpath = delPathSuffix(taskpath)
		tobackup(mainpath, True, move=True)  # Move to the backup (old results can't be reused in the forming results)
		os.mkdir(taskpath)


def prepareResDir(appname, taskname, odir, pathidsuf):
	"""Prepare output directory for the app results and back up the previous results

	appname  - application (algorithm) name
	taskname  - task name
	odir  - whether to output results to the dedicated dir named by the instance name,
		which is typically used for shuffles with the non-flat structure
	pathidsuf: str  - network path id prepended with the path separator

	return resulting directory without the ending '/' terminator
	"""
	# Preapare resulting directory
	taskdir = taskname  # Relative task directory without the ending '/'
	if odir:
		nameparts = parseName(taskname, True)
		taskdir = ''.join((nameparts.basepath, nameparts.insid, '/', taskname))  # Use base name and instance id
	assert not pathidsuf or pathidsuf.startswith(SEPPATHID), 'Ivalid pathidsuf: ' + pathidsuf
	taskpath = ''.join((RESDIR, appname, '/', CLSDIR, taskdir, pathidsuf))

	preparePath(taskpath)
	return taskpath


class PyBin(object):
	"""Automatically identify the most appropriate Python interpreter among the available"""
	#_pybin = PYEXEC
	_pypy3 = None
	_pypy = None
	_python3 = None

	# Initialized existing Python interpreters once
	try:
		with open(os.devnull, 'wb') as fdevnull:
			# Note: More accurate solution is not check "python -V" output, but it fails on Python2 for the
			# 'python -V' (but works for the 'python -h')
			# pyverstr = subprocess.check_output([PYEXEC, '-V']).decode()  # Note: Xcoding is required for Python3
			##pyverstr = subprocess.Popen((PYEXEC, '-V'), stdout=subprocess.PIPE).communicate()[0].decode()
			# pyver = int(reFirstDigits.search(pyverstr).group())  # Take the first digits, i.e. the major version
			# pybin = 'python' if pyver >= 3 else PYEXEC
			#
			# Check for the pypy interpreter/JIT in the system if required
			# ATTENTION: due to some bug 'python -V' does not output results
			# to the specified pipe and .check_output() also fails to deliver results,
			# always outputting to the stdout (which is not desirable in our case);
			# 'python -V' works fine only for the Python3 that is why it is not used here.
			try:
				if not subprocess.call(('pypy3', '-h'), stdout=fdevnull):
					_pypy3 = 'pypy3'
			except OSError:
				pass
			try:
				if not subprocess.call(('pypy', '-h'), stdout=fdevnull):
					_pypy = 'pypy'
			except OSError:
				pass
			try:
				if not subprocess.call(('python3', '-h'), stdout=fdevnull):
					_python3 = 'python3'
			except OSError:
				pass
	except IOError:
		# Note: the required interpreter existence in the system can't be checked here,
		# only 'python' is assumed to be present by default.
		pass

	@staticmethod
	def bestof(pypy, v3):
		"""Select the best suitable Python interpreter

		pypy  - whether to consider PyPy versions, give priority to pypy over the CPython (standard interpreter)
		v3  - whether to consider interpretors of v3.x, give priority to the largest version
		"""
		pybin = PYEXEC
		pyname = os.path.split(pybin)[1]
		if pypy and v3 and PyBin._pypy3:
			if pyname.find('pypy3') == -1:  # Otherwise retain PYEXEC
				pybin = PyBin._pypy3
		elif pypy and PyBin._pypy:
			if pyname.find('pypy') in (-1, pyname.find('pypy3')):  # Otherwise retain PYEXEC
				pybin = PyBin._pypy
		elif v3 and PyBin._python3:
			if pyname.find('python3') == -1:  # Otherwise retain PYEXEC
				pybin = PyBin._python3
		elif pyname.find('python') in (-1, pyname.find('python3')):  # Otherwise retain PYEXEC
			pybin = 'python'

		return pybin


def iround(val, lower):
	"""Round value to lower or upper integer in case of the equally good fit.
	Equas to math.round for lower = False.

	val: float  - the value to be rounded
	lower: bool  - direction of the rounding resolution in case of the equally good fit

	return  v: int  - rounded value

	>>> iround(2.5, True)
	2
	>>> iround(2.5, False)
	3
	>>> iround(2.2, True)
	2
	>>> iround(2.2, False)
	2
	>>> iround(2.7, True)
	3
	>>> iround(2.7, False)
	3
	"""
	q, r = divmod(val, 1)
	res = int(q if lower and r <= 0.5 or not lower and r < 0.5 else q + 1)
	# print('>> val: {:.3f}, q: {:.0f}, r: {:.3f}, res: {:.0f}'.format(val, q, r-0.5, res), file=sys.stderr)
	return res


def reduceLevels(levs, num, root0):
	"""Uniformly fetch required number of levels from the levs giving priority
	to the coarse-grained (top hierarchy levels) in case of the equal fit

	levs: list  - ORDERED levels to be processed, where the list starts from the bottom
		level of the hierarchy having the highest (most fine-grained resolution) and the
		last level in the list is the root level having the most coarse-grained resolution
	num: uint >= 1  - target number of levels to be fetched uniformly
	root0: bool  - whether the root (most coarse-grained) level has zero or maximal index

	return  rlevs: list, tuple  - list of the reduced levels

	>>> list(reduceLevels([1, 2], 1, True))
	[1]
	>>> list(reduceLevels([1, 2], 1, False))
	[2]
	>>> list(reduceLevels([1, 2, 3], 1, True))
	[2]
	>>> list(reduceLevels([1, 2, 3], 1, False))
	[2]
	>>> reduceLevels(range(0, 10), 9, True)
	[0, 1, 2, 3, 4, 6, 7, 8, 9]
	>>> reduceLevels(range(0, 10), 9, False)
	[0, 1, 2, 3, 5, 6, 7, 8, 9]
	>>> reduceLevels(range(0, 10), 8, True)
	[0, 1, 3, 4, 5, 6, 8, 9]
	>>> reduceLevels(range(0, 10), 8, False)
	[0, 1, 3, 4, 5, 6, 8, 9]
	>>> reduceLevels(range(0, 10), 7, True)
	[0, 1, 3, 4, 6, 7, 9]
	>>> reduceLevels(range(0, 10), 7, False)
	[0, 2, 3, 5, 6, 8, 9]
	>>> reduceLevels(range(0, 10), 6, True)
	[0, 2, 4, 5, 7, 9]
	>>> reduceLevels(range(0, 10), 6, False)
	[0, 2, 4, 5, 7, 9]
	>>> reduceLevels(range(0, 10), 5, True)
	[0, 2, 4, 7, 9]
	>>> reduceLevels(range(0, 10), 5, False)
	[0, 2, 5, 7, 9]
	>>> reduceLevels(range(0, 10), 4, True)
	[0, 3, 6, 9]
	>>> reduceLevels(range(0, 10), 4, False)
	[0, 3, 6, 9]
	>>> reduceLevels(range(0, 10), 3, True)
	[0, 4, 9]
	>>> reduceLevels(range(0, 10), 3, False)
	[0, 5, 9]
	>>> list(reduceLevels(range(0, 10), 2, True))
	[0, 9]
	>>> list(reduceLevels(range(0, 10), 2, False))
	[0, 9]
	>>> list(reduceLevels(range(0, 10), 1, True))
	[4]
	>>> list(reduceLevels(range(0, 10), 1, False))
	[5]
	>>> list(reduceLevels(range(0, 9), 1, True))
	[4]
	>>> list(reduceLevels(range(0, 9), 1, False))
	[4]
	"""
	nlevs = len(levs)
	if num >= nlevs:
		return levs
	elif num >= 2:
		# Multiplication ratio >= 1
		# The last source index is nlevs - 1, the number of dest indexes besides the zero is num - 1
		mrt = (nlevs - 1) / float(num - 1)
		# print('> num: {}, lower: {}, mrt: {:.3f}'.format(num, root0, mrt), file=sys.stderr)
		res = []
		i = 0
		while i < num:
			res.append(levs[iround(i * mrt, root0)])
			i += 1
		assert len(res) == num, ('Unexpected number of resulting levels:'
	 		' {} of {}: {}'.format(len(res), num, res))
		return res
	elif num == 1:
		# 1 element tuple
		return (levs[(nlevs - root0) // 2],)  # Note: -1 to give priority to the begin
	elif num <= 0:
		raise ValueError('The required number of levels should be positive: ' + str(num))
	else:
		raise AssertionError('The value of num has not been handled: ' + str(num))


def limlevs(job):
	"""Limit the number of output level to fit ALEVSMAX (unified for all algorithms).

	Limit the number of hierarchy levels in the output by moving the original output
	to the dedicated directory and uniformly linking the required number of levels it
	to the expected output path.

	Job params:
	taskpath: str  - task path, base directory of the resulting clusters output
	fetchLevId: callable  - algorithm-specific callback to fetch level ids
	levfmt (optional): str  - level format WILDCARD (only ? and * are supported
		as in the shell) to fetch levels among other files, for example: 'tp*'.
		Required at least for Oslom.
	"""
	lmax = ALEVSMAX  # Max number of the output levels for the network
	# Check the number of output levels and restructure the output if required saving the original one
	taskpath = job.params['taskpath']
	fetchLevId = job.params['fetchLevId']
	assert os.path.isdir(taskpath) and callable(fetchLevId), (
		'Invalid job parameters:  taskpath: {}, fetchLevId callable: {}'.format(
		taskpath, callable(fetchLevId)))
	# Filter files from other items (accessory dirs)
	levfmt = job.params.get('levfmt')
	if levfmt:
		levnames = [os.path.split(lev)[1] for lev in glob.iglob('/'.join((taskpath, levfmt)))]
	else:
		levnames = os.listdir(taskpath)  # Note: only file names without the path are returned
	# print('> limlevs() called from {}, levnames ({} / {}): {}'.format(
	# 	job.name, len(levnames), lmax, levnames), file=sys.stderr)
	if len(levnames) <= lmax:
		return
	# Move the initial output to the ORIGDIR
	origdir, oname = os.path.split(taskpath)
	if not origdir:
		origdir = '.'
	origdir = '/'.join((origdir, ORIGDIR))
	# Check existence of the destination dir
	newdir = origdir + oname + '/'
	if not os.path.exists(origdir):
		os.mkdir(origdir)
	elif os.path.exists(newdir):
		# Note: this notification is not so significant to be logged to the stderr
		print('WARNING {}.limlevs(), removing the former ORIGDIR clusters: {}'.format(job.name, newdir))
		# New destination of the original task output
		shutil.rmtree(newdir)
	shutil.move(taskpath, origdir)
	# Uniformly link the required number of levels to the expected output dir
	os.mkdir(taskpath)
	levnames.sort(key=fetchLevId)
	# Note: all callers have end indexing of the root level: Louvain, Oslom, Daoc
	levnames = reduceLevels(levnames, lmax, False)
	# print('> Creating symlinks for ', levnames, file=sys.stderr)
	for lev in levnames:
		os.symlink(os.path.relpath(newdir + lev, taskpath), '/'.join((taskpath, lev)))


def subuniflevs(job):
	"""Subtask of the levels output unification.
	Aggregates output levels from the parameterized job and reports them to the
	task to unify results for all parameterized jobs of the algorithm on the
	current network (input dataset).
	Required at least for Scp.

	Job params are propagated to the super-task params
		taskpath: str  - task path, base directory of the resulting clusters output
	"""
	# fetchLevId: callable  - algorithm-specific callback to fetch level ids
	# aparams: str  - algorithm parameters
	task = job.task
	assert task, 'A task should exist in the job: ' + job.name
	if task.params is None:
		task.params = {'subtasks': {job.name: job.params}}
	else:
		sbtasks = task.params.setdefault('subtasks', {})
		sbtasks[job.name] = job.params
	# print('> subuniflevs() from job {}, {} sbtasks'.format(job.name, len(task.params['subtasks'])), file=sys.stderr)


def uniflevs(task):
	"""Unify representation of the output levels.
	Aggregates levels from each parameter in a uniform way limiting their number
	to the required amount.

	At least one level is taken from the levels output corresponding to each parameter.
	The output levels of each parameter should be bound to task, which should pass
	aggregated values to this task on successful completion. Note that some
	subtasks might be failed but this task should perform the final aggregation
	till at least any subtask completed and provided required data.

	Task params:
	params: dict, str
		outpname: str, str  - target output name without the path
		fetchLevId: callable  - algorithm-specific callback to fetch level ids
		subtasks: dict
			<subtask_name>: str, <subtask_params>: dict  - processing outputs of the subtasks
	"""
	# root0: bool  - whether the hierarchy root (the most coarse-grained) level
	# has index 0 or the maximal index
	if not task.params:
		# Note: this is not an error to be reported to the stderr
		print('WARNING, no any output levels are reported for the unification in the super task: ', task.name)
		return
	# print('> uniflevs() of {} started'.format(task.name), file=sys.stderr)
	lmax = ALEVSMAX  # Max number of the output levels for the network
	# Check the number of output levels and restructure the output if required saving the original one
	levsnum = 0  # Total number of the (valid) output levels for all alg. parameters
	bpath = None  # Base path
	pouts = []  # Parameterized outputs of levels to be processed: [(outname, levnames), ...]
	origdir = None
	root0 = True  # Scp enumerates root on the zero level
	fetchLevId = task.params['fetchLevId']  # Callback to fetch level ids
	subtasks = task.params.get('subtasks')
	if subtasks:
		for sbt, tpars in viewitems(subtasks):
			try:
				taskpath = tpars if isinstance(tpars, str) else tpars['taskpath']
				# assert os.path.isdir(taskpath) and callable(fetchLevId), (
				# 	'Invalid job parameters:  taskpath: {}, fetchLevId callable: {}'.format(
				# 	taskpath, callable(fetchLevId)))
				# Define base path
				if bpath is not None:
					outbase, outname = os.path.split(taskpath)
					if outbase != bpath:
						print('ERROR, levels unification called for distinct networks. Omitted for', taskpath, file=sys.stderr)
						continue
				else:
					bpath, outname = os.path.split(taskpath)
				# Move parameterized levels to the orig dir
				if origdir is None:
					origdir = '/'.join((bpath if bpath else '.', ORIGDIR))
					if not os.path.exists(origdir):
						os.mkdir(origdir)
				# newdir = origdir + oname + '/'
				levnames = os.listdir(taskpath)  # Note: only file names without the path are returned
				# Check existence of the dest path, which causes exception in shutil.move()
				dstpath = origdir + os.path.split(taskpath)[1]
				if os.path.exists(dstpath):
					try:
						os.rmdir(dstpath)
					except OSError as err:
						print('WARNING uniflevs(), orig dest dir is dirty. Replaced with the latest version.'
							, err, file=sys.stderr)
						shutil.rmtree(dstpath)
				# # Note: os.listdir would throw OSError if taskpath would not be a dir
				# assert os.path.isdir(taskpath), 'A directory is expected: ' + taskpath
				shutil.move(taskpath, origdir)
				if levnames:
					levsnum += len(levnames)
					# Sort levnames in a way to start from the root (the most coarse-grained) level
					levnames.sort(key=fetchLevId, reverse=not root0)
					pouts.append((outname, levnames))  # Output dir name without the path and corresponding levels
					# print('> pout added: {} {} levs ({} .. {})'.format(outname, len(levnames), levnames[0], levnames[-1]), file=sys.stderr)
			except Exception as err:  #pylint: disable=W0703
				print('ERROR, {} subtask output levels aggregating unification failed'
					', {} params ({}): {}. Discarded. {}'.format(sbt
					, None if tpars is None else len(tpars), type(tpars).__name__
					, err, traceback.format_exc(3)), file=sys.stderr)
	if not pouts:
		print('WARNING uniflevs(), nothing to process because the output levels are empty for the task'
			', which may happen if there are no any completed subtasks/jobs', task.name, file=sys.stderr)
		return
	# Sort pouts by the decreasing number of levels, i.e. from the fine to coarse grained outputs
	pouts.sort(key=lambda outp: len(outp[1]), reverse=True)
	# Create the unifying output dir
	uniout = task.params.get('outpname')
	if not uniout:
		#uniout, _apars, insid, shfid, pathid
		sname = parseName(pouts[0], True)  # Parse name only without the path
		uniout = ''.join((sname.basepath, sname.insid, sname.shfid, sname.pathid))  # , sname.lnkrd;  Note: alg params marker is intentionally omitted
	assert uniout, 'Output directory name should be defined'
	unidir = '/'.join((bpath if bpath else '.', uniout, ''))  # Note: ending '' to have the ending '/'
	if os.path.exists(unidir):
		if not (os.path.isdir(unidir) and dirempty(unidir)):
			tobackup(unidir, False, move=True)  # Move to the backup (old results can't be reused)
			os.mkdir(unidir)
	else:
		os.mkdir(unidir)
	# Take lmax output levels from pnets parameterized outputs proportionally to the number of
	# levels in each output but with at least one output per each network
	# NOTE: Take the most coarce-grained level when only a single level from the parameterized
	# output is taken.
	# Remained number of output clusterings after the reservation of a single level in each output
	# print('> unidir: {}, {} pouts, {} levsnum'.format(unidir, len(pouts), levsnum), file=sys.stderr)
	numouts = len(pouts)
	iroot = 0 if root0 else -1  # Index of the root level
	if numouts < lmax:
		# rlevs = levsnum - numouts
		lmax -= numouts  # Remained limit considering the reserved levels from each output
		levsnum -= numouts  # The number of levels besides the reserved
		for i in range(0, numouts):
			outname, levs = pouts[i]
			# Evaluate current number of the processing levels, take at least one
			# in addition to the already reserved because the number of levels in
			# the begin of pouts is maximal
			levnames = None
			if levsnum:
				numcur = iround(len(levs) * lmax / float(levsnum), False)
				if lmax and not numcur:
					numcur = 1
				if numcur:
					# Take 2+ levels
					levnames = reduceLevels(levs, 1 + numcur, root0)
					lmax -= numcur  # Note: the reserved 1 level was already considered
					# Note: even when lmax becomes zero, the reserved levels should be linked below
			if not levnames:
				# Take only the root level
				levnames = (levs[iroot],)
			# Link the required levels
			for lname in levnames:
				os.symlink(os.path.relpath(''.join((origdir, outname, '/', lname)), unidir)
					, '/'.join((unidir, lname)))
		assert lmax >= 0, 'lmax levels at most should be outputted'
	else:
		# Link a single network from as many subsequent pouts as possible
		for i in range(0, lmax):
			outname, levs = pouts[i]
			os.symlink(os.path.relpath(''.join((origdir, outname, '/', levs[iroot])), unidir)
				, '/'.join((unidir, levs[iroot])))


def fetchLevIdCnl(name):
	"""Fetch level id of the hierarchy/scale from the output Cnl file name.
	The format of the output file name: <outpfile_name>_<lev_num><EXTCLSNDS>

	name: str  - level name

	return  id: uint  - hierarchy/scale level id
	"""
	iid = name.rfind('_')  # Index of the id
	if iid == -1:
		raise ValueError('The file name does not contain lev_num: ' + name)
	iid += 1
	iide = name.rfind('.', iid)  # Extension index
	if iide == -1:
		print('WARNING, Cnl files should be named with the', EXTCLSNDS, 'extension:', name, file=sys.stderr)
		iide = len(name)
	return int(name[iid:iide])


def metainfo(levsmax=ALEVSMAX):
	"""Set some meta information for the executing algorithms

	levsmax: uint16  - expected max number of resolution level files (excluding the aggregated/multires output)
	"""
	def decor(func):
		"""Decorator returning the original function"""
		assert levsmax >= 1 and isinstance(levsmax, int), ('Invalid arguments, levsmax: {}'.format(levsmax))
		# QMSRAFN[funcToAppName(func)] = afnmask
		if levsmax != ALEVSMAX:  # Save only quality measures with non-default affinity
			ALGLEVS[funcToAppName(func.__name__)] = levsmax
		return func
	return decor


# Louvain
## Original Louvain
#def execLouvain(execpool, netfile, asym, odir, timeout=0, memlim=0., pathidsuf='', tasknum=0, task=None):
#	"""Execute Louvain
#	Results are not stable => multiple execution is desirable.
#
#	tasknum  - index of the execution on the same dataset
#	"""
#
#	# Evaluate relative network size considering whether the network is directed (asymmetric)
#	netsize = os.path.getsize(netfile)
#	if not asym:
#		netsize *= 2
#	# Fetch the task name and chose correct network filename
#	netfile = os.path.splitext(netfile)[0]  # Remove the extension
#	taskname = os.path.split(netfile)[1]  # Base name of the network
#	assert taskname, 'The network name should exists'
#	if tasknum:
#		taskname = '-'.join((taskname, str(tasknum)))
#	netfile = '../' + netfile  # Use network in the required format
#
#	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'louvain'
#	# ./community graph.bin -l -1 -w graph.weights > graph.tree
#	args = ('../exectime', ''.join(('-o=../', RESDIR, algname, EXTRESCONS)), ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
#		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
#	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=ALGSDIR, args=args
#		, timeout=timeout, memlim=memlim, stdout=''.join((RESDIR, algname, '/', taskname, '.loc'))
#		, task=task, category=algname, size=netsize, stderr=''.join((RESDIR, algname, '/', taskname, EXTLOG))))
#	return 1
#
#
#def evalLouvain(execpool, basefile, measure, timeout):
#	return


def execLouvainIg(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  # , selfexec=False  - whether to call self recursively
	"""Execute Louvain using the igraph library
	Note: Louvain produces not stable results => multiple executions are desirable.

	Mandatory arguments:
	execpool: ExecPool  - execution pool of worker processes
	netfile: str  - the input network to be clustered
	asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
	odir: bool  - whether to output results to the dedicated dir named by the instance name,
		which is actual for the shuffles with non-flat structure

	Optiononal arguments:
	timeout: ufloat32  - processing (clustering) timeout of the input file, 0 means infinity
	memlim: ufloat32  - max amount of memory in GB allowed for the algorithm execution, 0 - unlimited
	seed: uint64  - random seed, uint64_t
	task: Task  - owner task
	pathidsuf: str  - network path id prepended with the path separator
	workdir: str  - relative working directory of the app, actual when the app contains libs

	returns  - the number of executions or None
	"""
	# Note: .. + 0 >= 0 to be sure that type is arithmetic, otherwise it is always true for the str
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {}'
		.format(execpool, netfile, asym, timeout, memlim))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network; , netext
	assert taskname, 'The network name should exists'
	#if tasknum:
	#	taskname = '_'.join((taskname, str(tasknum)))

	# ATTENTION: for the correct execution algname must be always the same as func name without the prefix "exec"
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'LouvainIg'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	# print('> execLouvainIg(), taskpath exists:', os.path.exists(taskpath))

	# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
	pybin = PyBin.bestof(pypy=False, v3=True)
	# Note: Louvain_igraph creates the output dir if it has not been existed, but not the exectime app
	errfile = taskpath + EXTERR
	logfile = taskpath + EXTLOG

	# def relpath(path, basedir=workdir):
	# 	"""Relative path to the specified basedir"""
	# 	return os.path.relpath(path, basedir)

	# Note: without './' relpath args do not work properly for the binaries located in the current dir
	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	# taskpath = relpath(taskpath)

	# ./louvain_igraph.py -i=../syntnets/1K5.nsa -o=louvain_igoutp/1K5/1K5.cnl -l
	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, pybin, './louvain_igraph.py', '-i' + ('nsa' if asym else 'nse')
		, '-lo', ''.join((relpath(taskpath), '/', taskname, EXTCLSNDS)), netfile)
	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=workdir, args=args, timeout=timeout
		#, stdout=os.devnull
		, ondone=limlevs, params={'taskpath': taskpath, 'fetchLevId': fetchLevIdCnl}
		, task=task, category=algname, size=netsize, memlim=memlim, stdout=logfile, stderr=errfile))

	execnum = 1
	# Note: execution on shuffled network instances is now generalized for all algorithms
	## Run again for all shuffled nets
	#if not selfexec:
	#	selfexec = True
	#	netdir = os.path.split(netfile)[0]
	#	if not netdir:
	#		netdir = .
	#	netdir += '/'
	#	#print('Netdir: ', netdir)
	#	for netfile in glob.iglob(''.join((escapePathWildcards(netdir), escapePathWildcards(taskname), '/*', netext))):
	#		execLouvain_ig(execpool, netfile, asym, odir, timeout, memlim, selfexec)
	#		execnum += 1
	return execnum


def fastConsBase(algname, execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  # , selfexec=False  - whether to call self recursively
	"""Execute Fast Consensus using the networkx and igraph libraries
	Note: Louvain produces not stable results => multiple executions are desirable.

	Mandatory arguments:
	algname: str  - underlying clusterig algorithm
	execpool: ExecPool  - execution pool of worker processes
	netfile: str  - the input network to be clustered
	asym: bool  - whether the input network is asymmetric (directed, specified by arcs)
	odir: bool  - whether to output results to the dedicated dir named by the instance name,
		which is actual for the shuffles with non-flat structure

	Optiononal arguments:
	timeout: ufloat32  - processing (clustering) timeout of the input file, 0 means infinity
	memlim: ufloat32  - max amount of memory in GB allowed for the algorithm execution, 0 - unlimited
	seed: uint64  - random seed, uint64_t
	task: Task  - owner task
	pathidsuf: str  - network path id prepended with the path separator
	workdir: str  - relative working directory of the app, actual when the app contains libs

	returns  - the number of executions or None
	"""
	# Note: .. + 0 >= 0 to be sure that type is arithmetic, otherwise it is always true for the str
	assert algname in ('FcLouv', 'FcLpm', 'FcCnm', 'FcImap') and  execpool and netfile and (
		asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {}'
		.format(execpool, netfile, asym, timeout, memlim))

	# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
	pybin = PyBin.bestof(pypy=False, v3=True)

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Remove the base path and separate extension;  , netext
	assert taskname, 'The network name should exists'

	# ATTENTION: for the correct execution algname must be always the same as func name without the prefix "exec"
	alg = None  # Algorithm name parameter: louvain, lpm, cnm, infomap
	if algname == 'FcCnm':
		alg = 'cnm'
	elif algname == 'FcImap':
		alg = 'infomap'
	elif algname == 'FcLouv':
		alg = 'louvain'
	elif algname == 'FcLpm':
		alg = 'lpm'
	else:
		raise ValueError('Algorithm name mapping is not defined: {} <- {}'.format(alg, algname))
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	# logfile = taskpath + EXTLOG

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	# Run for range of delta
	delta = 0.02  # dmin
	dmax = 0.1
	steps = ALEVSMAX  # The number of steps (similarity thresholds). Use 10 scale levels as in Ganxis.
	if steps >= 2:
		dd = (dmax - delta) / (steps - 1)
		# print('>> steps: {}, da: {:.2f}'.format(steps, da))
	else:
		delta = (delta + dmax) / 2.
		dd = dmax - delta
	while delta <= dmax:
	# for delta in (dmin + (0 if steps <= 1 else (dmax - dmin) / (steps - 1) * i) for i in range(steps)):
		# Note: the number of digits should be at lest one larger that the margin values to not overwrite the file on rounding
		dstr = '{:.3f}'.format(delta)  # Alg params as string
		# Embed params into the task name
		taskparname = delPathSuffix(taskname, True)
		tasksuf = taskname[len(taskparname):]
		taskparname = ''.join((taskparname, SEPPARS, 'a', dstr, tasksuf))  # Current task
		# ./fast_consensus.py -f <inpnet> -p 5 --outp-parts 1 -a louvain -o <outpdir>
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskparname, pathidsuf)), '-s=/etime_' + algname
			, pybin, './fast_consensus.py', '-f', netfile, '-a', alg
			# p: 5-20
			, '-p', '5', '--outp-parts', '1', '-d', dstr, '-w', '1', '-o', taskpath)
		execpool.execute(Job(name=SEPNAMEPART.join((algname, taskparname)), workdir=workdir, args=args, timeout=timeout
			#, ondone=postexec, stdout=os.devnull, stdout=logfile
			, task=task, category=algname, size=netsize, memlim=memlim, stdout=os.devnull, stderr=errfile))
		delta += dd
	return steps
	#
	# # Note: without './' relpath args do not work properly for the binaries located in the current dir
	# relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# # Evaluate relative paths
	# xtimebin = relpath(UTILDIR + 'exectime')
	# xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	# netfile = relpath(netfile)
	#
	# # Create subtask to monitor execution for each clique size
	# taskbasex = delPathSuffix(taskname, True)
	# tasksuf = taskname[len(taskbasex):]
	# aggtname = taskname + pathidsuf
	# task = Task(aggtname if task is None else SEPSUBTASK.join((task.name, tasksuf))
	# 	, task=task, onfinish=uniflevs, params={'outpname': aggtname, 'fetchLevId': fetchLevIdCnl})
	#
	# # Run for range of delta
	# dmin = 0.02
	# dmax = 0.1
	# dnum = 10
	# for delta in (dmin + (dmax - dmin) / (dnum - 1) * i for i in range(dnum)):
	# 	# A single argument is k-clique size
	# 	dstr = str(delta)
	# 	dstrex = 'd{:.2}'.format(delta)
	# 	# Embed params into the task name
	# 	dtaskname = ''.join((taskbasex, SEPPARS, dstrex, tasksuf))
	# 	# Backup prepared the resulting dir and back up the previous results if exist
	# 	taskpath = prepareResDir(algname, dtaskname, odir, pathidsuf)
	# 	errfile = taskpath + EXTERR
	# 	logfile = taskpath + EXTLOG
	# 	# Evaluate relative paths dependent of the alg params
	# 	reltaskpath = relpath(taskpath)
	#
	# 	# scp.py netname k [start_linksnum end_linksnum number_of_evaluations] [weight]
	# 	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', dtaskname, pathidsuf)), '-s=/etime_' + algname
	# 		# p: 5-20
	# 		, pybin, './fast_consensus.py', '-f', netfile, '-a', alg, '-p', '5', '-d', dstr, '-w', '1', '-o', reltaskpath)
	#
	# 	#print('> Starting job {} with args: {}'.format('_'.join((ktaskname, algname, kstrex)), args + [kstr]))
	# 	execpool.execute(Job(name=SEPNAMEPART.join((algname, dtaskname)), workdir=workdir, args=args, timeout=timeout
	# 		# , ondone=tidy, params=taskpath  # Do not delete dirs with empty results to explicitly see what networks are clustered having empty results
	# 		# Note: increasing clique size k causes ~(k ** pratio) increased consumption of both memory and time (up to k ^ 2),
	# 		# so it is better to use the same category with boosted size for the much more efficient filtering comparing to the distinct categories
	# 		, task=task, category='_'.join((algname, dstrex))
	# 		, size=netsize, ondone=subuniflevs, params=taskpath # {'taskpath': taskpath} # , 'aparams': kstrex
	# 		#, memlim=64  # Limit max memory consumption to 64 GB
	# 		, memlim=memlim, stdout=logfile, stderr=errfile))
	#
	# return dnum


# # Extremely slow
# def execFcCnm(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  # , selfexec=False  - whether to call self recursively
# 	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'FcImap'
# 	return fastConsBase(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir)


# Even more slower
def execFcImap(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  # , selfexec=False  - whether to call self recursively
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'FcImap'
	return fastConsBase(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir)


# Not too fast
def execFcLouv(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  # , selfexec=False  - whether to call self recursively
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'FcLouv'
	return fastConsBase(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir)


# Slower
def execFcLpm(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  # , selfexec=False  - whether to call self recursively
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'FcLpm'
	return fastConsBase(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir)


# SCP (Sequential algorithm for fast clique percolation)
# Note: it is desirable to have a dedicated task for each type of networks or even for each network for this algorithm
def execScp(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  #pylint: disable=W0613
	"""SCP algorithm

	return uint: the number of scheduled jobs
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and memlim + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {}'
		.format(execpool, netfile, asym, timeout, memlim))

	# Fetch the task name (includes networks instance and shuffle if any)
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network; , netext
	assert taskname, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'scp'

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	with open(netfile) as finp:
		netinfo = parseHeaderNslFile(finp, asym)
		asym = netinfo.directed
		if not netinfo.lnsnum:
			# Use network size if the number of links is not available
			size = os.fstat(finp.fileno()).st_size * (1 + (not asym))  # Multiply by 2 for the symmetric (undirected) network
			avgnls = None
		else:
			# The number of arcs in the network
			# ATTENTION: / 2. is important since the resulting value affects avgnls, which affects the k powering
			size = netinfo.lnsnum * (1 + (not netinfo.directed)) / 2.  # arcs = edges * 2
			avgnls = size / float(netinfo.ndsnum)  # Average number of arcs per node
			# size *= avgnls  # To partially consider complexity increase with the density

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)

	# Set the best possible interpreter, run under pypy if possible
	# ATTENTION: Scp doesn't work correctly under Python 3
	pybin = PyBin.bestof(pypy=True, v3=False)
	if _DEBUG_TRACE:
		print('  Selected Python interpreter:  {}', pybin)

	# def tidy(job):
	# 	# The network might lack large cliques, so for some parameters the resulting
	# 	# directories might be empty and should be cleared
	# 	if os.path.isdir(job.params) and dirempty(job.params):
	# 		os.rmdir(job.params)

	# Create subtask to monitor execution for each clique size
	taskbasex = delPathSuffix(taskname, True)
	tasksuf = taskname[len(taskbasex):]
	aggtname = taskname + pathidsuf
	task = Task(aggtname if task is None else SEPSUBTASK.join((task.name, tasksuf))
		, task=task, onfinish=uniflevs, params={'outpname': aggtname, 'fetchLevId': fetchLevIdCnl})
	kmin = 3  # Min clique size to be used for the communities identification
	kmax = 7  # Max clique size (~ min node degree to be considered)
	steps = str(ALEVSMAX)  # Use 10 scale levels as in Ganxis
	# Power ratio to consider non-linear memory complexity increase depending on k
	pratio = (1 + 5 ** 0.5) * 0.5  # Golden section const: 1.618  # 2.718  # exp(1)
	# Run for range of clique sizes
	for k in range(kmin, kmax + 1):
		# A single argument is k-clique size
		kstr = str(k)
		kstrex = 'k' + kstr
		# Embed params into the task name
		ktaskname = ''.join((taskbasex, SEPPARS, kstrex, tasksuf))
		# Backup prepared the resulting dir and back up the previous results if exist
		taskpath = prepareResDir(algname, ktaskname, odir, pathidsuf)
		errfile = taskpath + EXTERR
		logfile = taskpath + EXTLOG
		# Evaluate relative paths dependent of the alg params
		reltaskpath = relpath(taskpath)

		# scp.py netname k [start_linksnum end_linksnum number_of_evaluations] [weight]
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', ktaskname, pathidsuf)), '-s=/etime_' + algname
			, pybin, './scp.py', netfile, kstr, steps, ''.join((reltaskpath, '/', ktaskname, EXTCLSNDS)))

		#print('> Starting job {} with args: {}'.format('_'.join((ktaskname, algname, kstrex)), args + [kstr]))
		execpool.execute(Job(name=SEPNAMEPART.join((algname, ktaskname)), workdir=workdir, args=args, timeout=timeout
			# , ondone=tidy, params=taskpath  # Do not delete dirs with empty results to explicitly see what networks are clustered having empty results
			# Note: increasing clique size k causes ~(k ** pratio) increased consumption of both memory and time (up to k ^ 2),
			# so it is better to use the same category with boosted size for the much more efficient filtering comparing to the distinct categories
			, task=task, category=algname if avgnls is not None else '_'.join((algname, kstrex))
			, size=size * (k ** pratio if avgnls is None or k <= avgnls else ((k + avgnls)/2.) ** (1./pratio))
			, ondone=subuniflevs, params=taskpath # {'taskpath': taskpath} # , 'aparams': kstrex
			#, memlim=64  # Limit max memory consumption to 64 GB
			, memlim=memlim, stdout=logfile, stderr=errfile))

	return kmax + 1 - kmin


def execRandcommuns(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR, instances=5):  # _netshuffles + 1
	"""Execute Randcommuns, Random Disjoint Clustering
	Results are not stable => multiple execution is desirable.

	Note: the ground-thruth should have the same file name as netfile and '.cnl' extension

	instances  - the number of clustering instances to be produced
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {},\n\tseed: {}'
		.format(execpool, netfile, asym, timeout, memlim, seed))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	taskname = os.path.split(netfile)[1]  # Base name of the network
	assert taskname, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'randcommuns'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	logfile = taskpath + EXTLOG

	# Form name of the ground-truth file on base of the input network filename with the extension relpaced to '.cnl'
	# Note: take base name if the instance of shuffle id components are present
	originpbase = delPathSuffix(netfile)  # Note: netext is already split
	if odir or not os.path.exists(originpbase + EXTCLSNDS):
		# Take file with the target name but in the upper dir
		dirbase, namebase = os.path.split(originpbase)
		dirbase = os.path.split(dirbase)[0]
		if not dirbase:
			dirbase = '..'
		originpbase = '/'.join((dirbase, namebase))
	gtfile = originpbase + EXTCLSNDS
	assert os.path.exists(gtfile), 'Ground-truth file should exist to apply randcommuns: ' + gtfile
	# print('> Starting Randcommuns; odir: {}, asym: {}, netfile: {}, gtfile (exists: {}): {}'
	# 	.format(odir, asym, netfile, os.path.exists(gtfile), gtfile))

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)
	gtfile = relpath(gtfile)
	# Set the best possible interpreter
	# Note: randcommuns loads input network using external igraph-python lib, which interacts
	# slower with PyPy than with CPython but the execution on large networks is slow on CPython.
	# Anyway, randcommuns requires igraph-python which is not present in pypy out of the box
	pybin = PyBin.bestof(pypy=False, v3=True)

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, pybin, './randcommuns.py', '-g=' + gtfile, ''.join(('-i=', netfile, netext)), '-o=' + taskpath
		, '-n=' + str(instances)]
	if seed is not None:
		args.append('-r=' + str(seed))
	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, task=task, category=algname, size=netsize, memlim=memlim, stdout=logfile, stderr=errfile))

	return 1

# Daoc should be executed for:
# - gamma = 1 and automatic gamma:  -g={-1, 1}
# - with/out the [default=medium] input links reduction:  -r
# - with/out the representative clusters output (default: sa). Consider levels output: -cxl[:/0.8]s

# DAOC Options
class DaocOpts(object):
	"""DAOC execution options"""
	__slots__ = ('gamma', 'rgamma', 'reduction', 'gband', 'exclude', 'rlevout', 'significance', 'densdrop', 'clszmin')  # , 'srweight', 'ndsmin'

	def __init__(self, gamma=-1, rgamma='', reduction=None, gband=None, exclude=None, rlevout=0.8, significance='sd', densdrop=None, clszmin=None):  # , srweight=0.85, ndsmin=3
		"""DAOC execution options initialization

		gamma: float  - resolution parameter, float:
			> 0 - static manual gamma for all clusters (1 is the default manual value for the standard modularity)
			-1  - dynamic automatic identification for each cluster
		rgamma: str  - gammaa ratio value or range for the non-linear gamma variation on hierarchy building
		reduction: str  - items links reduction policy on clustering, [w][X] or None (disabled),'
		' where w means use links weights instead of the optimization function, X:
			a  - ACCURATE
			m  - MEAN (recommended)
			s  - SEVERE
			'' - default reduction policy (-m)
		gband: str  - band of the mutual maximal gain for the imprecise fast clustering, default: None (disabled)
			r<float>  - ratio of the maximal modularity gain, recommended: [0.001 .. ] 0.005
			n<float>  - normalized value by the total weight of the network, recommended: 0.05
			''  - default* gband value: r0.005
		exclude: str  - exclude application of the features:
			a  - aagregating hashing being used for the fast matching of the fully mutual mcands
				(extremely profitable to apply it in semantic networks or converted attributed graphs)
		rlevout: float  - ratio (at least) of output levels shrinking starting from the widest (bottom) level,
			applied only for the multi-level output, (0, 1]. Recommended (if used): 0.75 .. 0.9.
		significance: str  - significant clusters output policy:
			sd  - single (one any of) direct owner (default, good recall, fastest)
			ad  - all direct owners
			sh  - single (one any of) direct upper hierarchy of owners (senseless being too mild)
			ah  - all upper hierarchy of owners (maximizes precision)
			''  - default policy for the significant clusters:
				sd with default* srweight[=0.618 or 0.85] and minclsize[=3]
		densdrop: bool  - apply bottom bounded linear density drop (b0.5)
		clszmin: str  - min cluster size in nodes: {<nodes_min>,pg,r2,r3,l2}

		NOTE (*): default values of the parameters might vary in each particular version of the libdaoc
		"""
		# srweight  - weight step ratio for the significant clusters output to avoid output of the large clusters
		# 	that differ only a bit in weight, multiplier, (0, 1]. Recommended: 0.75 .. 0.9.
		# ndsmin  - min number of nodes in the non-root cluster to be eligible for the output.
		# 	NOTE: all nodes are guaranted to be outputted, so there is
		# 	no sence to apply this option for the per-level output

		# Note the significance potentially can be more precise: 'ad%0.86/0.14~'
		assert (isinstance(gamma, Number) and (reduction is None or reduction == ''
				or (1 <= len(reduction) <= 2 and reduction[-1] in 'ams' and (len(reduction) == 1 or reduction[0] == 'w')))
			and isinstance(rgamma, str)
			and (gband is None or gband == '' or (isinstance(gband, str) and len(gband) >= 3 and gband[0] in 'rn'))
			and (exclude is None or exclude == 'a')
			and (rlevout is None or rlevout > 0) and (significance is None or significance in ('', 'sd', 'ad', 'sh', 'ah'))
			and (densdrop is None or isinstance(densdrop, bool))
			and (clszmin is None or (isinstance(clszmin, str) and clszmin in ('pg','r2','r3','l2') or float(clszmin) > 0))
			# and (srweight is None or 0 < srweight <= 1) and (ndsmin is None or ndsmin >= 0)
			), ('Invalid input parameters:\n\tgamma: {}\n\trgamma:{}\n\treduction: {}\n\tgband: {}\n\texclude: {}'
			',\n\trlevout: {}\n\tsignificance: {}\n\tdensdrop: {}\n\tclszmin: {}' #,\n\tsrweight: {},\n\tndsmin: {}'
			.format(gamma, rgamma, reduction, gband, exclude, rlevout, significance, densdrop, clszmin))  # , srweight, ndsmin
		self.gamma = gamma
		self.rgamma = rgamma
		self.reduction = reduction
		self.gband = gband
		self.exclude = exclude
		self.rlevout = rlevout
		self.significance = significance
		self.densdrop = densdrop
		self.clszmin = clszmin
		# self.srweight = srweight
		# self.ndsmin = ndsmin


	def __str__(self):
		"""String conversion"""
		# return ', '.join(': '.join((name, str(val))) for name, val in viewitems(self.__dict__))
		return ', '.join(': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__)


# DAOC wit parameterized gamma
def daocGamma(algname, execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts()):  #pylint: disable=W0613
	"""Execute DAOC, Deterministic (including input order independent) Agglomerative Overlapping Clustering
	using standard modularity as optimization function.
	The output levels are enumerated starting from the bottom of the hierarchy having index 0
	(corresponds to the most fine-grained level with the most number of clusters of the smallest size)
	up to the top (root) level having the maximal index (corresponds to the most coarse-grained level,
	typically having small number of large clusters).

	algname  - name of the executing algorithm to be traced
	...
	rlevout  - ratio (at least) of output levels shrinking starting from the widest (bottom) level, (0, 1]
	gamma  - resolution parameter gamma, <0 means automatic identification of the optimal dymamic value, number (float or int)
	"""
	# Verify that gamma is a numeric value (int or float)
	assert isinstance(algname, str) and algname and execpool and netfile and (asym is None or isinstance(asym, bool)
		) and memlim + 0 >= 0 and timeout + 0 >= 0 and (task is None or isinstance(task, Task)) and isinstance(opts, DaocOpts), (
		'Invalid input parameters:\n\talgname: {},\n\texecpool: {},\n\tnet: {}'
		',\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {},\n\topts: {}'.format(algname, execpool, netfile, asym, timeout, memlim, opts))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Remove the base path and separate extension; , netext
	assert taskname, 'The network name should exists'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)  # Base name of the resulting clusters output
	errfile = taskpath + EXTERR  # Errors log + lib tracing including modularity value and clustering summary
	logfile = taskpath + EXTLOG   # Tracing to stdout, contains timings

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	reltaskpath = relpath(taskpath)

	# ./daoc -w -g=1 -te -cxl[:/0.8]s=../../results/Daoc/karate.cnl ../../realnets/karate.nse.txt
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
		, './daoc', '-t'  # Trace timing
		, ''.join(('-g', opts.rgamma, '=', str(opts.gamma)))  # Resolution parameter = 1 (standard modularity)
		, '-n' + ('a' if asym else 'e'), '-bpu']  # Accomplish with the root level shrinking maximizing non-negative global gain
	if opts.reduction is not None:
		args.append('-r' + opts.reduction)
	if opts.gband is not None:
		args.append('-d' + (opts.gband if opts.gband == '' else '='.join((opts.gband[0], opts.gband[1:]))))
	if opts.exclude is not None:
		args.append('-x' + opts.exclude)

	# Clusters output options
	# Output only max shares, per-level clusters output with step 0.8 in the simple format
	# (with the header but without the share value)
	# Note: there is no sense to apply ndsmin for the per-level output since all nodes are guaranteed to be output
	if opts.rlevout is not None:
		args.append(''.join(('-cx', str(opts.rlevout).join(('l[:/', ']')), 's=', reltaskpath, EXTCLSNDS)))
	if opts.significance is not None:
		ddrop = ''
		if opts.densdrop:
			ddrop = opts.significance + '%be/g' + ('' if opts.clszmin is None else '_' + opts.clszmin)
		# Output with the default significance policy
		args.append(''.join(('-c', 'S', ddrop, 's=', reltaskpath, EXTCLSNDS)))
		# NOTE: output with the specific significance policy is commented as redundant
		# # The significant clusters considering srweight are outputted into the dedicated file
		# if opts.srweight is not None:
		# 	srwstr = str(opts.srweight)
		# 	ndsminstr = str(opts.ndsmin)
		# 	args.append(''.join(('-cx', 's', opts.significance, '/', srwstr, '_', ndsminstr, 's='
		# 		, reltaskpath, '-', srwstr, '-', ndsminstr, EXTCLSNDS)))
	args.append(netfile)

	# print(algname, 'called with args:', str(args), '\n\ttaskpath:', taskpath)
	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, ondone=limlevs, params={'taskpath': taskpath, 'fetchLevId': fetchLevIdCnl}
		, task=task, category=algname, size=netsize, memlim=memlim, stdout=logfile, stderr=errfile))
	return 1


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaoc(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1)):
	"""DAOC with static gamma=1"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)

# DAOC (using standard modularity as an optimization function, non-generalized, with variable gamma on the fixed ratio)
def execDaocRf(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, rgamma='r')):
	"""DAOC with static gamma=1"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)

# DAOC (using standard modularity as an optimization function, non-generalized, with variable gamma on the fixed ratio and bounded size of clusters)
def execDaocRfD_r3(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, rgamma='r', densdrop=True, clszmin='r3')):
	"""DAOC with static gamma=1"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)

# DAOC (using standard modularity as an optimization function, non-generalized, with variable gamma on the variable ratio)
def execDaocRv(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, rgamma='r:')):
	"""DAOC with static gamma=1"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)

# DAOC (using standard modularity as an optimization function, non-generalized, with variable gamma on the ariable ratio and bounded size of clusters)
def execDaocRvD_r3(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, rgamma='r:', densdrop=True, clszmin='r3')):
	"""DAOC with static gamma=1"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)

# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocD(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, densdrop=True)):
	"""DAOC with static gamma=1 and bottom bounded density drop output of significant/salient clusters"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocB(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, gband='r0.005')):
	"""DAOC with the static gamma=1 and a band for the mutual maximal gain taken as a ratio of MMG"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocB1(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, gband='r0.01')):
	"""DAOC with the static gamma=1 and a band for the mutual maximal gain taken as 1% of MMG"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocB5(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, gband='r0.05')):
	"""DAOC with the static gamma=1 and a band for the mutual maximal gain taken as 1% of MMG"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocB10(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, gband='r0.05')):
	"""DAOC with the static gamma=1 and a band for the mutual maximal gain taken as 1% of MMG"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocR(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, reduction='m')):
	"""DAOC with the static gamma=1 and a medium reduction policy of the insignificant links"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocRw(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, reduction='wm')):
	"""DAOC with the static gamma=1 and a medium reduction policy of the insignificant links"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocX(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, exclude='a')):
	"""DAOC with the static gamma=1 and exclusion of the aggregating hashing being
	used for the fast match of the fully mutual mcands"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
# Note: Expected to be the fastest among DAOC versions
def execDaocRB1(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, reduction='m', gband='r0.01')):
	"""DAOC with the static gamma=1, medium reduction policy and a band for the
	mutual maximal gain taken as 1% of MMG"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
# Note: Expected to be the fastest among DAOC versions
def execDaocRB5(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, reduction='m', gband='r0.05')):
	"""DAOC with the static gamma=1, medium reduction policy and a band for the
	mutual maximal gain taken as 1% of MMG"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using standard modularity as an optimization function, non-generalized)
def execDaocRB1X(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=1, reduction='m', gband='r0.01', exclude='a')):
	"""DAOC with the static gamma=1, a medium reduction policy, an MMG band
	and exclusion of the aggregting hashing application"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using automatic adjusting of the resolution parameter, generalized modularity)
def execDaocA(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=-1)):
	"""DAOC with an automatic dynamic gamma"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'DaocA'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# DAOC (using automatic adjusting of the resolution parameter, generalized modularity)
def execDaocAR(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf=''
, workdir=ALGSDIR+'daoc/', opts=DaocOpts(gamma=-1, reduction='m')):  # Note: '' values mean use default
	"""DAOC with an automatic dynamic gamma, a medium reduction policy and an MMG band"""
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'DaocAR'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, opts)


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR+'ganxis/'):
	"""GANXiS/SLPA algorithm"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {},\n\tseed: {}'
		.format(execpool, netfile, asym, timeout, memlim, seed))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Remove the base path and separate extension; , netext
	assert taskname, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Ganxis'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	logfile = taskpath + EXTLOG

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	def tidy(job):  #pylint: disable=W0613
		"""Tidy the temporary output dirs"""
		# Note: GANXiS leaves empty ./output dir in the ALGSDIR, which should be deleted
		tmp = workdir + 'output/'
		if os.path.exists(tmp):
			#os.rmdir(tmp)
			shutil.rmtree(tmp)

	# java -jar GANXiSw.jar -Sym 1 -seed 12345 -i ../../realnets/karate.txt -d ../../results/ganxis/karate
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
		, 'java', '-jar', './GANXiSw.jar', '-i', netfile, '-d', taskpath]
	if not asym:
		args.extend(['-Sym', '1'])
	if seed is not None:
		args.extend(['-seed', str(seed)])
	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, task=task, category=algname, size=netsize, ondone=tidy, memlim=memlim, stdout=logfile, stderr=errfile))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):
	"""OSLOM v2 algorithm
	The output levels are enumerated from the most fine-grained (tp) having max number of clusters
	of the smallest size up to the most coarse-grained (tpN with N haing the maximal index)
	having min number of clusters, where each cluster has the largest size.
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {},\n\tseed: {}'
		.format(execpool, netfile, asym, timeout, memlim, seed))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	netbasepath, taskname = os.path.split(netfile)  # Extract base path and file name
	if not netbasepath:
		netbasepath = '.'  # Note: '/' is added later
	taskname, netext = os.path.splitext(taskname)  # Separate file name and extension
	assert taskname, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Oslom2'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	logfile = taskpath + EXTLOG

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)

	def fetchLevId(levname):
		"""Fetch level id of the hierarchy from the output file name.
		The format of the output file name: tp[<num:uint+>]
		"""
		return 0 if levname == 'tp' else int(levname[2:])

	# Move final results to the required dir on post-processing and clear up
	def postexec(job):  #pylint: disable=W0613
		"""Refine the output"""
		# Move communities output from the original location to the target one
		origResDir = ''.join((netbasepath, '/', taskname, netext, '_oslo_files/'))
		for fname in glob.iglob(escapePathWildcards(origResDir) +'tp*'):
			shutil.move(fname, taskpath)

		# Move the remained files as an extra task output
		outpdire = taskpath + '/extra/'
		if os.path.exists(outpdire):
			# If dest dir already exists, remove it to avoid exception on rename
			shutil.rmtree(outpdire)
		shutil.move(origResDir, outpdire)

		# Note: oslom2 leaves ./tp, which should be deleted
		fname = workdir + 'tp'
		if os.path.exists(fname):
			os.remove(fname)

		# Limit the number of output levels
		limlevs(job)

	# ./oslom_[un]dir -f ../../realnets/karate.txt -w -seed 12345
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
		, './oslom_' +  ('dir' if asym else 'undir'), '-f', netfile, '-w']
	if seed is not None:
		args.extend(['-seed', str(seed)])
	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, params={'taskpath': taskpath, 'fetchLevId': fetchLevId, 'levfmt': 'tp*'}
		, task=task, category=algname, size=netsize, ondone=postexec, memlim=memlim, stdout=logfile, stderr=errfile))
	return 1


# pSCAN (Fast and Exact Structural Graph Clustering)
def execPscan(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  #pylint: disable=W0613
	"""pScan algorithm

	return uint: the number of scheduled jobs
	"""
	# Note: the original implementation does not specify the default parameter values
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {}'
		.format(execpool, netfile, asym, timeout, memlim))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network;  , netext
	assert taskname, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Pscan'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	# logfile = taskpath + EXTLOG

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	eps = 0.05  # Min epsilon (similarity threshold)
	epsMax = 0.9  # Max epsilon (similarity threshold)
	steps = ALEVSMAX  # The number of steps (similarity thresholds). Use 10 scale levels as in Ganxis.
	# Run for range of eps
	# Epsilon delta for each step; -1 is used because of the inclusive range
	if steps >= 2:
		deps = (epsMax - eps) / (steps - 1)
	else:
		eps = (eps + epsMax) / 2.
		deps = epsMax - eps
	while eps <= epsMax:
		# Note: the number of digits should be at lest one larger that the margin values to not overwrite the file on rounding
		#prm = '{:3g}'.format(eps)  # Alg params (eps) as string
		prm = '{:.3f}'.format(eps)  # Alg params (eps) as string
		# prmex = 'e' + prm
		# Embed params into the task name
		taskbasex = delPathSuffix(taskname, True)
		tasksuf = taskname[len(taskbasex):]
		ctaskname = ''.join((taskbasex, SEPPARS, 'e', prm, tasksuf))  # Current task

		# ATTENTION: a single argument is k-clique size, specified later
		# ./pscan -e 0.7 -o graph-e7.cnl -f NSE graph.nse
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', ctaskname, pathidsuf)), '-s=/etime_' + algname
			, './pscan', '-e', prm, '-o', ''.join((taskpath, '/', ctaskname, EXTCLSNDS))
			, '-f', 'NSA' if asym else 'NSE', netfile)

		#print('> Starting job {} with args: {}'.format('_'.join((ctaskname, algname, prmex)), args + [prm]))
		execpool.execute(Job(name=SEPNAMEPART.join((algname, ctaskname)), workdir=workdir, args=args, timeout=timeout
			# , ondone=tidy, params=taskpath  # Do not delete dirs with empty results to explicitly see what networks are clustered having empty results
			#, stdout=logfile  # Skip standard log, because there are too many files, which does not contain useful information
			# Note: eps has not monotonous impact mainly on the execution time, not large impact and the clustering is fast anyway
			 #, category='_'.join((algname, prmex))
			, task=task, category=algname, size=netsize, memlim=memlim, stdout=os.devnull, stderr=errfile))
		eps += deps
	return steps


# rgmc algorithms family: 1: RG, 2: CGGC_RG, 3: CGGCi_RG
def rgmcAlg(algname, execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR, alg=None):
	"""Rgmc algorithms family

	algname  - name of the executing algorithm to be traced
	...
	alg  - the algorithm to be executed:  1: RG, 2: CGGC_RG, 3: CGGCi_RG
	"""
	# Note: the influential parameter is --finalk but it takes an absolute value,
	# which depends on the network size making the algorithm hardly parameterizable,
	# so only the default values used
	algs = ('RG', 'CGGC_RG', 'CGGCi_RG')
	assert isinstance(algname, str) and algname and execpool and netfile and (asym is None or isinstance(asym, bool)
		) and memlim + 0 >= 0 and timeout + 0 >= 0 and (task is None or isinstance(task, Task)
		) and (seed is None or isinstance(seed, int)) and alg in (1, 2, 3), (
		'Invalid input parameters:\n\talgname: {},\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {},\n\talg: {}'
		.format(algname, execpool, netfile, asym, timeout, memlim, algs[alg]))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Remove the base path and separate extension;  , netext
	assert taskname, 'The network name should exists'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	logfile = taskpath + EXTLOG

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	# ./rgmc -a 2 -c tests/rgmc_2/email.nse.cnl -i e networks/email.nse.txt
	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskname, pathidsuf)), '-s=/etime_' + algname
		, './rgmc', '-a', str(alg), '-c', ''.join((taskpath, '/', taskname, EXTCLSNDS))
		, '-i', 'a' if asym else 'e', netfile)
	execpool.execute(Job(name=SEPNAMEPART.join((algname, taskname)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, task=task, category=algname, size=netsize, memlim=memlim, stdout=logfile, stderr=errfile))
	return 1


# CGGC_RG (rgmc -a 2)
@metainfo(levsmax=1)  # Note: rgmcAlg parameters are not easily adjustable, see the executor
def execCggcRg(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  #pylint: disable=C0111
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'CggcRg'
	return rgmcAlg(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, alg=2)


# CGGCi_RG (rgmc -a 3)
@metainfo(levsmax=1)  # Note: rgmcAlg parameters are not easily adjustable, see the executor
def execCggciRg(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):  #pylint: disable=C0111
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'CggciRg'
	return rgmcAlg(algname, execpool, netfile, asym, odir, timeout, memlim, seed, task, pathidsuf, workdir, alg=3)


# SCD
def execScd(execpool, netfile, asym, odir, timeout=0, memlim=0., seed=None, task=None, pathidsuf='', workdir=ALGSDIR):
	"""Scalable Community Detection (SCD)
	Note: SCD os applicable only for the undirected unweighted networks, it skips the weight
	in the weighted network.
	"""
	# Note: -a parameter controls cohesion of the communities, E (0, 1] and can be thought
	# as a resolution (scale) parameter, but is not presented in the documentation.
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		memlim + 0 >= 0 and task is None or isinstance(task, Task)) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tmemlim: {}'
		.format(execpool, netfile, asym, timeout, memlim))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	taskname = os.path.splitext(os.path.split(netfile)[1])[0]  # Remove the base path and separate extension;  , netext
	assert taskname, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'scd'
	# Backup prepared the resulting dir and back up the previous results if exist
	taskpath = prepareResDir(algname, taskname, odir, pathidsuf)
	errfile = taskpath + EXTERR
	# logfile = taskpath + EXTLOG

	relpath = lambda path: './' + os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(UTILDIR + 'exectime')
	xtimeres = relpath(''.join((RESDIR, algname, '/', algname, EXTRESCONS)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	alfa = 0.25  # Min value of "alfa"
	amax = 1.  # Max value of "alfa", default
	steps = ALEVSMAX  # The number of steps (similarity thresholds). Use 10 scale levels as in Ganxis.
	if steps >= 2:
		da = (amax - alfa) / (steps - 1)
		# print('>> steps: {}, da: {:.2f}'.format(steps, da))
	else:
		alfa = (alfa + amax) / 2.
		da = amax - alfa
	while alfa <= amax:
		# Note: the number of digits should be at lest one larger that the margin values to not overwrite the file on rounding
		astr = '{:.3f}'.format(alfa)  # Alg params (alpha) as string
		# Embed params into the task name
		taskparname = delPathSuffix(taskname, True)
		tasksuf = taskname[len(taskparname):]
		taskparname = ''.join((taskparname, SEPPARS, 'a', astr, tasksuf))  # Current task
		# ./scd -n 1 [-a 1] -o tests/scd/karate.nse.cnl -f networks/karate.nse.txt
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', taskparname, pathidsuf)), '-s=/etime_' + algname
			, './scd', '-n', '1' # Use a single threaded implementation
			, '-a', astr
			, '-o', ''.join((taskpath, '/', taskparname, EXTCLSNDS)), '-f', netfile)
		execpool.execute(Job(name=SEPNAMEPART.join((algname, taskparname)), workdir=workdir, args=args, timeout=timeout
			#, ondone=postexec, stdout=os.devnull, stdout=logfile
			, task=task, category=algname, size=netsize, memlim=memlim, stdout=os.devnull, stderr=errfile))
		alfa += da
	return steps


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
