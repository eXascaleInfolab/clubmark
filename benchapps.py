#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr: List of the clustering algorithms and their evaluation functions
	to be executed by the benchmark

	Execution function for each algorithm must be named: exec<Algname>
	Evaluation function for each algorithm must be named: eval<Algname>

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-07
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import os
import shutil
import glob
import subprocess
import sys
# Add algorithms modules
#sys.path.insert(0, 'algorithms')  # Note: this operation might lead to ambiguity on paths resolving

from algorithms.louvain_igraph import louvain
from algorithms.randcommuns import randcommuns
from benchcore import *
from benchutils import *


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_algsdir = 'algorithms/'  # Default directory of the benchmarking algorithms
_resdir = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to _algsdir
_clsdir = 'clusters/'  # Clusters directory for the resulting clusters of algorithms execution
_moddir = 'mod/'
_nmidir = 'nmi/'
_extlog = '.log'
_exterr = '.err'
_extexectime = '.rcp'  # Resource Consumption Profile
_extclnodes = '.cnl'  # Clusters (Communities) Nodes Lists
#_extmod = '.mod'
_execnmi = './gecmi'  # Binary for NMI evaluation
_sepinst = '^'  # Network instances separator, must be a char
_seppars = '!'  # Network shuffles separator, must be a char
#_netshuffles = 4  # Number of shuffles for each input network for Louvain_igraph (non determenistic algorithms)


def	preparePath(taskpath):
	"""Create the path if required, otherwise move existent data to backup.
	All itnstances and shuffles of each network are handled all together and only once,
	even on calling this function for each shuffle.
	NOTE: To process files starting with taskpath, it should not contain '/' in the end

	taskpath  - the path to be prepared
	"""
	# Backup existent files & dirs with such base only if this path exists and is not empty
	# ATTENTION: do not use basePathExists(taskpath) heree to avoid movement to the backup
	# processing paths when xxx.mod.net is processed before the xxx.net (have the same base)
	if os.path.exists(taskpath) and not dirempty(taskpath):
		# Extract main task base name from instances, shuffles and params and process them all together
		mainpath, name = os.path.split(taskpath)
		if name:
			name = os.path.splitext(name)[0]
			pos = filter(lambda x: x != -1, [name.find(c) for c in (_sepinst, _seppars)])
			if pos:
				pos = min(pos)
				assert pos, 'Separators should not be the first symbol of the name'
				name = name[:pos]
			mainpath = '/'.join((mainpath, name))
		# Extract endings of multiple instances
		parts = mainpath.rsplit('_', 1)
		if len(parts) >= 2:
			try:
				int(parts[1])
			except ValueError:
				# It's not an instance name
				pass
			else:
				# Instance name
				mainpath = parts[0]
		backupPath(mainpath, True)
	# Create target path if not exists
	if not os.path.exists(taskpath):
		os.makedirs(taskpath)


def nmiAlgorithm(execpool, algname, gtres, timeout, evalbin=_execnmi, evalname='nmi', stderr=os.devnull):
	"""Evaluate the algorithm by the specified nmi measure

	execpool  - execution pool of worker processes
	algname  - the algorithm name that is evaluated
	gtres  - ground truth result: file name of clusters for each of which nodes are listed (clusters nodes lists file)
	timeout  - execution timeout, 0 - infinity
	evalbin  - file name of the evaluation binary
	evalname  - name of the evaluation measure
	stderr  - optional redifinition of the stderr channel: None - use default, os.devnull - skip
	"""
	assert execpool and gtres and algname and evalbin and evalname, "Parameters must be defined"
	# Fetch the task name and chose correct network filename
	task = os.path.splitext(os.path.split(gtres)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	args = ('../exectime', ''.join(('-o=./', evalname,_extexectime)), ''.join(('-n=', task, '_', algname))
		, './eval.sh', evalbin, '../' + gtres, ''.join(('../', _resdir, algname, '/', task)), algname, evalname)
	execpool.execute(Job(name='_'.join((evalname, task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((_resdir, algname, '/', evalname, '_', task, _extlog)), stderr=stderr))

	# Evaluate also shuffled networks if exists
	i = 0
	taskex = ''.join((task, '_', str(i)))
	while os.path.exists(''.join((_resdir, algname, '/', taskex))):
		args = ('../exectime', ''.join(('-o=./', evalname,_extexectime)), ''.join(('-n=', taskex, '_', algname))
			, './eval.sh', evalbin, '../' + gtres, ''.join(('../', _resdir, algname, '/', taskex)), algname, evalname)
		execpool.execute(Job(name='_'.join((evalname, taskex, algname)), workdir=_algsdir, args=args
			, timeout=timeout, stdout=''.join((_resdir, algname, '/', evalname, '_', taskex, _extlog)), stderr=stderr))
		i += 1
		taskex = ''.join((task, '_', str(i)))


def evalGeneric(execpool, evalname, algname, basefile, resdir, timeout, evalfile, aggregate=None):
	"""Generic evaluation on the specidied file
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	evalname  - evaluating measure name
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
	resdir  - dir to store results
	timeout  - execution timeout for this task
	evalfile  - file evaluation callback to define evaluation jobs, signature:
		evalfile(jobs, cfile, jobname, task, taskoutp, ijobsuff, logsbase)
	aggregate  - aggregation callback, called on the task completion, signature: aggregate(task)
	"""
	assert execpool and basefile and evalname and algname, "Parameters must be defined"
	# Fetch the task name and chose correct network filename
	taskcapt = os.path.splitext(os.path.split(basefile)[1])[0]  # Name of the basefile
	assert taskcapt, 'The file name must exists'

	# Make dirs with logs & errors
	# Directory of resulting community structures (clusters) for each network
	# Note: consider possible parameters of the executed algorithm, embedded into the dir names with _seppars
	taskame, ishuf = os.path.splitext(taskcapt)  # Separate shuffling index if present
	assert not ishuf, 'Base file should not be shuffled'
	evaluated = False
	#print('basefile: {}, taskame: {}'.format(basefile, taskame))

	# Resource consumption profile file name
	rcpoutp = ''.join((_resdir, algname, '/', evalname, _extexectime))
	# Task for all instances and shuffles to perform single postprocessing
	itaskcapt = len(taskcapt)  # Index of the task identifier start
	task = Task(name='_'.join((evalname, taskame, algname)), ondone=aggregate)
	jobs = []
	for clsbase in glob.iglob(''.join((_resdir, algname, '/', _clsdir, escapePathWildcards(taskame), '*'))):
		# Skip instances of the base network traversed by iglob
		basename = os.path.split(clsbase)[1]
		if basename[itaskcapt] == _sepinst:
			continue
		evaluated = True
		# Index of the base name without shuffling notation
		ijobsuff = basename.rfind('.') + 1  # Remove shuffling part
		if not ijobsuff:
			ijobsuff = len(basename) + 1  # Skip level separator symbol
		else:
			try:
				int(basename[ijobsuff:])
			except ValueError as err:
				raise ValueError('Shuffling suffix represents part of the filename: ' + str(err))
		# Note: separate dir is created, because modularity is evaluated for all files in the target dir,
		# which are different granularity / hierarchy levels
		logsbase = clsbase.replace(_clsdir, resdir)
		# Remove previous results if exist
		if os.path.exists(logsbase):
			shutil.rmtree(logsbase)
		os.makedirs(logsbase)

		# Skip shuffle indicator to accumulate values from all shuffles into the single file
		taskoutp = '.'.join((os.path.splitext(logsbase)[0], evalname))  # evalext  # Name of the file with modularity values for each level
		if os.path.exists(taskoutp):
			os.remove(taskoutp)

		# Traverse over all resulting communities for each ground truth, log results
		for cfile in glob.iglob(escapePathWildcards(clsbase) + '/*'):
			# Extract base name of the evaluating level
			taskex = os.path.splitext(os.path.split(cfile)[1])[0]
			assert taskex, 'The clusters name should exists'
			jobname = '_'.join((evalname, taskex, algname))
			logfilebase = '/'.join((logsbase, taskex))
			evalfile(jobs, cfile, jobname, task, taskoutp, rcpoutp, taskex[ijobsuff:], logfilebase)
	# Run all jobs after all of them were added to the task
	if not evaluated:
		print('WARNING, "{}" clusters "{}" do not exist'.format(algname, basename), file=sys.stderr)
	else:
		for job in jobs:
			try:
				execpool.execute(job)
			except StandardError as err:
				print('WARNING, "{}" job is interrupted by the exception: {}'
					.format(job.name, err), file=sys.stderr)


def evalAlgorithm(execpool, algname, basefile, measure, timeout):
	"""Evaluate the algorithm by the specified measure.
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
	measure  - target measure to be evaluated: {nmi, nmi-s, mod}
	timeout  - execution timeout for this task
	"""
	print('Evaluating {} for "{}" on base of "{}"...'.format(measure, algname, basefile))

	#evalname = None
	#if measure == 'nmi-s':
	#	# Evaluate by NMI_sum (onmi) instead of NMI_conv(gecmi)
	#	evalname = measure
	#	measure = 'nmi'
	#eaname = measure + 'Algorithm'
	#evalg = getattr(sys.modules[__name__], eaname, unknownApp(eaname))
	#if not evalname:
	#	evalg(execpool, algname, basefile, timeout)
	#else:
	#	evalg(execpool, algname, basefile, timeout, evalbin='./onmi_sum', evalname=evalname)

	def modEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, jobsuff, logsbase):
		"""Add modularity evaluatoin job to the current jobs
		NOTE: all paths are given relative to the root benchmark directory.

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		jobsuff  - job specific suffix after the mutual name base inherent to the task
		logsbase  - base part of the file name for the logs including errors
		"""
		# Processing is performed from the algorithms dir
		args = ('./hirecs', '-e=../' + cfile, '../' + basefile)

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			result = job.proc.communicate()[0]  # Read buffered stdout
			# Find require value to be aggregated
			targpref = 'mod: '
			# Match float number
			mod = parseFloat(result[len(targpref):]) if result.startswith(targpref) else None
			if mod is None:
				print('ERROR, job "{}" has invalid output format. Moularity value is not found in:\n{}'
					.format(job.name, result), file=sys.stderr)
				return

			taskoutp = job.params['taskoutp']
			with open(taskoutp, 'a') as tmod:  # Append to the end
				if not os.path.getsize(taskoutp):
					tmod.write('# Q\t[ShuffleIndex_]Level\n')
					tmod.flush()
				tmod.write('{}\t{}\n'.format(mod, job.params['jobsuff']))


		jobs.append(Job(name=jobname, task=task, workdir=_algsdir, args=args
			, timeout=timeout, ondone=aggLevs, params={'taskoutp': taskoutp, 'jobsuff': jobsuff}
			# Output modularity to the proc PIPE buffer to be aggregated on postexec to avoid redundant files
			, stdout=PIPE, stderr=logsbase + _exterr))


	def nmiEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, jobsuff, logsbase):
		"""Add nmi evaluatoin job to the current jobs

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		jobsuff  - job specific suffix after the mutual name base inherent to the task
		logsbase  - base part of the file name for the logs including errors

		Example:
		[basefile: syntnets/networks/1K10/1K10.cnl]
		cfile: results/scp/clusters/1K10!k3/1K10!k3_1.cnl
		jobname: nmi_1K10!k3_1_scp
		task.name: nmi_1K10_scp
		taskoutp: results/scp/nmi/1K10!k3.nmi
		rcpoutp: results/scp/nmi.rcp
		jobsuff: 1
		logsbase: results/scp/nmi/1K10!k3/1K10!k3_1
		"""
		print('nmieval;  basefile: {}\n\tcfile: {}\n\tjobname: {}\n\ttask.name: {}\n\ttaskoutp: {}'
			  '\n\trcpoutp: {} \n\tjobsuff: {}\n\tlogsbase: {}'
			  .format(basefile, cfile, jobname, task.name, taskoutp, rcpoutp, jobsuff, logsbase))
		## Undate current environmental variables with LD_LIBRARY_PATH
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
				taskoutp = job.params['taskoutp']
				print('>>> NMI aggLevs executing, taskoutp: ' + taskoutp)
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.path.getsize(taskoutp):
						tnmi.write('# NMI\t[shuffle_]level\n')
						tnmi.flush()
					tnmi.write('{}\t{}\n'.format(nmi, job.params['jobsuff']))
					#subprocess.call(''.join(('tail -n 1 "', job.stdout, '" ', "| sed 's/^mod: \\([^,]*\\).*/\\1\\t{}/'"
					#	# Add task name as part of the filename considering redundant prefix in GANXiS
					#	.format(job.params['jobsuff']))), stdout=tnmi, shell=True)


		jobs.append(Job(name=jobname, task=task, workdir=_algsdir, args=args
			, timeout=timeout, ondone=aggLevs, params={'taskoutp': taskoutp, 'jobsuff': jobsuff}
			, stdout=PIPE, stderr=logsbase + _exterr))

		#args = ('../exectime', ''.join(('-o=./', evalname,_extexectime)), ''.join(('-n=', task, '_', algname))
		#	, './eval.sh', evalbin, '../' + gtres, ''.join(('../', _resdir, algname, '/', task)), algname, evalname)
		#execpool.execute(Job(name='_'.join((evalname, task, algname)), workdir=_algsdir, args=args
		#	, timeout=timeout, stdout=''.join((_resdir, algname, '/', evalname, '_', task, _extlog)), stderr=stderr))


	def modAggregate(task):
		"""Aggregate resutls for the executed task from task-related resulting files
		"""
		# Traverse over *.mod files, evaluate mean and 2*STD for shuffles and output
		# everything to the accumulative average file: resdir/scp.mod
		pass
		## Sort the task acc mod file and accumulate the largest value to the totall acc mod file
		## Note: here full path is required
		#amodname = ''.join((_resdir, algname, _extmod))  # Name of the file with resulting modularities
		#if not os.path.exists(amodname):
		#	with open(amodname, 'a') as amod:
		#		if not os.path.getsize(amodname):
		#			amod.write('# Network\tQ\tTask\n')  # Network\tQ\tQ_STD
		#			amod.flush()
		#with open(amodname, 'a') as amod:  # Append to the end
		#	subprocess.call(''.join(('printf "', task, '\t `sort -g -r "', taskoutp,'" | head -n 1`\n"')), stdout=amod, shell=True)


	def nmiAggregate(task):
		pass


	if measure == 'mod':
		evalGeneric(execpool, measure, algname, basefile, _moddir, timeout, modEvaluate, modAggregate)
	elif measure == 'nmi':
		evalGeneric(execpool, measure, algname, basefile, _nmidir, timeout, nmiEvaluate, nmiAggregate)
	elif measure == 'nmi-s':
		pass
		#evalg(execpool, algname, basefile, timeout)
		#evalg(execpool, algname, basefile, timeout, evalbin='./onmi_sum', evalname=evalname)
	else:
		raise ValueError('Unexpected measure: ' + measure)


# ATTENTION: this function should not be defined to not beight automatically executed
#def execAlgorithm(execpool, netfile, asym, timeout, selfexec=False, **kwargs):
#	"""Execute the algorithm (stub)
#
#	execpool  - execution pool to perform execution of current task
#	netfile  -  input network to be processed
#	asym  - network links weights are assymetric (in/outbound weights can be different)
#	timeout  - execution timeout for this task
#	selfexec=False  - current execution is the external or internal self call
#	kwargs  - optional algorithm-specific keyword agguments
#
#	return  - number of executions
#	"""
#	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
#		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
#		.format(execpool, netfile, asym, timeout))
#	return 0


# Louvain
## Original Louvain
#def execLouvain(execpool, netfile, asym, timeout, tasknum=0):
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
#	algname = 'louvain'
#	# ./community graph.bin -l -1 -w graph.weights > graph.tree
#	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
#		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
#	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
#		, timeout=timeout, stdout=''.join((_resdir, algname, '/', task, '.loc'))
#		, stderr=''.join((_resdir, algname, '/', task, _extlog))))
#	return 1
#
#
#def evalLouvain(execpool, basefile, measure, timeout):
#	return


def execLouvain_ig(execpool, netfile, asym, timeout, selfexec=False):
	"""Execute Louvain
	Results are not stable => multiple execution is desirable.

	returns number of executions or None
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	#if tasknum:
	#	task = '_'.join((task, str(tasknum)))

	algname = 'louvain_igraph'
	# ./louvain_igraph.py -i=../syntnets/1K5.nsa -ol=louvain_igoutp/1K5/1K5.cnl
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))

	preparePath(taskpath)

	## Louvain accumulated statistics over shuffled modification of the network or total statistics for all networks
	#extres = '.acs'
	#if not selfexec:
	#	outpdir = ''.join((_resdir, algname, '/'))
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
	#	accname = ''.join((_algsdir, _resdir, algname, extres))
	#	with open(accname, 'a') as accres:  # Append to the end
	#		# TODO: Evaluate the average
	#		subprocess.call(('tail', '-n 1', taskpath + _extlog), stdout=accres)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, pyexec, ''.join(('./', algname, '.py')), ''.join(('-i=../', netfile, netext))
		, ''.join(('-ol=../', taskpath, _extclnodes)))
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout
		#, ondone=postexec
		, stdout=os.devnull, stderr=''.join((taskpath, _extlog))))

	execnum = 1
	# Note: execution on shuffled network instances is now generalized for all algorithms
	## Run again for all shuffled nets
	#if not selfexec:
	#	selfexec = True
	#	netdir = os.path.split(netfile)[0] + '/'
	#	#print('Netdir: ', netdir)
	#	for netfile in glob.iglob(''.join((escapePathWildcards(netdir), escapePathWildcards(task), '/*', netext))):
	#		execLouvain_ig(execpool, netfile, asym, timeout, selfexec)
	#		execnum += 1
	return execnum
#
#
#def evalLouvain_ig(execpool, cnlfile, timeout):
#	#print('Applying {} to {}'.format('louvain_igraph', cnlfile))
#	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph')
#
#
#def evalLouvain_igNS(execpool, basefile, measure, timeout):
#	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
#	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph', evalbin='./onmi_sum', evalname='nmi-s')
#
#
#def modLouvain_ig(execpool, netfile, timeout):
#	modAlgorithm(execpool, netfile, timeout, 'louvain_igraph')


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, timeout):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task, netext = os.path.splitext(netfile)
	task = os.path.split(task)[1]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'scp'
	kmin = 3  # Min clique size to be used for the communities identificaiton
	kmax = 8  # Max clique size (~ min node degree to be considered)
	# Run for range of clique sizes
	for k in range(kmin, kmax + 1):
		kstr = str(k)
		kstrex = 'k' + kstr
		# Embed params into the task name
		taskbasex, taskshuf = os.path.splitext(task)
		ktask = ''.join((taskbasex, _seppars, kstrex, taskshuf))
		# Backup previous results if exist
		taskpath = ''.join((_resdir, algname, '/', _clsdir, ktask))

		preparePath(taskpath)

		# ATTENTION: a single argument is k-clique size, specified later
		steps = '10'  # Use 10 levels in the hierarchy Ganxis
		resbase = ''.join(('../', taskpath, '/', ktask))  # Base name of the result
		# scp.py netname k [start_linksnum end__linksnum numberofevaluations] [weight]
		args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + ktask
			, pyexec, ''.join(('./', algname, '.py')), '../' + netfile, kstr, steps, resbase + _extclnodes)

		def tidy(job):
			"""Remove empty resulting folders"""
			# Note: GANXiS leaves empty ./output dir in the _algsdir, which should be deleted
			path = os.path.split(job.args[-1])[0][3:]  # Skip '../' prefix
			if dirempty(path):
				os.rmdir(path)

		#print('> Starting job {} with args: {}'.format('_'.join((ktask, algname, kstrex)), args + [kstr]))
		execpool.execute(Job(name='_'.join((ktask, algname)), workdir=_algsdir, args=args, timeout=timeout
			, ondone=tidy, stderr=taskpath + _extlog))

	return kmax + 1 - kmin


def execRandcommuns(execpool, netfile, asym, timeout, instances=5):  # _netshuffles + 1
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
	algname = 'randcommuns'
	# Backup previous results if exist
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))

	preparePath(taskpath)

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, pyexec, ''.join(('./', algname, '.py')), ''.join(('-g=../', netfile, _extclnodes))
		, ''.join(('-i=../', netfile, netext)), ''.join(('-o=../', taskpath))
		, ''.join(('-n=', str(instances))))
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout
		, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def execHirecs(execpool, netfile, asym, timeout):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecs'
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cls=../', taskpath, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def execHirecsOtl(execpool, netfile, asym, timeout):
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
	algname = 'hirecsotl'
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cols=../', taskpath, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def execHirecsAhOtl(execpool, netfile, asym, timeout):
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
	algname = 'hirecsahotl'
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-coas=../', taskpath, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def execHirecsNounwrap(execpool, netfile, asym, timeout):
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
	algname = 'hirecshfold'
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((taskpath, '.hoc'))
		, stderr=taskpath + _extlog))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, timeout):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.split(netfile)[1]  # Base name of the network
	task, netext = os.path.splitext(task)
	assert task, 'The network name should exists'

	algname = 'oslom2'
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))
	# Note: wighted networks (-w) stands for the used null model, not for the input file format.
	# Link weight is set to 1 if not specified in the file for weighted network.
	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
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

		# Note: oslom2 leaves ./tp file in the _algsdir, which should be deleted
		fname = _algsdir + 'tp'
		if os.path.exists(fname):
			os.remove(fname)

	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
		, stdout=taskpath + _extlog, stderr=taskpath + _exterr))
	return 1


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, timeout):
	#print('> exec params:\n\texecpool: {}\n\tnetfile: {}\n\tasym: {}\n\ttimeout: {}'
	#	.format(execpool, netfile, asym, timeout))
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'ganxis'
	taskpath = ''.join((_resdir, algname, '/', _clsdir, task))
	args = ['../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, 'java', '-jar', './GANXiSw.jar', '-i', '../' + netfile, '-d', '../' + taskpath]
	if not asym:
		args.append('-Sym 1')  # Check existance of the back links and generate them if requried

	preparePath(taskpath)

	def postexec(job):
		# Note: GANXiS leaves empty ./output dir in the _algsdir, which should be deleted
		tmp = _algsdir + 'output/'
		if os.path.exists(tmp):
			#os.rmdir(tmp)
			shutil.rmtree(tmp)

	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
		, stdout=taskpath + _extlog, stderr=taskpath + _exterr))
	return 1
