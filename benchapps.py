#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr: List of the clustering algorithms to be executed by the benchmark

	Execution function for each algorithm must be named: exec<Algname>

	def execAlgorithm(execpool, netfile, asym, timeout, pathid='', selfexec=False):
		Execute the algorithm (stub)

		execpool  - execution pool to perform execution of current task
		netfile  -  input network to be processed
		asym  - network links weights are assymetric (in/outbound weights can be different)
		timeout  - execution timeout for this task
		pathid  - path id of the net to distinguish nets with the same name located in different dirs.
			Note: pathid already pretended with the separator symbol
		selfexec  - current execution is the external or internal self call

		return  - number of executions

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-07
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import os
import shutil
import glob
#import subprocess
import sys
# Add algorithms modules
#sys.path.insert(0, 'algorithms')  # Note: this operation might lead to ambiguity on paths resolving

#from algorithms.louvain_igraph import louvain
#from algorithms.randcommuns import randcommuns
from execpool import *
from benchutils import *

from sys import executable as PYEXEC  # Full path to the current Python interpreter
from benchevals import _ALGSDIR
from benchevals import _RESDIR
from benchevals import _CLSDIR
from benchevals import _EXTERR
from benchevals import _EXTEXECTIME
from benchevals import _SEPINST

_EXTLOG = '.log'
_EXTCLNODES = '.cnl'  # Clusters (Communities) Nodes Lists
#_extmod = '.mod'
#_EXECNMI = './gecmi'  # Binary for NMI evaluation
_SEPPARS = '!'  # Network parameters separator, must be a char
## Note: '.' is used as network shuffles separator
##_netshuffles = 4  # Number of shuffles for each input network for Louvain_igraph (non determenistic algorithms)


def	preparePath(taskpath):
	"""Create the path if required, otherwise move existent data to backup.
	All itnstances and shuffles of each network are handled all together and only once,
	even on calling this function for each shuffle.
	NOTE: To process files starting with taskpath, it should not contain '/' in the end

	taskpath  - the path to be prepared
	"""
	# Backup existent files & dirs with such base only if this path exists and is not empty
	# ATTENTION: do not use basePathExists(taskpath) here to avoid movement to the backup
	# processing paths when xxx.mod.net is processed before the xxx.net (have the same base)
	if os.path.exists(taskpath) and not dirempty(taskpath):
		# Extract main task base name from instances, shuffles and params, and process them all together
		mainpath, name = os.path.split(taskpath)
		if name:
			# Extract name suffix, skipping the extension
			name = os.path.splitext(name)[0]
			# Find position of the separator symbol, considering that it can't be begin of the name
			pos = filter(lambda x: x >= 1, [name.rfind(c) for c in (_SEPINST, _SEPPARS)])  # Note: reverse direction to skip possible separator symbols in the name itself
			if pos:
				pos = min(pos)
				name = name[:pos]
			mainpath = '/'.join((mainpath, name))  # Note: reverse direction to skip possible separator symbols in the name itself
		# Extract endings of multiple instances
		parts = mainpath.rsplit(_SEPINST, 1)
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


# ATTENTION: this function should not be defined to not beight automatically executed
#def execAlgorithm(execpool, netfile, asym, timeout, pathid='', selfexec=False, **kwargs):
#	"""Execute the algorithm (stub)
#
#	execpool  - execution pool to perform execution of current task
#	netfile  -  input network to be processed
#	asym  - network links weights are assymetric (in/outbound weights can be different)
#	timeout  - execution timeout for this task
#	pathid  - path id of the net to distinguish nets with the same name located in different dirs.
#		Note: pathid already pretended with the separator symbol
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
#def execLouvain(execpool, netfile, asym, timeout, pathid='', tasknum=0):
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
#	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
#		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
#	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args
#		, timeout=timeout, stdout=''.join((_RESDIR, algname, '/', task, '.loc'))
#		, stderr=''.join((_RESDIR, algname, '/', task, _EXTLOG))))
#	return 1
#
#
#def evalLouvain(execpool, basefile, measure, timeout):
#	return


def execLouvain_ig(execpool, netfile, asym, timeout, pathid='', selfexec=False):
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
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

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
	#	accname = ''.join((_ALGSDIR, _RESDIR, algname, extres))
	#	with open(accname, 'a') as accres:  # Append to the end
	#		# TODO: Evaluate the average
	#		subprocess.call(('tail', '-n 1', taskpath + _EXTLOG), stdout=accres)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, 'python', ''.join(('./', algname, '.py')), ''.join(('-i=../', netfile, netext))
		, ''.join(('-ol=../', taskpath, _EXTCLNODES)))
	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout
		#, ondone=postexec
		, stdout=os.devnull, stderr=''.join((taskpath, _EXTLOG))))

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
#	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph', evalbin='./onmi_sum', evalname='nmi_s')
#
#
#def modLouvain_ig(execpool, netfile, timeout):
#	modAlgorithm(execpool, netfile, timeout, 'louvain_igraph')


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, timeout, pathid=''):
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
		ktask = ''.join((taskbasex, _SEPPARS, kstrex, taskshuf))
		# Backup previous results if exist
		taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, ktask, pathid))

		preparePath(taskpath)

		# ATTENTION: a single argument is k-clique size, specified later
		steps = '10'  # Use 10 levels in the hierarchy Ganxis
		resbase = ''.join(('../', taskpath, '/', ktask))  # Base name of the result
		# scp.py netname k [start_linksnum end__linksnum numberofevaluations] [weight]
		args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', ktask, pathid))
			, PYEXEC, ''.join(('./', algname, '.py')), '../' + netfile, kstr, steps, resbase + _EXTCLNODES)

		def tidy(job):
			"""Remove empty resulting folders"""
			# Note: GANXiS leaves empty ./output dir in the _ALGSDIR, which should be deleted
			path = os.path.split(job.args[-1])[0][3:]  # Skip '../' prefix
			if dirempty(path):
				os.rmdir(path)

		#print('> Starting job {} with args: {}'.format('_'.join((ktask, algname, kstrex)), args + [kstr]))
		execpool.execute(Job(name='/'.join((algname, ktask)), workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=tidy, stderr=taskpath + _EXTLOG))

	return kmax + 1 - kmin


def execRandcommuns(execpool, netfile, asym, timeout, pathid='', instances=5):  # _netshuffles + 1
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
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, PYEXEC, ''.join(('./', algname, '.py')), ''.join(('-g=../', netfile, _EXTCLNODES))
		, ''.join(('-i=../', netfile, netext)), ''.join(('-o=../', taskpath))
		, ''.join(('-n=', str(instances))))
	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout
		, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecs(execpool, netfile, asym, timeout, pathid=''):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecs'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cls=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsOtl(execpool, netfile, asym, timeout, pathid=''):
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
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cols=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsAhOtl(execpool, netfile, asym, timeout, pathid=''):
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
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-coas=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsNounwrap(execpool, netfile, asym, timeout, pathid=''):
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
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', '../' + netfile)
	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=''.join((taskpath, '.hoc'))
		, stderr=taskpath + _EXTLOG))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, timeout, pathid=''):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.split(netfile)[1]  # Base name of the network
	task, netext = os.path.splitext(task)
	assert task, 'The network name should exists'

	algname = 'oslom2'
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

	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout, ondone=postexec
		, stdout=taskpath + _EXTLOG, stderr=taskpath + _EXTERR))
	return 1


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, timeout, pathid=''):
	#print('> exec params:\n\texecpool: {}\n\tnetfile: {}\n\tasym: {}\n\ttimeout: {}'
	#	.format(execpool, netfile, asym, timeout))
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'ganxis'
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

	execpool.execute(Job(name='/'.join(( algname, task)), workdir=_ALGSDIR, args=args, timeout=timeout, ondone=tidy
		, stdout=taskpath + _EXTLOG, stderr=taskpath + _EXTERR))
	return 1
