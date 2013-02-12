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

class OSMMemStore():
    def __init__(self):
        self.ways  = {}
        self.nodes = {}
        self.relations = {}

        self.numnodes = 0
        self.numways = 0
        self.numrelations = 0

    # "commit" is called after the import is finished 
    # to wrap any pending things from the datastore up
    # (e.g. commiting changes to database)
    def commit(self):
        pass
    
    # "cleanup" is called at the end of osm2spatialite.py
    def cleanup(self):
        pass
    
    # "Add" functions
    def addNode(self, object):            
        self.nodes[object["id"]] = object
    
    def addWay(self, object):
        self.ways[object["id"]] = object
    
    def addRelation(self, object):
        self.relations[object["id"]] = object

    # "Delete" functions                
    def delWays(self, osm_ids):
        for osm_id in osm_ids:
            try:
                del self.ways[osm_id]
            except:
                pass		
        
    # "Iteration" functions to browse through all data
    def getNodesIter(self):
        return self.nodes.itervalues()
        
    def getWaysIter(self):
        return self.ways.itervalues()
        
    def getRelationsIter(self):
        return self.relations.itervalues()
        
    # Count data length
    def getNumNodes(self):
        return len(self.nodes)
    def getNumWays(self):
        return len(self.ways)
    def getNumRelations(self):
        return len(self.relations)
                   
   # "Get" functions 
    def _getSet(self, osm_ids, func):
        result = {}
        for osm_id in osm_ids:
            result[osm_id] = func(id)
        return result
    
    def getNode(self, osm_id):
        try:
            return self.nodes[osm_id]
        except KeyError:
            return None
    
    def getNodes(self, osm_ids):
        return self._getSet(osm_ids, self.getNode)
        
    def getWay(self, osm_id):
        try:
            return self.ways[osm_id]
        except KeyError:
            return None
    
    def getWays(self, osm_ids):
        return self._getSet(osm_ids, self.getWay)
        
    def getRelation(self, osm_id):
        try:
            return self.relations[osm_id]
        except KeyError:
            return None
    
    def getRelations(self, osm_ids):
        return self._getSet(osm_ids, self.getRelation)
        
