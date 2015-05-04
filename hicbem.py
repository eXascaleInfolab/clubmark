#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: Overlapping Hierarhical Clusterig Benchmark

# Generates synthetic datasets for reusing
# https://sites.google.com/site/santofortunato/inthepress2
# "Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti 1 and Santo Fortunato

Runs hierarchical clustering algorithms on the synthetic networks and real-word datasets

(c) 
\author: Artem Lutov <artem@exascale.info>
\organizations: eXascale lab <http://exascale.info/>, ScienceWise <http://sciencewise.info/>, Lumais <http://www.lumais.com/>
\date: 2015-04
"""

from __future__ import print_function
import sys
import time
import subprocess
#from functools import wraps
import os
from math import sqrt


# Note: '/' is required in the end of the dir to evaluate whether it is already exists and distinguish it from the file
_syntdir = './syntnets/'  # Default directory for the synthetic generated datasets

_jobs = []  # Executing jobs
_jobsLimit = 1  # Max number of concurently executing jobs


def parseParams(args):
	"""Parse user-specified parameters
	
	return
		gensynt  - generate synthetic networks:
			0 - do not generate
			1 - generate only if this network is not exists
			2 - force geration (overwrite all)
		udatas  - list of unweighted datasets to be run
		wdatas  - list of weighted datasets to be run
		timeout  - execution timeout in sec per each algorithm
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	gensynt = 0
	udatas = []
	wdatas = []
	timeout = 0
	sparam = False  # Additional string parameter
	weighted = False
	timemul = 1  # Time multiplier, sec by default
	for arg in args:
		# Validate input format
		if (arg[0] != '-') != bool(sparam) or (len(arg) < 2 if arg[0] == '-' else arg in '..'):
			raise ValueError(''.join(('Unexpected argument'
				, ', file/dir name is expected: ' if sparam else ': ', arg)))
		
		if arg[0] == '-':
			if arg[1] == 'g':
				if arg not in '-gf':
					raise ValueError('Unexpected argument: ' + arg)
				gensynt = len(arg) - 1  # '-gf'  - forced generation (overwrite)
			elif arg[1] == 'd' or arg[1] == 'f':
				weighted = False
				sparam = 'd'  # Dataset
				if len(arg) >= 3:
					if arg[2] not in 'uw' or len(arg) > 3:
						raise ValueError('Unexpected argument: ' + arg)
					weighted = arg[2] == 'w'
			elif arg[1] == 't':
				sparam = 't'  # Time
				if len(arg) >= 3:
					if arg[2] not in 'smh' or len(arg) > 3:
						raise ValueError('Unexpected argument: ' + arg)
					if arg[2] == 'm':
						timemul = 60  # Minutes
					elif arg[2] == 'h':
						timemul = 3600  # Hours
			else:
				raise ValueError('Unexpected argument: ' + arg)
		else:
			assert sparam in 'dt', "sparam should be either dataset file/dir or time"
			if sparam == 'd':
				(wdatas if weighted else udatas).append(arg)
			elif sparam == 't':
				timeout = int(arg) * timemul
			else:
				raise RuntimeError('Unexpected value of sparam: ' + sparam)
			sparam = False
	
	return gensynt, udatas, wdatas, timeout


def secondsToHms(seconds):
	"""Convert seconds to hours, mins, secs
	
	seconds  - seconds to be converted
	
	return hours, mins, secs
	"""
	hours = int(seconds / 3600)
	mins = int((seconds - hours * 3600) / 60)
	secs = seconds - hours * 3600 - mins * 60
	return hours, mins, secs
	

def controlExecTime(proc, algname, exectime, timeout):
	"""Conterol the time of the process execution
	
	Evaluate execution time and kills the process after the specified timeout
	if required.
	
	proc  - active executing process
	algname  - name of the executing algorithm
	exectime  - start time of the execution
	timeout  - execution timeout, 0 means infinity
	"""
	_jobs
	print('controlExecTime started, timeout: ' + str(timeout))
	while proc.poll() is None:
		time.sleep(1)
		if timeout and time.time() - exectime > timeout:
			exectime = time.time() - exectime
			proc.terminate()
			# Wait a few sec for the successful process termitaion before killing it
			i = 0
			while proc.poll() is None and i < 5:
				i += 1
				time.sleep(1)
			if proc.poll() is None:
				proc.kill()
			print('{} is terminated by the timeout ({} sec): {} sec ({} h {} m {} s)'
				.format(algname, timeout, exectime, *secondsToHms(exectime)))


def execJob(jname, workdir, args, timeout, tracelev=2):
	"""Execute specified job
	
	jname  - job name (id)
	workdir  - working directory
	args  - execution arguments including the executable itself
	timeout  - execution timeout
	tracelev  - tracing detalizationg level:
		0  - no tracing
		1  - trace to stdout only
		2  - trace to stderr only. Default
		3  - trace to both stdout and stderr
	"""
	assert jname and workdir and args, ""
	
	# Execution block
	if tracelev & 2:
		print(jname + ' is starting...', file=sys.stderr)
	if tracelev & 1:
		print(jname + ' is starting...')

	exectime = time.time()
	try:
		proc = subprocess.Popen(args, cwd=workdir)  # bufsize=-1 - use system default IO buffer size
	except StandardError as err:  # Should not occur: subprocess.CalledProcessError
		print('ERROR on {} execution occurred: {}'.format(jname, err))
	else:
		controlExecTime(proc, jname, exectime, timeout)

	exectime = time.time() - exectime
	if tracelev & 2:
		print('{} is finished on {} sec ({} h {} m {} s).\n'
			.format(jname, exectime, *secondsToHms(exectime)), file=sys.stderr)
	if tracelev & 1:
		print('{} is finished on {} sec ({} h {} m {} s).\n\n'
			.format(jname, exectime, *secondsToHms(exectime)))
		 

def generateNets(overwrite=False):
	"""Generate synthetic networks with ground-truth communities and save generation params
	
	overwrite  - whether to overwrite existing networks or use them
	"""
	paramsdir = 'params/'
	
	assert _syntdir[-1] == '/' and paramsdir[-1] == '/', "Directory name must have valid terminator"
	paramsDirFull = _syntdir + paramsdir
	if not os.path.exists(paramsDirFull):
		os.makedirs(paramsDirFull)
	# Initial options for the networks generation
	N0 = 1000;  # Satrting number of nodes
	
	evalmaxk = lambda genopts: round(sqrt(genopts['N']))
	evalmuw = lambda genopts: genopts['mut'] * 2/3
	evalminc = lambda genopts: 5 + int(genopts['N'] / N0)
	evalmaxc = lambda genopts: int(genopts['N'] / 3)
	evalon = lambda genopts: int(genopts['N'] * genopts['mut']**2)
	# Template of the generating options files
	genopts = {'mut': 0.275, 'beta': 1.35, 't1': 1.65, 't2': 1.3, 'om': 2, 'cnd': 1}
	
	# Generate options for the networks generation using chosen variations of params
	varNmul = (1, 2, 5, 10, 25, 50)  # *N0
	vark = (5, 10, 20)
	
	for nm in varNmul:
		N = nm * N0
		for k in vark:
			fname = ''.join((str(nm), 'K', str(k), '.ngp'))
			if not overwrite and os.path.exists(fname):
				continue
			print('Generating {} parameters file...'.format(fname))
			with open(paramsDirFull + fname, 'w') as fout:
				genopts.update({'N': N, 'k': k})
				genopts.update({'maxk': evalmaxk(genopts), 'muw': evalmuw(genopts), 'minc': evalminc(genopts)
					, 'maxc': evalmaxc(genopts), 'on': evalon(genopts)})
				for opt in genopts.items():
					fout.write(''.join(('-', opt[0], ' ', str(opt[1]), '\n')))
	print('Parameters files generation is completed')
	
	# Generate the networks with ground truth
	#_jobsLimit = 4
	#_workers
	


def execLouvain(udatas, wdatas, timeout):
	return
	# TODO: add URL to the alg src
	algname = 'Louvain'
	workdir = 'LouvainUpd'

	# Preparation block
	#...

	args = ['../exectime', 'ls']
	execJob(algname, workdir, args, timeout)

	# Postprocessing block
	#...


def execHirecs(udatas, wdatas, timeout):
	return
	# TODO: add URL to the alg src
	algname = 'HiReCS'
	workdir = '.'
	args = ['./exectime', 'top']
	timeout = 3
	execJob(algname, workdir, args, timeout)


def execOslom2(udatas, wdatas, timeout):
	algname = 'OSLOM2'
	workdir = 'OSLOM2'
	for udata in udatas:
		fname = udata
		ifn = fname.rfind('/')
		if ifn != -1:
			fname = fname[ifn + 1:]
		args = ['../exectime', ''.join(('-o=', fname, '_', algname.lower(), '.rst')), './oslom_undir', '-f', udata, '-uw']
		execJob(algname, workdir, args, timeout)


def execGanxis(udatas, wdatas, timeout):
	algname = 'GANXiS'
	workdir = 'GANXiS_v3.0.2'
	for udata in udatas:
		fname = udata
		ifn = fname.rfind('/')
		if ifn != -1:
			fname = fname[ifn + 1:]
		args = ['../exectime', ''.join(('-o=', fname, '_', algname.lower(), '.rst')), 'java', '-jar', './GANXiSw.jar', '-i', udata, '-Sym 1']
		execJob(algname, workdir, args, timeout)


def benchmark(*args):
	""" Execute the benchmark:
	Run the algorithms on the specified datasets respecting the parameters
	"""
	exectime = time.time()
	gensynt, udatas, wdatas, timeout = parseParams(args)
	if gensynt:
		generateNets(gensynt == 2)
	
	raise RuntimeError('Stop')
		
	print("Parsed params:\n\tudatas: {}, \n\twdatas: {}\n\ttimeout: {}"
		.format(', '.join(udatas), ', '.join(wdatas), timeout))
	
	udatas = ['../snap/com-dblp.ungraph.txt', '../snap/com-amazon.ungraph.txt', '../snap/com-youtube.ungraph.txt']
	algors = (execLouvain, execHirecs, execOslom2, execGanxis)
	try:
		#algtime = time.time()
		for alg in algors:
			alg(udatas, wdatas, timeout)
	except StandardError as err:
		print('The benchmark is interrupted by the exception: {} on {} sec ({} h {} m {} s)'
			.format(err, exectime, *secondsToHms(exectime)))
	else:
		exectime = time.time() - exectime
		print('The benchmark execution is successfully comleted on {} sec ({} h {} m {} s)'
			.format(exectime, *secondsToHms(exectime)))


if __name__ == '__main__':
	if len(sys.argv) > 1:
		benchmark(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} [-g[f] | [-d{{u,w}} <datasets_dir>] [-f{{u,w}} <dataset>] [-t[{{s,m,h}}] <timeout>]',
			'  -g[f]  - generate synthetic daatasets in the {syntdir}',
			'    Xf  - force the generation even when the data is already exists',
			'  -d[X] <datasets_dir>  - directory of the datasets',
			'  -f[X] <dataset>  - dataset file name',
			'    Xu  - the dataset is unweighted. Default option',
			'    Xw  - the dataset is weighted',
			'    Notes:',
			'    - multiple directories and files can be specified',
			'    - datasets should have the following format: <node_src> <node_dest> [<weight>]',
			'  -t[X] <number>  - specifies timeout per an algorithm in sec, min or hours. Default: 0 sec',
			'    Xs  - time in seconds. Default option',
			'    Xm  - time in minutes',
			'    Xh  - time in hours',
			))
			.format(sys.argv[0], syntdir=_syntdir))