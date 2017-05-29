#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
\descr: A modular benchmark, wich optionally generates and preprocesses (shuffles,
	i.e. reorder nodes in the networks) datasets using specified executable,
	optionally executes specified applications (clustering algorithms) with
	specified parameters on the specified datasets,	and optionally evaluates
	results of the execution using specified executable(s).

	All executions are traced and logged also as resources consumption:
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
import atexit  # At exit termination handleing
import sys
import time
import subprocess
from multiprocessing import cpu_count  # Returns the number of multi-core CPU units if exist, otherwise the number of cores
import os
import shutil
import signal  # Intercept kill signals
from math import sqrt
import glob
from datetime import datetime
import traceback  # Stacktrace

import benchapps  # Benchmarking apps (clustering algs)

from utils.mpepool import *
from benchutils import *

from benchutils import _SEPPARS
from benchutils import _SEPSHF
from benchutils import _SEPINST
from benchutils import _SEPPATHID

from benchapps import PYEXEC
from benchapps import aggexec
from benchapps import _EXTCLNODES

from benchevals import evalAlgorithm
from benchevals import aggEvaluations
from benchevals import EvalsAgg
from benchevals import _RESDIR
from benchevals import _EXTEXECTIME


# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_UTILDIR = 'utils/'  # Utilities directory
_SYNTDIR = 'syntnets/'  # Default base directory for the synthetic datasets (both networks, params and seeds)
_NETSDIR = 'networks/'  # Networks sub-directory of the synthetic networks (inside _SYNTDIR)
assert _RESDIR.endswith('/'), 'A directory should have a valid terminator'
_SEEDFILE = _RESDIR + 'seed.txt'
_SYNTINUM = 3  # Default number of instances of each synthetic network, >= 1
_TIMEOUT = 36 * 60*60  # Default execution timeout for each algorithm for a single network instance
_EXTNETFILE = '.nse'  # Extension of the network files to be executed by the algorithms; Network specified by tab/space separated edges (.nsa - arcs)
#_algseeds = 9  # TODO: Implement
#_EVALDFL = 'd'  # Default evaluation measures: d - default extrinsic eval measures (NMI_max, F1h, F1p)
_PREFEXEC = 'exec'  # Execution prefix for the apps functions in benchapps
_WPROCSMIN = 1  # Minimal number of the worker processes, maximal number is cpu_num-1 or core_num-1 for the single CPU with multiple cores

_execpool = None  # Pool of executors to process jobs

_TRACE = 2  # Tracing level: 0 - none, 1 - lightweight, 2 - debug, 3 - detailed


def asymnet(netext):
	"""Whether the network is asymmetric (directed, specified by arcs rather than edges)

	netext  - network extension (starts with '.'): .nse or .nsa

	return  - the networks is asymmetric (specified by arcs)
	"""
	assert netext in ('.nse', '.nsa'), 'Unknown network extension'
	return netext == '.nsa'


# Data structures --------------------------------------------------------------
class PathOpts(object):
	"""Input parameters"""
	def __init__(self, path, flat=False, asym=False):
		"""Sets default values for the input parameters

		path  - path (directory or file), a wildcard is allowed
		flat  - use flat derivatives or create the dedicated directory on shuffling
			to avoid flooding of the base directory
		asym  - the network is asymmetric (specified by arcs rather than edges)
		"""
		self.path = path
		self.flat = flat
		self.asym = asym


class Params(object):
	"""Input parameters"""
	def __init__(self):
		"""Sets default values for the input parameters

		gensynt  - generate synthetic networks:
			0 - do not generate
			1 - generate only if the network is not exist
			2 - force geration (overwrite all)
		netins  - number of network instances for each network type to be generated, >= 1
		shufnum  - number of shuffles of each network instance to be produced, >= 0
		syntdir  - base directory for synthetic datasets
		convnets  - convert existing networks into the .hig format
			0 - do not convert
			0b001  - convert:
				0b01 - convert only if this network is not exist
				0b11 - force conversion (overwrite all)
			0b100 - resolve duplicated links on conversion
		runalgs  - execute algorithm or not
		evalres  - resulting measures to be evaluated:
			Note: all the employed measures are applicable for overlapping clusters
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
		datas: PathOpts  - list of datasets to be run with asym flag (asymmetric / symmetric links weights):
			[PathOpts, ...] , where path is either dir or file [wildcard]
		netext  - network file extension, should have the leading '.'
		timeout  - execution timeout in sec per each algorithm
		algorithms  - algorithms to be executed (just names as in the code)
		aggrespaths = paths for the evaluated resutls aggregation (to be done for already existent evaluations)
		seedfile  - seed file name
		"""
		self.gensynt = 0
		self.netins = _SYNTINUM  # Number of network instances to generate, >= 1
		assert self.netins >= 1, 'The number of network instances to generate should be positive'
		self.shufnum = 0  # Number of shuffles for each network instance to be produced, >=0
		self.syntdir = _SYNTDIR  # Base directory for synthetic datasets
		self.convnets = 0
		self.runalgs = False
		self.evalres = 0  # 1 - NMI, 2 - NMI_s, 4 - Q, 7 - all measures
		self.datas = []  # Input datasets, list of triples: [PathOpts, ...], where path is either dir or file
		self.netext = _EXTNETFILE  # Network file extension (.nse)
		assert self.netext and self.netext[0] == '.', 'A file extension should have the leading "."'
		self.timeout = _TIMEOUT
		self.algorithms = []
		self.aggrespaths = []  # Paths for the evaluated resutls aggregation (to be done for already existent evaluations)
		self.seedfile = _SEEDFILE  # Seed value for the synthetic networks generation and stochastic algorithms, integer


# Input зarameters processing --------------------------------------------------
def parseParams(args):
	"""Parse user-specified parameters

	return params
	"""
	assert isinstance(args, (tuple, list)) and args, 'Input arguments must be specified'
	opts = Params()

	timemul = 1  # Time multiplier, sec by default
	for arg in args:
		# Validate input format
		if arg[0] != '-':
			raise ValueError('Unexpected argument: ' + arg)

		if arg[1] == 'g':
			opts.gensynt = 1  # Generate if not exists
			alen = len(arg)
			if alen == 2:
				continue
			pos = arg.find('=', 2)
			if arg[2] not in 'f=' or alen == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			if arg[2] == 'f':
				opts.gensynt = 2  # Forced generation (overwrite)
			if pos != -1:
				# Parse number of instances, shuffles and outpdir:  [<instances>][.<shuffles>][=<outpdir>]
				val = arg[pos+1:].split('=', 1)
				if val[0]:
					# Parse number of instances
					nums = val[0].split('.', 1)
					# Now [instances][shuffles][outpdir]
					if nums[0]:
						opts.netins = int(nums[0])
					else:
						opts.netins = 0  # Zero if omitted in case of shuffles are specified
					# Parse shuffles
					if len(nums) > 1:
						opts.shufnum = int(nums[1])
					if opts.netins < 0 or opts.shufnum < 0:
						raise ValueError('Value is out of range:  opts.netins: {netins} >= 1, opts.shufnum: {shufnum} >= 0'
							.format(netins=opts.netins, shufnum=opts.shufnum))
				# Parse outpdir
				if len(val) > 1:
					if not val[1]:  # arg ended with '=' symbol
						raise ValueError('Unexpected argument: ' + arg)
					opts.syntdir = val[1]
					opts.syntdir = opts.syntdir.strip('"\'')
					if not opts.syntdir.endswith('/'):
						opts.syntdir += '/'
		elif arg[1] == 'a':
			if not (arg[:3] == '-a=' and len(arg) >= 4):
				raise ValueError('Unexpected argument: ' + arg)
			opts.algorithms = arg[3:].strip('"\'').split()  # Note: argparse automatically performs this escaping
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
		elif arg[1] == 'r':
			if arg != '-r':
				raise ValueError('Unexpected argument: ' + arg)
			opts.runalgs = True
		elif arg[1] == 'e':
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
			evalres = 0  # Evaluation results bitmask
			pos = 2
			if len(arg) == pos:
				evalres = 0xFFF  # All extrinsic and intrinsic measures
			elif arg[pos] == 'e':
				pos += 1
				if len(arg) == pos:
					evalres |= 0xFF  # All extrinsic measures
				elif arg[pos] == 'n':
					pos += 1
					if len(arg) == pos:
						evalres |= 0b11  # All NMIs
					elif arg[pos] == 'x':
						evalres |= 0b01  # NMI_max
				elif arg[pos] == 'o':
					pos += 1
					if len(arg) == pos:
						evalres |= 0b1100  # All ONMIs
					elif arg[pos] == 'x':
						evalres |= 0b0100  # ONMI_max
				elif arg[pos] == 'f':
					pos += 1
					if len(arg) == pos:
						evalres |= 0b1110000  # All F1s
					elif arg[pos] == 'h':
						evalres |= 0b0010000  # F1h
					elif arg[pos] == 'p':
						evalres |= 0b0100000  # F1p
				elif arg[pos] == 'd':  # Default extrinsic measures
					evalres |= 0b0110001  # NMI_max, F1h, F1p
			elif arg[pos] == 'i':
				pos += 1
				if len(arg) == pos:
					evalres |= 0xF00  # All intrinsic measures
				elif arg[pos] == 'm':
					evalres |= 0x100  # Modularity
				elif arg[pos] == 'c':
					evalres |= 0x200  # Conductance

			if evalres:
				opts.evalres |= evalres
			else:
				raise ValueError('Unexpected argument: ' + arg)
		elif arg[1] == 'i':  # arg[1] == 'd' or arg[1] == 'f'
			pos = arg.find('=', 2)
			if pos == -1 or arg[2] not in 'gas=' or len(arg) == pos + 1:
				raise ValueError('Unexpected argument: ' + arg)
			# Extend weighted / unweighted opts.dataset, default is unweighted
			val = arg[2]
			flat = False  # Use flat derivatives or generate the dedicated dir for the derivatives of this network(s)
			if val == 'f':
				flat = True
				val = arg[3]
			asym = asymnet(_EXTNETFILE)  # Asym: None - not specified (symmetric is assumed), False - symmetric, True - asymmetric
			if val == 'a':
				asym = True
			elif val == 'e':
				asym = False
			opts.datas.append(PathOpts(arg[pos+1:].strip('"\''), flat, asym))  # Remove quotes if exist
		elif arg[1] == 'x':
			if len(arg) <= 3 or arg[2] != '=':
				raise ValueError('Unexpected argument: ' + arg)
			opts.ext = arg[3:].strip('"\'')  # Remove quotes if exist
			if not opts.ext:
				raise ValueError('Unexpected argument: ' + arg)
			# Add leading '.' if required
			if opts.ext[0] != '.':
				opts.ext = '.' + opts.ext
		elif arg[1] == 'a':
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
		elif arg[1] == 's':
			if len(arg) <= 3 or arg[2] != '=':
				raise ValueError('Unexpected argument: ' + arg)
			opts.seedfile = arg[3:]
		else:
			raise ValueError('Unexpected argument: ' + arg)

	return opts


def prepareInput(datas, netext=_EXTNETFILE):
	"""Generating directories structure, linking there the original network, and shuffles
	for the input datasets according to the specidied parameters. The former dir is backuped.
	The wildcards are resolved.

	datas  - pathes with flags to be processed in the format: [PathOpts, ...]
	netext  - extension of the network files with the leading point

	return
		datadirs  - unique target dirs of networks to be processed (without wildcards)
		datafiles  - unique target files to be processed (without wildcards)
	"""
	datadirs = set()
	datafiles = set()

	if not datas:
		return datadirs, datafiles
	assert isinstance(datas[0], PathOpts), 'datas must be a container of PathOpts'
	assert netext and netext[0] == '.', 'file extension should have the leading point'

	def prepareDir(dirname, netfile, bcksuffix=None):
		"""Move specified dir to the backup if not empty. Make the dir if not exists.
		Link the origal network inside the dir.

		dirname  - dir to be moved
		netfile  - network file to be linked into the <dirname> dir
		bcksuffix  - backup suffix for the group of directories, formed automatically
			from the SyncValue()
		"""
		if os.path.exists(dirname) and not dirempty(dirname):
			backupPath(dirname, False, bcksuffix)
		if not os.path.exists(dirname):
			os.mkdir(dirname)
		# Make hard link to the network.
		# Hard link is used to have initial former copy in the archive even when the origin is changed
		os.link(netfile, '/'.join((dirname, os.path.split(netfile)[1])))

	for popt in datas:
		# Resolve wildcards
		for path in glob.iglob(popt.path):  # Allow wildcards
			if not popt.flat:
				bcksuffix = SyncValue()  # Use unified suffix for the backup of various network instances
			if os.path.isdir(path):
				# Use the same path separator on all OSs
				if not path.endswith('/'):
					path += '/'
				# Generate dirs if required
				if not popt.flat:
					# Traverse over the networks instances and create corresponding dirs
					for net in glob.iglob('*'.join((path, netext))):  # Allow wildcards
						# Backup existent dir
						dirname = os.path.splitext(net)[0]
						prepareDir(dirname, net, bcksuffix)
						# Update target dirs
						datadirs.add(dirname + '/')
				else:
					datadirs.add(path)
			else:
				# Generate dirs if required
				if not popt.flat:
					dirname = os.path.splitext(path)[0]
					prepareDir(dirname, path, bcksuffix)
					datafiles.add('/'.join((dirname, os.path.split(path)[1])))
				else:
					datafiles.add(path)
	return [p for p in datadirs], [p for p in datafiles]


# Networks processing ----------------------------------------------------------
def generateNets(genbin, basedir=_SYNTDIR, netsdir=_NETSDIR, netext=_EXTEXECTIME, overwrite=False, count=_SYNTINUM, seedfile=_SEEDFILE, gentimeout=2*60*60):  # 2 hours
	"""Generate synthetic networks with ground-truth communities and save generation params.
	Previously existed paths with the same name are backuped.

	genbin  - the binary used to generate the data (full path or relative to the base benchmark dir)
	basedir  - base directory where data will be generated
	netsdir  - relative directory for the synthetic networks, contains subdirs,
		each contains all instances of each network and all shuffles of each instance
	netext  - network file extension (should have the leading '.')
	overwrite  - whether to overwrite existing networks or use them
	count  - number of insances of each network to be generated, >= 1
	seedfile  - seed file name
	gentimeout  - timeout for all networks generation in parallel mode
	"""
	paramsdir = 'params/'  # Contains networks generation parameters per each network type
	seedsdir = 'seeds/'  # Contains network generation seeds per each network instance
	# Note: shuffles unlike ordinary networks have double extension: shuffling nimber and standard extension

	# Store all instances of each network with generation parameters in the dedicated directory
	assert count >= 1, 'Number of the network instances to be generated must be positive'
	assert ((basedir == '' or basedir[-1] == '/') and paramsdir[-1] == '/' and seedsdir[-1] == '/' and netsdir[-1] == '/'
		), 'Directory name must have valid terminator'
	assert netext and netext[0] == '.', 'A file extension should have the leading "."'

	paramsdirfull = basedir + paramsdir
	seedsdirfull = basedir + seedsdir
	netsdirfull = basedir + netsdir
	# Backup params dirs on rewriting
	if overwrite:
		bcksuffix = SyncValue()
		for dirname in (paramsdirfull, seedsdirfull, netsdirfull):
			if os.path.exists(dirname) and not dirempty(dirname):
				backupPath(dirname, False, bcksuffix)

	# Create dirs if required
	for dirname in (basedir, paramsdirfull, seedsdirfull, netsdirfull):
		if not os.path.exists(dirname):
			os.mkdir(dirname)  # Note: mkdir does not create intermediate (non-leaf) dirs

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
	#varNmul = (1, 5, 20, 50)  # *N0 - sizes of the generating networks in thousands of nodes;  Note: 100K on max degree works more than 30 min; 50K -> 15 min
	#vark = (5, 25, 75)  # Average node degree (density of the network links)
	varNmul = (1, 5)  # *N0 - sizes of the generating networks in thousands of nodes;  Note: 100K on max degree works more than 30 min; 50K -> 15 min
	vark = (5, 25)  # Average node degree (density of the network links)
	assert vark[-1] <= round(varNmul[0] * 1000 / rmaxK), 'Avg vs max degree validation failed'
	#varkr = (0.5, 1, 5)  #, 20)  # Average relative density of network links in percents of the number of nodes
	global _execpool

	if not _execpool:
		_execpool = ExecPool(max(cpu_count() - 1, _WPROCSMIN))
	netgenTimeout = 30 * 60  # 30 min per a network instance (50K nodes on K=75 takes ~15 min)
	#shuftimeout = 1 * 60  # 1 min per each shuffling
	bmname =  os.path.split(genbin)[1]  # Benchmark name
	genbin = os.path.relpath(genbin, basedir)  # Update path to the executable relative to the job workdir
	#bmbin = './' + bmname  # Benchmark binary
	randseed = basedir + 'lastseed.txt'  # Random seed file name

	# Copy benchmark seed to the syntnets seed
	if not os.path.isfile(seedfile):
		with open(seedfile, 'w') as fseed:
			fseed.write('{}\n'.format(timeSeed()))
	shutil.copy2(seedfile, randseed)

	asym = '-a' if asymnet(netext) else None  # Whether to generate directed (specified by arcs) or undirected (specified by edges) network
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
			# Recover the seed file is exists
			netseed = name.join((seedsdirfull, '.ngs'))
			if os.path.isfile(netseed):
				shutil.copy2(netseed, randseed)
				if _TRACE >= 2:
					print('The seed {netseed} is retained'.format(netseed=netseed))

			# Generate networks with ground truth corresponding to the parameters
			if os.path.isfile(fnamex):
				netpath = name.join((netsdir, '/'))  # syntnets/networks/<netname>/  netname.*
				netparams = name.join((paramsdir, ext))  # syntnets/params/<netname>.<ext>
				xtimebin = os.path.relpath(_UTILDIR + 'exectime', basedir)
				jobseed = os.path.relpath(netseed, basedir)
				# Generate required number of network instances
				if _execpool:
					netpathfull = basedir + netpath
					if not os.path.exists(netpathfull):
						os.mkdir(netpathfull)
					startdelay = 0.1  # Required to start execution of the LFR benchmark before copying the time_seed for the following process
					netfile = netpath + name
					if _TRACE >= 2:
						print('Generating {netfile} as {name} by {netparams}'.format(netfile=netfile, name=name, netparams=netparams))
					if count and overwrite or not os.path.exists(netfile.join((basedir, netext))):
						args = [xtimebin, '-n=' + name, ''.join(('-o=', bmname, _EXTEXECTIME))  # Output .rcp in the current dir, basedir
							, genbin, '-f', netparams, '-name', netfile, '-seed', jobseed]
						if asym:
							args.append(args)
						#Job(name, workdir, args, timeout=0, ontimeout=False, onstart=None, ondone=None, tstart=None)
						_execpool.execute(Job(name=name, workdir=basedir, args=args, timeout=netgenTimeout, ontimeout=True
							#, onstart=lambda job: shutil.copy2(randseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
							, onstart=lambda job: shutil.copy2(randseed, netseed)  # Network generation seed
							#, ondone=shuffle if shufnum > 0 else None
							, startdelay=startdelay))
					for i in range(1, count):
						namext = ''.join((name, _SEPINST, str(i)))
						netfile = netpath + namext
						if overwrite or not os.path.exists(netfile.join((basedir, netext))):
							args = [xtimebin, '-n=' + namext, ''.join(('-o=', bmname, _EXTEXECTIME))
								, genbin, '-f', netparams, '-name', netfile, '-seed', jobseed]
							if asym:
								args.append(args)
							#Job(name, workdir, args, timeout=0, ontimeout=False, onstart=None, ondone=None, tstart=None)
							_execpool.execute(Job(name=namext, workdir=basedir, args=args, timeout=netgenTimeout, ontimeout=True
								#, onstart=lambda job: shutil.copy2(randseed, job.name.join((seedsdirfull, '.ngs')))  # Network generation seed
								, onstart=lambda job: shutil.copy2(randseed, netseed)  # Network generation seed
								#, ondone=shuffle if shufnum > 0 else None
								, startdelay=startdelay))
			else:
				print('ERROR: network parameters file "{}" does not exist'.format(fnamex), file=sys.stderr)
	print('Parameter files generation is completed')
	if _execpool:
		_execpool.join(max(gentimeout, count * (netgenTimeout  #+ (shufnum * shuftimeout)  # Note: consider only the time required for the largest instances generation
			)))  # 2 hours vs inst_count * inst_timeout
		_execpool = None
	print('Synthetic networks files generation is completed')


def shuffleNets(datadirs, datafiles, shufnum, netext=_EXTNETFILE, overwrite=False, shuftimeout=30*60):  # 30 min
	"""Shuffle specified networks

	datadirs  - unique directories of the converting networks (without wildcards)
	datafiles  - unique files of the converting networks (without wildcards)
	shufnum  - number of shufflings for of each instance on the generated network, > 0
	netext  - network file extension (should have the leading '.')
	overwrite  - whether to renew existent shuffles (delete former and generate new).
		ATTENTION: Anyway redundant shuffles are deleted.
	shuftimeout  - global shuffling timeout
	"""
	# Note: backup is performe on paths extraction, see prepareInput()
	assert shufnum >= 1, 'Number of the network shuffles to be generated must be positive'
	assert netext and netext[0] == '.', 'A file extension should have the leading "."'
	global _execpool

	if not _execpool:
		_execpool = ExecPool(max(cpu_count() - 1, _WPROCSMIN))

	timeout = 5 * 60  # 5 min per each shuffling

	def shuffle(job):
		"""Shufle network specified by the job"""
		if shufnum < 1:
			return
		args = (PYEXEC, '-c',
# Shuffling procedure
"""import os
import subprocess

basenet = '{jobname}' + '{netext}'
#print('basenet: ' + basenet, file=sys.stderr)
for i in range(1, {shufnum} + 1):
	# sort -R pgp_udir.net -o pgp_udir_rand3.net
	netfile = ''.join(('{jobname}', '{sepshf}', str(i), '{netext}'))
	if {overwrite} or not os.path.exists(netfile):
		with open(basenet) as inpnet:
			ln = inpnet.readline()
			if ln.startswith('#'):
				# Shuffle considering the header
				# ('sort', '-R') or just ('shuf')
				wproc = subprocess.Popen(('shuf'), bufsize=-1, stdin=subprocess.PIPE, stdout=subprocess.PIPE)  # bufsize=-1 - use system default IO buffer size
				with open(netfile, 'w') as shfnet:
					hdr = True  # The file header is processed
					body = []  # File body
					while ln:
						# Write the header
						if hdr and ln.startswith('#'):
							shfnet.write(ln)
							ln = inpnet.readline()
							continue
						hdr = False
						body.append(ln)
						ln = inpnet.readline()
					body = wproc.communicate(''.join(body))[0]  # Fetch stdout (PIPE)
					shfnet.write(body)
			else:
				# The file does not have a header
				#subprocess.call(('sort', '-R', basenet, '-o', netfile))
				subprocess.call(('shuf', basenet, '-o', netfile))
""".format(jobname=job.name, sepshf=_SEPSHF, netext=netext, shufnum=shufnum
, overwrite=overwrite))
		_execpool.execute(Job(name=job.name + '_shf', workdir=job.workdir
			, args=args, timeout=timeout * shufnum))

	def shuffleNet(netfile):
		"""Shuffle specified network

		return
			shufnum - number of shufflings to be done
		"""
		# Remove existent shuffles if required
		path, name = os.path.split(netfile)
		name = os.path.splitext(name)[0]
		if name.find(_SEPSHF) != -1:
			shf = name.rsplit(_SEPSHF, 1)[1]
			# Omit shuffling of the shuffles, remove redundant shuffles
			if int(shf[1:]) > shufnum:
				os.remove(netfile)
			return 0
		# Note: the shuffling might be scheduled even when the shuffles exist in case
		# the origin network is traversed before it's shuffles
		shuffle(Job(name=name, workdir=path + '/'))
		return shufnum  # The network is shuffled shufnum times

	count = 0
	for netdir in datadirs:
		for nets in (glob.iglob('*'.join((netdir, netext))), datafiles):
			for net in nets:  # Allow wildcards
				count += shuffleNet(net)
	for asym, dfile in datafiles:
		count += shuffleNet(dfile)

	if _execpool:
		_execpool.join(max(shuftimeout, count * shufnum * timeout))  # 30 min
		_execpool = None
	print('Synthetic networks files generation is completed')


def convertNet(inpnet, overwrite=False, resdub=False, timeout=3*60):  # 3 min
	"""Convert input networks to another formats

	inpnet  - the network file to be converted
	overwrite  - whether to overwrite existing networks or use them
	resdub  - resolve duplicated links
	timeout  - network conversion timeout
	"""
	try:
		args = [PYEXEC, _UTILDIR + 'convert.py', inpnet, '-o rcg', '-r ' + ('o' if overwrite else 's')]
		if resdub:
			args.append('-d')
		_execpool.execute(Job(name=os.path.splitext(os.path.split(inpnet)[1])[0], args=args, timeout=timeout))
	except StandardError as err:
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
	#except StandardError as err:
	#	print('ERROR on "{}" conversion into .lig, the network is skipped: {}'.format(net), err, file=sys.stderr)


def convertNets(datadirs, datafiles, netext=_EXTNETFILE, overwrite=False, resdub=False, convtimeout=30*60):  # 30 min
	"""Convert input networks to another formats

	datadirs  - unique directories of the converting networks (without wildcards)
	datafiles  - unique files of the converting networks (without wildcards)
	netext  - network file extension (should have the leading '.')
	overwrite  - whether to overwrite existing networks or use them
	resdub  - resolve duplicated links
	"""
	assert netext and netext[0] == '.', 'A file extension should have the leading "."'
	print('Converting networks into the required formats (.hig, .lig, etc.)...')
	global _execpool

	if not _execpool:
		_execpool = ExecPool(max(cpu_count() - 1, _WPROCSMIN))

	convTimeMax = 5 * 60  # 5 min
	netsnum = 0  # Number of converted networks
	# Convert network files to required formats: .rcg, .lig (Louvain Input Format), etc.
	for netdir in datadirs:
		for nets in (glob.iglob('*'.join((netdir, netext))), datafiles):
			for net in nets:  # Note: the shuffles are also included
				convertNet(net, overwrite, resdub, convTimeMax)
				netsnum += 1

	if _execpool:
		_execpool.join(max(convtimeout, netsnum * convTimeMax))
		_execpool = None
	print('Networks conversion is completed, converted {} networks'.format(netsnum))


def runApps(appsmodule, algorithms, datadirs, datafiles, netext, exectime, timeout):
	"""Run specified applications (clustering algorithms) on the specified datasets

	appsmodule  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms  - list of the algorithms to be executed
	datadirs  - directories with target networks to be processed
	datafiles  - target networks to be processed
	netext  - network file extension (should have the leading '.')
	exectime  - elapsed time since the benchmarking started
	timeout  - timeout per each algorithm execution
	"""
	assert netext and netext[0] == '.', 'A file extension should have the leading "."'
	assert appsmodule and (datadirs or datafiles) and exectime >= 0 and timeout >= 0, 'Invalid input arguments'

	global _execpool

	assert not _execpool, '_execpool should be clear on algs execution'
	starttime = time.time()  # Procedure start time
	if not _execpool:
		_execpool = ExecPool(max(cpu_count() - 1, _WPROCSMIN))

	def unknownApp(name):
		"""A stub for the unknown / not implemented apps (algorithms) to be benchmaked

		name  - name of the funciton to be called (traced and skipped)
		"""
		def stub(*args, **kwargs):
			print(' '.join(('ERROR: ', name, 'function is not implemented, the call is skipped.')), file=sys.stderr)
		stub.__name__ = name  # Set original name to the stub func
		return stub

	# Run all algs if not specified the concrete algorithms to be run
	if not algorithms:
		execalgs = [getattr(appsmodule, func) for func in dir(appsmodule) if func.startswith(_PREFEXEC)]
		# Save algorithms to perform resutls aggregation after the execution
		preflen = len(_PREFEXEC)
		algorithms = [func[preflen:] for func in dir(appsmodule) if func.startswith(_PREFEXEC)]
	else:
		execalgs = [getattr(appsmodule, _PREFEXEC + alg.capitalize(), unknownApp(_PREFEXEC + alg.capitalize())) for alg in algorithms]
		#algorithms = [alg.lower() for alg in algorithms]
	execalgs = tuple(execalgs)

	def execute(net, asym, pathid=''):
		"""Execute algorithms on the specified network counting number of ran jobs

		net  - network to be processed
		asym  - network links weights are asymmetric (in/outbound weights can be different)
		pathid  - path id of the net to distinguish nets with the same name located in different dirs

		return
			jobsnum  - number of scheduled jobs
		"""
		for ealg in execalgs:
			try:
				jobsnum = ealg(_execpool, net, asym, timeout, pathid)
			except StandardError as err:
				jobsnum = 0
				errexectime = time.time() - exectime
				print('WARNING, the "{}" is interrupted by the exception: {}. {} on {:.4f} sec ({} h {} m {:.4f} s)'
					.format(ealg.__name__, err, errexectime, traceback.format_exc(), *secondsToHms(errexectime)), file=sys.stderr)
		return jobsnum

	# Desribe paths mapping if required
	fpid = None
	if len(datadirs) + len(datafiles) > 1:
		if not os.path.exists(_RESDIR):
			os.mkdir(_RESDIR)
		pathidsMap = _RESDIR + 'path_ids.map'  # Path ids map file
		try:
			fpid = open(pathidsMap, 'a')
		except IOError as err:
			print('WARNING, creation of the path ids map file is failed: {}. The mapping is outputted to stdout.'
				.format(err), file=sys.stderr)
			fpid = sys.stdout
		# Write header if required
		if not os.path.getsize(pathidsMap):
			fpid.write('# ID(#)\tPath\n')  # Note: buffer flushing is not nesessary here, beause the execution is not concurrent
		fpid.write('# --- {} ---\n'.format(datetime.utcnow()))  # Write timestamp
	jobsnum = 0  # Number of the processed network jobs (can be a few per each algorithm per each network)
	netcount = 0  # Number of networks to be processed
	# Track processed file names to resolve cases when files with the same name present in different input dirs
	filenames = set()
	for pathid, (asym, ddir) in enumerate(datadirs):
		pathid = _SEPPATHID + str(pathid)
		tracePath = False
		for net in glob.iglob('*'.join((ddir, netext))):  # Allow wildcards
			netname = os.path.split(net)[1]
			ambiguous = False  # Net name is unambigues even without the dir
			if netname not in filenames:
				filenames.add(netname)
			else:
				ambiguous = True
				tracePath = True
			tnum = execute(net, asym, pathid if ambiguous else '')
			jobsnum += tnum
			netcount += tnum != 0
		if tracePath:
			fpid.write('{}\t{}\n'.format(pathid[1:], ddir))  # Skip the separator symbol
	for pathid, (asym, net) in enumerate(datafiles):
		pathid = ''.join((_SEPPATHID, _PATHID_FILE, str(pathid)))
		netname = os.path.split(net)[1]
		ambiguous = False  # Net name is unambigues even without the dir
		if netname not in filenames:
			filenames.add(netname)
		else:
			ambiguous = True
			fpid.write('{}\t{}\n'.format(pathid[1:], net))  # Skip the separator symbol
		tnum = execute(net, asym, pathid if ambiguous else '')
		jobsnum += tnum
		netcount += tnum != 0
	# Flush resulting buffer
	if fpid:
		if fpid is not sys.stdout:
			fpid.close()
		else:
			fpid.flush()
	filenames = None  # Free memory from filenames

	if _execpool:
		timelim = min(timeout * jobsnum, 5 * 24*60*60)  # Global timeout, up to N days
		print('Waiting for the apps execution on {} jobs from {} networks'
			' with {} sec ({} h {} m {:.4f} s) timeout ...'.format(jobsnum, netcount, timelim, *secondsToHms(timelim)))
		_execpool.join(timelim)
		_execpool = None
	starttime = time.time() - starttime
	print('The apps execution is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(starttime, *secondsToHms(starttime)))
	print('Aggregating execution statistics...')
	aggexec(algorithms)
	print('Execution statistics aggregated')


def evalResults(evalres, appsmodule, algorithms, datadirs, datafiles, exectime, timeout):
	"""Run specified applications (clustering algorithms) on the specified datasets

	evalres  - evaluation flags: 0 - Skip evaluations, 1 - NMI, 2 - NMI_s, 4 - Q (modularity), 7 - all measures
	appsmodule  - module with algorithms definitions to be run; sys.modules[__name__]
	algorithms  - list of the algorithms to be executed
	datadirs  - directories with target networks to be processed
	datafiles  - target networks to be processed
	exectime  - elapsed time since the benchmarking started
	timeout  - timeout per each evaluation run
	"""
	assert (evalres and appsmodule and (datadirs or datafiles) and exectime >= 0
		and timeout >= 0), 'Invalid input arguments'

	global _execpool

	assert not _execpool, '_execpool should be clear on algs evaluation'
	starttime = time.time()  # Procedure start time
	if not _execpool:
		_execpool = ExecPool(max(cpu_count() - 1, _WPROCSMIN))

	# Measures is a dict with the Array values: <evalcallback_prefix>, <grounttruthnet_extension>, <measure_name>
	measures = {3: ['nmi', _EXTCLNODES, 'NMIs'], 4: ['mod', '.hig', 'Q']}
	evaggs = []  # Evaluation results aggregators
	for im, msr in measures.items():
		# Evaluate only required measures
		if evalres & im == 0:
			continue
		if im == 3:
			# Exclude NMI if it is aplied, but evalres & 1 == 0
			if evalres & 1 == 0:
				msr[0] = 'nmi_s'
				msr[2] = 'NMI_s'
			elif evalres & 2 == 0:
				msr[2] = 'NMI'
			else:
				evagg_s = EvalsAgg('nmi_s')  # Reserve also second results aggregator for nmi_s
				evaggs.append(evagg_s)
		evagg = EvalsAgg(msr[0])  # Evaluation results aggregator
		evaggs.append(evagg)

		if not algorithms:
			# Fetch available algorithms
			ianame = len(_PREFEXEC)  # Index of the algorithm name start
			evalalgs = [funcname[ianame:].lower() for funcname in dir(appsmodule) if func.startswith(_PREFEXEC)]
		else:
			evalalgs = [alg.lower() for alg in algorithms]
		evalalgs = tuple(evalalgs)

		def evaluate(measure, basefile, asym, jobsnum, pathid=''):
			"""Evaluate algorithms on the specified network

			measure  - target measure to be evaluated: {nmi, mod}
			basefile  - ground truth result, or initial network file or another measure-related file
			asym  - network links weights are asymmetric (in/outbound weights can be different)
			jobsnum  - accumulated number of scheduled jobs
			pathid  - path id of the basefile to distinguish files with the same name located in different dirs
				Note: pathid includes pathid separator

			return
				jobsnum  - updated accumulated number of scheduled jobs
			"""
			assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'

			for algname in evalalgs:
				try:
					evalAlgorithm(_execpool, algname, basefile, measure, timeout, evagg, pathid)
					## Evaluate also nmi_s besides nmi if required
					if evalres & im == 3:
					#if measure == 'nmi':
						evalAlgorithm(_execpool, algname, basefile, 'nmi_s', timeout, evagg_s, pathid)
				except StandardError as err:
					print('WARNING, "{}" evaluation of "{}" is interrupted by the exception: {}. {}'
						.format(measure, algname, err, traceback.format_exc()), file=sys.stderr)
				else:
					jobsnum += 1
			return jobsnum

		print('Starting {} evaluation...'.format(msr[2]))
		jobsnum = 0
		measure = msr[0]
		fileext = msr[1]  # Initial networks in .hig formatare required for mod, clusters for NMIs
		# Track processed file names to resolve cases when files with the same name present in different input dirs
		filenames = set()
		for pathid, (asym, ddir) in enumerate(datadirs):
			pathid = _SEPPATHID + str(pathid)
			# Read ground truth
			for basefile in glob.iglob('*'.join((ddir, fileext))):  # Allow wildcards in the names
				netname = os.path.split(basefile)[1]
				ambiguous = False  # Net name is unambigues even without the dir
				if netname not in filenames:
					filenames.add(netname)
				else:
					ambiguous = True
				evaluate(measure, basefile, asym, jobsnum, pathid if ambiguous else '')
		for pathid, (asym, basefile) in enumerate(datafiles):
			pathid = ''.join((_SEPPATHID, _PATHID_FILE, str(pathid)))
			# Use files with required extension
			basefile = os.path.splitext(basefile)[0] + fileext
			netname = os.path.split(basefile)[1]
			ambiguous = False  # Net name is unambigues even without the dir
			if netname not in filenames:
				filenames.add(netname)
			else:
				ambiguous = True
			evaluate(basefile, asym, jobsnum, pathid if ambiguous else '')
		print('{} evaluation is scheduled'.format(msr[2]))
		filenames = None  # Free memory from filenames

	if _execpool:
		timelim = min(timeout * jobsnum, 5 * 24*60*60)  # Global timeout, up to N days
		try:
			_execpool.join(max(timelim, exectime * 2))  # Twice the time of algorithms execution
		except StandardError as err:
			print('Results evaluation execution pol is interrupted by: {}. {}'
				.format(err, traceback.format_exc()), file=sys.stderr)
			raise
		_execpool = None
	starttime = time.time() - starttime
	print('Results evaluation is successfully completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(starttime, *secondsToHms(starttime)))
	# Aggregate results and output
	starttime = time.time()
	print('Starting processing of aggregated results ...')
	for evagg in evaggs:
		evagg.aggregate()
	starttime = time.time() - starttime
	print('Processing of aggregated results completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(starttime, *secondsToHms(starttime)))


def benchmark(*args):
	"""Execute the benchmark

	Run the algorithms on the specified datasets respecting the parameters.
	"""
	exectime = time.time()  # Benchmarking start time

	opts = parseParams(args)
	print('The benchmark is started, parsed params:\n\tgensynt: {}\n\tsyntdir: {}\n\tconvnets: 0b{:b}'
		'\n\trunalgs: {}\n\tevalres: 0b{:b}\n\tdatas: {}\n\ttimeout (h, min, sec): {}\n\talgorithms: {},\n\taggrespaths: {}'
		.format(opts.gensynt, opts.syntdir, opts.convnets, opts.runalgs, opts.evalres
			, ', '.join(['{}{}{}'.format('' if not asym else 'asym: ', path, ' (gendir)' if gen else '')
				for asym, path, gen in opts.datas])
			, secondsToHms(opts.timeout), ', '.join(opts.algorithms) if opts.algorithms else ''
			, ', '.join(opts.aggrespaths) if opts.aggrespaths else ''))
	# Make opts.syntdir and link there lfr benchmark bin if required
	bmname = 'lfrbench_udwov'  # Benchmark name for the synthetic networks generation
	assert _UTILDIR.endswith('/'), 'A directory should have a valid terminator'
	benchpath = _UTILDIR + bmname  # Benchmark path
	if not os.path.exists(opts.syntdir):
		os.makedirs(opts.syntdir)
		## Symlink is used to work even when target file is on another file system
		#os.symlink(os.path.relpath(opts.syntdir + bmname, opts.syntdir), benchpath)

	if opts.gensynt and opts.netins >= 1:
		# opts.gensynt:  0 - do not generate, 1 - only if not exists, 2 - forced generation
		generateNets(benchpath, opts.syntdir, _NETSDIR, opts.netext, opts.gensynt == 2, opts.netins, opts.seedfile)

	# Update opts.datasets with sythetic generated
	# Note: should be done only after the genertion, because new directories can be created
	asym = asymnet(opts.netext)  # Whether the network is asymetric (directed)
	if opts.gensynt or not opts.datas:
		opts.datas.append(PathOpts(_NETSDIR.join((opts.syntdir, '*/')), False, asym))  # path, flat, asym

	# Extract dirs and files from opts.datas, generate dirs structure if required and resolve the wildcards
	datadirs, datafiles = prepareInput(opts.datas, opts.netext)
	opts.datas = None
	#print('Datadirs: ', datadirs)

	# Note: the conversion should be performed after the shuffling if required to convert also the shuffles
	if opts.shufnum:
		shuffleNets(datadirs, datafiles, opts.shufnum, opts.netext, opts.gensynt == 2)

	# Note: conversion should not be used typically
	# opts.convnets: 0 - do not convert, 0b01 - only if not exists, 0b11 - forced conversion, 0b100 - resolve duplicated links
	if opts.convnets:
		convertNets(datadirs, datafiles, opts.netext, opts.convnets&0b11 == 0b11, opts.convnets&0b100)

	# Run the opts.algorithms and measure their resource consumption
	if opts.runalgs:
		runApps(benchapps, opts.algorithms, datadirs, datafiles, exectime, opts.timeout)

	# Evaluate results
	if opts.evalres:
		evalResults(opts.evalres, benchapps, opts.algorithms, datadirs, datafiles, exectime, opts.timeout)

	if opts.aggrespaths:
		aggEvaluations(opts.aggrespaths)

	exectime = time.time() - exectime
	print('The benchmark is completed in {:.4f} sec ({} h {} m {:.4f} s)'
		.format(exectime, *secondsToHms(exectime)))


def terminationHandler(signal=None, frame=None):
	"""Signal termination handler"""
	#if signal == signal.SIGABRT:
	#	os.killpg(os.getpgrp(), signal)
	#	os.kill(os.getpid(), signal)

	global _execpool

	if _execpool:
		del _execpool  # Destructors are caled later
	sys.exit(0)


if __name__ == '__main__':
	if len(sys.argv) <= 1 or (len(sys.argv) == 2 and sys.argv[1] == '-h'):
		print('\n'.join(('Usage:',
			'  {0} [-g[f][=[<number>][.<shuffles_number>][=<outpdir>]] [-c[f][r]] [-a="app1 app2 ..."]'
			' [-r] [-e[{{n[x],o[x],f[{{h,p}}],d,e,m}}] [-i[f]{{a,e}}=<datasets_{{dir, file}}_wildcard>'
			' [-a=<eval_path>] [-x=<extension>] [-t[{{s,m,h}}]=<timeout>] [-s=<seed_file>] | -h',
			'',
			'Example:',
			'  {0} -g=3.5 -r -e -th=2.5 1> {resdir}bench.log 2> {resdir}bench.err',
			'Note: should be executed exclusively from the current directory (./)',
			'',
			'Parameters:',
			'  -h  - show this usage description',
			'  -g[f][=[<number>][.<shuffles_number>][=<outpdir>]]  - generate <number> ({synetsnum} by default) >= 0'
			' synthetic datasets (networks) in the <outpdir> ("{syntdir}" by default), shuffling each <shuffles_number>'
			'  >= 0 times (default: 0). If <number> is omitted or set to 0 then ONLY shuffling of the specified datasets'
			' should be performed including the <outpdir>/{netsdir}/*.',
			'    f  - force the generation even when the data already exists (existent datasets are moved to backup)',
			'  NOTE:',
			'    - shuffled datasets have the following naming format:\n'
			'\t<base_name>[(seppars)<param1>...][{sepinst}<instance_index>][{sepshf}<shuffle_index>].<net_extension>',
			'    - use "-g0" to execute existing synthetic datasets not changing them',
			'  -c[X]  - convert existing networks into the required formats (.rcg[.hig], .lig, etc.)',
			'    f  - force the conversion even when the data is already exist',
			'    r  - resolve (remove) duplicated links on conversion (recommended to be used)',
			'  NOTE: files with {extnetfile} are looked for in the specified dirs to be converted',
			'  -a="app1 app2 ..."  - apps (clustering algorithms) to run/benchmark among the implemented.'
			' Available: scp louvain_igraph randcommuns hirecs oslom2 ganxis.'
			' Impacts {{r, e}} options. Optional, all apps are executed by default.',
			'  NOTE: output results are stored in the "{resdir}<algname>/" directory',
			'  -r  - run the benchmarking apps on the specified networks',
			#'    f  - force execution even when the results already exists (existent datasets are moved to backup)',
			'  -e[X]  - evaluate quality of the results, default: all',
			#'    f  - force execution even when the results already exists (existent datasets are moved to backup)',
			'    e[Y]  - extrinsic measures for overlapping communities, default: all',
			'     n[Z]  - NMI measure(s) for overlapping and multi-level communities: max, avg, min, sqrt',
			'      x  - NMI_max,',
			#'      a  - NMI_avg (also known as NMI_sum),',
			#'      n  - NMI_min,',
			#'      r  - NMI_sqrt',
			'     o[Z]  - overlapping NMI measure(s) for overlapping communities'
			' that are not multi-level: max, sum, lfk. Note: it is much faster than generalized NMI',
			'      x  - NMI_max',
			'     f[Y]  - avg F1-Score(s) for overlapping and multi-level communities: avg, hmean, pprob',
			#'      a  - avg F1-Score',
			'      h  - harmonic mean of F1-Score',
			'      p  - F1p measure (harmonic mean of the weighted average of partial probabilities)',
			'     d  - default extrinsic measures (NMI_max, F1_h, F1_p) for overlapping communities',
			'    i[Y]  - intrinsic measures for overlapping communities',
			'     m  - modularity Q',
			'     c  - conductance f',
			'  -i[X]=<datasets_dir>  - input dataset(s), directory with datasets or a single dataset file, wildcards allowed.'
			' Default: -ie={syntdir}{netsdir}*/',  # Note: corresponds to the _EXTNETFILE=.'.nse'
			'    f  - use flat derivatives on shuffling instead of generating the dedicted directory (havng the file base name)'
			' for each input network when shuffling is performed to avoid flooding of the base directory with network shuffles.'
			' Used when the number of instances*shuffles is small. Existed shuffles are backuped',
			'    a  - the dataset is specified by arcs (asymmetric links, in/outbound weights of the link might differ)',
			'    e  - the dataset is specified by edges (symmetric links). Default option',
			'    NOTE:',
			'    - datasets file names must not contain "." (besides the extension),'
			' because it is used as indicator of the shuffled datasets',
			'    - paths can contain wildcards: *, ?, +',
			'    - multiple directories and files can be specified via multiple -d/f options (one per the item)',
			'    - datasets should have the following format: <node_src> <node_dest> [<weight>]',
			'    - {{a,s}} is considered only if the network file has no corresponding metadata (formats like SNAP, ncol, nsa, ...)',
			'    - ambiguity of links weight resolution in case of duplicates (or edges specified in both directions)'
			' is up to the clustering algorithm',
			'  -x=<extension>  - network (dataset) file extension (leading "." cand be omitted), default: {extnetfile}',
			'  -a=<eval_path>  - perform aggregation of the specified evaluation results without the evaluation itself',
			'    NOTE:',
			'    - paths can contain wildcards: *, ?, +'
			'    - multiple paths can be specified via multiple -s options (one per the item)',
			'  -t[X]=<float_number>  - specifies timeout for each benchmarking application per single evaluation on each network'
			' in sec, min or hours; 0 sec - no timeout, Default: {th} h {tm} min {ts} sec',
			'    s  - time in seconds. Default option',
			'    m  - time in minutes',
			'    h  - time in hours',
			'  -s=<seed_file>  - seed file to be used/created for the synthetic networks generation and stochastic algorithms'
			', contains uint64_t value. Default: {seedfile}'
			)).format(sys.argv[0], syntdir=_SYNTDIR, synetsnum=_SYNTINUM, netsdir=_NETSDIR
				, sepinst=_SEPINST, seppars=_SEPPARS, sepshf=_SEPSHF, extnetfile=_EXTNETFILE, resdir=_RESDIR
				, th=_TIMEOUT//3600, tm=_TIMEOUT//60%60, ts=_TIMEOUT%60, seedfile=_SEEDFILE))
	else:
		# Set handlers of external signals
		signal.signal(signal.SIGTERM, terminationHandler)
		signal.signal(signal.SIGHUP, terminationHandler)
		signal.signal(signal.SIGINT, terminationHandler)
		signal.signal(signal.SIGQUIT, terminationHandler)
		signal.signal(signal.SIGABRT, terminationHandler)

		# Set termination handler for the internal termination
		atexit.register(terminationHandler)

		benchmark(*sys.argv[1:])


# Extrenal API (exporting functions)
__all__ = [generateNets, shuffleNets, convertNet, convertNets, runApps, evalResults, benchmark]
