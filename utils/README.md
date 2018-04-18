# Utilities

## Clustering Quality Measures

### Extrinsic quality measures

* F1 Scores for overlapping communities on multiple resolutions and standard NMI for hard partitioning only (non-overlapping singe resolution clustering) by are evaluated by [xmeasures](https://github.com/eXascaleInfolab/xmeasures).
* NMI (Normalized Mutual Information) for overlapping multiresolution clustering (NMI_max compatile with the standard NMI) is evaluated by [GenConvMI](https://github.com/eXascaleInfolab/GenConvMI). GenConvMI is the extended version of [gecmi](https://bitbucket.org/dsign/gecmi/wiki/Home)), paper: [Comparing network covers using mutual information](https://arxiv.org/abs/1202.0425) by Alcides Viamontes Esquivel, Martin Rosvall.
* NMIs (NMI_max, NMI_lfr, NMI_avg) are evaluated by [OvpNMI](https://github.com/eXascaleInfolab/OvpNMI). OvpNMI is the extended version of [onmi](https://github.com/aaronmcdaid/Overlapping-NMI), paper: [Normalized Mutual Information to evaluate overlapping community finding algorithms](https://arxiv.org/abs/1110.2515) by Aaron F. McDaid, Derek Greene, Neil Hurley.

### Intrinsic quality measures (evaluated by `DAOC`)

* Standard modularity `Q`, but applicable for overlapping communities.
* Conductance `f` applicable for overlapping communities.


## Data Preparation and Postprocessing

### Synthetic Networks Generation and Shuffling

Generation of the synthetic undirected weighted networks with overlaps is performed by the [LFR-Benchmark](https://github.com/eXascaleInfolab/LFR-Benchmark_UndirWeightOvp), which is the extended version of the [original](https://sites.google.com/site/andrealancichinetti/files) [LFR](https://sites.google.com/site/santofortunato/inthepress2).

The optional shuffling of the input datasets is performed by the standard `shuf` Linux application and applicable for the networks in `ncol` format. Networks in other formats or with the present header are shuffled by the `shuffleNets()` procedure of the [benchmark.py](../benchmark.py) script.

### Network Format Conversion

convert.py script is used to perform conversion of the network formats.

### Network Perturbation

remlinks.py script is used to randomly remove specified percent of links from the network, which is useful for robustness evaluation of the clustering algorithms.

### Clusters Postprocessing

Resulting clusterings on multiple resolutions can be merged using [resmerge](https://github.com/eXascaleInfolab/resmerge), which also perfors the node base synchronization with the ground truth communities on Large real-world networks from [SNAP](https://snap.stanford.edu/data/#communities). SNAP datasets provide the ground-truth communities with less nodes than in the input networks, which requires node base synchronization of the resulting clusters for the fair evaluation.
 <!-- and clusters on multiple resolutions in the single ground-truth collection. -->


## Resource Consumption Tracing Tools

Resources consumption is evaluated using [exectime](https://bitbucket.org/lumais/exectime/) profiler.
