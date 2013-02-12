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

import xml.sax, xml.sax.handler
import array

class OSMXMLParser(xml.sax.handler.ContentHandler):
    def __init__(self):
        xml.sax.handler.ContentHandler.__init__(self)
        self.endElementFilters = []

    def parse(self, filename, datastore):
        self.datastore = datastore
        f = open(filename)
        try:
            xml.sax.parse(f, self)
        finally:
            f.close()

    def startDocument(self):
        self.currentObject = None
        self.ticker = 0
        self.nodeCount = 0
        self.wayCount = 0
        self.relCount = 0
    
    def reportProgress(self, progress):
        pass
        
    def reportWarning(self, w):
        print w
    
    def reportFinished(self):
        pass
        
    def startElement(self, name, attrs):
        if self.currentObject:
            try:
                if name == "member":
                    member = {
                        "type":intern(str(attrs.getValue("type"))),
                        "ref":int(attrs.getValue("ref")),
                        "role":intern(str(attrs.getValue("role"))),
                    }
                    self.currentObject["members"].append(member)
                elif name == "nd":
                    self.currentObject["nodes"].append(int(attrs.getValue("ref")))
                elif name == "tag":
                    key = intern(str(attrs.getValue("k")))
                    value = attrs.getValue("v")
                    try:
                        value = intern(str(value))
                    except UnicodeEncodeError:
                        pass
                    self.currentObject["tags"][key] = value
            except:
                import traceback
                traceback.print_exc()
                self.reportWarning("Aborting object parse due to exception")
                self.currentObject = None
        elif name == "node":
            try:
                version = int(attrs.getValue("version"))
            except KeyError:
                version = -1
            self.currentObject = {
                "tags":{},
                "point":array.array('d',[float(attrs.getValue("lon")),float(attrs.getValue("lat"))]),
                "id":int(attrs.getValue("id")),
                "version":version
            }
        elif name == "way":
            try:
                version = int(attrs.getValue("version"))
            except KeyError:
                version = -1
            self.currentObject = {
                "tags":{},
                "nodes":[],
                "id":int(attrs.getValue("id")),
                "version":version
            }
        elif name == "relation":
            try:
                version = int(attrs.getValue("version"))
            except KeyError:
                version = -1
            self.currentObject = {
                "tags":{},
                "members":[],
                "id":int(attrs.getValue("id")),
                "version":version
            }
    
    def endElement(self, name):
        if not self.currentObject:
            return
        
        for endFilter in self.endElementFilters:
            self.currentObject = endFilter.testElement(name, self.currentObject)
        
        if name == "node":
            self.datastore.addNode(self.currentObject)
            self.nodeCount += 1
            self.currentObject = None
        elif name == "way":
            self.currentObject["nodes"] = array.array('i', self.currentObject["nodes"])
            self.datastore.addWay(self.currentObject)
            self.wayCount += 1
            self.currentObject = None
        elif name == "relation":
            self.datastore.addRelation(self.currentObject)
            self.relCount += 1
            self.currentObject = None
        
        # Report the status every 1000 objects
        self.ticker += 1
        if self.ticker == 1000:
            self.reportProgress({
                "nodes":self.nodeCount,
                "ways":self.wayCount,
                "relations":self.relCount,
                #"filesize":1,
                #"filepos":0,
                })
            self.ticker = 0
        
    def endDocument(self):
        self.reportFinished()
    
    