#!/bin/sh
#
# This is internal script to sync benchmarking components to the latest version

# Make target dirs if have not been existed yet
mkdir -pv algorithms/utils/louvain/ algorithms/daoc/ algorithms/ganxis/ formats/

# File Formats Specificaitons --------------------------------------------------
rsync -aLhv ../daoc/common/format.cnl\
	 ../daoc/common/format.nsl\
	 \
	 formats/

# Utilities --------------------------------------------------------------------
rsync -aLhv ../../system/ExecTime/bin/Release/exectime\
	\
	../daoc/common/convert.py\
	../daoc/common/remlinks.py\
	../daoc/common/batch_run_brief.sh\
	\
	../../system/PyExPool/mpepool.py\
	../../system/PyExPool/mpewui.py\
	\
	../xmeasures/bin/Release/xmeasures\
	../gecmi_c++/bin/Release/gecmi\
	../onmi/bin/Release/onmi\
	../resmerge/bin/Release/resmerge\
	\
	../lfrbench_undir_weight_ovp/lfrbench_udwov\
	\
	utils/

# Algorithms accessory utils
rsync -aLhv ../daoc/common/parser_nsl.py algorithms/utils/

# Louvain accessory utils
rsync -aLhv ../oslom/OSLOM2/convert\
	 ../oslom/OSLOM2/hierarchy\
	 \
	 algorithms/utils/louvain/

rsync -aLhv ../oslom/OSLOM2/community algorithms/louvain

# Custering algorithms ---------------------------------------------------------
# Note: oslom_undir can be used for the symmetric networks specified with the arcs
rsync -aLhv\
	../cggc_rg/bin/Release/rgmc\
	../oslom/OSLOM2/oslom_undir\
	../oslom/OSLOM2/oslom_dir\
	../pscan/bin/Release/pscan\
	../scd/build/scd\
	\
	algorithms/
	
# SCP
rsync -aLhv ../scp_0.1/kclique.py algorithms/scp.py

# GANXiS
rsync -aLhv\
	/home/lav/exascale/Papers/DataAnalysis/Clustering/Communities/Evaluation/Benchmarks/AlorithmsImpl/GANXiS_v3.0.2/GANXiS_v3.0.2/commons-collections-3.2.1.jar\
	/home/lav/exascale/Papers/DataAnalysis/Clustering/Communities/Evaluation/Benchmarks/AlorithmsImpl/GANXiS_v3.0.2/GANXiS_v3.0.2/GANXiSw.jar\
	\
	algorithms/ganxis/

# DAOC
rsync -aLhv\
	../daoc/lib/bin/Release/libdaoc.so\
	../daoc/cli/bin/Release/daoc\
	\
	algorithms/daoc/
