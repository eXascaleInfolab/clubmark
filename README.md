# HiCBeM - Generic Benchmarking Framework with customization for the evaluation of <br />Hierarchical Overlapping Clustering Algorithms
\author: (c) [Artem Lutov](artem@exascale.info)  
\organizations: [eXascale Infolab](http://exascale.info/), [Lumais](http://www.lumais.com/), [ScienceWise](http://sciencewise.info/)  
\keywords: overlapping clustering benchmarking, community detection benchmarking, algorithms benchmarking framework

## Content
[Functionality](#functionality)  
[Dependencies](#dependencies)  
[Usage](#usage)  
[Benchmark Structure](#benchmark-structure)  
[Extension](#extension)  
[Related Projects](#related-projects)  

## Functionality
### Generic Benchmarking Framework
- optionally generates or preprocesses datasets using specified executable(s)
- optionally executes specified apps with the specified params on the specified datasets
- optionally evaluates results of the execution using specified executable(s)
	
All executions (stdout/err output) are logged also as resources consumption: CPU (user, kernel, etc.) and memory (RAM RSS).
Logs are saved even in case of internal / external interruptions and crashes.

### Hierarchical Overlapping Clustering Benchmark
The benchmark is implemented as customization of the Generic Benchmarking Framework to evaluate *Hierarchical Overlapping  Clustering Algorithms*, which:
- produces synthetic datasets, generating them by the extended [LFR Framework](https://sites.google.com/site/santofortunato/inthepress2) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti and Santo Fortunato)
- executes
	* [HiReCS](http://www.lumais.com/hirecs) (www.lumais.com/hirecs),
	* [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations),
	* [Oslom2](http://www.oslom.org/software.htm)
	* [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/) (but *this algorithm is not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only"*)
	* [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) ([Sequential algorithm for fast clique percolation](http://www.lce.hut.fi/research/mm/complex/software/))

	clustering algorithms on the generated synthetic networks. Output results (clusters, hierarchy, modularty, etc.) of the clustering algorithms are stored in the corresponding files.
- evaluates results using NMI for overlapping communities, extended versions (to have uniform input / output formats) of:
  * gecmi (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
  * onmi (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms" by Aaron F. McDaid, Derek Greene, Neil Hurley)
- resources consumption is evaluated using exectime profiler (https://bitbucket.org/lumais/exectime/)
- modularity of the clustering (compatible to the standard modularity value, but applicable for overlapping clusters) is evaluated by HiReCS (http://www.lumais.com/hirecs)

All results and traces are stored into the corresponding files even in case of internal (crash) / external termination of the benchmarking applications or the whole framework.

 > Note: valuable extensions of the employed external applications are uploaded into ./3dparty/

Basically the framework executes a set of algorithms on the specified datasets in interactive or daemon mode, logging the resources consumption, output and exceptions, providing workflow management (termination by timeout, resistance to exceptions, etc.).

## Dependencies
### Fundamental
* Python (or [pypy](http://pypy.org/) for the fast execution)

### Libraries
* [hirecs](http://www.lumais.com/hirecs/) for modularity evaluation of overlapping community structure with results compatible to the standard modularity
* [python-igraph](http://igraph.org/python/) for Louvain algorithm evaluation by NMIs (because the original implementation does not provide convenient output of the communities to evaluate NMIs): `$ pip install python-igraph`  

> Note:
- `hirecs` depends on libstdc++.so.6: version GLIBCXX_3.4.20 (precompiled version for modularity evaluation). To install it on Ubuntu use: `sudo apt-get install libstdc++6` or
```sh
$ sudo add-apt-repository ppa:ubuntu-toolchain-r/test 
$ sudo apt-get update
$ sudo apt-get install libstdc++6
```

- `python-igraph` depends on `libz` and `libxml2`, which are installed in Linux Ubuntu executing:  
`$ sudo apt-get install lib32z1-dev libxml2-dev`
- `gecmi`, which is used for the NMI_ovp evaluation depends on:
	* `libboost_program_options.so.1.54.0`, to install execute: `$ sudo apt-get install libboost-program-options1.54.0`
	* `libtbb.so.2`, to install execute: `sudo aptitude download libtbb2; sudo aptitude install libtbb2`
>	
>	This dependencies are uploaded to `./algorithms/gecmi_deps/`.

### External tools that are used as executables
- [Extended LFR Benchmark](3dparty/lfrbench_weight-undir-ovp) for the undirected weighted networks with overlaps (origins are here: https://sites.google.com/site/santofortunato/inthepress2, https://sites.google.com/site/andrealancichinetti/files)
- [Tiny execution profiler](https://bitbucket.org/lumais/exectime/) to evaluate resources consumption: https://bitbucket.org/lumais/exectime/
- Clustering algorithms, used in the benchmarking: [HiReCS](http://www.lumais.com/hirecs), [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm) and [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/)
 
## Usage
- `./install_depends.sh`  - install dependencies
- `./benchmark.py`  - run the benchmark in the terminal (interactive mode)
- `./benchmark_daemon.sh`  - run the benchmark in background (daemon mode)

> Note: Execution of the benchmark was verified only on Linux Ubuntu 14.04 x64, but it should work on any platform if corresponding external executables (algorithms, nmi evaluation apps, etc.) are provided for the required platforms.

To see possible input parameters just run the benchmark without the arguments: `$ ./benchmark.py`.

## Benchmark Structure
- ./3dparty/  - contains valuable patches to the external open source tools used as binaries
- ./algorithms/  - contains benchmarking algorithms
	* ./algorithms/<algname>outp/  - results of the algorithm evaluation:
		- `*.log`  - `stdout` of the executed algorithm
		- `*.err`  -  `stderr` of the executed algorithm and benchmarking routings
		- `*.cnl`  - resulting clusters unwrapped to nodes (community nodes list) for NMIs evaluation. `*.cnl` are generated either per each level of the resulting hierarchy of communities or for the whole hierarchy (parameterized inside the benchmark)
	* `<algname>.rcp`  - resource consumption profile for all executions of the algorithm even in case of crashes / interruptions.
	* `<algname>.nmi[-s]`  - best NMI value considering overlapping communities produced by gecmi [onmi] app (cf. above). 

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

- ./smallnets/  - simple gold standard networks with available ground truth value of the modularity for non-overlapping clustering (from [DIMACS 10th](http://www.cc.gatech.edu/dimacs10/), "Modularity Maximization in Networks by Variable Neighborhood Search" by Daniel Aloise et al)
- ./syntnets/  - synthetic networks produced by the extended LFR framework: undirected weighted complex networks with overlaps, both mixing parameters are set for the topology and weights, both exponential nodes degree and weights distributions are set
	* `*.ngp`  - network generation parameters
	* `time_seed.dat`  - used time seed on batch generation
	* `*.ngs`  - time seed for the network
	* `*.nst`  - statistics for the generated network
	* `*.nsa`  - generated network to be processed as input graph by the algorithms to build the community structure. The *n*etwork is specified by space/tab **s**eparated **a**rcs
	* `*.cnl`  - ground truth for the community structure (community nodes list) generated by the LFR framework. It is specified by the space/tab separated nodes for each cluster (a line in the file)
- `./exectime`  - lightweight resource consumption [profiler](https://bitbucket.org/lumais/exectime/)
- `./benchmark.py`  - the benchmark (interactive mode)
- `./benchmark_daemon.sh`  - the shell script to execute the benchmark in background (daemon mode)
- `./install_depends.sh`  - the shell script to install dependencies


## Extension
To add own apps / algorithms to be benchmarked just add corresponding functions for "myalgorithm" app:
- `def execMyalgorithm(execpool, netfile, timeout, selfexec=False)`  - to execute the algorihm for the network
- `def evalMyalgorithm(execpool, cnlfile, timeout)`  - to evaluate accuracy of the custering results (community structure) comparing to the specified ground truth using NMIs measures
- `def modMyalgorithm(execpool, netfile, timeout)`  - to evaluate quality of the clsutering results (community structure) by the standard modularity measure (applicable for overlapping clusters)

into the `benchapps.py`.


## Related Projects
* [HiReCS](https://github.com/XI-lab/hirecs) - High Resolution Hierarchical Clustering with Stable State: https://github.com/XI-lab/hirecs

If you are interested in this benchmark, please visit <a href="http://exascale.info/">eXascale Infolab</a> where you can find another projects and research papers related to Big Data!
