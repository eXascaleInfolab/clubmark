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

import os
import shutil
import glob
import subprocess

# Add algorithms modules
import sys
sys.path.insert(0, 'algorithms')
from louvain_igraph import louvain
from randcommuns import randcommuns
from benchcore import Job

from benchcore import _syntdir
from benchcore import _extexectime
from benchcore import _extclnodes


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_algsdir = 'algorithms/'  # Default directory of the benchmarking algorithms
_logext = '.log'
_nmibin = './gecmi'  # Binary for NMI evaluation


def evalAlgorithm(execpool, cnlfile, timeout, algname, evalbin=_nmibin, evalname='nmi', stderr=os.devnull):
	"""Evaluate the algorithm by the specified measure
	
	execpool  - execution pool of worker processes
	cnlfile  - file name of clusters for each of which nodes are listed (clsuters nodes lists file)
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


# Louvain
## Original Louvain
#def execLouvain(execpool, netfile, timeout, tasknum=0):
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
#
#
#def evalLouvain(execpool, cnlfile, timeout):
#	return


## Igraph implementation of the Louvain
#	# Fetch the task name
#	task = os.path.split(os.path.splitext(netfile)[0])[1]  # Base name of the network
#	assert task, 'The network name should exists'
#	
#	algname = 'oslom2'
#	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
#		, './oslom_undir', '-f', '../' + netfile, '-w')
#	# Copy results to the required dir on postprocessing
#	logsdir = ''.join((_algsdir, algname, 'outp/'))
#	def postexec(job):
#		outpdir = ''.join((logsdir, task, '/'))
#		if not os.path.exists(outpdir):
#			os.makedirs(outpdir)
#		for fname in glob.iglob(''.join((_syntdir, task, '.nsa', '_oslo_files/tp*'))):
#			shutil.copy2(fname, outpdir)
#		
#	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None)
#	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
#		, stdout=''.join((logsdir, task, _logext)), stderr=''.join((logsdir, task, '.err'))))
def execLouvain_ig(execpool, netfile, timeout, selfexec=False):
	"""Execute Louvain
	Results are not stable => multiple execution is desirable.
	"""
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	#if tasknum:
	#	task = '_'.join((task, str(tasknum)))
	
	algname = 'louvain_igraph'
	# ./louvain_igraph.py -i=../syntnets/1K5.nsa -ol=louvain_igoutp/1K5/1K5.cnl
	pyexec = 'python'
	#with open(os.devnull, 'w') as fotmp:
	#	pyexec = 'pypy' if subprocess.call(['which', 'pypy'], stdout=fotmp) == 0 else 'python'
	
	logsbase = ''.join((_algsdir, algname, 'outp/', task))
	resext = '.las'  # Louvain accum statistics
	if not selfexec:
		# Just erase the file of the accum results
		with open(logsbase + resext, 'w') as accres:
			accres.write('# Accumulated final results\n')

	def postexec(job):
		"""Copy final modularity output to the separate file"""
		# File name of the accumulated result
		accname = (logsbase[:logsbase.rfind('_')] if selfexec else logsbase) + resext
		with open(accname, 'a') as accres:  # Append to the end
			subprocess.call(['tail', '-n 1', logsbase + _logext], stdout=accres)

	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, pyexec, ''.join(('./', algname, '.py')), ''.join(('-i=../', netfile, netext))
		, ''.join(('-ol=', algname, 'outp/', task, _extclnodes)))
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout
		, ondone=postexec, stdout=os.devnull, stderr=''.join((logsbase, _logext))))
	
	# Run again for all shuffled nets
	if not selfexec:
		selfexec = True
		for netfile in glob.iglob(''.join((_syntdir, task, '/*', netext))):
			execLouvain_ig(execpool, netfile, timeout, selfexec)
			

def evalLouvain_ig(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph')
			

def evalLouvain_igNS(execpool, cnlfile, timeout):
	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph', evalbin='./onmi_sum', evalname='nmi-s')


# Random Disjoing Clustering



# HiReCS
def execHirecs(execpool, netfile, timeout):
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


def evalHirecs(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs')


def evalHirecsNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsOtl(execpool, netfile, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
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


def evalHirecsOtl(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsotl')


def evalHirecsOtlNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsotl', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsAhOtl(execpool, netfile, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
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


def evalHirecsAhOtl(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsahotl')


def evalHirecsAhOtlNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecsahotl', evalbin='./onmi_sum', evalname='nmi-s')


def execHirecsNounwrap(execpool, netfile, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
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


# Oslom2
def execOslom2(execpool, netfile, timeout):
	# Fetch the task name
	task, netext = os.path.splitext(netfile)
	task = os.path.split(task)[1]  # Base name of the network
	assert task, 'The network name should exists'
	
	algname = 'oslom2'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './oslom_undir', '-f', '../' + netfile, '-w')
	# Copy results to the required dir on postprocessing
	logsdir = ''.join((_algsdir, algname, 'outp/'))
	def postexec(job):
		# Copy communities output
		outpdir = ''.join((logsdir, task, '/'))
		if not os.path.exists(outpdir):
			os.makedirs(outpdir)
		for fname in glob.iglob(''.join((_syntdir, task, netext, '_oslo_files/tp*'))):
			shutil.copy2(fname, outpdir)
		# Move dir
		outpdire = ''.join((logsdir, 'extra/'))
		if not os.path.exists(outpdire):
			os.makedirs(outpdire)
		for dname in glob.iglob(''.join((_syntdir, task, netext, '_oslo_files/'))):
			shutil.move(dname, outpdire)
		
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
		, stdout=''.join((logsdir, task, _logext)), stderr=''.join((logsdir, task, '.err'))))


def evalOslom2(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2')


def evalOslom2NS(execpool, cnlfile, timeout):
	"""Evaluate Oslom2 by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2', evalbin='./onmi_sum', evalname='nmi-s')


# Ganxis (SLPA)
def execGanxis(execpool, netfile, timeout):
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


def evalGanxis(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis')


def evalGanxisNS(execpool, cnlfile, timeout):
	"""Evaluate Ganxis by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis', evalbin='./onmi_sum', evalname='nmi-s')
