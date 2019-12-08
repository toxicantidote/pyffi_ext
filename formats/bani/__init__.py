# ***** BEGIN LICENSE BLOCK *****
#
# Copyright (c) 2007-2012, Python File Format Interface
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#	 * Redistributions of source code must retain the above copyright
#	   notice, this list of conditions and the following disclaimer.
#
#	 * Redistributions in binary form must reproduce the above
#	   copyright notice, this list of conditions and the following
#	   disclaimer in the documentation and/or other materials provided
#	   with the distribution.
#
#	 * Neither the name of the Python File Format Interface
#	   project nor the names of its contributors may be used to endorse
#	   or promote products derived from this software without specific
#	   prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# ***** END LICENSE BLOCK *****

import struct
import os
import re
import io
import math

import pyffi.object_models.xml
import pyffi.object_models.common
import pyffi.object_models

def make_interpolater(left_min, left_max, right_min, right_max): 
    # Figure out how 'wide' each range is  
    leftSpan = left_max - left_min  
    rightSpan = right_max - right_min  

    # Compute the scale factor between left and right values 
    scaleFactor = float(rightSpan) / float(leftSpan) 

    # create interpolation function using pre-calculated scaleFactor
    def interp_fn(value):
        return right_min + (value-left_min)*scaleFactor

    return interp_fn


def export_key(key):

	# this seems to be a modulo equivalent
	k = [x for x in key]
	for i in range(3):
		# if k[i] < -180:
			# k[i]+= 360
		if k[i] < -90:
			k[i] = 360 - k[i]
	k[0]-=90
	k[2]+=90
	# calculate short
	k = [int(x/180*32768-16385) for x in k]
	return k

	
class BaniFormat(pyffi.object_models.xml.FileFormat):
	"""This class implements the Bani format."""
	xml_file_name = 'bani.xml'
	# where to look for bani.xml and in what order:
	# BANIXMLPATH env var, or BaniFormat module directory
	xml_file_path = [os.getenv('BANIXMLPATH'), os.path.dirname(__file__)]
	# file name regular expression match
	RE_FILENAME = re.compile(r'^.*\.bani$', re.IGNORECASE)
	# used for comparing floats
	_EPSILON = 0.0001

	# basic types
	int = pyffi.object_models.common.Int
	uint64 = pyffi.object_models.common.UInt64
	uint = pyffi.object_models.common.UInt
	byte = pyffi.object_models.common.Byte
	ubyte = pyffi.object_models.common.UByte
	char = pyffi.object_models.common.Char
	short = pyffi.object_models.common.Short
	ushort = pyffi.object_models.common.UShort
	float = pyffi.object_models.common.Float
	SizedString = pyffi.object_models.common.SizedString
	ZString = pyffi.object_models.common.ZString
	
	class Data(pyffi.object_models.FileFormat.Data):
		"""A class to contain the actual Bani data."""
		def __init__(self):
			self.version = 0
			self.header = BaniFormat.BaniInfoHeader()
			# the output array
			self.bones_frames_eulers = []
			self.bones_frames_locs = []
			# input
			self.keys = []
		
		def inspect_quick(self, stream):
			"""Quickly checks if stream contains DDS data, and gets the
			version, by looking at the first 8 bytes.

			:param stream: The stream to inspect.
			:type stream: file
			"""
			pass

		# overriding pyffi.object_models.FileFormat.Data methods

		def inspect(self, stream):
			"""Quickly checks if stream contains DDS data, and reads the
			header.

			:param stream: The stream to inspect.
			:type stream: file
			"""
			pos = stream.tell()
			try:
				self.inspect_quick(stream)
				self.header.read(stream, data=self)
			finally:
				stream.seek(pos)
		
		def read(self, stream, verbose=0, file=""):
			"""Read a dds file.

			:param stream: The stream from which to read.
			:type stream: ``file``
			"""
			# store file name for later
			if file:
				self.file = file
				self.dir, self.basename = os.path.split(file)
				self.file_no_ext = os.path.splitext(self.file)[0]
			# read the file
			self.header.read(stream, data=self)
			
			# create function for doing interpolation of the desired ranges
			center = self.header.data_1.translation_center
			first = self.header.data_1.translation_first
			self.scaler = make_interpolater(0, 65535, first, center-first)
			
			# read banis array according to bani header
			self.read_banis()
			# print(self.bones_frames_locs)
			
		def read_banis(self,):
			# get banis file
			banis_path = os.path.join(self.dir, self.header.banis_name.decode() )
			
			# todo: check exists
			
			# create list of frames for each bone
			for bone_i in range(self.header.data_1.num_bones):
				self.bones_frames_eulers.append( [] )
				self.bones_frames_locs.append( [] )
			
			with open(banis_path, 'rb') as banis:
				# seek to the starting position
				banis.seek(self.header.data_0.read_start_frame * self.header.data_1.bytes_per_frame)
				# read frames for this bani from banis buffer
				for frame_i in range(self.header.data_0.num_frames):
					for bone_i in range(self.header.data_1.num_bones):
					
						in_key = BaniFormat.Key()
						in_key.read(banis, data=self)
						euler, loc = self.import_key(in_key)
						
						# this is irreversible, fixing gimbal issues in baked anims; game fixes these as well and does not mind our fix
						if self.bones_frames_eulers[bone_i]:
							# get previous euler for this bone
							last_euler = self.bones_frames_eulers[bone_i][-1]
							for key_i in range(3):
								# found weird axis cross, correct for it
								if abs(euler[key_i]-last_euler[key_i]) > 45:
									euler[key_i] = math.copysign((180-euler[key_i]), last_euler[key_i])
							
						self.bones_frames_eulers[bone_i].append( euler )
						self.bones_frames_locs[bone_i].append( loc )
					
		def import_key(self, key):
			# calculate degrees
			e = [(x+16385)*180/32768 for x in (key.euler.x, key.euler.y, key.euler.z)]
			e[0]+=90
			e[2]-=90
			# this seems to be a modulo equivalent
			for i in range(3):
				if e[i] > 180:
					e[i]-= 360

			l = [self.scaler(x) for x in (key.translation.x, key.translation.y, key.translation.z)]
			return e, l
			
		def encode_eulers(self,):
			
			# todo: update array size
		
			eulers = [self.eulers_dict[bone_name] for bone_name in self.header.names]
			# print(eulers)
			# print(list(zip(eulers)))
			num_bones = len(self.header.names)
			num_frames = len(eulers[0])
			for bone_i in range(num_bones):
				for frame_i in range(num_frames):
					in_key = eulers[bone_i][frame_i]
					out_key = self.header.keys[frame_i][bone_i]
					# todo: actually store the exported value
					# print(export_key(in_key), out_key)
			
		def write(self, stream, verbose=0):
			"""Write a dds file.

			:param stream: The stream to which to write.
			:type stream: ``file``
			:param verbose: The level of verbosity.
			:type verbose: ``int``
			"""

			# write the file
			# first header
			self.encode_eulers()
			self.header.write(stream, data=self)
