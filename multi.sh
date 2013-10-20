nick=YOURNICKHERE
oldip=x.x.x.x

for i in `cat ips`;  do
    sed s/$oldip/$i/ pipeline.py -i
    nohup run-pipeline pipeline.py $nick --concurrent 6 --disable-web-server > $i.log &
	oldip=$i
done

sed s/$oldip/x.x.x.x/ pipeline.py -i
