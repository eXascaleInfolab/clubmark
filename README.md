# PyCABeM (former HiCBeM) - Python Benchmarking Framework for the Clustering Algorithms Evaluation
\brief Uses extrinsic (NMIs - normalized [mutual information](https://en.wikipedia.org/wiki/Mutual_information) for overlapping clusters) and intrinsic (Q - [modularity](https://en.wikipedia.org/wiki/Modularity_(networks))) measures for the clusters quality evaluation considering overlaps (nodes membership by multiple clusters)  
\author: (c) Artem Lutov <artem@exascale.info>  
\organizations: [eXascale Infolab](http://exascale.info/), [Lumais](http://www.lumais.com/), [ScienceWise](http://sciencewise.info/)  
\keywords: overlapping clustering benchmarking, community detection benchmarking, algorithms benchmarking framework.

Author (c)  Artem Lutov <artem@exascale.info>

## Content
- [Functionality](#functionality)
  - [Generic Benchmarking Framework](#generic-benchmarking-framework)
  - [Clustering Algorithms Benchmark](#clustering-algorithms-benchmark)
- [Prerequisites](#prerequisites)
- [Dependencies](#dependencies)
  - [Overview](#overview)
  - [Docker Container](#docker-container)
  - [Direct Execution](#direct-execution)
    - [Libraries](#libraries)
    - [Accessory Utilities](#accessory-utilities)
- [Usage](#usage)  
  - [Usage Examples](#usage-examples)  
- [Benchmark Structure](#benchmark-structure)  
- [Benchmark Extension](#benchmark-extension)  
- [Related Projects](#related-projects)  


## Functionality
### Generic Benchmarking Framework
- optionally *generates or preprocesses datasets* using specified executable(s) (by default uses LFR framework for overlapping weighted networks)
- optionally *executes specified apps* (clustering algorithms; can be a binary, any script or java executable) with the specified params on the specified datasets (networks)
- optionally *evaluates results* of the execution using specified executable(s) (by default performs NMIs and Q evaluation) and *performs unified aggregation* of results from multiple apps on multiple datasets into the single file by the specified measure
- *per-task and global timeouts* (for an app execution on a single dataset) and specified number of CPU cores (workers) are set for the *batch apps execution / evaluation* using the multi-process task execution pool ([mpepool](https://github.com/eXascaleInfolab/PyExPool))
- per-task and accumulative *execution tracing and results logging* is performed even in case of internal / external interruptions and crashes:
	* all stdout/err output is logged
	* resources consumption, i. e. time: execution (wall-clock) and CPU consumption (user, kernel, total), memory (RAM RSS) are traced
- *automatic extension / backup* of the previously existent results to .gzip with the timestamp on the benchmarking reexecution

It is possible to have multiple input directories with similarly named files inside, which represent different instances / snapshots of the datasets. In such case, the output results are provided per each snapshot, plus aggregated weighted average over all snapshots. This is useful to avoid occasional bias to the specific instance or to analyze evolving networks.

In case of the measured application crash, the crash is logged and has no any impact on the execution of the remaining applications.


### Clustering Algorithms Benchmark
The benchmark is implemented as customization of the Generic Benchmarking Framework to evaluate *Hierarchical Overlapping  Clustering Algorithms*:
- produces synthetic networks with specified number of instances for each set of parameters, generating them by the extended [LFR Framework](https://github.com/eXascaleInfolab/LFR-Benchmark_UndirWeightOvp) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti and Santo Fortunato)
- shuffles (reorders nodes) specified networks specified number of times, which is required to evaluate stability / determinism of the clustering algorithms
- executes
	* DAOC (former [HiReCS](http://www.lumais.com/hirecs), www.lumais.com/hirecs)
	* [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) ([Sequential algorithm for fast clique percolation](http://www.lce.hut.fi/research/mm/complex/software/))
	* [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations)
	* [Oslom2](http://www.oslom.org/software.htm)
	* [GANXiS/SLPA](https://sites.google.com/site/communitydetectionslpa/) (but *this algorithm is not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only"*; *deterministic algorithm LabelRankT* is a modification of GANXiS, but LabelRankT is not publicly available)  
	  > GANXiS requires preliminary created output directory if it is specified in the options, but GANXiS always creates also default "./output/" directory, which is empty if the custom one is used.
	* [Randcommuns](/algorithms/randcommuns.py)  - generation of random communities (clusters) with structure of clusters similar to the ground-truth: the same number of random connected nodes in the number of clusters taken from the ground-truth

	clustering algorithms on the generated synthetic networks (or on any specified directories and files). Outputs results (clusters/communities structure, hierarchy, modularity, nmi, etc.) of the clustering algorithms are stored in the corresponding files.

	Features \ Algs | *DAOC* | SCP | Louvain | Oslom2 | GANXiS | pSCAN | CGGCi_RG
	            --- | --- | --- | --- | --- | --- | --- | ---
	Hierarchical    | + | | + | + | | | |
	Multi-scale     | + | + | + | + | + | | |
	Deterministic   | + | + | | | | ? | |
	With Overlaps   | + | + | | + | + | + | * |
	Parameter-Free  | + | | + | * | * |  | *
	Consensus/Ensemble | + | | | + | | | +

> *With Overlaps* marked with `*` means non-overlapping clusters as a result, but the algorithm can be modified to output overlapping clusters.  
*Parameter-Free* marked with `*` means availability of default values for all parameters.

- evaluates results using:
	- extrinsic measures :
		* F1_gwah for overlapping communities on multiple resolutions and standard NMI for hard partitioning only (non-overlapping singe resolution clustering)  - `xmeasures` (https://github.com/eXascaleInfolab/xmeasures)
		* NMI (NMI_max compatile with the standard NMI)  - `gecmi` (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
		* NMIs (NMI_max, NMI_lfr, NMI_avg)  - `onmi` (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms" by Aaron F. McDaid, Derek Greene, Neil Hurley)
	- intrinsic measures evaluated by `DAOC`:
	  * Q (standard modularity value, but applicable for overlapping communities)
		* f (conductance applicable for overlapping communities)
- resulting clusterings on multiple resolutions are merged using `resmerge` (https://github.com/eXascaleInfolab/resmerge) with node base synchronization to the ground truth communities on Large real-world networks from [SNAP](https://snap.stanford.edu/data/#communities), which have less nodes in the ground-truth communities than in the input networks and clusters on multiple resolutions in the single ground-truth collection
- resources consumption is evaluated using `exectime` profiler (https://bitbucket.org/lumais/exectime/)

All results and traces are stored into the corresponding files even in case of internal (crash) / external termination of the benchmarking applications or the whole framework.

 > Note: valuable extensions of the employed external applications are uploaded into ./contrib/

Basically the framework executes a set of applications on the specified datasets in interactive or daemon mode, logging the resources consumption, output and exceptions, providing workflow management (termination by timeout, resistance to exceptions, etc.) and results aggregation.


## Prerequisites
Operational System Environment
Be sure that the operational system allows to work with lots of opened files and have adequate swapping policy.

> Even when run under **Docker**, the Docker uses kernel, memory and swap of the host.
So system-wide host swappiness, file limits, etc. should be tuned.

- Max number of the opened files in the system`$ sysctl fs.file-max` should be large enough, the recommended value is `1048576`.
- Max number of the opened files per a process`$ ulimit -n` should be at least `4096`, may be higher depending on the evaluating datasets and algorithms. The recommended value is `65536`.

To setup `fs.file-max` permanently in the system add the following line to the `/etc/sysctl.conf`:
```
fs.file-max = 1048576
```
and then reload it by `# sysctl -p`.  
To setup the `ulimit` permanently add the following lines to the `/etc/security/limits.conf`:
```
*               hard    nofile          524288
*               soft    nofile          4096  
```
And then execute `ulimit -n 65536` to set this value for the current process.

Typically the benchmarking is expected to be executed in the RAM, so reduce the system swappiness setting it to 1 .. 10:
`sysctl -w vm.swappiness=10` or setting it permanently in `/etc/sysctl.conf`:
```
vm.swappiness = 10
``` 


## Dependencies
### Overview
There are some prerequisites related to the Operational System Environment, dependencies for the benchmarking itself and for each of the executing algorithms. Target OS is Ubuntu 16.04 x64, other OSes also can be used to run the benchmark itself, but there might be issues with the evaluation algorithms and evaluation utilities builds.

> Use Docker image where all dependencies are already satisfied


### Docker Container
On Linux Ubuntu 16.04 the Docker can be installed:
```
$ sudo apt-get update && apt-get upgrade
$ sudo apt-get install -y docker.io
```
See the [official site for the installation](https://docs.docker.com/engine/installation/) details on another platforms.
To start docker on Linux
```
$ sudo systemctl start docker
$ docker version
```
See also the [brief tutorial on Docker installation and usage](https://www.howtoforge.com/tutorial/docker-installation-and-usage-on-ubuntu-16.04/) or the [official getting started tutorial](https://docs.docker.com/get-started/).

To build the `PyCaBeM` Docker image from the source file:
```
$ docker build -t luaxi/pycabem:env-U16.04-v2.0 .
```
Alternatively the prebuilt image can be downloaded:
```
$ docker pull luaxi/pycabem:env-U16.04-v2.0
```

To run the benchmark:
```
$ docker run -it -u $UID -v `pwd`:/opt/benchmark luaxi/pycabem:env-U16.04-v2.0 [<pycabem_args>]
'''
Or to open "bash" shell in the benchmarking directory:
'''
$ docker run -it --entrypoint bash -u $UID -v `pwd`:/opt/benchmark luaxi/pycabem:env-U16.04-v2.0 ls
```
Where ``pwd`` projects to `<PYCABEM_REPOSITORY_PATH>`, which is the current directory and working directory of the benchmarking

See also [Docker cheat sheet](https://coderwall.com/p/2es5jw/docker-cheat-sheet-with-examples).

### Direct Execution

- Python 2.7+ (optionally [PyPy](http://pypy.org/) JIT for the fast execution).

> Note: It is recommended to run the benchmark itself under PyPy. The measured algorithms can be ran either using the same python or under the dedicated interpreter / script / executable.


#### Libraries
Full list of dependencies for execution:
- Required for the clustering algorithms:
  - GANXiS:
  `$ sudo apt-get install openjdk-8-jre`

  - ...
  pypy

- Required for the evaluation applications:
  - gecmi:
  `$ sudo sudo apt-get install libboost-program-options1.58.0 libtbb2`

Full list of dependencies for build and execution:
  - Required for the clustering algorithms:
    - GANXiS:
    `$ sudo apt-get install openjdk-8-jdk`

  - Required for the evaluation applications:
    - gecmi:
    `$ sudo sudo apt-get install libboost-program-options1.58-dev libtbb-dev`

  - Required for the debugging:
    `$ sudo apt install gdb`


- daoc (former [hirecs](http://www.lumais.com/hirecs/)) for modularity evaluation of overlapping community structure with results compatible to the standard modularity value. It depends on:
  * `libstdc++.so.6`: version GLIBCXX_3.4.20 (precompiled version for modularity evaluation). To install it on Ubuntu use: `sudo apt-get install libstdc++6` or
```sh
$ sudo add-apt-repository ppa:ubuntu-toolchain-r/test
$ sudo apt-get update
$ sudo apt-get install libstdc++6
```

- [python-igraph](http://igraph.org/python/) for Louvain algorithm evaluation by NMIs (because the original implementation does not provide convenient output of the communities to evaluate NMIs): `$ pip install python-igraph`. It depends on:
	* `libxml2` (and `libz` on Ubuntu 14), which are installed in Linux Ubuntu executing:  
	`$ sudo apt-get install libxml2-dev`  (`lib32z1-dev` might be also required)

- [`gecmi`](https://bitbucket.org/dsign/gecmi/wiki/Home) for the NMI_ovp evaluation depends on:
	* `libboost_program_options`, to install execute: `$ sudo apt-get install libboost-program-options`. The older version of gecmi compiled under Ubuntu 14 depends on `libboost_program_options.so.1.54.0`, the newer one compiled under Ubuntu 16 depends on `libboost_program_options.so.1.58.0`.
	* `libtbb.so.2`, to install execute: `sudo aptitude download libtbb2; sudo aptitude install libtbb2`

  > Note: gecmi dependencies are uploaded to `./algorithms/gecmi_deps/`.

- [PyExPool](//github.com/eXascaleInfolab/PyExPool) for asynchronous jobs execution and results aggregation via tasks of jobs

  > Note: it is uploaded to `./contrib/`.


#### Accessory Utilities
- [Extended LFR Benchmark](https://github.com/eXascaleInfolab/LFR-Benchmark_UndirWeightOvp) for the undirected weighted networks with overlaps (origins are here: https://sites.google.com/site/santofortunato/inthepress2, https://sites.google.com/site/andrealancichinetti/files)
- [Tiny execution profiler](https://bitbucket.org/lumais/exectime/) to evaluate resources consumption: https://bitbucket.org/lumais/exectime/
- Clustering algorithms, used in the benchmarking: DAOC (former [HiReCS](http://www.lumais.com/hirecs)), [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm), [GANXiS/SLPA](https://sites.google.com/site/communitydetectionslpa/), pScan (binaries provided by the [author](http://www.cse.unsw.edu.au/~ljchang/)) and [CGGCi_RG](https://github.com/eXascaleInfolab/CGGC).


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
  -a="app1 app2 ..."  - apps (clustering algorithms) to run/benchmark among the implemented. Available: scp louvain_igraph randcommuns daoc oslom2 ganxis. Impacts {r, e} options. Optional, all apps are executed by default.
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


### Synthetic networks generation, clustering algorithms execution and evaluation
```
$ pypy ./benchmark.py -g=3.2=syntnets_i3_s4 -cr -a="scp oslom2" -r -emn -tm=90
```
Run the benchmark under PyPy.  
Generate synthetic networks producing 3 instances of each network with 2 shuffles (random reordering of network nodes) of each instance, having 3*2=6 sythetic networks of each type (for each set of network generation parameters). Generated networks are stored in the ./syntnets_i3_s4/ directory.  
Convert all networks into the .hig format resolving duзlicated links. This conversion is required to be able to evaluate modularity measure.  
Run `scp` and `oslom2` clustering algorithms for each generated network and evaluate modularity and NMI measures for these algorithms.  
Tшmeout is 90 min for each task of each network processing, where the tasks are: networks generation, clustering and evaluation by each specified measure. The network is each shuffle of each instance of each network type.  

### Shuffling existing network instances, clustering algorithm execution and evaluation
```
$ ./benchmark.py -g=.4 -d=syntnets_i3_s4 -a=oslom2 -es -th=1
```
Run the benchmark for the networks located in ./syntnets_i3_s4/ directory.  
Produce 4 shuffles of the specified networks, previously existed shuffles are backed up.  
Run `oslom2` clusterшng algorithm for the specified networks with their shuffles and evaluate NMI_s measure.  
Timeout is 1 hour for each task on each network.  

### Aggregation of the specified evaluation results
```
$ pypy benchmark.py -s=results/scp/mod/*.mod
```
Results aggregation is performed with automatic identification of the target clustering algorithm and evaluation measure by the specified path. It is performed automatically as the last step of the algorithm evaluation, but also can be called manually for the modified scope.

## Benchmark Structure
- ./contrib/  - valuable patches to the external open source tools used as binaries
- ./algorithms/  - benchmarking algorithms
- ./resutls/  - aggregated and per-algorithm execution and evaluation results (brief `*.res` and extended `*.resx`): timings (execution and CPU), memory consumption, NMIs, Q, per-algorithm resources consumption profile (`*.rcp`)
	- `<algname>.rcp`  - resource consumption profile for all executions of the algorithm even in case of crashes / interruptions
	- `<measure>.res[x]`  - aggregated value of the measure: average is evaluated for each level / scale for all shuffles of the each network instance, then the weighted best average among all levels is taken for all instances as a final result
	* <algname>/clusters/  - algorithm execution results produced hierarchies of communities for each network instance shuffle
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

- ./realnets/  - simple gold standard networks with available ground-truth
	- dimacs/  - [10th DIMACS'13](http://www.cc.gatech.edu/dimacs10/) networks with the ground-truth modularity value for non-overlapping clustering (see "Modularity Maximization in Networks by Variable Neighborhood Search" by Daniel Aloise et al, 10th DIMACS'13)
	- snap/  - Stanford SNAP large networks with available ground-truth communities (see "Defining and Evaluating Network Communities based on Ground-truth" by J. Yang and J. Leskovec., ICDM'12)
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


## Benchmark Extension
To add custom apps / algorithms to be benchmarked just add corresponding function for "myalgorithm" app to `benchapps.py`:

```python
def execMyalgorithm(execpool, netfile, asym, timeout, pathid='', selfexec=False)
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

All the evaluations will be performed automatically, the algorithm should just follow conversion of the execution results output.


## Related Projects
* DAOC - (former [HiReCS](https://github.com/eXascaleInfolab/hirecs) High Resolution Hierarchical Clustering with Stable State, which was totally redesigned: https://github.com/eXascaleInfolab/hirecs)

If you are interested in this benchmark, please visit <a href="http://exascale.info/">eXascale Infolab</a> where you can find another projects and research papers related to Big Data!  
Please, [star this project](https://github.com/eXascaleInfolab/PyCABeM) if you use it.
