#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: A modular benchmark, which optionally generates and pre-processes
	(shuffles, i.e. reorder nodes in the networks) datasets using specified
	executable, optionally executes specified applications (clustering algorithms)
	with specified parameters on the specified datasets, and optionally evaluates
	results of the execution using specified executable(s).

	All executions are traced and resources consumption is logged as:
	CPU (user, kernel, etc.) and memory (RSS RAM).
	Traces are saved even in case of internal / external interruptions and crashes.

	= Overlapping Hierarchical Clustering Benchmark =
	Implemented:
	- synthetic datasets are generated using extended LFR Framework (origin:
		https://sites.google.com/site/santofortunato/inthepress2, which is
		"Benchmarks for testing community detection algorithms on directed and
		weighted graphs with overlapping communities" by Andrea Lancichinetti 1
		and Santo Fortunato) and producing specified number of instances per
		each set of parameters (there can be varying network instances for the
		same set of generating parameters);
	- networks are shuffled (nodes are reordered) to evaluate stability /
		determinism of the clustering algorithm;
	- executes HiReCS (http://www.lumais.com/hirecs), Louvain (original
		https://sites.google.com/site/findcommunities/ and igraph implementations),
		Oslom2 (http://www.oslom.org/software.htm),
		Ganxis/SLPA (https://sites.google.com/site/communitydetectionslpa/) and
		SCP (http://www.lce.hut.fi/~mtkivela/kclique.html) clustering algorithms
		on the generated synthetic networks and real world networks;
	- evaluates results using NMI for overlapping communities, extended versions of:
		* gecmi (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers
			using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall),
		* onmi (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual
			Information to evaluate overlapping community finding algorithms" by
			Aaron F. McDaid, Derek Greene, Neil Hurley);
	- resources consumption is evaluated using exectime profiler (https://bitbucket.org/lumais/exectime/).

:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>,
	ScienceWise <http://sciencewise.info/>
:Date: 2015-04
"""
from __future__ import print_function, division  # Required for stderr output, must be the first import
# Extrenal API (exporting functions)
__all__ = ['generateNets', 'shuffleNets', 'convertNets', 'runApps', 'evalResults', 'benchmark']


# Required to efficiently traverse items of dictionaries in both Python 2 and 3
try:
	from future.builtins import range
except ImportError:
	# Replace range() implementation for Python2
	try:
		range = xrange
	except NameError:
		pass  # xrange is not defined in Python3, which is fine
import atexit  # At exit termination handling
import sys
import os
import shutil
import signal  # Intercept kill signals
import glob
import traceback  # Stacktrace
import copy
import itertools  # Iterables chaining
import time
# Consider time interface compatibility for Python before v3.3
if not hasattr(time, 'perf_counter'):  #pylint: disable=C0413
	time.perf_counter = time.time

from math import sqrt
from multiprocessing import cpu_count  # Returns the number of logical CPU units (HW treads) if defined

import benchapps  # Required for the functions name mapping to/from the app names
from benchapps import PYEXEC, aggexec, EXTCLNODES  # , ALGSDIR
from benchutils import viewitems, timeSeed, dirempty, tobackup, dhmsSec, syncedTime, \
	secDhms, delPathSuffix, parseName, funcToAppName, PREFEXEC, SEPPARS, SEPINST, SEPSHF, SEPPATHID, \
	SEPSUBTASK, UTILDIR, TIMESTAMP_START_STR, TIMESTAMP_START_HEADER, ALEVSMAX, ALGLEVS
# PYEXEC - current Python interpreter
import benchevals  # Required for the functions name mapping to/from the quality measures names
from benchevals import aggEvaluations, RESDIR, CLSDIR, QMSDIR, EXTEXECTIME, QMSRAFN, QMSINTRIN, QMSRUNS, \
	QualitySaver, NetInfo, SMeta
from utils.mpepool import AffinityMask, ExecPool, Job, Task, secondsToHms
from utils.mpewui import WebUiApp  #, bottle
from algorithms.utils.parser_nsl import asymnet, dflnetext

# if not bottle.TEMPLATE_PATH:
# 	bottle.TEMPLATE_PATH = []
# bottle.TEMPLATE_PATH.append('utils/views')

# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_SYNTDIR = 'syntnets/'  # Default base directory for the synthetic datasets (both networks, params and seeds)
_NETSDIR = 'networks/'  # Networks sub-directory of the synthetic networks (inside _SYNTDIR)
assert RESDIR.endswith('/'), 'A directory should have a valid terminator'
_SEEDFILE = RESDIR + 'seed.txt'
_PATHIDFILE = RESDIR + 'pathid.map'  # Path id map file for the results interpretation (mapping back to the input networks)
_TIMEOUT = 36 * 60*60  # Default execution timeout for each algorithm for a single network instance
_GENSEPSHF = '%'  # Shuffle number separator in the synthetic networks generation parameters
_WPROCSMAX = max(cpu_count()-1, 1)  # Maximal number of the worker processes, should be >= 1
assert _WPROCSMAX >= 1, 'Natural number is expected not exceeding the number of system cores'
_VMLIMIT = 4096  # Set 4 TB or RAM to be automatically limited to the physical memory of the computer
_PORT = 8080  # Default port for the WebUI, Note: port 80 accessible only from the root in NIX
_RUNTIMEOUT = 10*24*60*60  # Clustering execution timeout, 10 days
_EVALTIMEOUT = 5*24*60*60  # Results evaluation timeout, 5 days

#_TRACE = 1  # Tracing level: 0 - none, 1 - lightweight, 2 - debug, 3 - detailed
_DEBUG_TRACE = False  # Trace start / stop and other events to stderr

_webuiapp = None  # Global WebUI application
# Pool of executors to process jobs, the global variable is required to terminate
# the worker processes on external signal (TERM, KILL, etc.)
_execpool = None


# Data structures --------------------------------------------------------------
class PathOpts(object):
	"""Paths parameters"""
	__slots__ = ('path', 'flat', 'asym', 'shfnum')

	def __init__(self, path, flat=False, asym=False, shfnum=None):
		"""Sets default values for the input parameters

		path  - path (directory or file), a wildcard is allowed
		flat  - use flat derivatives or create the dedicated directory on shuffling
			to avoid flooding of the base directory.
			NOTE: variance over the shuffles of each network instance is evaluated
			only for the non-flat structure.
		asym  - the network is asymmetric (specified by arcs rather than edges),
			which is considered only for the non-standard file extensions (not .nsL)
		shfnum  - the number of shuffles of each network instance to be produced, >= 0;
			0 means do not produce any shuffles but process all existent
		"""
		# assert isinstance(path, str)
		self.path = path
		self.flat = flat
		self.asym = asym
		self.shfnum = shfnum  # Number of shuffles for each network instance to be produced, >= 0

	def __str__(self):
		"""String conversion"""
		# return ', '.join([': '.join((name, str(val))) for name, val in viewitems(self.__dict__)])
		return ', '.join([': '.join((name, str(self.__getattribute__(name)))) for name in self.__slots__])


class SyntPathOpts(PathOpts):
	"""Paths parameters for the synthetic networks"""
	__slots__ = ('netins', 'overwrite')

	def __init__(self, path, netins=3, overwrite=False, flat=False, asym=False, shfnum=0):
		"""Sets default values for the input parameters

		path  - path (directory or file), a wildcard is allowed
		netins  - the number of network instances to generate, >= 0
		overwrite  - overwrite or skip generation if the synthetic networks instances
			already exist
			NOTE: the shuffling is performed always anyway if it was specified
		flat  - use flat derivatives or create the dedicated directory on shuffling
			to avoid flooding of the base directory.
			NOTE: variance over the shuffles of each network instance is evaluated
			only for the non-flat structure.
		asym  - the network is asymmetric (specified by arcs rather than edges)
		shfnum  - the number of shuffles of each network instance to be produced, >= 0
		"""
		super(SyntPathOpts, self).__init__(path, flat, asym, shfnum)
		self.netins = netins
		self.overwrite = overwrite

	def __str__(self):
		"""String conversion"""
		return ', '.join((super(SyntPathOpts, self).__str__(), 'netins: ' + str(self.netins)
			, 'overwrite: ' + str(self.overwrite)))


class Params(object):
	"""Input parameters"""
	def __init__(self):
		"""Sets default values for the input parameters

		syntpo  - synthetic networks path options, SyntPathOpts
		runalgs  - execute algorithm or not
		qmeasures: list(list(str))  - quality measures with their parameters to be evaluated
			on the clustering results. None means do not evaluate.
		qupdate  - update quality evaluations storage (update with the lacking evaluations
			omitting the existent one until qrevalue is set) instead of creating a new storage
			for the quality measures evaluation, applicable only for the same seed.
			Otherwise a new storage is created and the existent is backed up.
		qrevalue  - revalue all values from scratch instead of leaving the existent values
			and (evaluating and) adding only the non-existent (lacking values), makes sense
			only if qupdate otherwise all values are computed anyway.
		datas: PathOpts  - list of datasets to be run with asym flag (asymmetric
			/ symmetric links weights):
			[PathOpts, ...] , where path is either dir or file [wildcard]
		timeout  - execution timeout in sec per each algorithm
		algorithms  - algorithms to be executed (just names as in the code)
		seedfile  - seed file name
		convnets: bits  - convert existing networks into the .rcg format, DEPRECATED
			0 - do not convert
			0b001  - convert:
				0b01 - convert only if this network is not exist
				0b11 - force conversion (overwrite all)
			0b100 - resolve duplicated links on conversion
			TODO: replace with IntEnum like in mpewui
		aggrespaths: iterable(str)  -  paths for the evaluated results aggregation
			(to be done for already existent evaluations)
			TODO: clarify and check availability in the latest version
		host: str  - WebUI host, None to disable WebUI
		port: int  - WebUI port
		runtimeout: uint  - clustering algorithms execution timeout
		evaltimeout: uint  - resulting clusterings evaluations timeout
		"""
		self.syntpo = None  # SyntPathOpts()
		self.runalgs = False
		self.qmeasures = None  # Evaluating quality measures with their parameters
		self.qupdate = True
		self.qrevalue = False
		self.datas = []  # Input datasets, list of PathOpts, where path is either dir or file wildcard
		self.timeout = _TIMEOUT
		self.algorithms = []
		self.seedfile = _SEEDFILE  # Seed value for the synthetic networks generation and stochastic algorithms, integer
		self.convnets = 0
		self.aggrespaths = []  # Paths for the evaluated results aggregation (to be done for already existent evaluations)
		# WebUI host and port
		self.host = None
		self.port = _PORT
		self.runtimeout = _RUNTIMEOUT
		self.evaltimeout = _EVALTIMEOUT


# Input parameters processing --------------------------------------------------
def parseParams(args):
	"""Parse user-specified parameters

	return params: Params
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	opts = Params()

	timemul = 1  # Time multiplier, sec by default
	for arg in args:
		# Validate input format
		if arg[0] != '-':
			raise ValueError('Unexpected argument: ' + arg)
		# Always output TIMESTAMP_START_HEADER to both stdout and stderr
		print(TIMESTAMP_START_HEADER)
		print(TIMESTAMP_START_HEADER, file=sys.stderr)
		# Process long args
		if arg[1] == '-':
			# if arg.startswith('--std'):
			# 	if arg == '--stderr-stamp':  # or arg == '--stdout-stamp':
			# 		#if len(args) == 1:
			# 		#	raise  ValueError('More input arguments are expected besides: ' + arg)
			# 		print(TIMESTAMP_START_HEADER, file=sys.stderr if arg == '--stderr-stamp' else sys.stdout)
			# 		continue
			# 	raise ValueError('Unexpected argument: ' + arg)
			if arg.startswith('--generate'):
				arg = '-g' + arg[len('--generate'):]
			elif arg.startswith('--input'):
				arg = '-i' + arg[len('--input'):]
			elif arg.startswith('--apps'):
				arg = '-a' + arg[len('--apps'):]
			elif arg.startswith('--runapps'):
				arg = '-r' + arg[len('--runapps'):]
			elif arg.startswith('--quality'):
				arg = '-q' + arg[len('--quality'):]
			elif arg.startswith('--timeout'):
				arg = '-t' + arg[len('--timeout'):]
			elif arg.startswith('--seedfile'):
				arg = '-d' + arg[len('--seedfile'):]
			elif arg.startswith('--convret'):
				arg = '-c' + arg[len('--convret'):]
			elif arg.startswith('--summary'):
				arg = '-s' + arg[len('--summary'):]
			elif arg.startswith('--webaddr'):
				arg = '-w' + arg[len('--webaddr'):]
			# Exclusive long options
			elif arg.startswith('--quality-noupdate'):
				opts.qupdate = False
			elif arg.startswith('--quality-revalue'):
				opts.qrevalue = True
			elif arg.startswith('--runtimeout'):
				nend = len('--runtimeout')
				if len(arg) <= nend + 1 or arg[nend] != '=':
					raise ValueError('Unexpected argument: ' + arg)
				opts.runtimeout = dhmsSec(arg[nend+1:])
				continue
			elif arg.startswith('--evaltimeout'):
				nend = len('--evaltimeout')
				if len(arg) <= nend + 1 or arg[nend] != '=':
					raise ValueError('Unexpected argument: ' + arg)
				opts.evaltimeout = dhmsSec(arg[nend+1:])
				continue
			else:
				raise ValueError('Unexpected argument: ' + arg)

		if arg[1] == 'g':
			# [-g[o][a]=[<number>][{gensepshuf}<shuffles_number>][=<outpdir>]
			opts.syntpo = SyntPathOpts(_SYNTDIR)
			alen = len(arg)
			if alen == 2:
				continue
			pos = arg.find('=', 2)
			ieflags = pos if pos != -1 else len(arg)  # End index of the prefix flags
			for i in range(2, ieflags):
				if arg[i] == 'o':
					opts.syntpo.overwrite = True  # Forced generation (overwrite)
				elif arg[i] == 'a':
					opts.syntpo.asym = True  # Generate asymmetric (directed) networks
				else:
					raise ValueError('Unexpected argument: ' + arg)
			if pos != -1:
				# Parse number of instances, shuffles and outpdir:  [<instances>][.<shuffles>][=<outpdir>]
				val = arg[pos+1:].split('=', 1)
				if val[0]:
					# Parse number of instances
					nums = val[0].split(_GENSEPSHF, 1)
					# Now [instances][shuffles][outpdir]
					if nums[0]:
						opts.syntpo.netins = int(nums[0])
					else:
						opts.syntpo.netins = 0  # Zero if omitted in case of shuffles are specified
					# Parse shuffles
					if len(nums) > 1:
						opts.syntpo.shfnum = int(nums[1])
					if opts.syntpo.netins < 0 or opts.syntpo.shfnum < 0:
						raise ValueError('Value is out of range:  netins: {netins} >= 1, shfnum: {shfnum} >= 0'
							.format(netins=opts.syntpo.netins, shfnum=opts.syntpo.shfnum))
				# Parse outpdir
				if len(val) > 1:
					if not val[1]:  # arg ended with '=' symbol
						raise ValueError('Unexpected argument: ' + arg)
					opts.syntpo.path = val[1]
					opts.syntpo.path = opts.syntpo.path.strip('"\'')
					if not opts.syntpo.path.endswith('/'):
						opts.syntpo.path += '/'
		elif arg[1] == 'i':
			# [-i[f][a][{gensepshuf}<shuffles_number>]=<datasets_{{dir,file}}_wildcard>
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'fa=' + _GENSEPSHF or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			# flat  - Use flat derivatives or generate the dedicated dir for the derivatives of this network(s)
			# asym  - asymmetric (directed): None - not specified (symmetric is assumed), False - symmetric, True - asymmetric
			# shfnum  - the number of shuffles
			popt = PathOpts(arg[pos+1:].strip('"\''), flat=False, asym=False, shfnum=0)  # Remove quotes if exist
			for i in range(2, pos):
				if arg[i] == 'f':
					popt.flat = True
				elif arg[i] == 'a':
					popt.asym = True
				elif arg[i] == _GENSEPSHF:
					popt.shfnum = int(arg[i+1:pos])
					if popt.shfnum < 0:
						raise ValueError('Value is out of range:  shfnum: {} >= 0'.format(popt.shfnum))
					break
				else:
					raise ValueError('Unexpected argument: ' + arg)
				val = arg[3]
			opts.datas.append(popt)
		elif arg[1] == 'c':
			opts.convnets = 1
			for i in range(2, 4):
				if len(arg) > i and (arg[i] not in 'fr'):
					raise ValueError('Unexpected argument: ' + arg)
			arg = arg[2:]
			if 'f' in arg:
				opts.convnets |= 0b10
			if 'r' in arg:
				opts.convnets |= 0b100
		elif arg[1] == 'a':
			if not (arg.startswith('-a=') and len(arg) >= 4):
				raise ValueError('Unexpected argument: ' + arg)
			inverse = arg[3] == '-'  # Consider inversing (run all except)
			if inverse and len(arg) <= 4:
				raise ValueError('Unexpected argument: ' + arg)
			opts.algorithms = arg[3 + inverse:].strip('"').strip("'").split()  # Note: argparse automatically performs this escaping
			# Exclude algorithms if required
			if opts.algorithms and inverse:
				algs = fetchAppnames(benchapps)
				try:
					for alg in opts.algorithms:
						algs.remove(alg)
				except ValueError as err:
					print('ERROR, "{}" does not exist: {}'.format(alg, err))
					raise
				opts.algorithms = algs
			# Note: all algs are run if not specified
		elif arg[1] == 'r':
			if len(arg) > 2:
				raise ValueError('Unexpected argument: ' + arg)
			opts.runalgs = True
		elif arg[1] == 'q':
			if not (arg == '-q' or (arg.startswith('-q=') and len(arg) >= 4)):
				raise ValueError('Unexpected argument: ' + arg)
			# Note: this option can be supplied multiple time with various values
			if opts.qmeasures is None:
				opts.qmeasures = []
			# Note: each argument is stored as an array item, which is either a parameter or its value
			opts.qmeasures.append(arg[3:].strip('"').strip("'").split())
		elif arg[1] == 's':
			if len(arg) <= 3 or arg[2] != '=':
				raise ValueError('Unexpected argument: ' + arg)
			opts.aggrespaths.append(arg[3:].strip('"\''))  # Remove quotes if exist
		elif arg[1] == 't':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'smh=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
			if arg[2] == '=':
				opts.timeout = dhmsSec(arg[pos:])
			else:
				if arg[2] == 'm':
					timemul = 60  # Minutes
				elif arg[2] == 'h':
					timemul = 3600  # Hours
				opts.timeout = float(arg[pos:]) * timemul
			assert opts.timeout >= 0, 'Non-negative timeout is expected'
		elif arg[1] == 'd':
			if len(arg) <= 3 or arg[2] != '=':
				raise ValueError('Unexpected argument: ' + arg)
			opts.seedfile = arg[3:]
		elif arg[1] == 'w':
			if len(arg) <= 3 or arg[2] != '=':
				raise ValueError('Unexpected argument: ' + arg)
			# Parse host and port
			host = arg[3:]
			if host:
				isep = host.rfind(':')
				if isep != -1:
					try:
						opts.port = int(host[isep+1:])
						opts.host = host[:isep]
					except ValueError:
						opts.port = _PORT
						opts.host = host
				else:
					opts.host = host
			# print('>>> Webaddr specified: {}, parced host: {}, port: {}'.format(
			# 	host, opts.host, opts.port), file=sys.stderr)
		else:
			raise ValueError('Unexpected argument: ' + arg)

	return opts


# Networks processing ----------------------------------------------------------
def generateNets(genbin, insnum, asym=False, basedir=_SYNTDIR, netsdir=_NETSDIR
, overwrite=False, seedfile=_SEEDFILE, gentimeout=3*60*60):  # 2-4 hours
	"""Generate synthetic networks with ground-truth communities and save generation params.
	Previously existed paths with the same name are backed up before being updated.

	genbin  - the binary used to generate the data (full path or relative to the base benchmark dir)
	insnum  - the number of instances of each network to be generated, >= 1
	asym  - generate asymmetric (specified by arcs, directed) instead of undirected networks
	basedir  - base directory where data will be generated
	netsdir  - relative directory for the synthetic networks, contains subdir-s,
		each contains all instances of each network and all shuffles of each instance
	overwrite  - whether to overwrite existing networks or use them
	seedfile  - seed file name
	gentimeout  - timeout for all networks generation in parallel mode, >= 0,
		0 means unlimited time
	"""
	paramsdir = 'params/'  # Contains networks generation parameters per each network type
	seedsdir = 'seeds/'  # Contains network generation seeds per each network instance

	# Store all instances of each network with generation parameters in the dedicated directory
	assert insnum >= 1, 'Number of the network instances to be generated must be positive'
	assert ((basedir == '' or basedir[-1] == '/') and paramsdir[-1] == '/' and seedsdir[-1] == '/' and netsdir[-1] == '/'
	 ), 'Directory name must have valid terminator'
	assert os.path.exists(seedfile), 'The seed file should exist'

	paramsdirfull = basedir + paramsdir
	seedsdirfull = basedir + seedsdir
	netsdirfull = basedir + netsdir
	# Initialize backup path suffix if required
	if overwrite:
		bcksuffix = syncedTime(lock=False)  # Use the same backup suffix for multiple paths

	# Create dirs if required
	for dirname in (basedir, paramsdirfull, seedsdirfull, netsdirfull):
		if not os.path.exists(dirname):
			os.mkdir(dirname)  # Note: mkdir does not create intermediate (non-leaf) dirs
		# Backup target dirs on rewriting, removing backed up content
		elif overwrite and not dirempty(dirname):
			tobackup(dirname, False, bcksuffix, move=True)  # Move to the backup
			os.mkdir(dirname)

	# Initial options for the networks generation
	N0 = 1000  # Satrting number of nodes
	rmaxK = 3  # Min ratio of the max degree relative to the avg degree
	# 1K ** 0.618 -> 71,  100K -> 1.2K

	def evalmaxk(genopts):
		"""Evaluate LFR maxk"""
		# 0.618 is 1/golden_ratio; sqrt(n), but not less than rmaxK times of the average degree
		# => average degree should be <= N/rmaxK
		return int(max(genopts['N'] ** 0.618, genopts['k']*rmaxK))

	def evalmuw(genopts):
		"""Evaluate LFR muw"""
		return genopts['mut'] * 0.75

	def evalminc(genopts):
		"""Evaluate LFR minc"""
		return 2 + int(sqrt(genopts['N'] / N0))

	def evalmaxc(genopts):
		"""Evaluate LFR maxc"""
		return int(genopts['N'] / 3)

	def evalon(genopts):
		"""Evaluate LFR on"""
		return int(genopts['N'] * genopts['mut']**2)  # The number of overlapping nodes

	# Template of the generating options files
	# mut: external cluster links / total links
	genopts = {'mut': 0.275, 'beta': 1.5, 't1': 1.75, 't2': 1.35, 'om': 2, 'cnl': 1}  # beta: 1.35, 1.2 ... 1.618;  t1: 1.65,
	# Defaults: beta: 1.5, t1: 2, t2: 1

	# Generate options for the networks generation using chosen variations of params
	varNmul = (1, 5, 20, 50)  # *N0 - sizes of the generating networks in thousands of nodes;  Note: 100K on max degree works more than 30 min; 50K -> 15 min
	vark = (5, 25, 75)  # Average node degree (density of the network links)
	#varNmul = (1, 5)  # *N0 - sizes of the generating networks in thousands of nodes;  Note: 100K on max degree works more than 30 min; 50K -> 15 min
	#vark = (5, 25)  # Average node degree (density of the network links)
	assert vark[-1] <= round(varNmul[0] * 1000 / rmaxK), 'Avg vs max degree validation failed'
	#varkr = (0.5, 1, 5)  #, 20)  # Average relative density of network links in percents of the number of nodes

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Note: AffinityMask.CORE_THREADS - set affinity in a way to maximize the CPU cache L1/2 for each process
	# 1 - maximizes parallelization => overall execution speed
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1)
	, memlimit=_VMLIMIT, name='gennets', webuiapp=_webuiapp) as _execpool:
		bmname = os.path.split(genbin)[1]  # Benchmark name
		genbin = os.path.relpath(genbin, basedir)  # Update path to the executable relative to the job workdir
		# Copy benchmark seed to the syntnets seed
		randseed = basedir + 'lastseed.txt'  # Random seed file name
		shutil.copy2(seedfile, randseed)

		netext = dflnetext(asym)  # Network file extension (should have the leading '.')
		asymarg = ['-a', '1'] if asym else None  # Whether to generate directed (specified by arcs) or undirected (specified by edges) network
		for nm in varNmul:
			N = nm * N0
			for k in vark:
				netgenTimeout = max(nm * k / 1.5, 30)  # ~ up to 30 min (>= 30 sec) per a network instance (50K nodes on K=75 takes ~15-35 min)
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
						for opt in viewitems(genopts):
							fout.write(''.join(('-', opt[0], ' ', str(opt[1]), '\n')))
				else:
					assert os.path.isfile(fnamex), '{} should be a file'.format(fnamex)
				# Recover the seed file is exists
				netseed = name.join((seedsdirfull, '.ngs'))
				if os.path.isfile(netseed):
					shutil.copy2(netseed, randseed)
					if _DEBUG_TRACE:
						print('The seed {netseed} is retained (but inapplicable for the shuffles)'.format(netseed=netseed))

				# Generate networks with ground truth corresponding to the parameters
				if os.path.isfile(fnamex):
					netpath = name.join((netsdir, '/'))  # syntnets/networks/<netname>/  netname.*
					netparams = name.join((paramsdir, ext))  # syntnets/params/<netname>.<ext>
					xtimebin = os.path.relpath(UTILDIR + 'exectime', basedir)
					jobseed = os.path.relpath(netseed, basedir)
					# Generate required number of network instances
					netpathfull = basedir + netpath
					if not os.path.exists(netpathfull):
						os.mkdir(netpathfull)
					startdelay = 0.1  # Required to start execution of the LFR benchmark before copying the time_seed for the following process
					netfile = netpath + name
					if _DEBUG_TRACE:
						print('Generating {netfile} as {name} by {netparams}'.format(netfile=netfile, name=name, netparams=netparams))
					if insnum and overwrite or not os.path.exists(netfile.join((basedir, netext))):
						args = [xtimebin, '-n=' + name, ''.join(('-o=', bmname, EXTEXECTIME))  # Output .rcp in the current dir, basedir
							, genbin, '-f', netparams, '-name', netfile, '-seed', jobseed]
						if asymarg:
							args.extend(asymarg)
						#Job(name, workdir, args, timeout=0, rsrtonto=False, onstart=None, ondone=None, tstart=None)
						_execpool.execute(Job(name=name, workdir=basedir, args=args, timeout=netgenTimeout, rsrtonto=True
							#, onstart=lambda job: shutil.copy2(randseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
							, onstart=lambda job: shutil.copy2(randseed, netseed)  #pylint: disable=W0640;  Network generation seed
							#, ondone=shuffle if shfnum > 0 else None
							, startdelay=startdelay, category='generate_' + str(k), size=N))
					for i in range(1, insnum):
						namext = ''.join((name, SEPINST, str(i)))
						netfile = netpath + namext
						if overwrite or not os.path.exists(netfile.join((basedir, netext))):
							args = [xtimebin, '-n=' + namext, ''.join(('-o=', bmname, EXTEXECTIME))
								, genbin, '-f', netparams, '-name', netfile, '-seed', jobseed]
							if asymarg:
								args.extend(asymarg)
							#Job(name, workdir, args, timeout=0, rsrtonto=False, onstart=None, ondone=None, tstart=None)
							_execpool.execute(Job(name=namext, workdir=basedir, args=args, timeout=netgenTimeout, rsrtonto=True
								#, onstart=lambda job: shutil.copy2(randseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
								, onstart=lambda job: shutil.copy2(randseed, netseed)  #pylint: disable=W0640;  Network generation seed
								#, ondone=shuffle if shfnum > 0 else None
								, startdelay=startdelay, category='generate_' + str(k), size=N))
				else:
					print('ERROR, network parameters file "{}" does not exist'.format(fnamex), file=sys.stderr)
		print('Parameter files generation completed')
		if gentimeout <= 0:
			gentimeout = insnum * netgenTimeout
		# Note: insnum*netgenTimeout is max time required for the largest instances generation,
		# insnum*2 to consider all smaller networks
		try:
			_execpool.join(min(gentimeout, insnum*2*netgenTimeout))
		except BaseException as err:  # Consider also system interruptions not captured by the Exception
			print('WARNING, network generation execution pool is interrupted by: {}. {}'
				.format(err, traceback.format_exc(5)), file=sys.stderr)
			raise
	_execpool = None
	print('Synthetic networks files generation completed')


def shuffleNets(datas, timeout1=7*60, shftimeout=30*60):  # 7, 30 min
	"""Shuffle specified networks backing up and updating existent shuffles.
	Existing shuffles with the target name are skipped, redundant are deleted,
	lacked are formed.

	datas  - input datasets, PathOpts with wildcards of files or directories
		containing files of the default extensions .ns{{e,a}}
	timeout1  - timeout for a single shuffle, >= 0
	shftimeout  - total shuffling timeout, >= 0, 0 means unlimited time
	"""
	if not datas:
		return
	assert isinstance(datas[0], PathOpts), 'datas must be a container of PathOpts'
	assert timeout1 + 0 >= 0, 'Non-negative shuffling timeout is expected'

	# Check whether the shuffling is required at all
	noshuf = True
	for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
		# Skip paths that do not require any shuffling
		if not popt.shfnum:
			continue
		noshuf = False
	if noshuf:
		return

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	shufnets = 0  # The number of shuffled networks
	# Note: afnstep = 1 because the processes are not cache-intensive, not None, because the workers are single-threaded
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1), memlimit=_VMLIMIT, name='shufnets') as _execpool:
		def shuffle(job):
			"""Shuffle network instance specified by the job"""
			#assert job.params, 'Job params should be defined'
			if job.params['shfnum'] < 1:
				return
			job.args = (PYEXEC, '-c',
			# Shuffling procedure
			"""from __future__ import print_function  #, division  # Required for stderr output, must be the first import
import os
import subprocess

basenet = '{jobname}' + '{netext}'
#print('basenet: ', basenet, file=sys.stderr)
i = 1
while i <= {shfnum}:
	# sort -R pgp_udir.net -o pgp_udir_rand3.net
	netfile = ''.join(('{jobname}', '{sepshf}', str(i), '{netext}'))
	if {overwrite} or not os.path.exists(netfile):
		with open(basenet) as inpnet:
			pos = 0
			ln = inpnet.readline()
			if ln.startswith('#'):
				print(''.join(('Shuffling ', basenet, ' to ', netfile)))
				# Shuffle considering the header
				# ('sort', '-R') or just ('shuf')
				wproc = subprocess.Popen(('shuf'), bufsize=-1, stdin=subprocess.PIPE, stdout=subprocess.PIPE)  # bufsize=-1 - use system default IO buffer size
				with open(netfile, 'w') as shfnet:
					body = ''  # File body
					while ln:
						# Write the header
						if ln.startswith('#'):
							shfnet.write(ln)
							pos = inpnet.tell()
							ln = inpnet.readline()
							continue
						inpnet.seek(pos)
						body = inpnet.read()
						break
					body = wproc.communicate(body.encode())[0]  # Fetch stdout (PIPE)
					shfnet.write(body.decode())
			else:
				# The file does not have a header
				# Note: "sort -R" sorts identical lines together unlike "shuf"
				#subprocess.call(('sort', '-R', basenet, '-o', netfile))
				subprocess.call(('shuf', basenet, '-o', netfile))
	i += 1
while True:
	netfile = ''.join(('{jobname}', '{sepshf}', str(i), '{netext}'))
	if os.path.exists(netfile):
		os.remove(netfile)
		i += 1
	else:
		break
""".format(jobname=job.name, sepshf=SEPSHF, netext=job.params['netext'], shfnum=job.params['shfnum']
			, overwrite=False))  # Skip the shuffling if the respective file already exists
			job.name += '_shf'  # Update jobname to clearly associate it with the shuffling process
			_execpool.execute(job)

		def shuffleNet(netfile, shfnum):
			"""Shuffle specified network producing specified number of shuffles in the same directory

			netfile  - the network instance to be shuffled
			shfnum  - the number of shuffles to be done

			return
				shfnum - number of shuffles to be produced or zero if the instance is a shuffle by itself
			"""
			# Remove existing shuffles if required
			path, name = os.path.split(netfile)
			if not path:
				path = '.'  # Note: '/' is added later
			name, netext = os.path.splitext(name)
			if name.find(SEPSHF) != -1:
				shf = name.rsplit(SEPSHF, 1)[1]
				# Omit shuffling of the shuffles, remove redundant shuffles
				if int(shf[1:]) > shfnum:
					os.remove(netfile)
				return 0
			# Note: the shuffling might be scheduled even when the shuffles exist in case
			# the origin network is traversed before its shuffles
			shuffle(Job(name=name, workdir=path + '/', params={'netext': netext, 'shfnum': shfnum}
				, timeout=timeout1*shfnum, category='shuffle', size=os.path.getsize(netfile)))
			return shfnum  # The network is shuffled shfnum times

		def prepareDir(dirpath, netfile, backup, bcksuffix=None):
			"""Make the dir if not exists, otherwise move to the backup if the dir is not empty.
			Link the original network inside the dir.

			dirpath  - directory to be initialized or moved to the backup
			netfile  - network file to be linked into the <dirpath> dir
			backup  - whether to backup the directory content
			bcksuffix: Value(time: float) or c_double  - backup suffix for the group of directories

			return  - shuffle0, the origin network filename for the shuffles
			"""
			# Make hard link of the origin network to the target dir if this file does not exist yet
			shuf0 = '/'.join((dirpath, os.path.split(netfile)[1]))
			if not os.path.exists(dirpath):
				os.mkdir(dirpath)
				# Hard link is used to have initial former copy of the archive even when the origin is deleted
				os.link(netfile, shuf0)
			# Avoid backup of the fully retained shuffles
			elif not dirempty(dirpath):
				if backup:
					tobackup(dirpath, False, bcksuffix, move=False)  # Copy to the backup to not regenerate existing networks
				if not os.path.exists(shuf0):
					os.link(netfile, shuf0)
			#if os.path.exists(dirpath) and not dirempty(dirpath):
			#	tobackup(dirpath, False, bcksuffix, move=True)  # Move to the backup
			#if not os.path.exists(dirpath):
			#	os.mkdir(dirpath)
			## Make hard link of the origin network to the target dir if this file does not exist
			#shuf0 = '/'.join((dirpath, os.path.split(netfile)[1]))
			#if not os.path.exists(shuf0):
			#	# Hard link is used to have initial former copy of the archive even when the origin is deleted
			#	os.link(netfile, shuf0)
			return shuf0

		def xpathExists(wildcard):
			"""Whether the path specified by the wildcard exist

			wildcard: str  - path wildcard

			return: bool  - path existence
			"""
			try:
				next(glob.iglob(wildcard))
			except StopIteration:
				return False  # Such path does not exist
			return True

		bcksuffix = syncedTime(lock=False)  # Use unified suffix for the backup of various network instances
		shfnum = 0  # Total number of shuffles
		for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
			#assert isinstance(popt, PathOpts), 'datas must be a container of PathOpts'
			# Skip paths that do not require any shuffling
			if not popt.shfnum:
				continue
			dflext = dflnetext(popt.asym)  # Default network extension for files in dirs
			# Resolve wildcards
			for path in glob.iglob(popt.path):  # Allow wildcards
				# Shuffle synthetic networks if required
				if os.path.isdir(path):
					# Use the same path separator on all OSs
					if not path.endswith('/'):
						path += '/'
					# Generate dirs if required
					if not popt.flat:
						# Traverse over the networks instances and create corresponding dirs
						for net in glob.iglob('*'.join((path, dflext))):  # Allow wildcards
							# Skip the shuffles if any to avoid dir preparation for them
							netname = os.path.split(net)[1]
							if netname.find(SEPSHF) != -1:
								continue
							# Whether the shuffles will be modified and need to be backed up
							backup = xpathExists(''.join((path, os.path.splitext(netname)[0]
								, '*', SEPSHF, str(popt.shfnum + 1), '*', dflext)))
							# Backup existed dir (path, not just a name)
							shuf0 = prepareDir(os.path.splitext(net)[0], net, backup, bcksuffix)
							shfnum += shuffleNet(shuf0, popt.shfnum)
					else:
						# Backup the whole dir of network instances with possible shuffles,
						# which are going to be shuffled
						tobackup(path, False, bcksuffix, move=False)  # Copy to the backup
						# Note: the folder containing the network instance originating the shuffling should not be deleted
						# notbacked = True
						for net in glob.iglob('*'.join((path, dflext))):
							# # Skip the shuffles if any to avoid dir preparation for them
							# netname = os.path.split(net)[1]
							# if netname.find(SEPSHF) != -1:
							# 	continue
							# # Whether the shuffles will be modified and need to be backed up
							# backup = xpathExists(''.join((path, os.path.splitext(netname)[0]
							# 	, '*', SEPSHF, str(popt.shfnum + 1), '*', dflext)))
							# if backup and notbacked:
							# 	tobackup(path, False, bcksuffix, move=False)  # Copy to the backup
							shfnum += shuffleNet(net, popt.shfnum)  # Note: shuffleNet() skips of the existing shuffles and performs their reduction
				else:
					# Skip shuffles and their direct backing up
					# Note: previous shuffles are backed up from their origin instance
					netname = os.path.split(path)[1]
					if netname.find(SEPSHF) != -1:
						continue
					# Generate dirs if required
					dirpath = os.path.splitext(path)[0]
					basename = os.path.splitext(netname)[0]
					if not popt.flat:
						# Whether the shuffles will be modified and need to be backed up
						backup = xpathExists(''.join((dirpath, '/', basename
							, '*', SEPSHF, str(popt.shfnum + 1), '*', dflext)))
						shuf0 = prepareDir(dirpath, path, backup, bcksuffix)
						shfnum += shuffleNet(shuf0, popt.shfnum)
					else:
						# Backup existing flat shuffles if any (expanding the base path), which will be updated the subsequent shuffling
						# Whether the shuffles will be modified and need to be backed up
						if xpathExists('*'.join((dirpath, SEPSHF + str(popt.shfnum + 1), dflext))):
							tobackup(os.path.split(path)[0], True, bcksuffix, move=False)  # Copy to the backup
						shfnum += shuffleNet(path, popt.shfnum)  # Note: shuffleNet() skips of the existing shuffles and performs their reduction
				shufnets += 1

		if shftimeout <= 0:
			shftimeout = shfnum * timeout1
		_execpool.join(min(shftimeout, shfnum * timeout1))
	_execpool = None
	if shufnets:
		print('Networks ({}) shuffling completed. NOTE: random seed is not supported for the shuffling'.format(shufnets))


def basenetTasks(netname, pathidsuf, basenets, rtasks):
	"""Fetch or make tasks for the specific base network name (with pathidsuf
	and without the instance and shuffle id)

	netname: str  - network name, possibly includes instance but NOT shuffle id
	pathidsuf: str  - network path id prepended with the path separator
	basenets: dict(basenet: str, nettasks: list(Task))  - tasks for the basenet
	rtasks: list(Task)  - root tasks for the running apps on all networks

	return  nettasks: list(Task) or None  - tasks for the basenet of the specified netname
	"""
	if not (rtasks and basenets):
		return None
	assert not pathidsuf or pathidsuf.startswith(SEPPATHID), 'Ivalid pathidsuf: ' + pathidsuf

	iename = netname.find(SEPINST)
	if iename == -1:
		basenet = os.path.splitext(netname)[0]  # Remove network extension if any
	else:
		basenet = netname[:iename]
	basenet += pathidsuf
	nettasks = basenets.get(basenet)
	if not nettasks and rtasks:
		nettasks = [Task(SEPSUBTASK.join((t.name, basenet)), task=t) for t in rtasks]
		basenets[basenet] = nettasks
	return nettasks


def updateNetInfos(netinfs, net, pathidsuf='', shfnum=0):
	"""Update networks info

	netinfs: dict(str, NetInfo)  - network meta information for each base network to be formed if not None
	net: str  - network file path
	pathidsuf: str  - network path id prepended with the path separator
	shfnum: uint  - the number of shuffles if specified excluding the origin
	"""
	assert not pathidsuf or pathidsuf.startswith(SEPPATHID), 'Ivalid pathidsuf: ' + pathidsuf
	netnameps = parseName(os.path.splitext(os.path.split(net)[1])[0], True)
	# Note: +1 to consider the origin
	ntinf = netinfs.setdefault(netnameps[0] + pathidsuf, NetInfo(nshf=shfnum+1))
	# Evaluate the number of instances only if not specified explicitly
	if netnameps[2]:
		ntinf.nins = max(ntinf.nins, int(netnameps[2][len(SEPINST):]) + 1)  # Note: +1 to form total number from id
	# Evaluate the number of shuffles only if it is not specified explicitly (or specified as 0)
	if not shfnum and netnameps[3]:
		ntinf.nshf = max(ntinf.nshf, int(netnameps[3][len(SEPSHF):]) + 1)  # Note: +1 to form total number from id
	# print('> updateNetInfos(), netinfs size: {}, net: {}, nins: {}, nshf: {}'.format(
	# 	len(netinfs), net, ntinf.nins, ntinf.nshf))


def processPath(popt, handler, xargs=None, dflextfn=dflnetext, tasks=None, netinfs=None):
	"""Process the specified path with the specified handler

	popt: PathOpts  - processing path options (the path is directory of file, not a wildcard)
	handler: callable  - handler to be called as handler(netfile, netshf, xargs, tasks),
		netshf means that the processing networks is a shuffle in the non-flat dir structure
	xargs: dict(str, val)  - extra arguments of the handler following after the processing network file
	dflextfn: callable  - function(asymflag) for the default extension of the input files in the path
	tasks: list(tasks)  - root tasks per each algorithm
	netinfs: dict(str, NetInfo)  - network meta information for each base network to be formed if not None
	"""
	# assert tasks is None or isinstance(tasks[0], Task), ('Unexpected task format: '
	# 	+ str(None) if not tasks else type(tasks[0]).__name__)
	# appnames  - names of the running apps to create be associated with the tasks
	assert os.path.exists(popt.path), 'Target path should exist'
	path = popt.path  # Assign path to a local variable to not corrupt the input data
	dflext = dflextfn(popt.asym)  # dflnetext(popt.asym)  # Default network extension for files in dirs
	pathidsuf = xargs['pathidsuf']
	# Base networks with their tasks (netname with the pathid
	# and without the instance and shuffle suffixes)
	bnets = {}

	def fetchNetInfo(path):
		"""Fetch net info by the path

		path: str  - network path

		return netinf: NetInfo  - network meta information if available
		"""
		return None if netinfs is None else netinfs[
			delPathSuffix(os.path.splitext(os.path.split(path)[1])[0], True) + pathidsuf]

	if os.path.isdir(path):
		# Traverse over the instances in the specified directory
		# Use the same path separator on all OSs
		if not path.endswith('/'):
			path += '/'
		# Take shuffles in subdirs if required
		# Note: the origin instance is mapped to the shuffles dir, so traverse only
		# the directories with shuffles if exist
		if not popt.flat:
			# Only the instances should be considered here
			if netinfs is not None:
				for net in glob.iglob('*'.join((path, dflext))):
					netname = os.path.split(net)[1]
					if netname.find(SEPSHF) != -1:
						continue
					updateNetInfos(netinfs, netname, pathidsuf, popt.shfnum)
			# Traverse over the networks instances
			for net in glob.iglob('*'.join((path, dflext))):  # Allow wildcards
				# Skip the shuffles if any to process only specified networks
				# (all target shuffles are located in the dedicated dirs for non-flat paths)
				netname = os.path.split(net)[1]
				if netname.find(SEPSHF) != -1:
					continue
				# Fetch base network name (without the instance and shuffle id)
				nettasks = basenetTasks(netname, pathidsuf, bnets, tasks)
				# #if popt.shfnum:  # ATTENTNION: shfnum may not be available for non-synthetic networks
				# Process dedicated dir of shuffles for the specified network,
				# the origin network itself is linked to the shuffles dir (inside it)
				dirname, ext = os.path.splitext(net)
				if os.path.isdir(dirname):
					# Shuffles exist for this network and located in the subdir together with the copy of origin
					# Update the number of shuffles if not specified, the netinfs entry is already created by the caller
					if netinfs and not popt.shfnum:
						for desnet in glob.iglob('/*'.join((dirname, ext))):
							updateNetInfos(netinfs, desnet, pathidsuf, popt.shfnum)
					for desnet in glob.iglob('/*'.join((dirname, ext))):
						handler(desnet, True, xargs, nettasks, netinf=fetchNetInfo(desnet))  # True - shuffle is processed in the non-flat dir structure
				else:
					handler(net, False, xargs, tasks, netinf=fetchNetInfo(dirname))  # Shufles do not exist for this network instance
		else:
			# Both shuffles (if exist any) and network instances are located in the same dir
			# Form network meta information if required
			if netinfs is not None:
				for net in glob.iglob('*'.join((path, dflext))):
					updateNetInfos(netinfs, net, pathidsuf, popt.shfnum)
			for net in glob.iglob('*'.join((path, dflext))):
				# Note: typically, shuffles and instances do not exist in the flat structure
				# or their number is small
				#
				# # Fetch base network name (without instance and shuffle id)
				# basenet = os.path.split(net)[1]
				# iename = basenet.find(SEPINST)
				# if iename != -1:
				# 	basenet = basenet[:iename]
				# iename = basenet.find(SEPSHF)
				# if iename != -1:
				# 	basenet = basenet[:iename]
				# basenet += pathidsuf
				# nettasks = bnets.get(basenet)
				# if not nettasks:
				# 	nettasks = [Task(SEPSUBTASK.join((t.name, basenet)), task=t) for t in tasks]
				# 	bnets[basenet] = nettasks
				handler(net, False, xargs, tasks, netinf=fetchNetInfo(net))
	else:
		if not popt.flat:
			# Skip the shuffles if any to process only specified networks
			# (all target shuffles are located in the dedicated dirs for non-flat paths)
			netname = os.path.split(path)[1]
			if netname.find(SEPSHF) != -1:
				return
			# Fetch base network name (without the instance and shuffle id)
			nettasks = basenetTasks(netname, pathidsuf, bnets, tasks)
			#if popt.shfnum:  # ATTENTNION: shfnum is not available for non-synthetic networks
			# Process dedicated dir of shuffles for the specified network,
			# the origin network itself is linked to the shuffles dir (inside it)
			dirname, ext = os.path.splitext(path)
			if os.path.isdir(dirname):
				# Update the number of shuffles if not specified, the netinfs entry is already created by the caller
				if netinfs and not popt.shfnum:
					for desnet in glob.iglob('/*'.join((dirname, ext))):
						updateNetInfos(netinfs, desnet, pathidsuf, popt.shfnum)
				for desnet in glob.iglob('/*'.join((dirname, ext))):
					# True - shuffle is processed in the non-flat dir structure
					handler(desnet, True, xargs, nettasks, netinf=fetchNetInfo(desnet))
			else:
				handler(path, False, xargs, tasks, netinf=fetchNetInfo(dirname))
		else:
			handler(path, False, xargs, tasks, netinf=fetchNetInfo(path))


def processNetworks(datas, handler, xargs={}, dflextfn=dflnetext, tasks=None, fpathids=None, metainf=False):  #pylint: disable=W0102
	"""Process input networks specified by the path wildcards

	datas: iterable(PathOpts)  - processing path options including the path wildcard
	handler: callable  - handler to be called in the processPath() as handler(netfile, netshf, xargs, tasks, netinf),
		netshf means that the processing networks is a shuffle in the non-flat dir structure
	xargs: dict(str, val)  - extra arguments of the handler following after the processing network file
	dflextfn: callable  - function(asymflag) for the default extension of the input files in the path
	tasks: list(tasks)  - root tasks per each executing application
	fpathids: File  - path ids file opened for the writing or None
	metainf: bool  - extract meta information about the processing networks
	"""
	# Track processed file names to resolve cases when files with the same name present in different input dirs
	# Note: pathids are required at least to set concise job names to see what is executed in runtime
	netsNameCtr = {}  # Net base name to counter mapping: {net base name: counter}
	netinfs = {}  # Base network name (with pathid) to network meta information (the number of shuffles, instances, etc.) mapping

	def procPath(pcuropt, path):
		"""Process path given the current path options"""
		# Assign resolved path from the wildcard
		pcuropt.path = path
		if _DEBUG_TRACE:
			print('  Scheduling apps execution for the path options ({})'.format(str(pcuropt)))
		processPath(pcuropt, handler, xargs=xargs, dflextfn=dflextfn, tasks=tasks
			, netinfs=None if not metainf else netinfs)

	for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
		xargs['asym'] = popt.asym
		# Resolve wildcards
		pcuropt = copy.copy(popt)  # Path options for the resolved .path wildcard
		# Note: each path (wildcard) here is associated with distinct set(s) of instances and shuffles ids
		# for im in range(1 + metainf):
		for path in glob.iglob(popt.path):  # Allow wildcards
			# Form pathid mapping as netsNameCtr
			if os.path.isdir(path):
				# ATTENTION: required to process directories ending with '/' correctly
				# Note: normpath() may change semantics in case symbolic link is used with parent dir:
				# base/linkdir/../a -> base/a, which might be undesirable
				mpath = path.rstrip('/')  # os.path.normpath(path)
			else:
				mpath = os.path.splitext(path)[0]
			net = os.path.split(mpath)[1]
			pathid = netsNameCtr.get(net)
			if pathid is None:
				netsNameCtr[net] = 0
				xargs['pathidsuf'] = ''
			else:
				# TODO: To unify quality measures evaluation with the clustering and consider pathids everywhere,
				# pathids dict should be used instead of the fpathids with pathid reading besides the writing.
				pathid += 1
				netsNameCtr[net] = pathid
				nameid = SEPPATHID + str(pathid)
				xargs['pathidsuf'] = nameid
				if fpathids is not None:
					fpathids.write('{}\t{}\n'.format(net + nameid, mpath))
			#if _DEBUG_TRACE >= 2:
			#	print('  Processing "{}", net: {}, pathidsuf: {}'.format(path, net, xargs['pathidsuf']))
			#  Process path if metainf formation is not required
			if not metainf:
				procPath(pcuropt, path)
			elif not os.path.isdir(path):  # Update netinfs only for the files of the path, others handled in the procPath()
				# Both shuffles (if exist any) and network instances are located in the same dir
				updateNetInfos(netinfs, path, xargs['pathidsuf'], popt.shfnum)
		# Process paths if have not been done yet because of the the meta information construction
		if metainf:
			for path in glob.iglob(popt.path):  # Allow wildcards
				procPath(pcuropt, path)


def convertNets(datas, overwrite=False, resdub=False, timeout1=7*60, convtimeout=30*60):  # 7, 30 min
	"""Convert input networks to another formats

	datas  - input datasets, wildcards of files or directories containing files
		of the default extensions .ns{{e,a}}
	overwrite  - whether to overwrite existing networks or use them
	resdub  - resolve duplicated links
	timeout1  - timeout for a single file conversion, >= 0
	convtimeout  - timeout for all networks conversion in parallel mode, >= 0,
		0 means unlimited time
	"""
	assert timeout1 + 0 >= 0, 'Non-negative network conversion timeout is expected'
	print('Converting networks to the required formats (.rcg, .lig, etc.)...')

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Note: afnstep = 1 because the processes are not cache-intensive, not None, because the workers are single-threaded
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1), memlimit=_VMLIMIT, name='convnets') as _execpool:
		def convertNet(inpnet, overwrite=False, resdub=False, timeout=7*60):  # 7 min
			"""Convert input networks to another formats

			inpnet  - the network file to be converted
			overwrite  - whether to overwrite existing networks or use them
			resdub  - resolve duplicated links
			timeout  - network conversion timeout, 0 means unlimited
			"""
			try:
				args = [PYEXEC, UTILDIR + 'convert.py', inpnet, '-o rcg', '-r ' + ('o' if overwrite else 's')]
				if resdub:
					args.append('-d')
				_execpool.execute(Job(name=os.path.splitext(os.path.split(inpnet)[1])[0], args=args, timeout=timeout
					, category='convert', size=os.path.getsize(inpnet)))
			except Exception as err:  #pylint: disable=W0703
				print('ERROR on "{}" conversion to .rcg, the conversion is canceled: {}. {}'
					.format(inpnet, err, traceback.format_exc(5)), file=sys.stderr)
			#netnoext = os.path.splitext(net)[0]  # Remove the extension
			#
			## Convert to Louvain binary input format
			#try:
			#	# ./convert [-r] -i graph.txt -o graph.bin -w graph.weights
			#	# r  - renumber nodes
			#	# ATTENTION: original Louvain implementation processes incorrectly weighted networks with uniform weights (=1) if supplied as unweighted
			#	subprocess.call((ALGSDIR + 'convert', '-i', net, '-o', netnoext + '.lig'
			#		, '-w', netnoext + '.liw'))
			#except Exception as err:
			#	print('ERROR on "{}" conversion into .lig, the network is skipped: {}'.format(net), err, file=sys.stderr)

		def converter(net, netshf, xargs):  #pylint: disable=W0613
			"""Network conversion helper

			net  - network file name
			netshf  - whether this network is a shuffle in the non-flat dir structure
			xargs  - extra custom parameters
			"""
			xargs['netsnum'] += 1
			convertNet(net, xargs.overwrite, xargs.resdub, xargs.timeout1)

		xargs = {'overwrite': overwrite, 'resdub': resdub, 'timeout1': timeout1, 'netsnum': 0}  # Number of converted networks
		for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
			# Resolve wildcards
			pcuropt = copy.copy(popt)  # Path options for the resolved wildcard
			for path in glob.iglob(popt.path):  # Allow wildcards
				pcuropt.path = path
				processPath(pcuropt, converter, xargs=xargs)  # Calls converter(net, netshf, xargs)

		netsnum = xargs['netsnum']
		if convtimeout <= 0:
			convtimeout = netsnum * timeout1
		_execpool.join(min(convtimeout, netsnum * timeout1))
	_execpool = None
	print('Networks ({}) conversion completed'.format(netsnum))


def fetchAppnames(appsmodule):
	"""Get names of the executable applications from the module

	appsmodule  - module that implements execution of the apps
	return  - list of the apps names
	"""
	return [funcToAppName(func) for func in dir(appsmodule) if func.startswith(PREFEXEC)]


def clarifyApps(appnames, appsmodule, namefn=None):
	"""Validate and refine or form appnames considering the appsmonule functions
	and fetch the respective executors

	appnames: list(str)  - names of the apps to be clarified or formed if empty
	appsmodule: module  - module with the respective app functions staring with PREFEXEC
	namefn: callable  - name extraction function if appnames is a list of (compound) objects

	return
		appfns: list(function)  - executor functions of the required apps
	"""
	assert isinstance(appnames, list) and appsmodule and (namefn is None or callable(namefn)
		), ('Invalid arguments, appnames type: {}, appsmodule type: {}, namefn type: {}'.format(
		type(appnames).__name__, type(appsmodule).__name__, type(namefn).__name__))
	if not appnames:
		# Save app names to perform results aggregation after the execution
		appnames.extend(fetchAppnames(appsmodule))  # alg.lower() for alg in fetchAppnames()
	# Fetch app functions (executors) from the module
	appfns = [getattr(appsmodule, PREFEXEC + name, None) for name in (
		appnames if namefn is None else [namefn(an) for an in appnames])]
	# Ensure that all specified appnames correspond to the functions
	invalapps = []  # Indexes of the applications having the invalid name (without the respective executor)
	for i in range(len(appfns)):
		if appfns[i] is None:
			invalapps.append(i)
	if invalapps:
		print('WARNING, the specified appnames are omitted as not existent: '
			, ' '.join([appnames[ia] for ia in invalapps]), file=sys.stderr)
		while invalapps:
			i = invalapps.pop()
			del appnames[i]
			del appfns[i]
	assert len(appnames) == len(appfns), 'appfns are not synced with the appnames'
	return appfns


def runApps(appsmodule, algorithms, datas, seed, exectime, timeout, runtimeout=10*24*60*60):  # 10 days
	"""Run specified applications (clustering algorithms) on the specified datasets

	appsmodule  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms: list(str)  - list of the algorithms to be executed
	datas: iterable(PathOpts)  - input datasets, wildcards of files or directories containing files
		of the default extensions .ns{{e,a}}
	seed  - benchmark seed, natural number
	exectime  - elapsed time since the benchmarking started
	timeout  - timeout per each algorithm execution
	runtimeout  - timeout for all algorithms execution, >= 0, 0 means unlimited time
	"""
	# return  netnames: iterable(str) or None  - network names with path id and without the base directory
	# netnames = None  # Network names with path id and without the base directory
	if not datas:
		print('WRANING runApps(), there are no input datasets specified to be clustered', file=sys.stderr)
		# return netnames
		return
	assert isinstance(algorithms, list) and appsmodule and isinstance(datas[0], PathOpts
		) and exectime + 0 >= 0 and timeout + 0 >= 0, ('Invalid input arguments, algorithms type: {}'
		', appsmodule type: {} datas type: {}, exectime: {}, timeout: {}'.format(type(algorithms).__name__
		, type(appsmodule).__name__, type(datas).__name__, exectime, timeout))
	assert isinstance(seed, int) and seed >= 0, 'Seed value is invalid'

	stime = time.perf_counter()  # Procedure start time; ATTENTION: .perf_counter() should not be used, because it does not consider "sleep" time
	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Note: set affinity in a way to maximize the CPU cache L1/2 for each process
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(AffinityMask.CORE_THREADS)
	, memlimit=_VMLIMIT, name='runapps', webuiapp=_webuiapp) as _execpool:
		# Run all algs if not specified the concrete algorithms to be run
		# # Algorithms callers
		# execalgs = [getattr(appsmodule, func) for func in dir(appsmodule) if func.startswith(PREFEXEC)]
		execalgs = clarifyApps(algorithms, appsmodule)

		def runapp(net, asym, netshf, pathidsuf='', tasks=None, netinf=None):
			"""Execute algorithms on the specified network counting number of ran jobs

			net  - network to be processed
			asym  - whether the network is asymmetric (directed), considered only for the
				non-standard network file extensions
			netshf  - whether this network is a shuffle in the non-flat dir structure
			pathidsuf: str  - network path id prepended with the path separator, used to distinguish nets
				with the same name located in different dirs
			tasks: list(Task)  - tasks associated with the running algorithms on the specified network
			netinf: NetInfo  - network meta information (the number of network instances and shuffles, etc.)

			return
				jobsnum  - the number of scheduled jobs, typically 1
			"""
			jobsnum = 0
			netext = os.path.splitext(net)[1].lower()
			for ia, ealg in enumerate(execalgs):
				try:
					jobsnum += ealg(_execpool, net, asym=asymnet(netext, asym), odir=netshf
						, timeout=timeout, seed=seed, task=None if not tasks else tasks[ia], pathidsuf=pathidsuf)
				except Exception as err:  #pylint: disable=W0703
					errexectime = time.perf_counter() - exectime
					print('ERROR, "{}" is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s), call stack:'
						.format(ealg.__name__, err, errexectime, *secondsToHms(errexectime)), file=sys.stderr)
					# traceback.print_stack(limit=5, file=sys.stderr)
					traceback.print_exc(5)
			return jobsnum

		def runner(net, netshf, xargs, tasks=None, netinf=None):
			"""Network runner helper

			net  - network file name
			netshf  - whether this network is a shuffle in the non-flat dir structure
			xargs  - extra custom parameters
			tasks: list(Task)  - tasks associated with the running algorithms on the specified network
			netinf: NetInfo  - network meta information (the number of network instances and shuffles, etc.)
			"""
			tnum = runapp(net, xargs['asym'], netshf, xargs['pathidsuf'], tasks, netinf)
			xargs['jobsnum'] += tnum
			xargs['netcount'] += tnum != 0

		# Prepare resulting paths mapping file
		fpathids = None  # File of paths ids
		if not os.path.exists(RESDIR):
			os.mkdir(RESDIR)
		try:
			fpathids = open(_PATHIDFILE, 'a')
		except IOError as err:
			print('WARNING, creation of the path ids map file is failed: {}. The mapping is outputted to stdout.'
				.format(err), file=sys.stderr)
			fpathids = sys.stdout
		try:
			# Write header if required
			#timestamp = datetime.utcnow()
			if not os.fstat(fpathids.fileno()).st_size:
				fpathids.write('# Name{}ID\tPath\n'.format(SEPPATHID))  # Note: buffer flushing is not necessary here, because the execution is not concurrent
			fpathids.write('# --- {time} (seed: {seed}) ---\n'.format(time=TIMESTAMP_START_STR, seed=seed))  # Write timestamp

			xargs = {'asym': False,  # Asymmetric network
				 'pathidsuf': '',  # Network path id prepended with the path separator, used to deduplicate the network name shortcut
				 'jobsnum': 0,  # Number of the processing network jobs (can be several per each instance if shuffles exist)
				 'netcount': 0}  # Number of processing network instances (includes multiple shuffles)
			tasks = [Task(appname) for appname in algorithms]
			# netnames =
			processNetworks(datas, runner, xargs=xargs, dflextfn=dflnetext, tasks=tasks, fpathids=fpathids)
			# netnames = None  # Free memory from filenames
		finally:
			# Flush the formed fpathids
			if fpathids:
				if fpathids is not sys.stdout and fpathids is not sys.stderr:
					fpathids.close()
				else:
					fpathids.flush()

		if runtimeout <= 0:
			runtimeout = timeout * xargs['jobsnum']
		timelim = min(timeout * xargs['jobsnum'], runtimeout)
		print('Waiting for the apps execution on {} jobs from {} networks'
			' with {} sec ({} h {} m {:.4f} s) timeout ...'
			.format(xargs['jobsnum'], xargs['netcount'], timelim, *secondsToHms(timelim)))
		# Note: all failed jobs of the ExecPool are hierarchically traced by the assigned tasks
		# (on both completion and termination)
		try:
			_execpool.join(timelim)
		except BaseException as err:  # Consider also system interruptions not captured by the Exception
			print('WARNING, algorithms execution pool is interrupted by: {}. {}'
				.format(err, traceback.format_exc(5)), file=sys.stderr)
			raise
		finally:
			# Extend algorithm and quality measure resource consumption files (.rcp) with time tracing,
			# once per the benchmark run
			for alg in algorithms:
				aresdir = RESDIR + alg
				# if not os.path.exists(aresdir):
				# 	os.mkdir(aresdir)
				aexecres = ''.join((aresdir, '/', alg, EXTEXECTIME))
				# Add timestamps also to the quality measures resource consumption files
				aqxres = ''.join((aresdir, '/', QMSDIR, '*', EXTEXECTIME))
				# Output timings only to the existing files after the execution results
				# to not affect the original header
				for xres in itertools.chain((aexecres,), glob.iglob(aqxres)):
					if os.path.isfile(xres):
						with open(xres, 'a') as fxr:
							fxr.write('# --- {time} (seed: {seed}) ---\n'.format(time=TIMESTAMP_START_STR, seed=seed))  # Write timestamp

	_execpool = None
	stime = time.perf_counter() - stime
	print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
	 .format(stime, *secondsToHms(stime)))
	print('Aggregating execution statistics...')
	aggexec(algorithms)
	print('Execution statistics aggregated')
	# return netnames


def clnames(net, odir, alg, pathidsuf=''):
	"""Clustering names by the input network name

	net: str  - input network name
	odir: bool - whether the resulting clusterings are outputted to the dedicated dir named by the instance name,
		which is typically used for shuffles with the non-flat structure
	alg: str  - algorithm name
	pathidsuf: str  - network path id prepended with the path separator, used to distinguish nets
		with the same name located in different dirs

	return
		cfnames: list(str)  - clustering file names
		uclfname: str or Null  - a multi-resolution clustering file name, which consists of
			the SINGLE (unified) level containing (representative) clusters from ALL (multiple) resolutions
	"""
	assert not pathidsuf or pathidsuf.startswith(SEPPATHID), 'Ivalid pathidsuf: ' + pathidsuf
	clpath = os.path.splitext(os.path.split(net)[1])[0]  # Part of the resulting path suffix
	# Consider the multi-level clustering in a single file (required at least for DAOC)
	# having the same name as the directory being aggregated
	cbdir = ''.join((RESDIR, alg, '/', CLSDIR))
	mrcl = ''.join((cbdir, clpath, '/', clpath, EXTCLNODES))
	# Take base network name (without the shuffle id)
	if odir:
		nameparts = parseName(clpath, True)
		clpath = ''.join((nameparts[0], nameparts[2], '/', clpath))  # Use base name and instance id
	clpath = clpath.join((cbdir, pathidsuf))
	# Reselting clustering file names
	return ([clp for clp in glob.iglob('/'.join((clpath, '*'))) if os.path.isfile(clp)],
		# Aggregated levels into the single clustering
		None if not os.path.isfile(mrcl) else mrcl)


def gtpath(net, idir):
	"""Ground-truth clustering file path by the input network file path

	net: str  - input network path, may include instace and shuffle suffixes
	idir: bool - whether the input network is given from the dedicated directory of shuffles or
		a flat structure is used where all networks are located in the same dir

	return gfpath: str  - ground-truth clustering file path
	"""
	if not idir:
		gfpath = delPathSuffix(os.path.splitext(net)[0]) + EXTCLNODES
		if os.path.isfile(gfpath):
			return gfpath
		print('WARNING, gtpath() idir parameter does not correspond to the actual input structure.'
			' Checking the ground-truth availability in the upper dir.', file=sys.stderr)
	path, name = os.path.split(net)
	# Check the ground-truth file in the parent directory
	gfpath = ''.join((os.path.split(path)[0], '/', delPathSuffix(os.path.splitext(name)[0], True), EXTCLNODES))
	if not os.path.isfile(gfpath):
		raise RuntimeError('Invalid argument, the ground-truth clustering {}'
			' does not exist for the network {}'.format(gfpath, net))
	return gfpath



def evalResults(qmsmodule, qmeasures, appsmodule, algorithms, datas, seed, exectime, timeout  #pylint: disable=W0613
, evaltimeout=14*24*60*60, update=True, revalue=False):  #pylint: disable=W0613;  # , netnames=None
	"""Run specified applications (clustering algorithms) on the specified datasets

	qmsmodule: module  - module with quality measures definitions to be run; sys.modules[__name__]
	qmeasures: list(list(str))  - evaluating quality measures with their parameters
	appsmodule: module  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms: iterable(str)  - algorithms to be executed
	datas: iterable(PathOpts)  - input datasets, wildcards of files or directories containing files
		of the default extensions .ns{{e,a}}
	seed: uint  - benchmark seed, natural number. Used to mark evaluations file via
		the HDF5 user block.
		ATTENTION: seed is not supported by [some] evaluation apps (gecmi)
	exectime  - elapsed time since the benchmarking started
	timeout: uint  - timeout per each evaluation run, a single measure applied to the results
		of a single algorithm on a single network (all instances and shuffles), >= 0
	evaltimeout: uint  - timeout for all evaluations, >= 0, 0 means unlimited time
	update: bool  - update evaluations file (storage of datasets) or create a new one,
		anyway existed evaluations are backed up
	revalue: bool  - whether to revalue the existent results or omit such evaluations
		calculating and saving only the values being not present in the dataset,
		actual only for the update flag set
	"""
	# netnames: iterable(str)  - input network names with path id and without the base path,
	# 	used to form meta data in the evaluation storage. Explicit specification is useful
	# 	if the netnames were been already formed on the clustering execution and
	# 	the intrinsic measures are not used (otherwise netnames are evalauted there).
	if not datas:
		print('WRANING evalResults(), there are no input datasets specified to be clustered', file=sys.stderr)
		return
	if qmeasures is None:
		print('WRANING evalResults(), there are no quality measures specified to be evaluated', file=sys.stderr)
		return
	assert qmsmodule and appsmodule and isinstance(datas[0], PathOpts) and exectime + 0 >= 0 and timeout + 0 >= 0, 'Invalid input arguments'
	assert isinstance(seed, int) and seed >= 0, 'Seed value is invalid'

	# Validate group attributes
	def validateDim(vactual, group, vname, vtype='B'):
		"""Validate dimension value creating a scalar attribute if required

		vactual: uint >= 1  - actual current value provided by the called
		group: hdf5.Group  - opened group
		vname: str or None  - name of the stored attribute if exists
		vtype: str or ctype  - type of the attribute

		return vstored: uint  - the attribute value in the dataset (>= vactual)
		"""
		assert vactual >= 1 and isinstance(vactual, int) and group and (vname is None or isinstance(vname, str)
			), 'Invalid arguments  vactual: {}, group type: {}, vname: {}'.format(vactual, type(group).__name__, vname)
		vstored = group.attrs.get(vname)
		if vstored != vactual and vstored is not None:
			# Warn and use the persisted value if it is larger otherwise raise an error requiring a new storage
			# since the dimensions should be permanent in the persisted storage
			if vactual < vstored:
				print('WARNING execXmeasures(), processing {} {} < {} persisted dimension size'  # The non-filled values will remain NaN
					.format(vname, vactual, vstored))
			else:
				raise ValueError('Processing {} {} > {} persisted. A new dedicated storage is required'.format(vname, vactual, vstored))
		if vstored is None:
			group.attrs.create(vname, vactual, shape=(1,), dtype=vtype)
			return vactual  # The same as new vstored
		return vstored  # >= vactual

	stime = time.perf_counter()  # Procedure start time; ATTENTION: .perf_counter() should not be used, because it does not consider "sleep" time
	print('Starting quality evaluations...')

	# Refine and validate names of the algorithms and measures, form the respective executors
	clarifyApps(algorithms, appsmodule)  # execalgs =
	exeqms = clarifyApps(qmeasures, qmsmodule, namefn=lambda qm: qm[0])

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Prepare HDF5 evaluations store
	with QualitySaver(seed=seed, update=update) as qualsaver:  # , nets=netnames
		# Validate algorithm HDF5 group attributes (nlev)
		# alevs = {}  # The actual number of levels in each algorithm in the storage
		try:
			with qualsaver.storage:
				for alg in algorithms:
					group = qualsaver.storage.value.require_group(alg)  #pylint: disable=E1101
					# alevs[alg] =
					validateDim(ALGLEVS.get(alg, ALEVSMAX), group, 'nlev')
		except Exception as err:  #pylint: disable=W0703
			errexectime = time.perf_counter() - exectime
			print('ERROR, quality evaluations are interrupted by the exception:'
				' {} on {:.4f} sec ({} h {} m {:.4f} s), call stack:'
				.format(errexectime, *secondsToHms(errexectime)), file=sys.stderr)
			# traceback.print_stack(limit=5, file=sys.stderr)
			traceback.print_exc(5)

		# Compute quality measures grouping them into batches with the same affinity
		# starting with the measures having the affinity step = 1
		# Sort qmeasures with their executables having affinity step = 1 in the end for the pop()
		qmeas = sorted(zip(qmeasures, exeqms, [QMSRAFN.get(eq) for eq in exeqms]), key=lambda qmea: qmea[2], reverse=True)
		cqmes = []  # Currently processing qmes having the same affinity mask
		# tasks = []  # All tasks
		while qmeas:
			afn = qmeas[-1][2]
			del cqmes[:]
			while qmeas and qmeas[-1][2] == afn:
				cqmes.append(qmeas.pop()[:2])
			if afn is None:  # Note: QMSRAFN contains mandatory values only for the non-default AffinityMask
				afn = AffinityMask(1)

			# Perform quality evaluations
			with ExecPool(_WPROCSMAX, afnmask=afn, memlimit=_VMLIMIT
			, name='runqms_' + str(afn.afnstep) + ('f' if afn.first else 'a'), webuiapp=_webuiapp) as _execpool:
				def runapp(net, asym, netshf, pathidsuf='', tasks=None, netinf=None):
					"""Execute algorithms on the specified network counting number of ran jobs

					net  - network to be processed
					asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions
					netshf  - whether this network is a shuffle in the non-flat dir structure
					pathidsuf  - path id of the net to distinguish nets with the same name located in different dirs
					tasks: list(Task)  - tasks associated with the running algorithms on the specified network
					netinf: NetInfo  - network meta information (the number of network instances and shuffles, etc.)

					return
						jobsnum  - the number of scheduled jobs, typically 1
					"""
					# Note: netinf is mandatory for this callback
					assert isinstance(netinf, NetInfo), 'Ivalid argument: ' + type(netinf)
					# Scheduled tasks: qmeasure / basenet for each net
					jobsnum = 0
					## Task suffix is the network name
					# tasksuf, netext = os.path.splitext(os.path.split(net)[1])
					gfpath = gtpath(net, netshf)  # Ground-truth file name by the network file name (with full path)
					# # Form Measure [/ Basebneet] / Network tasks
					# assert not tasks or len(tasks) == len(cqmes), 'Tasks are not synced with the quality measures'
					# mntasks = []
					# for i, qm, eq in enumerate(cqmes):
					# 	runs = QMSRUNS.get(qm[0], 1)  # The number of quality measure runs (subsequent evaluations)
					# 	mntasks.append(Task(SEPSUBTASK.join((qm[0] if not tasks else tasks[i].name
					# 			# Append irun to the task suffix
					# 			, tasksuf if runs == 1 else 'r'.join((tasksuf, str(irun)))))
					# 		, task=None if not tasks else tasks[j]))

					# Apply all quality measures having the same affinity for all the algorithms on all networks,
					# such traversing benefits from both the networks and clusterings caching
					#
					# Fetch base network name and its attributes
					netname, netext = os.path.splitext(os.path.split(net)[1])
					netext = netext.lower()
					# Note: the input network name does not contain the paid id, which is added during the processing
					netname, _aparams, inst, shuf, _pid  = parseName(netname, True)
					iinst = 0 if not inst else int(inst[len(SEPINST):])  # Instance id
					ishuf = 0 if not shuf else int(shuf[len(SEPSHF):])  # Shuffle id
					with qualsaver.storage:
						for alg in algorithms:
							# Validate network HDF5 group attributes (instances and shuffles) if required
							group = None
							try:
								group = qualsaver.storage.value.require_group(''.join(('/', alg, '/'
									# Form network name with path id
									, delPathSuffix(netname, True) + pathidsuf)))
								if not netinf.gvld:
									# nins =
									validateDim(netinf.nins, group, 'nins')
									# nshf =
									validateDim(netinf.nshf, group, 'nshf')
									netinf.gvld = True
							except Exception as err:  #pylint: disable=W0703
								print('ERROR, quality evaluation of "{}" is interrupted by the exception: {}, call stack:'
									.format(netname + pathidsuf, err), file=sys.stderr)
								traceback.print_exc(5)
								return jobsnum

							for i, (qm, eq) in enumerate(cqmes):
								# Append algortihm-indicating subtask: QMeasure / BaseNet / Alg
								task = None if not tasks else tasks[i]
								if task:
									task = Task(SEPSUBTASK.join((task.name, alg)), task=task
										# TODO: Aggregate quality evaluations of each algorithm on each network
										#, onfinish=aggAlgQevals, params=_execpool
									)
								try:
									# Whether the input path is a network or a clustering
									ifpath = net if eq in QMSINTRIN else gfpath
									cfnames, uclfname = clnames(net, netshf, alg=alg, pathidsuf=pathidsuf)
									# Create or open the respective datasets
									# Dataset with multiple cluster levels, typically each having clusters on a single resolution
									if cfnames:
										pass
									# Dataset with a single level containing multi-resolution clusters
									if uclfname:
										pass
									# Sort the clustering file names to form their clustering level ids in the same order
									if len(cfnames) >= 2:
										cfnames.sort()
									runs = QMSRUNS.get(qm[0], 1)  # The number of quality measure runs (subsequent evaluations)
									for inpcls, ulev in ((cfnames, False), ([] if uclfname is None else [uclfname], True)):
										# ilev == ifc corresponds to the alphabetical ordering of the clustering levels file names
										for ifc, fcl in enumerate(inpcls):
											for irun in range(runs):
												smeta = SMeta(group=group, measure=qm[0], ulev=ulev,
													iins=iinst, ishf=ishuf, ilev=ifc, irun=irun)
												jobsnum += eq(_execpool, qualsaver, smeta, qm[1:], cfpath=fcl, inpfpath=ifpath,
													asym=asym, timeout=timeout, seed=seed, task=task, revalue=revalue)
								except Exception as err:  #pylint: disable=W0703
									errexectime = time.perf_counter() - exectime
									print('ERROR, "{}" is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s), call stack:'
										.format(eq.__name__, err, errexectime, *secondsToHms(errexectime)), file=sys.stderr)
									# traceback.print_stack(limit=5, file=sys.stderr)
									traceback.print_exc(5)
					return jobsnum

				def runner(net, netshf, xargs, tasks=None, netinf=None):
					"""Network runner helper

					net  - network file name
					netshf  - whether this network is a shuffle in the non-flat dir structure
					xargs  - extra custom parameters
					tasks: list(Task)  - tasks associated with the running algorithms on the specified network
					netinf: NetInfo  - network meta information (the number of network instances and shuffles, etc.)
					"""
					tnum = runapp(net, xargs['asym'], netshf, xargs['pathidsuf'], tasks, netinf)
					xargs['jobsnum'] += tnum
					xargs['netcount'] += tnum != 0

				xargs = {'asym': False,  # Asymmetric network
						'pathidsuf': '',  # Network path id prepended with the path separator, used to deduplicate the network name shortcut
						'jobsnum': 0,  # Number of the processing network jobs (can be several per each instance if shuffles exist)
						'netcount': 0}  # Number of processing network instances (includes multiple shuffles)
				ctasks = [Task(qme[0][0]) for qme in cqmes]  # Current tasks
				# tasks.extend(ctasks)

				# Note: subtasks for each base networks are created automatically
				## TODO: aggregate results for each quality measure with the fixed args on each base network
				# onfinish=bestlev, params={...}
				processNetworks(datas, runner, xargs=xargs, dflextfn=dflnetext, tasks=ctasks, metainf=True)

				if evaltimeout <= 0:
					evaltimeout = timeout * xargs['jobsnum']
				timelim = min(timeout * xargs['jobsnum'], evaltimeout)
				print('Waiting for the quality evaluation on {} jobs from {} networks'
					' with {} sec ({} h {} m {:.4f} s) timeout ...'
					.format(xargs['jobsnum'], xargs['netcount'], timelim, *secondsToHms(timelim)))
				# Note: all failed jobs of the ExecPool are hierarchically traced by the assigned tasks
				# (on both completion and termination)
				try:
					_execpool.join(timelim)
				except BaseException as err:  # Consider also system interruptions not captured by the Exception
					print('WARNING, algorithms execution pool is interrupted by: {}. {}'
						.format(err, traceback.format_exc(5)), file=sys.stderr)
					raise
	# Clear execpool
	_execpool = None
	stime = time.perf_counter() - stime
	print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
	 .format(stime, *secondsToHms(stime)))
	print('Aggregating execution statistics...')
	aggexec([qm[0] for qm in qmeasures])
	print('Execution statistics aggregated')
# 	# TODO: aggregate and visualize quality evaluation results
# 	qualsaver.storage.value.close()
# 	_execpool = None  # Reset global execpool
# 	stime = time.perf_counter() - stime
# 	print('Results evaluation is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
# 	 .format(stime, *secondsToHms(stime)))
# 	# Aggregate results and output
# 	stime = time.perf_counter()
# 	print('Starting processing of aggregated results ...')
# 	#for evagg in evaggs:
# 	#	evagg.aggregate()
# 	stime = time.perf_counter() - stime
# 	print('Processing of aggregated results completed in {:.4f} sec ({} h {} m {:.4f} s)'
# 	 .format(stime, *secondsToHms(stime)))


def benchmark(*args):
	"""Execute the benchmark

	Run the algorithms on the specified datasets respecting the parameters.
	"""
	exectime = time.perf_counter()  # Benchmarking start time

	opts = parseParams(args)
	print('The benchmark is started, parsed params:\n\tsyntpo: "{}"\n\tconvnets: 0b{:b}'
		'\n\trunalgs: {}\n\talgorithms: {}\n\tquality measures: {}\n\tqupdate: {}\n\tqrevalue: {}\n\tdatas: {}'
		'\n\taggrespaths: {}\n\twebui: {}\n\ttimeout: {} h {} m {:.4f} sec'
	 .format(opts.syntpo, opts.convnets, opts.runalgs
		, ', '.join(opts.algorithms) if opts.algorithms else ''
		, None if opts.qmeasures is None else ' '.join([qm[0] for qm in opts.qmeasures]), opts.qupdate, opts.qrevalue
		, '; '.join([str(pathopts) for pathopts in opts.datas])  # Note: ';' because internal separator is ','
		, ', '.join(opts.aggrespaths) if opts.aggrespaths else ''
		, None if opts.host is None else '{}:{}'.format(opts.host, opts.port)
		, *secondsToHms(opts.timeout)))

	# Start WebUI if required
	global _webuiapp  #pylint: disable=W0603
	if _webuiapp is None and opts.host:
		print('Calling WebUI on the host {}:{}'.format(opts.host, opts.port))
		_webuiapp = WebUiApp(host=opts.host, port=opts.port, name='MpeWebUI', daemon=True)
	else:
		print('WARNING, WebUI app ({}) omitted on the host {}:{}'.format(_webuiapp, opts.host, opts.port), file=sys.stderr)

	# Benchmark app can be called from the remote directory
	bmname = 'lfrbench_udwov'  # Benchmark name for the synthetic networks generation
	assert UTILDIR.endswith('/'), 'A directory should have a valid terminator'
	benchpath = UTILDIR + bmname  # Benchmark path

	# Create the global seed file if not exists
	if not os.path.exists(opts.seedfile):
		# Consider nonexistent base path of the common seed file
		sfbase = os.path.split(opts.seedfile)[0]
		if sfbase and not os.path.exists(sfbase):
			os.makedirs(sfbase)
		seed = timeSeed()
		with open(opts.seedfile, 'w') as fseed:
			fseed.write('{}\n'.format(seed))
		# Reset the quality measures update request if any since the seed is new
		# Note: the WARNING is not displayed since the update policy is default
		opts.qupdate = False
		opts.qrevalue = True  # qrevalue equal to False actual only if qupdate
	else:
		with open(opts.seedfile) as fseed:
			seed = int(fseed.readline())

	# Generate parameters for the synthetic networks and the networks instances if required
	if opts.syntpo and opts.syntpo.netins >= 1:
		# Note: on overwrite old instances are rewritten and shuffles are deleted making the backup
		generateNets(genbin=benchpath, insnum=opts.syntpo.netins, asym=opts.syntpo.asym
			, basedir=opts.syntpo.path, netsdir=_NETSDIR, overwrite=opts.syntpo.overwrite
			, seedfile=opts.seedfile, gentimeout=3*60*60)  # 3 hours

	# Update opts.datasets with synthetic generated data: all subdirs of the synthetic networks dir
	# Note: should be done only after the generation, because new directories can be created
	if opts.syntpo or not opts.datas:
		# Note: even if syntpo was no specified, use it as the default path
		if opts.syntpo is None:
			opts.syntpo = SyntPathOpts(_SYNTDIR)
		#popts = copy.copy(super(SyntPathOpts, opts.syntpo))
		#popts.path = _NETSDIR.join((popts.path, '*/'))  # Change meaning of the path from base dir to the target dirs
		opts.syntpo.path = _NETSDIR.join((opts.syntpo.path, '*/'))  # Change meaning of the path from base dir to the target dirs
		# Generated synthetic networks are processed before the manually specified other paths
		opts.datas.insert(0, opts.syntpo)
		opts.syntpo = None  # Delete syntpo to not occasionally use .path with changed meaning

	# Shuffle datasets backing up and overwriting existing shuffles if the shuffling is required at all
	shuffleNets(opts.datas, timeout1=7*60, shftimeout=45*60)

	# Note: conversion should not be used typically
	# opts.convnets: 0 - do not convert, 0b01 - only if not exists, 0b11 - forced conversion, 0b100 - resolve duplicated links
	if opts.convnets:
		convertNets(opts.datas, overwrite=opts.convnets & 0b11 == 0b11
			, resdub=opts.convnets & 0b100, timeout1=7*60, convtimeout=45*60)  # 45 min

	# Run the opts.algorithms and measure their resource consumption
	if opts.runalgs:
		runApps(appsmodule=benchapps, algorithms=opts.algorithms, datas=opts.datas
			, seed=seed, exectime=exectime, timeout=opts.timeout, runtimeout=opts.runtimeout)

	# Evaluate results
	if opts.qmeasures is not None:
		evalResults(qmsmodule=benchevals, qmeasures=opts.qmeasures, appsmodule=benchapps
			, algorithms=opts.algorithms, datas=opts.datas, seed=seed, exectime=exectime
			, timeout=opts.timeout, evaltimeout=opts.evaltimeout, update=opts.qupdate, revalue=opts.qrevalue)
			# , netnames=netnames

	if opts.aggrespaths:
		aggEvaluations(opts.aggrespaths)

	exectime = time.perf_counter() - exectime
	print('The benchmark completed in {:.4f} sec ({} h {} m {:.4f} s)'
	 .format(exectime, *secondsToHms(exectime)))


_signals = {}  # Signals mapping


def terminationHandler(signal=None, frame=None, terminate=True):  #pylint: disable=W0621,W0613
	"""Signal termination handler
	signal  - raised signal
	frame  - origin stack frame
	terminate  - whether to terminate the application
	"""
	#if signal == signal.SIGABRT:
	#	os.killpg(os.getpgrp(), signal)
	#	os.kill(os.getpid(), signal)

	global _execpool

	if _execpool:
		print('WARNING{}, execpool is terminating by the signal {} ({})'
			.format('' if not _execpool.name else ' ' + _execpool.name, signal
			, _signals.get(signal, '-')))  # Note: this is a trace log record
		del _execpool  # Destructors are called later
		# Define _execpool to avoid unnecessary trash in the error log, which might
		# be caused by the attempt of subsequent deletion on destruction
		_execpool = None  # Note: otherwise _execpool becomes undefined
	if terminate:
		sys.exit()  # exit(0), 0 is the default exit code.


if __name__ == '__main__':
	if len(sys.argv) <= 1 or (len(sys.argv) == 2 and sys.argv[1] in ('-h', '--help')):
		apps = fetchAppnames(benchapps)
		qmapps = fetchAppnames(benchevals)
		print('\n'.join(('Usage:',
			'  {0} [-g[o][a]=[<number>][{gensepshuf}<shuffles_number>][=<outpdir>]'
			' [-i[f][a][{gensepshuf}<shuffles_number>]=<datasets_{{dir,file}}_wildcard>'
			' [-c[f][r]] [-a=[-]"app1 app2 ..."] [-r] [-q[="qmapp [arg1 arg2 ...]"]]'
			' [-s=<resval_path>] [-t[{{s,m,h}}]=<timeout>] [-d=<seed_file>] [-w=<webui_addr>] | -h',
			'',
			'Example:',
			'  {0} -g=3{gensepshuf}5 -r -q -th=2.5 1> {resdir}bench.log 2> {resdir}bench.err',
			'NOTE:',
			'  - The benchmark should be executed exclusively from the current directory (./).',
			'  - The expected format of input datasets (networks) is .ns<l> - network specified by'
			' <links> (arcs / edges), a generalization of the .snap, .ncol and Edge/Arcs Graph formats.',
			'  - Paths can contain wildcards: *, ?, +.',
			'  - Multiple paths can be specified with multiple -i, -s options (one per the item).',
			'',
			'Parameters:',
			'  --help, -h  - show this usage description',
			'  --generate, -g[o][a]=[<number>][{gensepshuf}<shuffles_number>][=<outpdir>]  - generate <number> synthetic datasets'
			' of the required format in the <outpdir> (default: {syntdir}), shuffling (randomly reordering network links'
			' and saving under another name) each dataset <shuffles_number> times (default: 0).'
			' If <number> is omitted or set to 0 then ONLY shuffling of <outpdir>/{netsdir}/* is performed.'
			' The generated networks are automatically added to the begin of the input datasets.',
			'    o  - overwrite existing network instances (old data is backed up) instead of skipping generation',
			'    a  - generate networks specified by arcs (directed) instead of edges (undirected)',
			'NOTE: shuffled datasets have the following naming format:',
			'\t<base_name>[(seppars)<param1>...][{sepinst}<instance_index>][{sepshf}<shuffle_index>].<net_extension>',
			'  --input, -i[f][a][{gensepshuf}<shuffles_number>]=<datasets_dir>  - input dataset(s), wildcards of files or directories'
			', which are shuffled <shuffles_number> times. Directories should contain datasets of the respective extension'
			' (.ns{{e,a}}). Default: -i={syntdir}{netsdir}*/, which are subdirs of the synthetic networks dir without shuffling.',
			'    f  - make flat derivatives on shuffling instead of generating the dedicated directory (having the file base name)'
			' for each input network, might cause flooding of the base directory. Existed shuffles are backed up.',
			'    NOTE: variance over the shuffles of each network instance is evaluated only for the non-flat structure.',
			'    a  - the dataset is specified by arcs (asymmetric, directed links) instead of edges (undirected links)'
			', considered only for not .ns{{a,e}} extensions.',
			'NOTE:',
			'  - The following symbols in the path name have specific semantic and processed respectively: {rsvpathsmb}.',
			'  - Paths may contain wildcards: *, ?, +.',
			'  - Multiple directories and files wildcards can be specified with multiple -i options.',
			'  - Existent shuffles are backed up if reduced, the existent shuffles are RETAINED and only the additional'
			' shuffles are generated if required.',
			'  - Datasets should have the .ns<l> format: <node_src> <node_dest> [<weight>]',
			'  - Ambiguity of links weight resolution in case of duplicates (or edges specified in both directions)'
			' is up to the clustering algorithm.',
			'  --apps, -a[=[-]"app1 app2 ..."]  - apps (clustering algorithms) to be applied, default: all.',
			'Leading "-" means apply all except the specified apps. Available apps ({anppsnum}): {apps}.',
			'Impacts {{r, q}} options. Optional, all registered apps (see benchapps.py) are executed by default.',
			'NOTE: output results are stored in the "{resdir}<algname>/" directory',
			#'    f  - force execution even when the results already exists (existent datasets are moved to the backup)',
			'  --runapps, -r  - run specified apps on the specified datasets, default: all',
			'  --quality, -q[="qmapp [arg1 arg2 ...]"  - evaluate quality (accuracy) with the specified quality measure'
			' application (<qmapp>) for the algorithms (specified with "-a") on the datasets (specified with "-i")'
			' and form the aggregated final results. Default: MF1p, GNMI_max, OIx extrinsic and Q, f intrinsic measures'
			' on all datasets. Available qmapps ({qmappsnum}): {qmapps}.',
			'NOTE:',
			'  - Multiple quality measure applications can be specified with multiple -q options.',
			'  - Existent quality measures with the same seed are updated (extended with the lacking'
			' evaluations omitting the already existent) until --quality-revalue is specified.',
			'Notations of the quality measurements:',
			' = Extrinsic Quality (Accuracy) Measures =',
			'   - GNMI[_{{max,sqrt}}]  - Generalized Normalized Mutual Information for overlapping and multi-resolution clusterings'
			' (collections of clusters), equals to the standard NMI when applied to the non-overlapping single-resolution clusterings.',
			'   - MF1{{p,h,a}}[_{{w,u,c}}]  - mean F1 measure (harmonic or average) of all local best matches by the'
			' Partial Probabilities or F1 (harmonic mean) considering macro/micro/combined weighting.',
			'   - OI[x]  - [x - extended] Omega Index for the overlapping clusterings, non-extended version equals to the'
			' Adjusted Rand Index when applied to the non-overlapping single-resolution clusterings.',
			' --- Less Indicative Extrinsic Quality Measures ---',
			'   - F1{{p,h}}_[{{w,u}}]  - perform labeling of the evaluating clusters with the specified ground-truth'
			' and evaluate F1-measure of the labeled clusters',
			'   - ONMI[_{{max,sqrt,avg,lfk}}]  - Ovelapping NMI suitable for a single-resolution clusterings having light overlaps,'
			' the resulting values are not compatible with the standard NMI when applied to the non-overlapping clusters.',
			# '   - NMI[_{{max,sqrt,avg,min}}]  - standard NMI for the non-overlapping (disjoint) clusters only.',
			' = Intrinsic Quality Measures =',
			'   - Cdt  - conductance f for the overlapping clustering.',  # Cdt, Cds, f
			'   - Q[a]  - [autoscaled] modularity for the overlapping clustering, non-autoscaled equals to the standard modularity',
			' when applied to the non-overlapping single-resolution clustering.',
			'  --timeout, -t=[<days:int>d][<hours:int>h][<minutes:int>m][<seconds:float>] | -t[X]=<float>  - timeout for each'
			' benchmarking application per single evaluation on each network; 0 - no timeout, default: {algtimeout}. X option:',
			'    s  - time in seconds, default option',
			'    m  - time in minutes',
			'    h  - time in hours',
			'    Examples: `-th=2.5` is the same as `-t=2h30m` and `--timeout=2h1800`',
			'  --quality-noupdate  - always create a new storage file for the quality measure evaluations'
			' instead of updating the existent one.',
			'  --quality-revalue  - evaluate resulting clusterings with the quality measures from scratch'
			' instead of retaining the existent values (for the same seed) and adding only the non-existent.',
			'NOTE: actual (makes sense) only when --quality-noupdate is NOT applied.',
			'  --seedfile, -d=<seed_file>  - seed file to be used/created for the synthetic networks generation,'
			' stochastic algorithms and quality measures execution, contains uint64_t value. Default: {seedfile}.',
			'NOTE:',
			'  - The seed file is not used on shuffling, so the shuffles are DISTINCT for the same seed.',
			'  - Each re-execution of the benchmarking reuses once created seed file, which is permanent'
			' and can be updated manually.',
			'',
			'Advanced parameters:',
			#'  --stderr-stamp  - output a time stamp to the stderr on the benchmarking start to separate multiple re-executions',
			'  --convret, -c[X]  - convert input networks into the required formats (app-specific formats: .rcg[.hig], .lig, etc.), deprecated',
			'    f  - force the conversion even when the data is already exist',
			'    r  - resolve (remove) duplicated links on conversion (recommended to be used)',
			'  --summary, -s=<resval_path>  - aggregate and summarize specified evaluations extending the benchmarking results'
			', which is useful to include external manual evaluations into the final summarized results',
			'ATTENTION: <resval_path> should include the algorithm name and target measure.',
			'  --webaddr, -w  - run WebUI on the specified <webui_addr> in the format <host>[:<port>], default port={port}.',
			'  --runtimeout  - global clustering algorithms execution timeout in the'
			' format [<days>d][<hours>h][<minutes>m<seconds>], default: {runtimeout}.',
			'  --evaltimeout  - global clustering algorithms execution timeout in the'
			' format [<days>d][<hours>h][<minutes>m<seconds>], default: {evaltimeout}.',
			)).format(sys.argv[0], gensepshuf=_GENSEPSHF, resdir=RESDIR, syntdir=_SYNTDIR, netsdir=_NETSDIR
				, sepinst=SEPINST, seppars=SEPPARS, sepshf=SEPSHF, rsvpathsmb=(SEPPARS, SEPINST, SEPSHF, SEPPATHID)
				, anppsnum=len(apps), apps=', '.join(apps), qmappsnum=len(qmapps), qmapps=', '.join(qmapps)
				, algtimeout=secDhms(_TIMEOUT), seedfile=_SEEDFILE, port=_PORT
				, runtimeout=secDhms(_RUNTIMEOUT), evaltimeout=secDhms(_EVALTIMEOUT)))
	else:
		# Fill signals mapping {value: name}
		_signals = {sv: sn for sn, sv in viewitems(signal.__dict__)
			if sn.startswith('SIG') and not sn.startswith('SIG_')}

		# Set handlers of external signals
		signal.signal(signal.SIGTERM, terminationHandler)
		signal.signal(signal.SIGHUP, terminationHandler)
		signal.signal(signal.SIGINT, terminationHandler)
		signal.signal(signal.SIGQUIT, terminationHandler)
		signal.signal(signal.SIGABRT, terminationHandler)

		# Ignore terminated children procs to avoid zombies
		# ATTENTION: signal.SIG_IGN affects the return code of the former zombie resetting it to 0,
		# where signal.SIG_DFL works fine and without any the side effects.
		signal.signal(signal.SIGCHLD, signal.SIG_DFL)

		# Set termination handler for the internal termination
		atexit.register(terminationHandler, terminate=False)  # Note: False because it is already terminating

		benchmark(*sys.argv[1:])
