#
#  osm2spatialite
#  Copyright (C) 2011 Daniel Genrich
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

import cPickle
import math

try:
    # Use the KyngChaos sqlite3 if it's available, otherwise try the standard one
    from pysqlite2 import dbapi2 as sqlite
except ImportError:
    import sqlite3 as sqlite 

class OSMSQLiteStore():
    def __init__(self, db):
        if db == None:
            raise

        self.ways  = {}
        self.nodes = {}
        self.relations = {}

        self.numnodes = 0
        self.numways = 0
        self.numrelations = 0

        self.db = db
        self.cursor = None

        if self.db != None:
            self.cursor = db.cursor()

        # init database for temporary storage
        self.cursor.execute("DROP TABLE IF EXISTS \"tmpNodes\";")
        self.cursor.execute("CREATE TABLE \"tmpNodes\" (\"id\" INTEGER PRIMARY KEY NOT NULL, \"object\" BLOB);")      
        self.cursor.execute("DROP TABLE IF EXISTS \"tmpWays\";")
        self.cursor.execute("CREATE TABLE \"tmpWays\" (\"id\" INTEGER PRIMARY KEY NOT NULL, \"object\" BLOB);") 
        self.cursor.execute("DROP TABLE IF EXISTS \"tmpRels\";")
        self.cursor.execute("CREATE TABLE \"tmpRels\" (\"id\" INTEGER PRIMARY KEY NOT NULL, \"object\" BLOB);")  
        
    def commit(self):
        # save nodes
        self.cursor.executemany("insert into \"tmpNodes\" values (?,?)", self.nodes.iteritems() )
        self.nodes.clear()
        del self.nodes
        self.nodes = {}
        
        # save ways
        self.cursor.executemany("insert into \"tmpWays\" values (?,?)", self.ways.iteritems() )
        self.ways.clear()
        del self.ways
        self.ways = {}
        
        # save relations
        self.cursor.executemany("insert into \"tmpRels\" values (?,?)", self.relations.iteritems() )
        self.relations.clear()
        del self.relations
        self.relations = {}
        
        self.db.commit()
        
    def cleanup(self):
        # drop temporary tables
        self.cursor.execute("DROP TABLE IF EXISTS \"tmpNodes\";")
        self.cursor.execute("DROP TABLE IF EXISTS \"tmpWays\";")
        self.cursor.execute("DROP TABLE IF EXISTS \"tmpRels\";")
        
        # speedup database
        self.db.commit()
        self.cursor.execute("ANALYZE")
        self.db.commit()
        self.cursor.execute("VACUUM")
        self.db.commit()
        self.cursor.close()
            
    
    # "Add" functions
    def addNode(self, object):
        self.numnodes += 1
        self.nodes[object["id"]] = sqlite.Binary(cPickle.dumps(object, cPickle.HIGHEST_PROTOCOL))
        
        if self.numnodes % 250001 >= 250000:
            self.cursor.executemany("insert into \"tmpNodes\" values (?,?)", self.nodes.iteritems() )
            self.db.commit()
            self.nodes.clear()
            del self.nodes
            self.nodes = {}
    
    def addWay(self, object):
        self.numways += 1
        self.ways[object["id"]] = sqlite.Binary(cPickle.dumps(object, cPickle.HIGHEST_PROTOCOL))
        
        if self.numways % 250001 >= 250000:
            self.cursor.executemany("insert into \"tmpWays\" values (?,?)", self.ways.iteritems() )
            self.db.commit()
            self.ways.clear()
            del self.ways
            self.ways = {}
    
    def addRelation(self, object):
        self.numrelations += 1
        self.relations[object["id"]] = sqlite.Binary(cPickle.dumps(object, cPickle.HIGHEST_PROTOCOL))
        
        if self.numrelations % 250001 >= 250000:
            self.cursor.executemany("insert into \"tmpRels\" values (?,?)", self.relations.iteritems() )
            self.db.commit()    
            self.relations.clear()
            del self.relations
            self.relations = {}
    
    # "Delete" functions
    def delWays(self, osm_ids):
        if len(osm_ids) == 0:
            return         
        # Try to circumvent the 999 arguments limit of SQLite    
        numLoop = int(math.ceil(len(osm_ids) / 999.0))
        for x in range(numLoop):
            numIds = min(999,len(osm_ids))
            sql = "DELETE FROM \"tmpWays\" WHERE id IN (%s);" % (','.join(['?' for x in range(numIds)]))
            self.cursor.execute(sql , osm_ids[:numIds])
            # Alternative to test for later: 
            # Only commiting one/two queries using executemany: 
            # [ osm_id[i:i+999] for i in range(0, len(osm_id), 999) ]
            del osm_ids[:numIds]
        self.db.commit()
        self.numways -= self.cursor.rowcount
        
    # "Iteration" functions to browse through all data
    def getNodesIter(self):
        cur = self.db.cursor()
        cur.execute("SELECT object FROM \"tmpNodes\";")
        for row in cur:
            yield cPickle.loads(str(row[0]))
        cur.close()
        
    def getWaysIter(self):
        cur = self.db.cursor()
        cur.execute("SELECT object FROM \"tmpWays\";")
        for row in cur:
            yield cPickle.loads(str(row[0]))
        cur.close()
        
    def getRelationsIter(self):
        cur = self.db.cursor()
        cur.execute("SELECT object FROM \"tmpRels\";")
        for row in cur:
            yield cPickle.loads(str(row[0]))
        cur.close()
        
    # Count data length
    def getNumNodes(self):
        return self.numnodes
    def getNumWays(self):
        return self.numways
    def getNumRelations(self):
        return self.numrelations
    
    # "Get" functions
    def _get(self, sql, osm_id):
        cur = self.db.cursor()  
        try:
            cur.execute(sql, [osm_id])
            row = cur.fetchone()
            cur.close()           
            if row is not None:
                return cPickle.loads(str(row[0]))
            else:
                return None
        except sqlite.Error, e:
            cur.close()
            return None
    
    def getNode(self, osm_id):
        return self._get("SELECT object FROM \"tmpNodes\" WHERE id=?;", osm_id)
        
    def getWay(self, osm_id):
        return self._get("SELECT object FROM \"tmpWays\" WHERE id=?;", osm_id)
        
    def getRelation(self, osm_id):
        return self._get("SELECT object FROM \"tmpRels\" WHERE id=?;", osm_id)

        
