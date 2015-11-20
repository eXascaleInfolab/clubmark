# PyCABeM (former HiCBeM) - Python Benchmarking Framework for the Clustering Algorithms Evaluation
\brief Uses extrinsic (NMIs) and intrinsic (Q) measures for the clusters quality evaluation considering overlaps (nodes membership in multiple clusters)  
\author: (c) [Artem Lutov](artem@exascale.info)  
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
- optionally generates or preprocesses datasets using specified executable(s) (by default uses LFR framework for overlapping weightted networks)
- optionally executes specified apps (clustering algorithms; can be a binary, any script or java executable) with the specified params on the specified datasets (networks, graphs)
- optionally evaluates results of the execution using specified executable(s) (by default performs NMIs and Q evaluation)
- batch apps execution / evaluation is performed with per-task timeout (for an app execution on a single dataset) using specified number of CPU cores (workers) for the task pool
- per-task and accumulative execution tracing and resutls logging is performed even in case of internal / external interruptions and crashes:
  * all stdout/err output is logged
  * resources consumption: CPU (user, kernel, etc.) and memory (RAM RSS) is traced


### Hierarchical Overlapping Clustering Benchmark
The benchmark is implemented as customization of the Generic Benchmarking Framework to evaluate *Hierarchical Overlapping  Clustering Algorithms*, which:
- produces synthetic datasets, generating them by the extended [LFR Framework](https://sites.google.com/site/santofortunato/inthepress2) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti and Santo Fortunato)
- executes
	* [HiReCS](http://www.lumais.com/hirecs) (www.lumais.com/hirecs)
	* [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) ([Sequential algorithm for fast clique percolation](http://www.lce.hut.fi/research/mm/complex/software/))
	* [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations)
	* [Oslom2](http://www.oslom.org/software.htm)
	* [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/) (but *this algorithm is not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only"*; *deterministic algorithm LabelRankT* is a modification of GANXiS, but LabelRankT is not publicly available)

	clustering algorithms on the generated synthetic networks (or on any specified directories and files). Output results (clusters/communities structure, hierarchy, modularity, nmi, etc.) of the clustering algorithms are stored in the corresponding files.
	
	Features \ Algs | *HiReCS* | SCP | Louvain | Oslom2 | GANXiS
	            --- | --- | --- | --- | --- | ---
	Hierarchical    | + | + | + | + |
	Multi-scale     | + | + | + | + | + 
	Deterministic   | + | + | | | 
	With Overlaps   | + | + | | + | +
	Parameter-Free  | + | | + | | 

- evaluates results using NMI for overlapping communities, extended versions (to have uniform input / output formats) of:
  * `gecmi` (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
  * `onmi` (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms" by Aaron F. McDaid, Derek Greene, Neil Hurley)
- resources consumption is evaluated using `exectime` profiler (https://bitbucket.org/lumais/exectime/)
- modularity of the clustering (compatible to the standard modularity value, but applicable for overlapping clusters) is evaluated by `HiReCS` (http://www.lumais.com/hirecs)

All results and traces are stored into the corresponding files even in case of internal (crash) / external termination of the benchmarking applications or the whole framework.

 > Note: valuable extensions of the employed external applications are uploaded into ./3dparty/

Basically the framework executes a set of algorithms on the specified datasets in interactive or daemon mode, logging the resources consumption, output and exceptions, providing workflow management (termination by timeout, resistance to exceptions, etc.).


## Dependencies
### Fundamental
- Python (or [pypy](http://pypy.org/) for the fast execution)

### Libraries
- [hirecs](http://www.lumais.com/hirecs/) for modularity evaluation of overlapping community structure with results compatible to the standard modularity. It depends on:
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

- `gecmi`, which is used for the NMI_ovp evaluation depends on:
	* `libboost_program_options.so.1.54.0`, to install execute: `$ sudo apt-get install libboost-program-options1.54.0`
	* `libtbb.so.2`, to install execute: `sudo aptitude download libtbb2; sudo aptitude install libtbb2`
	
  > Note: This dependencies are uploaded to `./algorithms/gecmi_deps/`.


### External tools that are used as executables
- [Extended LFR Benchmark](3dparty/lfrbench_weight-undir-ovp) for the undirected weighted networks with overlaps (origins are here: https://sites.google.com/site/santofortunato/inthepress2, https://sites.google.com/site/andrealancichinetti/files)
- [Tiny execution profiler](https://bitbucket.org/lumais/exectime/) to evaluate resources consumption: https://bitbucket.org/lumais/exectime/
- Clustering algorithms, used in the benchmarking: [HiReCS](http://www.lumais.com/hirecs) [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations) [Oslom2](http://www.oslom.org/software.htm) and [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/)
 
## Usage
- `./install_depends.sh`  - install dependencies (using apt-get)
- `./benchmark.py`  - run the benchmark in the terminal (interactive mode)
- `./benchmark_daemon.sh`  - run the benchmark in background (daemon mode)

> Note: Execution of the benchmark was verified only on Linux Ubuntu 14.04 x64, but it should work on any platform if corresponding external executables (algorithms, nmi evaluation apps, etc.) are provided for the required platforms.

To see possible input parameters run the benchmark without arguments: `$ ./benchmark.py`.  
For the version from 20015-11-20 the output is:
```
$ ./benchmark.py 
Usage: ./benchmark.py [-g[f] [-c[f][r]] [-r] [-e[n][m]] [-d{a,s}=<datasets_dir>] [-f{a,s}=<dataset>] [-t[{s,m,h}]=<timeout>]
  -g[f]  - generate synthetic datasets in the syntnets/
    Xf  - force the generation even when the data already exists
  -a[="app1 app2 ..."]  - apps (clusering algorithms) to benchmark among the implemented. Available: scp louvain_ig randcommuns hirecs oslom2 ganxis Impacts -{c, r, e} options. Optional, all apps are executed by default
  -c[X]  - convert existing networks into the .hig, .lig, etc. formats
    Xf  - force the conversion even when the data is already exist
    Xr  - resolve (remove) duplicated links on conversion. Note: this option is recommended to be used
  -r  - run the benchmarking apps on the prepared data
  -e[X]  - evaluate quality of the results. Default: apply all measurements
    Xn  - evaluate results accuracy using NMI measures for overlapping communities
    Xm  - evaluate results quality by modularity
  -d[X]=<datasets_dir>  - directory of the datasets
  -f[X]=<dataset>  - dataset (network, graph) file name
    Xa  - the dataset is specified by asymmetric links (in/outbound weights of the link migh differ), arcs
    Xs  - the dataset is specified by symmetric links, edges. Default option
    Notes:
    - multiple directories and files can be specified via multiple -d/f options (one per the item)
    - datasets should have the following format: <node_src> <node_dest> [<weight>]
    - {a, s} is considered only if the network file has no corresponding metadata (formats like SNAP, ncol, nsa, ...)
    - ambiguity of links weight resolution in case of duplicates (or edges specified in both directions) is up to the clustering algorithm
  -t[X]=<number>  - specifies timeout for each benchmarking application per single evalution on each network in sec, min or hours. Default: 0 sec  - no timeout
    Xs  - time in seconds. Default option
    Xm  - time in minutes
    Xh  - time in hours
```

## Benchmark Structure
- ./3dparty/  - contains valuable patches to the external open source tools used as binaries
- ./algorithms/  - contains benchmarking algorithms
	* ./algorithms/<algname>outp/  - detailed results of the algorithm evaluation:
		- `*.log`  - `stdout` of the executed algorithm
		- `*.err`  -  `stderr` of the executed algorithm and benchmarking routings
		- `*.cnl`  - resulting clusters unwrapped to nodes (community nodes list) for NMIs evaluation. `*.cnl` are generated either per each level of the resulting hierarchy of communities or for the whole hierarchy (parameterized inside the benchmark)
		- `*.mod`  - resulting modularity value pear each hierarchical/scale level of each network
	* ./algorithms/results/  - final accumulated results of the algorithm evaluation (previously located in ./algorithms/):
		- `<algname>.rcp`  - resource consumption profile for all executions of the algorithm even in case of crashes / interruptions
		- `<algname>.nmi[-s]`  - best NMI value for each network considering overlapping communities (and compatble with standard NMI), evaluated by `gecmi` and `onmi` (cf. above)
		- `<algname>.mod`  - best Q (modularity) value for each network considering overlapping communities (and compatible with standard modularity value), evaluated by `hirecs` (in special evaluation mode without the clustering)

Example of the `.rcp` format:
```
# ExecTime(sec)	CPU_time(sec)	CPU_usr(sec)	CPU_kern(sec)	RSS_RAM_peak(Mb)	TaskName
2.575555	2.574302	2.540420	0.033882	6.082	5K5
0.528582	0.528704	0.519277	0.009427	3.711	2K10
...
```

Example of the `.nmi[-s]` format:
```
# TaskName	NMI
5K20	0.874124
2K20	0.887181
...
```

Example of the `.mod` format:
```
# Network	Q
xlet	 0.224837
bamp	 0.528431
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
To add own apps / algorithms to be benchmarked just add corresponding functions for "myalgorithm" app:
- `def execMyalgorithm(execpool, netfile, asym, timeout, selfexec=False)`  - to execute the algorithm for the network
- `def evalMyalgorithm(execpool, cnlfile, timeout)`  - to evaluate accuracy of the clustering results (community structure) comparing to the specified ground truth using NMIs measures

  > Note: default implementation is provided and should be called for NMIs evaluation.

- `def modMyalgorithm(execpool, netfile, timeout)`  - to evaluate quality of the clustering results (community structure) by the standard modularity measure (applicable for overlapping clusters)  

  > Note: default implementation is provided and should be called.

into the `benchapps.py`.


## Related Projects
* [HiReCS](https://github.com/XI-lab/hirecs) - High Resolution Hierarchical Clustering with Stable State: https://github.com/XI-lab/hirecs

If you are interested in this benchmark, please visit <a href="http://exascale.info/">eXascale Infolab</a> where you can find another projects and research papers related to Big Data!
