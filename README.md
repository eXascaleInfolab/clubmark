# HiCBeM - Generic Benchmarking Framework with customization for the evaluation of <br />Hierarchical Clustering Algorithms with Overlaps
\author: (c) [Artem Lutov](artem@exascale.info)  
\organizations: [eXascale Infolab](http://exascale.info/), [Lumais](http://www.lumais.com/), [ScienceWise](http://sciencewise.info/)  

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
	
All executions are traced and logged also as resources consumption: CPU (user, kernel, etc.) and memory (RAM RSS).
Traces are saved even in case of internal / external interruptions and crashes.

### Overlapping Hierarhical Clusterig Benchmark
The benchmark is implemented as customization of the Generic Benchmarking Framework with:
- synthetic datasets are generated using extended [LFR Framework](https://sites.google.com/site/santofortunato/inthepress2) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti and Santo Fortunato)
- executes [HiReCS](http://www.lumais.com/hirecs) (www.lumais.com/hirecs), [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm) and [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/) (but this algorithm is not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only") clustering algorithms on the generated synthetic networks. Output results of the clustering algorithms (clsuters, hierarchy, modularty, etc.) are stored into the corresponding files.
- evaluates results using NMI for overlapping communities, extended versions of:
  * gecmi (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
  * onmi (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms" by Aaron F. McDaid, Derek Greene, Neil Hurley)
- resources consumption is evaluated using exectime profiler (https://bitbucket.org/lumais/exectime/)

All results and traces are stored into the corresponding files even in case of internal (crash) / external termination of the benchmarking application or framework.

*Note: valuable extensions of the employed external applications are uploaded into ./3dparty/*

Basically the framework executes a set of algorithms on the specified datasets in interactive or daemon mode logging the resources consumption, output, exception and providing workflow management (termination by timeout, resistance to exceptions, etc.).

## Dependencies
### Fundamental
* Python (or [pypy](http://pypy.org/) for fast execution)

### Libraries

* [python-igraph](http://igraph.org/python/) for Louvain algorithm evaluation by NMIs (because the original implementation does not provide convenient output of the communities to evaluate NMIs): `$ pip install python-igraph`  
*Note: `python-igraph` depends on `libz` and `libxml2`, which are installed on Linux Ubuntu in a such way: `$ sudo apt-get install lib32z1-dev libxml2-dev`*

### External tools that are used as executables
* [Extended LFR Benchmark](3dparty/lfrbench_weight-undir-ovp) for undirected weighted networks with overlaps, origins: https://sites.google.com/site/santofortunato/inthepress2, https://sites.google.com/site/andrealancichinetti/files
* [Tiny execution profiler](https://bitbucket.org/lumais/exectime/) to evaluate resources consumption: https://bitbucket.org/lumais/exectime/
* Clustering algorithms, used in the benchmarking: [HiReCS](http://www.lumais.com/hirecs), [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm) and [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/)
 
## Usage
- `./install_depends.sh`  - install dependencies
- `./benchmark.py`  - run the benchmark in the terminal (interactive mode)
- `./benchmark_daemon.sh`  - run the benchmark in background (daemon mode)

*Note: Execution of the benchmark was verified only on Linux Ubuntu 14.04 x64, but it should work on any platform if corresponding external executables (algorithms, nmi evaluation apps, etc.) are provided for the required platforms.*

To see possible input parameters just run the benchmark without arguments: `$ ./benchmark.py`.

## Benchmark Structure
- ./3dparty/  - contains valuable patches to the external open source tools used as binaries
- ./algorithms/  - contains benchmarking algorithms
	- ./algorithms/<algname>outp/  - results of the algorithm evaluation:
		- `*.log`  - `stdout` of the executed algorithm
		- `*.err`  -  `stderr` of the executed algorithm and benchmarking routings
		- `*.cnl`  - resulting clusters unwrapped to nodes (community-nodes list) for NMIs evaluation. `*.cnl` are generated either per each level of the resulting hierarchy of communities or for the whole hierarchy (parameterized inside the benchmark)
	- <algname>.rcp  - resource consumption profile for all executions of the algorithm even in case of crashes / interruptions.
	- <algname>.nmi[-s]  - best NMI value considering overlapping communities produced by gecmi [onmi] app (cf. above). 

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
- ./syntnets/  - synthetic networks produced by the extended LFR framework: undirected weighted complex networks with overlaps, both mixing parameters set for the topology and weights, both exponential nodes degree and weights distributions set
	- `*.ngp`  - network generation parameters
	- `time_seed.dat`  - used time seed on batch generation
	- `*.ngs`  - time seed for the network
	- `*.nst`  - statistics for the generated network
	- `*.nsa`  - network source to be processed by the algorithms to build the community structure
	- `*.cnl`  - ground truth for the community structure (community-nodes list) generated by the LFR framework
- `./exectime`  - lightweight resource consumption [profiler](https://bitbucket.org/lumais/exectime/)
- `./benchmark.py`  - the benchmark (interactive mode)
- `./benchmark_daemon.sh`  - the shell script to execute the benchmark in background (daemon mode)
- `./install_depends.sh`  - the shell script to install dependencies


## Extension
To add own apps / algorithms to be benchmarked just add corresponding functions for "myalgorithm" app:
- `def execMyalgorithm(execpool, netfile, timeout, tasknum=0)`
- `def evalMyalgorithm(execpool, cnlfile, timeout)`

into the `benchapps.py`.


## Related Projects
* [HiReCS](https://github.com/XI-lab/hirecs) - High Resolution Hierarchical Clustering with Stable State: https://github.com/XI-lab/hirecs

If you are interested in this benchmark, please visit <a href="http://exascale.info/">eXascale Infolab</a> where you can find another projects and research papers related to Big Data!
