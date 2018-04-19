# PyCABeM - Benchmarking Framework for the Clustering Algorithms Evaluation
`\brief` Benchmarking of the clustering (community detection) algorithms using extrinsic (various Normalized [Mutual Information](https://en.wikipedia.org/wiki/Mutual_information)(NMI) and Mean [F1 Score](https://en.wikipedia.org/wiki/F1_score) measures) and intrinsic ([Modularity](https://en.wikipedia.org/wiki/Modularity_(networks))(Q) and [Conductance](https://en.wikipedia.org/wiki/Conductance_(graph))(f)) measures, considering overlaps (shared node membership by multiple clusters \[on the same resolution level\]) and multiple resolutions (the same node can be a full member of some cluster and parent clusters of that cluster).  
`\authors` (c) Artem Lutov <artem@exascale.info>  
`\organizations` [eXascale Infolab](http://exascale.info/), [Lumais](http://www.lumais.com/), [ScienceWise](http://sciencewise.info/)  
`\keywords` overlapping clustering benchmarking, community detection benchmarking, algorithms benchmarking framework.


## Content
<!--  - [Points of Differentiation](#points-of-differentiation) -->
<!--   - [Functionality](#functionality)
    - [Generic Benchmarking](#generic-benchmarking)
    - [Clustering Specific Benchmarking](#clustering-specific-benchmarking) -->
- [Overview](#overview)
  - [Motivation](#motivation)
- [Prerequisites](#prerequisites)
- [Requirements](#requirements)
  - [Docker Container](#docker-container)
  - [Direct Execution](#direct-execution)
- [Usage](#usage)  
- [Benchmark Structure](#benchmark-structure)  
- [Benchmark Extension](#benchmark-extension)  
- [Related Projects](#related-projects)  


## Overview

<!-- ### Points of Differentiation -->
The benchmark executes specified applications (clustering algorithms) on the specified or generated input datasets (networks), measures execution statistics and evaluates accuracy of the results using specified measures. PyCABeM is a general-purpose modular benchmarking framework specialized for the clustering (community detection) algorithms evaluation. The general functionality is based on [PyExPool](https://github.com/eXascaleInfolab/PyExPool) multiprocess execution pool and load balancer.
<!-- PyExPool provides [external] applications scheduling for the in-RAM execution on NUMA architecture with capabilities of the affinity control, CPU cache vs parallelization maximization, memory consumption and execution time constrains specification for the whole execution pool and per each executor process (called worker, executes a job).
 -->

General purpose properties:
- Data preprocessing (synthetic networks generation, shuffling, etc.);
- Pre/post execution callbacks for each executable to perform the application specific initialization and finalization (results normalization, logs post-processing, etc.);
- Resource consumption management and tracing:
  * Specification of the global and per executable constraints for the maximal execution time and memory consumption;
  * Binding of any executable to the specified set of logical CPUs (affinity masking) to employ advantages of the NUMA hardware executing apps in parallel not affecting their CPU caches (dedicating L1/2/3 caches);
  * Tracing of the execution time, CPU timings (user and kernel) and peak RAM RSS memory consumption;
- Load balancing of the executing apps to employ as much as possible available hardware resources respecting the specified constraints;
- Resiliency and fault tolerance (failover execution) tracing crashes of faulty apps not affecting execution of other apps.

Properties specific for the clustering algorithms benchmarking:
- Evaluation of the extrinsic (modularity, conductance) and intrinsic (various NMIs and F1-Scores) quality measures for the generalized clustering algorithms (considering overlaps and multiple resolutions/scales if any);
- Selection of the best result for the parameterized clustering algorithms among the results produced for all specified variations of the parameters;
- Evaluation of both the average value and deviation of the measures if multiple instances and/or shuffles (nodes and links reordering) of the input networks are used.

Executing [algorithms](algorithms/README.md) and [evaluation measures with the accessory processing tools](utils/README.md) are described on the respective pages.


### Motivation
I have not any open source cross-platform framework for the [efficient] execution and evaluation of custom applications, which have  significant variation of the time/memory complexity and custom constraints, so decided to write the own one.

Particularly, I had to evaluate various clustering (community detection) algorithms on large networks using specific measures. The main challenges are the following:
- the executing applications (clustering algorithms) being benchmarked have very different (orders of magnitude) time and memory complexity and represented by the applications implemented on various languages (mainly C++, Java, C and Python);
- the target datasets are very different by structure and size (orders of magnitude varying from KBs to GBs);
- the accessory evaluating applications (NMI, F1 Scores, ...) have very different (orders of magnitude) time and memory complexity and architecture (single-threaded and multi-threaded applications).

Ideally, the executing applications (algorithms) should be executed in parallel in a way to guarantee that they:
- are not swapped from RAM to HDD (which happens on the *unconstrained* execution of multiple memory demanding apps) to not affect the efficiency measurements;
- consume as much available hardware resources as possible to speedup the benchmarking;
- localize the CPU cache (the processes are not jumped between the CPUs and work with the hot cache);
- are automatically terminated from the execution on more complex datasets if do not satisfy the execution constraints on lighter datasets.

Before starting PyCABeM development I found several open source frameworks for the "Community Detection Algorithms" evaluation but they do not fulfill the outlined constraints. The most comprehensive one is [Circulo](http://www.lab41.org/circulo-a-community-detection-evaluation-framework/) from [Lab41](https://github.com/Lab41/Circulo/tree/master/experiments), another one is called [CommunityEvaluation](https://github.com/rabbanyk/CommunityEvaluation).  
Circulo is an excellent framework until you don't run evaluations on the large networks, don't need to specify per-algorithm time/memory constraints and in case the default pipeline is sufficient, which was not the case for me.


<!-- ### Functionality -->
<!-- #### Generic Benchmarking
The generic benchmarking functionality is based on [PyExPool](https://github.com/eXascaleInfolab/PyExPool), which provides [external] applications scheduling for the in-RAM execution on NUMA architecture with capabilities of the affinity control, CPU cache vs parallelization maximization, memory consumption and execution time constrains specification for the whole execution pool and per each executor process (called worker, executes a job).

The benchmarking framework specifies the structure and provides APIs for the:
- optional *generation of datasets* or their preprocessing using specified executable(s);
- optional *execution of the specified computing applications* (clustering algorithms) on the specified datasets (using wildcards), where each application may produce multiple output files (levels of the hierarchy of clusters for each input network);
- optional *execution of the evaluating applications* on the produced results (and ground-truth if applicable), aggregation of the results grouped by the computing application;
- optional specification of the *execution constraints* (time, memory, parallelization, CPU cache and affinity) for each executable and for the whole benchmarking using the [PyExPool](https://github.com/eXascaleInfolab/PyExPool) multi-process execution pool balancer;
- skipping computations on the more complex datasets if the executing application failed constraints on some lighter dataset;
- *efficiency measurements* (time, memory) tracing for each executable;
- *logging of traces (stdout) and errors (stderr)* (outputs of the executables and their runtime statistics) for each executable and for the benchmarking framework itself;
- *automatic extension / backup* of the already existent results to the timestamped .gzip archives on the benchmarking re-execution.

It is possible to have multiple input directories with similarly named files inside, which represent different instances / snapshots of the datasets. In such case, the results are produced per each snapshot, plus aggregated weighted average over all snapshots. This is useful to avoid occasional bias to the specific instance or to analyze evolving networks.  
If any application is crashed, the crash is logged and does not affect execution of the remaining applications. The benchmark can be terminated by the timeout or manually.
 -->

<!-- #### Clustering Specific Benchmarking -->
<!-- The benchmark is implemented as customization of the Generic Benchmarking Framework to evaluate various *Clustering Algorithms* (Community Detection Algorithms) including *Hierarchical Clustering Algorithms with Overlaps and Consensus*:
- produces synthetic networks with specified number of instances for each set of parameters, generating them by the extended [LFR Framework](https://github.com/eXascaleInfolab/LFR-Benchmark_UndirWeightOvp) ("Benchmarks for testing community detection algorithms on directed and weighted graphs with overlapping communities" by Andrea Lancichinetti and Santo Fortunato)
- shuffles specified networks (reorders nodes) specified number of times, which is required to evaluate stability / determinism of the clustering algorithms
- executes clustering algorithms on the generated synthetic networks (or on any specified directories and files). Outputs results (clusters/communities structure, hierarchy, modularity, nmi, etc.) of the clustering algorithms are stored in the corresponding files.

 -->

All results and traces are stored into the corresponding files even in case of internal (crash) / external termination of the benchmarking applications or the whole framework.

Basically the framework executes a set of applications on the specified datasets in interactive or daemon mode, logging the resources consumption, output and exceptions, providing workflow management (termination by timeout, resistance to exceptions, etc.) and results aggregation.


## Prerequisites
The benchmarking framework itself is a *cross-platform* application implemented purely on Python, and works on CPython 2/3 and Pypy interpreters.  
However, the benchmark runs clustering algorithms and evaluation utilities implemented on C++ and built for the specific platform. The build is performed for the *Linux Ubuntu 16.04 x64*, on other NIX systems requirements might be missed and not easily solvable. [Docker](https://docs.docker.com/get-started/) image is prepared to run the build from the docker container on any other platform avoiding dependency related issues.

> [Windows 10+ x64 provides Ubuntu-compatible bash shell](https://www.howtogeek.com/249966/how-to-install-and-use-the-linux-bash-shell-on-windows-10/), which allows to install and execute terminal Ubuntu apps and execute the benchmarking exactly as on Linux Ubuntu 16.04 x64.

All subsequent steps are described for the *NIX* platforms including MaxOS.  
To be sure that the operational system allows to work with lots of opened files and has adequate swapping policy, execute (the leading `.` or `source` keyword is mandatory):
```sh
$ . ./prepare_hostenv.sh
```

> This script should be executed **on the host system event if the benchmark is executed from the docker container**, because the container shares resources of the host system (kernel, memory and swap).  
The made changes will be reseted after the restart.  
ATTENTION: starting `.` or `source` is *required* to execute the script in the current shell environment instead of the new process.

Alternatively, perform the following steps to tune the operational system environment permanently.

- The max number of the opened files in the system `$ sysctl fs.file-max` should be large enough, the recommended value is `1048576`.
- The max number of the opened files per a process`$ ulimit -n` should be at least `4096`, the recommended value is `65536`.

To setup `fs.file-max` permanently in the system add the following line to the `/etc/sysctl.conf`:
```sh
fs.file-max = 1048576
```
and then reload it by `# sysctl -p`.  
To setup the `ulimit` permanently add the following lines to the `/etc/security/limits.conf`:
```sh
*               hard    nofile          524288
*               soft    nofile          32768  
```
And then execute `ulimit -n 32768` to set this value for the current shell.

> `ulimit` can't be set higher than the hard limit `ulimit -Hn`, so if the latter < `32768` then execute:
```sh
$ ulimit -n `ulimit -Hn`
```

Reduce the system `swappiness` setting to 1 .. 10 by `$ sudo sysctl -w vm.swappiness=5` or set it permanently in `/etc/sysctl.conf`:
```sh
vm.swappiness = 5
``` 


## Requirements

The benchmarking can be run either directly on the *Linux Ubuntu 16.04 x64* or via the [Docker](https://docs.docker.com/get-started/) container with the preinstalled environment on any platform. Anyway, the sources are required:
```sh
$ git clone https://github.com/eXascaleInfolab/PyCABeM.git
```


### Docker Container

> This section is optional if your host OS is *Linux Ubuntu 16.04 x64* and the benchmarking is run directly on the host OS.

The *Docker* can be installed on the Linux Ubuntu 16.04 executing:
```sh
$ sudo apt-get update && apt-get upgrade
$ sudo apt-get install -y docker.io
```
To install the Docker on any other platform refer the [official installation instructions](https://docs.docker.com/engine/installation/).

> It is recommended to use `overlay2` storage driver on any OS, see details in the [official documentation](https://docs.docker.com/engine/userguide/storagedriver/overlayfs-driver/#configure-docker-with-the-overlay-or-overlay2-storage-driver). `overlay2` requires Linux kernel v4.x, which can be updated from 3.x to 4.x on Red Hat / CentOS 7 / Scientific Linux as described in [this article](https://www.tecmint.com/install-upgrade-kernel-version-in-centos-7/).

Add your user to the docker group to use it without `sudo`:
```sh
$ sudo groupadd docker
$ sudo usermod -aG docker $USER
```
Log out and log back in so that your group membership is re-evaluated, or execute:
```sh
$ su - $USER
```
Optionally, configure Docker to start on boot:
```sh
$ sudo systemctl enable docker
```
and check other [docker post-installation](https://docs.docker.com/engine/installation/linux/linux-postinstall/) steps.

Start Docker service:
```sh
$ sudo systemctl start docker
$ docker version
```
See also the [brief tutorial on Docker installation and usage](https://www.howtoforge.com/tutorial/docker-installation-and-usage-on-ubuntu-16.04/) or the [official getting started tutorial](https://docs.docker.com/get-started/).

Optionally, the `PyCaBeM` docker image containing the execution environment can be built from the source [Dockerfile](Dockerfile) by executing from the repository directory:
```sh
$ docker build -t luaxi/pycabem:env-U16.04-v2.0 .
```
Otherwise, the prebuilt image will be automatically pulled from the *Docker Hub* repository on first docker `run`.


### Direct Execution

> This section is optional if the benchmarking is run on the docker container.

The target environment is *Linux Ubuntu 16.04 x64*. To install all the requirements there, execute from repository directory:
```sh
$ ./install_reqs.sh
```
See [install_reqs.sh](install_reqs.sh) and [pyreqs.txt](pyreqs.txt) for details about the installing packages.

> The benchmarking framework can be executed under Python 2.7+ including 3.x (works on both the official CPython and on [PyPy](http://pypy.org/) JIT for the faster execution).  
Some executing algorithms support only Python2 / pypy, others both Python3 and Python2. Selection of the appropriate interpreter is made automatically in runtime. At least Python2 is required to run the benchmarking, but the recommended environment, which is installed by the script is both Python3 and pypy.


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


## Usage

To run the benchmark you can execute
```sh
$ docker run -it -u $UID -v `pwd`:/opt/pycabem luaxi/pycabem:env-U16.04-v2.0 [<pycabem_args>]
```
Or to open a shell in the benchmarking directory:
```sh
$ docker run -it --entrypoint "" -u $UID -v `pwd`:/opt/pycabem luaxi/pycabem:env-U16.04-v2.0
```

> $UID might not be defined in the non-bash shell (sh, etc), then use `id -u $USER` instead

Where ``pwd`` projects to `<PYCABEM_REPOSITORY_PATH>`, which is the current directory and working directory of the benchmarking

See also [Docker cheat sheet](https://coderwall.com/p/2es5jw/docker-cheat-sheet-with-examples).



- `./install_depends.sh`  - install dependencies (using apt-get)
- `./benchmark.py`  - run the benchmark in the terminal (interactive mode)
- `./benchmark_daemon.sh`  - run the benchmark in background (daemon mode)

> Note: Execution of the benchmark was verified only on Linux Ubuntu 14.04 x64, but it should work on any platform if corresponding external executables (algorithms, nmi evaluation apps, etc.) are provided for the required platform.

To see possible input parameters run the benchmark without arguments: `$ ./benchmark.py`:  
```sh
$ ./benchmark.py 
Usage:
  ./benchmark.py [-g[o][a]=[<number>][%<shuffles_number>][=<outpdir>] [-i[f][a][%<shuffles_number>]=<datasets_{dir,file}_wildcard> [-c[f][r]] [-a=[-]"app1 app2 ..."] [-r] [-q[e[{n[x],o[x],f[{h,p}],d}][i[{m,c}]]] [-s=<eval_path>] [-t[{s,m,h}]=<timeout>] [-d=<seed_file>] | -h

Example:
  ./benchmark.py -g=3%5 -r -q -th=2.5 1> results/bench.log 2> results/bench.err
NOTE:
  - The benchmark should be executed exclusively from the current directory (./)
  - The expected format of input datasets (networks) is .ns<l> - network specified by <links> (arcs / edges), a generalization of the .snap, .ncol and Edge/Arcs Graph formats.
  - paths can contain wildcards: *, ?, +
  - multiple paths can be specified via multiple -i, -s options (one per the item)

Parameters:
  --help, -h  - show this usage description
  --generate, -g[o][a]=[<number>][%<shuffles_number>][=<outpdir>]  - generate <number> synthetic datasets of the required format in the <outpdir> (default: syntnets/), shuffling (randomly reordering network links and saving under another name) each dataset <shuffles_number> times (default: 0). If <number> is omitted or set to 0 then ONLY shuffling of <outpdir>/networks//* is performed. The generated networks are automatically added to the begin of the input datasets.
    o  - overwrite existing network instances (old data is backuped) instead of skipping generation
    a  - generate networks specified by arcs (directed) instead of edges (undirected)
NOTE: shuffled datasets have the following naming format:
  <base_name>[(seppars)<param1>...][^<instance_index>][%<shuffle_index>].<net_extension>
  --input, -i[X][%<shuffles_number>]=<datasets_dir>  - input dataset(s), wildcards of files or directories, which are shuffled <shuffles_number> times. Directories should contain datasets of the respective extension (.ns{e,a}). Default: -ie=syntnets/networks/*/, which are subdirs of the synthetic networks dir without shuffling.
    f  - make flat derivatives on shuffling instead of generating the dedicated directory (having the file base name) for each input network, might cause flooding of the base directory. Existed shuffles are backuped.
    NOTE: variance over the shuffles of each network instance is evaluated only for the non-flat structure.
    a  - the dataset is specified by arcs (asymmetric, directed links) instead of edges (undirected links), considered only for not .ns{a,e} extensions.
NOTE:
  - The following symbols in the path name have specific semantic and processed respectively: ('!', '^', '%', '#')
  - Paths may contain wildcards: *, ?, +
  - Multiple directories and files wildcards can be specified via multiple -i options
  - Shuffles backup and OVERWRITE already existent shuffles
  - Datasets should have the .ns<l> format: <node_src> <node_dest> [<weight>]
  - Ambiguity of links weight resolution in case of duplicates (or edges specified in both directions) is up to the clustering algorithm
  --apps, -a[=[-]"app1 app2 ..."]  - apps (clustering algorithms) to be applied, default: all.
Leading "-" means applying of all except the specified apps. Available apps (13): CggcRg, CggciRg, Daoc, DaocA, DaocA_s_r, Daoc_s_r, Ganxis, LouvainIg, Oslom2, Pscan, Randcommuns, Scd, Scp.
Impacts {r, q} options. Optional, all registered apps (see benchapps.py) are executed by default.
NOTE: output results are stored in the "results/<algname>/" directory
  --runapps, -r  - run specified apps on the specified datasets, default: all
  --quality, -q[X]  - evaluate quality (including accuracy) of the results for the specified algorithms on the specified datasets and form the summarized results. Default: NMI_max, F1h and F1p measures on all datasets
    e[Y]  - extrinsic measures for overlapping communities, default: all
      n[Z]  - NMI measure(s) for overlapping and multi-level communities: max, avg, min, sqrt
        x  - NMI_max,
      NOTE: unified NMI evaluation is stochastic and does not provide the seed parameter.
      o[Z]  - overlapping NMI measure(s) for overlapping communities that are not multi-level: max, sum, lfk. Note: it is much faster than generalized NMI
        x  - NMI_max
      f[Z]  - avg F1-Score(s) for overlapping and multi-level communities: avg, hmean, pprob
        h  - harmonic mean of F1-Score
        p  - F1p measure (harmonic mean of the weighted average of partial probabilities)
      r  - recommended extrinsic measures (NMI_max, F1_h, F1_p) for overlapping multi-level communities
    i[Y]  - intrinsic measures for overlapping communities, default: all
      m  - modularity Q
      c  - conductance f
    u  - update quality evaluations appending the new results to the existing stored evaluations (if any) and then aggregate everything to the final summarized results skipping older duplicates (if any).
  ATTENTION: "-qu" requires at least one more "-qX" flag to indicate what measures should be (re)evaluated. Applicable only for the same seed as existed evaluations had. The existed quality evaluations are backed up anyway.
NOTE: multiple quality evaluation options can be specified via the multiple -q options.
  --timeout, -t[X]=<float_number>  - specifies timeout for each benchmarking application per single evaluation on each network in sec, min or hours; 0 sec - no timeout, default: 36 h 0 min 0 sec
    s  - time in seconds, default option
    m  - time in minutes
    h  - time in hours
  --seedfile, -d=<seed_file>  - seed file to be used/created for the synthetic networks generation and stochastic algorithms, contains uint64_t value. Default: results/seed.txt
NOTE: the seed file is not used in the shuffling, so the shuffles are distinct for the same seed

Advanced parameters:
  --convret, -c[X]  - convert input networks into the required formats (app-specific formats: .rcg[.hig], .lig, etc.)
    f  - force the conversion even when the data is already exist
    r  - resolve (remove) duplicated links on conversion (recommended to be used)
  --summary, -s=<resval_path>  - aggregate and summarize specified evaluations extending the benchmarking results, which is useful to include external manual evaluations into the final summarized results
ATTENTION: <resval_path>  should include the algorithm name and target measure
```

> _REPRODUCIBILITY NOTICE_: Use seed to reproduce the evaluations, but be aware that:
> - the seed is not applicable for the shuffling (reordering of the network nodes and links, which is truly random) and
> - not all clustering algorithms might support the seed.
So, in case of shuffling, the original shuffles should be provided to reproduce exactly the same results (for either deterministic algorithms or algorithms that have the input seed).


### Synthetic networks generation, clustering algorithms execution and evaluation
```sh
$ pypy ./benchmark.py -g=3%2=syntnets_i3_s4 -cr -a="scp oslom2" -r -q -tm=90
```
Run the benchmark under PyPy.  
Generate synthetic networks producing 3 instances of each network with 2 shuffles (random reordering of network nodes) of each instance, having 3*2=6 synthetic networks of each type (for each set of network generation parameters). Generated networks are stored in the ./syntnets_i3_s4/ directory.  
Convert all networks into the .hig format resolving duplicated links. This conversion is required to be able to evaluate modularity measure.  
Run `scp` and `oslom2` clustering algorithms for each generated network and evaluate modularity and NMI measures for these algorithms.  
Timeout is 90 min for each task of each network processing, where the tasks are: networks generation, clustering and evaluation by each specified measure. The network is each shuffle of each instance of each network type.  

### Shuffling existing network instances, clustering algorithm execution and evaluation using NMI_max with 1h timeout for any task
```sh
$ ./benchmark.py -g=.4 -i=syntnets_i3_s4 -a=oslom2 -qenx -th=1
```
Run the benchmark for the networks located in ./syntnets_i3_s4/ directory.  
Produce 4 shuffles of the specified networks, previously existed shuffles are backed up.  
Run `oslom2` clusterшng algorithm for the specified networks with their shuffles and evaluate NMI_s measure.  
Timeout is 1 hour for each task on each network.  

### Aggregation of the specified evaluation results
```sh
$ pypy benchmark.py -s=results/scp/mod/*.mod
```
Results aggregation is performed with automatic identification of the target clustering algorithm and evaluation measure by the specified path. It is performed automatically as the last step of the algorithm evaluation, but also can be called manually for the modified scope.


## Benchmark Structure
- ./contrib/  - valuable patches to the external open source tools used as binaries
- ./algorithms/  - benchmarking algorithms
- ./results/  - aggregated and per-algorithm execution and evaluation results (brief `*.res` and extended `*.resx`): timings (execution and CPU), memory consumption, NMIs, Q, per-algorithm resources consumption profile (`*.rcp`)
  - `<algname>.rcp`  - resource consumption profile for all executions of the algorithm even in case of crashes / interruptions
  - `<measure>.res[x]`  - aggregated value of the measure: average is evaluated for each level / scale for all shuffles of the each network instance, then the weighted best average among all levels is taken for all instances as a final result
  * `<algname>/clusters/`  - algorithm execution results produced hierarchies of communities for each network instance shuffle
    - `*.cnl`  - resulting clusters unwrapped to nodes (community nodes list) for NMIs evaluation. `*.cnl` are generated either per each level of the resulting hierarchy of communities or for the whole hierarchy (parameterized inside the benchmark)
  * `<algname>/mod/`  - algorithm evaluation modularity for each produced hierarchical/scale level
    - `<net_instance>.mod`  - modularity value aggregated per network instances (results for all shuffles on the network instance are aggregated in the same file)
  * `<algname>/nmi[_s]/`  - algorithm evaluation NMI[_s] for each produced hierarchical/scale level
    - `<net_instance>.nmi[_s]`  - NMI[_s] value aggregated per network instances
  - `*.log`  - `stdout` of the executed algorithm, logs
  - `*.err`  - `stderr` of the executed algorithm and benchmarking routings, errors

Example of the `<entity>.rcp` format:
```sh
# ExecTime(sec)	CPU_time(sec)	CPU_usr(sec)	CPU_kern(sec)	RSS_RAM_peak(Mb)	TaskName
2.575555	2.574302	2.540420	0.033882	6.082	5K5
0.528582	0.528704	0.519277	0.009427	3.711	2K10
...
```

Example of the `.res` format:
```sh
# --- 2015-12-31 16:15:37.693514, output:  Q_avg
# <network>	ganxis	louvain_igraph	...
karate	0.130950	0.414481	0.233974	0.240929
jazz_u	0.330844	0.400587	0.392081	0.292395
...
```

Example of the `.resx` format:
```sh
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
```sh
# NMI	level[/shuffle]
0.815814	0
0.870791	1
0.882737	0/1
...
```

Example of the `<net_instance>.mod` format:
```sh
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
  asym  - network links weights are asymmetric (in/outbound weights can be different)
  timeout  - execution timeout for this task
  pathid  - path id of the net to distinguish nets with the same name located in different dirs.
    Note: pathid is prepended with the separator symbol
  selfexec  - current execution is the external or internal self call

  return  - number of executions (jobs) made
  """
```

All the evaluations will be performed automatically, the algorithm should just follow conversion of the execution results output.


## Related Projects
* DAOC - (former [HiReCS](https://github.com/eXascaleInfolab/hirecs) High Resolution Hierarchical Clustering with Stable State, which was totally redesigned)
* [eXascale Infolab](https://github.com/eXascaleInfolab) GitHub repository and [our website](http://exascale.info/) where you can find another projects and research papers related to Big Data processing!  
Please, [star this project](https://github.com/eXascaleInfolab/PyCABeM) if you use it.
