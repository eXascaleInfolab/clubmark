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

# Add algorithms modules
import sys
#sys.path.insert(0, 'algorithms')  # Note: this operation might lead to ambiguity on paths resolving

from algorithms.louvain_igraph import louvain
from algorithms.randcommuns import randcommuns
from benchcore import Job
from benchutils import *

from benchcore import _extexectime
from benchcore import _extclnodes
from benchutils import  *  # Full path to the current Python interpreter


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_algsdir = 'algorithms/'  # Default directory of the benchmarking algorithms
_resdir = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to _algsdir
_extlog = '.log'
_exterr = '.err'
_execnmi = './gecmi'  # Binary for NMI evaluation
_extmod = '.mod'
_sepinst = '^'  # Network instances separator, must be a char
_seppars = '*'  # Network shuffles separator, must be a char
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
				assert pos, 'Separators are not the first symbol of the name'
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


def execAlgorithm(execpool, netfile, asym, timeout, selfexec=False, **kwargs):
	"""Execute the algorithm (stub)

	execpool  - execution pool to perform execution of current task
	netfile  -  input network to be processed
	asym  - network links weights are assymetric (in/outbound weights can be different)
	timeout  - execution timeout for this task
	selfexec=False  - current execution is the external or internal self call
	kwargs  - optional algorithm-specific keyword agguments

	return  - number of executions
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	return 0


def evalAlgorithm(execpool, gtres, timeout, algname, evalbin=_execnmi, evalname='nmi', stderr=os.devnull):
	"""Evaluate the algorithm by the specified measure

	execpool  - execution pool of worker processes
	gtres  - ground truth result: file name of clusters for each of which nodes are listed (clusters nodes lists file)
	timeout  - execution timeout, 0 - infinity
	algname  - the algorithm name that is evaluated
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


def modAlgorithm(execpool, netfile, timeout, algname):  # , multirun=True
	"""Evaluate quality of the algorithm by modularity

	execpool  - execution pool of worker processes
	netfile  - file name of the input network
	timeout  - execution timeout, 0 - infinity
	algname  - the algorithm name that is evaluated
	multirun  - evaluate also on the shuffled networks (is required for non-deterministic algorithms only)
	"""
	assert execpool and netfile and algname, "Parameters must be defined"
	# Fetch the task name and chose correct network filename
	task = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	# Make dirs with mod logs
	# Directory of resulting community structures (clusters) for each network
	# Note: consider possible parameters of the executed algorithm, embedded into the dir names with _seppars
	basename, ishuf = os.path.splitext(task)  # Separate shuffling index if present
	evalname = 'mod'
	evaluated = False
	#clsbase = ''.join((_resdir, algname, '/', task))
	print('netfile: {}, basename: {}'.format(netfile, basename))
	iisep = len(_resdir) + len(algname) + 1 + len(basename)  # Inex of the possible instance symbol
	for clsbase in glob.iglob(''.join((_resdir, algname, '/', basename, '*', ishuf))):
		# Skip instances different from the basename
		if clsbase[iisep] == _sepinst:
			continue
		evaluated = True
		# Note: separate dir is created, because modularity is evaluated for all files in the target dir,
		# which are different granularity / hierarchy levels
		logsdir = ''.join((clsbase, '_', evalname, '/'))
		if not os.path.exists(logsdir):
			os.makedirs(logsdir)

		# Traverse over all resulting communities for each ground truth, log results
		tmodname = ''.join((clsbase, '_', algname, _extmod))  # Name of the file with modularity values for each level
		jobsinfo = []
		for cfile in glob.iglob(clsbase + '/*'):
			#print('Checking ' + cfile)
			# Extract base name of the evaluating level
			taskex = os.path.splitext(os.path.split(cfile)[1])[0]
			assert taskex, 'The clusters name should exists'
			# Processing is performed from the algorithms dir
			args = ('./hirecs', '-e=../' + cfile, '../' + netfile)
			#print('> Executing: ' + ' '.join(args))

			#raise AssertionError('Checkpoint, taskex: ' + taskex)
			# Job postprocessing
			def postexec(job):
				"""Copy final modularity output to the separate file"""
				with open(tmodname, 'a') as tmod:  # Append to the end
					subprocess.call(''.join(('tail -n 1 "', job.stderr, '" ', "| sed 's/.* mod: \\([^,]*\\).*/\\1\\t{}/'"
						# Add task name as part of the filename considering redundant prefix in GANXiS
						.format(job.name.lstrip(evalname + '_').rstrip('_' + algname).split('_', 2)[-1]))), stdout=tmod, shell=True)
				# Accuulate all results by the last task of the job ----------------
				# Check number of completed jobs
				processing = False
				skip = False  # If more than one task is executed, skip accumulative statistics evaluation
				for jobexec in jobsinfo:
					if not jobexec.value:
						if skip:
							processing = True
							break
						skip = True
				if processing:
					return
				# Find the highest value of modularity from the accumulated one and store it in the
				# acc file for all networks
				# Sort the task acc mod file and accumulate the largest value to the totall acc mod file
				# Note: here full path is required
				amodname = ''.join((_algsdir, _resdir, algname, _extmod))  # Name of the file with accumulated modularity
				if not os.path.exists(amodname):
					with open(amodname, 'a') as amod:
						amod.write('# Network\tQ\tTask\n')
				with open(amodname, 'a') as amod:  # Append to the end
					subprocess.call(''.join(('printf "', task, '\t `sort -g -r "', tmodname,'" | head -n 1`\n"')), stdout=amod, shell=True)

			job = Job(name='_'.join((evalname, taskex, algname)), workdir=_algsdir, args=args
				, timeout=timeout, ondone=postexec, stdout=os.devnull, stderr=''.join((logsdir, taskex, _extlog)))
			jobsinfo.append(job.executed)
			execpool.execute(job)
	if not evaluated:
		print('WARNING clusters "{}" do not exist from "{}"'.format(task, algname), file=sys.stderr)


# Louvain
## Original Louvain
#def execLouvain(execpool, netfile, asym, timeout, tasknum=0, **kwargs):
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
#def evalLouvain(execpool, cnlfile, timeout):
#	return


def execLouvain_ig(execpool, netfile, asym, timeout, selfexec=False, **kwargs):
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
	taskpath = ''.join((_resdir, algname, '/', task))

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
	#	for netfile in glob.iglob(''.join((netdir, task, '/*', netext))):
	#		execLouvain_ig(execpool, netfile, asym, timeout, selfexec)
	#		execnum += 1
	return execnum


def evalLouvain_ig(execpool, cnlfile, timeout):
	#print('Applying {} to {}'.format('louvain_igraph', cnlfile))
	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph')


def evalLouvain_igNS(execpool, cnlfile, timeout):
	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph', evalbin='./onmi_sum', evalname='nmi-s')


def modLouvain_ig(execpool, netfile, timeout):
	modAlgorithm(execpool, netfile, timeout, 'louvain_igraph')


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, timeout, **kwargs):
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
		taskbase, extshuf = os.path.splitext(task)
		ktask = ''.join((taskbase, _seppars, kstrex, extshuf))
		# Backup previous results if exist
		taskpath = ''.join((_resdir, algname, '/', ktask))

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


def evalScp(execpool, cnlfile, timeout):
	#print('Applying {} to {}'.format('louvain_igraph', cnlfile))
	evalAlgorithm(execpool, cnlfile, timeout, 'scp')


def evalScpNS(execpool, cnlfile, timeout):
	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'scp', evalbin='./onmi_sum', evalname='nmi-s')


def modScp(execpool, netfile, timeout):
	modAlgorithm(execpool, netfile, timeout, 'scp')


# Random Disjoing Clustering
def execRandcommuns(execpool, netfile, asym, timeout, selfexec=False, instances=5, **kwargs):  # _netshuffles + 1
	"""Execute Randcommuns
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
	taskpath = ''.join((_resdir, algname, '/', task))

	preparePath(taskpath)

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, pyexec, ''.join(('./', algname, '.py')), ''.join(('-g=../', netfile, _extclnodes))
		, ''.join(('-i=../', netfile, netext)), ''.join(('-o=../', taskpath))
		, ''.join(('-n=', str(instances))))
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout
		, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def evalRandcommuns(execpool, cnlfile, timeout):
	#print('Applying {} to {}'.format('randcommuns', cnlfile))
	evalAlgorithm(execpool, cnlfile, timeout, 'randcommuns')


def evalRandcommunsNS(execpool, cnlfile, timeout):
	"""Evaluate Randcommuns by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'randcommuns', evalbin='./onmi_sum', evalname='nmi-s')


def modRandcommuns(execpool, netfile, timeout):
	modAlgorithm(execpool, netfile, timeout, 'randcommuns')


# HiReCS
def execHirecs(execpool, netfile, asym, timeout, **kwargs):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecs'
	taskpath = ''.join((_resdir, algname, '/', task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cls=../', taskpath, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def evalHirecs(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs')


def evalHirecsNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs', evalbin='./onmi_sum', evalname='nmi-s')


#def modHirecs(execpool, netfile, timeout):
#	modAlgorithm(execpool, netfile, timeout, 'hirecs')


def execHirecsOtl(execpool, netfile, asym, timeout, **kwargs):
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
	taskpath = ''.join((_resdir, algname, '/', task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cols=../', taskpath, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def evalHirecsOtl(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsotl')


def evalHirecsOtlNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsotl', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsAhOtl(execpool, netfile, asym, timeout, **kwargs):
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
	taskpath = ''.join((_resdir, algname, '/', task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-coas=../', taskpath, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _extlog))
	return 1


def evalHirecsAhOtl(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsahotl')


def evalHirecsAhOtlNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsahotl', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsNounwrap(execpool, netfile, asym, timeout, **kwargs):
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
	taskpath = ''.join((_resdir, algname, '/', task))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _resdir, algname, _extexectime)), '-n=' + task, '-s=/etime_' + algname
		, './hirecs', '-oc', '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((taskpath, '.hoc'))
		, stderr=taskpath + _extlog))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, timeout, **kwargs):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.split(netfile)[1]  # Base name of the network
	task, netext = os.path.splitext(task)
	assert task, 'The network name should exists'

	algname = 'oslom2'
	taskpath = ''.join((_resdir, algname, '/', task))
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
		for fname in glob.iglob(origResDir +'tp*'):
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


def evalOslom2(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2')


def evalOslom2NS(execpool, cnlfile, timeout):
	"""Evaluate Oslom2 by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2', evalbin='./onmi_sum', evalname='nmi-s')


def modOslom2(execpool, netfile, timeout):
	modAlgorithm(execpool, netfile, timeout, 'oslom2')


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, timeout, **kwargs):
	#print('> exec params:\n\texecpool: {}\n\tnetfile: {}\n\tasym: {}\n\ttimeout: {}'
	#	.format(execpool, netfile, asym, timeout))
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'ganxis'
	taskpath = ''.join((_resdir, algname, '/', task))
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


def evalGanxis(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis')


def evalGanxisNS(execpool, cnlfile, timeout):
	"""Evaluate Ganxis by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis', evalbin='./onmi_sum', evalname='nmi-s')


def modGanxis(execpool, netfile, timeout):
	modAlgorithm(execpool, netfile, timeout, 'ganxis')
