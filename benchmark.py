#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: A modular benchmark, which optionally generates and preprocesses
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
import atexit  # At exit termination handleing
import sys
import os
import shutil
import signal  # Intercept kill signals
import glob
import traceback  # Stacktrace
import copy
import time
# Consider time interface compatibility for Python before v3.3
if not hasattr(time, 'perf_counter'):  #pylint: disable=C0413
	time.perf_counter = time.time

from math import sqrt
from multiprocessing import cpu_count  # Returns the number of logical CPU units (hw treads) if defined

import benchapps  # Required for the functions name mapping to/from the app names
from benchapps import PYEXEC, aggexec, funcToAppName, PREFEXEC  # , _EXTCLNODES, ALGSDIR
from benchutils import viewitems, timeSeed, SyncValue, dirempty, tobackup, dhmsSec, secDhms \
 	, SEPPARS, SEPINST, SEPSHF, SEPPATHID, SEPSUBTASK, UTILDIR, TIMESTAMP_START_STR, TIMESTAMP_START_HEADER
# PYEXEC - current Python interpreter
import benchevals  # Required for the functions name mapping to/from the quality measures names
from benchevals import aggEvaluations, RESDIR, EXTEXECTIME, QualitySaver #, evaluators,
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

	def __init__(self, path, flat=False, asym=False, shfnum=0):
		"""Sets default values for the input parameters

		path  - path (directory or file), a wildcard is allowed
		flat  - use flat derivatives or create the dedicated directory on shuffling
			to avoid flooding of the base directory.
			NOTE: variance over the shuffles of each network instance is evaluated
			only for the non-flat structure.
		asym  - the network is asymmetric (specified by arcs rather than edges),
			which is considered only for the non-standard file extensions (not .nsL)
		shfnum  - the number of shuffles of each network instance to be produced, >= 0
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
		qmeasures  - quality measures with their parameters to be evaluated
			on the clustering results. None means do not evaluate.
		qupdate  - update quality evaluations storage with the lacking evaluations
			omitting the existent one, applicable only for the same seed.
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
		aggrespaths: iterable(str)  -  paths for the evaluated results aggregation (to be done for
			already existent evaluations)
			TODO: clarify and check availability in the latest version
		host: str  - WebUI host, None to disable WebUI
		port: int  - WebUI port
		runtimeout: uint  - clustering algoritims execution timeout
		evaltimeout: uint  - resulting clusterings evaluations timeout
		"""
		self.syntpo = None  # SyntPathOpts()
		self.runalgs = False
		self.qmeasures = None  # Evaluating quality measures with their parameters
		self.qupdate = True
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
			elif arg.startswith('--quality-revalue '):
				opts.qupdate = False
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
			# aysm  - asymmetric (directed): None - not specified (symmetric is assumed), False - symmetric, True - asymmetric
			# shfnum  - the number of shuffles
			popt = PathOpts(arg[pos+1:].strip('"\''), flat=False, asym=False, shfnum=0)  # Remove quotes if exist
			for i in range(2, pos):
				if arg[i] == 'f':
					popt.flat = True
				elif arg[i] == 'a':
					popt.asym = True
				elif arg[i] == _GENSEPSHF:
					popt.shfnum = int(arg[i+1:pos])
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
				algs = appnames(benchapps)
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
	netsdir  - relative directory for the synthetic networks, contains subdirs,
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
		bcksuffix = SyncValue()  # Use the same backup suffix for multiple paths

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
		except BaseException as err:  # Consider also system iteruptions not captured by the Exception
			print('WARNING, network generation execution pool is interrupted by: {}. {}'
				.format(err, traceback.format_exc(5)), file=sys.stderr)
			raise
	_execpool = None
	print('Synthetic networks files generation completed')


def shuffleNets(datas, timeout1=7*60, shftimeout=30*60):  # 7, 30 min
	"""Shuffle specified networks backing up and updating exsinting shuffles.
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

	# Check whether the shufflng is required at all
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
	# Note: afnstep = 1 because the processes are not cache-intencive, not None, because the workers are single-threaded
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
			bcksuffix  - backup suffix for the group of directories, formed automatically
				from the SyncValue()

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

			return: bool  - path existance
			"""
			try:
				next(glob.iglob(wildcard))
			except StopIteration:
				return False  # Such path does not exist
			return True

		bcksuffix = SyncValue()  # Use unified suffix for the backup of various network instances
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
							# Whether the shuffles will be modified and need to be backuped
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
							# # Whether the shuffles will be modified and need to be backuped
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
						# Whether the shuffles will be modified and need to be backuped
						backup = xpathExists(''.join((dirpath, '/', basename
							, '*', SEPSHF, str(popt.shfnum + 1), '*', dflext)))
						shuf0 = prepareDir(dirpath, path, backup, bcksuffix)
						shfnum += shuffleNet(shuf0, popt.shfnum)
					else:
						# Backup existing flat shuffles if any (expanding the base path), which will be updated the subsequent shuffling
						# Whether the shuffles will be modified and need to be backuped
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


def basenetTasks(netname, pathidstr, basenets, rtasks):
	"""Fetch or make tasks for the specific base network name (with pathidstr
	and whitout the instance and shuffle id)

	netname: str  - network name, possibly includes instance but NOT shuffle id
	pathidstr: str  - network path id in the string representation
	basenets: dict(basenet: str, nettasks: list(Task))  - tasks for the basenet
	rtasks: list(Task)  - root tasks for the running apps on all networks

	return  nettasks: list(Task)  - tasks for the basenet of the specified netname
	"""
	iename = netname.find(SEPINST)
	if iename == -1:
		basenet = os.path.splitext(netname)[0]  # Remove network extension if any
	else:
		basenet = netname[:iename]
	if pathidstr:
		basenet = SEPPATHID.join((basenet, pathidstr))
	nettasks = basenets.get(basenet)
	if not nettasks:
		nettasks = [Task(SEPSUBTASK.join((t.name, basenet)), task=t) for t in rtasks]
		basenets[basenet] = nettasks
	return nettasks


def processPath(popt, handler, xargs=None, dflextfn=dflnetext, tasks=None):
	"""Process the specified path with the specified handler

	popt: PathOpts  - processing path options (the path is directory of file, not a wildcard)
	handler: callable  - handler to be called as handler(netfile, netshf, xargs, tasks),
		netshf means that the processing networks is a shuffle in the non-flat dir structure
	xargs: dict(str, val)  - extra arguments of the handler following after the processing network file
	dflextfn: callable  - function(asymflag) for the default extension of the input files in the path
	tasks: list(tasks)  - root tasks per each algorithm
	"""
	# assert tasks is None or isinstance(tasks[0], Task), ('Unexpected task format: '
	# 	+ str(None) if not tasks else type(tasks[0]).__name__)
	# appnames  - names of the running apps to create be associated with the tasks
	assert os.path.exists(popt.path), 'Target path should exist'
	path = popt.path  # Assign path to a local variable to not corrupt the input data
	dflext = dflextfn(popt.asym)  # dflnetext(popt.asym)  # Default network extension for files in dirs
	# Base networks with their tasks (netname with the pathid
	# and without the instance and shuffle suffixes)
	bnets = {}
	if os.path.isdir(path):
		# Traverse over the instances in the specified directory
		# Use the same path separator on all OSs
		if not path.endswith('/'):
			path += '/'
		# Take shuffles in subdirs if required
		# Note: the origin instance is mapped to the shuffles dir, so traverse only
		# the directories with shuffles if exist
		if not popt.flat:
			# Traverse over the networks instances
			for net in glob.iglob('*'.join((path, dflext))):  # Allow wildcards
				# Skip the shuffles if any to process only specified networks
				# (all target shuffles are located in the dedicated dirs for non-flat paths)
				netname = os.path.split(net)[1]
				if netname.find(SEPSHF) != -1:
					continue
				# Fetch base network name (whitout the instance and shuffle id)
				nettasks = basenetTasks(netname, None if not xargs else xargs['pathidstr'], bnets, tasks)
				# iename = netname.find(SEPINST)
				# basenet = netname if iename == -1 else netname[:iename]
				# if xargs and xargs['pathidstr']:
				# 	basenet = SEPPATHID.join((basenet, xargs['pathidstr']))
				# nettasks = bnets.get(basenet)
				# if not nettasks:
				# 	nettasks = [Task(SEPSUBTASK.join((t.name, basenet)), task=t) for t in tasks]
				# 	bnets[basenet] = nettasks
				# #if popt.shfnum:  # ATTENTNION: shfnum is not available for non-synthetic networks
				# Process dedicated dir of shuffles for the specified network,
				# the origin network itself is linked to the shuffles dir (inside it)
				dirname, ext = os.path.splitext(net)
				if os.path.isdir(dirname):
					# Shuffles exist for this network and located in the subdir together with the copy of origin
					for desnet in glob.iglob('/*'.join((dirname, ext))):
						handler(desnet, True, xargs, nettasks)  # True - shuffle is processed in the non-flat dir structure
				else:
					handler(net, False, xargs, tasks)  # Neither multiple instances nor shufles exist for this net
		else:
			# Both shuffles (if exist any) and network instances are located
			# in the same dir, convert them
			for net in glob.iglob('*'.join((path, dflext))):
				# Note: typically, shuffles and instances do not exist in the flat structure
				# or their number is small
				#
				# # Fetch base network name (whitout instance and shuffle id)
				# basenet = os.path.split(net)[1]
				# iename = basenet.find(SEPINST)
				# if iename != -1:
				# 	basenet = basenet[:iename]
				# iename = basenet.find(SEPSHF)
				# if iename != -1:
				# 	basenet = basenet[:iename]
				# if xargs and xargs['pathidstr']:
				# 	basenet = SEPPATHID.join((basenet, xargs['pathidstr']))
				# nettasks = bnets.get(basenet)
				# if not nettasks:
				# 	nettasks = [Task(SEPSUBTASK.join((t.name, basenet)), task=t) for t in tasks]
				# 	bnets[basenet] = nettasks
				handler(net, False, xargs, tasks)
	else:
		if not popt.flat:
			# Skip the shuffles if any to process only specified networks
			# (all target shuffles are located in the dedicated dirs for non-flat paths)
			netname = os.path.split(path)[1]
			if netname.find(SEPSHF) != -1:
				return
			# Fetch base network name (whitout the instance and shuffle id)
			nettasks = basenetTasks(netname, None if not xargs else xargs['pathidstr'], bnets, tasks)
			#if popt.shfnum:  # ATTENTNION: shfnum is not available for non-synthetic networks
			# Process dedicated dir of shuffles for the specified network,
			# the origin network itself is linked to the shuffles dir (inside it)
			dirname, ext = os.path.splitext(path)
			if os.path.isdir(dirname):
				for desnet in glob.iglob('/*'.join((dirname, ext))):
					handler(desnet, True, xargs, nettasks)  # True - shuffle is processed in the non-flat dir structure
			else:
				handler(path, False, xargs, tasks)
		else:
			handler(path, False, xargs, tasks)


def processNetworks(datas, handler, xargs={}, dflextfn=dflnetext, tasks=None, fpathids=None):  #pylint: disable=W0102
	"""Process input networks specified by the path wildcards

	datas: iterable(PathOpts)  - processing path options including the path wildcard
	handler: callable  - handler to be called in the processPath() as handler(netfile, netshf, xargs, tasks),
		netshf means that the processing networks is a shuffle in the non-flat dir structure
	xargs: dict(str, val)  - extra arguments of the handler following after the processing network file
	dflextfn: callable  - function(asymflag) for the default extension of the input files in the path
	tasks: list(tasks)  - root tasks per each algorithm
	fpathids: File  - path ids file opened for the writing or None

	return netnames  - network names with the path id (without the basepath)
	"""
	# Track processed file names to resolve cases when files with the same name present in different input dirs
	# Note: pathids are required at least to set concise job names to see what is executed in runtime
	netnames = {}  # Name to pathid mapping: {Name: counter}
	for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
		xargs['asym'] = popt.asym
		# Resolve wildcards
		pcuropt = copy.copy(popt)  # Path options for the resolved .path wildcard
		for path in glob.iglob(popt.path):  # Allow wildcards
			if os.path.isdir(path):
				# ATTENTION: required to process directories ending with '/' correctly
				# Note: normpath() may change semantics in case symbolic link is used with parent dir:
				# base/linkdir/../a -> base/a, which might be undesirable
				mpath = path.rstrip('/')  # os.path.normpath(path)
			else:
				mpath = os.path.splitext(path)[0]
			net = os.path.split(mpath)[1]
			pathid = netnames.get(net)
			if pathid is None:
				netnames[net] = 0
				xargs['pathidstr'] = ''
			else:
				pathid += 1
				netnames[net] = pathid
				nameid = SEPPATHID + str(pathid)
				xargs['pathidstr'] = nameid
				if fpathids is not None:
					fpathids.write('{}\t{}\n'.format(net + nameid, mpath))
			#if _DEBUG_TRACE >= 2:
			#	print('  Processing "{}", net: {}, pathidstr: {}'.format(path, net, xargs['pathidstr']))
			pcuropt.path = path
			if _DEBUG_TRACE:
				print('  Scheduling apps execution for the path options ({})'.format(str(pcuropt)))
			processPath(pcuropt, handler, xargs=xargs, dflextfn=dflextfn, tasks=tasks)
	return netnames


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


def appnames(appsmodule):
	"""Get names of the executable applications from the module

	appsmodule  - module that implements execution of the apps
	return  - list of the apps names
	"""
	return [funcToAppName(func) for func in dir(appsmodule) if func.startswith(PREFEXEC)]


def runApps(appsmodule, algorithms, datas, seed, exectime, timeout, runtimeout=10*24*60*60):  # 10 days
	"""Run specified applications (clustering algorithms) on the specified datasets

	appsmodule  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms  - list of the algorithms to be executed
	datas: iterable(PathOpts)  - input datasets, wildcards of files or directories containing files
		of the default extensions .ns{{e,a}}
	seed  - benchmark seed, natural number
	exectime  - elapsed time since the benchmarking started
	timeout  - timeout per each algorithm execution
	runtimeout  - timeout for all algorithms execution, >= 0, 0 means unlimited time

	return  netnames: iterable(str) or None  - network names with path id and without the base direcotry
	"""
	netnames = None  # Network names with path id and without the base direcotry
	if not datas:
		print('WRANING runApps(), there are no input datasets specified to be clustered', file=sys.stderr)
		return netnames
	assert appsmodule and isinstance(datas[0], PathOpts) and exectime + 0 >= 0 and timeout + 0 >= 0, 'Invalid input arguments'
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
		if not algorithms:
			# Save algorithms names to perform results aggregation after the execution
			algorithms = appnames(appsmodule)
			#algorithms = [alg.lower() for alg in algorithms]
		# Execute the specified algorithms
		execalgs = [getattr(appsmodule, PREFEXEC + alg, None) for alg in algorithms]
		# Ensure that all specified algorithms correspond to the functions
		invalalgs = []
		for i in range(len(execalgs)):
			if execalgs[i] is None:
				invalalgs.append(i)
		if invalalgs:
			print('WARNING, the specified algorithms are omitted as not existent: '
				, ' '.join([algorithms[ia] for ia in invalalgs]), file=sys.stderr)
			while invalalgs:
				i = invalalgs.pop()
				del algorithms[i]
				del execalgs[i]
		assert len(algorithms) == len(execalgs), 'execalgs are not synced with the algorithms'

		def runapp(net, asym, netshf, pathid='', tasks=None):
			"""Execute algorithms on the specified network counting number of ran jobs

			net  - network to be processed
			asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions
			netshf  - whether this network is a shuffle in the non-flat dir structure
			pathid  - path id of the net to distinguish nets with the same name located in different dirs
			tasks: list(Task)  - tasks associated with the running algorithms on the specified network

			return
				jobsnum  - the number of scheduled jobs, typically 1
			"""
			jobsnum = 0
			netext = os.path.splitext(net)[1].lower()
			for ia, ealg in enumerate(execalgs):
				try:
					jobsnum += ealg(_execpool, net, asym=asymnet(netext, asym), odir=netshf
						, timeout=timeout, pathid=pathid, task=None if not tasks else tasks[ia], seed=seed)
				except Exception as err:  #pylint: disable=W0703
					errexectime = time.perf_counter() - exectime
					print('ERROR, "{}" is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s), call stack:'
						.format(ealg.__name__, err, errexectime, *secondsToHms(errexectime)), file=sys.stderr)
					# traceback.print_stack(limit=5, file=sys.stderr)
					traceback.print_exc(5)
			return jobsnum

		def runner(net, netshf, xargs, tasks=None):
			"""Network runner helper

			net  - network file name
			netshf  - whether this network is a shuffle in the non-flat dir structure
			xargs  - extra custom parameters
			tasks: list(Task)  - tasks associated with the running algorithms on the specified network
			"""
			tnum = runapp(net, xargs['asym'], netshf, xargs['pathidstr'], tasks)
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
				 'pathidstr': '',  # Id of the duplicated path shortcut to have the unique shortcut
				 'jobsnum': 0,  # Number of the processing network jobs (can be several per each instance if shuffles exist)
				 'netcount': 0}  # Number of processing network instances (includes multiple shuffles)
			tasks = [Task(appname) for appname in algorithms]
			netnames = processNetworks(datas, runner, xargs=xargs, dflextfn=dflnetext, tasks=tasks, fpathids=fpathids)
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
			# Extend algorithms execution tracing files (.rcp) with time tracing, once per an executing algorithm
			# to distinguish different executions (benchmark runs)
			for alg in algorithms:
				aresdir = RESDIR + alg
				# if not os.path.exists(aresdir):
				# 	os.mkdir(aresdir)
				aexecres = ''.join((aresdir, '/', alg, EXTEXECTIME))
				# Output timings only to the existing files after the execution results
				# to not affect the original header
				if os.path.isfile(aexecres):
					with open(aexecres, 'a') as faexres:
						faexres.write('# --- {time} (seed: {seed}) ---\n'.format(time=TIMESTAMP_START_STR, seed=seed))  # Write timestamp

	_execpool = None
	stime = time.perf_counter() - stime
	print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
	 .format(stime, *secondsToHms(stime)))
	print('Aggregating execution statistics...')
	aggexec(algorithms)
	print('Execution statistics aggregated')
	return netnames


def evalResults(qmsmodule, qmeasures, appsmodule, algorithms, datas, seed, exectime, timeout  #pylint: disable=W0613
, evaltimeout=14*24*60*60, update=False, netnames=None):  #pylint: disable=W0613
	"""Run specified applications (clustering algorithms) on the specified datasets

	qmsmodule: module  - module with quality measures definitions to be run; sys.modules[__name__]
	qmeasures: iterable(str)  - evaluating quality measures with their parameters
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
	update: bool  - update evaluations file or create a new one, anyway existed evaluations
		are backed up.
	netnames: iterable(str)  - input network names with path id and without the base path,
		used to form meta data in the evaluation storage. Explicit specification is useful
		if the netnames were been already formed on the clustering execution and
		the intrinsic measures are not used (otherwise netnames are evalauted there).
	"""
	if not datas:
		print('WRANING evalResults(), there are no input datasets specified to be clustered', file=sys.stderr)
		return
	if qmeasures is None:
		print('WRANING evalResults(), there are no quality measures specified to be evaluated', file=sys.stderr)
		return
	assert qmsmodule and appsmodule and isinstance(datas[0], PathOpts) and exectime + 0 >= 0 and timeout + 0 >= 0, 'Invalid input arguments'
	assert isinstance(seed, int) and seed >= 0, 'Seed value is invalid'

	stime = time.perf_counter()  # Procedure start time; ATTENTION: .perf_counter() should not be used, because it does not consider "sleep" time
	print('Starting quality evaluations...')

	# Run evaluations by all quality measures if not specified the concrete measures for the evaluation
	if not qmeasures:
		qmeasures = appnames(qmsmodule)
	# Run evaluations for all algs if not specified the concrete algorithms to be run
	if not algorithms:
		algorithms = appnames(appsmodule)

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'

	# Prepare HDF5 evaluations store
	with QualitySaver(algs=algorithms, qms=qmeasures, seed=seed, nets=netnames, update=update) as qualsaver:
		# TODO: consider QMSRAFN, actual for Gnmi
		tasks = [Task(qmname) for qmname in qmeasures]

# 		def evalquality(execpool, evalapps, net, asym, netshf, pathids=None):
# 			"""Evaluate algorithms results on the specified network counting number of ran jobs

# 			net  - network to be processed
# 			asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions
# 			netshf  - whether this network is a shuffle in the non-flat dir structure
# 			pathid  - path id of the net to distinguish nets with the same name located in different dirs

# 			return
# 				jobsnum  - the number of scheduled jobs, typically 1
# 			"""
# 			jobsnum = 0
# 			netext = os.path.splitext(net)[1].lower()
# 			for eapp in evalapps:
# 				try:
# 					jobsnum += eapp(execpool, qualsaver, net, asym=asymnet(netext, asym), odir=netshf, timeout=timeout, pathids=pathids, seed=seed)
# 				except Exception as err:
# 					errexectime = time.perf_counter() - exectime
# 					print('ERROR, "{}" is interrupted by the exception: {} on {:.4f} sec ({} h {} m {:.4f} s), call stack:'
# 						.format(eapp.__name__, err, errexectime, *secondsToHms(errexectime)), file=sys.stderr)
# 					#traceback.print_stack(limit=5, file=sys.stderr)
#					traceback.print_exc(5)
# 			# Note: jobs are executed asynchronously, so here none of them is completed
# 			#_STORAGE_FILE.flush()  # Write results to the persistent storage
# 			return jobsnum

# 		def runeval(net, netshf, xargs):  # TODO: default ext
# 			"""Clustering evaluation runner

# 			net  - network file name
# 			netshf  - whether this network is a shuffle in the non-flat dir structure
# 			xargs  - extra custom parameters
# 			"""
# 			tnum = evalquality(xargs['execpool'], xargs['evaluators'], net, xargs['asym'], netshf, pathids)
# 			xargs['jobsnum'] += tnum
# 			xargs['netcount'] += tnum != 0

# 		def dflclsext(asym=None):
# 			"""Get default file extension for the resulting clustering

# 			asym  - whether the input network is asymmetric (directed) or symmetric (undirected)

# 			return  - respective extension of the network file having leading '.'
# 			"""
# 			return '.cnl'

# 		xargs = {'execpool': None,  # Execution pool to schedule evaluators
# 			 'evaluators': None,  # Evaluating functions
# 			 'asym': False,  # Asymmetric network, required for the intrinsic measures
# 			 'pathidstr': '',  # Id of the duplicated path shortcut to have the unique shortcut
# 			 'jobsnum': 0,  # Number of the processed network jobs (can be several per each instance if shuffles exist)
# 			 'netcount': 0}  # Number of converted network instances (includes multiple shuffles)

# 		# ATTENTION: NMI ovp multiresolution should be evaluated in the dedicated mode requiring multiple CPU cores,
# 		# so it will be scheduled separately after other measures
# 		# Note: afnstep = 1 to maximize parallelization the same time binding single-treaded apps to the logical CPUs (hardware threads)
# 		xargs['evaluators'] = evaluators(quality & 0xFFFC)  # Skip gecmi (Multiresolution Overlapping NMI) because it requires special scheduling
# 		if xargs['evaluators']:
# 			print('  Scheduling quality evaluation for the evaluators: ', ', '.join(
# 				[funcToAppName(func.__name__) for func in xargs['evaluators']]))
# 			with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1), memlimit=_VMLIMIT, name='qualityst', webuiapp=_webuiapp) as _execpool:
# 				xargs['execpool'] = _execpool
# 				# Load pathid mapping (nameid: fullpath)
# 				pathids = {}
# 				if os.path.isfile(_PATHIDFILE):
# 					with open(_PATHIDFILE) as fpais:
# 						for ln in fpais:
# 							# Skip comments
# 							if not ln or ln[0] == '#':
# 								continue
# 							fnamex, path = ln.split(None, 1)  # Filename extended with id, full path to the input file
# 							pathids[fnamex] = path
# 					if pathids:
# 						print('Pathid mapping loaded: {} items'.format(len(pathids)))
# 				else:
# 					print('WARNING, pathid mapping does not exist', file=sys.stderr)

# 				# Track processed file names to resolve cases when files with the same name present in different input dirs
# 				# Note: pathids are required at least to set concise job names to see what is executed in runtime
# 				netnames = {}  # Name to pathid mapping: {Name: counter}
# 				for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
# 					xargs['asym'] = popt.asym
# 					# Resolve wildcards
# 					pcuropt = copy.copy(popt)  # Path options for the resolved wildcard
# 					for path in glob.iglob(popt.path):  # Allow wildcards
# 						# Form non-empty pathid string for the duplicated file names
# 						if os.path.isdir(path):
# 							# ATTENTION: required to process directories ending with '/' correctly
# 							# Note: normpath() may change semantics in case symbolic link is used with parent dir:
# 							# base/linkdir/../a -> base/a, which might be undesirable
# 							mpath = path.rstrip('/')  # os.path.normpath(path)
# 						else:
# 							mpath = os.path.splitext(path)[0]
# 						net = os.path.split(mpath)[1]
# 						pathid = netnames.get(net)
# 						if pathid is None:
# 							netnames[net] = 0
# 							xargs['pathidstr'] = ''
# 						else:
# 							pathid += 1
# 							netnames[net] = pathid
# 							nameid = SEPPATHID + str(pathid)
# 							xargs['pathidstr'] = nameid
# 							# Validate loaded pathids mapping
# 							if pathids.get(nameid) != mpath:
# 								raise ValueError('ERROR, "{}" mapping validation failed.'
# 									' Can not find correspondence of the ground truth files to the evaluating clusterings.')
# 						pcuropt.path = path
# 						if _DEBUG_TRACE:
# 							print('  Scheduling quality evaluation for the path options ({})'.format(str(pcuropt)))
# 						processPath(pcuropt, runeval, xargs=xargs, dflextfn=dflclsext)
# 				netnames.clear()
# 				pathids = None  # Release loaded pathid mapping
# 				if evaltimeout <= 0:
# 					evaltimeout = timeout * xargs['jobsnum']
# 				timelim = min(timeout * xargs['jobsnum'], evaltimeout)
# 				print('Waiting for the quality evaluation on {} jobs from {} networks'
# 					' with {} sec ({} h {} m {:.4f} s) timeout ...'
# 					.format(xargs['jobsnum'], xargs['netcount'], timelim, *secondsToHms(timelim)))
# 				try:
# 					_execpool.join(timelim)
# 				except BaseException as err:  # Consider also system interruptions not captured by the Exception
# 					print('WARNING{}, quality evaluation execution pool is interrupted by: {}. {}'
# 						.format('' if not _execpool.name else ' ' + _execpool.name
# 						, err, traceback.format_exc(5)), file=sys.stderr)
# 					raise

# 		# Schedule NMI multiresolution overlapping evaluations (gecmi) either on the whole NUMA node or
# 		# on the whole server because gecmi is multi-threaded app with huge number of threads
# 		# Reuse execpool
# 		xargs['evaluators'] = evaluators(quality & 0b11)  # Skip gecmi (Multiresolution Overlapping NMI) because it requires special scheduling
# 		if xargs['evaluators']:
# 			print('  Scheduling quality evaluation for the evaluators: ', ', '.join(
# 				[funcToAppName(func.__name__) for func in xargs['evaluators']]))
# 			if _execpool is not None:
# 				_execpool.name = 'qualitymt'
# 				_execpool.alive = True
# 				_execpool.afnmask = AffinityMask(AffinityMask.NODE_CPUS)
# 			else:
# 				_execpool = ExecPool(_WPROCSMAX, afnmask=AffinityMask(AffinityMask.NODE_CPUS), memlimit=_VMLIMIT, name='qualitymt', webuiapp=_webuiapp)

# 			with _execpool:
# 				xargs['execpool'] = _execpool

# 				# Track processed file names to resolve cases when files with the same name present in different input dirs
# 				# Note: pathids are required at least to set concise job names to see what is executed in runtime
# 				for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
# 					xargs['asym'] = popt.asym
# 					# Resolve wildcards
# 					pcuropt = copy.copy(popt)  # Path options for the resolved wildcard
# 					for path in glob.iglob(popt.path):  # Allow wildcards
# 						# Form non-empty pathid string for the duplicated file names
# 						if os.path.isdir(path):
# 							# ATTENTION: required to process directories ending with '/' correctly
# 							# Note: normpath() may change semantics in case symbolic link is used with parent dir:
# 							# base/linkdir/../a -> base/a, which might be undesirable
# 							net = path.rstrip('/')  # os.path.normpath(path)
# 						else:
# 							net = os.path.splitext(path)[0]
# 						net = os.path.split(net)[1]
# 						pathid = netnames.get(net)
# 						if pathid is None:
# 							netnames[net] = 0
# 							xargs['pathidstr'] = ''
# 						else:
# 							pathid += 1
# 							netnames[net] = pathid
# 							nameid = SEPPATHID + str(pathid)
# 							xargs['pathidstr'] = nameid
# 						pcuropt.path = path
# 						if _DEBUG_TRACE:
# 							print('  Scheduling quality evaluation for the path options ({})'.format(str(pcuropt)))
# 						processPath(pcuropt, runeval, xargs=xargs, dflextfn=dflclsext)
# 				netnames = None

# 				# Extend quality evaluation tracing files (.rcp) with time tracing to distinguish different executions (benchmark runs)
# 				evaluator.mark(algorithms, seed)

# 				for alg in algorithms:
# 					aexecres = ''.join((RESDIR, alg, '/', measure, EXTEXECTIME))
# 					with open(aexecres, 'a') as faexres:
# 						faexres.write('# --- {time} (seed: {seed}) ---\n'.format(time=TIMESTAMP_START_STR, seed=seed))  # Write timestamp

# 				if runtimeout <= 0:
# 					runtimeout = timeout * xargs['jobsnum']
# 				timelim = min(timeout * xargs['jobsnum'], runtimeout)
# 				elapsed = time.perf_counter() - stime  # Elapsed time
# 				timelim -= elapsed
# 				if timelim > 0:
# 					print('Waiting for the quality evaluation on {} jobs from {} networks'
# 						' with {} sec ({} h {} m {:.4f} s) timeout ...'
# 						.format(xargs['jobsnum'], xargs['netcount'], timelim, *secondsToHms(timelim)))
# 					try:
# 						_execpool.join(timelim)
# 					except BaseException as err:  # Consider also system interruptions not captured by the Exception
# 						print('WARNING{}, quality evaluation execution pool is interrupted by: {}. {}'
# 							.format('' if not _execpool.name else ' ' + _execpool.name
# 							, err, traceback.format_exc(5)), file=sys.stderr)
# 						raise
# 				else:
# 					print('WARNING {}, the execution pool is terminated by the timeout of {} sec,'
# 						', executed {} sec ({} h {} m {:.4f} s)'.format(
# 						 '' if not _execpool.name else ' ' + _execpool.name
# 						 , timelim + elapsed, elapsed, *secondsToHms(elapsed), file=sys.stderr))
# 			# _execpool = None
# 			# stime = time.perf_counter() - stime
# 			# print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
# 			# 	.format(stime, *secondsToHms(stime)))
# 			# print('Aggregating execution statistics...')
# 			# aggexec(algorithms)
# 			# print('Execution statistics aggregated')


# 			# def evaluate(measure, basefile, asym, jobsnum, pathid=''):
# 			# 	"""Evaluate algorithms on the specified network
# 			#
# 			# 	measure  - target measure to be evaluated: {nmi, mod}
# 			# 	basefile  - ground truth result, or initial network file or another measure-related file
# 			# 	asym  - network links weights are asymmetric (in/outbound weights can be different)
# 			# 	jobsnum  - accumulated number of scheduled jobs
# 			# 	pathid  - path id of the basefile to distinguish files with the same name located in different dirs
# 			# 		Note: pathid includes pathid separator
# 			#
# 			# 	return
# 			# 		jobsnum  - updated accumulated number of scheduled jobs
# 			# 	"""
# 			# 	assert not pathid or pathid[0] == SEPPATHID, 'pathid must include pathid separator'
# 			#
# 			# 	for algname in evalalgs:
# 			# 		try:
# 			# 			evalAlgorithm(_execpool, algname, basefile, measure, timeout, evagg, pathid)
# 			# 			## Evaluate also nmi_s besides nmi if required
# 			# 			if quality & im == 3:
# 			# 			#if measure == 'nmi':
# 			# 				evalAlgorithm(_execpool, algname, basefile, 'nmi_s', timeout, evagg_s, pathid)
# 			# 		except Exception as err:
# 			# 			print('ERROR, "{}" evaluation of "{}" is interrupted by the exception: {}. {}'
# 			# 				.format(measure, algname, err, traceback.format_exc(5)), file=sys.stderr)
# 			# 		else:
# 			# 			jobsnum += 1
# 			# 	return jobsnum
# 			#
# 			# # Measures is a dict with the Array values: <evalcallback_prefix>, <grounttruthnet_extension>, <measure_name>
# 			# measures = {3: ['nmi', _EXTCLNODES, 'NMIs'], 4: ['mod', '.rcg', 'Q']}
# 			# evaggs = []  # Evaluation results aggregators
# 			# for im, msr in viewitems(measures):  # Note: the number of measures is small
# 			# 	# Evaluate only required measures
# 			# 	if quality & im == 0:
# 			# 		continue
# 			# 	if im == 3:
# 			# 		# Exclude NMI if it is aplied, but quality & 1 == 0
# 			# 		if quality & 1 == 0:
# 			# 			msr[0] = 'nmi_s'
# 			# 			msr[2] = 'NMI_s'
# 			# 		elif quality & 2 == 0:
# 			# 			msr[2] = 'NMI'
# 			# 		else:
# 			# 			evagg_s = EvalsAgg('nmi_s')  # Reserve also second results aggregator for nmi_s
# 			# 			evaggs.append(evagg_s)
# 			# 	evagg = EvalsAgg(msr[0])  # Evaluation results aggregator
# 			# 	evaggs.append(evagg)
# 			#
# 			# 	if not algorithms:
# 			# 		# Fetch available algorithms
# 			# 		evalalgs = appnames(appsmodule)
# 			# 	else:
# 			# 		evalalgs = [alg for alg in algorithms]  # .lower()
# 			# 	evalalgs = tuple(evalalgs)
# 			#
# 			# print('Starting {} evaluation...'.format(msr[2]))
# 			# jobsnum = 0
# 			# measure = msr[0]
# 			# fileext = msr[1]  # Initial networks in .rcg format are required for mod, clusters for NMIs
# 			# # Track processed file names to resolve cases when files with the same name present in different input dirs
# 			# filenames = set()
# 			# for pathid, (asym, ddir) in enumerate(datadirs):
# 			# 	pathid = SEPPATHID + str(pathid)
# 			# 	# Read ground truth
# 			# 	for basefile in glob.iglob('*'.join((ddir, fileext))):  # Allow wildcards in the names
# 			# 		netname = os.path.split(basefile)[1]
# 			# 		ambiguous = False  # Net name is unambiguous even without the dir
# 			# 		if netname not in filenames:
# 			# 			filenames.add(netname)
# 			# 		else:
# 			# 			ambiguous = True
# 			# 		evaluate(measure, basefile, asym, jobsnum, pathid if ambiguous else '')
# 			# for pathid, (asym, basefile) in enumerate(datafiles):
# 			# 	#pathid = ''.join((SEPPATHID, _PATHID_FILE, str(pathid)))
# 			# 	pathid = ''.join((SEPPATHID, str(pathid)))
# 			# 	# Use files with required extension
# 			# 	basefile = os.path.splitext(basefile)[0] + fileext
# 			# 	netname = os.path.split(basefile)[1]
# 			# 	ambiguous = False  # Net name is unambiguous even without the dir
# 			# 	if netname not in filenames:
# 			# 		filenames.add(netname)
# 			# 	else:
# 			# 		ambiguous = True
# 			# 	evaluate(basefile, asym, jobsnum, pathid if ambiguous else '')
# 			# print('{} evaluation is scheduled'.format(msr[2]))
# 			# filenames = None  # Free memory from filenames
# 			#
# 			# if evaltimeout <= 0:
# 			# 	evaltimeout = timeout * jobsnum
# 			# timelim = min(timeout * jobsnum, evaltimeout)  # Global timeout, up to N days
# 			# print('Waiting for the evaluations execution on {} jobs'
# 			# 	' with {} sec ({} h {} m {:.4f} s) timeout ...'
# 			# 	.format(jobsnum, timelim, *secondsToHms(timelim)))
# 			# try:
# 			# 	_execpool.join(timelim)  # max(timelim, exectime * 2) - Twice the time of the algorithms execution
# 			# except BaseException as err:  # Consider also system interruptions not captured by the Exception
# 			# 	print('WARNING, results evaluation execution pool is interrupted by: {}. {}'
# 			# 		.format(err, traceback.format_exc(5)), file=sys.stderr)
# 			# 	raise

# 	# TODO: aggregate and visualize quality evaluation results
# 	qualsaver.storage.close()
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
		'\n\trunalgs: {}\n\talgorithms: {}\n\tquality measures: {}\n\tqupdate: {}\n\tdatas: {}'
		'\n\taggrespaths: {}\n\twebui: {}\n\ttimeout: {} h {} m {:.4f} sec'
	 .format(opts.syntpo, opts.convnets, opts.runalgs
		, ', '.join(opts.algorithms) if opts.algorithms else ''
		, None if opts.qmeasures is None else ' '.join([qm[0] for qm in opts.qmeasures]), opts.qupdate
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
	netnames = None
	if opts.runalgs:
		netnames = runApps(appsmodule=benchapps, algorithms=opts.algorithms, datas=opts.datas
			, seed=seed, exectime=exectime, timeout=opts.timeout, runtimeout=opts.runtimeout)

	# Evaluate results
	if opts.qmeasures is not None:
		evalResults(qmsmodule=benchevals, qmeasures=opts.qmeasures, appsmodule=benchapps
			, algorithms=opts.algorithms, datas=opts.datas, seed=seed, exectime=exectime
			, timeout=opts.timeout, evaltimeout=opts.evaltimeout, update=opts.qupdate, netnames=netnames)

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
		apps = appnames(benchapps)
		qmapps = appnames(benchevals)
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
			'  - Existent shuffles are backed up if reduced, the existend shuffles are RETAINED and only the additional'
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
			' evalations omitting the already existent) until --quality-revalue is specified.',
			'Notations of the quality mesurements:',
			' = Extrinsic Quality (Accuracy) Measures =',
			'   - GNMI[_{{max,sqrt}}]  - Generalized Normalized Mutual Information for overlapping and multi-resolution clusterings'
			' (collections of clusters), equals to the standard NMI when applied to the non-overlapping single-resolution clusterings.',
			'   - MF1{{p,h,a}}[_{{w,u,c}}]  - mean F1 measure (harmonic or average) of all local best matches by the'
			' Partial Probabilities or F1 (harmonic mean) considering macro/micro/combined weighting.',
			'   - OI[x]  - [x - extended] Omega Index for the overlapping clusterings, non-extended version equals to the'
			' Adjusted Rand Index when applied to the non-overlapping single-resolution clusterings.',
			' --- Less Indicative Extrinsic Quality Measures ---',
			'   - F1{{p,h}}_[{{w,u}}]  - perform labelling of the evaluating clusters with the specified ground-truth'
			' and evaluate F1-measure of the labeled clusters',
			'   - ONMI[_{{max,sqrt,avg,lfk}}]  - Ovelapping NMI suitable for a single-resolution clusterins having light overlaps,'
			' the resulting values are not compatible with the standard NMI when applied to the non-overlapping clsuters.',
			# '   - NMI[_{{max,sqrt,avg,min}}]  - standart NMI for the non-overlapping (disjoint) clusters only.',
			' = Intrinsic Quality Measures =',
			'   - Cdt  - conducance f for the overlapping clustering.',  # Cdt, Cds, f
			'   - Q[a]  - [autoscaled] modularity for the overlapping clustering, non-autoscaled equals to the standard modularity',
			' when applied to the non-overlapping single-resolution clustering.',
			'  --timeout, -t=[<days:int>d][<hours:int>h][<minutes:int>m][<seconds:float>] | -t[X]=<float>  - timeout for each'
			' benchmarking application per single evaluation on each network; 0 - no timeout, default: {algtimeout}. X option:',
			'    s  - time in seconds, default option',
			'    m  - time in minutes',
			'    h  - time in hours',
			'    Examples: `-th=2.5` is the same as `-t=2h30m` and `--timeout=2h1800`',
			'  --quality-revalue  - revalue resulting clusterings with the quality measures from scratch'
			' even if (some) evaluations with the same seed have been already performed.',
			'  --seedfile, -d=<seed_file>  - seed file to be used/created for the synthetic networks generation,'
			' stochastic algorithms and quality measures execution, contains uint64_t value. Default: {seedfile}.',
			'NOTE:',
			'  - The seed file is not used on shuffling, so the shuffles are DISTINCT for the same seed.',
			'  - Each reexecution of the benchmarking reuses once created seed file, which is permanent'
			' and can be updated manually.',
			'',
			'Advanced parameters:',
			#'  --stderr-stamp  - output a time stamp to the stderr on the benchmarking start to separate multiple re-exectuions',
			'  --convret, -c[X]  - convert input networks into the required formats (app-specific formats: .rcg[.hig], .lig, etc.), deprecated',
			'    f  - force the conversion even when the data is already exist',
			'    r  - resolve (remove) duplicated links on conversion (recommended to be used)',
			'  --summary, -s=<resval_path>  - aggregate and summarize specified evaluations extending the benchmarking results'
			', which is useful to include external manual evaluations into the final summarized results',
			'ATTENTION: <resval_path> should include the algorithm name and target measure.',
			'  --webaddr, -w  - run WebUI on the specified <webui_addr> in the format <host>[:<port>], default port={port}.',
			'  --runtimeout  - global clustrering algorithms execution timeout in the'
			' format [<days>d][<hours>h][<minutes>m<seconds>], default: {runtimeout}.',
			'  --evaltimeout  - global clustrering algorithms execution timeout in the'
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
