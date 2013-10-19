isohunt-grab
=========================

Seesaw script for the Archive Team Isohunt grabbing.
You'll find this project on the Archive Team Warrior (http://tracker.archiveteam.org/isoprey/).


Running without a warrior
-------------------------

To run this outside the warrior, clone this repository and run:

    pip install seesaw
    ./get-wget-lua.sh

then start downloading with:

    run-pipeline pipeline.py YOURNICKNAME

For more options, run:

    run-pipeline --help

Distribution-specific setup
-------------------------

### For Debian:

Be sure to replace `YOURNICKHERE` with your nickname.

    adduser --system --group --shell /bin/bash archiveteam
    apt-get install -y git-core gnutls-dev lua5.1 liblua5.1-0 liblua5.1-0-dev screen
    pip install seesaw
    su -c "cd /home/archiveteam; git clone https://github.com/joepie91/isohunt-grab.git; cd isohunt-grab; ./get-wget-lua.sh" archiveteam
    screen su -c "cd /home/archiveteam/isohunt-grab/; run-pipeline pipeline.py --concurrent 2 --address '127.0.0.1' YOURNICKHERE" archiveteam
    [... ctrl+A D to detach ...]
    
### For CentOS:

    yum -y install gnutls-devel lua-devel
    [... pretty much the same as above ...]
