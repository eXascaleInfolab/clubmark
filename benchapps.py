#!/usr/bin/env python2
# -*- coding: utf-8 -*-

"""
\descr: List of the clustering algorithms to be executed by the benchmark and accessory routines.

	Execution function for each algorithm must be named "exec<Algname>" and have the following signature:

	def execAlgorithm(execpool, netfile, asym, odir, timeout, pathid='', selfexec=False):
		Execute the algorithm (stub)

		execpool  - execution pool to perform execution of current task
		netfile  -  input network to be processed
		asym  - network links weights are assymetric (in/outbound weights can be different)
		timeout  - execution timeout for this task
		pathid  - path id of the net to distinguish nets with the same name located in different dirs.
			Note: pathid is prepended with the separator symbol
		selfexec  - current execution is the external or internal self call

		return  - number of executions (jobs) made

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-07
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import os
import shutil
import glob
import sys
import inspect  # To automatically fetch algorithm name
import traceback  # Stacktrace
import subprocess
import re

from datetime import datetime

from utils.mpepool import *

from sys import executable as PYEXEC  # Full path to the current Python interpreter
from benchutils import viewitems, delPathSuffix, ItemsStatistic, parseName, dirempty, tobackup, _SEPPARS, _UTILDIR
from benchevals import _SEPNAMEPART, _ALGSDIR, _RESDIR, _CLSDIR, _EXTERR, _EXTEXECTIME, _EXTAGGRES, _EXTAGGRESEXT

_EXTLOG = '.log'
_EXTCLNODES = '.cnl'  # Clusters (Communities) Nodes Lists
_PREFEXEC = 'exec'  # Prefix of the executing application / algorithm


reFirstDigits = re.compile('\d+')  # First digit regex


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
	mnames = ('exectime', 'cputime', 'rssmem')  # Measures names; ATTENTION: for the correct output memory must be the last one
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
							assert len(netstats) == ialg, 'Network statistics are not synced with algorithms: ialg={}, net: {}, netstats: {}'.format(ialg, net, netstats)
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
	# Output resutls
	timestamp = datetime.utcnow()
	for imsr, measure in enumerate(mnames):
		resfile = ''.join((_RESDIR, measure, _EXTAGGRES))
		resxfile = ''.join((_RESDIR, measure, _EXTAGGRESEXT))
		try:
			with open(resfile, 'a') as outres, open(resxfile, 'a') as outresx:
				# The header is unified for multiple outputs only for the outresx
				if not os.path.getsize(resxfile):
					outresx.write('# <network>\n#\t<alg1_outp>\n#\t<alg2_outp>\n#\t...\n')  # ExecTime(sec), ExecTime_avg(sec), ExecTime_min\tExecTime_max
				# Output timestamp
				outres.write('# --- {} ---\n'.format(timestamp))
				outresx.write('# --- {} ---\n'.format(timestamp))
				# Output header, which might differ for distinct runs by number of algs
				outres.write('# <network>')
				for alg in malgs:
					outres.write('\t{}'.format(alg))
				outres.write('\n')
				# Output results for each network
				for netname, netstats in viewitems(measures[imsr]):  # Note: .items() are not efficient on Python2
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
			print('ERROR, "{}" results output execution is failed: {}. {}'
				.format(measure, err, traceback.format_exc()), file=sys.stderr)


def	preparePath(taskpath):  # , netshf=False
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
#	asym  - network links weights are assymetric (in/outbound weights can be different)
#	timeout  - execution timeout for this task
#	pathid  - path id of the net to distinguish nets with the same name located in different dirs.
#		Note: pathid is prepended with the separator symbol
#	selfexec=False  - current execution is the external or internal self call
#	kwargs  - optional algorithm-specific keyword agguments
#
#	return  - number of executions (executed jobs)
#	"""
#	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
#		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
#		.format(execpool, netfile, asym, timeout))
#	# ATTENTION: for the correct execution algname must be always the same as func lower case name without the prefix "exec"
#	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'louvain_igraph'
#	return 0


def funcToAppName(funcname):
	"""Fetch name of the execution application by the function name"""
	assert funcname.startswith(_PREFEXEC), 'Executing appliation is expected instead of "{}"'.format(functname)
	return funcname[len(_PREFEXEC):]  # .lower()


def prepareResDir(appname, task, odir, pathid):
	"""Prepare output directory for the app results and backup the previous results

	appname  - application (algorithm) name
	task  - task name
	odir  - whether to output results to the dedicated dir named by the instance name,
		which actual the the shuffles with non-flat structure
	pathid  - pather id of the input networks file

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
#		, stderr=''.join((_RESDIR, algname, '/', task, _EXTLOG))))
#	return 1
#
#
#def evalLouvain(execpool, basefile, measure, timeout):
#	return


def execLouvainIg(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR, selfexec=False):
	"""Execute Louvain using the igraph library
	Note: Louvain produces not stable results => multiple executions are desirable.

	execpool  - execution pool of worker processes
	netfile  - the input network to be clustered
	asym  - whether the input network is asymmetric (directed, specified by arcs)
	odir  - whether to output results to the dedicated dir named by the instance name,
		which actual the the shuffles with non-flat structure
	timeout  - processing (clustering) timeout of the input file
	pathid  - pather id of the input networks file
	workdir  - relative working directory of the app, actual when the app contains libs
	selfexec  - whether to call self recursively

	returns  - the number of executions or None
	"""
	# Note: .. + 0 >= 0 to be sure that type is arithmetic, otherwise it's always true for the str
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Base name of the network
	assert task, 'The network name should exists'
	#if tasknum:
	#	task = '_'.join((task, str(tasknum)))

	# ATTENTION: for the correct execution algname must be always the same as func lower case name without the prefix "exec"
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
	pybin = PYEXEC if not os.path.split(PYEXEC)[1].startswith('pypy') else 'python'
	# Note: Louvain_igraph creates the output dir if it has not been existed, but not the exectime app
	errfile = ''.join((taskpath, _EXTLOG))

	# def relpath(path, basedir=workdir):
	# 	"""Relative path to the specidied basedir"""
	# 	return os.path.relpath(path, basedir)
	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specidied basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)
	taskpath = relpath(taskpath)

	# Prepare resdir
	resdir = _RESDIR
	if odir:
		resdir += algname + '/'
		if not os.path.exists(resdir):
			os.mkdir(resdir)
	args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, pybin, './louvain_igraph.py', '-i' + ('nsa' if asym else 'nse')
		, '-lo', ''.join((taskpath, '/', task, _EXTCLNODES)), netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=workdir, args=args, timeout=timeout
		#, ondone=postexec, stdout=os.devnull
		, stderr=errfile))

	execnum = 1
	# Note: execution on shuffled network instances is now generalized for all algorithms
	## Run again for all shuffled nets
	#if not selfexec:
	#	selfexec = True
	#	netdir = os.path.split(netfile)[0] + '/'
	#	#print('Netdir: ', netdir)
	#	for netfile in glob.iglob(''.join((escapePathWildcards(netdir), escapePathWildcards(task), '/*', netext))):
	#		execLouvain_ig(execpool, netfile, asym, odir, timeout, selfexec)
	#		execnum += 1
	return execnum


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task, netext = os.path.splitext(os.path.split(netfile)[1])  # Base name of the network
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'scp'

	relpath = lambda path: os.path.relpath(path, workdir)  # Relative path to the specidied basedir
	# Evaluate relative paths
	xtimebin = relpath(_UTILDIR + 'exectime')
	xtimeres = relpath(''.join((_RESDIR, algname, '/', algname, _EXTEXECTIME)))
	netfile = relpath(netfile)

	# Set the best possible interpreter
	# ATTENTION: Scp doesn't work correctly under Python 3
	pybin = PYEXEC if not os.path.split(PYEXEC)[1].find('3') == -1 else 'python'
	# Note: More accurate solution is not check "python -V" output, but it fails on Python2 for the
	# 'python -V' (but works for the 'python -h')
	# pyverstr = subprocess.check_output([PYEXEC, '-V']).decode()  # Note: Xcoding is required for Python3
	##pyverstr = subprocess.Popen((PYEXEC, '-V'), stdout=subprocess.PIPE).communicate()[0].decode()
	# pyver = int(reFirstDigits.search(pyverstr).group())  # Take the first digits, i.e. the magor version
	# pybin = 'python' if pyver >= 3 else PYEXEC
	#
	# Note: run SCP under pypy if possible
	try:
		with open(os.devnull, 'wb') as fdevnull:
			# NOTE: 'pypy -V' is outputted into the stdout even when another file is specified for pypy/Python2,
			# it works fine only on Python3
			if pybin.find('pypy') == -1 and not subprocess.call(('pypy', '-h'), stdout=fdevnull):
				pybin = 'pypy'
	except OSError:
		pass

	# def tidy(job):
	# 	# The network might lack large cliques, so for some parameters the resulting
	# 	# directories might be empty and should be cleared
	# 	if os.path.isdir(job.params) and dirempty(job.params):
	# 		os.rmdir(job.params)

	kmin = 3  # Min clique size to be used for the communities identificaiton
	kmax = 8  # Max clique size (~ min node degree to be considered)
	# Run for range of clique sizes
	for k in range(kmin, kmax + 1):
		kstr = str(k)
		kstrex = 'k' + kstr
		# Embed params into the task name
		taskbasex = delPathSuffix(task, True)
		tasksuf = task[len(taskbasex):]
		ktask = ''.join((taskbasex, _SEPPARS, kstrex, tasksuf))
		# Backup prepated the resulting dir and backup the previous results if exist
		taskpath = prepareResDir(algname, ktask, odir, pathid)
		errfile = ''.join((taskpath, _EXTLOG))
		# Evaluate relative paths dependent of the alg params
		reltaskpath = relpath(taskpath)

		# ATTENTION: a single argument is k-clique size, specified later
		steps = '10'  # Use 10 scale levels as in Ganxis
		# scp.py netname k [start_linksnum end__linksnum numberofevaluations] [weight]
		args = (xtimebin, '-o=' + xtimeres, ''.join(('-n=', ktask, pathid)), '-s=/etime_' + algname
			, pybin, './scp.py', netfile, kstr, steps, ''.join((reltaskpath, '/', ktask, _EXTCLNODES)))

		#print('> Starting job {} with args: {}'.format('_'.join((ktask, algname, kstrex)), args + [kstr]))
		execpool.execute(Job(name=_SEPNAMEPART.join((algname, ktask)), workdir=workdir, args=args, timeout=timeout
			# , ondone=tidy, params=taskpath  # Do not delete dirs with empty results to explicitly see what networks are clustered having empty results
			, stderr=errfile))

	return kmax + 1 - kmin


def execRandcommuns(execpool, netfile, asym, odir, timeout, pathid='', instances=5):  # _netshuffles + 1
	"""Execute Randcommuns, Random Disjoint Clustering
	Results are not stable => multiple execution is desirable.

	instances  - number of networks instances to be generated
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'randcommuns'
	# Backup previous results if exist
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, 'python', ''.join(('./', algname, '.py')), ''.join(('-g=../', netfile, _EXTCLNODES))
		, ''.join(('-i=../', netfile, netext)), ''.join(('-o=../', taskpath))
		, ''.join(('-n=', str(instances))))
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout
		, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


# HiReCS
def execHirecs(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'hirecs'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cls=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsOtl(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'hirecsotl'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cols=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsAhOtl(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'hirecsahotl'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-coas=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsNounwrap(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # Or 'hirecshfold'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', '../' + netfile)
	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=''.join((taskpath, '.hoc'))
		, stderr=taskpath + _EXTLOG))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.split(netfile)[1]  # Base name of the network
	task, netext = os.path.splitext(task)
	assert task, 'The network name should exists'

	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'oslom2'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))
	# Note: wighted networks (-w) stands for the used null model, not for the input file format.
	# Link weight is set to 1 if not specified in the file for weighted network.
	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './oslom_undir' if not asym else './oslom_dir', '-f', '../' + netfile, '-w')

	preparePath(taskpath)

	netdir = os.path.split(netfile)[0] + '/'
	# Copy results to the required dir on postprocessing
	def postexec(job):
		# Copy communities output from original location to the target one
		origResDir = ''.join((netdir, task, netext, '_oslo_files/'))
		for fname in glob.iglob(escapePathWildcards(origResDir) +'tp*'):
			shutil.copy2(fname, taskpath)

		# Move whole dir as extra task output to the logsdir
		outpdire = taskpath + '/extra/'
		if not os.path.exists(outpdire):
			os.mkdir(outpdire)
		else:
			# If dest dir already exists, remove it to avoid exception on rename
			shutil.rmtree(outpdire)
		os.rename(origResDir, outpdire)

		# Note: oslom2 leaves ./tp file in the _ALGSDIR, which should be deleted
		fname = _ALGSDIR + 'tp'
		if os.path.exists(fname):
			os.remove(fname)

	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout, ondone=postexec
		, stdout=taskpath + _EXTLOG, stderr=taskpath + _EXTERR))
	return 1


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, odir, timeout, pathid='', workdir=_ALGSDIR):
	#print('> exec params:\n\texecpool: {}\n\tnetfile: {}\n\tasym: {}\n\ttimeout: {}'
	#	.format(execpool, netfile, asym, timeout))
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	algname = funcToAppName(inspect.currentframe().f_code.co_name)  # 'ganxis'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))
	args = ['../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, 'java', '-jar', './GANXiSw.jar', '-i', '../' + netfile, '-d', '../' + taskpath]
	if not asym:
		args.append('-Sym 1')  # Check existance of the back links and generate them if requried

	preparePath(taskpath)

	def tidy(job):
		# Note: GANXiS leaves empty ./output dir in the _ALGSDIR, which should be deleted
		tmp = _ALGSDIR + 'output/'
		if os.path.exists(tmp):
			#os.rmdir(tmp)
			shutil.rmtree(tmp)

	execpool.execute(Job(name=_SEPNAMEPART.join((algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout, ondone=tidy
		, stdout=taskpath + _EXTLOG, stderr=taskpath + _EXTERR))
	return 1


#if __name__ == '__main__':
#	"""Doc tests execution"""
#	import doctest
#	doctest.testmod()  # Detailed tests output
