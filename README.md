# HiCBeM - Generic Benchmarking Framework with customization for the evaluation of <br />Hierarchical Clustering Algorithms with Overlaps
\author: (c) [Artem Lutov](artem@exascale.info)  
\organizations: [eXascale Infolab](http://exascale.info/), [Lumais](http://www.lumais.com/), [ScienceWise](http://sciencewise.info/)  

## Generic Benchmarking Framework
- optionally generates or preprocesses datasets using specified executable(s)
- optionally executes specified apps with the specified params on the specified datasets
- optionally evaluates results of the execution using specified executable(s)
	
All executions are traced and logged also as resources consumption: CPU (user, kernel, etc.) and memory (RAM RSS).
Traces are saved even in case of internal / external interruptions and crashes.

## Overlapping Hierarhical Clusterig Benchmark
The benchmark is implemented as customization of the Generic Benchmarking Framework with:
- synthetic datasets are generated using extended [LFR Framework](https://sites.google.com/site/santofortunato/inthepress2) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti 1 and Santo Fortunato)
- executes [HiReCS](http://www.lumais.com/hirecs) (www.lumais.com/hirecs), [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm) and [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/) (but this algorithm is not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only") clustering algorithms on the generated synthetic networks
- evaluates results using NMI for overlapping communities, extended versions of:
  * gecmi (https://bitbucket.org/dsign/gecmi/wiki/Home, "Comparing network covers using mutual information" by Alcides Viamontes Esquivel, Martin Rosvall)
  * onmi (https://github.com/aaronmcdaid/Overlapping-NMI, "Normalized Mutual Information to evaluate overlapping community finding algorithms" by  Aaron F. McDaid, Derek Greene, Neil Hurley)
- resources consumption is evaluated using exectime profiler (https://bitbucket.org/lumais/exectime/)

*Note: valuable extensions of the employed external applications are uploaded into ./3dparty/*

Basically the framework executes a set of algorithms on the specified datasets in interactive or daemon mode logging the resources consumption, output, exception and providing workflow management (termination by timeout, resistance to exceptions, etc.).

## Dependencies
### Fundamental
* Python (or [pypy](http://pypy.org/) for fast execution)

### Libraries

* [python-igraph](http://igraph.org/python/) for Louvain algorithm evaluation by NMIs (because the original implementation does not provide convenient output of the communities to evaluate NMIs): `$ pip install python-igraph`

### External tools that are used as executables
* [Extended LFR Benchmark](3dparty/lfrbench_weight-undir-ovp) for undirected weighted networks with overlaps, origins: https://sites.google.com/site/santofortunato/inthepress2, https://sites.google.com/site/andrealancichinetti/files
* [Tiny execution profiler](https://bitbucket.org/lumais/exectime/) to evaluate resources consumption: https://bitbucket.org/lumais/exectime/
* Clustering algorithms, used in the benchmarking: [HiReCS](http://www.lumais.com/hirecs), [Louvain](https://sites.google.com/site/findcommunities/) (original and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), [Oslom2](http://www.oslom.org/software.htm) and [Ganxis/SLPA](https://sites.google.com/site/communitydetectionslpa/)
 
## Usage
- `./install_depends.sh`  - install dependencies
- `./benchmark.py`  - run the benchmark in the terminal (interactive mode)
- `./benchmark_daemon.sh`  - run the benchmark in background (daemon mode)

*Note: Execution of the benchmark was verified only on Linux Ubuntu 14.04 x64, but should work on any platform*

To see possible input parameters just run the benchmark without arguments:
```
$ ./benchmark.py 
Usage: ./benchmark.py [-g[f] [-c] [-r] [-e] [-d{u,w} <datasets_dir>] [-f{u,w} <dataset>] [-t[{s,m,h}] <timeout>]
  -g[f]  - generate synthetic daatasets in the syntnets/
    Xf  - force the generation even when the data is already exists
  -a[="app1 app2 ..."]  - apps to benchmark among the implemented. Impacts -{c, r, e} options. Optional, all apps are executed by default.
  -c  - convert existing networks into the .hig, .lig, etc. formats
  -r  - run the applications on the prepared data
  -e  - evaluate the results through measurements
  -d[X] <datasets_dir>  - directory of the datasets
  -f[X] <dataset>  - dataset file name
    Xu  - the dataset is unweighted. Default option
    Xw  - the dataset is weighted
    Notes:
    - multiple directories and files can be specified
    - datasets should have the following format: <node_src> <node_dest> [<weight>]
  -t[X] <number>  - specifies timeout per each benchmarking application in sec, min or hours. Default: 0 sec
    Xs  - time in seconds. Default option
    Xm  - time in minutes
    Xh  - time in hours
```

## Related Projects
* [HiReCS](https://github.com/XI-lab/hirecs) - High Resolution Hierarchical Clustering with Stable State: https://github.com/XI-lab/hirecs

If you are interested in this benchmark, please visit <a href="http://exascale.info/">eXascale Infolab</a> where you can find another projects and research papers related to Big Data!
