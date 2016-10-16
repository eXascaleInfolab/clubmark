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
