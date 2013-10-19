import os

newest = 526925991
oldest = 112161930
#newest = 200000000
item_size = 50
per_file = 100000

def mkdir(path):
	try:
		os.makedirs(path)
	except OSError, e:
		pass

fnum = 0
flim = 0
id_ = str(fnum).rjust(7, "0")
mkdir("idlist/%s/%s/%s/%s" % (id_[0], id_[1], id_[2], id_[3]))
f = open("idlist/%s/%s/%s/%s/list_%s.txt" % (id_[0], id_[1], id_[2], id_[3], id_), "w")
for i in xrange(oldest, newest, item_size):
	if flim > per_file:
		f.close()
		fnum += 1
		flim = 0
		id_ = str(fnum).rjust(7, "0")
		mkdir("idlist/%s/%s/%s/%s" % (id_[0], id_[1], id_[2], id_[3]))
		f = open("idlist/%s/%s/%s/%s/list_%s.txt" % (id_[0], id_[1], id_[2], id_[3], id_), "w")
	
	first = i
	last = i + item_size
	
	f.write("%s-%s " % (first, last - 1))
	
	flim += 1
	
f.close()
