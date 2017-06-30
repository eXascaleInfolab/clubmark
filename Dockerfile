# Use the specified base image.
# All evaluating algorithms are built under Ubuntu 16.04
FROM ubuntu:16.04

# Specify the working directory (created if did not exist)
WORKDIR /opt/benchmark

# Copy required files to the container WORKDIR
# ADD src dest

# Install Ubuntu dependencies
# - Python scripts:  python
# Python2 can be used for all .py files, but it is recommended to use
# Python3 for most of the files (scp.py supports only Python2) and pypy[2]
# for the heavy python apps that do not link C libs (scp, ...)
# - Accessory libraries:
# -- python-igraph:  libxml2-dev zlib1g-dev (Virtual Package: libz-dev)
# - Clustering Algorithms:
# -- ganxis:  openjdk-8-jre  (openjdk >= 7)
# -- rgmc:  libboost-program-options1.58.0
# - Evaluation Apps & Utilities:
# -- gecmi:  libtbb2
# -- remlinks.py: numpy future
RUN apt-get update && apt-get install -y \
	python3 python3-pip pypy \
	libxml2-dev zlib1g-dev \
	openjdk-8-jre \
	libboost-program-options1.58.0 \
	libtbb2

RUN pip3 install --upgrade pip

# Install Python dependencies
# louvain_igraph.py:  python-igraph
RUN pip install -r pyreqs.txt

# Make port 80 available to the world outside this container
#EXPOSE 80

# Run something when the container launches
#CMD ["python", "benchmark.py"]
#
# ATTENTION: Benchmarking in daemon mode should be run only if the Docker is run
# in the interactive mode, not detached:
# https://docs.docker.com/engine/reference/run/#detached--d
#CMD ["python", "benchmark_daemon.sh"]
#CMD ["bash"]
