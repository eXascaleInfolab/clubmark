#!/bin/sh
#
# This is internal script to sync benchmarking components to the latest version

# Make target dirs if have not been existed yet
mkdir -pv utils/lfrbench/ utils/louvain/ algorithms/daoc/

# Utilities
rsync -aLh ../../system/ExecTime/bin/Release/exectime\
	\
	../daoc/common/convert.py\
	../daoc/common/remlinks.py\
	../daoc/common/batch_run_brief.sh\
	\
	../../system/PyExPool/mpepool.py\
	\
	../xmeasures/bin/Release/xmeasures\
	../gecmi_c++/bin/Release/gecmi\
	../onmi/bin/Release/onmi\
	../resmerge/bin/Release/resmerge\
	\
	utils/

# LFR benchmark generator
rsync -aLhv ../lfrbench_undir_weight_ovp/lfrbench_udwov\
	utils/lfrbench/

# Louvain accessory utils
rsync -aLh ../oslom/OSLOM2/convert\
	 ../oslom/OSLOM2/hierarchy\
	 \
	 utils/louvain/

# Custering algorithms
rsync -aLh\
	/home/lav/exascale/Papers/DataAnalysis/Clustering/Communities/Evaluation/Benchmarks/AlorithmsImpl/GANXiS_v3.0.2/GANXiS_v3.0.2/commons-collections-3.2.1.jar\
	/home/lav/exascale/Papers/DataAnalysis/Clustering/Communities/Evaluation/Benchmarks/AlorithmsImpl/GANXiS_v3.0.2/GANXiS_v3.0.2/GANXiSw.jar\
	\
	../cggc_rg/bin/Release/rgmc\
	../oslom/OSLOM2/oslom_undir\
	../pscan/bin/Release/pscan\
	../scd/build/scd\
	\
	algorithms/
	
# SCP
rsync -aLh ../scp_0.1/kclique.py algorithms/scp.py

# DAOC
rsync -aLh\
	../daoc/lib/bin/Release/libdaoc.so\
	../daoc/cli/bin/Release/daoc\
	\
	algorithms/daoc/
