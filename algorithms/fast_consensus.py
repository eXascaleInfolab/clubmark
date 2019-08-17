#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function  # Required for stderr output, must be the first import
import os
import random
import math
import argparse
import multiprocessing as mp
import networkx as nx
import numpy as np
import igraph as ig
import community as cm
# from networkx.algorithms import community as cm


def check_consensus_graph(G, n_p, delta):
    '''
    This function checks if the networkx graph has converged.
    Input:
    G: networkx graph
    n_p: number of partitions while creating G
    delta: if more than delta fraction of the edges have weight != n_p then returns False, else True
    '''
    count = 0

    for wt in nx.get_edge_attributes(G, 'weight').values():
        if wt != 0 and wt != n_p:
            count += 1

    if count > delta*G.number_of_edges():
        return False

    return True


def nx_to_igraph(Gnx):
    '''
    Function takes in a network Graph, Gnx and returns the equivalent
    igraph graph g
    '''
    # g = ig.Graph(n=Gnx.number_of_nodes())
    # # graph.vs["name"] = Gnx.nodes()
    # g.add_edges(sorted(Gnx.edges()))
    g = ig.Graph(sorted(Gnx.edges()))
    g.es['weight'] = 1.0
    for edge in Gnx.edges():
        g[edge[0], edge[1]] = Gnx[edge[0]][edge[1]]['weight']
    return g


def group_to_partition(partition):
    '''
    Takes in a partition, dictionary in the format {node: community_membership}
    Returns a nested list of communities [[comm1], [comm2], ...... [comm_n]]
    '''
    part_dict = {}

    for index, value in partition.items():

        if value in part_dict:
            part_dict[value].append(index)
        else:
            part_dict[value] = [index]


    return part_dict.values()


def validate_arguments(args, algorithms):
    if args.delta < 0.02:
        raise ValueError('delta is too low. Allowed values are between 0.02 and 0.2')
    if args.delta > 0.2:
        raise ValueError('delta is too high. Allowed values are between 0.02 and 0.2')

    if args.alg not in algorithms:
        raise ValueError('Incorrect algorithm entered. run with -h for help')
    if args.tau < 0 or args.tau > 1:
        raise ValueError('Incorrect tau. run with -h for help')
    if args.procs < 1:
        raise ValueError('The number of worker processes shuould be positive')
    if args.parts <=0 or args.outp_parts > args.parts:
        raise ValueError('Invalid number of the output/input partitons is specified: {}/{}'.format(args.outp_parts, args.parts))


def louvain_community_detection(networkx_graph):
    """
    Do louvain community detection
    :param networkx_graph:
    :return:
    """
    return cm.partition_at_level(cm.generate_dendrogram(networkx_graph, randomize=True, weight='weight'), 0)


def get_yielded_graph(graph, times):
    """
    Creates an iterator containing the same graph object multiple times. Can be used for applying multiprocessing map
    """
    for _ in range(times):
        yield graph


def fast_consensus(G,  algorithm='louvain', n_p=20, thresh=0.2, delta=0.02, procs=mp.cpu_count()):
    """Fast consensus algorithm

    return communities  - resulting communities
        placeholder_nds  - whether placeholder nodes are used by the igraph, which happens for
            the non-contiguous node range or node ids not starting from 0
    """
    graph = G.copy()
    L = G.number_of_edges()
    N = G.number_of_nodes()

    for u,v in graph.edges():
        graph[u][v]['weight'] = 1.0

    while(True):
        if (algorithm == 'louvain'):
            nextgraph = graph.copy()
            L = G.number_of_edges()
            for u,v in nextgraph.edges():
                nextgraph[u][v]['weight'] = 0.0

            with mp.Pool(processes=procs) as pool:
                communities_all = pool.map(louvain_community_detection, get_yielded_graph(graph, n_p))
            for node,nbr in graph.edges():
                if (node,nbr) in graph.edges() or (nbr, node) in graph.edges():
                    if graph[node][nbr]['weight'] not in (0,n_p):
                        for i in range(n_p):
                            communities = communities_all[i]
                            if communities[node] == communities[nbr]:
                                nextgraph[node][nbr]['weight'] += 1

            remove_edges = []
            for u,v in nextgraph.edges():
                if nextgraph[u][v]['weight'] < thresh*n_p:
                    remove_edges.append((u, v))

            nextgraph.remove_edges_from(remove_edges)
            if check_consensus_graph(nextgraph, n_p=n_p, delta=delta):
                break

            for _ in range(L):
                node = np.random.choice(nextgraph.nodes())
                neighbors = [a[1] for a in nextgraph.edges(node)]
                if (len(neighbors) >= 2):
                    a, b = random.sample(set(neighbors), 2)
                    if not nextgraph.has_edge(a, b):
                        nextgraph.add_edge(a, b, weight = 0)
                        for i in range(n_p):
                            communities = communities_all[i]
                            if communities[a] == communities[b]:
                                nextgraph[a][b]['weight'] += 1

            for node in nx.isolates(nextgraph):
                    nbr, weight = sorted(graph[node].items(), key=lambda edge: edge[1]['weight'])[0]
                    nextgraph.add_edge(node, nbr, weight=weight['weight'])
            graph = nextgraph.copy()
            if check_consensus_graph(nextgraph, n_p=n_p, delta=delta):
                break

        elif (algorithm in ('infomap', 'lpm')):
            nextgraph = graph.copy()
            for u,v in nextgraph.edges():
                nextgraph[u][v]['weight'] = 0.0

            if algorithm == 'infomap':
                communities = [{frozenset(c) for c in nx_to_igraph(graph).community_infomap().as_cover()} for _ in range(n_p)]
            if algorithm == 'lpm':
                communities = [{frozenset(c) for c in nx_to_igraph(graph).community_label_propagation().as_cover()} for _ in range(n_p)]

            for node, nbr in graph.edges():
                for i in range(n_p):
                    for c in communities[i]:
                        if node in c and nbr in c:
                            if not nextgraph.has_edge(node,nbr):
                                nextgraph.add_edge(node, nbr, weight = 0)
                            nextgraph[node][nbr]['weight'] += 1

            remove_edges = []
            for u,v in nextgraph.edges():
                if nextgraph[u][v]['weight'] < thresh*n_p:
                    remove_edges.append((u, v))
            nextgraph.remove_edges_from(remove_edges)

            for _ in range(L):
                node = np.random.choice(nextgraph.nodes())
                neighbors = [a[1] for a in nextgraph.edges(node)]
                if (len(neighbors) >= 2):
                    a, b = random.sample(set(neighbors), 2)
                    if not nextgraph.has_edge(a, b):
                        nextgraph.add_edge(a, b, weight = 0)
                        for i in range(n_p):
                            if a in communities[i] and b in communities[i]:
                                nextgraph[a][b]['weight'] += 1

            graph = nextgraph.copy()
            if check_consensus_graph(nextgraph, n_p=n_p, delta=delta):
                break
        elif (algorithm == 'cnm'):
            nextgraph = graph.copy()
            for u,v in nextgraph.edges():
                nextgraph[u][v]['weight'] = 0.0

            communities = []
            mapping = []
            inv_map = []
            for _ in range(n_p):
                order = list(range(N))
                random.shuffle(order)
                maps = dict(zip(range(N), order))

                mapping.append(maps)
                inv_map.append({v: k for k, v in maps.items()})
                G_c = nx.relabel_nodes(graph, mapping = maps, copy = True)
                G_igraph = nx_to_igraph(G_c)

                communities.append(G_igraph.community_fastgreedy(weights = 'weight').as_clustering())
            for i in range(n_p):
                edge_list = [(mapping[i][j], mapping[i][k]) for j,k in graph.edges()]
                for node,nbr in edge_list:
                    a, b = inv_map[i][node], inv_map[i][nbr]
                    if graph[a][b] not in (0, n_p):
                        for c in communities[i]:
                            if node in c and nbr in c:
                                nextgraph[a][b]['weight'] += 1

            remove_edges = []
            for u,v in nextgraph.edges():
                if nextgraph[u][v]['weight'] < thresh*n_p:
                    remove_edges.append((u, v))
            nextgraph.remove_edges_from(remove_edges)

            for _ in range(L):
                node = np.random.choice(nextgraph.nodes())
                neighbors = [a[1] for a in nextgraph.edges(node)]

                if (len(neighbors) >= 2):
                    a, b = random.sample(set(neighbors), 2)
                    if not nextgraph.has_edge(a, b):
                        nextgraph.add_edge(a, b, weight = 0)
                        for i in range(n_p):
                            for c in communities[i]:
                                if mapping[i][a] in c and mapping[i][b] in c:
                                    nextgraph[a][b]['weight'] += 1
            if check_consensus_graph(nextgraph, n_p, delta):
                break
        else:
            break

    communities = None
    placeholder_nds = False
    if (algorithm == 'louvain'):
        with mp.Pool(processes=procs) as pool:
            communities = pool.map(louvain_community_detection, get_yielded_graph(graph, n_p))
    elif algorithm == 'cnm':
        communities = []
        mapping = []
        inv_map = []
        for _ in range(n_p):
            order = list(range(N))
            random.shuffle(order)
            maps = dict(zip(range(N), order))

            mapping.append(maps)
            inv_map.append({v: k for k, v in maps.items()})
            G_c = nx.relabel_nodes(graph, mapping=maps, copy=True)
            G_igraph = nx_to_igraph(G_c)
            if len(G_igraph.vs) != graph.number_of_nodes():
                placeholder_nds = True
            communities.append(G_igraph.community_fastgreedy(weights = 'weight').as_clustering())
    else:
        ig_graph = nx_to_igraph(graph)
        if len(ig_graph.vs) != graph.number_of_nodes():
            placeholder_nds = True
        if algorithm == 'infomap':
            communities = [{frozenset(c) for c in ig_graph.community_infomap().as_cover()} for _ in range(n_p)]
        if algorithm == 'lpm':
            communities = [{frozenset(c) for c in ig_graph.community_label_propagation().as_cover()} for _ in range(n_p)]

    return communities, placeholder_nds


if __name__ == "__main__":
    algorithms = ('louvain', 'lpm', 'cnm', 'infomap')  # Clustering algorithms

    parser = argparse.ArgumentParser(description='Fast consensus clustering algorithm.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    nparts = 20
    parser.add_argument('-f', '--network-file', dest='inpfile', type=str, nargs='?', help='file with edgelist')
    parser.add_argument('-a', '--algorithm', dest='alg', type=str, nargs='?', default='louvain' , help='underlying clustering algorithm: {}'.format(', '.join(algorithms)))
    parser.add_argument('-p', '--partitions', dest='parts', type=int, nargs='?', default=nparts, help='number of input partitions for the algorithm')
    parser.add_argument('--outp-parts', dest='outp_parts', type=int, nargs='?', default=None, help='number of partitions to be outputted, <= input partitions')
    parser.add_argument('-t', '--tau', dest='tau', type=float, nargs='?', help='used for filtering weak edges')
    parser.add_argument('-d', '--delta', dest='delta', type=float,  nargs='?', default=0.02, help='convergence parameter. Converges when less than delta proportion of the edges are with wt = 1')
    parser.add_argument('-w', '--worker-procs', dest='procs', type=int, default=mp.cpu_count(), help='number of parallel worker processes for the clustering')
    parser.add_argument('-o', '--output-dir', dest='outdir', type=str, nargs='?', default='out_partitions', help='output directory')

    args = parser.parse_args()

    default_tau = {'louvain': 0.2, 'cnm': 0.7 ,'infomap': 0.6, 'lpm': 0.8}
    if args.tau is None:
        args.tau = default_tau.get(args.alg, 0.2)
    if args.outp_parts is None:
       args.outp_parts = args.parts

    validate_arguments(args, algorithms)

    G = nx.read_edgelist(args.inpfile, nodetype=int, data=(('weight',float),))
    output, placeholder_nds = fast_consensus(G, algorithm=args.alg, n_p=args.parts, thresh=args.tau, delta=args.delta, procs=args.procs)

    if not os.path.exists('out_partitions'):
        os.makedirs('out_partitions')

    if(args.alg == 'louvain'):
        for i in range(len(output)):
            output[i] = group_to_partition(output[i])

    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)
    if not args.outdir.endswith('/'):
        args.outdir += '/'
    ofbase = args.outdir + os.path.splitext(os.path.split(args.inpfile)[1])[0]

    oftpl = '{{}}_d{:.2}_{{:0{}d}}.cnl'.format(args.delta, int(math.ceil(math.log10(len(output)))))
    for i, partition in enumerate(output):
        if i >= args.outp_parts:
            break
        with open(oftpl.format(ofbase, i), 'w') as f:
            for community in partition:
                # Placeholder nodes of igraph form disconnected clusters, filter them out.
                # Typically it happens when node ids in the edges file start from 1+ instead of 0
                if placeholder_nds and len(community) == 1:
                    continue
                print(*community, file=f)
