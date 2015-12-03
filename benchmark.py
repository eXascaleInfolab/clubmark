#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: The benchmark, winch optionally generates or preprocesses datasets using specified executable,
	optionally executes specified apps with the specified params on the specified datasets,
	and optionally evaluates results of the execution using specified executable(s).

	All executions are traced and logged also as resources consumption: CPU (user, kernel, etc.) and memory (RSS RAM).
	Traces are saved even in case of internal / external interruptions and crashes.


	Using this generic benchmarking framework,
	= Overlapping Hierarchical Clustering Benchmark =
	is implemented:
	- synthetic datasets are generated using extended LFR Framework (origin: https://sites.google.com/site/santofortunato/inthepress2,
		which is "Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities"
		by Andrea Lancichinetti 1 and Santo Fortunato)
	- executes HiReCS (www.lumais.com/hirecs), Louvain (original https://sites.google.com/site/findcommunities/ and igraph implementations),
		Oslom2 (http://www.oslom.org/software.htm) and Ganxis/SLPA (https://sites.google.com/site/communitydetectionslpa/) clustering algorithms
		on the generated synthetic networks
	- evaluates results using NMI for overlapping communities, extended versions of:
		* gecmi (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
		* onmi (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms"
		  by  Aaron F. McDaid, Derek Greene, Neil Hurley)
	- resources consumption is evaluated using exectime profiler (https://bitbucket.org/lumais/exectime/)

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-04
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import sys
import time
import subprocess
from multiprocessing import cpu_count
import os
import shutil
import signal  # Intercept kill signals
from math import sqrt
import glob
from itertools import chain

import benchapps  # Benchmarking apps (clustering algs)
from benchcore import *
from benchutils import *


# Add 3dparty modules
#sys.path.insert(0, '3dparty')  # Note: this operation might lead to ambiguity on paths resolving
thirdparty = __import__('3dparty.tohig')
tohig = thirdparty.tohig.tohig  # ~ from 3dparty.tohig import tohig
#from tohig import tohig
#from functools import wraps

from benchcore import _extexectime
from benchcore import _extclnodes
from benchcore import _execpool
from benchapps import _algsdir
from benchapps import _resdir
from benchapps import pyexec


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_syntdir = 'syntnets/'  # Default directory for the synthetic datasets
_synetsnum = 8  # Default number of instances of each synthetic network
_extnetfile = '.nsa'  # Extension of the network files to be executed by the algorithms; Network specified by tab/space separated arcs
#_algseeds = 9  # TODO: Implement


def parseParams(args):
	"""Parse user-specified parameters

	return
		gensynt  - generate synthetic networks:
			0 - do not generate
			1 - generate only if this network is not exist
			2 - force geration (overwrite all)
		netins  - number of network instances for each network type to be generated, >= 1
		shufnum  - number of shuffles of each network instance to be produced, >= 0
		convnets  - convert existing networks into the .hig format
			0 - do not convert
			0b001  - convert:
				0b01 - convert only if this network is not exist
				0b11 - force conversion (overwrite all)
			0b100 - resolve duplicated links on conversion
		datas  - list of datasets to be run with asym flag (asymmetric / symmetric links weights):
			[(<asym>, <path>), ...] , where path is either dir or file
		timeout  - execution timeout in sec per each algorithm
		algorithms  - algorithms to be executed (just names as in the code)
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	gensynt = 0
	netins = _synetsnum  # Number of network instances to generate, >= 1
	shufnum = 0  # Number of shuffles for each network instance to be produced, >=0
	convnets = 0
	runalgs = False
	evalres = 0  # 1 - NMIs, 2 - Q, 3 - all measures
	datas = []  # list of pairs: (<asym>, <path>), where path is either dir or file
	#asym = None  # Asymmetric dataset, per dataset
	timeout = 36 * 60*60  # 36 hours
	timemul = 1  # Time multiplier, sec by default
	algorithms = None

	for arg in args:
		# Validate input format
		if arg[0] != '-':
			raise ValueError('Unexpected argument: ' + arg)

		if arg[1] == 'g':
			gensynt = 1  # Generate if not exists
			alen = len(arg)
			if alen == 2:
				continue
			pos = arg.find('=', 2)
			if arg[2] not in 'f=' or alen == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			if arg[2] == 'f':
				gensynt = 2  # Forced generation (overwrite)
			if pos != -1:
				# Parse number of instances and shuffles:  <instances>.<shuffles>
				val = arg[pos+1:].split('.', 1)
				netins = int(val[0])
				if len(arg) > 1:
					shufnum = int(val[1])
				if netins <= 0 or shufnum < 0:
					raise ValueError('Value is out of range:  netins: {netins} >= 1, shufnum: {shufnum} >= 0'
						.format(netins=netins, shufnum=shufnum))
		elif arg[1] == 'a':
			if not (arg[0:3] == '-a=' and len(arg) >= 4):
				raise ValueError('Unexpected argument: ' + arg)
			algorithms = arg[3:].split()
		elif arg[1] == 'c':
			convnets = 1
			for i in range(2,4):
				if len(arg) > i and (arg[i] not in 'fr'):
					raise ValueError('Unexpected argument: ' + arg)
			arg = arg[2:]
			if 'f' in arg:
				convnets |= 0b10
			if 'r' in arg:
				convnets |= 0b100
		elif arg[1] == 'r':
			if arg != '-r':
				raise ValueError('Unexpected argument: ' + arg)
			runalgs = True
		elif arg[1] == 'e':
			for i in range(2,4):
				if len(arg) > i and (arg[i] not in 'nm'):
					raise ValueError('Unexpected argument: ' + arg)
			if len(arg) in (2, 4):
				evalres = 3  # all
			# Here len(arg) >= 3
			elif arg[2] == 'n':
				evalres = 1  # NMIs
			else:
				evalres = 2  # Q (modularity)
		elif arg[1] == 'd' or arg[1] == 'f':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'as=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			# Extend weighted / unweighted dataset, default is unweighted
			asym = None  # Asym: None - not specified (symmetric is assumed), False - symmetric, True - asymmetric
			if arg[2] == 'a':
				asym = True
			elif arg[2] == 's':
				asym = False
			datas.append((asym, arg[pos+1:]))
		elif arg[1] == 't':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'smh=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			if arg[2] == 'm':
				timemul = 60  # Minutes
			elif arg[2] == 'h':
				timemul = 3600  # Hours
			timeout = float(arg[pos:]) * timemul
		else:
			raise ValueError('Unexpected argument: ' + arg)

	return gensynt, netins, shufnum, convnets, runalgs, evalres, datas, timeout, algorithms


def generateNets(overwrite=False, count=8, shufnum=0):
	"""Generate synthetic networks with ground-truth communities and save generation params

	overwrite  - whether to overwrite existing networks or use them
	count  - number of insances of each network to be generated, >= 1
	shufnum  - number of shufflings for of each instance on the generated network, >= 0
	"""
	paramsdir = 'params/'  # Contains networks generation parameters per each network type
	seedsdir = 'seeds/'  # Contains network generation seeds per each network instance
	netsdir = 'networks/'  # Contains subdirs, each contains all instances of each network and all shuffles of each instance
	# Note: shuffles unlike ordinary networks have double extension: shuffling nimber and standard extension

	# Store all instances of each network with generation parameters in the dedicated directory
	assert count >= 1, 'Number of the network instances to be generated must be positive'
	assert shufnum >= 0, 'Number of shufflings must be non-negative'
	assert _syntdir[-1] == '/' and paramsdir[-1] == '/' and seedsdir[-1] == '/' and netsdir[-1] == '/', "Directory name must have valid terminator"
	
	paramsdirfull = _syntdir + paramsdir
	seedsdirfull = _syntdir + seedsdir
	netsdirfull = _syntdir + netsdir
	# Backup params dirs on rewriting
	if overwrite:
		for dirname in (paramsdirfull, seedsdirfull, netsdirfull):
			if os.path.exists(dirname) and not dirempty(dirname):
				backupPath(dirname, SyncValue())
				
	# Create dirs if required
	if not os.path.exists(_syntdir):
		os.mkdir(_syntdir)
	for dirname in (paramsdirfull, seedsdirfull, netsdirfull):
		if not os.path.exists(dirname):
			os.mkdir(dirname)
		
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
	varNmul = (1, 2, 5, 10, 25, 50)  # *N0 - sizes of the generating networks
	vark = (5, 10)  #, 20)  # Average density of network links
	global _execpool
				
	_execpool = ExecPool(max(cpu_count() - 1, 1))
	netgenTimeout = 15 * 60  # 15 min
	shuftimeout = 1 * 60  # 1 min per each shuffling
	bmname = 'lfrbench_udwov'  # Benchmark name
	bmbin = './' + bmname  # Benchmark binary
	timeseed = _syntdir + 'time_seed.dat'
	
	def shuffle(job):
		"""Shufling postprocessing"""
		if shufnum < 1:
			return
		args = (pyexec, '-c',
"""import os
import subprocess

basenet = '{jobname}' + '{_extnetfile}'
for i in range(1, {shufnum} + 1):
	# sort -R pgp_udir.net -o pgp_udir_rand3.net
	netfile = ''.join(('{jobname}', '.', str(i), '{_extnetfile}'))
	if {overwrite} or not os.path.exists(netfile):
		subprocess.call(('sort', '-R', basenet, '-o', netfile))
""".format(jobname=job.name, _extnetfile=_extnetfile, shufnum=shufnum, overwrite=overwrite))
		_execpool.execute(Job(name=job.name + '_shf', task=job.task, workdir=netsdirfull + job.task.name
			, args=args, timeout=shuftimeout * shufnum))

	# Check whether time seed exists and create it if required
	if not os.path.exists(timeseed):  # Note: overwrite is not relevant here
		proc = subprocess.Popen((bmbin), bufsize=-1, cwd=_syntdir)
		proc.wait()
		assert os.path.exists(timeseed), timeseed + ' must be created'
	for nm in varNmul:
		N = nm * N0
		for k in vark:
			name = 'K'.join((str(nm), str(k)))
			ext = '.ngp'  # Network generation parameters
			# Generate network parameters files if not exist
			fnamex = name.join((paramsdirfull, ext))
			if overwrite or not os.path.exists(fnamex):
				print('Generating {} parameters file...'.format(fnamex))
				with open(fnamex, 'w') as fout:
					genopts.update({'N': N, 'k': k})
					genopts.update({'maxk': evalmaxk(genopts), 'muw': evalmuw(genopts), 'minc': evalminc(genopts)
						, 'maxc': evalmaxc(genopts), 'on': evalon(genopts), 'name': name})
					for opt in genopts.items():
						fout.write(''.join(('-', opt[0], ' ', str(opt[1]), '\n')))
			else:
				assert os.path.isfile(fnamex), '{} should be a file'.format(fnamex)
			# Generate networks with ground truth corresponding to the parameters
			if os.path.isfile(fnamex):  # TODO: target
				netpath = name.join((netsdir, '/'))  # syntnets/networks/<netname>/  netname.*
				netparams = name.join((paramsdir, ext))  # syntnets/params/<netname>.<ext>
				# Generate required number of network instances
				if _execpool:
					netpathfull = _syntdir + netpath
					if not os.path.exists(netpathfull):
						os.mkdir(netpathfull)
					task = Task(name)  # Required to use task.name as basedir identifier
					startdelay = 0.1  # Required to start execution of the LFR benchmark before copying the time_seed for the following process
					netfile = netpath + name
					if overwrite or not os.path.exists(netfile.join((_syntdir, _extnetfile))):
						args = ('../exectime', '-n=' + name, ''.join(('-o=', bmname, _extexectime))  # Output .rcp in the current dir, _syntdir
							, bmbin, '-f', netparams, '-name', netfile)
						#Job(name, workdir, args, timeout=0, ontimeout=False, onstart=None, ondone=None, tstart=None)
						_execpool.execute(Job(name=name, task=task, workdir=_syntdir, args=args, timeout=netgenTimeout, ontimeout=True
							, onstart=lambda job: shutil.copy2(timeseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
							, ondone=shuffle if shufnum > 0 else None, startdelay=startdelay))
					else:
						# Create missing shufflings
						shuffle(Job(name=name, task=task))
					for i in range(1, count):
						namext = ''.join((name, '_', str(i)))
						netfile = netpath + namext
						if overwrite or not os.path.exists(netfile.join((_syntdir, _extnetfile))):
							args = ('../exectime', '-n=' + namext, ''.join(('-o=', bmname, _extexectime))
								, bmbin, '-f', netparams, '-name', netfile)
							#Job(name, workdir, args, timeout=0, ontimeout=False, onstart=None, ondone=None, tstart=None)
							_execpool.execute(Job(name=namext, task=task, workdir=_syntdir, args=args, timeout=netgenTimeout, ontimeout=True
								, onstart=lambda job: shutil.copy2(timeseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
								, ondone=shuffle if shufnum > 0 else None, startdelay=startdelay))
						else:
							# Create missing shufflings
							shuffle(Job(name=namext, task=task))
			else:
				print('ERROR: network parameters file "{}" is not exist'.format(fnamex), file=sys.stderr)
	print('Parameter files generation is completed')
	if _execpool:
		_execpool.join(max(2 * 60*60, count * (netgenTimeout  + (shufnum * shuftimeout))))  # 2 hours
		_execpool = None
	print('Synthetic networks files generation is completed')


def convertNet(filename, asym, overwrite=False, resdub=False):
	"""Gonvert input networks to another formats

	datadir  - directory of the networks to be converted
	asym  - network has asymmetric links weights (in/outbound weights can be different)
	overwrite  - whether to overwrite existing networks or use them
	resdub  - resolve duplicated links
	"""
	try:
		# Convert to .hig format
		# Network in the tab separated weighted arcs format
		args = ['-f=ns' + ('a' if asym else 'e'), '-o' + ('f' if overwrite else 's')]
		if resdub:
			args.append('-r')
		tohig(net, args)
	except StandardError as err:
		print('ERROR on "{}" conversion into .hig, the network is skipped: {}'.format(net, err), file=sys.stderr)
	netnoext = os.path.splitext(net)[0]  # Remove the extension

	## Confert to Louvain binaty input format
	#try:
	#	# ./convert [-r] -i graph.txt -o graph.bin -w graph.weights
	#	# r  - renumber nodes
	#	# ATTENTION: original Louvain implementation processes incorrectly weighted networks with uniform weights (=1) if supplied as unweighted
	#	subprocess.call((_algsdir + 'convert', '-i', net, '-o', netnoext + '.lig'
	#		, '-w', netnoext + '.liw'))
	#except StandardError as err:
	#	print('ERROR on "{}" conversion into .lig, the network is skipped: {}'.format(net), err, file=sys.stderr)

	## Make shuffled copies of the input networks for the Louvain_igraph
	##if not os.path.exists(netnoext) or overwrite:
	#print('Shuffling {} into {} {} times...'.format(net, netnoext, _netshuffles))
	#if not os.path.exists(netnoext):
	#	os.makedirs(netnoext)
	#netname = os.path.split(netnoext)[1]
	#assert netname, 'netname should be defined'
	#for i in range(_netshuffles):
	#	outpfile = ''.join((netnoext, '/', netname, '_', str(i), _extnetfile))
	#	if overwrite or not sys.path.exists(outpfile):
	#		# sort -R pgp_udir.net -o pgp_udir_rand3.net
	#		subprocess.call(('sort', '-R', net, '-o', outpfile))
	##else:
	##	print('The shuffling is skipped: {} is already exist'.format(netnoext))


def convertNets(datadir, asym, overwrite=False, resdub=False):
	"""Gonvert input networks to another formats

	datadir  - directory of the networks to be converted
	asym  - network links weights are asymmetric (in/outbound weights can be different)
	overwrite  - whether to overwrite existing networks or use them
	resdub  - resolve duplicated links
	"""
	print('Converting networks from {} into the required formats (.hig, .lig, etc.)...'
		.format(datadir))
	# Convert network files into .hig format and .lig (Louvain Input Format)
	for net in glob.iglob('*'.join((datadir, _extnetfile))):
		convertNet(net, asym, overwrite, resdub)

	print('Networks conversion is completed')


def unknownApp(name):
	"""A stub for the unknown / not implemented apps (algorithms) to be benchmaked

	name  - name of the funciton to be called (traced and skipped)
	"""
	def stub(*args):
		print(' '.join(('ERROR: ', name, 'function is not implemented, the call is skipped.')), file=sys.stderr)
	stub.__name__ = name  # Set original name to the stub func
	return stub


def terminationHandler(signal, frame):
	"""Signal termination handler"""
	global _execpool

	#if signal == signal.SIGABRT:
	#	os.killpg(os.getpgrp(), signal)
	#	os.kill(os.getpid(), signal)

	if _execpool:
		del _execpool
		_execpool = None
	sys.exit(0)


def benchmark(*args):
	""" Execute the benchmark

	Run the algorithms on the specified datasets respecting the parameters.
	"""
	exectime = time.time()  # Start of the executing time
	gensynt, netins, shufnum, convnets, runalgs, evalres, datas, timeout, algorithms = parseParams(args)
	print('The benchmark is started, parsed params:\n\tgensynt: {}\n\tconvnets: {:b}'
		'\n\trunalgs: {}\n\tevalres: {}\n\tdatas: {}\n\ttimeout: {}\n\talgorithms: {}'
		.format(gensynt, convnets
			, runalgs, evalres
			, ', '.join(['{}{}'.format('' if not asym else 'asym: ', path) for asym, path in datas])
			, timeout, algorithms))
	# TODO: Implement consideration of udata, wdata (or just datadir - for some algs weighted/unweighted are defined from the file)
	# TODO: implement files and filters support, not only directories
	datadirs = []
	datafiles = []
	for asym, path in datas:
		if os.path.isdir(path):
			# Use the same path separator on all OSs
			if not path.endswith('/'):
				path += '/'
			datadirs.append((asym, path))
		else:
			datafiles.append((asym, path))
	datas = None
	if not datadirs and not datafiles:
		datadirs = [(False, _syntdir)]
	#print('Datadirs: ', datadirs)

	if gensynt:
		generateNets(gensynt == 2, netins, shufnum)  # 0 - do not generate, 1 - only if not exists, 2 - forced generation

	# convnets: 0 - do not convert, 0b01 - only if not exists, 0b11 - forced conversion, 0b100 - resolve duplicated links
	if convnets:
		for asym, ddir in datadirs:
			convertNets(ddir, asym, convnets&0b11, convnets&0b100)
		for asym, dfile in datafiles:
			convertNet(dfile, asym, convnets&0b11, convnets&0b100)

	global _execpool
	appsmodule = benchapps  # Module with algorithms definitions to be run; sys.modules[__name__]

	# Run the algorithms and measure their resource consumption
	if runalgs:
		# Run algs on synthetic datasets
		#udatas = ['../snap/com-dblp.ungraph.txt', '../snap/com-amazon.ungraph.txt', '../snap/com-youtube.ungraph.txt']
		assert not _execpool, '_execpool should be clear on algs execution'
		_execpool = ExecPool(max(min(4, cpu_count() - 1), 1))

		if not algorithms:
			#algs = (execLouvain, execHirecs, execOslom2, execGanxis, execHirecsNounwrap)
			#algs = (execHirecsNounwrap,)  # (execLouvain, execHirecs, execOslom2, execGanxis, execHirecsNounwrap)
			# , execHirecsOtl, execHirecsAhOtl, execHirecsNounwrap)  # (execLouvain, execHirecs, execOslom2, execGanxis, execHirecsNounwrap)
			algs = [getattr(appsmodule, func) for func in dir(appsmodule) if func.startswith('exec')]
		else:
			algs = [getattr(appsmodule, 'exec' + alg.capitalize(), unknownApp('exec' + alg.capitalize())) for alg in algorithms]
		algs = tuple(algs)

		def execute(net, asym, taksnum):
			"""Execute algorithms on the specified network counting number of ran tasks

			net  - network to be processed
			asym  - network links weights are asymmetric (in/outbound weights can be different)
			taksnum  - accumulated number of scheduled tasks
			
			return
				taksnum  - updated accumulated number of scheduled tasks
			"""
			for alg in algs:
				try:
					taksnum += alg(_execpool, net, asym, timeout)
				except StandardError as err:
					errexectime = time.time() - exectime
					print('The {} is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s)'
						.format(alg.__name__, err, errexectime, *secondsToHms(errexectime)))
			return taksnum

		taksnum = 1  # Number of networks tasks to be processed (can be a few per each algorithm per each network)
		netcount = 0  # Number of networks to be processed
		for asym, ddir in datadirs:
			for net in glob.iglob('*'.join((ddir, _extnetfile))):
				tnum = execute(net, asym, taksnum)
				taksnum += tnum
				netcount += tnum != 0
		for asym, net in datafiles:
			tnum = execute(net, asym, taksnum)
			taksnum += tnum
			netcount += tnum != 0

		if _execpool:
			timelim = timeout * taksnum
			print('Waiting for the algorithms execution on {} tasks from {} networks'
				' with {} sec ({} h {} m {:.4f} s) timeout'.format(taksnum, netcount, timelim, *secondsToHms(timelim)))
			_execpool.join(timelim)
			_execpool = None
		exectime = time.time() - exectime
		print('The benchmark execution is successfully comleted on {:.4f} sec ({} h {} m {:.4f} s)'
			.format(exectime, *secondsToHms(exectime)))

	# Evaluate results
	if evalres:
		# Create dir for the final results
		if not os.path.exists(_algsdir + _resdir):
			os.mkdir(_algsdir + _resdir)
		# measures is a mao with the Array values: <evalcallback_prefix>, <grounttruthnet_extension>, <measure_name>
		measures = {1: ['eval', _extclnodes, 'NMI'], 2: ['mod', '.hig', 'Q']}
		for im in measures:
			# Evaluate only required measures
			if evalres & im != im:
				continue

			evalpref = measures[im][0]  # Evaluation prefix
			if not algorithms:
				#evalalgs = (evalLouvain, evalHirecs, evalOslom2, evalGanxis
				#				, evalHirecsNS, evalOslom2NS, evalGanxisNS)
				#evalalgs = (evalHirecs, evalHirecsOtl, evalHirecsAhOtl
				#				, evalHirecsNS, evalHirecsOtlNS, evalHirecsAhOtlNS)
				evalalgs = [getattr(appsmodule, func) for func in dir(appsmodule) if func.startswith(evalpref)]
			else:
				if im == 1:
					assert evalpref == 'eval', 'Evaluation prefix is invalid'
					evalalgs = chain(*[(getattr(appsmodule, evalpref + alg.capitalize(), unknownApp(evalpref + alg.capitalize())),
						getattr(appsmodule, ''.join((evalpref, alg.capitalize(), 'NS')), unknownApp(''.join((evalpref, alg.capitalize(), 'NS')))))
						for alg in algorithms])
				else:
					assert evalpref == 'mod', 'Evaluation prefix is invalid'
					evalalgs = [getattr(appsmodule, evalpref + alg.capitalize(), unknownApp(evalpref + alg.capitalize()))
						for alg in algorithms]
			evalalgs = tuple(evalalgs)
			
			def evaluate(gtres, asym, taksnum):
				"""Evaluate algorithms on the specified network
	
				gtres  - ground truth results
				asym  - network links weights are asymmetric (in/outbound weights can be different)
				taksnum  - accumulated number of scheduled tasks
				
				return
					taksnum  - updated accumulated number of scheduled tasks
				"""
				for elg in evalalgs:
					try:
						elg(_execpool, gtres, timeout)
					except StandardError as err:
						print('The {} is interrupted by the exception: {}'
							.format(elg.__name__, err))
					else:
						taksnum += 1
				return taksnum
				

			print('Starting {} evaluation...'.format(measures[im][2]))
			assert not _execpool, '_execpool should be clear on algs evaluation'
			_execpool = ExecPool(max(cpu_count() - 1, 1))
			taksnum = 0
			timeout = 20 *60*60  # 20 hours
			for asym, ddir in datadirs:
				# Read ground truth
				for gtfile in glob.iglob('*'.join((ddir, measures[im][1]))):
					evaluate(gtfile, asym, taksnum)
			for asym, gtfile in datafiles:
				# Use files with required extension
				gtfile = os.path.splitext(gtfile)[0] + measures[im][1]
				evaluate(gtfile, asym, taksnum)
			if _execpool:
				_execpool.join(max(max(timeout, exectime * 2), timeout + 60 * taksnum))  # Twice the time of algorithms execution
				_execpool = None
			print('{} evaluation is completed'.format(measures[im][2]))
	print('The benchmark is completed')


if __name__ == '__main__':
	if len(sys.argv) > 1:
		# Set handlers of external signals
		signal.signal(signal.SIGTERM, terminationHandler)
		signal.signal(signal.SIGHUP, terminationHandler)
		signal.signal(signal.SIGINT, terminationHandler)
		signal.signal(signal.SIGQUIT, terminationHandler)
		signal.signal(signal.SIGABRT, terminationHandler)
		benchmark(*sys.argv[1:])
	else:
		print('\n'.join(('Usage: {0} [-g[f][=[<number>][.<shuffles_number>]] [-c[f][r]] [-a="app1 app2 ..."] [-r] [-e[n][m]] [-d{{a,s}}=<datasets_dir>] [-f{{a,s}}=<dataset>] [-t[{{s,m,h}}]=<timeout>]',
			'  -g[f][=[<number>][.<shuffles_number>]]  - generate <number> ({synetsnum} by default) >= 1 synthetic datasets in the {syntdir},'
			' shuffling each <shuffles_number> (0 by default) >= 0 times.',
			'  NOTE: shuffled datasets have the following naming format <net_name>.<shuffle_index>.<net_extension>',
			'    Xf  - force the generation even when the data already exists (existent datasets are moved to backup)',
			'  -c[X]  - convert existing networks into the .hig, .lig, etc. formats',
			'    Xf  - force the conversion even when the data is already exist',
			'    Xr  - resolve (remove) duplicated links on conversion. Note: this option is recommended to be used',
			'  -a="app1 app2 ..."  - apps (clustering algorithms) to run/benchmark among the implemented.'
			' Available: scp louvain_ig randcommuns hirecs oslom2 ganxis.'
			' Impacts -{{r, e}} options. Optional, all apps are executed by default.',
			'  NOTE: output results are stored in the "algorithms/<algname>outp/" directory',
			'  -r  - run the benchmarking apps on the prepared data',
			#'    Xf  - force execution even when the results already exists (existent datasets are moved to backup)',
			'  -e[[X]  - evaluate quality of the results. Default: apply all measurements',
			#'    Xf  - force execution even when the results already exists (existent datasets are moved to backup)',
			'    Xn  - evaluate results accuracy using NMI measures for overlapping communities',
			'    Xm  - evaluate results quality by modularity',
			# TODO: customize extension of the network files (implement filters)
			'  -d[X]=<datasets_dir>  - directory of the datasets.',
			'  -f[X]=<dataset>  - dataset (network, graph) file name.',
			'  NOTE: datasets file names must not contain "." (besides the extension),'
			' because it is used as indicator of the shuffled datasets',
			'    Xa  - the dataset is specified by asymmetric links (in/outbound weights of the link migh differ), arcs',
			'    Xs  - the dataset is specified by symmetric links, edges. Default option',
			'    Notes:',
			'    - multiple directories and files can be specified via multiple -d/f options (one per the item)',
			'    - datasets should have the following format: <node_src> <node_dest> [<weight>]',
			'    - {{a,s}} is considered only if the network file has no corresponding metadata (formats like SNAP, ncol, nsa, ...)',
			'    - ambiguity of links weight resolution in case of duplicates (or edges specified in both directions)'
			' is up to the clustering algorithm',
			'  -t[X]=<float_number>  - specifies timeout for each benchmarking application per single evaluation on each network'
			' in sec, min or hours. Default: 0 sec  - no timeout',
			'    Xs  - time in seconds. Default option',
			'    Xm  - time in minutes',
			'    Xh  - time in hours',
			)).format(sys.argv[0], syntdir=_syntdir, synetsnum=_synetsnum))
