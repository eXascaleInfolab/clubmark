#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:Description: HDF5 dataset conversion to Text/CSV/SSV.
:Authors: (c) Artem Lutov <artem@exascale.info>
:Organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>,
:Date: 2019-05
"""
from __future__ import print_function, division  # Required for stderr output, must be the first import
from functools import partial  # Custom parameterized routes
import argparse
import os
import sys
# import numpy as np
import h5py

try:
	from future.utils import viewvalues, viewitems  #, viewkeys, viewvalues  # External package: pip install future
	from future.builtins import range  #, list
except ImportError:
	def viewMethod(obj, method):
		"""Fetch view method of the object

		obj  - the object to be processed
		method  - name of the target method, str

		return  target method or AttributeError

		>>> callable(viewMethod(dict(), 'items'))
		True
		"""
		viewmeth = 'view' + method
		ometh = getattr(obj, viewmeth, None)
		if not ometh:
			ometh = getattr(obj, method)
		return ometh

	viewitems = lambda dct: viewMethod(dct, 'items')()
	#viewkeys = lambda dct: viewMethod(dct, 'keys')()
	viewvalues = lambda dct: viewMethod(dct, 'values')()

	# Replace range() implementation for Python2
	try:
		range = xrange
	except NameError:
		pass  # xrange is not defined in Python3, which is fine


def parseArgs(params=None):
	"""Parse input parameters (arguments)

	params  - the list of arguments to be parsed (argstr.split()), sys.argv is used if args is None

	return args  - parsed arguments
	"""
	parser = argparse.ArgumentParser(description='HDF5 dataset conversion to CSV/SSV.'
		' The resulting files are outbutted next to the input files as <inpfile>.txt.'
		, formatter_class=argparse.ArgumentDefaultsHelpFormatter)  # Adds default values to the help
	parser.add_argument('datas', metavar='DATSET', nargs='+', help='HDF5 datasets')
	parser.add_argument('-s', '--separator', dest='sep', default=' '
		, help=argparse.SUPPRESS  # Note: not implemented yet
		#, help='values separator in the resulting file'
		)
	parser.add_argument('-o', '--overwrite', action='store_true'
		, help='overwrite existent output files instead of omitting them')
	args = parser.parse_args(params)

	return args


def dataprinter(name, obj, fout, sep):
	if isinstance(obj, h5py.Dataset):
		fout.write('# {}; shape({}): {}'.format(obj.name, len(obj.shape)
			, ', '.join(str(dim) for dim in obj.shape)))
		if obj.attrs:
			fout.write('; attributes({}):\n'.format(len(obj.attrs)))
			for key, val in viewitems(obj.attrs):
				fout.write('#\t{}: {}\n'.format(key, val))
		else:
			fout.write('\n')
		# Consider compound objects
		if obj.dtype.names:
			fout.write('#{}\n'.format('\t'.join('{: >7}'.format(h) for h in obj.dtype.names)))
			for i in range(obj.len()):
				fout.write(' {}\n'.format('\t'.join('{: >7.5}'.format(v) for v in obj[i])))
			fout.write('\n')
		else:
			print('{}\n'.format(obj[:]), file=fout)
		# # np.empy(obj.shape, dtype=obj.dtype)
		# ndims = len(obj.shape)
		# if ndims >= 2:  # inst(row), shuf(col), lev, qmsrun
		# 	# dims = list(obj.shape)
		# 	dims = np.zero(list(obj.shape[2:]), dtype=np.uint16)
		# 	upd = True
		# 	while upd:
		# 		for i, v in range(dims):
		# 		print(obj[:,:,])
		# 	for i in range(dims):
		# 		dims
		# else:
		# 	print('{}'.format(obj[:]), file=fout)
		# 	# fout.write(sep.join(str(v) for v in obj[:]))
		# 	# fout.write('\n')
		# fout.write('\n')


# def outpdatas(fstore, fout, sep):
# 	"""Output datasets from the HDF5 storage to the specified file
#
# 	fstore: h5py.Group  - hdf5 group
# 	fout: FILE  - output file opened for writing
# 	sep: str  - values separator in the output file
# 	"""
# 	for gr in fstore:
# 		if isinstance(gr, h5py.Dataset):
# 			#dataprinter(gr.name, gr, fout, sep)
# 			fout.write('# {}'.format(gr.name))
# 			if gr.attrs:
# 				fout.write(', atributes:\n')
# 				for key, val in viewitems(gr.attrs):
# 					fout.write('#\t{}: {}\n'.format(key, val))
# 			print('{}\n'.format(gr[:]), file=fout)
# 		else:
# 			outpdatas(gr, fout, sep)


def hdf5ToCsv(args):
	"""Convers HDF5 datasets to Text/CSV/SSV

	args.datas: list(str)  - HDF5 datasets
	args.sep: str  - values separator
	args.overwrite: bool  - overwrite existent output files instead of skipping them
	"""
	outpext = '.txt' if not args.sep.startswith(',') else '.csv'  # Default output extension
	for inpfile in args.datas:
		ublock = None
		try:
			fstore = h5py.File(inpfile, mode='r')  # ATTENTION: 'latest' libver viewing is not fully supported after HDFView 2.7.1
			ublocksize = fstore.userblock_size
			fstore.close()
			with open(inpfile, 'rb') as fstore:
				ublock = fstore.read(ublocksize).decode().rstrip('\0')
		except OSError:
			print('WARNING, can not open the file {}.'.format(inpfile, file=sys.stderr))
		with h5py.File(inpfile, mode='r', driver='core', libver='latest') as fstore:
			inpname, inpext = os.path.splitext(inpfile)
			# Prevent overwriting of the input files
			if inpext == outpext:
				inpname += inpext
			outname = inpname + outpext
			if os.path.isfile(outname):
				if args.overwrite:
					print('WARNING, overwriting the existent', outname)
				else:
					print('WARNING, omitting overwriting of the existent', outname)
					continue
			with open(inpname + outpext, 'w') as fout:
				fout.write('# Converted from {}\n'.format(os.path.split(inpfile)[1]))
				if ublock:
					fout.write('#\tUserblock: {}\n'.format(ublock))
				if fstore.attrs:
					fout.write('#\tAttributes({}):  '.format(len(fstore.attrs)))
					for key, val in viewitems(fstore.attrs):
						fout.write('{}: {}; '.format(key, val))
					fout.write('\n')
				fout.write('\n')
				fstore.visititems(partial(dataprinter, fout=fout, sep=args.sep))
				# outpdatas(fstore, fout, args.sep)

if __name__ == '__main__':
	hdf5ToCsv(parseArgs())
