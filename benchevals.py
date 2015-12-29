#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr: Evaluations of results produced by each executed app

	Resulting cluster/community structure is evluated using extrinsic (NMI, NMI_s)
	and intrinsic (Q - modularity) measures considering overlaps

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-12
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import os
import shutil
import glob
#import subprocess
import sys
# Add algorithms modules
#sys.path.insert(0, 'algorithms')  # Note: this operation might lead to ambiguity on paths resolving

from datetime import datetime

#from algorithms.louvain_igraph import louvain
#from algorithms.randcommuns import randcommuns
from contrib.mpepool import *
from benchutils import *

from benchutils import _SEPINST
from benchutils import _SEPPATHID
from benchutils import _PATHID_FILE


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_ALGSDIR = 'algorithms/'  # Default directory of the benchmarking algorithms
_RESDIR = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to _ALGSDIR
_CLSDIR = 'clusters/'  # Clusters directory for the resulting clusters of algorithms execution
_MODDIR = 'mod/'
_NMIDIR = 'nmi/'
_EXTERR = '.err'
_EXTEXECTIME = '.rcp'  # Resource Consumption Profile
_EXTAGGRES = '.res'  # Aggregated results
_EXTAGGRESEXT = '.resx'  # Extended aggregated results
#_extmod = '.mod'
#_EXECNMI = './gecmi'  # Binary for NMI evaluation
#_netshuffles = 4  # Number of shuffles for each input network for Louvain_igraph (non determenistic algorithms)


class ShufflesAgg(object):
	"""Shuffles evaluations aggregator"""
	def __init__(self, evagg, name):
		"""Constructor

		evagg  - global evaluations aggregator, which traces this partial aggrigator
		name  - aggregator name, which should correspond to the task name over the jobs

		levels  - resulting aggregated evaluations for the cluster / community levels

		fixed  - whether all items are aggregated and summarization is performed
		bestlev  - cluster level with the best value, defined for the finalized evaluations
		"""
		self.name = name
		#self.evagg = evagg
		# Aggregation data
		self.levels = {}  # Name, LevelStat

		self.fixed = False  # All related jobs have been aggregated
		self.bestlev = None

		# Register this aggregator in the global results aggregator
		evagg.register(self)  # sagg: isfixed  - dict


	def add(self, job, val):
		"""Add subsequent value to the aggregation

		job  - the job produced the val
		val  - the integral value to be aggregated
		"""
		# Aggregate over cluster levels by shuffles
		# [Evaluate max avg among the aggregated level and transfer it to teh instagg as final result]
		assert not self.fixed,  'Only non-fixed aggregator can be modified'
		levname = job.params['clslev']
		levstat = self.levels.get(levname)
		if levstat is None:
			levstat = ItemsStatistic(levname)
			self.levels[levname] = levstat
		levstat.add(val)


	def stat(self):
		"""Accumulated statistics"""
		assert self.fixed, 'Only fixed aggregator has final statistics'
		return self.bestlev[1] if self.bestlev else None


	def fix(self, task=None):
		"""Fix (finalize) statistics accumulation and produce the summary of the results

		task  - the task that calls results fixation
		"""
		if self.levels:
			itlevs = self.levels.iteritems()
			self.bestlev = itlevs.next()
			self.bestlev[1].fix()
			for name, val in itlevs:
				val.fix()
				if val.avg > self.bestlev[1].avg:
					self.bestlev = (name, val)
		self.fixed = True
		if self.bestlev is None or self.bestlev[1].avg is None:
			print('WARNING, "{}" has no defined results'.format(self.name))
		## Trace best lev value for debugging purposes
		#else:
		#	val = self.bestlev[1]
		#	print('{} bestval is {}: {} (from {} up to {}, sd: {})'
		#		.format(self.name, self.bestlev[0], val.avg, val.min, val.max, val.sd))


class EvalsAgg(object):
	"""Evaluations aggregator for the specified measure"""
	def __init__(self, measure):
		"""Constractor

		measure  - target measure for this aggrigator

		partaggs  - partial aggregators to be processed
		aevals  - resulting algorithm evaluations
		"""
		self.measure = measure
		self.partaggs = []

		self.netsev = {}  # Global network evaluations in the format: net_name: alg_eval
		self.algs = set()

		#self.aevals = {}
		##self.netsev = {}
		#self.networks = set()


	def aggregate(self):
		"""Aggregate results over all partial aggregates and output them"""
		# Show warning for all non-fixed registered instances over what the aggregation is performed.
		# Evaluate max among all avg value among instances of each network with particular params. - 3rd element of the task name
		# Evaluate avg and range over all network instances with the same base name (and params),
		# #x and ^x are processed similary as instances.
		for inst in self.partaggs:
			if not inst.fixed:
				print('WARNING, shuffles aggregator for task "{}" was not fixed on final aggregation'
					.format(inst.name))
				inst.fix()
			measure, algname, netname, pathid = inst.name.split('/')  # Note: netname might include instance index
			## Separate instance name into the base name of the network and instance id
			#iisep = netname.rfind(_SEPINST) + 1  # Skip the separator symbol
			##instid = 0
			#if iisep:
			#	# Validate that this is really index
			#	try:
			#		int(netname[iisep:])  # instid
			#	except ValueError as err:
			#		print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
			#		.format(_SEPINST, netname, err), file=sys.stderr)
			#	else:
			#		netname = netname[:iisep-1]
			#		assert netname, 'Network name must be valid'
			netname = delPathSuffix(netname, True)
			# Maintain list of all evaluated algs to output results in the table format
			self.algs.add(algname)
			# Update global network evaluation results
			algsev = self.netsev.setdefault(netname, {})
			netstat = algsev.get(algname)
			if netstat is None:
				netstat = ItemsStatistic(algname)
				algsev[algname] = netstat
			## Update global register of evaluations
			#self.networks.add(netname)  # Maintain list of networks to output evaluation table
			#aeval = self.aevals.setdefault(algname, {})  # Network evaluations for the algorithm
			#nstat = aeval.get(netname)  # Aggregated resulting statistics for the network
			#if not nstat:
			#	nstat = ItemsStatistic(netname)
			#	aeval[netname] = nstat
			netstat.addstat(inst.stat())
		# Remove partial aggregations
		self.partaggs = None

		# Order available algs names
		self.algs = sorted(self.algs)
		#print('Available algs: ' + ' '.join(self.algs))
		# Output aggregated results for this measure for all algorithms
		resbase = _RESDIR + self.measure
		with open(resbase + _EXTAGGRES, 'a') as fmeasev, open(resbase + _EXTAGGRESEXT, 'a') as fmeasevx:
			# Append to the results and extended results
			timestamp = datetime.utcnow()
			fmeasev.write('# --- {}, output:  Q_avg\n'.format(timestamp))  # format = Q_avg: Q_min Q_max, Q_sd count;
			# Extended output has notations in each row
			fmeasevx.write('# --- {} ---\n'.format(timestamp))  # format = Q_avg: Q_min Q_max, Q_sd count;
				  # Write timestamp
			header = True  # Output header
			#? netsnum = None  # Verufy that each algorithm is executed on the same number of networks
			for net, algsev in self.netsev.iteritems():
				if header:
					fmeasev.write('# <network>')
					for alg in self.algs:
						fmeasev.write('\t{}'.format(alg))
					fmeasev.write('\n')
					# Brief header for the extended results
					fmeasevx.write('# <network>\n#\t<alg1_outp>\n#\t<alg2_outp>\n#\t...\n')
					header = False
				algsev = iter(sorted(algsev.items(), key=lambda x: x[0]))
				ialgs = iter(self.algs)
				firstcol = True
				# Output aggregated network evaluation for each algorithm
				for alg in ialgs:
					# Output row header it required
					if firstcol:
						fmeasev.write(net)
						fmeasevx.write(net)
						firstcol = False
					try:
						aev = algsev.next()
					except StopIteration:
						# Write separators till the end
						fmeasev.write('\t')
						for alg in ialgs:
							fmeasev.write('\t')
					else:
						# Check whether to show evaluated alg results now or later
						if aev[0] == alg:
							val = aev[1]
							val.fix()  # Process aggregated resutls
							fmeasev.write('\t{:.6f}'.format(val.avg))
							fmeasevx.write('\n\t{}>\tQ: {:.6f} ({:.6f} .. {:.6f}), s: {:.6f}, count: {}, fails: {},'
								' d(shuf): {:.6f}, s(shuf): {:.6f}, count(shuf): {}, fails(shuf): {}'
								.format(alg, val.avg, val.min, val.max, val.sd, val.count, val.invals
								, val.statDelta, val.statSD, val.statCount, val.invstats))
						else:
							# Skip this alg
							fmeasev.write('\t')
				fmeasev.write('\n')
				fmeasevx.write('\n')


	def register(self, shfagg):
		"""Register new partial aggregator, shuffles aggregator"""
		measure = shfagg.name.split('/', 1)[0]
		assert measure == self.measure, (
			'This aggregator serves "{}" measure, but "{}" is registering'
			.format(self.measure, measure))
		self.partaggs.append(shfagg)


def evalGeneric(execpool, evalname, algname, basefile, measdir, timeout, evalfile, resagg, pathid='', tidy=True):
	"""Generic evaluation on the specidied file
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	evalname  - evaluating measure name
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
		Note: basefile itself never contains pathid
	measdir  - measure-identifying directory to store results
	timeout  - execution timeout for this task
	evalfile  - file evaluation callback to define evaluation jobs, signature:
		evalfile(jobs, cfile, jobname, task, taskoutp, ijobsuff, logsbase)
	resagg  - results aggregator
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs.
		Note: pathid includes pathid separator
	tidy  - delete previously existent resutls. Must be False if a few apps output results into the same dir
	"""
	assert execpool and basefile and evalname and algname, "Parameters must be defined"
	assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'
	# Fetch the task name and chose correct network filename
	taskcapt = os.path.splitext(os.path.split(basefile)[1])[0]  # Name of the basefile (network or ground-truth clusters)
	ishuf = os.path.splitext(taskcapt)[1]  # Separate shuffling index (with pathid if exists) if exists
	assert taskcapt and not ishuf, 'The base file name must exists and should not be shuffled'
	# Define index of the task suffix (identifier) start
	tcapLen = len(taskcapt)  # Note: it never contains pathid

	# Make dirs with logs & errors
	# Directory of resulting community structures (clusters) for each network
	# Note:
	#  - consider possible parameters of the executed algorithm, embedded into the dir names with _SEPPARS
	#  - base file never has '.' in the name except exception, so ext extraction is applicable
	#print('basefile: {}, taskcapt: {}'.format(basefile, taskcapt))

	# Resource consumption profile file name
	rcpoutp = ''.join((_RESDIR, algname, '/', evalname, _EXTEXECTIME))
	shuffagg = ShufflesAgg(resagg, name='/'.join((evalname, algname, taskcapt, pathid)));
	task = Task(name=shuffagg.name, params=shuffagg, ondone=shuffagg.fix)  # , params=EvalState(taskcapt, )
	jobs = []
	# Traverse over directories of clusters corresponding to the base network
	for clsbase in glob.iglob(''.join((_RESDIR, algname, '/', _CLSDIR, escapePathWildcards(taskcapt), '*'))):
		# Skip execution of log files, leaving only dirs
		if not os.path.isdir(clsbase):
			continue
		clsname = os.path.split(clsbase)[1]  # Processing clusters dir, which base name of the job, id part of the task name
		clsnameLen = len(clsname)

		# Skip cases when processing clusters does not have expected pathid
		if pathid and not clsname.endswith(pathid):
			continue
		# Skip cases whtn processing clusters have unexpected pathid
		elif not pathid:
			icnpid = clsname.rfind(_SEPPATHID)  # Index of pathid in clsname
			if icnpid != -1 and icnpid + 1 < clsnameLen:
				# Check whether this is a valid pathid considering possible pathid file mark
				if clsname[icnpid + 1] == _PATHID_FILE:
					icnpid += 1
				# Validate pathid
				try:
					int(clsname[icnpid + 1:])
				except ValueError as err:
					# This is not the pathid, or this pathid has invalid format
					print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
					.format(_SEPPATHID, clsname, err), file=sys.stderr)
					# Continue processing as ordinary clusters wthout pathid
				else:
					# Skip this clusters having unexpected pathid
					continue
		icnpid = clsnameLen - len(pathid)  # Index of pathid in clsname

		# Filter out unexpected instances of the network (when then instance without id is processed)
		if clsnameLen > tcapLen and clsname[tcapLen] == _SEPINST:
			continue

		# Fetch shuffling index if exists
		ish = clsname[:icnpid].rfind('.') + 1  # Note: reverse direction to skip possible separator symbols in the name itself
		shuffle = clsname[ish:icnpid] if ish else ''
		# Validate shufflng index
		if shuffle:
			try:
				int(shuffle)
			except ValueError as err:
				print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
					.format('.', clsname, err), file=sys.stderr)
				# Continue processing skipping such index
				shuffle = ''

		# Note: separate dir is created, because modularity is evaluated for all files in the target dir,
		# which are different granularity / hierarchy levels
		logsbase = clsbase.replace(_CLSDIR, measdir)
		# Remove previous results if exist and required
		if tidy and os.path.exists(logsbase):
			shutil.rmtree(logsbase)
		if tidy or not os.path.exists(logsbase):
			os.makedirs(logsbase)

		# Skip shuffle indicator to accumulate values from all shuffles into the single file
		taskoutp = os.path.splitext(logsbase)[0] if shuffle else logsbase
		# Recover lost pathid if required
		if shuffle and pathid:
			taskoutp += pathid
		taskoutp = '.'.join((taskoutp, evalname))  # evalext  # Name of the file with modularity values for each level
		if tidy and os.path.exists(taskoutp):
			os.remove(taskoutp)

		# Traverse over all resulting communities for each ground truth, log results
		for cfile in glob.iglob(escapePathWildcards(clsbase) + '/*'):
			if os.path.isdir(cfile):  # Skip dirs among the resulting clusters (extra/, generated by OSLOM)
				continue
			# Extract base name of the evaluating clusters level
			# Note: benchmarking algortihm output file names are not controllable and can be any, unlike the embracing folders
			jbasename = os.path.splitext(os.path.split(cfile)[1])[0]
			assert jbasename, 'The clusters name should exists'
			# Extand job caption with the executing task if not already contains and update the caption index
			pos = jbasename.find(clsname)
			# Define clusters level name as part of the jbasename
			#if pos != -1:
			#	clslev = jbasename[pos:].lstrip('_-.')
			#	if not clslev:
			#		clslev = jbasename[:pos].rstrip('_-.')
			#	jbasename = clslev
			if pos == -1:
				pos = 0
				jbasename = '_'.join((clsname, jbasename))
			clslev = jbasename[pos + clsnameLen:].lstrip('_-.')
			if not clslev:
				clslev = jbasename[:pos].rstrip('_-.')  # Note: clslev can be empty if jbasename == clsname
			#if shuffle:
			#	clslev = '/'.join((clslev, shuffle))

			#clslev = '  '.join((jbasename, clsname, pathid, basefile, '<<<', clsbase, '>>>', clslev))
			jobname = '/'.join((evalname, algname, clsname))
			logfilebase = '/'.join((logsbase, jbasename))
			# pathid must be part of jobname, and  bun not of the clslev
			evalfile(jobs, cfile, jobname, task, taskoutp, rcpoutp, clslev, shuffle, logfilebase)
	# Run all jobs after all of them were added to the task
	if jobs:
		for job in jobs:
			try:
				execpool.execute(job)
			except StandardError as err:
				print('WARNING, "{}" job is interrupted by the exception: {}'
					.format(job.name, err), file=sys.stderr)
	else:
		print('WARNING, "{}" clusters "{}" do not exist to be evaluated'
			.format(algname, clsname), file=sys.stderr)


def evalAlgorithm(execpool, algname, basefile, measure, timeout, resagg, pathid=''):
	"""Evaluate the algorithm by the specified measure.
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
	measure  - target measure to be evaluated: {nmi, nmi_s, mod}
	timeout  - execution timeout for this task
	resagg  - results aggregator
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs
		Note: pathid includes pathid separator
	"""
	assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'
	print('Evaluating {} for "{}" on base of "{}"...'.format(measure, algname, basefile))

	#evalname = None
	#if measure == 'nmi_s':
	#	# Evaluate by NMI_sum (onmi) instead of NMI_conv(gecmi)
	#	evalname = measure
	#	measure = 'nmi'
	#eaname = measure + 'Algorithm'
	#evalg = getattr(sys.modules[__name__], eaname, unknownApp(eaname))
	#if not evalname:
	#	evalg(execpool, algname, basefile, timeout)
	#else:
	#	evalg(execpool, algname, basefile, timeout, evalbin='./onmi_sum', evalname=evalname)

	def modEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, clslev, shuffle, logsbase):
		"""Add modularity evaluatoin job to the current jobs
		NOTE: all paths are given relative to the root benchmark directory.

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		logsbase  - base part of the file name for the logs including errors
		"""
		#print('Starting modEvaluate with params:\t[basefile: {}]\n\tcfile: {}\n\tjobname: {}'
		#	'\n\ttask.name: {}\n\ttaskoutp: {}\n\tjobsuff: {}\n\tlogsbase: {}\n'
		#	.format(basefile, cfile, jobname, task.name, taskoutp, clslev, logsbase), file=sys.stderr)

		# Processing is performed from the algorithms dir
		args = ('./hirecs', '-e=../' + cfile, '../' + basefile)

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			result = job.proc.communicate()[0]  # Read buffered stdout
			# Find require value to be aggregated
			targpref = 'mod: '
			# Match float number
			mod = parseFloat(result[len(targpref):])[0] if result.startswith(targpref) else None
			if mod is None:
				print('ERROR, job "{}" has invalid output format. Moularity value is not found in:\n{}'
					.format(job.name, result), file=sys.stderr)
				return

			# Transfer resutls to the embracing task if exists
			if job.task and job.task.params:
				job.task.params.add(job, mod)
			else:
				print('WARNING, task "{}" of job "{}" has no results aggregator defined via params'
					.format(job.name), file=sys.stderr)
			# Log results
			taskoutp = job.params['taskoutp']
			with open(taskoutp, 'a') as tmod:  # Append to the end
				if not os.path.getsize(taskoutp):
					tmod.write('# Q\t[ShuffleIndex_]Level\n')
					tmod.flush()
				# Define result caption
				rescapt = job.params['clslev']
				if job.params['shuffle']:
					rescapt = '/'.join((rescapt, job.params['shuffle']))
				tmod.write('{}\t{}\n'.format(mod, rescapt))


		jobs.append(Job(name=jobname, task=task, workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			# Output modularity to the proc PIPE buffer to be aggregated on postexec to avoid redundant files
			, stdout=PIPE, stderr=logsbase + _EXTERR))


	def nmiEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, clslev, shuffle, logsbase):
		"""Add nmi evaluatoin job to the current jobs

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		logsbase  - base part of the file name for the logs including errors

		Example:
		[basefile: syntnets/networks/1K10/1K10.cnl]
		cfile: results/scp/clusters/1K10!k3/1K10!k3_1.cnl
		jobname: nmi_1K10!k3_1_scp
		task.name: nmi_1K10_scp
		taskoutp: results/scp/nmi/1K10!k3.nmi
		rcpoutp: results/scp/nmi.rcp
		clslev: 1
		shuffle:
		logsbase: results/scp/nmi/1K10!k3/1K10!k3_1
		"""
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
				# Transfer resutls to the embracing task if exists
				if job.task and job.task.params:
					job.task.params.add(job, nmi)
				else:
					print('WARNING, task "{}" of job "{}" has no results aggregator defined via params'
						.format(job.name), file=sys.stderr)
				# Log results
				taskoutp = job.params['taskoutp']
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.path.getsize(taskoutp):
						tnmi.write('# NMI\tlevel[/shuffle]\n')
						tnmi.flush()
					# Define result caption
					rescapt = job.params['clslev']
					if job.params['shuffle']:
						rescapt = '/'.join((rescapt, job.params['shuffle']))
					tnmi.write('{}\t{}\n'.format(nmi, rescapt))


		jobs.append(Job(name=jobname, task=task, workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			, stdout=PIPE, stderr=logsbase + _EXTERR))


	def nmisEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, clslev, shuffle, logsbase):
		"""Add nmi evaluatoin job to the current jobs

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		logsbase  - base part of the file name for the logs including errors
		"""
		# Processing is performed from the algorithms dir
		args = ('../exectime', '-o=../' + rcpoutp, '-n=' + jobname, './onmi_sum', '../' + basefile, '../' + cfile)

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0]
				nmi = float(result)  # Read buffered stdout
			except ValueError:
				print('ERROR, nmi_s evaluation failed for the job "{}": {}'
					.format(job.name, result), file=sys.stderr)
			else:
				# Transfer resutls to the embracing task if exists
				if job.task and job.task.params:
					job.task.params.add(job, nmi)
				else:
					print('WARNING, task "{}" of job "{}" has no results aggregator defined via params'
						.format(job.name), file=sys.stderr)
				# Log results
				taskoutp = job.params['taskoutp']
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.path.getsize(taskoutp):
						tnmi.write('# NMI_s\tlevel[/shuffle]\n')
						tnmi.flush()
					# Define result caption
					rescapt = job.params['clslev']
					if job.params['shuffle']:
						rescapt = '/'.join((rescapt, job.params['shuffle']))
					tnmi.write('{}\t{}\n'.format(nmi, rescapt))


		jobs.append(Job(name=jobname, task=task, workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			, stdout=PIPE, stderr=logsbase + _EXTERR))


	if measure == 'mod':
		evalGeneric(execpool, measure, algname, basefile, _MODDIR, timeout, modEvaluate, resagg, pathid)
	elif measure == 'nmi':
		evalGeneric(execpool, measure, algname, basefile, _NMIDIR, timeout, nmiEvaluate, resagg, pathid)
	elif measure == 'nmi_s':
		evalGeneric(execpool, measure, algname, basefile, _NMIDIR, timeout, nmisEvaluate, resagg, pathid, tidy=False)
	else:
		raise ValueError('Unexpected measure: ' + measure)
