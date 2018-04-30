# Utilities

## Clustering Quality Measures

### Extrinsic quality measures

* F1 Scores for overlapping communities on multiple resolutions and standard NMI for hard partitioning only (non-overlapping singe resolution clustering) by are evaluated by [xmeasures](https://github.com/eXascaleInfolab/xmeasures).
* NMI (Normalized Mutual Information) for overlapping multi-resolution clustering (NMI_max compatible with the standard NMI) is evaluated by [GenConvMI](https://github.com/eXascaleInfolab/GenConvMI). GenConvMI is the extended version of [gecmi](https://bitbucket.org/dsign/gecmi/wiki/Home)), paper: [Comparing network covers using mutual information](https://arxiv.org/abs/1202.0425) by Alcides Viamontes Esquivel, Martin Rosvall.
* NMIs (NMI_max, NMI_lfr, NMI_avg) are evaluated by [OvpNMI](https://github.com/eXascaleInfolab/OvpNMI). OvpNMI is the extended version of [onmi](https://github.com/aaronmcdaid/Overlapping-NMI), paper: [Normalized Mutual Information to evaluate overlapping community finding algorithms](https://arxiv.org/abs/1110.2515) by Aaron F. McDaid, Derek Greene, Neil Hurley.
 
### Intrinsic quality measures (evaluated by `DAOC`)

* Standard modularity `Q`, but applicable for overlapping communities.
* Conductance `f` applicable for overlapping communities.

### Requirements

- daoc (former [hirecs](http://www.lumais.com/hirecs/)) also used for modularity and conductance evaluation of overlapping community structure (with results compatible to the respective standard modularity and conductance values). It depends on:
  * `libstdc++.so.6`: version GLIBCXX_3.4.20 (precompiled version for modularity evaluation). To install it on Ubuntu use: `sudo apt-get install libstdc++6` or
    ```sh
    $ sudo add-apt-repository ppa:ubuntu-toolchain-r/test
    $ sudo apt-get update
    $ sudo apt-get install libstdc++6
    ```
- [python-igraph](http://igraph.org/python/) for Louvain algorithm evaluation by NMIs (because the original implementation does not provide convenient output of the communities to evaluate NMIs): `$ pip install python-igraph`. It depends on:
  * `libxml2` (and `libz` on Ubuntu 14), which are installed in Linux Ubuntu executing:  
  `$ sudo apt-get install libxml2-dev`  (`lib32z1-dev` might be also required)

- [OvpNMI](https://github.com/eXascaleInfolab/OvpNMI) or [`gecmi`](https://bitbucket.org/dsign/gecmi/wiki/Home) for the NMI_ovp evaluation depends on:
  * `libboost_program_options`, to install execute: `$ sudo apt-get install libboost-program-options`. The older version of gecmi compiled under Ubuntu 14 depends on `libboost_program_options.so.1.54.0`, the newer one compiled under Ubuntu 16 depends on `libboost_program_options.so.1.58.0`.
  * `libtbb.so.2`, to install execute: `sudo aptitude download libtbb2; sudo aptitude install libtbb2`

Optional requirements of the [mpepool.py](https://github.com/eXascaleInfolab/PyExPool) load balancer:
- [psutil](https://pypi.python.org/pypi/psutil) is required for the dynamic jobs balancing to perform the in-RAM computations (`_LIMIT_WORKERS_RAM = True`) and limit memory consumption of the workers.
  ```sh
  $ sudo pip install psutil
  ```
  > To perform in-memory computations dedicating almost all available RAM (specifying *memlimit ~= physical memory*), it is recommended to set swappiness to 1 .. 10: `$ sudo sysctl -w vm.swappiness=5` or set it permanently in `/etc/sysctl.conf`: `vm.swappiness = 5`.
- [hwloc](http://www.admin-magazine.com/HPC/Articles/hwloc-Which-Processor-Is-Running-Your-Service) (includes `lstopo`) is required to identify enumeration type of logical CPUs to perform correct CPU affinity masking. Required only for the automatic affinity masking with cache usage optimization and only if the CPU enumeration type is not specified manually.
  ```sh
  $ sudo apt-get install -y hwloc
  ```
- [bottle](http://bottlepy.org) is required for the minimalistic optional WebUI to monitor executing jobs.
  ```sh
  $ sudo pip install bottle
  ```

All Python requirements are optional and can be installed from the `pyreqs.txt` file:
```sh
$ sudo pip install -r pyreqs.txt
```
> `hwloc` is a system requirement and can't be installed from the `pyreqs.txt`


## Data Preparation and Post-processing

### Synthetic Networks Generation and Shuffling

Generation of the synthetic undirected weighted networks with overlaps is performed by the [LFR-Benchmark](https://github.com/eXascaleInfolab/LFR-Benchmark_UndirWeightOvp), which is the extended version of the [original](https://sites.google.com/site/andrealancichinetti/files) [LFR](https://sites.google.com/site/santofortunato/inthepress2).

The optional shuffling of the input datasets is performed by the standard `shuf` Linux application and applicable for the networks in `ncol` format. Networks in other formats or with the present header are shuffled by the `shuffleNets()` procedure of the [benchmark.py](../benchmark.py) script.

### Network Format Conversion

convert.py script is used to perform conversion of the network formats.

### Network Perturbation

remlinks.py script is used to randomly remove specified percent of links from the network, which is useful for robustness evaluation of the clustering algorithms.

### Clusters Post-processing

Resulting clusterings on multiple resolutions can be merged using [resmerge](https://github.com/eXascaleInfolab/resmerge), which also performs the node base synchronization with the ground truth communities on Large real-world networks from [SNAP](https://snap.stanford.edu/data/#communities). SNAP datasets provide the ground-truth communities with less nodes than in the input networks, which requires node base synchronization of the resulting clusters for the fair evaluation.
 <!-- and clusters on multiple resolutions in the single ground-truth collection. -->


## Resource Consumption Tracing Tools

Resources consumption is evaluated using [exectime](https://bitbucket.org/lumais/exectime/) profiler.
