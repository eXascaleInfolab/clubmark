#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: A modular benchmark, wich optionally generates and preprocesses (shuffles,
	i.e. reorder nodes in the networks) datasets using specified executable,
	optionally executes specified applications (clustering algorithms) with
	specified parameters on the specified datasets,	and optionally evaluates
	results of the execution using specified executable(s).

	All executions are traced and resources consumption is logged as:
	CPU (user, kernel, etc.) and memory (RSS RAM).
	Traces are saved even in case of internal / external interruptions and crashes.

	= Overlapping Hierarchical Clustering Benchmark =
	Implemented:
	- synthetic datasets are generated using extended LFR Framework (origin: https://sites.google.com/site/santofortunato/inthepress2,
		which is "Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities"
		by Andrea Lancichinetti 1 and Santo Fortunato) and producing specified number of instances per each set of parameters (there
		can be varying network instances for the same set of generating parameters);
	- networks are shuffled (nodes are reordered) to evaluate stability / determinism of the clsutering algorithm;
	- executes HiReCS (www.lumais.com/hirecs), Louvain (original https://sites.google.com/site/findcommunities/ and igraph implementations),
		Oslom2 (http://www.oslom.org/software.htm)m Ganxis/SLPA (https://sites.google.com/site/communitydetectionslpa/) and
		SCP (http://www.lce.hut.fi/~mtkivela/kclique.html) clustering algorithms on the generated synthetic networks and real world networks;
	- evaluates results using NMI for overlapping communities, extended versions of:
		* gecmi (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information"
			by Alcides Viamontes Esquivel, Martin Rosvall),
		* onmi (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping
			community finding algorithms" by  Aaron F. McDaid, Derek Greene, Neil Hurley);
	- resources consumption is evaluated using exectime profiler (https://bitbucket.org/lumais/exectime/).

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-04
"""

from __future__ import print_function, division  # Required for stderr output, must be the first import
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
import time
import os
import shutil
import signal  # Intercept kill signals
import glob
import traceback  # Stacktrace
import copy
import benchapps  # Required for the functions name mapping to/from the app names

from math import sqrt
from multiprocessing import cpu_count  # Returns the number of multi-core CPU units if defined
from benchutils import viewitems, timeSeed, SyncValue, dirempty, tobackup, _SEPPARS, _SEPINST, \
	_SEPSHF, _SEPPATHID, _UTILDIR, _TIMESTAMP_START_STR, _TIMESTAMP_START_HEADER
# PYEXEC - current Python interpreter
from benchapps import PYEXEC, aggexec, funcToAppName, _ALGSDIR, _EXTCLNODES, _PREFEXEC
from benchevals import QualitySaver, evaluators, aggEvaluations, _RESDIR, _EXTEXECTIME
from utils.mpepool import AffinityMask, ExecPool, Job, secondsToHms
from algorithms.utils.parser_nsl import asymnet, dflnetext


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_SYNTDIR = 'syntnets/'  # Default base directory for the synthetic datasets (both networks, params and seeds)
_NETSDIR = 'networks/'  # Networks sub-directory of the synthetic networks (inside _SYNTDIR)
assert _RESDIR.endswith('/'), 'A directory should have a valid terminator'
_SEEDFILE = _RESDIR + 'seed.txt'
_PATHIDFILE = _RESDIR + 'pathid.map'  # Path id map file for the results iterpratation (mapping back to the input networks)
_TIMEOUT = 36 * 60*60  # Default execution timeout for each algorithm for a single network instance
_GENSEPSHF = '%'  # Shuffle number separator in the synthetic networks generation parameters
_WPROCSMAX = max(cpu_count()-1, 1)  # Maximal number of the worker processes, should be >= 1
assert _WPROCSMAX >= 1, 'Natural number is expected not exceeding the number of system cores'
_VMLIMIT = 1024  # Set 1 TB or RAM to be automatically limited to the physical memory of the computer

#_TRACE = 1  # Tracing level: 0 - none, 1 - lightweight, 2 - debug, 3 - detailed
_DEBUG_TRACE = False  # Trace start / stop and other events to stderr

# Pool of executors to process jobs, the global variable is required to terminate
# the worker processes on external signal (TERM, KILL, etc.)
_execpool = None


# Data structures --------------------------------------------------------------
class PathOpts(object):
	"""Paths parameters"""
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
		self.path = path
		self.flat = flat
		self.asym = asym
		self.shfnum = shfnum  # Number of shuffles for each network instance to be produced, >= 0

	def __str__(self):
		"""String conversion"""
		return ', '.join([': '.join((name, str(val))) for name, val in viewitems(self.__dict__)])


class SyntPathOpts(PathOpts):
	"""Paths parameters for the synthetic networks"""
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
		convnets  - convert existing networks into the .hig format
			0 - do not convert
			0b001  - convert:
				0b01 - convert only if this network is not exist
				0b11 - force conversion (overwrite all)
			0b100 - resolve duplicated links on conversion
		runalgs  - execute algorithm or not
		quality  - quality measures to evaluate on the results:
			Note: all measures are applicable for overlapping clusters
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
		updqual  - update quality evaluations storage rewriting existed values
			instead of creating a new storage. Allowed only for the same seed.
			The existed quality evaluations are backed up anyway.
		datas: PathOpts  - list of datasets to be run with asym flag (asymmetric
			/ symmetric links weights):
			[PathOpts, ...] , where path is either dir or file [wildcard]
		netext  - network file extension, should have the leading '.'
		timeout  - execution timeout in sec per each algorithm
		algorithms  - algorithms to be executed (just names as in the code)
		aggrespaths = paths for the evaluated resutls aggregation (to be done for
			already existent evaluations)
		seedfile  - seed file name
		"""
		self.syntpo = None  # SyntPathOpts()
		self.runalgs = False
		self.quality = 0
		self.updqual = False
		self.datas = []  # Input datasets, list of PathOpts, where path is either dir or file wildcard
		self.timeout = _TIMEOUT
		self.algorithms = []
		self.seedfile = _SEEDFILE  # Seed value for the synthetic networks generation and stochastic algorithms, integer
		self.convnets = 0
		self.aggrespaths = []  # Paths for the evaluated resutls aggregation (to be done for already existent evaluations)


# Input зarameters processing --------------------------------------------------
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
		# Process long args
		if arg[1] == '-':
			if arg == '--stderr-stamp':
				if len(args) == 1:
					raise  ValueError('More input arguments are expected besides: ' + arg)
				print(_TIMESTAMP_START_HEADER, file=sys.stderr)
				continue
			elif arg.startswith('--generate'):
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
			else:
				raise  ValueError('Unexpected argument: ' + arg)

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
			for i in range(2,4):
				if len(arg) > i and (arg[i] not in 'fr'):
					raise ValueError('Unexpected argument: ' + arg)
			arg = arg[2:]
			if 'f' in arg:
				opts.convnets |= 0b10
			if 'r' in arg:
				opts.convnets |= 0b100
		elif arg[1] == 'a':
			if not (arg[:3] == '-a=' and len(arg) >= 4):
				raise ValueError('Unexpected argument: ' + arg)
			inverse = arg[3] == '-'  # Consider inversing (run all except)
			if inverse and len(arg) <= 4:
				raise ValueError('Unexpected argument: ' + arg)
			opts.algorithms = arg[3 + inverse:].strip('"\'').split()  # Note: argparse automatically performs this escaping
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
			# [-q[e[{{n[x],o[x],f[{{h,p}}],d}}][i[{{m,c}}]]]
			#0b00000001  - NMI_max
			#0b00000011  - all NMIs (max, min, avg, sqrt)
			#0b00000100  - ONMI_max
			#0b00001100  - all ONMIs (max, avg, lfk)
			#0b00010000  - Average F1h Score
			#0b00100000  - F1p measure
			#0b01110000  - All F1s (F1p, F1h, F1s)
			#0b10000000  - Default extrinsic measures (NMI_max, F1h and F1p)
			#0b1111'1111  - All extrinsic measures (NMI-s, ONMI-s, F1-s)
			#0x1xx  - Q (modularity)
			#0x2xx  - f (conductance)
			#0xFxx  - All intrinsic measures
			quality = 0  # Quality measures bitmask
			pos = 2
			if len(arg) == pos:
				quality = 0b10000000  # Use default extrinsic measures
			elif arg[pos] == 'e':
				pos += 1
				if len(arg) == pos:
					quality |= 0xFF  # All extrinsic measures
				elif arg[pos] == 'n':
					pos += 1
					if len(arg) == pos:
						quality |= 0b11  # All NMIs
					elif arg[pos] == 'x':
						quality |= 0b01  # NMI_max
				elif arg[pos] == 'o':
					pos += 1
					if len(arg) == pos:
						quality |= 0b1100  # All ONMIs
					elif arg[pos] == 'x':
						quality |= 0b0100  # ONMI_max
				elif arg[pos] == 'f':
					pos += 1
					if len(arg) == pos:
						quality |= 0b1110000  # All F1s
					elif arg[pos] == 'h':
						quality |= 0b0010000  # F1h
					elif arg[pos] == 'p':
						quality |= 0b0100000  # F1p
				elif arg[pos] == 'r':  # Recommended extrinsic measures
					quality |= 0b0110001  # NMI_max, F1h, F1p
			elif arg[pos] == 'i':
				pos += 1
				if len(arg) == pos:
					quality |= 0xF00  # All intrinsic measures
				elif arg[pos] == 'm':
					quality |= 0x100  # Modularity
				elif arg[pos] == 'c':
					quality |= 0x200  # Conductance
			elif arg[pos] == 'u' and len(arg) == pos+1:
				opts.updqual = True
				continue

			if quality:
				opts.quality |= quality
			else:
				raise ValueError('Unexpected argument: ' + arg)
		elif arg[1] == 's':
			if len(arg) <= 3 or arg[2] != '=':
				raise ValueError('Unexpected argument: ' + arg)
			opts.aggrespaths.append(arg[3:].strip('"\''))  # Remove quotes if exist
		elif arg[1] == 't':
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'smh=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			pos += 1
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
		else:
			raise ValueError('Unexpected argument: ' + arg)

	return opts


# Networks processing ----------------------------------------------------------
def generateNets(genbin, insnum, asym=False, basedir=_SYNTDIR, netsdir=_NETSDIR
, overwrite=False, seedfile=_SEEDFILE, gentimeout=3*60*60):  # 2-4 hours
	"""Generate synthetic networks with ground-truth communities and save generation params.
	Previously existed paths with the same name are backuped before being updated.

	genbin  - the binary used to generate the data (full path or relative to the base benchmark dir)
	insnum  - the number of insances of each network to be generated, >= 1
	asym  - generate asymmetric (specified by arcs, directed) instead of undifected networks
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
		# Backup target dirs on rewriting, removing backuped content
		elif overwrite and not dirempty(dirname):
			tobackup(dirname, False, bcksuffix, move=True)  # Move to the backup
			os.mkdir(dirname)

	# Initial options for the networks generation
	N0 = 1000  # Satrting number of nodes
	rmaxK = 3  # Min ratio of the max degree relative to the avg degree
	# 1K ** 0.618 -> 71,  100K -> 1.2K
	evalmaxk = lambda genopts: int(max(genopts['N'] ** 0.618, genopts['k']*rmaxK))  # 0.618 is 1/golden_ratio; sqrt(n), but not less than rmaxK times of the average degree  => average degree should be <= N/rmaxK
	evalmuw = lambda genopts: genopts['mut'] * 0.75
	evalminc = lambda genopts: 2 + int(sqrt(genopts['N'] / N0))
	evalmaxc = lambda genopts: int(genopts['N'] / 3)
	evalon = lambda genopts: int(genopts['N'] * genopts['mut']**2)  # The number of overlapping nodes
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
	# Note: set affinity in a way to maximize the CPU cache L1/2 for each process
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(AffinityMask.CORE_THREADS)
	, memlimit=_VMLIMIT, name='gennets') as _execpool:
		bmname =  os.path.split(genbin)[1]  # Benchmark name
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
					xtimebin = os.path.relpath(_UTILDIR + 'exectime', basedir)
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
						args = [xtimebin, '-n=' + name, ''.join(('-o=', bmname, _EXTEXECTIME))  # Output .rcp in the current dir, basedir
							, genbin, '-f', netparams, '-name', netfile, '-seed', jobseed]
						if asymarg:
							args.extend(asymarg)
						#Job(name, workdir, args, timeout=0, ontimeout=False, onstart=None, ondone=None, tstart=None)
						_execpool.execute(Job(name=name, workdir=basedir, args=args, timeout=netgenTimeout, ontimeout=True
							#, onstart=lambda job: shutil.copy2(randseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
							, onstart=lambda job: shutil.copy2(randseed, netseed)  # Network generation seed
							#, ondone=shuffle if shfnum > 0 else None
							, startdelay=startdelay, category='generate_' + str(k), size=N))
					for i in range(1, insnum):
						namext = ''.join((name, _SEPINST, str(i)))
						netfile = netpath + namext
						if overwrite or not os.path.exists(netfile.join((basedir, netext))):
							args = [xtimebin, '-n=' + namext, ''.join(('-o=', bmname, _EXTEXECTIME))
								, genbin, '-f', netparams, '-name', netfile, '-seed', jobseed]
							if asymarg:
								args.extend(asymarg)
							#Job(name, workdir, args, timeout=0, ontimeout=False, onstart=None, ondone=None, tstart=None)
							_execpool.execute(Job(name=namext, workdir=basedir, args=args, timeout=netgenTimeout, ontimeout=True
								#, onstart=lambda job: shutil.copy2(randseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
								, onstart=lambda job: shutil.copy2(randseed, netseed)  # Network generation seed
								#, ondone=shuffle if shfnum > 0 else None
								, startdelay=startdelay, category='generate_' + str(k), size=N))
				else:
					print('ERROR: network parameters file "{}" does not exist'.format(fnamex), file=sys.stderr)
		print('Parameter files generation completed')
		if gentimeout <= 0:
			gentimeout = insnum * netgenTimeout
		# Note: insnum*netgenTimeout is max time required for the largest instances generation,
		# insnum*2 to consider all smaller networks
		try:
			_execpool.join(min(gentimeout, insnum*2*netgenTimeout))
		except BaseException as err:  # Consider also system iteruptions not captured by the Exception
			print('ERROR, network generation execution pool is interrupted by: {}. {}'
				.format(err, traceback.format_exc()), file=sys.stderr)
			raise
	_execpool = None
	print('Synthetic networks files generation completed')


def shuffleNets(datas, timeout1=7*60, shftimeout=30*60):  # 7, 30 min
	"""Shuffle specified networks backing up and updateing exsinting shuffles.
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

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Note: afnstep = 1 because the processes are not cache-intencive, not None, because the workers are single-threaded
	shufnets = 0  # The number of shuffled networks
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1), memlimit=_VMLIMIT, name='shufnets') as _execpool:
		def shuffle(job):
			"""Shufle network instance specified by the job"""
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
""".format(jobname=job.name, sepshf=_SEPSHF, netext=job.params['netext'], shfnum=job.params['shfnum']
, overwrite=False))  # Skip the shuffling if the respective file already exists
			job.name += '_shf'  # Update jobname to cleary associate it with the shuffling process
			_execpool.execute(job)

		def shuffleNet(netfile, shfnum):
			"""Shuffle specified network produsing cpecified number of shuffles in the same directory

			netfile  - the network instance to be shuffled
			shfnum  - the number of shuffles to be done

			return
				shfnum - number of shufflings to be done or zero if the instance is a shuffle by itself
			"""
			# Remove existing shuffles if required
			path, name = os.path.split(netfile)
			if not path:
				path = '.'  # Note: '/' is added later
			name, netext = os.path.splitext(name)
			if name.find(_SEPSHF) != -1:
				shf = name.rsplit(_SEPSHF, 1)[1]
				# Omit shuffling of the shuffles, remove redundant shuffles
				if int(shf[1:]) > shfnum:
					os.remove(netfile)
				return 0
			# Note: the shuffling might be scheduled even when the shuffles exist in case
			# the origin network is traversed before it's shuffles
			shuffle(Job(name=name, workdir=path + '/', params={'netext': netext, 'shfnum': shfnum}
				, timeout=timeout1*shfnum, category='shuffle', size=os.path.getsize(netfile)))
			return shfnum  # The network is shuffled shfnum times

		def prepareDir(dirname, netfile, bcksuffix=None):
			"""Make the dir if not exists, otherwise move to the backup if the dir is not empty.
			Link the origal network inside the dir.

			dirname  - directory to be initialized or moved to the backup
			netfile  - network file to be linked into the <dirname> dir
			bcksuffix  - backup suffix for the group of directories, formed automatically
				from the SyncValue()

			return  - shuffle0, the origin network filename for the shuffles
			"""
			# Make hard link of the origin network to the target dir if this file does not exist yet
			shuf0 = '/'.join((dirname, os.path.split(netfile)[1]))
			if not os.path.exists(dirname):
				os.mkdir(dirname)
				# Hard link is used to have initial former copy of the archive even when the origin is deleted
				os.link(netfile, shuf0)
			elif not dirempty(dirname):
				tobackup(dirname, False, bcksuffix, move=False)  # Copy to the backup to not regenerate existing networks
			#if os.path.exists(dirname) and not dirempty(dirname):
			#	tobackup(dirname, False, bcksuffix, move=True)  # Move to the backup
			#if not os.path.exists(dirname):
			#	os.mkdir(dirname)
			## Make hard link of the origin network to the target dir if this file does not exist
			#shuf0 = '/'.join((dirname, os.path.split(netfile)[1]))
			#if not os.path.exists(shuf0):
			#	# Hard link is used to have initial former copy of the archive even when the origin is deleted
			#	os.link(netfile, shuf0)
			return shuf0

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
							if netname.find(_SEPSHF) != -1:
								continue
							# Backup existed dir (path, not just a name)
							dirname = os.path.splitext(net)[0]
							shuf0 = prepareDir(dirname, net, bcksuffix)
							shfnum += shuffleNet(shuf0, popt.shfnum)
					else:
						# Backup the whole dir of network instances with possible shuffles,
						# which are going ot be shuffled
						tobackup(path, False, bcksuffix, move=False)  # Copy to the backup
						# Note: the folder containing the network instance origining the shuffling should not be deleted
						for net in glob.iglob('*'.join((path, dflext))):
							shfnum += shuffleNet(net, popt.shfnum)  # Note: shuffleNet() skips of the existing shuffles and performs their reduction
				else:
					# Skip shuffles and their direct backup
					# Note: previous shuffles are backuped from their origin instance
					netname = os.path.split(path)[1]
					if netname.find(_SEPSHF) != -1:
						continue
					# Generate dirs if required
					if not popt.flat:
						dirname = os.path.splitext(path)[0]
						shuf0 = prepareDir(dirname, path, bcksuffix)
						shfnum += shuffleNet(shuf0, popt.shfnum)
					else:
						# Backup existing flat shuffles if any (expanding the base path), which will be updated the subsequent shuffling
						tobackup(path, True, bcksuffix, move=False)  # Copy to the backup
						shfnum += shuffleNet(path, popt.shfnum)  # Note: shuffleNet() skips of the existing shuffles and performs their reduction
				shufnets += 1

		if shftimeout <= 0:
			shftimeout = shfnum * timeout1
		_execpool.join(min(shftimeout, shfnum * timeout1))
	_execpool = None
	if shufnets:
		print('Networks ({}) shuffling completed. NOTE: random seed is not supported for the shuffling'.format(shufnets))


def processPath(popt, handler, xargs=None, dflextfn=dflnetext):
	"""Process the specified path with the specified handler

	popt  - processing path options (the path is directory of file, not a wildcard), PathOpts
	handler  - handler to be called as handler(netfile, netshf, xargs),
		netshf means that the processing networks is a shuffle in the non-flat dir structure
	xargs  - extra arguments of the handler following after the processing network file
	dflextfn  - function(asymflag) for the default extension of the input files in the path
	"""
	assert os.path.exists(popt.path), 'Target path should exist'

	path = popt.path  # Assign path to a local variable to not corrupt the input data
	dflext = dflextfn(popt.asym)  #  dflnetext(popt.asym)  # Default network extension for files in dirs
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
				if netname.find(_SEPSHF) != -1:
					continue
				#if popt.shfnum:  # ATTENTNION: shfnum is not available for non-synthetic networks
				# Process dedicated dir of shufles for the specified network,
				# the origin network itself is linked to the shufles dir (inside it)
				dirname, ext = os.path.splitext(net)
				if os.path.isdir(dirname):
					# Shuffles exist for this network and located in the subdir together with the copy of origin
					for desnet in glob.iglob('/*'.join((dirname, ext))):
						handler(desnet, True, xargs)  # True - shuffle is processed in the non-flat dir structure
				else:
					handler(net, False, xargs)
		else:
			# Both shuffles (if exist any) and network instances are located
			# in the same dir, convert them
			for net in glob.iglob('*'.join((path, dflext))):
				handler(net, False, xargs)
	else:
		if not popt.flat:
			# Skip the shuffles if any to process only specified networks
			# (all target shuffles are located in the dedicated dirs for non-flat paths)
			netname = os.path.split(path)[1]
			if netname.find(_SEPSHF) != -1:
				return
			#if popt.shfnum:  # ATTENTNION: shfnum is not available for non-synthetic networks
			# Process dedicated dir of shufles for the specified network,
			# the origin network itself is linked to the shufles dir (inside it)
			dirname, ext = os.path.splitext(path)
			if os.path.isdir(dirname):
				for desnet in glob.iglob('/*'.join((dirname, ext))):
					handler(desnet, True, xargs)  # True - shuffle is processed in the non-flat dir structure
			else:
				handler(path, False, xargs)
		else:
			handler(path, False, xargs)


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
	print('Converting networks into the required formats (.hig, .lig, etc.)...')

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Note: afnstep = 1 because the processes are not cache-intencive, not None, because the workers are single-threaded
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1), memlimit=_VMLIMIT, name='convnets') as _execpool:
		def convertNet(inpnet, overwrite=False, resdub=False, timeout=7*60):  # 7 min
			"""Convert input networks to another formats

			inpnet  - the network file to be converted
			overwrite  - whether to overwrite existing networks or use them
			resdub  - resolve duplicated links
			timeout  - network conversion timeout, 0 means unlimited
			"""
			try:
				args = [PYEXEC, _UTILDIR + 'convert.py', inpnet, '-o rcg', '-r ' + ('o' if overwrite else 's')]
				if resdub:
					args.append('-d')
				_execpool.execute(Job(name=os.path.splitext(os.path.split(inpnet)[1])[0], args=args, timeout=timeout
					, category='convert', size=os.path.getsize(inpnet)))
			except Exception as err:
				print('ERROR on "{}" conversion into .hig, the network is skipped: {}. {}'
					.format(inpnet, err, traceback.format_exc()), file=sys.stderr)
			#netnoext = os.path.splitext(net)[0]  # Remove the extension
			#
			## Convert to Louvain binaty input format
			#try:
			#	# ./convert [-r] -i graph.txt -o graph.bin -w graph.weights
			#	# r  - renumber nodes
			#	# ATTENTION: original Louvain implementation processes incorrectly weighted networks with uniform weights (=1) if supplied as unweighted
			#	subprocess.call((_ALGSDIR + 'convert', '-i', net, '-o', netnoext + '.lig'
			#		, '-w', netnoext + '.liw'))
			#except Exception as err:
			#	print('ERROR on "{}" conversion into .lig, the network is skipped: {}'.format(net), err, file=sys.stderr)

		def converter(net, netshf, xargs):
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
			convtimeout =  netsnum * timeout1
		_execpool.join(min(convtimeout, netsnum * timeout1))
	_execpool = None
	print('Networks ({}) conversion completed'.format(netsnum))


def appnames(appsmodule):
	"""Get names of the executable applications from the module

	appsmodule  - module that implements execution of the apps
	return  - list of the apps names
	"""
	return [funcToAppName(func) for func in dir(appsmodule) if func.startswith(_PREFEXEC)]


def runApps(appsmodule, algorithms, datas, seed, exectime, timeout, runtimeout=10*24*60*60):  # 10 days
	"""Run specified applications (clustering algorithms) on the specified datasets

	appsmodule  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms  - list of the algorithms to be executed
	datas  - input datasets, wildcards of files or directories containing files
		of the default extensions .ns{{e,a}}, PathOpts
	seed  - benchmark seed, natural number
	exectime  - elapsed time since the benchmarking started
	timeout  - timeout per each algorithm execution
	runtimeout  - timeout for all algorithms execution, >= 0, 0 means unlimited time
	"""
	if not datas:
		return
	assert appsmodule and isinstance(datas[0], PathOpts) and exectime + 0 >= 0 and timeout + 0 >= 0, 'Invalid input arguments'
	assert isinstance(seed, int) and seed >=0, 'Seed value is invalid'

	def unknownApp(name):
		"""A stub for the unknown / not implemented apps (algorithms) to be benchmaked

		name  - name of the funciton to be called (traced and skipped)
		"""
		def stub(*args, **kwargs):
			print(' '.join(('ERROR: ', name, 'function is not implemented, the call is skipped.')), file=sys.stderr)
		stub.__name__ = name  # Set original name to the stub func
		return stub

	stime = time.time()  # Procedure start time; ATTENTION: .clock() should not be used, because it does not consider "sleep" time
	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Note: set affinity in a way to maximize the CPU cache L1/2 for each process
	with ExecPool(_WPROCSMAX, afnmask=AffinityMask(AffinityMask.CORE_THREADS)
	, memlimit=_VMLIMIT, name='runapps') as _execpool:
		# Run all algs if not specified the concrete algorithms to be run
		if not algorithms:
			# Algorithms callers
			execalgs = [getattr(appsmodule, func) for func in dir(appsmodule) if func.startswith(_PREFEXEC)]
			# Save algorithms names to perform resutls aggregation after the execution
			algorithms = appnames(appsmodule)
		else:
			# Execute only specified algorithms
			execalgs = [getattr(appsmodule, _PREFEXEC + alg, unknownApp(_PREFEXEC + alg)) for alg in algorithms]
			#algorithms = [alg.lower() for alg in algorithms]

		def runapp(net, asym, netshf, pathid=''):
			"""Execute algorithms on the specified network counting number of ran jobs

			net  - network to be processed
			asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions
			netshf  - whether this network is a shuffle in the non-flat dir structure
			pathid  - path id of the net to distinguish nets with the same name located in different dirs

			return
				jobsnum  - the number of scheduled jobs, typically 1
			"""
			jobsnum = 0
			netext = os.path.splitext(net)[1].lower()
			for ealg in execalgs:
				try:
					jobsnum += ealg(_execpool, net, asym=asymnet(netext, asym), odir=netshf, timeout=timeout, pathid=pathid, seed=seed)
				except Exception as err:
					errexectime = time.time() - exectime
					print('WARNING, the "{}" is interrupted by the exception: {} with the callstack: {} on {:.4f} sec ({} h {} m {:.4f} s)'
						.format(ealg.__name__, err, traceback.format_exc(), errexectime, *secondsToHms(errexectime)), file=sys.stderr)
			return jobsnum

		def runner(net, netshf, xargs):
			"""Network runner helper

			net  - network file name
			netshf  - whether this network is a shuffle in the non-flat dir structure
			xargs  - extra custom parameters
			"""
			tnum = runapp(net, xargs['asym'], netshf, xargs['pathidstr'])
			xargs['jobsnum'] += tnum
			xargs['netcount'] += tnum != 0

		# Prepare resulting paths mapping file
		fpathids = None  # File of pathes ids
		if not os.path.exists(_RESDIR):
			os.mkdir(_RESDIR)
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
				fpathids.write('# Name{}ID\tPath\n'.format(_SEPPATHID))  # Note: buffer flushing is not nesessary here, beause the execution is not concurrent
			fpathids.write('# --- {time} (seed: {seed}) ---\n'.format(time=_TIMESTAMP_START_STR, seed=seed))  # Write timestamp

			xargs = {'asym': False,  # Asymmetric network
					 'pathidstr': '',  # Id of the dublicated path shortcut to have the unique shortcut
					 'jobsnum': 0,  # Number of the processed network jobs (can be several per each instance if shuffles exist)
					 'netcount': 0}  # Number of converted network instances (includes multiple shuffles)
			# Track processed file names to resolve cases when files with the same name present in different input dirs
			# Note: pathids are required at least to set concise job names to see what is executed in runtime
			netnames = {}  # Name to pathid mapping: {Name: counter}
			for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
				xargs['asym'] = popt.asym
				# Resolve wildcards
				pcuropt = copy.copy(popt)  # Path options for the resolved wildcard
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
						nameid = _SEPPATHID + str(pathid)
						xargs['pathidstr'] = nameid
						fpathids.write('{}\t{}\n'.format(net + nameid, mpath))
					#if _DEBUG_TRACE >= 2:
					#	print('  Processing "{}", net: {}, pathidstr: {}'.format(path, net, xargs['pathidstr']))
					pcuropt.path = path
					if _DEBUG_TRACE:
						print('  Scheduling apps execution for the path options ({})'.format(str(pcuropt)))
					processPath(pcuropt, runner, xargs=xargs)
			netnames = None  # Free memory from filenames

			# Extend algorithms execution tracing files (.rcp) with time tracing, once per an executing algorithm
			# to distinguish different executions (benchmark runs)
			for alg in algorithms:
				aexecres = ''.join((_RESDIR, alg, '/', alg, _EXTEXECTIME))
				with open(aexecres, 'a') as faexres:
					faexres.write('# --- {time} (seed: {seed}) ---\n'.format(time=_TIMESTAMP_START_STR, seed=seed))  # Write timestamp
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
		try:
			_execpool.join(timelim)
		except BaseException as err:  # Consider also system iteruptions not captured by the Exception
			print('ERROR, Algorithms execution pool is interrupted by: {}. {}'
				.format(err, traceback.format_exc()), file=sys.stderr)
			raise
	_execpool = None
	stime = time.time() - stime
	print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(stime, *secondsToHms(stime)))
	print('Aggregating execution statistics...')
	aggexec(algorithms)
	print('Execution statistics aggregated')


def evalResults(quality, appsmodule, algorithms, datas, seed, exectime, timeout
, evaltimeout=14*24*60*60, update=False):
	"""Run specified applications (clustering algorithms) on the specified datasets

	quality  - evaluation measures mask
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
	appsmodule  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms  - list of the algorithms to be executed
	datas  - input datasets, wildcards of files or directories containing files
		of the default extensions .ns{{e,a}}
	seed  - benchmark seed, natural number. Used to mark evaluations file via
		the HDF5 user block.
		ATTENTION: seed is not supported by [some] evaluation apps (gecmi)
	exectime  - elapsed time since the benchmarking started
	timeout  - timeout per each evaluation run, a single measure applied to the results
		of a single algorithm on a single network (all instances and shuffles), >= 0
	evaltimeout  - timeout for all evaluations, >= 0, 0 means unlimited time
	update  - update evalautions file or create a new one, anyway existed evaluations
		are backed up.
	"""
	assert (quality and appsmodule and datas and exectime + 0 >= 0
		and timeout + 0 >= 0), 'Invalid input arguments'
	assert isinstance(seed, int) and seed >=0, 'Seed value is invalid'

	stime = time.time()  # Procedure start time
	print('Starting quality evaluations...')
	# Run evaluations for all algs if not specified the concrete algorithms to be run
	if not algorithms:
		algorithms = appnames(appsmodule)

	global _execpool
	assert _execpool is None, 'The global execution pool should not exist'
	# Prepare HDF5 evaluations store
	with QualitySaver(apps=algorithms, seed=seed, update=update) as qualsaver:
		def evalquality(execpool, evalapps, net, asym, netshf, pathids=None):
			"""Evaluate algorithms results on the specified network counting number of ran jobs

			net  - network to be processed
			asym  - whether the network is asymmetric (directed), considered only for the non-standard network file extensions
			netshf  - whether this network is a shuffle in the non-flat dir structure
			pathid  - path id of the net to distinguish nets with the same name located in different dirs

			return
				jobsnum  - the number of scheduled jobs, typically 1
			"""
			jobsnum = 0
			netext = os.path.splitext(net)[1].lower()
			for eapp in evalapps:
				try:
					jobsnum += eapp(execpool, qualsaver, net, asym=asymnet(netext, asym), odir=netshf, timeout=timeout, pathids=pathids, seed=seed)
				except Exception as err:
					errexectime = time.time() - exectime
					print('WARNING, the "{}" is interrupted by the exception: {} with the callstack: {} on {:.4f} sec ({} h {} m {:.4f} s)'
						.format(eapp.__name__, err, traceback.format_exc(), errexectime, *secondsToHms(errexectime)), file=sys.stderr)
			# Note: jobs are executed asynchronously, so here none of them is completed
			#_STORAGE_FILE.flush()  # Write results to the persistent storage
			return jobsnum

		def runeval(net, netshf, xargs):  # TODO: default ext
			"""Clustering evaluation runner

			net  - network file name
			netshf  - whether this network is a shuffle in the non-flat dir structure
			xargs  - extra custom parameters
			"""
			tnum = evalquality(xargs['execpool'], xargs['evaluators'], net, xargs['asym'], netshf, pathids)
			xargs['jobsnum'] += tnum
			xargs['netcount'] += tnum != 0

		def dflclsext(asym=None):
			"""Get default file extension for the resulting clustering

			asym  - whether the input network is asymmetric (directed) or symmetric (undirected)

			return  - respective extension of the network file having leading '.'
			"""
			return '.cnl'

		xargs = {'execpool': None,  # Execution pool to schedule evaluators
				 'evaluators': None,  # Evaluating functions
				 'asym': False,  # Asymmetric network, required for the intrinsic measures
				 'pathidstr': '',  # Id of the dublicated path shortcut to have the unique shortcut
				 'jobsnum': 0,  # Number of the processed network jobs (can be several per each instance if shuffles exist)
				 'netcount': 0}  # Number of converted network instances (includes multiple shuffles)

		# ATTENTION: NMI ovp multiresolution should be ealuated in the dedicated mode requiring multiple CPU cores,
		# so it will be scheduled separately after other measures
		# Note: afnstep = 1 to maximize parallelization the same time binding single-treaded apps to the logical CPUs (hardware threads)
		with ExecPool(_WPROCSMAX, afnmask=AffinityMask(1), memlimit=_VMLIMIT, name='qualityst') as _execpool:
			xargs['execpool'] = _execpool
			xargs['evaluators'] = evaluators(quality & 0xFFFC)  # Skip gecmi (Multiresolution Overlapping NMI) because it requires special scheduling
			print('  Scheduling quality evaluation for the evaluators: ', ', '.join(
				[funcToAppName(func.__name__) for func in xargs['evaluators']]))
			# Load pathid mapping (nameid: fullpath)
			pathids = {}
			if os.path.isfile(_PATHIDFILE):
				with open(_PATHIDFILE) as fpais:
					for ln in fpais:
						# Skip comments
						if not ln or ln[0] == '#':
							continue
						fnamex, path = ln.split(None, 1)  # Filename extended with id, full path to the input file
						pathids[fnamex] = path
				if pathids:
					print('Pathid mapping loaded: {} items'.format(len(pathids)))
			else:
				print('WARNING, pathid mapping does not exist', file=sys.stderr)

			# Track processed file names to resolve cases when files with the same name present in different input dirs
			# Note: pathids are required at least to set concise job names to see what is executed in runtime
			netnames = {}  # Name to pathid mapping: {Name: counter}
			for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
				xargs['asym'] = popt.asym
				# Resolve wildcards
				pcuropt = copy.copy(popt)  # Path options for the resolved wildcard
				for path in glob.iglob(popt.path):  # Allow wildcards
					# Form non-empty pathid string for the duplicated file names
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
						nameid = _SEPPATHID + str(pathid)
						xargs['pathidstr'] = nameid
						# Validate loaded pathids mapping
						if pathids.get(nameid) != mpath:
							raise ValueError('ERROR, "{}" mapping validation failed.'
								' Can not find correspondence of the ground truth files to the evaluating clusterings.')
					pcuropt.path = path
					if _DEBUG_TRACE:
						print('  Scheduling quality evaluation for the path options ({})'.format(str(pcuropt)))
					processPath(pcuropt, runeval, xargs=xargs, dflextfn=dflclsext)
			netnames.clear()
			pathids = None  # Release loaded pathid mapping
			if evaltimeout <= 0:
				evaltimeout = timeout * xargs['jobsnum']
			timelim = min(timeout * xargs['jobsnum'], evaltimeout)
			print('Waiting for the quality evaluation on {} jobs from {} networks'
				' with {} sec ({} h {} m {:.4f} s) timeout ...'
				.format(xargs['jobsnum'], xargs['netcount'], timelim, *secondsToHms(timelim)))
			try:
				_execpool.join(timelim)
			except BaseException as err:  # Consider also system iteruptions not captured by the Exception
				print('ERROR{}, quality evaluation execution pool is interrupted by: {}. {}'
					.format('' if not _execpool.name else ' ' + _execpool.name
					, err, traceback.format_exc()), file=sys.stderr)
				raise

		# Schedule NMI multiresolution overlapping evalautions (gecmi) either on the whole NUMA node or
		# on the whole server because gecmi is multi-threaded app with huge number of threads
		# Reuse execpool
		_execpool.name = 'qualitymt'
		_execpool.alive = True
		_execpool.afnmask = AffinityMask(AffinityMask.NODE_CPUS)
		with _execpool:
			xargs['execpool'] = _execpool
			xargs['evaluators'] = evaluators(quality & 0b11)  # Skip gecmi (Multiresolution Overlapping NMI) because it requires special scheduling
			print('  Scheduling quality evaluation for the evaluators: ', ', '.join(
				[funcToAppName(func.__name__) for func in xargs['evaluators']]))

			# Track processed file names to resolve cases when files with the same name present in different input dirs
			# Note: pathids are required at least to set concise job names to see what is executed in runtime
			for popt in datas:  # (path, flat=False, asym=False, shfnum=0)
				xargs['asym'] = popt.asym
				# Resolve wildcards
				pcuropt = copy.copy(popt)  # Path options for the resolved wildcard
				for path in glob.iglob(popt.path):  # Allow wildcards
					# Form non-empty pathid string for the duplicated file names
					if os.path.isdir(path):
						# ATTENTION: required to process directories ending with '/' correctly
						# Note: normpath() may change semantics in case symbolic link is used with parent dir:
						# base/linkdir/../a -> base/a, which might be undesirable
						net = path.rstrip('/')  # os.path.normpath(path)
					else:
						net = os.path.splitext(path)[0]
					net = os.path.split(net)[1]
					pathid = netnames.get(net)
					if pathid is None:
						netnames[net] = 0
						xargs['pathidstr'] = ''
					else:
						pathid += 1
						netnames[net] = pathid
						nameid = _SEPPATHID + str(pathid)
						xargs['pathidstr'] = nameid
					pcuropt.path = path
					if _DEBUG_TRACE:
						print('  Scheduling quality evaluation for the path options ({})'.format(str(pcuropt)))
					processPath(pcuropt, runeval, xargs=xargs, dflextfn=dflclsext)
			netnames = None

			# Extend quality evaluation tracing files (.rcp) with time tracing to distinguish different executions (benchmark runs)
			evaluator.mark(algorithms, seed)

			for alg in algorithms:
				aexecres = ''.join((_RESDIR, alg, '/', measure, _EXTEXECTIME))
				with open(aexecres, 'a') as faexres:
					faexres.write('# --- {time} (seed: {seed}) ---\n'.format(time=_TIMESTAMP_START_STR, seed=seed))  # Write timestamp

			if runtimeout <= 0:
				runtimeout = timeout * xargs['jobsnum']
			timelim = min(timeout * xargs['jobsnum'], runtimeout)
			elapsed = time.time() - stime  # Elapsed time
			timelim -= elapsed
			if timelim > 0:
				print('Waiting for the quality evaluation on {} jobs from {} networks'
					' with {} sec ({} h {} m {:.4f} s) timeout ...'
					.format(xargs['jobsnum'], xargs['netcount'], timelim, *secondsToHms(timelim)))
				try:
					_execpool.join(timelim)
				except BaseException as err:  # Consider also system iteruptions not captured by the Exception
					print('ERROR{}, quality evaluation execution pool is interrupted by: {}. {}'
						.format('' if not _execpool.name else ' ' + _execpool.name
						, err, traceback.format_exc()), file=sys.stderr)
					raise
			else:
				print('WARNING {}, the execution pool is terminated by timeout of {} sec,'
					', executed {} sec ({} h {} m {:.4f} s)'.format(
					'' if not _execpool.name else ' ' + _execpool.name
					, timelim + elapsed, elapsed, *secondsToHms(elapsed), file=sys.stderr))
		# _execpool = None
		# stime = time.time() - stime
		# print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
		# 	.format(stime, *secondsToHms(stime)))
		# print('Aggregating execution statistics...')
		# aggexec(algorithms)
		# print('Execution statistics aggregated')





			# def evaluate(measure, basefile, asym, jobsnum, pathid=''):
			# 	"""Evaluate algorithms on the specified network
			#
			# 	measure  - target measure to be evaluated: {nmi, mod}
			# 	basefile  - ground truth result, or initial network file or another measure-related file
			# 	asym  - network links weights are asymmetric (in/outbound weights can be different)
			# 	jobsnum  - accumulated number of scheduled jobs
			# 	pathid  - path id of the basefile to distinguish files with the same name located in different dirs
			# 		Note: pathid includes pathid separator
			#
			# 	return
			# 		jobsnum  - updated accumulated number of scheduled jobs
			# 	"""
			# 	assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'
			#
			# 	for algname in evalalgs:
			# 		try:
			# 			evalAlgorithm(_execpool, algname, basefile, measure, timeout, evagg, pathid)
			# 			## Evaluate also nmi_s besides nmi if required
			# 			if quality & im == 3:
			# 			#if measure == 'nmi':
			# 				evalAlgorithm(_execpool, algname, basefile, 'nmi_s', timeout, evagg_s, pathid)
			# 		except Exception as err:
			# 			print('WARNING, "{}" evaluation of "{}" is interrupted by the exception: {}. {}'
			# 				.format(measure, algname, err, traceback.format_exc()), file=sys.stderr)
			# 		else:
			# 			jobsnum += 1
			# 	return jobsnum
			#
			# # Measures is a dict with the Array values: <evalcallback_prefix>, <grounttruthnet_extension>, <measure_name>
			# measures = {3: ['nmi', _EXTCLNODES, 'NMIs'], 4: ['mod', '.hig', 'Q']}
			# evaggs = []  # Evaluation results aggregators
			# for im, msr in viewitems(measures):  # Note: the number of measures is small
			# 	# Evaluate only required measures
			# 	if quality & im == 0:
			# 		continue
			# 	if im == 3:
			# 		# Exclude NMI if it is aplied, but quality & 1 == 0
			# 		if quality & 1 == 0:
			# 			msr[0] = 'nmi_s'
			# 			msr[2] = 'NMI_s'
			# 		elif quality & 2 == 0:
			# 			msr[2] = 'NMI'
			# 		else:
			# 			evagg_s = EvalsAgg('nmi_s')  # Reserve also second results aggregator for nmi_s
			# 			evaggs.append(evagg_s)
			# 	evagg = EvalsAgg(msr[0])  # Evaluation results aggregator
			# 	evaggs.append(evagg)
			#
			# 	if not algorithms:
			# 		# Fetch available algorithms
			# 		evalalgs = appnames(appsmodule)
			# 	else:
			# 		evalalgs = [alg for alg in algorithms]  # .lower()
			# 	evalalgs = tuple(evalalgs)
			#
			# print('Starting {} evaluation...'.format(msr[2]))
			# jobsnum = 0
			# measure = msr[0]
			# fileext = msr[1]  # Initial networks in .hig formatare required for mod, clusters for NMIs
			# # Track processed file names to resolve cases when files with the same name present in different input dirs
			# filenames = set()
			# for pathid, (asym, ddir) in enumerate(datadirs):
			# 	pathid = _SEPPATHID + str(pathid)
			# 	# Read ground truth
			# 	for basefile in glob.iglob('*'.join((ddir, fileext))):  # Allow wildcards in the names
			# 		netname = os.path.split(basefile)[1]
			# 		ambiguous = False  # Net name is unambigues even without the dir
			# 		if netname not in filenames:
			# 			filenames.add(netname)
			# 		else:
			# 			ambiguous = True
			# 		evaluate(measure, basefile, asym, jobsnum, pathid if ambiguous else '')
			# for pathid, (asym, basefile) in enumerate(datafiles):
			# 	#pathid = ''.join((_SEPPATHID, _PATHID_FILE, str(pathid)))
			# 	pathid = ''.join((_SEPPATHID, str(pathid)))
			# 	# Use files with required extension
			# 	basefile = os.path.splitext(basefile)[0] + fileext
			# 	netname = os.path.split(basefile)[1]
			# 	ambiguous = False  # Net name is unambigues even without the dir
			# 	if netname not in filenames:
			# 		filenames.add(netname)
			# 	else:
			# 		ambiguous = True
			# 	evaluate(basefile, asym, jobsnum, pathid if ambiguous else '')
			# print('{} evaluation is scheduled'.format(msr[2]))
			# filenames = None  # Free memory from filenames
			#
			# if evaltimeout <= 0:
			# 	evaltimeout = timeout * jobsnum
			# timelim = min(timeout * jobsnum, evaltimeout)  # Global timeout, up to N days
			# print('Waiting for the evaluations execution on {} jobs'
			# 	' with {} sec ({} h {} m {:.4f} s) timeout ...'
			# 	.format(jobsnum, timelim, *secondsToHms(timelim)))
			# try:
			# 	_execpool.join(timelim)  # max(timelim, exectime * 2) - Twice the time of the algorithms execution
			# except BaseException as err:  # Consider also system iteruptions not captured by the Exception
			# 	print('ERROR, Results evaluation execution pool is interrupted by: {}. {}'
			# 		.format(err, traceback.format_exc()), file=sys.stderr)
			# 	raise

	qualsaver.storage.close()
	_execpool = None  # Reset global execpool
	stime = time.time() - stime
	print('Results evaluation is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(stime, *secondsToHms(stime)))
	# Aggregate results and output
	stime = time.time()
	print('Starting processing of aggregated results ...')
	#for evagg in evaggs:
	#	evagg.aggregate()
	stime = time.time() - stime
	print('Processing of aggregated results completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(stime, *secondsToHms(stime)))


def benchmark(*args):
	"""Execute the benchmark

	Run the algorithms on the specified datasets respecting the parameters.
	"""
	exectime = time.time()  # Benchmarking start time

	opts = parseParams(args)
	print('The benchmark is started, parsed params:\n\tsyntpo: "{}"\n\tconvnets: 0b{:b}'
		'\n\trunalgs: {}\n\tquality: 0b{:b}\n\tupdqual: {}\n\tdatas: {}\n\talgorithms: {}'
		'\n\taggrespaths: {}\n\ttimeout: {} h {} m {:.4f} sec'
		.format(opts.syntpo, opts.convnets, opts.runalgs, opts.quality, opts.updqual
			, '; '.join([str(pathopts) for pathopts in opts.datas])  # Note: ';' because internal separator is ','
			, ', '.join(opts.algorithms) if opts.algorithms else ''
			, ', '.join(opts.aggrespaths) if opts.aggrespaths else '', *secondsToHms(opts.timeout)))
	# Benchmark app can be called from the remote directory
	bmname = 'lfrbench_udwov'  # Benchmark name for the synthetic networks generation
	assert _UTILDIR.endswith('/'), 'A directory should have a valid terminator'
	benchpath = _UTILDIR + bmname  # Benchmark path

	# Create the global seed file if not exists
	if not os.path.exists(opts.seedfile):
		# Consider inexisting base path of the common seed file
		sfbase = os.path.split(opts.seedfile)[0]
		if sfbase and not os.path.exists(sfbase):
			os.makedirs(sfbase)
		seed = timeSeed()
		with open(opts.seedfile, 'w') as fseed:
			fseed.write('{}\n'.format(seed))
	else:
		with open(opts.seedfile) as fseed:
			seed = int(fseed.readline())

	# Generate parameters for the synthetic networs and the networks instances if required
	if opts.syntpo and opts.syntpo.netins >= 1:
		# Note: on overwirte old instances are rewritten and shulles are deleted making the backup
		generateNets(genbin=benchpath, insnum=opts.syntpo.netins, asym=opts.syntpo.asym
			, basedir=opts.syntpo.path, netsdir=_NETSDIR, overwrite=opts.syntpo.overwrite
			, seedfile=opts.seedfile, gentimeout=3*60*60)  # 3 hours

	# Update opts.datasets with sythetic generated data: all subdirs of the synthetic networks dir
	# Note: should be done only after the genertion, because new directories can be created
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
		convertNets(opts.datas, overwrite=opts.convnets&0b11 == 0b11
			, resdub=opts.convnets&0b100, timeout1=7*60, convtimeout=45*60)

	# Run the opts.algorithms and measure their resource consumption
	if opts.runalgs:
		runApps(appsmodule=benchapps, algorithms=opts.algorithms, datas=opts.datas, seed=seed
			, exectime=exectime, timeout=opts.timeout, runtimeout=10*24*60*60)  # 10 days

	# Evaluate results
	if opts.quality:
		evalResults(quality=opts.quality, appsmodule=benchapps, algorithms=opts.algorithms
			, datas=opts.datas, seed=seed, exectime=exectime, timeout=opts.timeout
			, evaltimeout=14*24*60*60, update=opts.updqual)  # 14 days

	if opts.aggrespaths:
		aggEvaluations(opts.aggrespaths)

	exectime = time.time() - exectime
	print('The benchmark completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(exectime, *secondsToHms(exectime)))


_signals = {}  # Signals mapping


def terminationHandler(signal=None, frame=None, terminate=True):
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
		del _execpool  # Destructors are caled later
		# Define _execpool to avoid unnessary trash in the error log, which might
		# be caused by the attempt of subsequent deletion on destruction
		_execpool = None  # Note: otherwise _execpool becomes undefined
	if terminate:
		sys.exit()  # exit(0), 0 is the default exit code.


if __name__ == '__main__':
	if len(sys.argv) <= 1 or (len(sys.argv) == 2 and sys.argv[1] in ('-h', '--help')):
		apps = appnames(benchapps)
		print('\n'.join(('Usage:',
			'  {0} [-g[o][a]=[<number>][{gensepshuf}<shuffles_number>][=<outpdir>]'
			' [-i[f][a][{gensepshuf}<shuffles_number>]=<datasets_{{dir,file}}_wildcard>'
			' [-c[f][r]] [-a=[-]"app1 app2 ..."] [-r] [-q[e[{{n[x],o[x],f[{{h,p}}],d}}][i[{{m,c}}]]]'
			' [-s=<eval_path>] [-t[{{s,m,h}}]=<timeout>] [-d=<seed_file>] [--stderr-stamp] | -h',
			'',
			'Example:',
			'  {0} -g=3.5 -r -q -th=2.5 1> {resdir}bench.log 2> {resdir}bench.err',
			'NOTE:',
			'  - The benchmark should be executed exclusively from the current directory (./)',
			'  - The expected format of input datasets (networks) is .ns<l> - network specified by'
			' <links> (arcs / edges), a generalization of the .snap, .ncol and Edge/Arcs Graph formats.',
			'  - paths can contain wildcards: *, ?, +',
			'  - multiple paths can be specified via multiple -i, -s options (one per the item)',
			'',
			'Parameters:',
			'  --help, -h  - show this usage description',
			'  --generate, -g[o][a]=[<number>][{gensepshuf}<shuffles_number>][=<outpdir>]  - generate <number> synthetic datasets'
			' of the required format in the <outpdir> (default: {syntdir}), shuffling (randomly reordering network links'
			' and saving under another name) each dataset <shuffles_number> times (default: 0).'
			' If <number> is omitted or set to 0 then ONLY shuffling of <outpdir>/{netsdir}/* is performed.'
			' The generated networks are automatically added to the begin of the input datasets.',
			'    o  - overwrite existing network instances (old data is backuped) instead of skipping generation',
			'    a  - generate networks specifined by arcs (directed) instead of edges (undirected)',
			'NOTE: shuffled datasets have the following naming format:',
			'\t<base_name>[(seppars)<param1>...][{sepinst}<instance_index>][{sepshf}<shuffle_index>].<net_extension>',
			'  --input, -i[X][{gensepshuf}<shuffles_number>]=<datasets_dir>  - input dataset(s), wildcards of files or directories'
			', which are shuffled <shuffles_number> times. Directories should contain datasets of the respective extension (.ns{{e,a}}).'
			' Default: -ie={syntdir}{netsdir}*/, which are subdirs of the synthetic networks dir without shuffling.',
			'    f  - make flat derivatives on shuffling instead of generating the dedicted directory (havng the file base name)'
			' for each input network, might cause flooding of the base directory. Existed shuffles are backuped.',
			'    NOTE: variance over the shuffles of each network instance is evaluated only for the non-flat structure.',
			'    a  - the dataset is specified by arcs (asymmetric, directed links) instead of edges (undirected links)'
			', considered only for not .ns{{a,e}} extensions.',
			'NOTE:',
			'  - The following symbols in the path name have specific semantic and processed respectively: {rsvpathsmb}',
			'  - Paths may contain wildcards: *, ?, +',
			'  - Multiple directories and files wildcards can be specified via multiple -i options',
			'  - Shuffles backup and OVERWRITE previously excisting shuffles',
			'  - Datasets should have the .ns<l> format: <node_src> <node_dest> [<weight>]',
			'  - Ambiguity of links weight resolution in case of duplicates (or edges specified in both directions)'
			' is up to the clustering algorithm',
			'  --apps, -a[=[-]"app1 app2 ..."]  - apps (clustering algorithms) to be applied, default: all.',
			'Leading "-" means applying of all except the specified apps. Available apps ({anppsnum}): {apps}.',
			'Impacts {{r, q}} options. Optional, all registered apps (see benchapps.py) are executed by default.',
			'NOTE: output results are stored in the "{resdir}<algname>/" directory',
			#'    f  - force execution even when the results already exists (existent datasets are moved to backup)',
			'  --runapps, -r  - run specified apps on the specidied datasets, default: all',
			'  --quality, -q[X]  - evaluate quality (including accuracy) of the results for the specified algorithms'
			' on the specified datasets and form the summarized results. Default: NMI_max, F1h and F1p measures on all datasets',
			#  -q[X][="<SEP><inpnet_pyregex><SEP><gtnet_pyregex>[<SEP><pyregex_glags>]"]
			#  ";(?<=.)nse$;ncl;i", see details in https://docs.python.org/2/library/re.html
			#'    f  - force execution even when the results already exists (existent datasets are moved to backup)',
			'    e[Y]  - extrinsic measures for overlapping communities, default: all',
			'      n[Z]  - NMI measure(s) for overlapping and multi-level communities: max, avg, min, sqrt',
			'        x  - NMI_max,',
			'      NOTE: unified NMI evaluaiton is stochastic and does not provide the seed parameter.',
			#'        a  - NMI_avg (also known as NMI_sum),',
			#'        n  - NMI_min,',
			#'        r  - NMI_sqrt',
			'      o[Z]  - overlapping NMI measure(s) for overlapping communities'
			' that are not multi-level: max, sum, lfk. Note: it is much faster than generalized NMI',
			'        x  - NMI_max',
			'      f[Z]  - avg F1-Score(s) for overlapping and multi-level communities: avg, hmean, pprob',
			#'        a  - avg F1-Score',
			'        h  - harmonic mean of F1-Score',
			'        p  - F1p measure (harmonic mean of the weighted average of partial probabilities)',
			'      r  - recommended extrinsic measures (NMI_max, F1_h, F1_p) for overlapping multi-level communities',
			'    i[Y]  - intrinsic measures for overlapping communities, default: all',
			'      m  - modularity Q',
			'      c  - conductance f',
			'    u  - update quality evaluations storage rewriting existed values instead of creating a new storage.'
			' Allowed only for the same seed. The existed quality evaluations are backed up anyway.',
			'NOTE: multiple quality evaluaiton options can be specified via the multiple -q opitons',
			'  --timeout, -t[X]=<float_number>  - specifies timeout for each benchmarking application per single evaluation on each network'
			' in sec, min or hours; 0 sec - no timeout, default: {th} h {tm} min {ts} sec',
			'    s  - time in seconds, default option',
			'    m  - time in minutes',
			'    h  - time in hours',
			'  --seedfile, -d=<seed_file>  - seed file to be used/created for the synthetic networks generation and stochastic algorithms'
			', contains uint64_t value. Default: {seedfile}',
			'NOTE: the seed file is not used in the shuffling, so the shuffles are distinct for the same seed',
			'',
			'Advanced parameters:',
			'  --stderr-stamp  - output a time stamp to the stderr on the benchmarking start to separate multiple reexectuions',
			'  --convret, -c[X]  - convert input networks into the required formats (app-specific formats: .rcg[.hig], .lig, etc.)',
			'    f  - force the conversion even when the data is already exist',
			'    r  - resolve (remove) duplicated links on conversion (recommended to be used)',
			'  --summary, -s=<resval_path>  - aggregate and summarize specified evaluations extending the benchmarking results'
			', which is useful to include external manual evaluations into the final summarized results',
			'ATTENTION: <resval_path>  should include the algorithm name and target measure'
			)).format(sys.argv[0], gensepshuf=_GENSEPSHF, resdir=_RESDIR, syntdir=_SYNTDIR, netsdir=_NETSDIR
				, sepinst=_SEPINST, seppars=_SEPPARS, sepshf=_SEPSHF, rsvpathsmb=(_SEPPARS, _SEPINST, _SEPSHF, _SEPPATHID)
				, anppsnum=len(apps), apps=', '.join(apps), th=_TIMEOUT//3600, tm=_TIMEOUT//60%60, ts=_TIMEOUT%60, seedfile=_SEEDFILE))
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

		# Set termination handler for the internal termination
		atexit.register(terminationHandler, terminate=False)

		benchmark(*sys.argv[1:])


# Extrenal API (exporting functions)
__all__ = [generateNets, shuffleNets, convertNets, runApps, evalResults, benchmark]
