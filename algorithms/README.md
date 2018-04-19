# Clustering Algorithms

## Overview

Features \ Algs		| *DAOC* | SCP	| Louvain   | Oslom2 | GANXiS   | pSCAN | CGGCi_RG | SCD
| ---			 	| :-: 	 | :-: 	| :-: 		| :-: 	 | :-: 		| :-: 	| :-:      | :-:
Hierarchical    	| +      |  	| + 		| +  	 | 			| 		|          | 
Multi-scale     	| + 	 | + 	| + 		| + 	 | + 		| 		|          | 
Deterministic   	| + 	 | + 	| 			|        | 			| ? 	|          | ?
With Overlaps   	| + 	 | + 	| 			| + 	 | + 		| + 	| *        | 
With Weights        | +      | +    | +         | *      | +        |       |          |
Parameter-Free  	| +* 	 | 		| + 		| * 	 | * 		|  		| *        | *
Consensus/Ensemble  | + 	 | 		| 			| + 	 | 			| 		| +        | 

> - *With Overlaps*  
> `*` means non-overlapping clusters are produced but the algorithm can be modified to output the overlapping clusters.
> - *With Weights*  
> `*` means weighted networks are supported.
> - *Parameter-Free*  
> `*` means availability of default values for all parameters,  
> `+*` means parameter-free clustering algorithm with optional > parameters for the data preprocessing or output post-processing.


## Origins

* DAOC (former and fully redesigned [HiReCS](http://www.lumais.com/hirecs));
* [SCP](http://www.lce.hut.fi/~mtkivela/kclique.html) ([Sequential algorithm for fast clique percolation](http://www.lce.hut.fi/research/mm/complex/software/)), paper: [A sequential algorithm for fast clique percolation](https://arxiv.org/abs/0805.1449);
* Louvain ([original](https://sites.google.com/site/findcommunities/) and [igraph](http://igraph.org/python/doc/igraph.Graph-class.html#community_multilevel) implementations), paper: [Fast unfolding of communities in large networks](https://arxiv.org/abs/0803.0476);
* [Oslom2](http://www.oslom.org/software.htm), paper: [Finding Statistically Significant Communities in Networks](https://arxiv.org/abs/1012.2363);
* [GANXiS/SLPA](https://sites.google.com/site/communitydetectionslpa/) (*not uploaded into the repository, because it was provided by the author Jerry Xie for "academic use only"*<!-- ; *deterministic algorithm LabelRankT* is a modification of GANXiS, but LabelRankT is not publicly available -->), paper: [Extension of Modularity Density for Overlapping Community Structure](http://ieeexplore.ieee.org/document/6921686/);
  > GANXiS requires preliminary created output directory if it is specified in the options, but GANXiS always creates also default "./output/" directory, which is empty if the custom one is used.
* [pSCAN](https://github.com/eXascaleInfolab/pSCAN) binaries provided by the [author](http://www.cse.unsw.edu.au/~ljchang/), paper: [pSCAN : Fast and Exact Structural Graph Clustering](http://ieeexplore.ieee.org/document/7498245/);
* [CGGCi_RG](https://github.com/eXascaleInfolab/CGGC), paper: [An Ensemble Learning Strategy for Graph Clustering](https://www.cc.gatech.edu/dimacs10/papers/%5B18%5D-dimacs10_ovelgoennegeyerschulz.pdf);
* [SCD](http://www.dama.upc.edu), paper: [High Quality, Scalable and Parallel Community Detection for Large Real Graphs](http://wwwconference.org/proceedings/www2014/proceedings/p225.pdf);
* [randcommuns](/algorithms/randcommuns.py) generates random communities (clusters) having the following properties: the number of nodes in each cluster and the number of clusters are taken from the ground-truth.
