#!/usr/bin/env python2
# -*- coding: utf-8 -*-

"""
:Description: List of the clustering algorithms to be executed by the benchmark and accessory routines.

	Execution function for each algorithm must be named "exec<Algname>" and have the following signature:

	def execAlgorithm(execpool, netfile, asym, odir, timeout, pathid='', selfexec=False):
		Execute the algorithm (stub)

		execpool  - execution pool to perform execution of current task
		netfile  -  input network to be processed
		asym  - network links weights are asymmetric (in/outbound weights can be different)
		timeout  - execution timeout for this task
		pathid  - path id of the net to distinguish nets with the same name located in different dirs.
			Note: pathid is prepended with the separator symbol
		selfexec  - current execution is the external or internal self call

		return  - number of executions (jobs) made

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
# import re

from multiprocessing import Lock  # For the TaskTracer
from numbers import Number  # To verify that a variable is a number (int or float)
from sys import executable as PYEXEC  # Full path to the current Python interpreter
from benchutils import viewitems, delPathSuffix, ItemsStatistic, parseName, dirempty, \
 tobackup, escapePathWildcards, _SEPPARS, _UTILDIR, _TIMESTAMP_START_HEADER
from benchevals import _SEPNAMEPART, _RESDIR, _CLSDIR, _EXTEXECTIME, _EXTAGGRES, _EXTAGGRESEXT
from utils.mpepool import Job
from algorithms.utils.parser_nsl import parseHeaderNslFile, asymnet


_ALGSDIR = 'algorithms/'  # Default directory of the benchmarking algorithms
_EXTLOG = '.log'  # Extension for the logs
_EXTELOG = '.elog'  # Extension for the unbuffered (typically error) logs
_EXTCLNODES = '.cnl'  # Clusters (Communities) Nodes Lists
_PREFEXEC = 'exec'  # Prefix of the executing application / algorithm


# reFirstDigits = re.compile(r'\d+')  # First digit regex
_DEBUG_TRACE = False  # Trace start / stop and other events to stderr


def aggexec(algs):
	"""Aggregate execution statistics

	Aggregate execution results of all networks instances and shuffles and output average,
	and avg, min, max values for each network type per each algorithm.

	Expected format of the aggregating files:
	# ExecTime(sec)	CPU_time(sec)	CPU_usr(sec)	CPU_kern(sec)	RSS_RAM_peak(Mb)	TaskName
	0.550262	0.526599	0.513438	0.013161	2.086	syntmix/1K10/1K10^1!k7.1#1
	...

	algs  - algorithms were executed, which resource consumption  should be aggregated

	#>>> aggexec(['scp', 'ganxis']) is None
	#True
	"""
	#exectime = {}  # netname: [alg1_stat, alg2_stat, ...]
	# ATTENTION: for the correct output memory must be the last one
	mnames = ('exectime', 'cputime', 'rssmem')  # Measures names
	measures = [{}, {}, {}]  # exectiem, cputime, rssmem
	malgs = []  # Measured algs
	ialg = 0  # Algorithm index
	for alg in algs:
		algesfile = ''.join((_RESDIR, alg, '/', alg, _EXTEXECTIME))
		try:
			with open(algesfile, 'r') as aest:
				malgs.append(alg)
				for ln in aest:
					# Strip leading spaces
					ln = ln.lstrip()
					# Skip comments
					if not ln or ln[0] == '#':
						continue
					# Parse the content
					fields = ln.split(None, 5)
					# Note: empty and spaces strings were already excluded
					assert len(fields) == 6, (
						'Invalid format of the resource consumption file "{}": {}'.format(algesfile, ln))
					# Fetch and accumulate measures
					# Note: rstrip() is required, because fields[5] can ends with '\n';  os.path.split(...)[1]
					net = delPathSuffix(fields[5].rstrip(), True)  # Note: name can't be a path here
					#print('> net: >>>{}<<< from >{}<'.format(net, fields[5]), file=sys.stderr)
					assert net, 'Network name must exist'
					etime = float(fields[0])
					ctime = float(fields[1])
					rmem = float(fields[4])
					for imsr, val in enumerate((etime, ctime, rmem)):
						netstats = measures[imsr].setdefault(net, [])
						if len(netstats) <= ialg:
							assert len(netstats) == ialg, ('Network statistics are not synced with algorithms:'
								' ialg={}, net: {}, netstats: {}'.format(ialg, net, netstats))
							netstats.append(ItemsStatistic('_'.join((alg, net)), val, val))
						netstats[-1].add(val)
		except IOError:
			print('WARNING, execution results for "{}" do not exist, skipped.'.format(alg), file=sys.stderr)
		else:
			ialg += 1
	# Check number of the algorithms to be outputted
	if not malgs:
		print('WARNING, there are no any algortihms execution results to be aggregated.', file=sys.stderr)
		return
	# Output results
	for imsr, measure in enumerate(mnames):
		resfile = ''.join((_RESDIR, measure, _EXTAGGRES))
		resxfile = ''.join((_RESDIR, measure, _EXTAGGRESEXT))
		try:
			with open(resfile, 'a') as outres, open(resxfile, 'a') as outresx:
				# The header is unified for multiple outputs only for the outresx
				if not os.fstat(outresx.fileno()).st_size:
					# ExecTime(sec), ExecTime_avg(sec), ExecTime_min	ExecTime_max
					outresx.write('# <network>\n#\t<alg1_outp>\n#\t<alg2_outp>\n#\t...\n')
				# Output timestamp
				# Note: print() unlike .write() outputs also ending '\n'
				print(_TIMESTAMP_START_HEADER, file=outres)
				print(_TIMESTAMP_START_HEADER, file=outresx)
				# Output header, which might differ for distinct runs by number of algs
				outres.write('# <network>')
				for alg in malgs:
					outres.write('\t{}'.format(alg))
				outres.write('\n')
				# Output results for each network
				for netname, netstats in viewitems(measures[imsr]):
					outres.write(netname)
					outresx.write(netname)
					for ialg, stat in enumerate(netstats):
						if not stat.fixed:
							stat.fix()
						# Output sum for time, but avg for mem
						val = stat.sum if imsr < len(mnames) - 1 else stat.avg
						outres.write('\t{:.3f}'.format(val))
						outresx.write('\n\t{}>\ttotal: {:.3f}, per_item: {:.6f} ({:.6f} .. {:.6f})'
							.format(malgs[ialg], val, stat.avg, stat.min, stat.max))
					outres.write('\n')
					outresx.write('\n')
		except IOError as err:
			print('ERROR, "{}" resources consumption output is failed: {}. {}'
				.format(measure, err, traceback.format_exc(5)), file=sys.stderr)


def preparePath(taskpath):  # , netshf=False
	"""Create the path if required, otherwise move existent data to backup.
	All itnstances and shuffles of each network are handled all together and only once,
	even on calling this function for each shuffle.
	NOTE: To process files starting with taskpath, it should not contain '/' in the end

	taskpath  - the path to be prepared
	"""
	# netshf  - whether the task is a shuffle processing in the non-flat dir structure
	#
	# Backup existent files & dirs with such base only if this path exists and is not empty
	# ATTENTION: do not use only basePathExists(taskpath) here to avoid movement to the backup
	# processing paths when xxx.mod.net is processed before the xxx.net (have the same base)
	# Create target path if not exists
	if not os.path.exists(taskpath):
		os.makedirs(taskpath)
	elif not dirempty(taskpath):
		mainpath = delPathSuffix(taskpath)
		tobackup(mainpath, True, move=True)  # Move to the backup (old results can't be reused in the forming results)
		os.mkdir(taskpath)


# ATTENTION: this function should not be defined to not beight automatically executed
#def execAlgorithm(execpool, netfile, asym, odir, timeout, pathid='', selfexec=False, **kwargs):
#	"""Execute the algorithm (stub)
#
#	execpool  - execution pool to perform execution of current task
#	netfile  -  input network to be processed
#	asym  - network links weights are asymmetric (in/outbound weights can be different)
#	timeout  - execution timeout for this task
#	pathid  - path id of the net to distinguish nets with the same name located in different dirs.
#		Note: pathid is prepended with the separator symbol
#	selfexec=False  - current execution is the external or internal self call
#	kwargs  - optional algorithm-specific keyword agguments
#
#	return  - number of executions (executed jobs)
#	"""
#	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
# 		tasktracer is None or isinstance(tasktracer, TaskTracer)) , (
#		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
#		.format(execpool, netfile, asym, timeout))
#	# ATTENTION: for the correct execution algname must be always the same as func lower case name without the prefix "exec"
#	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'louvain_igraph'
#	return 0


class TaskTracer(object):
	_lock = Lock()

	def __init__(self, name, tasks):
		"""TaskTracer constructor
		
		Args:
			object (TaskTracer): TaskTracer instance
			name (str): the tracer name
			tasks (set(str)): remained tasks
		"""
		self.name = name
		self.tasks = tasks  # Active tasks
		self.ndone = 0  # The number of finished tasks

	def completed(self, task):
		"""Remove the task from the tracer incrementing the number of completed tasks
		
		Args:
			task (str): the completed task name
		"""
		if _lock.acquire(timeout=3):  # 3 sec
			try:
				self.tasks.remove(task)
				self.ndone += 1
			except ValueError as err:
				print('The completing task "{}" should be among the active tasks: {}', task, err, file=sys.stderr)
			finally:
				_lock.release()
		else:
			raise RuntimeError('Lock acqusition failed of "{}"'.format(self.name))


def funcToAppName(funcname):
	"""Fetch name of the execution application by the function name

	funcname  - name of the executing function

	returns  - name of the algorithm
	"""
	assert funcname.startswith(_PREFEXEC), 'Executing appliation is expected instead of "{}"'.format(funcname)
	return funcname[len(_PREFEXEC):]  # .lower()


def prepareResDir(appname, task, odir, pathid):
	"""Prepare output directory for the app results and backup the previous results

	appname  - application (algorithm) name
	task  - task name
	odir  - whether to output results to the dedicated dir named by the instance name,
		which actual the the shuffles with non-flat structure
	pathid  - path id (including the leading separator) of the input networks file, str

	return resulting directory without the ending '/' terminator
	"""
	# Preapare resulting directory
	taskdir = task  # Relative task directory withouth the ending '/'
	if odir:
		nameparts = parseName(task, True)
		taskdir = ''.join((nameparts[0], nameparts[2], '/', task))  # Use base name and instance id
	taskpath = ''.join((_RESDIR, appname, '/', _CLSDIR, taskdir, pathid))

	preparePath(taskpath)
	return taskpath


# Louvain
## Original Louvain
#def execLouvain(execpool, netfile, asym, odir, timeout, pathid='', tasknum=0):
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
#	task = os.path.split(netfile)[1]  # Base name of the network
#	assert task, 'The network name should exists'
#	if tasknum:
#		task = '-'.join((task, str(tasknum)))
#	netfile = '../' + netfile  # Use network in the required format
#
#	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'louvain'
#	# ./community graph.bin -l -1 -w graph.weights > graph.tree
#	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
#		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
#	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args
#		, timeout=timeout, stdout=''.join((_RESDIR, algname, '/', task, '.loc'))
#		, category=algname, size=netsize, stderr=''.join((_RESDIR, algname, '/', task, _EXTLOG))))
#	return 1
#
#
#def evalLouvain(execpool, basefile, measure, timeout):
#	return


class PyBin(object):
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
			# pyver = int(reFirstDigits.search(pyverstr).group())  # Take the first digits, i.e. the magor version
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
		# Note: the required interpreter existance in the system can't be checked here,
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


def execLouvainIg(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):  # , selfexec=False  - whether to call self recursively
	"""Execute Louvain using the igraph library
	Note: Louvain produces not stable results => multiple executions are desirable.

	execpool  - execution pool of worker processes
	netfile  - the input network to be clustered
	asym  - whether the input network is asymmetric (directed, specified by arcs)
	odir  - whether to output results to the dedicated dir named by the instance name,
		which is actual for the shuffles with non-flat structure
	timeout  - processing (clustering) timeout of the input file
	pathid  - path id (including the leading separator) of the input networks file, str
	tasktracer: TaskTracer  - optional task tracer
	workdir  - relative working directory of the app, actual when the app contains libs
	seed  - random seed, uint64_t

	returns  - the number of executions or None
	"""
	# Note: .. + 0 >= 0 to be sure that type is arithmetic, otherwise it's always true for the str
	assert execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Base name of the network
	assert task, 'The network name should exists'
	#if tasknum:
	#	task = '_'.join((task, str(tasknum)))

	# ATTENTION: for the correct execution algname must be always the same as func name without the prefix "exec"
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'louvain_igraph'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)

	# ./louvain_igraph.py -i=../syntnets/1K5.nsa -o=louvain_igoutp/1K5/1K5.cnl -l

	## Louvain accumulated statistics over shuffled modification of the network or total statistics for all networks
	#extres = '.acs'
	#if not selfexec:
	#	outpdir = ''.join((_RESDIR, algname, '/'))
	#	if not os.path.exists(outpdir):
	#		os.makedirs(outpdir)
	#	# Just erase the file of the accum results
	#	with open(taskpath + extres, 'w') as accres:
	#		accres.write('# Accumulated results for the shuffles\n')
	#
	#def postexec(job):
	#	"""Copy final modularity output to the separate file"""
	#	# File name of the accumulated result
	#	# Note: here full path is required
	#	accname = ''.join((workdir, _RESDIR, algname, extres))
	#	with open(accname, 'a') as accres:  # Append to the end
	#		# TODO: Evaluate the average
	#		subprocess.call(('tail', '-n 1', taskpath + _EXTLOG), stdout=accres)

	# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
	pybin = PyBin.bestof(pypy=False, v3=True)
	# Note: Louvain_igraph creates the output dir if it has not been existed, but not the exectime app
	errfile = taskpath + _EXTELOG
	logfile = taskpath + _EXTLOG

	# def relpath(path, basedir=workdir):
	# 	"""Relative path to the specified basedir"""
	# 	return os.path.relpath(path, basedir)
	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, pybin, './louvain_igraph.py', '-i' + ('nsa' if asym else 'nse')
		, '-lo', ''.join((taskpath, '/', task, _EXTCLNODES)), netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, stdout=logfile, stderr=errfile))

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
	#	for netfile in glob.iglob(''.join((escapePathWildcards(netdir), escapePathWildcards(task), '/*', netext))):
	#		execLouvain_ig(execpool, netfile, asym, odir, timeout, selfexec)
	#		execnum += 1
	return execnum


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		tasktracer is None or isinstance(tasktracer, TaskTracer)) , (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))

	# Fetch the task name
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Base name of the network
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'scp'

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	with open(netfile) as finp:
		netinfo = parseHeaderNslFile(finp, asym)
		asym = netinfo.directed
		if not netinfo.lnsnum:
			# Use network size if the number of links is not availbale
			size = os.fstat(finp.fileno()).st_size * (1 + (not asym))  # Multiply by 2 for the symmetric (undirected) network
			avgnls = None
		else:
			# The number of arcs in the network
			size = netinfo.lnsnum * (1 + (not netinfo.directed))  # arcs = edges * 2
			avgnls = size / float(netinfo.ndsnum)  # Average number of arcs per node
			size *= avgnls

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
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

	kmin = 3  # Min clique size to be used for the communities identificaiton
	kmax = 8  # Max clique size (~ min node degree to be considered)
	steps = '10'  # Use 10 scale levels as in Ganxis
	golden = (1 + 5 ** 0.5) * 0.5  # Golden section const: 1.618
	# Run for range of clique sizes
	for k in range(kmin, kmax + 1):
		# A single argument is k-clique size
		kstr = str(k)
		kstrex = 'k' + kstr
		# Embed params into the task name
		taskbasex = delPathSuffix(task, True)
		tasksuf = task[len(taskbasex):]
		ktask = ''.join((taskbasex, _SEPPARS, kstrex, tasksuf))
		# Backup prepated the resulting dir and backup the previous results if exist
		taskpath = prepareResDir(algname, ktask, odir, pathid)
		errfile = taskpath + _EXTELOG
		logfile = taskpath + _EXTLOG
		# Evaluate relative paths dependent of the alg params
		reltaskpath = relpath(taskpath)

		# scp.py netname k [start_linksnum end__linksnum numberofevaluations] [weight]
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', ktask, pathid)), '-s=/etime_' + algname
			, pybin, './scp.py', netfile, kstr, steps, ''.join((reltaskpath, '/', ktask, _EXTCLNODES)))

		#print('> Starting job {} with args: {}'.format('_'.join((ktask, algname, kstrex)), args + [kstr]))
		execpool.execute(Job(name=_SEPNAMEPART.join((algname, ktask)), workdir=workdir, args=args, timeout=timeout
			# , ondone=tidy, params=taskpath  # Do not delete dirs with empty results to explicitly see what networks are clustered having empty results
			# Note: increasing clique size k causes ~(k ** golden) increased consumption of both memory and time (up to k ^ 2),
			# so it's better to use the same category with boosted size for the much more efficient filtering comparing to the distinct categories
			, category=algname if avgnls is not None else '_'.join((algname, kstrex))
			, size=size * (k ** golden if avgnls is None or k >= avgnls else (avgnls - k) ** (-1/golden))
			, stdout=logfile, stderr=errfile))

	return kmax + 1 - kmin


def execRandcommuns(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None, instances=5):  # _netshuffles + 1
	"""Execute Randcommuns, Random Disjoint Clustering
	Results are not stable => multiple execution is desirable.

	Note: the ground-thruth should have the same file name as netfile and '.cnl' extension

	instances  - the number of clustering instances to be produced
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tseed: {}'
		.format(execpool, netfile, asym, timeout, seed))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'randcommuns'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)
	errfile = taskpath + _EXTELOG
	logfile = taskpath + _EXTLOG

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)
	# Set the best possible interpreter
	# Note: randcommuns loads input network using external igraph-python lib, which interacts slower with PyPy than with CPython
	pybin = PyBin.bestof(pypy=False, v3=True)

	# Form name of the ground-truth file on base of the input network filename with the extension relpaced to '.cnl'
	originpbase = netfile
	if odir:
		originpbase = os.path.split(netfile)[0]
		if not originpbase:
			assert 0, 'odir parameter validation failed, netfile should have some base directory'
			originpbase = os.path.splitext(netfile)[0]  # Take wile name without the extension instead of the parent dir
	gtfile = originpbase + _EXTCLNODES

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, pybin, './randcommuns.py', '-g=' + gtfile, ''.join(('-i=', netfile, netext)), '-o=' + taskpath
		, '-n=' + str(instances)]
	if seed is not None:
		args.append('-r=' + str(seed))
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, stdout=logfile, stderr=errfile))

	return 1


# DAOC Options
class DaocOpts(object):
	"""DAOC execution options"""
	def __init__(self, rlevout=None, gamma=1, reduction=None, significance=None):
		"""DAOC execution options initialization

		rlevout  - ratio (at least) of output levels shrinking starting from the widest (bottom) level, (0, 1].
			Recommended (if used): 0.75 .. 0.9.
		gamma  - resolution parameter, float:
			> 0 - static manual gamma for all clusters (1 is the default manual value)
			-1  - dynamic automatic identification for each cluster
		reduction  - items links reduction policy on clustering, X[w], where X:
			a  - ACCURATE
			m  - MEAN (recommended)
			s  - SEVERE
			'' - default reduction policy (-m)
		significance  - significant clusters output policy. Instead of the multi-level clusters output into distinct files with
		the rlevout step, output to the single file only significant (representative) clusers from all levels starting from the
		hierarhy root (top) and including all descendants that have higher density of the cluster structure than:
			sd  - single (one any of) direct owner
			ad  - all direct owners
			sh  - single (one any of) direct upper hierarchy of owners
			ah  - all upper hierarchy of owners
			''  - default policy for the significant clasters
		"""
		# Note the significance potentially can be more precise: 'ad%0.86/0.14~'
		assert ((rlevout is None and significance is not None) or rlevout > 0 and isinstance(gamma, Number)
			and (reduction is None or reduction == ''
				or (1 <= len(reduction) <= 2 and reduction[0] in 'ams' and (len(reduction) == 1 or reduction[1] == 'w')))
			and (significance is None or significance in ('', 'sd','ad','sh','ah'))
			# Note: either significant clusters are outputted or multilev clusters output is performed with the specified ratio
			and ((rlevout is None) ^ (significance is None))
			), ('Invalid input parameters:\n\trlevout: {},\n\tgamma: {}'
			'\n\treduction: {}\n\tsignificance: {}'.format(rlevout, gamma, reduction, significance))
		self.rlevout = rlevout
		self.gamma = gamma
		self.reduction = reduction
		self.significance = significance


	def __str__(self):
		"""String conversion"""
		return ', '.join([': '.join((name, str(val))) for name, val in viewitems(self.__dict__)])


# DAOC wit parameterized gamma
def daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None, opts=DaocOpts(rlevout=0.8)):
	"""Execute DAOC, Deterministic (including input order independent) Agglomerative Overlapping Clustering
	using standard modularity as optimization function

	algname  - name of the executing algorithm to be traced
	...
	rlevout  - ratio (at least) of output levels shrinking starting from the widest (bottom) level, (0, 1]
	gamma  - resolution parameter gamma, <0 means automatic identification of the optimal dymamic value, number (float or int)
	"""
	assert isinstance(algname, str) and algname and execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and isinstance(opts, DaocOpts), (  # Verify that gamma is a numeric value (int or float)
		'Invalid input parameters:\n\talgname: {},\n\texecpool: {},\n\tnet: {}'
		',\n\tasym: {},\n\ttimeout: {},\n\opts: {}'.format(algname, execpool, netfile, asym, timeout, opts))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Remove the base path and separate extension
	assert task, 'The network name should exists'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)
	errfile = taskpath + _EXTELOG  # Errors log + lib tracing including modularity value and clustering summary
	logfile = taskpath + _EXTLOG   # Tracing to stdout, contains timings

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	# ./daoc -w -g=1 -te -cxl[:/0.8]s=../../results/Daoc/karate.cnl ../../realnets/karate.nse.txt
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './daoc', '-t']  # Trace timing
	if opts.reduction is not None:
		args.append('-r' + opts.reduction)
	clsouto = ''  # Clusters optput options
	if opts.rlevout is not None:
		clsouto = str(opts.rlevout).join(('[:/', ']'))
	elif opts.significance is not None:
		clsouto = 's' + opts.significance
	args += ['-g=' + str(opts.gamma)  # Resolution parameter = 1 (standard modularity)
		, '-n' + ('a' if asym else 'e')
		# Output only max shares, per-level clusters output with step 0.8 in the simple format (with the header but without the share value)
		, ''.join(('-cx', clsouto, 's=', taskpath, _EXTCLNODES)), netfile]
	#print(''.join((algname, ' called with args: ', str(args))), file=sys.stderr)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, stdout=logfile, stderr=errfile))
	return 1


# DAOC (using standard modularity as an optimization function, non-generelized)
def execDaoc(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None
, opts=DaocOpts(rlevout=0.8, gamma=1, reduction=None, significance=None)):
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, opts)


# DAOC (using automatic adjusting of the resolution parameter, generelized modularity)
def execDaocA(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None
, opts=DaocOpts(rlevout=0.8, gamma=-1, reduction=None, significance=None)):
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'DaocA'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, opts)


# DAOC (using standard modularity as an optimization function, non-generelized)
def execDaoc_s_r(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None
, opts=DaocOpts(gamma=1, significance='', reduction='')):  # Note: '' values mean use default
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, opts)


# DAOC (using standard modularity as an optimization function, non-generelized)
def execDaocA_s_r(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None
, opts=DaocOpts(gamma=-1, significance='', reduction='')):  # Note: '' values mean use default
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'DaocA_s_r'
	return daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, opts)


# # DAOC (using standard modularity as an optimization function, non-generelized)
# def execDaoc_rm(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None
# # 1 - ACCURATE, 2 - MEAN;
# , opts=DaocOpts(rlevout=0.8, gamma=1, reduction='m')):
# 	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Daoc'
# 	return daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, opts)
#
#
# # DAOC (using automatic adjusting of the resolution parameter, generelized modularity)
# def execDaoc_ssh_rm(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'daoc/', seed=None
# #SIGNIF_OWNSHIER = 0xA
# , opts=DaocOpts(gamma=1, significance='sh')):
# 	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'DaocA'
# 	return daocGamma(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, opts)


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR+'ganxis/', seed=None):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tseed: {}'
		.format(execpool, netfile, asym, timeout, seed))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Remove the base path and separate extension
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Ganxis'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)
	errfile = taskpath + _EXTELOG
	logfile = taskpath + _EXTLOG

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	def tidy(job):
		# Note: GANXiS leaves empty ./output dir in the _ALGSDIR, which should be deleted
		tmp = workdir + 'output/'
		if os.path.exists(tmp):
			#os.rmdir(tmp)
			shutil.rmtree(tmp)

	# java -jar GANXiSw.jar -Sym 1 -seed 12345 -i ../../realnets/karate.txt -d ../../results/ganxis/karate
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, 'java', '-jar', './GANXiSw.jar', '-i', netfile, '-d', taskpath]
	if not asym:
		args.extend(['-Sym', '1'])
	if seed is not None:
		args.extend(['-seed', str(seed)])
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, ondone=tidy, stdout=logfile, stderr=errfile))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\tseed: {}'
		.format(execpool, netfile, asym, timeout, seed))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	netbasepath, task = os.path.split(netfile)  # Extract base path and file name
	if not netbasepath:
		netbasepath = '.'  # Note: '/' is added later
	task, netext = os.path.splitext(task)  # Separate file name and extension
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Oslom2'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)
	errfile = taskpath + _EXTELOG
	logfile = taskpath + _EXTLOG

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)

	# Move final results to the required dir on postprocessing and clear up
	def postexec(job):
		# Move communities output from the original location to the target one
		origResDir = ''.join((netbasepath, '/', task, netext, '_oslo_files/'))
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

	# ./oslom_[un]dir -f ../../realnets/karate.txt -w -seed 12345
	args = [xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './oslom_' +  ('dir' if asym else 'undir'), '-f', netfile, '-w']
	if seed is not None:
		args.extend(['-seed', str(seed)])
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, ondone=postexec, stdout=logfile, stderr=errfile))
	return 1


# pSCAN (Fast and Exact Structural Graph Clustering)
def execPscan(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0 and (
		tasktracer is None or isinstance(tasktracer, TaskTracer)) , (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Base name of the network
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'Pscan'

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)

	eps = 0.05  # Min epsilon (similarity threshold)
	epsMax = 0.9  # Max epsilon (similarity threshold)
	steps = 10  # The number of steps (similarity thresholds). Use 10 scale levels as in Ganxis.
	# Run for range of eps
	deps = (epsMax - eps) / steps  # Epsilon delta for each step
	while eps <= epsMax:
		#prm = '{:3g}'.format(eps)  # Alg params (eps) as string
		prm = '{:.2f}'.format(eps)  # Alg params (eps) as string
		prmex = 'e' + prm
		# Embed params into the task name
		taskbasex = delPathSuffix(task, True)
		tasksuf = task[len(taskbasex):]
		ctask = ''.join((taskbasex, _SEPPARS, prmex, tasksuf))  # Current task
		# Backup prepated the resulting dir and backup the previous results if exist
		taskpath = prepareResDir(algname, ctask, odir, pathid)
		errfile = taskpath + _EXTELOG
		#logfile = taskpath + _EXTLOG
		# Evaluate relative paths dependent of the alg params
		reltaskpath = relpath(taskpath)

		# ATTENTION: a single argument is k-clique size, specified later
		# ./pscan -e 0.7 -o graph-e7.cnl -f NSE graph.nse
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', ctask, pathid)), '-s=/etime_' + algname
			, './pscan', '-e', prm, '-o', ''.join((reltaskpath, '/', ctask, _EXTCLNODES))
			, '-f', 'NSA' if asym else 'NSE', netfile)

		#print('> Starting job {} with args: {}'.format('_'.join((ctask, algname, prmex)), args + [prm]))
		execpool.execute(Job(name=_SEPNAMEPART.join((algname, ctask)), workdir=workdir, args=args, timeout=timeout
			# , ondone=tidy, params=taskpath  # Do not delete dirs with empty results to explicitly see what networks are clustered having empty results
			#, stdout=logfile  # Skip standard log, because there are too many files, which does not contain useful information
			# Note: eps has not monotonous impact mainly on the exectution time, not large impact and the clustring is fast anyway
			, category='_'.join((algname, prmex)), size=netsize, stdout=os.devnull, stderr=errfile))
		eps += deps

	return steps


# rgmc algorithms family: 1: RG, 2: CGGC_RG, 3: CGGCi_RG
def rgmcAlg(algname, execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None, alg=None):
	"""Rgmc algorithms family

	algname  - name of the executing algorithm to be traced
	...
	alg  - the algorithm to be executed:  1: RG, 2: CGGC_RG, 3: CGGCi_RG
	"""
	algs = ('RG', 'CGGC_RG', 'CGGCi_RG')
	assert isinstance(algname, str) and algname and execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and (seed is None or isinstance(seed, int)) and alg in (1, 2, 3), (
		'Invalid input parameters:\n\talgname: {},\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {},\n\talg: {}'
		.format(algname, execpool, netfile, asym, timeout, algs[alg]))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Remove the base path and separate extension
	assert task, 'The network name should exists'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)
	errfile = taskpath + _EXTELOG
	logfile = taskpath + _EXTLOG

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	# ./rgmc -a 2 -c tests/rgmc_2/email.nse.cnl -i e networks/email.nse.txt
	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './rgmc', '-a', str(alg), '-c', ''.join((taskpath, '/', task, _EXTCLNODES))
		, '-i', 'a' if asym else 'e', netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, stdout=logfile, stderr=errfile))
	return 1


# CGGC_RG (rgmc -a 2)
def execCggcRg(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'CggcRg'
	return rgmcAlg(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, alg=2)


# CGGCi_RG (rgmc -a 3)
def execCggciRg(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'CggciRg'
	return rgmcAlg(algname, execpool, netfile, asym, odir, timeout, pathid, workdir, seed, alg=3)


# SCD
def execScd(execpool, netfile, asym, odir, timeout, pathid='', tasktracer=None, workdir=_ALGSDIR, seed=None):
	"""Scalable Community Detection (SCD)
	Note: SCD os applicable only for the undirected unweighted networks, it skips the weight
	in the weighted network.
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)
		) and timeout + 0 >= 0 and (tasktracer is None or isinstance(tasktracer, TaskTracer)
		) and (seed is None or isinstance(seed, int)), (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))

	# Evaluate relative network size considering whether the network is directed (asymmetric)
	netsize = os.path.getsize(netfile)
	if not asym:
		netsize *= 2
	# Fetch the task name and chose correct network filename
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Remove the base path and separate extension
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'scd'
	# Backup prepated the resulting dir and backup the previous results if exist
	taskpath = prepareResDir(algname, task, odir, pathid)
	errfile = taskpath + _EXTELOG
	logfile = taskpath + _EXTLOG

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specified basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	# ./scd -n 1 -o tests/scd/karate.nse.cnl -f networks/karate.nse.txt
	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './scd', '-n', '1' # Use a single threaded implementation
		, '-o', ''.join((taskpath, '/', task, _EXTCLNODES)), '-f', netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, category=algname, size=netsize, stdout=logfile, stderr=errfile))
	return 1


#if __name__ == '__main__':
#	"""Doc tests execution"""
#	import doctest
#	doctest.testmod()  # Detailed tests output
