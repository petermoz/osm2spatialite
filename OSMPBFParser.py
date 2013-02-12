#
#  osm2spatialite
#  Copyright (C) 2011 Daniel Sabo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import fileformat_pb2,osmformat_pb2
import struct
import zlib
import os.path
#import time

NANODEG = .000000001

class OSMPBFParser():
    def __init__(self):
        self.blob_header = fileformat_pb2.BlockHeader()
        self.blob = fileformat_pb2.Blob()
        
        self.pb = osmformat_pb2.PrimitiveBlock()
        
        self.pbf_file = None
        
        self.endElementFilters = []
        
    def reportProgress(self, progress):
        pass
    
    def reportFinished(self):
        pass
    
    def parse(self, filename, datastore):
        self.pbf_file = open(filename, "r")
        self.datastore = datastore
        
        self.nodeCount = 0
        self.wayCount = 0
        self.relCount = 0
        
        self.filesize = os.path.getsize(filename)
        self.pstart = self.pbf_file.tell()
        
        try:
            while self.readBlob():
                pass
        finally:
            self.pbf_file.close()
            self.pbf_file = None
            
        self.reportFinished()
        
    def readBlob(self):
#        t0 = time.time()
        data = self.pbf_file.read(4)
        if not data:
            return False

        size = struct.unpack("!I", data)[0]
        
        data = self.pbf_file.read(size)
        self.blob_header.ParseFromString(data)
        data = self.pbf_file.read(self.blob_header.datasize)
        self.blob.ParseFromString(data)
        
        if self.blob.raw:
            data = self.blob.raw
        elif self.blob.zlib_data:
            data = zlib.decompress(self.blob.zlib_data,15,self.blob.raw_size)
        elif self.blob.lzma_data:
            raise Exception("Unsupported compression: lzma")
        elif self.blob.bzip2_data:
            raise Exception("Unsupported compression: bzip2")
        
        self.pb = osmformat_pb2.PrimitiveBlock()
        self.pb.ParseFromString(data)
        
        granularity = self.pb.granularity or 100
        lat_offset  = self.pb.lat_offset or 0
        lon_offset  = self.pb.lat_offset or 0
        date_granularity = self.pb.date_granularity or 1000
        
        def denseTagYielder(dense, stringtable):
            kv = dense.keys_vals
            if not kv:
                return
            tags = {}
            i = 0
            while i < len(kv):
                key = kv[i]
                if 0 == key:
                    yield tags
                    tags = {}
                else:
                    i += 1
                    tags[stringtable[key].decode("utf-8")] = stringtable[kv[i]].decode("utf-8")
                i += 1
        
        def denseYielder(dense, stringtable):
            last_id  = 0
            last_lat = 0.0
            last_lon = 0.0
            
            tagger = denseTagYielder(dense, stringtable)
            for i,osm_id in enumerate(dense.id):
                lat = .000000001 * (lat_offset + (granularity * dense.lat[i]))
                lon = .000000001 * (lon_offset + (granularity * dense.lon[i]))
                
                if dense.keys_vals:
                    tags = tagger.next()
                else:
                    tags = {}
                osm_id = osm_id + last_id
                lat = lat + last_lat
                lon = lon + last_lon
                yield {"id":osm_id, "point":[lon, lat], "tags":tags, "version":-1}
                last_id  = osm_id
                last_lat = lat
                last_lon = lon
        
        for group in self.pb.primitivegroup:
            for node in group.nodes:
                tags = {}
                for k,v in zip(node.keys, node.vals):
                    tags[self.pb.stringtable.s[k].decode("utf-8")] = self.pb.stringtable.s[v].decode("utf-8")
                    
                lat = .000000001 * (lat_offset + (granularity * node.lat))
                lon = .000000001 * (lon_offset + (granularity * node.lon))
                
                self.parsedNode({"id":node.id, "point":[lon, lat], "tags":tags, "version":-1})
            if group.dense:
                #print "Dense: Nodes:", len(group.dense.id)
                for node in denseYielder(group.dense, self.pb.stringtable.s):
                    self.parsedNode(node)
            for way in group.ways:
                tags = {}
                for k,v in zip(way.keys, way.vals):
                    tags[self.pb.stringtable.s[k].decode("utf-8")] = self.pb.stringtable.s[v].decode("utf-8")
                
                refs = []
                last_ref = 0
                for ref in way.refs:
                    ref = ref + last_ref
                    refs.append(ref)
                    last_ref = ref
                
                self.parsedWay({"id":way.id, "nodes":refs, "tags":tags, "version":-1})
            for rel in group.relations:
                tags = {}
                for k,v in zip(rel.keys, rel.vals):
                    tags[self.pb.stringtable.s[k].decode("utf-8")] = self.pb.stringtable.s[v].decode("utf-8")
                
                members = []
                last_ref = 0
                for role,ref,ref_type in zip(rel.roles_sid, rel.memids, rel.types):
                    ref = ref + last_ref
                    #members.append([{0:"N", 1:"W", 2:"R"}[ref_type], ref, self.pb.stringtable.s[role]])
                    members.append({
                        "type":{0:"node", 1:"way", 2:"relation"}[ref_type],
                        "ref":ref,
                        "role":self.pb.stringtable.s[role]})
                    last_ref = ref
                    
                self.parsedRelation({"id":rel.id, "members":members, "tags":tags, "version":-1})
        
        
#        percent = self.pbf_file.tell() / float(self.filesize) * 100.0

#        thispercent = ((self.pbf_file.tell() - self.pstart) / float(self.filesize - self.pstart)) * 100.0
#        totalTime = time.time() - self.tstart
#        remaining = totalTime / (thispercent / 100)
#        remaining = "%d:%02d:%07.4f" % (
#          int(remaining / 3600),
#          int(remaining / 60) % 60,
#          remaining % 60,
#        )

#        print "%.2f%% (%d nodes, %d ways, %d relations) (%.4fs) est %s\r" % \
#          (percent,
#          self.objectReadCount[0],
#          self.objectReadCount[1],
#          self.objectReadCount[2],
#          time.time() - t0,
#          remaining,)


        self.reportProgress({
            "nodes":self.nodeCount,
            "ways":self.wayCount,
            "relations":self.relCount,
            "filesize":self.filesize,
            "filepos":self.pbf_file.tell(),
            })
        
        return True
    
    def parsedNode(self, node):
        for endFilter in self.endElementFilters:
            node = endFilter.testElement("node", node)
        
        self.datastore.addNode(node)
        self.nodeCount += 1
        
    def parsedWay(self, way):
        for endFilter in self.endElementFilters:
            way = endFilter.testElement("way", way)
        
        self.datastore.addWay(way)
        self.wayCount += 1
        
    def parsedRelation(self, rel):
        for endFilter in self.endElementFilters:
            rel = endFilter.testElement("relation", rel)
        
        self.datastore.addRelation(rel)
        self.relCount += 1
    