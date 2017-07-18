#!/usr/bin/env python2
# -*- coding: utf-8 -*-

"""
\descr: Evaluation of results produced by each executed application.

	Resulting cluster/community structure is evluated using extrinsic (NMI, NMI_s)
	and intrinsic (Q - modularity) measures considering overlaps.

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-12
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
import os
import shutil
import glob
import sys
import traceback  # Stacktrace
# from collections import namedtuple
from subprocess import PIPE


from benchutils import viewitems, viewvalues, ItemsStatistic, parseFloat, parseName, \
	escapePathWildcards, envVarDefined, _SEPPARS, _SEPINST, _SEPSHF, _SEPPATHID, _UTILDIR, \
	_TIMESTAMP_START_STR, _TIMESTAMP_START_HEADER
from utils.mpepool import Task, Job


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_RESDIR = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to _ALGSDIR
_CLSDIR = 'clusters/'  # Clusters directory for the resulting clusters of algorithms execution
_EXTERR = '.err'
#_EXTLOG = '.log'  # Extension for the logs
#_EXTELOG = '.elog'  # Extension for the unbuffered (typically error) logs
_EXTEXECTIME = '.rcp'  # Resource Consumption Profile
_EXTAGGRES = '.res'  # Aggregated results
_EXTAGGRESEXT = '.resx'  # Extended aggregated results
_SEPNAMEPART = '/'  # Job/Task name parts separator ('/' is the best choice, because it can not apear in a file name, which can be part of job name)

_DEBUG_TRACE = False  # Trace start / stop and other events to stderr


def execGecmi(execpool, clsfile, asym, odir, timeout, pathid='', workdir=_UTILDIR, seed=None):
	pass


def execOnmi(execpool, clsfile, asym, odir, timeout, pathid='', workdir=_UTILDIR, seed=None):
	pass


def execXmeasures(execpool, clsfile, asym, odir, timeout, pathid='', workdir=_UTILDIR, seed=None):
	pass


def execDaoc(execpool, clsfile, asym, odir, timeout, pathid='', workdir=_UTILDIR, seed=None):
	pass


def evaluators(quality):
	"""Fetch tuple of the evaluation executable calling functions for the specified measures

	quality  - quality measures mask
		Note: all measures are applicable for the overlapping clusters
		0  - nothing
		0b00000001  - NMI_max
		0b00000011  - all NMIs (max, min, avg, sqrt)
		0b00000100  - ONMI_max
		0b00001100  - all ONMIs (max, avg, lfk)
		0b00010000  - Average F1h Score
		0b00100000  - F1p measure
		0b01110000  - All F1s (F1p, F1h, F1s)
		0b10000000  - Default extrinsic measures (NMI_max, F1h and F1p)
		0b1111'1111  - All extrinsic measures (NMI-s, ONMI-s, F1-s)
		0x1xx  - Q (modularity)
		0x2xx  - f (conductance)
		0xFxx  - All intrinsic measures
	"""
	evals = []
	if quality & 0b11:  # NMI multiresolution (multiscale) and overlapping (gecmi)
		evals.append(execGecmi)
	if quality & 0b1100:  # NMI overlapping (onmi)
		evals.append(execOnmi)
	if quality & 0xF0:  # F1-s (xmeasures)
		evals.append(execXmeasures)
	if quality & 0xF00:  # Intrinsic measures: Q and f (daoc)
		evals.append(execDaoc)
	return tuple(evals)


class ShufflesAgg(object):
	"""Shuffles evaluations aggregator

	1. Best avg per level is defined as for all shuffles:
		sum value per each level is taken, highest sum / count is selected.
	2. For all instances average weighted among best levels (1) is taken
		(considering number of items in each best value).
	"""
	def __init__(self, evagg, name):
		"""Constructor

		evagg  - global evaluations aggregator, which traces this partial aggrigator
		name  - aggregator name in the format:  <measure>/<algname>/<netname>,
			<netname> includes pathid

		levels  - resulting aggregated evaluations for the cluster / community levels

		fixed  - whether all items are aggregated and summarization is performed
		bestlev  - cluster level with the best value, defined for the finalized evaluations
		"""
		assert name.count(_SEPNAMEPART) == 2, 'Name format validatoin failed: ' + name
		self.name = name
		# Aggregation data
		self.levels = {}  # Name: LevelStat

		self.fixed = False  # All related jobs have been aggregated
		self.bestlev = None  # Best level, format: (name, value)

		# Register this aggregator in the global results aggregator
		evagg.register(self)  # shufagg: isfixed  - dict


	def addraw(self, resfile, lev, val):
		"""Add subsequent value to the aggregation

		resfile  - full file name of the processing evaluation result
		lev  - processing level (can be any string, which is a part of the file name)
		val  - the real value to be aggregated
		"""
		# Aggregate over cluster levels by shuffles distinguishing each set of algorithm params (if exists)
		# [Evaluate max avg among the aggregated level and transfer it to teh instagg as final result]
		assert not self.fixed, 'Only non-fixed aggregator can be modified'
		# Validate lev to guarantee it does not contain shuffle part
		assert lev.find(_SEPNAMEPART) == -1, 'Level name should not contain shuffle part'

		# Extract algorithm params if exist from the 'taskoutp' job param
		taskname = os.path.splitext(os.path.split(resfile)[1])[0]
		# Validate taskname, i.e. validate that shuffles aggregator is called for it's network
		assert taskname == self.name[self.name.rfind('/') + 1:], (
			'taskname validation failed: "{}" does not belong to "{}"'.format(taskname, self.name))
		algpars = ''  # Algorithm params
		ipb = taskname.find(_SEPPARS, 1)  # Index of params begin. Params separator can't be the first symbol of the name
		if ipb != -1 and ipb != len(taskname) - 1:
			# Find end of the params
			ipe = filter(lambda x: x >= 0, [taskname[ipb:].rfind(c) for c in (_SEPINST, _SEPPATHID, _SEPSHF)])
			if ipe:
				ipe = min(ipe) + ipb  # Conside ipb offset
			else:
				ipe = len(taskname)
			algpars = taskname[ipb:ipe]
		# Update statiscit
		levname = lev
		if algpars:
			levname = _SEPNAMEPART.join((levname, algpars))  # Note: _SEPNAMEPART never occurs in the filename, levname
		#print('addraw lev: {}, aps: {}, taskname: {}'.format(levname, algpars, taskname))
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
			itlevs = iter(viewitems(self.levels))
			self.bestlev = itlevs.next()
			self.bestlev[1].fix()
			for name, val in itlevs:
				val.fix()
				if val.avg > self.bestlev[1].avg:
					self.bestlev = (name, val)
		self.fixed = True
		if self.bestlev is None or self.bestlev[1].avg is None:
			print('WARNING, "{}" has no defined results'.format(self.name))
		# Trace best lev value for debugging purposes
		elif _DEBUG_TRACE:
		#else:
			print('Best lev of {}:\t{} = {:.6f}'.format(
				self.name[self.name.rfind('/') + 1:], self.bestlev[0], self.bestlev[1].avg))
		##	val = self.bestlev[1]
		##	print('{} bestval is {}: {} (from {} up to {}, sd: {})'
		##		.format(self.name, self.bestlev[0], val.avg, val.min, val.max, val.sd))


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


	def aggregate(self):
		"""Aggregate results over all partial aggregates and output them"""
		# Show warning for all non-fixed registered instances over what the aggregation is performed.
		# Evaluate max among all avg value among instances of each network with particular params. - 3rd element of the task name
		# Evaluate avg and range over all network instances with the same base name (and params),
		# #x and ^x are processed similary as instances.
		nameps = False  # Parameters are used in the name
		for inst in self.partaggs:
			if not inst.fixed:
				print('WARNING, shuffles aggregator for task "{}" was not fixed on final aggregation'
					.format(inst.name), file=sys.stderr)
				inst.fix()
			measure, algname, netname = inst.name.split(_SEPNAMEPART)
			#print('Final aggregate over net: {}, pathid: {}'.format(netname, pathid))
			# Remove instance id if exists (initial name does not contain params and pathid)
			netname, apars, insid, shid, pathid = parseName(netname, True)
			assert not shid, 'Shuffles should already be aggregated'
			# Take average over instances and shuffles for each set of alg params
			# and the max for alg params among the obtained results
			if apars:
				nameps = True
				netname = _SEPNAMEPART.join((netname, apars))
			# Maintain list of all evaluated algs to output results in the table format
			self.algs.add(algname)
			# Update global network evaluation results
			algsev = self.netsev.setdefault(netname, {})
			netstat = algsev.get(algname)
			if netstat is None:
				netstat = ItemsStatistic(algname)
				algsev[algname] = netstat
			netstat.addstat(inst.stat())  # Note: best result for each network with the same alg params can correspond to different levels
		# For each network retain only best result among all algorithm parameters
		naparams = {}  # Algorithm parameters for the network that correspond to the best result, format:  AlgName: AlgParams
		if nameps:
			netsev = {}
			for net, algsev in viewitems(self.netsev):
				# Cut params from the network name
				pos = net.find(_SEPNAMEPART)
				if pos != -1:
					apars = net[pos+1:]
					net = net[:pos]
				else:
					apars = None
				# Sync processing network and alg params
				napars = naparams.setdefault(net, {})
				# Retain only the highest value among params
				uaev = netsev.setdefault(net, {})
				for alg, netstat in viewitems(algsev):
					netstat.fix()  # Process aggregated results
					uns = uaev.get(alg)
					#print('uns.avg: {:.6}, netstat.avg: {:.6}'.format(uns.avg if uns else None, netstat.avg))
					if not uns or uns.avg < netstat.avg:
						uaev[alg] = netstat
						napars[alg] = apars

			self.netsev = netsev
		# Remove partial aggregations
		self.partaggs = None

		# Order available algs names
		self.algs = sorted(self.algs)
		# Output aggregated results for this measure for all algorithms
		resbase = _RESDIR + self.measure
		with open(resbase + _EXTAGGRES, 'a') as fmeasev, open(resbase + _EXTAGGRESEXT, 'a') as fmeasevx:
			# Append to the results and extended results
			#timestamp = datetime.utcnow()
			fmeasev.write('# --- {}, output:  Q_avg\n'.format(_TIMESTAMP_START_STR))  # format = Q_avg: Q_min Q_max, Q_sd count;
			# Extended output has notations in each row
			# Note: print() unlike .write() outputs also ending '\n'
			print(_TIMESTAMP_START_HEADER, file=fmeasevx)
			header = True  # Output header
			for net, algsev in viewitems(self.netsev):
				if header:
					fmeasev.write('# <network>')
					for alg in self.algs:
						fmeasev.write('\t{}'.format(alg))
					fmeasev.write('\n')
					# Brief header for the extended results
					fmeasevx.write('# <network>\n#\t<alg1_outp>\n#\t<alg2_outp>\n#\t...\n')
					header = False
				algsev = iter(sorted(viewitems(algsev), key=lambda x: x[0]))
				ialgs = iter(self.algs)
				firstcol = True
				# Algorithms and their params for the best values on this network
				algspars = naparams.get(net)
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
							if not val.fixed:
								val.fix()  # Process aggregated resutls
							fmeasev.write('\t{:.6f}'.format(val.avg))
							if algspars:
								napars = algspars.get(alg)
							else:
								napars = None
							# Q is taken as weighted average for best values per each instance,
							# where best is defined as higest average value among all levels in the shuffles.
							# Min is min best avg among shuffles for each instance, max is max best avg.
							# ATTENTION: values that can be None can't be represented as .6f, but can be as .6
							fmeasevx.write('\n\t{}>\tQ: {:.6f} ({:.6f} .. {:.6f}), s: {:.6}, count: {}, fails: {},'
								' d(shuf): {:.6}, s(shuf): {:.6}, count(shuf): {}, fails(shuf): {}'
								.format(alg + (napars.join((' (', ')')) if napars else '')
								, val.avg, val.min, val.max, val.sd, val.count, val.invals
								, val.statDelta, val.statSD, val.statCount, val.invstats))
						else:
							# Skip this alg
							fmeasev.write('\t')
				fmeasev.write('\n')
				fmeasevx.write('\n')


	def register(self, shfagg):
		"""Register new partial aggregator, shuffles aggregator"""
		measure = shfagg.name.split(_SEPNAMEPART, 1)[0]
		assert measure == self.measure, (
			'This aggregator serves "{}" measure, but "{}" is registering'
			.format(self.measure, measure))
		self.partaggs.append(shfagg)


def aggEvaluations(respaths):
	"""Aggregate evaluations over speified paths of results.
	Results are appended to the files of the corresponding aggregated measures.

	respaths  - iterable container of evaluated reults paths
	"""
	print('Starting evaluation results aggregation ...')
	evalaggs = {}  # Evaluation aggregators per measures:  measure: evalagg
	# Process specified pahts
	for path in respaths:
		for resfile in glob.iglob(path):
			# Skip dirs if occurred
			if not os.path.isfile(resfile):
				continue
			## Fetch the measure be the file extension
			#measure = os.path.splitext(resfile)[1]
			#if not measure:
			#	print('WARNING, no any extension exists in the evaluatoin file: {}. Skipped.'.format(resfile))
			#	continue
			#measure = measure[1:]  # Skip extension separator

			# Fetch algname, measure, network name and pathid
			algname, measure, netname = resfile.rsplit('/', 2)
			algname = os.path.split(algname)[1]
			netname = os.path.splitext(netname)[0]
			assert measure in ('mod', 'nmi', 'nmi_s'), 'Invalid evaluation measure "{}" from file: {}'.format(measure, resfile)

			# Fetch corresponding evaluations aggregator
			eagg = evalaggs.get(measure)
			if not eagg:
				eagg = EvalsAgg(measure)
				evalaggs[measure] = eagg
			with open(resfile, 'r') as finp:
				partagg = ShufflesAgg(eagg, _SEPNAMEPART.join((measure, algname, netname)))
				#print('Aggregating partial: ', partagg.name)
				for ln in finp:
					# Skip header
					ln = ln.lstrip()
					if not ln or ln[0] == '#':
						continue
					# Process values:  <value>\t<lev_with_shuffle>
					val, levname = ln.split(None, 1)
					levname = levname.split(_SEPNAMEPART, 1)[0]  # Remove shuffle part from the levname if exists
					partagg.addraw(resfile, levname, float(val))
				partagg.fix()
	# Aggregate total statistics
	for eagg in viewvalues(evalaggs):
		eagg.aggregate()
	print('Evaluation results aggregation is finished.')


def evalGeneric(execpool, measure, algname, basefile, measdir, timeout, evaljob, resagg, pathid='', tidy=True):
	"""Generic evaluation on the specidied file
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	measure  - evaluating measure name
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
		Note: basefile itself never contains pathid
	measdir  - measure-identifying directory to store results
	timeout  - execution timeout for this task
	evaljob  - evaluatoin job to be performed on the evaluating file, signature:
		evaljob(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase)
	resagg  - results aggregator
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs.
		Note: pathid includes pathid separator
	tidy  - delete previously existent resutls. Must be False if a few apps output results into the same dir
	"""
	assert execpool and basefile and measure and algname, 'Parameters must be defined'
	assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'
	# Fetch the task name and chose correct network filename
	taskcapt = os.path.splitext(os.path.split(basefile)[1])[0]  # Name of the basefile (network or ground-truth clusters)
	ishuf = None if taskcapt.find(_SEPSHF) == -1 else taskcapt.rsplit(_SEPSHF, 1)[1]  # Separate shuffling index (with possible pathid) if exists
	assert taskcapt and not ishuf, 'The base file name must exists and should not be shuffled, file: {}, ishuf: {}'.format(
		taskcapt, ishuf)
	# Define index of the task suffix (identifier) start
	tcapLen = len(taskcapt)  # Note: it never contains pathid
	#print('Processing {}, pathid: {}'.format(taskcapt, pathid))

	# Resource consumption profile file name
	rcpoutp = ''.join((_RESDIR, algname, '/', measure, _EXTEXECTIME))
	jobs = []
	# Traverse over directories of clusters corresponding to the base network
	for clsbase in glob.iglob(''.join((_RESDIR, algname, '/', _CLSDIR, escapePathWildcards(taskcapt), '*'))):
		# Skip execution of log files, leaving only dirs
		if not os.path.isdir(clsbase):
			continue
		# Note: algorithm parameters are present in dirs and handled here together with shuffles and sinstance / pathid
		clsname = os.path.split(clsbase)[1]  # Processing a cluster dir, which is a base name of the job, id part of the task name
		clsnameLen = len(clsname)

		# Skip cases when processing clusters does not have expected pathid
		if pathid and not clsname.endswith(pathid):
			continue
		# Skip cases whtn processing clusters have unexpected pathid
		elif not pathid:
			icnpid = clsname.rfind(_SEPPATHID)  # Index of pathid in clsname
			if icnpid != -1 and icnpid + 1 < clsnameLen:
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
		ish = clsname[:icnpid].rfind(_SEPSHF) + 1  # Note: reverse direction to skip possible separator symbols in the name itself
		shuffle = clsname[ish:icnpid] if ish else ''
		# Validate shufflng index
		if shuffle:
			try:
				int(shuffle)
			except ValueError as err:
				print('WARNING, invalid suffix or the separator "{}" represents part of the path "{}", exception: {}. Skipped.'
					.format(_SEPSHF, clsname, err), file=sys.stderr)
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
		taskoutp = logsbase
		if shuffle:
			taskoutp = taskoutp.rsplit(_SEPSHF, 1)[0]
			# Recover lost pathid if required
			if pathid:
				taskoutp += pathid
		taskoutp = '.'.join((taskoutp, measure))  # evalext  # Name of the file with modularity values for each level
		if tidy and os.path.exists(taskoutp):
			os.remove(taskoutp)

		#shuffagg = ShufflesAgg(resagg, name=_SEPNAMEPART.join((measure, algname, taskcapt, pathid)))  # Note: taskcapt here without alg params
		taskname = os.path.splitext(os.path.split(taskoutp)[1])[0]
		shagg = ShufflesAgg(resagg, _SEPNAMEPART.join((measure, algname, taskname)))
		task = Task(name=taskname, params=shagg, ondone=shagg.fix)  # , params=EvalState(taskcapt, )
		# Traverse over all resulting communities for each ground truth, log results
		for cfile in glob.iglob(escapePathWildcards(clsbase) + '/*'):
			if os.path.isdir(cfile):  # Skip dirs among the resulting clusters (extra/, generated by OSLOM)
				continue
			# Extract base name of the evaluating clusters level
			# Note: benchmarking algortihm output file names are not controllable and can be any, unlike the embracing folders
			jbasename = os.path.splitext(os.path.split(cfile)[1])[0]
			assert jbasename, 'The clusters name should exists'
			# Extand job caption with the executing task if not already contains and update the caption index
			# Skip pathid in clsname, because it is not present in jbasename
			pos = jbasename.find(clsname[:icnpid])
			# Define clusters level name as part of the jbasename
			if pos == -1:
				pos = 0
				jbasename = '_'.join((clsname[:icnpid], jbasename))  # Note: pathid is already included into clsname
			#elif pathid:
			#	jbasename += pathid
			clslev = jbasename[pos + icnpid:].lstrip('_-.')  # Note: clslev can be empty if jbasename == clsname[:icnpid]
			#print('Lev naming: clslev = {}, jbasename = {}'.format(clslev, jbasename))
			# Note: it's better to path clsname and shuffle separately to avoid redundant cut on evaluations processing
			#if shuffle:
			#	clslev = _SEPNAMEPART.join((clslev, shuffle))

			#jobname = _SEPNAMEPART.join((measure, algname, clsname))
			logfilebase = '/'.join((logsbase, jbasename))
			# pathid must be part of jobname, and  bun not of the clslev
			jobs.append(evaljob(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logfilebase))
	# Run all jobs after all of them were added to the task
	if jobs:
		for job in jobs:
			try:
				execpool.execute(job)
			except Exception as err:
				print('WARNING, "{}" job is interrupted by the exception: {}. {}'
					.format(job.name, err, traceback.format_exc()), file=sys.stderr)
	else:
		print('WARNING, "{}" clusters from "{}" do not exist to be evaluated'
			.format(algname, basefile), file=sys.stderr)


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
	if _DEBUG_TRACE:
		print('Evaluating {} for "{}" on base of "{}"...'.format(measure, algname, basefile))

	def evaljobMod(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase):
		"""Produce modularity evaluation job
		NOTE: all paths are given relative to the root benchmark directory.

		cfile  - clusters file to be evaluated
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		logsbase  - base part of the file name for the logs including errors

		return
			job  - resulting evaluating job
		"""
		#print('Starting evaljobMod with params:\t[basefile: {}]\n\tcfile: {}\n\tjobname: {}'
		#	'\n\ttask.name: {}\n\ttaskoutp: {}\n\tjobsuff: {}\n\tlogsbase: {}'
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
				print('ERROR, job "{}" has invalid output format. Moularity value is not found in: {}'
					.format(job.name, result), file=sys.stderr)
				return

			# Transfer resutls to the embracing task if exists
			taskoutp = job.params['taskoutp']
			clslev = job.params['clslev']
			task.params.addraw(taskoutp, clslev, mod)  # Note: task.params is shuffles aggregator
			# Log results
			with open(taskoutp, 'a') as tmod:  # Append to the end
				if not os.fstat(tmod.fileno()).st_size:
					tmod.write('# Q\tlevel[/shuffle]\n')
					tmod.flush()
				# Define result caption
				shuffle = job.params['shuffle']
				if shuffle:
					clslev = _SEPNAMEPART.join((clslev, shuffle))
				tmod.write('{}\t{}\n'.format(mod, clslev))

		return Job(name=_SEPSHF.join((task.name, shuffle)), workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			# Output modularity to the proc PIPE buffer to be aggregated on postexec to avoid redundant files
			, stdout=PIPE, stderr=logsbase + _EXTERR)


	def evaljobNmi(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase):
		"""Produce nmi evaluation job

		cfile  - clusters file to be evaluated
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		logsbase  - base part of the file name for the logs including errors

		return
			job  - resulting evaluating job


		Args example:
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
		# Update current environmental variables with LD_LIBRARY_PATH
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
		jobname = _SEPSHF.join((task.name, shuffle))  # Name of the creating job
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
				taskoutp = job.params['taskoutp']
				clslev = job.params['clslev']
				task.params.addraw(taskoutp, clslev, nmi)  # Note: task.params is shuffles aggregator
				# Log results
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.fstat(tnmi.fileno()).st_size:
						tnmi.write('# NMI\tlevel[/shuffle]\n')
						tnmi.flush()
					# Define result caption
					shuffle = job.params['shuffle']
					if shuffle:
						clslev = _SEPNAMEPART.join((clslev, shuffle))
					tnmi.write('{}\t{}\n'.format(nmi, clslev))

		return Job(name=jobname, task=task, workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			, stdout=PIPE, stderr=logsbase + _EXTERR)


	def evaljobNmiS(cfile, task, taskoutp, clslev, shuffle, rcpoutp, logsbase):
		"""Produce nmi_s evaluation job

		cfile  - clusters file to be evaluated
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		clslev  - clusters level name
		shuffle  - shuffle index as string or ''
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		logsbase  - base part of the file name for the logs including errors

		return
			job  - resulting evaluating job
		"""
		# Processing is performed from the algorithms dir
		jobname = _SEPSHF.join((task.name, shuffle))  # Name of the creating job
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
				taskoutp = job.params['taskoutp']
				clslev = job.params['clslev']
				task.params.addraw(taskoutp, clslev, nmi)  # Note: task.params is shuffles aggregator
				# Log results
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.fstat(tnmi.fileno()).st_size:
						tnmi.write('# NMI_s\tlevel[/shuffle]\n')
						tnmi.flush()
					# Define result caption
					shuffle = job.params['shuffle']
					if shuffle:
						clslev = _SEPNAMEPART.join((clslev, shuffle))
					tnmi.write('{}\t{}\n'.format(nmi, clslev))

		return Job(name=jobname, task=task, workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=aggLevs, params={'taskoutp': taskoutp, 'clslev': clslev, 'shuffle': shuffle}
			, stdout=PIPE, stderr=logsbase + _EXTERR)


	if measure == 'mod':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobMod, resagg, pathid)
	elif measure == 'nmi':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobNmi, resagg, pathid)
	elif measure == 'nmi_s':
		evalGeneric(execpool, measure, algname, basefile, measure + '/', timeout, evaljobNmiS, resagg, pathid, tidy=False)
	else:
		raise ValueError('Unexpected measure: ' + measure)
