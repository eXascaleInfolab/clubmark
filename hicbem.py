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
from multiprocessing import cpu_count
import collections
import os
import shutil
from math import sqrt
import glob
import pajek_hig  # TODO: rename into the tohig.py or etc.
#from functools import wraps


# Note: '/' is required in the end of the dir to evaluate whether it is already exists and distinguish it from the file
_syntdir = 'syntnets/'  # Default directory for the synthetic generated datasets
_algsdir = 'algorithms/'  # Default directory of the benchmarking algorithms
_extnetfile = '.nsa'  # Extension of the network files to be executed by the algorithms
_extexectime = '.rcp'  # Resource Consumption Profile
_extclnodes = '.cnl'  # Clusters (Communities) Nodes Lists
_nmibin = './gecmi'  # BInary for NMI evaluation


def parseParams(args):
	"""Parse user-specified parameters
	
	return
		gensynt  - generate synthetic networks:
			0 - do not generate
			1 - generate only if this network is not exists
			2 - force geration (overwrite all)
		convnets  - convert existing networks into the .hig format
		udatas  - list of unweighted datasets to be run
		wdatas  - list of weighted datasets to be run
		timeout  - execution timeout in sec per each algorithm
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	gensynt = 0
	convnets = False
	runalgs = False
	evalres = False
	udatas = []
	wdatas = []
	timeout = 36 * 60*60  # 36 hours
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
			elif arg[1] == 'c':
				if arg != '-c':
					raise ValueError('Unexpected argument: ' + arg)
				convnets = True
			elif arg[1] == 'r':
				if arg != '-r':
					raise ValueError('Unexpected argument: ' + arg)
				runalgs = True
			elif arg[1] == 'e':
				if arg != '-e':
					raise ValueError('Unexpected argument: ' + arg)
				evalres = True
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
	
	return gensynt, convnets, runalgs, evalres, udatas, wdatas, timeout


def secondsToHms(seconds):
	"""Convert seconds to hours, mins, secs
	
	seconds  - seconds to be converted
	
	return hours, mins, secs
	"""
	hours = int(seconds / 3600)
	mins = int((seconds - hours * 3600) / 60)
	secs = seconds - hours * 3600 - mins * 60
	return hours, mins, secs


class Job:
#class Job(collections.namedtuple('Job', ('name', 'workdir', 'args', 'timeout', 'ontimeout', 'onstart', 'ondone', 'tstart'))):  # , 'tracelev'
	#Job = collections.namedtuple('Job', ('name', 'workdir', 'args', 'timeout', 'ontimeout', 'onstart', 'ondone', 'tstart'))
	#tracelev  - tracing detalizationg level:
	#	0  - no tracing
	#	1  - trace to stdout only
	#	2  - trace to stderr only. Default
	#	3  - trace to both stdout and stderr
	#def __new__(cls, name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None):
	#	assert name, "Job parameters must be defined"  #  and job.workdir and job.args
	#	return super(Job, cls).__new__(cls, name, workdir, args, timeout, ontimeout, onstart, ondone, tstart)
	def __init__(self, name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None):
		"""The job to be executed
		
		name  - job name
		workdir  - working directory for the corresponding process
		args  - execution arguments including the executable itself for the process
		timeout  - execution timeout. Default: 0, means infinity
		ontimeout  - action on timeout:
			0  - terminate the job. Default
			1  - restart the job
		onstart  - callback which is executed on the job starting in the CONTEXT OF
			THE CALLER (main process) with the single argument, the job. Default: None
		ondone  - callback which is executed on successful completion of the job in the
			CONTEXT OF THE CALLER (main process) with the single argument, the job. Default: None
			
		tstart  - start time is filled automatically on the execution start. Default: None
		"""
		assert name, "Job parameters must be defined"  #  and job.workdir and job.args
		self.name = name
		self.workdir = workdir
		self.args = args
		self.timeout = timeout
		self.ontimeout = ontimeout
		self.onstart = onstart
		self.ondone = ondone
		self.stdout = stdout
		self.stderr = stderr
		self.tstart = tstart


class ExecPool:
	'''Execution Pool of workers for jobs
	
	A worker in the pool executes only the one job, a new worker is created for
	each subsequent job.
	'''
	
	def __init__(self, workers=cpu_count()):
		assert workers >= 1, 'At least one worker should be managed by the pool'
		
		self._workersLim = workers  # Max number of workers
		self._workers = {}  # Current workers: 'jname': <proc>; <proc>: timeout
		self._jobs = collections.deque()  # Scheduled jobs: 'jname': **args
		self._tstart = None  # Start time of the execution of the first task


	def __del__(self):
		self.__terminate()
		
		
	def __terminate(self):
		"""Force termination of the pool"""
		if not self._jobs and not self._workers:
			return
		
		print('Terminating the workers pool ...')
		for job in self._jobs:
			print('Scheduled "{}" is removed'.format(job.name))
		self._jobs.clear()
		while self._workers:
			procs = self._workers.keys()
			for proc in procs:
				print('Terminating "{}" #{} ...'.format(self._workers[proc].name, proc.pid), file=sys.stderr)
				proc.terminate()
			# Wait a few sec for the successful process termitaion before killing it
			i = 0
			active = True
			while active and i < 3:
				active = False
				for proc in procs:
					if proc.poll() is None:
						active = True
						break
				time.sleep(1)
			# Kill nonterminated processes
			if active:
				for proc in procs:
					if proc.poll() is None:
						print('Killing the worker #{} ...'.format(proc.pid), file=sys.stderr)
						proc.kill()
			self._workers.clear()
			
			
	def __startJob(self, job):
		"""Start the specified job by one of workers
		
		job  - the job to be executed, instance of Job
		"""
		assert isinstance(job, Job), 'job must be a valid entity'
		if len(self._workers) > self._workersLim:
			raise AssertionError('Free workers must be available ({} busy workers of {})'
				.format(len(self._workers), self._workersLim))
		
		print('Starting "{}"...'.format(job.name), file=sys.stderr)
		job.tstart = time.time()
		if job.onstart:
			try:
				job.onstart(job)
			except Exception as err:
				print('ERROR in onstart callback of "{}": {}'.format(job.name, err), file=sys.stderr)
		# Consider custom output channels for the job
		fstdout = None
		fstderr = None
		try:
			if job.stdout:
				basedir = os.path.split(job.stdout)[0]
				if not os.path.exists(basedir):
					os.makedirs(basedir)
				try:
					fstdout = open(job.stdout, 'w')
				except IOError as err:
					print('ERROR on opening custom stdout "{}" for "{}": {}. Default stdout is used.'.format(
						job.stdout, job.name, err), file=sys.stderr)
			if job.stderr:
				basedir = os.path.split(job.stderr)[0]
				if not os.path.exists(basedir):
					os.makedirs(basedir)
				try:
					fstderr = open(job.stderr, 'w')
				except IOError as err:
					print('ERROR on opening custom stderr "{}" for "{}": {}. Default stderr is used.'.format(
						job.stderr, job.name, err), file=sys.stderr)
			if fstdout or fstderr:
				print('"{}" uses custom output channels:\n\tstdout: {}\n\tstderr: {}'.format(job.name
					, job.stdout if fstdout else '<default>', job.stderr if fstderr else '<default>'))
			proc = subprocess.Popen(job.args, cwd=job.workdir, stdout=fstdout, stderr=fstderr)  # bufsize=-1 - use system default IO buffer size
		except StandardError as err:  # Should not occur: subprocess.CalledProcessError
			if fstdout:
				fstdout.close()
			if fstderr:
				fstderr.close()
			print('ERROR on "{}" execution occurred: {}, skipping the job'.format(job.name, err), file=sys.stderr)
		else:
			self._workers[proc] = job


	def __reviseWorkers(self):
		"""Rewise the workers
		
		Check for the comleted jobs and their timeous, update corresponding
		workers and start the jobs if possible
		"""
		completed = []  # Completed workers
		for proc, job in self._workers.items():
			if proc.poll() is not None:
				completed.append((proc, job))
				continue
			exectime = time.time() - job.tstart
			if not job.timeout or exectime < job.timeout:
				continue
			# Terminate the worker
			proc.terminate()
			# Wait a few sec for the successful process termitaion before killing it
			i = 0
			while proc.poll() is None and i < 3:
				i += 1
				time.sleep(1)
			if proc.poll() is None:
				proc.kill()
			del self._workers[proc]
			print('"{}" #{} is terminated by the timeout ({:.4f} sec): {:.4f} sec ({} h {} m {:.4f} s)'
				.format(job.name, proc.pid, job.timeout, exectime, *secondsToHms(exectime)), file=sys.stderr)
			# Restart the job if required
			if job.ontimeout:
				self.__startJob(job)

		# Process completed jobs: execute callbacks and remove the workers
		for proc, job in completed:
			if job.ondone:
				try:
					job.ondone(job)
				except Exception as err:
					print('ERROR in ondone callback of "{}": {}'.format(job.name, err), file=sys.stderr)
			del self._workers[proc]
			print('"{}" #{} is completed'.format(job.name, proc.pid, file=sys.stderr))
			
		# Start subsequent job if it is required
		while self._jobs and len(self._workers) <  self._workersLim:
			self.__startJob(self._jobs.popleft())


	def execute(self, job):
		"""Schecule the job for the execution
		
		job  - the job to be executed, instance of Job
		"""
		assert isinstance(job, Job), 'job must be a valid entity'
		assert len(self._workers) <= self._workersLim, 'Number of workers exceeds the limit'
		assert job.name, "Job parameters must be defined"  #  and job.workdir and job.args
		
		print('Scheduling the job "{}" with timeout {}'.format(job.name, job.timeout))
		# Start the execution timer
		if self._tstart is None:
			self._tstart = time.time()
		# Schedule the job
		if self._jobs or len(self._workers) >= self._workersLim:
			self._jobs.append(job)
			#self.__reviseWorkers()  # Anyway the workers are revised if exist in the working cycle
		else:
			self.__startJob(job)



	def join(self, exectime=0):
		"""Execution cycle
		
		exectime  - execution timeout in seconds before the workers termination.
			The time is measured SINCE the first job was scheduled UNTIL the
			completion of all scheduled jobs and then is resetted.
		"""
		if self._tstart is None:
			assert not self._jobs and not self._workers, \
				'Start time should be defined for the present jobs'
			return
		
		self.__reviseWorkers()
		while self._jobs or self._workers:
			if exectime and time.time() - self._tstart > exectime:
				self.__terminate()
			time.sleep(1)
			self.__reviseWorkers()
		self._tstart = None


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
	
	evalmaxk = lambda genopts: int(round(sqrt(genopts['N'])))
	evalmuw = lambda genopts: genopts['mut'] * 2/3
	evalminc = lambda genopts: 5 + int(genopts['N'] / N0)
	evalmaxc = lambda genopts: int(genopts['N'] / 3)
	evalon = lambda genopts: int(genopts['N'] * genopts['mut']**2)
	# Template of the generating options files
	genopts = {'mut': 0.275, 'beta': 1.35, 't1': 1.65, 't2': 1.3, 'om': 2, 'cnl': 1}
	
	# Generate options for the networks generation using chosen variations of params
	varNmul = (1, 2, 5, 10, 25, 50)  # *N0
	vark = (5, 10, 20)
	
	epl = ExecPool(max(cpu_count() - 1, 1))
	netgenTimeout = 10 * 60  # 10 min
	for nm in varNmul:
		N = nm * N0
		for k in vark:
			name = 'K'.join((str(nm), str(k)))
			ext = '.ngp'  # Network generation parameters
			fnamex = name.join((paramsDirFull, ext))
			if not overwrite and os.path.exists(fnamex):
				assert os.path.isfile(fnamex), '{} should be a file'.format(fnamex)
				continue
			print('Generating {} parameters file...'.format(fnamex))
			with open(fnamex, 'w') as fout:
				genopts.update({'N': N, 'k': k})
				genopts.update({'maxk': evalmaxk(genopts), 'muw': evalmuw(genopts), 'minc': evalminc(genopts)
					, 'maxc': evalmaxc(genopts), 'on': evalon(genopts), 'name': name})
				for opt in genopts.items():
					fout.write(''.join(('-', opt[0], ' ', str(opt[1]), '\n')))
			if os.path.isfile(fnamex):
				args = ('../exectime', '-n=' + name, ''.join(('-o=', paramsdir, 'lfrbench_uwovp', _extexectime))
					, './lfrbench_uwovp', '-f', name.join((paramsdir, ext)))
				#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None)
				epl.execute(Job(name=name, workdir=_syntdir, args=args, timeout=netgenTimeout, ontimeout=1
					, onstart=lambda job: shutil.copy2(_syntdir + 'time_seed.dat', name.join((_syntdir, '.ngs')))))  # Network generation seed
	print('Parameter files generation is completed')
	epl.join(2 * 60*60)  # 2 hours
	print('Synthetic networks files generation is completed')
	

def convertNets():
	print('Starting networks conversion into required formats (.hig, .lig, etc.)...')
	# Convert network files into .hig format and .lig (Louvain Input Format)
	for net in glob.iglob('*'.join((_syntdir, _extnetfile))):
		try:
			pajek_hig.pajekToHgc(net, '-f', 'tsa')
		except StandardError as err:
			print('ERROR on "{}" conversion into .hig, the network is skipped: {}'.format(net), err, file=sys.stderr)
		netnoext = os.path.splitext(net)[0]  # Remove the extension
		try:
			# ./convert [-r] -i graph.txt -o graph.bin -w graph.weights
			# r  - renumber nodes
			subprocess.call([_algsdir + 'convert', '-i', net, '-o', netnoext + '.lig'
				, '-w', netnoext + '.liw'])
		except StandardError as err:
			print('ERROR on "{}" conversion into .lig, the network is skipped: {}'.format(net), err, file=sys.stderr)
	print('Networks conversion is completed')
	
	
def execLouvain(execpool, netfile, timeout, tasknum=0):
	"""Execute Louvain
	Results are not stable => multiple execution is desirable.
	
	tasknum  - index of the execution on the same dataset
	"""
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	if tasknum:
		task = '-'.join((task, str(tasknum)))
	netfile = '../' + netfile  # Use network in the required format
	
	algname = 'louvain'
	# ./community graph.bin -l -1 -w graph.weights > graph.tree
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', task, '.loc'))
		, stderr=''.join((_algsdir, algname, 'outp/', task, '.log'))))


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
		, timeout=timeout, stdout=os.devnull, stderr=''.join((_algsdir, algname, 'outp/', task, '.log'))))


def execOslom2(execpool, netfile, timeout):
	# Fetch the task name
	task = os.path.split(os.path.splitext(netfile)[0])[1]  # Base name of the network
	assert task, 'The network name should exists'
	
	algname = 'oslom2'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './oslom_undir', '-f', '../' + netfile, '-w')
	# Copy results to the required dir on postprocessing
	logsdir = ''.join((_algsdir, algname, 'outp/'))
	def postexec(job):
		outpdir = ''.join((logsdir, task, '/'))
		if not os.path.exists(outpdir):
			os.makedirs(outpdir)
		for fname in glob.iglob(''.join((_syntdir, task, '.nsa', '_oslo_files/tp*'))):
			shutil.copy2(fname, outpdir)
		
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, tstart=None)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args, timeout=timeout, ondone=postexec
		, stdout=''.join((logsdir, task, '.log')), stderr=''.join((logsdir, task, '.err'))))


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
		, stdout=''.join((logsdir, task, '.log')), stderr=''.join((logsdir, task, '.err'))))


def execHirecsNounwrap(execpool, netfile, timeout):
	"""Hirecs which performs the clustering, but does not unwrappes the wierarchy into levels,
	just outputs the folded hierarchy"""
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	
	algname = 'hirecshfold'
	args = ('../exectime', ''.join(('-o=./', algname, _extexectime)), '-n=' + task
		, './hirecs', '-oc', ''.join(('-cls=./', algname, 'outp/', task, '/', task, '_', algname, _extclnodes))
		, '../' + netfile)
	#Job(name, workdir, args, timeout=0, ontimeout=0, onstart=None, ondone=None, stdout=None, stderr=None, tstart=None)  os.devnull
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_algsdir, args=args
		, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', task, '.hoc'))
		, stderr=''.join((_algsdir, algname, 'outp/', task, '.log'))))
	

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
		, timeout=timeout, stdout=''.join((_algsdir, algname, 'outp/', evalname, '_', task, '.log')), stderr=stderr))


def evalLouvain(execpool, cnlfile, timeout):
	return


def evalHirecs(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs')


def evalOslom2(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2')


def evalGanxis(execpool, cnlfile, timeout):
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis')


def evalHirecsNS(execpool, cnlfile, timeout):
	"""Evaluate Hirecs by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'hirecs', evalbin='./onmi_sum', evalname='nmi-s')


def evalOslom2NS(execpool, cnlfile, timeout):
	"""Evaluate Oslom2 by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'oslom2', evalbin='./onmi_sum', evalname='nmi-s')


def evalGanxisNS(execpool, cnlfile, timeout):
	"""Evaluate Ganxis by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
	evalAlgorithm(execpool, cnlfile, timeout, 'ganxis', evalbin='./onmi_sum', evalname='nmi-s')
	

def benchmark(*args):
	""" Execute the benchmark
	
	Run the algorithms on the specified datasets respecting the parameters.
	"""
	exectime = time.time()
	gensynt, convnets, runalgs, evalres, udatas, wdatas, timeout = parseParams(args)
	print('The benchmark is started, parsed params:\n\tgensynt: {}\n\tconvnets: {}'
		'\n\trunalgs: {}\n\tevalres: {}\n\tudatas: {}, \n\twdatas: {}\n\ttimeout: {}'
		.format(gensynt, convnets, runalgs, evalres, ', '.join(udatas), ', '.join(wdatas), timeout))
	
	if gensynt:
		generateNets(gensynt == 2)
		
	if convnets:
		convertNets()
	
	# Run the algorithms and measure their resource consumption
	if runalgs:
		# Run algs on synthetic datasets
		#udatas = ['../snap/com-dblp.ungraph.txt', '../snap/com-amazon.ungraph.txt', '../snap/com-youtube.ungraph.txt']
		epl = ExecPool(max(min(4, cpu_count() - 1), 1))
		netsnum = 1
	
		algorithms = (execLouvain, execHirecs, execOslom2, execGanxis, execHirecsNounwrap)
		for net in glob.iglob('*'.join((_syntdir, _extnetfile))):
			for alg in algorithms:
				try:
					alg(epl, net, timeout)
				except StandardError as err:
					errexectime = time.time() - exectime
					print('The {} is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s)'
						.format(alg.__name__, err, errexectime, *secondsToHms(errexectime)))
				else:
					netsnum += 1
		
		# Additionally execute Louvain multiple times
		alg = execLouvain
		for net in glob.iglob('*'.join((_syntdir, _extnetfile))):
			for execnum in range(1, 10):
				try:
					alg(epl, net, timeout, execnum)
				except StandardError as err:
					errexectime = time.time() - exectime
					print('The {} is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s)'
						.format(alg.__name__, err, errexectime, *secondsToHms(errexectime)))
		
		# TODO: Implement execution on custom datasets considering whether they weighted / unweighted			
		## Run algs on the specified datasets if required
		## Unweighted networks
		#for udat in udatas:
		#	if not os.path.exists(udat):
		#		print('WARNING, "{}" does not exist, skipped', file=sys.stderr)
		#	#if os.path.isdir(udat):
		#	#	fnames = glob.iglob('*'.join((_syntdir, _extnetfile))):


		epl.join(timeout * netsnum)
		exectime = time.time() - exectime
		print('The benchmark execution is successfully comleted on {:.4f} sec ({} h {} m {:.4f} s)'
			.format(exectime, *secondsToHms(exectime)))
	
	# Evaluate results (NMI)
	if evalres:
		print('Starting NMI evaluation...')
		evalalgs = (evalLouvain, evalHirecs, evalOslom2, evalGanxis
						, evalHirecsNS, evalOslom2NS, evalGanxisNS)
		epl = ExecPool(max(cpu_count() - 1, 1))
		netsnum = 0
		timeout = 20 *60*60  # 20 hours
		for cndfile in glob.iglob('*'.join((_syntdir, _extclnodes))):
			for elg in evalalgs:
				try:
					elg(epl, cndfile, timeout)
				except StandardError as err:
					print('The {} is interrupted by the exception: {}'
						.format(epl.__name__, err))
				else:
					netsnum += 1
		epl.join(max(exectime * 2, 60 * netsnum))  # Twice the time of algorithms execution
		print('NMI evaluation is completed')
	print('The benchmark is completed')


if __name__ == '__main__':
	if len(sys.argv) > 1:
		benchmark(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} [-g[f] [-c] [-r] [-e] [-d{{u,w}} <datasets_dir>] [-f{{u,w}} <dataset>] [-t[{{s,m,h}}] <timeout>]',
			'  -g[f]  - generate synthetic daatasets in the {syntdir}',
			'    Xf  - force the generation even when the data is already exists',
			'  -c  - convert existing networks into the .hig format',
			'  -r  - run the applications on the prepared data',
			'  -e  - evaluate the results through measurements',
			'  -d[X] <datasets_dir>  - directory of the datasets',
			'  -f[X] <dataset>  - dataset file name',
			'    Xu  - the dataset is unweighted. Default option',
			'    Xw  - the dataset is weighted',
			'    Notes:',
			'    - multiple directories and files can be specified',
			'    - datasets should have the following format: <node_src> <node_dest> [<weight>]',
			'  -t[X] <number>  - specifies timeout per each benchmarking application in sec, min or hours. Default: 0 sec',
			'    Xs  - time in seconds. Default option',
			'    Xm  - time in minutes',
			'    Xh  - time in hours',
			))
			.format(sys.argv[0], syntdir=_syntdir))