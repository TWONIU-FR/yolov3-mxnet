#!/usr/bin/env python

import os
import sys
import cv2
from xml.dom.minidom import Document
import pdb


def insertObject(doc, datas,classes):
    obj = doc.createElement('object')
    name = doc.createElement('name')
    name.appendChild(doc.createTextNode(classes[int(datas[-1])]))
    obj.appendChild(name)
    pose = doc.createElement('pose')
    pose.appendChild(doc.createTextNode('Unspecified'))
    obj.appendChild(pose)
    truncated = doc.createElement('truncated')
    truncated.appendChild(doc.createTextNode(str(0)))
    obj.appendChild(truncated)
    difficult = doc.createElement('difficult')
    difficult.appendChild(doc.createTextNode(str(0)))
    obj.appendChild(difficult)
    bndbox = doc.createElement('bndbox')


    
    xmin = doc.createElement('xmin')
    xmin.appendChild(doc.createTextNode(str(int(datas[1]))))
    bndbox.appendChild(xmin)
    
    ymin = doc.createElement('ymin')                
    ymin.appendChild(doc.createTextNode(str(int(datas[2]))))
    bndbox.appendChild(ymin)                

    xmax = doc.createElement('xmax')                
    xmax.appendChild(doc.createTextNode(str(int(datas[3]))))
    bndbox.appendChild(xmax)                

    ymax = doc.createElement('ymax')
    ymax.appendChild(doc.createTextNode(str(int(datas[4]))))
    bndbox.appendChild(ymax)

    obj.appendChild(bndbox)

    return obj



def create(xmlpath,img_name,imgShape,box_list,classes):
	
	
	xmlName = img_name.replace('.jpg', '.xml')
	xmlName = xmlName.replace('.jpeg', '.xml')
	xmlName = xmlName.replace('.png', '.xml')
	f = open(xmlpath + xmlName, "w")
	doc = Document()
    	annotation = doc.createElement('annotation')
	doc.appendChild(annotation)
	foldername = 'traffic'
	folder = doc.createElement('folder')
	folder.appendChild(doc.createTextNode(foldername))
	annotation.appendChild(folder)
	
	filename = doc.createElement('filename')
	filename.appendChild(doc.createTextNode(img_name))
	annotation.appendChild(filename)
	
	path_zl='/jiaotong/'+img_name
	path  = doc.createElement('path')
	path.appendChild(doc.createTextNode(path_zl))
	annotation.appendChild(path)

        source = doc.createElement('source')                
    	database = doc.createElement('database')
    	database.appendChild(doc.createTextNode('XX Database'))
    	source.appendChild(database)
	annotation.appendChild(source)


    	size = doc.createElement('size')
    	width = doc.createElement('width')
    	width.appendChild(doc.createTextNode(str(imgShape[0])))
    	size.appendChild(width)
    	height = doc.createElement('height')
    	height.appendChild(doc.createTextNode(str(imgShape[1])))
    	size.appendChild(height)
    	depth = doc.createElement('depth')
    	depth.appendChild(doc.createTextNode(str(imgShape[2])))
    	size.appendChild(depth)
    	annotation.appendChild(size)

	segmented = doc.createElement('segmented')
    	segmented.appendChild(doc.createTextNode(str(0)))
    	annotation.appendChild(segmented)   
	for bl in box_list:
	    	annotation.appendChild(insertObject(doc, bl,classes))


	try:
                f.write(doc.toprettyxml(indent = '    '))
                f.close()
        except:
                pass















