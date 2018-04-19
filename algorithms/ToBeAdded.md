# Clustering Algorithms
> The algorithms marked with (*) work with the attributed networks (record data), but we have similarity networks  (relations data) / adjacency matrices. The networks conversion is required with subsequent conversion of the output formats.

## Efficient Popular Algorithms
- [HDBSCAN](https://github.com/lmcinnes/hdbscan)* - Density-Based Clustering Based on Hierarchical Density Estimates '13. Python implementation (with possible C backend) is available.

##  Deterministic Clustering Algorithms
- Deterministic Annealing probably using the [SMILE implementation](https://github.com/haifengl/smile/blob/master/core/src/main/java/smile/clustering/DeterministicAnnealing.java). Parameters: ? O(n2), requires max num of clusters (and the temperature cooling parameter alpha = 0.9 by default), reuses K-Means.
- [hkgrow](https://www.cs.purdue.edu/homes/dgleich/codes/hkgrow/) - Deterministic Personal PageRank, KDD'14. Parameters: *seeds*, N (some parameter), t {3, 5, 15, ...?}, eps.

## Ensemble Clustering Algorithms
- KCC* - K-means-based Consensus Clustering: A Unified View, TKDE'15. Mathlab only implementation is available. Not sure where it can be executed under Octave on Linux.

## Another Popular Algorithms
- [Infomap](http://www.mapequation.org/code.html) (papers from '08 up to '16: "Maps of sparse Markov chains efficiently reveal community structure in network flows with memory" '16).
- [KaHIP](https://github.com/schulzchristian/KaHIP/) - [Karlsruhe High Quality Partitioning](http://algo2.iti.kit.edu/documents/kahip/). The best Graph partitioning solution according to the 10th Dimacs ’13.

# Measures
- F1
	- SkiKit provides only for a single pair of clusters: http://scikit-learn.org/stable/modules/generated/sklearn.metrics.f1_score.html
	- NF1 - slow Python impl., but could be reimplemented using Cython as https://github.com/alamages/cls-metrics !
		But instead of separate converts and redundancy evaluation  just evaluate all distinct clusters with the provision markers
		and eval F1 to the clusters from the opposite source (actual result VS ground-truth), all matchin clusters have F1=1.
		Also check how Leckovec did it.
		! Use Cython, see https://github.com/alamages/cls-metrics
		~1-2 days.
		
		=> use [start:end:step/maxsteps#relativeOutpDir; start2:end2....] in DAOC.
		~ 2 days
- FNMI:
	- Is Normalized Mutual Information a Fair Measure for Comparing Community Detection Methods, ASONAM'15:  ~ 2 hours / app
- Conductance
	- Implement in DAOC, ~ 1 day


# Addditional Features:
- Run algorithms optionally from different home folders to allow execution of multiple versions of the same algorithm
- CPU affinity specification (taskset)

## Interactivity
	- Store intermediate results in HDF5 via panda and stream them using PyDAP: http://www.pydap.org/handlers.html#hdf5



Rename and cleanup Stanford datasets, but we will need to have different datasets for all communities evaluation and Top5K => 
	- twice clustering time in case of evaluation for both objectives
	* ATTENTION: nodes reduction before the clustering affects the community structure, i.e. results of the clustering.
~ 1 day
VS
	- Update NMI eval algs (both gecmi and onmi) to omit nbodes that are not present in the ground truth
	- add static linking
~ 2 days

? Demo paper for the benchmarking system with Pandas and REal time streaming of the results



# Additional TODO
	- onmi [sum]: https://github.com/aaronmcdaid/Overlapping-NMI
		- Add optional output of the single specified type of NMI, ? sum by default
		- sync with the latest update from the original repository, consider GPLv3 license
	- gecmi https://bitbucket.org/dsign/gecmi/wiki/Home
		- sync with the latest update from the original repository, consider GPLv3 license
		> Uses Boost lib
		

+ Clone and update repositories
- Modify the libs.
	- Assumptions: ground truth contains always not more clusters that the whole network
		=> parameter to identify ground-truth or non-ground-truth
		first required positional argument 
		and the second either required or the option is specified for the reduction 



To Verify in gecmi:
1. pimpl_t
2. Usage of vector
src/deep_complete_simulator.cpp|160|std::vector< size_t > vertices( vertex_count );|
											std::random_shuffle( vertices.begin(),

