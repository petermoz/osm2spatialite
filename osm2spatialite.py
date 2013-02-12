#!/usr/bin/env python
#
#  osm2spatialite
#  Copyright (C) 2010 Daniel Sabo
#
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


#from guppy import hpy
#hp = hpy()

import sys, os.path
import platform
import copy
import array
import ctypes.util
import OSMXMLParser, OSMMemStore, OSMSQLiteStore

# The following is a hack to avoid unicode errors when printing errors:
import sys
import codecs
sys.stdout = codecs.getwriter('utf8')(sys.stdout)

try:
    import OSMPBFParser
except:
    OSMPBFParser = None

# The following is a huge hack:
try:
    from shapely.geometry import Point,MultiPolygon,Polygon,LineString
except OSError:
    if sys.platform == 'darwin':
        # Trick shapely into loading the KyngChaos GEOS
        ctypes.util.find_library_base = ctypes.util.find_library

        def override(libname):
            lib = ctypes.util.find_library_base(libname)
            if not lib:
                if libname == "geos_c":
                    libname = "GEOS"
            return ctypes.util.find_library_base(libname)
        ctypes.util.find_library = override
            
        from shapely.geometry import Point,MultiPolygon,Polygon,LineString
            
        ctypes.util.find_library = ctypes.util.find_library_base
        del ctypes.util.find_library_base
    else:
        raise

try:
    # Use the KyngChaos sqlite3 if it's available, otherwise try the standard one
    from pysqlite2 import dbapi2 as sqlite
except ImportError:
    import sqlite3 as sqlite

def reportStatus(s):
    print s

def reportDetailedProgress(progress):
    if "nodes" in progress:
        nodes = progress["nodes"]
    else:
        nodes = 0
        
    if "ways" in progress:
        ways = progress["ways"]
    else:
        nodes = 0
        
    if "relations" in progress:
        relations = progress["relations"]
    else:
        relations = 0
    
    if "filesize" in progress and "filepos" in progress:
        percent = "%6.2f%%" % ((float(progress["filepos"]) / float(progress["filesize"])) * 100)
    else:
        percent = "???.??%"
    
    print "\rParsing OSM File: nodes(%d) ways(%d) relations(%d) (%s) done" % (nodes, ways, relations, percent),
    sys.stdout.flush()

def reportEndParse():
    print

def reportWarning(w):
    print w

def reportError(e):
    print e

def polyWinding(poly):
    """Determine the winding of a non-self intersecting polygon, from http://local.wasp.uwa.edu.au/~pbourke/geometry/clockwise/"""
    a = 0.0
    for i in range(len(poly) - 1):
        a += poly[i][0] * poly[i+1][1] - poly[i+1][0] * poly[i][1]
    #a = a / 2.0
    return bool(a > 0)
        
def composeWay(datastore,way):
    """Compose a line from it's node refs into an array of coordinates"""
    line = []            
    for nodeRef in way["nodes"]:
        node = datastore.getNode(nodeRef)
        if node is not None:
            line.append(node["point"])
        else:
            reportWarning("Way %s is incomplete!" % (str(way["id"])))
            line = None
            break
    if not line:
        reportWarning("Way %s has no nodes!" % (str(way["id"])))
        return None
    elif len(line) <= 1:
        reportWarning("Way %s only one node!" % (str(way["id"])))
        return None
    return line

# not used at the moment
def composeWays(datastore):
    """Compose all ways"""
    incompleteCount = 0
    for way in datastore.getWaysIter():
        line = composeWay(datastore, way)
        if not line:
            reportWarning("Way %s is incomplete!" % (str(way["id"])))
            incompleteCount += 1
        way["line"] = line
    if incompleteCount > 0:
        reportWarning("%s incomplete ways!" % (str(incompleteCount)))

def composeMultipolygons(datastore):
    """Compose the line segments that make up a multipolygon into closed rings"""
    incompleteCount = 0
    
    multipolygons = []
    
    def composeMultipolygon(id,relation):
        outerLines = []
        innerLines = []
        
        for member in relation["members"]:
            if member["type"] == "way":
                way = datastore.getWay(member["ref"])
                if way is not None:
                    if member["role"] == "outer":
                        outerLines.append(way)
                    elif member["role"] == "inner":
                        innerLines.append(way)
                else:
                    return None
        
        name = None
        if "name" in relation["tags"]:
            name = relation["tags"]["name"]
        #print "Composing relation \"%s\" from %d lines" % (name, len(outerLines) + len(innerLines))
        
        def composeLoops(lines):
            endpoints = {}
            for way in lines:
                line = composeWay(datastore, way)
                if line == None:
                    reportWarning("Multipolygon (%d) contains an incomplete way! (%d)" % (id, way["id"]))
                    return None
                start = way["nodes"][0]
                end   = way["nodes"][-1]
            
                for point in [start,end]:
                    if point in endpoints:
                        endpoints[point].append(way)
                    else:
                        endpoints[point] = [way]
                        
            for ways in endpoints.values():
                if len(ways) % 2 != 0:
                    reportWarning("Multipolygon (%d) has an unclosed ring!" % (id))
                    return None
            
            remainingEndpoints = copy.copy(endpoints)
                        
            composedLines = []
            while remainingEndpoints:
                point,ways = remainingEndpoints.items()[0]
                lastWay = ways[0]
                if lastWay["nodes"][0] == point:
                    #line  = ways[0]["line"][:]
                    line  = composeWay(datastore, ways[0])
                    start = ways[0]["nodes"][0]
                    end   = ways[0]["nodes"][-1]
                    del remainingEndpoints[start][0]
                    #del remainingEndpoints[start]
                else:
                    #line  = ways[0]["line"][:]
                    line  = composeWay(datastore, ways[0])
                    line.reverse()
                    start = ways[0]["nodes"][-1]
                    end   = ways[0]["nodes"][0]
                    del remainingEndpoints[start][0]
                    #del remainingEndpoints[start]
                
                while end != start:
                    # Find our next line:
                    ways = endpoints[end]
                    nextWay = None
                    if ways[0] != lastWay:
                        nextWay = ways[0]
                    else:
                        nextWay = ways[1]
                        
                    # find out which end they connect at
                    #nextLine = nextWay["line"][:]
                    nextLine  = composeWay(datastore, nextWay)
                    newEnd = nextWay["nodes"][-1]
                    if nextWay["nodes"][0] != end:
                        # start to start, flip the new line
                        nextLine.reverse()
                        newEnd = nextWay["nodes"][0]
                    line.extend(nextLine[1:])
                    
                    del remainingEndpoints[end][remainingEndpoints[end].index(nextWay)]
                    del remainingEndpoints[end][remainingEndpoints[end].index(lastWay)]
                    if not remainingEndpoints[end]:
                        del remainingEndpoints[end]
                    #del remainingEndpoints[end]
                    
                    end = newEnd
                    lastWay = nextWay
                del remainingEndpoints[end][remainingEndpoints[end].index(lastWay)]
                if not remainingEndpoints[end]:
                    del remainingEndpoints[end]
                
                if line[0] == line[-1]:
                    composedLines.append(line)
                else:
                    reportWarning("Multipolygon (%d) ring is not closed!" % (id))
            return composedLines
     
        outerRings = composeLoops(outerLines)
        innerRings = composeLoops(innerLines)
        
        if outerRings is None:
            return None
        
        if innerRings is None:
            # We can fudge bad inner rings
            innerRings = []
        
        #print "\tComposed",len(outerRings),"outer rings"
        #print "\tComposed",len(innerRings),"inner rings"
        # ----
        
        outerRings.extend(innerRings)
        return outerRings
    
    for relation in datastore.getRelationsIter():
        if "type" in relation["tags"] and (relation["tags"]["type"] == "multipolygon" or relation["tags"]["type"] == "boundary"):
            result = composeMultipolygon(relation["id"],relation)
            if not result:
                name = None
                if "name" in relation["tags"]:
                    name = relation["tags"]["name"]
                reportWarning("Relation \"%s\" (%d) is incomplete!" % (name,relation["id"]))
                incompleteCount += 1
            else:
                multipolygons.append(relation)
                relation["composed"] = result
                
    if incompleteCount:
        print incompleteCount,"incomplete relations!"
    
    return multipolygons

def shapelyPolygonizeMultipolygons(mpolys):
    """Determine the nesting of multipolygon rings and build a Shapely multipolygon from them"""
    result = []
        
    for mpoly_obj in mpolys:
        mpoly = mpoly_obj["composed"]
        polyTree = {}
        
        # For each ring, is it inside another ring?
        polyList = []
        polyMap = {}
        for ring in mpoly:
            poly = Polygon(ring)
            polyMap[poly] = ring
            polyList.append(poly)
        nextPass = []
        
        while polyList:
            for poly in polyList:
                withins = []
                for tpoly in polyList:
                    if tpoly != poly and tpoly.contains(poly):
                        withins.append(tpoly)
                        
                # If a polygon is within more than one other polygon it must be nested, we'll have to do another pass to place it
                if len(withins) == 0:
                    if not poly in polyTree:
                        polyTree[poly] = []
                elif len(withins) == 1:
                    if withins[0] in polyTree:
                        polyTree[withins[0]].append(poly)
                    else:
                        polyTree[withins[0]] = [poly]
                else:
                    nextPass.append(poly)
            polyList = nextPass
            nextPass = []
        
        mpolyList = []
        for poly,inner in polyTree.items():
            mlist = [poly.exterior.coords,[]]
             # Winding: This shouldn't be needed, but mapnik makes assumptions about winding
            outerWinding = polyWinding(polyMap[poly])
            for i in inner:
                innerWinding = polyWinding(polyMap[i])
                coords = polyMap[i][:]
                if outerWinding == innerWinding:
                    coords.reverse()
                mlist[1].append(coords)
            mpolyList.append(mlist)
        #FIXME: Not sure if this is a worthwhile optimization
        del mpoly_obj["composed"]
        mpoly_obj["shape"] = MultiPolygon(mpolyList)

class AreaColector():
    """Find lines that represent valid simple areas"""
    def __init__(self, areaTags):
        """areaTags: A dict of tags that indicate possible areas, e.g.
        {
         "amenity":["parking"],
         "leisure":["park","playground"],
         "landuse": None # None acts as a wildcard
        }
        """
        self.areaTags = areaTags
        self.areas = []
    
    def testElement(self, type, object):
        """type: A string representing the type of object being tested
        object: the object"""
        if type == "way" and object["nodes"]:
            # Is it closed?
            if object["nodes"][0] == object["nodes"][-1] and len(object["nodes"]) > 2:
                for key in self.areaTags.keys():
                    # Check if it has an area style tag
                    if key in object["tags"]:
                        if self.areaTags[key] is None or object["tags"][key] in self.areaTags[key]:
                            self.areas.append(object)
                            break
        return object

class CopyTagValue():
    def __init__(self, fromtag, totag):
        self.fromtag = fromtag
        self.totag   = totag
    
    def testElement(self, type, object):
        if self.fromtag in object["tags"]:
            object["tags"][self.totag] = object["tags"][self.fromtag]
        return object

def initializeSqlite(db, tags):
    """Initialized an empty SpatiaLite database"""
    cur = db.cursor()
    
    tableType = "\" TEXT, \""
    tags = "\"" + tableType.join(tags) + "\" TEXT"
    
    # While it would be better to call the init script, we have no way to locate it on random systems
    #with open('/Library/Frameworks/SQLite3.framework/Resources/init_spatialite.sql') as file:
    #    cur.executescript(file.read())
    cur.execute("SELECT InitSpatialMetaData()")
    
    #ver = map(int, cur.execute("select spatialite_version()").fetchone()[0].split("."))
    column_count = len(cur.execute("PRAGMA table_info(spatial_ref_sys)").fetchall())
    
    if column_count == 6:
        srs = [
          [4326, "epsg", 4326, "WGS 84", "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs","""GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]"""],
          [900913, "spatialreference.org", 900913,
          "Popular Visualisation CRS / Mercator (deprecated)", "+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +units=m +k=1.0 +nadgrids=@null +no_defs",
          """PROJCS["WGS84 / Simple Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS_1984", 6378137.0, 298.257223563]],PRIMEM["Greenwich", 0.0],UNIT["degree", 0.017453292519943295],AXIS["Longitude", EAST],AXIS["Latitude", NORTH]],PROJECTION["Mercator_1SP_Google"],PARAMETER["latitude_of_origin", 0.0],PARAMETER["central_meridian", 0.0],PARAMETER["scale_factor", 1.0],PARAMETER["false_easting", 0.0],PARAMETER["false_northing", 0.0],UNIT["m", 1.0],AXIS["x", EAST],AXIS["y", NORTH],AUTHORITY["EPSG","900913"]]"""
          ],    
         ]
        cur.executemany("insert or ignore into spatial_ref_sys values (?,?,?,?,?,?)", srs)
    else:        
        srs = [
        [4326, "epsg", 4326, "WGS 84", "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs"],
        [900913, "spatialreference.org", 900913, "Popular Visualisation CRS / Mercator (deprecated)", "+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +units=m +k=1.0 +nadgrids=@null +no_defs"]
        ]
        cur.executemany("INSERT OR IGNORE INTO spatial_ref_sys VALUES (?,?,?,?,?)", srs)
        
    initSql = """CREATE TABLE "world_polygon" ("osm_id" INTEGER, "osm_type" VCHAR(1), %(tagColumns)s);
    CREATE TABLE "world_line" ("osm_id" INTEGER, %(tagColumns)s);
    CREATE TABLE "world_point" ("osm_id" INTEGER, %(tagColumns)s);
    CREATE TABLE "world_roads" ("osm_id" INTEGER, "osm_type" VCHAR(1), %(tagColumns)s);
    SELECT AddGeometryColumn('world_polygon', 'way', 4326, 'MULTIPOLYGON', 2);
    SELECT AddGeometryColumn('world_line', 'way', 4326, 'LINESTRING', 2);
    SELECT AddGeometryColumn('world_point', 'way', 4326, 'POINT', 2);
    SELECT AddGeometryColumn('world_roads', 'way', 4326, 'GEOMETRYCOLLECTION', 2);
    """ % {"tagColumns": tags}
    cur.executescript(initSql)
    
    # This doesn't seem like it provides much of speed increase
    #cur.execute("PRAGMA synchronous=OFF")
    #cur.execute("PRAGMA journal_mode=OFF")
    
    return db

def writeMpolysToSQLite(db, mpolys, tags):    
    shapelyPolygonizeMultipolygons(mpolys)
    
    cur = db.cursor() 
    for mpoly in mpolys:
        cur.execute("INSERT INTO world_polygon(osm_id,osm_type,way) VALUES ((?),'R',GeomFromWKB((?),4326))", [mpoly["id"],sqlite.Binary(mpoly["shape"].wkb)])
        rowid = cur.lastrowid
        for tag in tags:
            if tag in mpoly["tags"]:
                sql = "UPDATE world_polygon SET \"%s\" = ? WHERE rowid == (?)" % (tag)
                cur.execute(sql, [mpoly["tags"][tag], rowid])
    cur.close()
    
def writeSimpleAreasToSQLite(db, datastore, ac, tags):    
    cur = db.cursor()
    for area in ac.areas:
        line = composeWay(datastore, area)
        if not line or not area["tags"]:
            continue
        mpoly = MultiPolygon([[line,[]]])
        cur.execute("INSERT INTO world_polygon(osm_id,osm_type,way) VALUES ((?),'W',GeomFromWKB((?),4326))", [area["id"], sqlite.Binary(mpoly.wkb)])
        rowid = cur.lastrowid
        sqlTags = []
        sqlTagKeys = []
        for tag in tags:
            if tag in area["tags"]:
                sqlTags.append(tag)
                sqlTagKeys.append(area["tags"][tag])                
        if len(sqlTagKeys) > 0:
            sql = "UPDATE world_polygon SET %s WHERE rowid == (?)" % (','.join(['\"%s\" = ?' % (x) for x in sqlTags]))
            sqlTagKeys.append(rowid)
            cur.execute(sql, sqlTagKeys)
    cur.close()

def writeLinesToSQLite(db, datastore, tags):    
    cur = db.cursor()  
    for way in datastore.getWaysIter():
        line = composeWay(datastore, way)
        if not way["tags"] or not line:
            continue
        linestring = LineString(line)
        cur.execute("INSERT INTO world_line(osm_id,way) VALUES ((?),GeomFromWKB((?),4326))", [way["id"],sqlite.Binary(linestring.wkb)])
        rowid = cur.lastrowid
        sqlTags = []
        sqlTagKeys = []
        for tag in tags:
            if tag in way["tags"]:
                sqlTags.append(tag)
                sqlTagKeys.append(way["tags"][tag])    
        if len(sqlTagKeys) > 0:
            sql = "UPDATE world_line SET %s WHERE rowid == (?)" % (','.join(['\"%s\" = ?' % (x) for x in sqlTags]))
            sqlTagKeys.append(rowid)
            cur.execute(sql, sqlTagKeys)
    cur.close()

def writeNodesToSQLite(db, datastore, tags):
    cur = db.cursor()
    for node in datastore.getNodesIter():
        if not node["tags"]:
            continue
        point = Point(node["point"])
        cur.execute("INSERT INTO world_point(osm_id,way) VALUES ((?),GeomFromWKB((?),4326))", [node["id"],sqlite.Binary(point.wkb)])
        rowid = cur.lastrowid
        sqlTags = []
        sqlTagKeys = []
        for tag in tags:
            if tag in node["tags"]:
                sqlTags.append(tag)
                sqlTagKeys.append(node["tags"][tag])  
        if len(sqlTagKeys) > 0:
            sql = "UPDATE world_point SET %s WHERE rowid == (?)" % (','.join(['\"%s\" = ?' % (x) for x in sqlTags]))
            sqlTagKeys.append(rowid)
            cur.execute(sql, sqlTagKeys)
    cur.close()

def sqlCalculateValues(db):
    cur = db.cursor()
    
    cur.execute("update world_polygon set way_area=Area(way)")
    
    for table in ["polygon", "line", "point", "roads"]:
        cur.execute("update world_%s set z_order=0 where z_order is null" % table)
        cur.execute("update world_%s set z_order=z_order * 10" % table)
        # Road levels
        cur.execute("update world_%s set z_order=z_order + 3 where highway in ('minor','road','unclassified','residential')" % table)
        cur.execute("update world_%s set z_order=z_order + 4 where highway in ('tertiary_link','tertiary')" % table)
        cur.execute("update world_%s set z_order=z_order + 6 where highway in ('secondary_link','secondary')" % table)
        cur.execute("update world_%s set z_order=z_order + 7 where highway in ('primary_link','primary')" % table)
        cur.execute("update world_%s set z_order=z_order + 8 where highway in ('trunk_link','trunk')" % table)
        cur.execute("update world_%s set z_order=z_order + 9 where highway in ('motorway_link','motorway')" % table)
        
        cur.execute("update world_%s set z_order=z_order + 5 where railway is not null" % table)
        cur.execute("update world_%s set z_order=z_order + 10 where bridge in ('true','yes','1')" % table)
        cur.execute("update world_%s set z_order=z_order - 10 where tunnel in ('true','yes','1')" % table)

def sqlDoRoads(db, tags):
    cur = db.cursor()
    tags = "\"" + "\", \"".join(tags) + "\""
    roadTags = "railway <> '' or highway <> '' or boundary='administrative'"
    sql = "insert into world_roads (\"osm_id\", \"osm_type\", %(tagColumns)s, way) select \"osm_id\", 'W', %(tagColumns)s, CastToGeometryCollection(way) from world_line where %(roadTags)s" % {"tagColumns": tags, "roadTags": roadTags}
    cur.execute(sql)
    sql = "insert into world_roads (\"osm_id\", \"osm_type\", %(tagColumns)s, way) select \"osm_id\", \"osm_type\", %(tagColumns)s, CastToGeometryCollection(way) from world_polygon where %(roadTags)s" % {"tagColumns": tags, "roadTags": roadTags}
    cur.execute(sql)

def sqlCreateIndexes(db):
    cur = db.cursor()
    
    for table in ["polygon", "line", "point", "roads"]:
        cur.execute("select CreateSpatialIndex('world_%s','way')" % table)

def parseFile(osmfilename, db, config, verbose=False, useCache=False):
    if osmfilename.endswith(".osm.pbf"):
        if OSMPBFParser:
            osmParser = OSMPBFParser.OSMPBFParser()
        else:
            reportError("Couldn't load PBF modules")
            return
    else:
        osmParser = OSMXMLParser.OSMXMLParser()
    
    if useCache:
        datastore = OSMSQLiteStore.OSMSQLiteStore(db)
    else:
        datastore = OSMMemStore.OSMMemStore()
    
    osmParser.reportProgress = reportDetailedProgress
    osmParser.reportWarning  = reportWarning
    osmParser.reportFinished = reportEndParse
    
    reportStatus("Initialzing SQLite DB...")
    tags = config["tags"]
    initializeSqlite(db, tags)
    
    ac = AreaColector(config["area_tags"])
    
    osmParser.endElementFilters.append(ac)
    osmParser.endElementFilters.append(CopyTagValue(fromtag="layer", totag="z_order"))
    
    reportStatus("Parsing OSM file...")
    osmParser.parse(osmfilename, datastore)
    
    # write temporary memory content to database
    datastore.commit()
    
    #composeWays(osmParser)
    mpolys = composeMultipolygons(datastore)
    
    print datastore.getNumRelations(), "relations"
    print datastore.getNumNodes(), "nodes"
    print datastore.getNumWays(), "ways"
    
    print len(mpolys), "multipolygons"
    print len(ac.areas), "areas"
    
    reportStatus("Writing multipolygons...")
    writeMpolysToSQLite(db, mpolys, tags)
    reportStatus("Writing simple areas...")
    writeSimpleAreasToSQLite(db, datastore, ac, tags)
    
    # Trim areas out of the lines table
    reportStatus("Trim areas out of the lines table...")
    datastore.delWays([area["id"] for area in ac.areas])
    
    reportStatus("Writing lines...")
    writeLinesToSQLite(db, datastore, tags)
    reportStatus("Writing nodes...")
    writeNodesToSQLite(db, datastore, tags)
    reportStatus("Calculating values in SQL...")
    sqlCalculateValues(db)
    reportStatus("Copying values to world_roads...")
    sqlDoRoads(db, tags)
    reportStatus("Creating indexes...")
    sqlCreateIndexes(db)
    
    db.commit()
    datastore.cleanup()

defaultConfig = {
"area_tags": {
 "amenity": None,
 "area":["yes"],
 "boundary": None,
 "building": None, #FIXME: Should exclude building=no?
 "historic": None,
 "leisure": None,
 "landuse": None,
 "military": None,
 "natural": None,
 "sport": None,
 "place": None,
 "waterway": ["dam", "dock"],
 "railway": ["station"],
 "aeroway": ["aerodrome", "terminal", "helipad", "apron"],
 "aerialway": ["station"],
 "power": ["station", "sub_station", "generator"],
},
        
"tags": ['access', 'addr:flats', 'addr:housenumber', 'addr:interpolation', 'admin_level', 'aerialway', 
         'aeroway', 'amenity', 'area', 'barrier', 'bicycle', 'bridge', 'boundary', 'building', 'capital',
         'construction', 'cutting', 'disused', 'ele', 'embankment', 'foot', 'highway', 'historic', 'horse',
         'junction', 'landuse', 'layer', 'learning', 'leisure', 'lock', 'man_made', 'military', 'motorcar',
         'name', 'natural', 'oneway', 'operator', 'poi', 'power', 'power_source', 'place', 'railway', 'ref',
         'religion', 'residence', 'route', 'service', 'shop', 'sport', 'tourism', 'tracktype', 'tunnel',
         'waterway', 'width', 'wood',
         # osm2pgsql calculates these:
         'z_order', 'way_area'],
        
"projection": 4326
}

def readConfig(filename, defaults):
    defaults = copy.deepcopy(defaults)
    if filename:
        execfile(filename, {}, defaults)
    return defaults

def trydb(dbfilename, force=False):
    """ See if SpatiaLite works and create the DB """
    if os.path.exists(dbfilename):
        db = sqlite.connect(dbfilename)
        cur = db.cursor()
        try:
            ok = cur.execute("pragma quick_check").fetchone()[0]
        except sqlite.DatabaseError as ex:
            print "ERROR: %s exists and is not a sqlite database" % dbfilename
            print "ERROR:", ex
            return None
        
        if not force:
            print "ERROR: Database exists %s, use --force to erase it" % dbfilename
            return None
        
        os.unlink(dbfilename)
    
    db = sqlite.connect(dbfilename)
    
    db.enable_load_extension(True)
    
    error = ""
    if platform.system() == 'Linux':
        try:
            db.load_extension("libspatialite.so") 
        except:
            pass    
        error = "ERROR: Cannot find libspatialite.so in path."
    elif platform.system() == 'Windows':
        try:
            db.load_extension("libspatialite-2.dll")
        except:
            pass
        error = "ERROR: Cannot find libspatialite-2.dll in path."
    
    cur = db.cursor()
    
    try:
        version = cur.execute("select spatialite_version()").fetchall()[0]
    except sqlite.DatabaseError as ex:
        print "ERROR: SQLite module does not support SpatiaLite"
        return None
    
    return db

def main():
    import getopt

    def print_usage():
        print "%s <options> DBFILE OSMFILE" % sys.argv[0]
        print
        print "DBFILE              the SpatiaLite file to write to"
        print "OSMFILE             the osm file to import"
        print
        print "options:"
        print " -h, --help         display this message"
        print "     --force        force overwrite of existing data"
        print " -v, --verbose      be verbose"
        print " -c, --config       config python file to read"
        print "     --cache        cache intermediate data to disk"

    try:
        (args, files) = getopt.getopt(sys.argv[1:], 'vc:h', ["force", "verbose", "config", "help", "cache"])
    except getopt.GetoptError as ex:
        print ex
        return
    args = dict(args)


    if "-h" in args or "--help" in args:
        print_usage()
        return

    if len(files) != 2:
        print "Wrong number of file arguments"
        print_usage()
        return

    force = "--force" in args
    verbose = "-v" in args or "--verbose" in args

    configFile = None
    if "-c" in args:
        configFile = args["-c"]    
    if "--config" in args:
        configFile = args["--config"]

    useCache = False
    if "--cache" in args:
        useCache = True

    dbfilename = files[0]
    osmfilename = files[1]
    
    if configFile:
        config = readConfig(configFile, defaultConfig)
    else:
        config = defaultConfig
        
    db = trydb(dbfilename, force)

    if db:
        print u"Importing %s" % osmfilename
        parseFile(osmfilename, db, config=config, verbose=verbose, useCache=useCache)

if __name__ == "__main__":
    main()
