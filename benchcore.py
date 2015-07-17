#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr:  The benchmark, winch optionally generates or preprocesses datasets using specified executable,
	optionally executes specified apps with the specified params on the specified datasets,
	and optionally evaluates results of the execution using specified executable(s).
	
	All executions are traced and logged also as resources consumption: CPU (user, kernel, etc.) and memory (RSS RAM).
	Traces are saved even in case of internal / external interruptions and crashes.
	
\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-07
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import sys
import time
import subprocess
from multiprocessing import cpu_count
import collections
import os


_extexectime = '.rcp'  # Resource Consumption Profile
_extclnodes = '.cnl'  # Clusters (Communities) Nodes Lists
_execpool = None  # Active execution pool
_netshuffles = 4  # Number of shuffles for each input network for Louvain_igraph (non determenistic algorithms)


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
	
		
	def __finalize__(self):
		self.__del__()
		
		
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
