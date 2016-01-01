# PyCABeM (former HiCBeM) - Python Benchmarking Framework for the Clustering Algorithms Evaluation
\brief Uses extrinsic (NMIs) and intrinsic (Q) measures for the clusters quality evaluation considering overlaps (nodes membership by multiple clusters)  
\author: (c) Artem Lutov <artem@exascale.info>  
\organizations: [eXascale Infolab](http://exascale.info/), [Lumais](http://www.lumais.com/), [ScienceWise](http://sciencewise.info/)  
\keywords: overlapping clustering benchmarking, community detection benchmarking, algorithms benchmarking framework.


## Content
[Functionality](#functionality)  
[Dependencies](#dependencies)  
[Usage](#usage)  
[Benchmark Structure](#benchmark-structure)  
[Extension](#extension)  
[Related Projects](#related-projects)  


## Functionality
### Generic Benchmarking Framework
- optionally *generates or preprocesses datasets* using specified executable(s) (by default uses LFR framework for overlapping weightted networks)
- optionally *executes specified apps* (clustering algorithms; can be a binary, any script or java executable) with the specified params on the specified datasets (networks)
- optionally *evaluates results* of the execution using specified executable(s) (by default performs NMIs and Q evaluation) and *performs unified aggregation* of results from multiple apps on multiple datasets into the single file by the specified measure
- *per-task and global timeouts* (for an app execution on a single dataset) and specified number of CPU cores (workers) are set for the *batch apps execution / evaluation* using the multi-process task execution pool ([mpepool](//github.com/XI-lab/PyExPool))
- per-task and accumulative *execution tracing and resutls logging* is performed even in case of internal / external interruptions and crashes:
	* all stdout/err output is logged
	* resources consumption, i. e. time: execution (wall-clock) and CPU concumption (user, kernel, total), memory (RAM RSS) are traced
- *automatic extension / backup* of the previously existent results to .gzip with the timestamp on the benchmarking reexecution

It is possible to have multiple input directories with similary named files inside, which represent different instances / snapshots of the datasets. In such case, the output results are provided per each snapshot, plus aggregated weighted average over all snapshots. This is useful to avoid occasional bias to the specific instance or to analize evolving networks.

In case of the measured application crash, the crash is logged and has no any impact on the exectuion of the remaining applications.


### Benchmark of the Hierarchical Overlapping Clustering Algorithms
The benchmark is implemented as customization of the Generic Benchmarking Framework to evaluate *Hierarchical Overlapping  Clustering Algorithms*:
- produces synthetic networks with specified number of instances for each set of parameters, generating them by the extended [LFR Framework](https://sites.google.com/site/santofortunato/inthepress2) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti and Santo Fortunato)
- shuffles (reorders nodes) specified networks specified number of times, which is required to evaluate stability / determinism of the clustering algorithms
- executes
	* [HiReCS](http://www.lumais.com/hirecs) (www.lumais.com/hirecs)
	* [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) ([Sequential algorithm for fast clique percolation](http://www.lce.hut.fi/research/mm/complex/software/))
	* [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations)
	* [Oslom2](http://www.oslom.org/software.htm)
	* [GANXiS/SLPA](https://sites.google.com/site/communitydetectionslpa/) (but *this algorithm is not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only"*; *deterministic algorithm LabelRankT* is a modification of GANXiS, but LabelRankT is not publicly available)
	* [Randcommuns](/algorithms/randcommuns.py)  - generation of random communities (clusters) with struture of clusters similar to the ground-truth: the same number of random connected nodes in the number of clusters taken from the ground-truth

	clustering algorithms on the generated synthetic networks (or on any specified directories and files). Outputs results (clusters/communities structure, hierarchy, modularity, nmi, etc.) of the clustering algorithms are stored in the corresponding files.
	
	Features \ Algs | *HiReCS* | SCP | Louvain | Oslom2 | GANXiS
	            --- | --- | --- | --- | --- | ---
	Hierarchical    | + | | + | + |
	Multi-scale     | + | + | + | + | + 
	Deterministic   | + | + | | | 
	With Overlaps   | + | + | | + | +
	Parameter-Free  | + | | + | | 

- evaluates results using:
	- extrinsic measures  - NMIs for overlapping communities, extended to have uniform input / output formats:
		* NMI  - `gecmi` (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
		* NMI_s  - `onmi` (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms" by Aaron F. McDaid, Derek Greene, Neil Hurley)
	- intrinsic measure  - Q (standard modularity value, but applicable for overlapping communities), evaluated by `HiReCS` (http://www.lumais.com/hirecs)
- resources consumption is evaluated using `exectime` profiler (https://bitbucket.org/lumais/exectime/)

All results and traces are stored into the corresponding files even in case of internal (crash) / external termination of the benchmarking applications or the whole framework.

 > Note: valuable extensions of the employed external applications are uploaded into ./contrib/

Basically the framework executes a set of applications on the specified datasets in interactive or daemon mode, logging the resources consumption, output and exceptions, providing workflow management (termination by timeout, resistance to exceptions, etc.) and results aggregation.


## Dependencies
### Fundamental
- Python 2.7+ (or [PyPy](http://pypy.org/) JIT for the fast execution).
 
> Note: It is recommended to run the benchmark itself under PyPy. The measured algorithms can be ran either using the same python or under the dedicated interpreter / script / executable.

### Libraries
- [hirecs](http://www.lumais.com/hirecs/) for modularity evaluation of overlapping community structure with results compatible to the standard modularity value. It depends on:
  * `libstdc++.so.6`: version GLIBCXX_3.4.20 (precompiled version for modularity evaluation). To install it on Ubuntu use: `sudo apt-get install libstdc++6` or
```sh
$ sudo add-apt-repository ppa:ubuntu-toolchain-r/test 
$ sudo apt-get update
$ sudo apt-get install libstdc++6
```
	
  > Note: This functionality is available in the dev version of the HiReCS 2 and have not been pushed to the public hirecs repository yet. Please write me if you need it.

- [python-igraph](http://igraph.org/python/) for Louvain algorithm evaluation by NMIs (because the original implementation does not provide convenient output of the communities to evaluate NMIs): `$ pip install python-igraph`. It depends on:
	* `libz` and `libxml2`, which are installed in Linux Ubuntu executing:  
	`$ sudo apt-get install lib32z1-dev libxml2-dev`

- [`gecmi`](https://bitbucket.org/dsign/gecmi/wiki/Home) for the NMI_ovp evaluation, it depends on:
	* `libboost_program_options.so.1.54.0`, to install execute: `$ sudo apt-get install libboost-program-options1.54.0`
	* `libtbb.so.2`, to install execute: `sudo aptitude download libtbb2; sudo aptitude install libtbb2`
	
  > Note: gecmi dependencies are uploaded to `./algorithms/gecmi_deps/`.

- [PyExPool](//github.com/XI-lab/PyExPool) for asynchronious jobs execution and results aggregation via tasks of jobs
	
  > Note: it is uploaded to `./contrib/`.

### External tools that are used as executables
- [Extended LFR Benchmark](contrib/lfrbench_weight-undir-ovp) for the undirected weighted networks with overlaps (origins are here: https://sites.google.com/site/santofortunato/inthepress2, https://sites.google.com/site/andrealancichinetti/files)
- [Tiny execution profiler](https://bitbucket.org/lumais/exectime/) to evaluate resources consumption: https://bitbucket.org/lumais/exectime/
- Clustering algorithms, used in the benchmarking: [HiReCS](http://www.lumais.com/hirecs), [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm) and [GANXiS/SLPA](https://sites.google.com/site/communitydetectionslpa/)
 
## Usage
- `./install_depends.sh`  - install dependencies (using apt-get)
- `./benchmark.py`  - run the benchmark in the terminal (interactive mode)
- `./benchmark_daemon.sh`  - run the benchmark in background (daemon mode)

> Note: Execution of the benchmark was verified only on Linux Ubuntu 14.04 x64, but it should work on any platform if corresponding external executables (algorithms, nmi evaluation apps, etc.) are provided for the required platform.

To see possible input parameters run the benchmark without arguments: `$ ./benchmark.py`:  
```
$ ./benchmark.py 
Usage: ./benchmark.py [-g[f][=[<number>][.<shuffles_number>][=<outpdir>]] [-c[f][r]] [-a="app1 app2 ..."] [-r] [-e[n][s][e][m]] [-d[g]{a,s}=<datasets_dir>] [-f[g]{a,s}=<dataset>] [-t[{s,m,h}]=<timeout>]
Parameters:
  -g[f][=[<number>][.<shuffles_number>][=<outpdir>]]  - generate <number> (5 by default) >= 0 synthetic datasets in the <outpdir> ("syntnets/" by default), shuffling each <shuffles_number> (0 by default) >= 0 times. If <number> is omitted or set to 0 then ONLY shuffling of the specified datasets should be performed including the <outpdir>/networks//*.
    Xf  - force the generation even when the data already exists (existent datasets are moved to backup)
  NOTE:
    - shuffled datasets have the following naming format: <base_name>[^<instance_index>][(seppars)<param1>...][.<shuffle_index>].<net_extension>
    - use "-g0" to execute existing synthetic networks not changing them
  -c[X]  - convert existing networks into the .hig, .lig, etc. formats
    Xf  - force the conversion even when the data is already exist
    Xr  - resolve (remove) duplicated links on conversion. Note: this option is recommended to be used
  NOTE: files with .nsa are looked for in the specified dirs to be converted
  -a="app1 app2 ..."  - apps (clustering algorithms) to run/benchmark among the implemented. Available: scp louvain_igraph randcommuns hirecs oslom2 ganxis. Impacts {r, e} options. Optional, all apps are executed by default.
  NOTE: output results are stored in the "algorithms/<algname>outp/" directory
  -r  - run the benchmarking apps on the prepared data
  -e[X]  - evaluate quality of the results. Default: apply all measurements
    Xn  - evaluate results accuracy using NMI measure for overlapping communities
    Xs  - evaluate results accuracy using NMI_s measure for overlapping communities
    Xe  - evaluate results accuracy using extrinsic measures (both NMIs) for overlapping communities (same as Xns)
    Xm  - evaluate results quality by modularity
  -d[X]=<datasets_dir>  - directory of the datasets.
  -f[X]=<dataset>  - dataset (network, graph) file name.
    Xg  - generate directory with the network file name without extension for each input network (*.nsa) when shuffling is performed (to avoids flooding of the base directory with network shuffles). Previously existed shuffles are backuped
    Xa  - the dataset is specified by asymmetric links (in/outbound weights of the link might differ), arcs
    Xs  - the dataset is specified by symmetric links, edges. Default option
    NOTE:
	 - datasets file names must not contain "." (besides the extension), because it is used as indicator of the shuffled datasets
    - paths can contain wildcards: *, ?, +    - multiple directories and files can be specified via multiple -d/f options (one per the item)
    - datasets should have the following format: <node_src> <node_dest> [<weight>]
    - {a,s} is considered only if the network file has no corresponding metadata (formats like SNAP, ncol, nsa, ...)
    - ambiguity of links weight resolution in case of duplicates (or edges specified in both directions) is up to the clustering algorithm
  -t[X]=<float_number>  - specifies timeout for each benchmarking application per single evaluation on each network in sec, min or hours. Default: 0 sec  - no timeout
    Xs  - time in seconds. Default option
    Xm  - time in minutes
    Xh  - time in hours
```

## Benchmark Structure
- ./contrib/  - valuable patches to the external open source tools used as binaries
- ./algorithms/  - benchmarking algorithms
- ./resutls/  - aggregated and per-algorithm execution and evaluation results (brief `*.res` and extended `*.resx`): timings (execution and CPU), memory consumption, NMIs, Q, per-algorithm resources consumption profile (`*.rcp`)
	- `<algname>.rcp`  - resource consumption profile for all executions of the algorithm even in case of crashes / interruptions
	- `<measure>.res[x]`  - aggregated value of the measure: average is evaluated for each level / scale for all shuffles of the each network instance, then the weighted best average among all levels is taken for all instances as a final result
	* <algname>/clusters/  - algorithm execution results produced hierachies of communities for each network instance shuffle
		- `*.cnl`  - resulting clusters unwrapped to nodes (community nodes list) for NMIs evaluation. `*.cnl` are generated either per each level of the resulting hierarchy of communities or for the whole hierarchy (parameterized inside the benchmark)
	* <algname>/mod/  - algorithm evaluation modularity for each produced hierarchical/scale level
		- `<net_instance>.mod`  - modularity value aggregated per network instances (results for all shuffles on the network instance are aggregated in the same file)
	* <algname>/nmi[_s]/  - algorithm evaluation NMI[_s] for each produced hierarchical/scale level
		- `<net_instance>.nmi[_s]`  - NMI[_s] value aggregated per network instances
	- `*.log`  - `stdout` of the executed algorithm, logs
	- `*.err`  - `stderr` of the executed algorithm and benchmarking routings, errors

Example of the `<entity>.rcp` format:
```
# ExecTime(sec)	CPU_time(sec)	CPU_usr(sec)	CPU_kern(sec)	RSS_RAM_peak(Mb)	TaskName
2.575555	2.574302	2.540420	0.033882	6.082	5K5
0.528582	0.528704	0.519277	0.009427	3.711	2K10
...
```

Example of the `.res` format:
```
# --- 2015-12-31 16:15:37.693514, output:  Q_avg
# <network>	ganxis	louvain_igraph	...
karate	0.130950	0.414481	0.233974	0.240929
jazz_u	0.330844	0.400587	0.392081	0.292395
...
```

Example of the `.resx` format:
```
# --- 2015-12-31 17:05:50.582245 ---
# <network>
#	<alg1_outp>
#	<alg2_outp>
#	...
karate
	ganxis>	Q: 0.130950 (0.084073 .. 0.217867), s: 0.163688, count: 5, fails: 0, d(shuf): 0.133794, s(shuf): 0.0566965, count(shuf): 5, fails(shuf): 0
	louvain_igraph>	Q: 0.414481 (0.395217 .. 0.419790), s: 0.518101, count: 5, fails: 0, d(shuf): 0.024573, s(shuf): 0.0120524, count(shuf): 5, fails(shuf): 0
	...
jazz_u
	ganxis>	Q: 0.340728 (0.321374 .. 0.371617), s: 0.42591, count: 5, fails: 0, d(shuf): 0.050243, s(shuf): 0.0219596, count(shuf): 5, fails(shuf): 0
	louvain_igraph>	Q: 0.400587 (0.399932 .. 0.400999), s: 0.534116, count: 4, fails: 0, d(shuf): 0.001067, s(shuf): 0.000595067, count(shuf): 4, fails(shuf): 0
	...
...
```

Example of the `<net_instance>.nmi[_s]` format:
```
# NMI	level[/shuffle]
0.815814	0
0.870791	1
0.882737	0/1
...
```

Example of the `<net_instance>.mod` format:
```
# Q	level[/shuffle]
0.333874	1
0.32539	0
0.313085	0/1
...
```

- ./realnets/  - simple gold standard networks with available ground truth value of the modularity for non-overlapping clustering (from [DIMACS 10th](http://www.cc.gatech.edu/dimacs10/), "Modularity Maximization in Networks by Variable Neighborhood Search" by Daniel Aloise et al)
- ./syntnets/  - synthetic networks produced by the extended LFR framework: undirected weighted complex networks with overlaps, both mixing parameters are set for the topology and weights, both exponential nodes degree and weights distributions are set
	* `*.ngp`  - network generation parameters
	* `time_seed.dat`  - used time seed on batch generation
	* `*.ngs`  - time seed for the network (**n**etwork **g**eneration **s**eed)
	* `*.nst`  - statistics for the generated network (**n**etwork **st**atistics)
	* `*.nsa`  - generated network to be processed as input graph by the algorithms to build the community structure. The **n**etwork is specified by newline / space/tab **s**eparated **a**rcs as a list of lines: `<src_id> <dst_id> [<weight>]`
	* `*.cnl`  - ground truth for the community structure (cluster/**c**ommunity **n**odes **l**ist) generated by the LFR framework. It is specified by the space/tab separated nodes for each cluster (a line in the file): `<c1_nid_1> <c1_nid_2> ...`
- `./exectime`  - lightweight resource consumption [profiler](https://bitbucket.org/lumais/exectime/)
- `./benchmark.py`  - the benchmark (interactive mode)
- `./benchmark_daemon.sh`  - the shell script to execute the benchmark in background (daemon mode)
- `./install_depends.sh`  - the shell script to install dependencies


## Extension
To add custom apps / algorithms to be benchmarked just add corresponding function for "myalgorithm" app to `benchapps.py`:

```python
def execMyalgorithm(execpool, netfile, asym, timeout, pathid='', selfexec=False)`
	"""Execute the algorithm (stub)

	execpool  - execution pool to perform execution of current task
	netfile  -  input network to be processed
	asym  - network links weights are assymetric (in/outbound weights can be different)
	timeout  - execution timeout for this task
	pathid  - path id of the net to distinguish nets with the same name located in different dirs.
		Note: pathid is prepended with the separator symbol
	selfexec  - current execution is the external or internal self call

	return  - number of executions (jobs) made
	"""
```

All the evaluatoins will be performed automatically, the algorithm should just follow convension of the execution results output.


## Related Projects
* [HiReCS](https://github.com/XI-lab/hirecs) - High Resolution Hierarchical Clustering with Stable State: https://github.com/XI-lab/hirecs

If you are interested in this benchmark, please visit <a href="http://exascale.info/">eXascale Infolab</a> where you can find another projects and research papers related to Big Data!
