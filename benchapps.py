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
from sys import executable as _pyexec  # Full path to the current Python interpreter

from algorithms.louvain_igraph import louvain
from algorithms.randcommuns import randcommuns
from benchcore import Job

from benchcore import _extexectime
from benchcore import _extclnodes
from benchcore import _netshuffles


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_algsdir = 'algorithms/'  # Default directory of the benchmarking algorithms
_logext = '.log'
_nmibin = './gecmi'  # Binary for NMI evaluation
_modext = '.mod'


def evalAlgorithm(execpool, cnlfile, timeout, algname, evalbin=_nmibin, evalname='nmi', stderr=os.devnull):
	"""Evaluate the algorithm by the specified measure

	execpool  - execution pool of worker processes
	cnlfile  - file name of clusters for each of which nodes are listed (clusters nodes lists file)
	timeout  - execution timeout, 0 - infinity
	algname  - the algorithm name that is evaluated
	evalbin  - file name of the evaluation binary
	evalname  - name of the evaluation measure
	stderr  - optional redifinition of the stderr channel: None - use default, os.devnull - skip
	"""
	assert execpool and cnlfile and algname and evalbin and evalname, "Parameters must be defined"
	# Fetch the task name and chose correct network filename
	task = os.path.split(os.path.splitext(cnlfile)[0])[1]  # Base name of the network
	assert task, 'The network name should exists'

	args = ('../exectime', ''.join(('-o=./', evalname,_extexectime)), ''.join(('-n=', task, '_', algname))
		, './eval.sh', evalbin, '../' + cnlfile, ''.join((algname, 'outp/', task)), algname, evalname)
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((evalname, task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', evalname, '_', task, _logext)), stderr=stderr))

	# Evaluate also shuffled networks if exists
	i = 0
	taskex = ''.join((task, '_', str(i)))
	while os.path.exists(''.join((_algsdir, algname, 'outp/', taskex))):
		args = ('../exectime', ''.join(('-o=./', evalname,_extexectime)), ''.join(('-n=', taskex, '_', algname))
			, './eval.sh', evalbin, '../' + cnlfile, ''.join((algname, 'outp/', taskex)), algname, evalname)
		#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
		execpool.execute(Job(name='_'.join((evalname, taskex, algname)), workdir=_algsdir, args=args
			, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', evalname, '_', taskex, _logext)), stderr=stderr))
		i += 1
		taskex = ''.join((task, '_', str(i)))


def modAlgorithm(execpool, nsafile, timeout, algname):  # , multirun=True
	"""Evaluate quality of the algorithm by modularity

	execpool  - execution pool of worker processes
	nsafile  - file name of the input network
	timeout  - execution timeout, 0 - infinity
	algname  - the algorithm name that is evaluated
	multirun  - evaluate also on the shuffled networks (is required for non-deterministic algorithms only)
	"""
	assert execpool and nsafile and algname, "Parameters must be defined"
	# Fetch the task name and chose correct network filename
	task = os.path.split(os.path.splitext(nsafile)[0])[1]  # Base name of the network
	assert task, 'The network name should exists'
	
	# Make dirs with mod logs
	# Directory of resulting community structures (clusters) for each network
	resdir = ''.join((_algsdir, algname, 'outp/'))
	clsbase = resdir + task
	if not os.path.exists(clsbase):
		print('WARNING clusters "{}" do not exist from "{}"'.format(task, algname), file=sys.stderr)
		return
	
	evalname = 'mod'
	logsdir = ''.join((clsbase, '_', evalname, '/'))
	if not os.path.exists(logsdir):
		os.makedirs(logsdir)
	
	# Traverse over all resulting communities for each ground truth, log results
	tmodname = ''.join((clsbase, '_', algname, _modext))  # Name of the file with accumulated modularity
	jobsinfo = []
	for cfile in glob.iglob(clsbase + '/*'):
		print('Checking ' + cfile)
		taskex = os.path.split(os.path.splitext(cfile)[0])[1]  # Base name of the network
		assert taskex, 'The clusters name should exists'
		args = ('./hirecs', '-e=../' + cfile, '../' + nsafile)
		#print('> Executing: ' + ' '.join(args))

		# Job postprocessing
		def postexec(job):
			"""Copy final modularity output to the separate file"""
			with open(tmodname, 'a') as tmod:  # Append to the end
				subprocess.call(''.join(('tail -n 1 "', job.stderr, '" ', r"| sed 's/.* mod: \([^,]*\).*/\1/'")), stdout=tmod, shell=True)
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
			amodname = ''.join((resdir, algname, _modext))  # Name of the file with accumulated modularity
			if not os.path.exists(amodname):
				with open(amodname, 'a') as amod:
					amod.write('<Network>\t<Q>\n')
			with open(amodname, 'a') as amod:  # Append to the end
				subprocess.call(''.join(('printf "', task, '\t `sort -g -r "', tmodname,'" | head -n 1`\n"')), stdout=amod, shell=True)

		#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
		job = Job(name='_'.join((evalname, taskex, algname)), workdir=_algsdir, args=args
			, timeout=timeout, ondone=postexec, stdout=os.devnull, stderr=''.join((logsdir, taskex, _logext)))
		jobsinfo.append(job.executed)
		execpool.execute(job)


def execAlgorithm(execpool, netfile, asym, timeout, selfexec=False):
	"""Execute the algorithm (stub)

	execpool  - execution pool to perform execution of current task
	netfile  -  input network to be processed
	asym  - network links weights are assymetric (in/outbound weights can be different)
	timeout  - execution timeout for this task
	selfexec=False  - current execution is the external or internal self call

	return  - number of executions
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	return 0


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
#	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
#		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
#	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
#	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
#		, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', task, '.loc'))
#		, stderr=''.join((_algsdir, algname, 'outp/', task, _logext))))
#	return 1
#
#
#def evalLouvain(execpool, cnlfile, timeout):
#	return


def execLouvain_ig(execpool, netfile, asym, timeout, selfexec=False):
	"""Execute Louvain
	Results are not stable => multiple execution is desirable.

	returns number of executions or None
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	#if tasknum:
	#	task = '_'.join((task, str(tasknum)))

	algname = 'louvain_igraph'
	# ./louvain_igraph.py -i=../syntnets/1K5.nsa -ol=louvain_igoutp/1K5/1K5.cnl
	logsbase = ''.join((_algsdir, algname, 'outp/', task))
	resext = '.acs'  # Louvain accum statistics
	if not selfexec:
		outpdir = ''.join((_algsdir, algname, 'outp/'))
		if not os.path.exists(outpdir):
			os.makedirs(outpdir)
		# Just erase the file of the accum results
		with open(logsbase + resext, 'w') as accres:
			accres.write('# Accumulated final results\n')

	def postexec(job):
		"""Copy final modularity output to the separate file"""
		# File name of the accumulated result
		accname = (logsbase[:logsbase.rfind('_')] if selfexec else logsbase) + resext
		with open(accname, 'a') as accres:  # Append to the end
			subprocess.call(('tail', '-n 1', logsbase + _logext), stdout=accres)

	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, _pyexec, ''.join(('./', algname, '.py')), ''.join(('-i=../', netfile, netext))
		, ''.join(('-ol=', algname, 'outp/', task, _extclnodes)))
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout
		, ondone=postexec, stdout=os.devnull, stderr=''.join((logsbase, _logext))))

	# Run again for all shuffled nets
	execnum = 0
	if not selfexec:
		selfexec = True
		netdir = os.path.split(netfile)[0]
		if not netdir.endswith('/'):
			netdir += '/'
		print('Netdir: ', netdir)
		for netfile in glob.iglob(''.join((netdir, task, '/*', netext))):
			execLouvain_ig(execpool, netfile, asym, timeout, selfexec)
			execnum += 1
	return execnum


def evalLouvain_ig(execpool, cnlfile, timeout):
	#print('Applying {} to {}'.format('louvain_igraph', cnlfile))
	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph')


def evalLouvain_igNS(execpool, cnlfile, timeout):
	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph', evalbin='./onmi_sum', evalname='nmi-s')


def modLouvain_ig(execpool, nsafile, timeout):
	modAlgorithm(execpool, nsafile, timeout, 'louvain_igraph')


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, timeout):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name
	task, netext = os.path.splitext(netfile)
	task = os.path.split(task)[1]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'scp'
	# ATTENTION: a single argument is k-clique size, specified later
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), ''.join(('-n=', task, '_{}'))
		, _pyexec, ''.join(('./', algname, '.py')), '../' + netfile, '{}')

	# Run again for k E [3, 12]
	resbase = ''.join((_algsdir, algname, 'outp/', task, '/', task, '_'))  # Base name of the result
	kmin = 3  # Min clique size to be used for the communities identificaiton
	kmax = 8  # Max clique size
	for k in range(kmin, kmax + 1):
		kstr = str(k)
		kstrex = 'k' + kstr
		#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
		#print('> Starting job {} with args: {}'.format('_'.join((task, algname, kstrex)), args + [kstr]))
		finargs = list(args)  # Copy args
		finargs[2] = finargs[2].format(kstrex)
		finargs[-1] = finargs[-1].format(kstr)
		execpool.execute(Job(name='_'.join((task, algname, kstrex)), workdir=_algsdir, args=finargs, timeout=timeout
			, stdout=''.join((resbase, kstrex, _extclnodes))
			, stderr=''.join((resbase, kstrex, _logext)) ))
	return kmax + 1 - kmin


def evalScp(execpool, cnlfile, timeout):
	#print('Applying {} to {}'.format('louvain_igraph', cnlfile))
	evalAlgorithm(execpool, cnlfile, timeout, 'scp')


def evalScpNS(execpool, cnlfile, timeout):
	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'scp', evalbin='./onmi_sum', evalname='nmi-s')


def modScp(execpool, nsafile, timeout):
	modAlgorithm(execpool, nsafile, timeout, 'scp')


# Random Disjoing Clustering
def execRandcommuns(execpool, netfile, asym, timeout, selfexec=False):
	"""Execute Randcommuns
	Results are not stable => multiple execution is desirable.
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'randcommuns'
	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, _pyexec, ''.join(('./', algname, '.py')), ''.join(('-g=../', netfile, _extclnodes))
		, ''.join(('-i=../', netfile, netext)), ''.join(('-o=', algname, 'outp/', task))
		, ''.join(('-n=', str(_netshuffles + 1))))
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout
		, stdout=os.devnull, stderr=''.join((_algsdir, algname, 'outp/', task, _logext))))
	return 1


def evalRandcommuns(execpool, cnlfile, timeout):
	#print('Applying {} to {}'.format('randcommuns', cnlfile))
	evalAlgorithm(execpool, cnlfile, timeout, 'randcommuns')


def evalRandcommunsNS(execpool, cnlfile, timeout):
	"""Evaluate Randcommuns by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'randcommuns', evalbin='./onmi_sum', evalname='nmi-s')


def modRandcommuns(execpool, nsafile, timeout):
	modAlgorithm(execpool, nsafile, timeout, 'randcommuns')


# HiReCS
def execHirecs(execpool, netfile, asym, timeout):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format

	algname = 'hirecs'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './hirecs', '-oc', ''.join(('-cls=./', algname, 'outp/', task, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=''.join((_algsdir, algname, 'outp/', task, _logext))))
	return 1


def evalHirecs(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs')


def evalHirecsNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs', evalbin='./onmi_sum', evalname='nmi-s')


#def modHirecs(execpool, nsafile, timeout):
#	modAlgorithm(execpool, nsafile, timeout, 'hirecs')


def execHirecsOtl(execpool, netfile, asym, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format

	algname = 'hirecsotl'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './hirecs', '-oc', ''.join(('-cols=./', algname, 'outp/', task, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=''.join((_algsdir, algname, 'outp/', task, _logext))))
	return 1


def evalHirecsOtl(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsotl')


def evalHirecsOtlNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsotl', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsAhOtl(execpool, netfile, asym, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format

	algname = 'hirecsahotl'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './hirecs', '-oc', ''.join(('-coas=./', algname, 'outp/', task, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=os.devnull, stderr=''.join((_algsdir, algname, 'outp/', task, _logext))))
	return 1


def evalHirecsAhOtl(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsahotl')


def evalHirecsAhOtlNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsahotl', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsNounwrap(execpool, netfile, asym, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format

	algname = 'hirecshfold'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './hirecs', '-oc', '../' + netfile)
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', task, '.hoc'))
		, stderr=''.join((_algsdir, algname, 'outp/', task, _logext))))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, timeout):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name
	task, netext = os.path.splitext(netfile)
	task = os.path.split(task)[1]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'oslom2'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './oslom_undir', '-f', '../' + netfile, '-w')
	# Copy results to the required dir on postprocessing
	logsdir = ''.join((_algsdir, algname, 'outp/'))
	netdir = os.path.split(netfile)[0]
	if not netdir.endswith('/'):
		netdir += '/'
	def postexec(job):
		# Copy communities output
		outpdir = ''.join((logsdir, task, '/'))
		if not os.path.exists(outpdir):
			os.makedirs(outpdir)
		for fname in glob.iglob(''.join((netdir, task, netext, '_oslo_files/tp*'))):
			shutil.copy2(fname, outpdir)
		# Move dir
		outpdire = ''.join((logsdir, 'extra/'))
		if not os.path.exists(outpdire):
			os.makedirs(outpdire)
		for dname in glob.iglob(''.join((netdir, task, netext, '_oslo_files/'))):
			shutil.move(dname, outpdire)

	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
		, stdout=''.join((logsdir, task, _logext)), stderr=''.join((logsdir, task, '.err'))))
	return 1


def evalOslom2(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2')


def evalOslom2NS(execpool, cnlfile, timeout):
	"""Evaluate Oslom2 by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2', evalbin='./onmi_sum', evalname='nmi-s')


def modOslom2(execpool, nsafile, timeout):
	modAlgorithm(execpool, nsafile, timeout, 'oslom2')


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, timeout):
	#print('> exec params:\n\texecpool: {}\n\tnetfile: {}\n\tasym: {}\n\ttimeout: {}'
	#	.format(execpool, netfile, asym, timeout))
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and isinstance(timeout, int), 'Invalid params'
	# Fetch the task name
	task = os.path.split(os.path.splitext(netfile)[0])[1]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'ganxis'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, 'java', '-jar', './GANXiSw.jar', '-i', '../' + netfile, '-d', algname + 'outp/')
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None)
	logsdir = ''.join((_algsdir, algname, 'outp/'))
	def postexec(job):
		outpdir = ''.join((logsdir, task, '/'))
		if not os.path.exists(outpdir):
			os.mkdir(outpdir)
		for fname in glob.iglob(''.join((logsdir, 'SLPAw_', task, '_run*.icpm'))):
			shutil.move(fname, outpdir)

	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
		, stdout=''.join((logsdir, task, _logext)), stderr=''.join((logsdir, task, '.err'))))
	return 1


def evalGanxis(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis')


def evalGanxisNS(execpool, cnlfile, timeout):
	"""Evaluate Ganxis by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis', evalbin='./onmi_sum', evalname='nmi-s')


def modGanxis(execpool, nsafile, timeout):
	modAlgorithm(execpool, nsafile, timeout, 'ganxis')
